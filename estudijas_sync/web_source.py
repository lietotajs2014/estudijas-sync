"""Rezerves avots: saglabātā pārlūka sesija (headless Chromium) + lapu nolasīšana.
Izmanto tikai tad, ja estudijās nav pieejams mobilās lietotnes API."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .auth import (_accept_stay_signed_in, is_site_page, launch_context, login_window, restore_cookies,
                   safe_sesskey, save_cookies)
from .config import Config
from .model import (CollectResult, Course, Deadline, FileItem, Link, LoginRequired,
                    MoodleError, TextBlock)
from .textdates import classify_kind, extract_dates
from .progress import NullProgress
from .util import html_to_text, write_atomic

log = logging.getLogger(__name__)
CMID_RE = re.compile(r"[?&]id=(\d+)")


def _cmid_from(el) -> str:
    if el.get("data-id"):
        return str(el["data-id"])
    m = re.search(r"module-(\d+)", el.get("id", ""))
    return m.group(1) if m else ""


def _clean_name(el) -> str:
    if el is None:
        return ""
    for s in el.select(".accesshide, .sr-only, .visually-hidden"):
        s.decompose()
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


class WebSource:
    name = "web"

    def __init__(self, cfg: Config, interactive: bool = True, prog=None):
        self.cfg = cfg
        self.interactive = interactive   # ja sesija beigusies — atvērt redzamu logu pieteikšanās/MFA koda dēļ
        self.prog = prog
        self.site = cfg.site
        self.tz = ZoneInfo(cfg.timezone)
        self.now_naive = datetime.now(self.tz).replace(tzinfo=None)

    # ---------------------------------------------------------------
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._open_headless()
            try:
                self._ensure_session()
            except LoginRequired:
                if not self.interactive:
                    raise
                # Sesija beigusies: atveram redzamu logu, lai var ievadīt paroli un redzēt MFA kodu,
                # tad turpinām neredzami ar jaunajām sīkdatnēm.
                self.ctx.close()
                self.ctx = None
                vis_ctx, _page, _sk = login_window(self._pw, self.cfg, 600, self.prog)
                vis_ctx.close()
                self._open_headless()
                self._ensure_session()
            save_cookies(self.ctx, self.cfg)
        except Exception:
            self.__exit__()
            raise
        return self

    def _open_headless(self) -> None:
        self.ctx = launch_context(self._pw, self.cfg, headless=True)
        restore_cookies(self.ctx, self.cfg)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def __exit__(self, *exc):
        try:
            if getattr(self, "ctx", None):
                save_cookies(self.ctx, self.cfg)
                self.ctx.close()
        finally:
            self._pw.stop()

    def _ensure_session(self) -> None:
        self.page.goto(self.site + "/my/", wait_until="domcontentloaded", timeout=60000)
        for _ in range(25):  # MS SSO bieži pāradresē atpakaļ automātiski
            _accept_stay_signed_in(self.page)
            if is_site_page(self.page.url, self.site):
                sk = safe_sesskey(self.page)
                if sk:
                    self.sesskey = sk
                    return
            self.page.wait_for_timeout(1000)
        raise LoginRequired("Pārlūka sesija beigusies (vajag pieteikties Microsoft kontā no jauna).")

    def _check_login(self, url: str) -> None:
        if "login.microsoftonline.com" in url or "/login/index.php" in url:
            raise LoginRequired("Pārlūka sesija beigusies.")

    def _get(self, url: str, **kw):
        time.sleep(0.15)
        r = self.ctx.request.get(url, timeout=120000, **kw)
        self._check_login(r.url)
        loc = r.headers.get("location", "")
        if loc:
            self._check_login(loc)
        return r

    def soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._get(url).text(), "html.parser")

    def redirect_target(self, url: str) -> str | None:
        r = self._get(url, max_redirects=0)
        loc = r.headers.get("location")
        if loc:
            return urljoin(url, loc)
        m = re.search(r'href="([^"]*pluginfile\.php[^"]+)"', r.text())
        return m.group(1).replace("&amp;", "&") if m else None

    def ajax(self, method: str, args: dict):
        url = f"{self.site}/lib/ajax/service.php?sesskey={self.sesskey}&info={method}"
        r = self.ctx.request.post(url, data=json.dumps([{"index": 0, "methodname": method, "args": args}]),
                                  headers={"Content-Type": "application/json"}, timeout=60000)
        j = r.json()
        if isinstance(j, dict):
            exc = j.get("exception") or {}
            if exc.get("errorcode") in ("servicerequireslogin", "invalidsesskey", "requireloginerror"):
                raise LoginRequired("Pārlūka sesija beigusies.")
            raise MoodleError(f"{method}: {exc.get('message') or j}", exc.get("errorcode"))
        item = j[0]
        if item.get("error"):
            exc = item.get("exception") or {}
            if exc.get("errorcode") in ("servicerequireslogin", "invalidsesskey"):
                raise LoginRequired("Pārlūka sesija beigusies.")
            raise MoodleError(f"{method}: {exc.get('message')}", exc.get("errorcode"))
        return item.get("data")

    # ---------------------------------------------------------------
    def site_info(self) -> dict:
        try:
            info = self.page.evaluate("""() => {
                const u = document.querySelector('.usermenu .usertext, .userbutton .usertext, .usermenu .login');
                const d = document.querySelector('[data-userid]');
                return {fullname: u ? u.textContent.trim() : '', userid: d ? d.dataset.userid : null};
            }""")
        except Exception:
            info = {}
        return {"fullname": info.get("fullname", ""), "userid": info.get("userid")}

    def courses(self) -> list[Course]:
        data = self.ajax("core_course_get_enrolled_courses_by_timeline_classification",
                         {"offset": 0, "limit": 0, "classification": "inprogress", "sort": "fullname"})
        return [Course(int(c["id"]), c.get("shortname", ""), c.get("fullname", ""),
                       c.get("viewurl") or f"{self.site}/course/view.php?id={c['id']}")
                for c in data.get("courses", [])]

    def collect(self, courses: list[Course], prog=None) -> CollectResult:
        prog = prog or NullProgress()
        res = CollectResult()
        prog.start("Nolasa estudijas", len(courses) + 1)
        for c in courses:
            prog.label(c.label)
            try:
                self._course(c, res)
            except LoginRequired:
                raise
            except Exception as e:
                log.exception(c.fullname)
                res.warnings.append(f"{c.label}: {e}")
            prog.advance(c.label)
        prog.label("kalendārs")
        try:
            self._calendar(courses, res)
        except LoginRequired:
            raise
        except Exception as e:
            log.exception("calendar")
            res.warnings.append(f"kalendārs: {e}")
        prog.advance("kalendārs")
        prog.finish(f"{len(courses)} kursi, {len(res.files)} faili, {len(res.deadlines)} termiņi")
        return res

    # ---------------------------------------------------------------
    def _parse_sections(self, soup: BeautifulSoup) -> list[dict]:
        out = []
        for i, li in enumerate(soup.select("li.section, li.course-section")):
            num = li.get("data-number") or li.get("data-sectionnum")
            if num is None:
                m = re.search(r"section-(\d+)", li.get("id", ""))
                num = m.group(1) if m else i
            name_el = li.select_one(".sectionname, h3.section-title, h3")
            name = li.get("data-sectionname") or _clean_name(name_el) or f"Sadaļa {num}"
            summ = li.select_one(".summarytext, .summary")
            acts = []
            for a in li.select("li.activity"):
                modtype = next((c[8:] for c in a.get("class", []) if c.startswith("modtype_")), "")
                link = a.select_one("a.aalink, .activityname a, .activityinstance a")
                aname = _clean_name(a.select_one(".instancename") or link)
                text_el = a.select_one(".activity-altcontent, .contentwithoutlink, .description, .activity-description")
                acts.append({"cmid": _cmid_from(a), "modtype": modtype, "name": aname,
                             "url": urljoin(self.site, link["href"]) if link and link.get("href") else "",
                             "text": html_to_text(str(text_el)) if text_el else ""})
            out.append({"num": int(num), "name": name.strip(),
                        "summary": html_to_text(str(summ)) if summ else "", "acts": acts})
        return out

    def _course(self, c: Course, res: CollectResult) -> None:
        soup = self.soup(c.url)
        sections = self._parse_sections(soup)
        if sections and not any(s["acts"] for s in sections):
            # "Viena sadaļa lapā" — ielādē katru sadaļu atsevišķi
            links = {urljoin(self.site, a["href"]) for a in soup.select(
                'a[href*="course/section.php"], a[href*="course/view.php"][href*="section="]')}
            sections = []
            for u in sorted(links):
                sections += [s for s in self._parse_sections(self.soup(u)) if s["acts"]]
        seen: set[str] = set()
        first_forum = True
        for sec in sections:
            if sec["summary"]:
                res.texts.append(TextBlock(c.id, sec["name"], sec["summary"], c.url, "sadaļa"))
            for a in sec["acts"]:
                if a["cmid"] in seen:
                    continue
                seen.add(a["cmid"])
                try:
                    self._activity(c, sec, a, res, first_forum)
                except LoginRequired:
                    raise
                except Exception as e:
                    log.info("%s / %s: %s", c.label, a["name"], e)
                    res.warnings.append(f"{c.label} / {a['name']}: {e}")
                if a["modtype"] == "forum":
                    first_forum = False

    def _activity(self, c: Course, sec: dict, a: dict, res: CollectResult, first_forum: bool) -> None:
        mt, cmid, name, url = a["modtype"], a["cmid"], a["name"], a["url"]
        if mt == "label":
            if a["text"]:
                res.texts.append(TextBlock(c.id, sec["name"], a["text"], c.url, "sadaļa"))
            return
        if a["text"]:
            res.texts.append(TextBlock(c.id, f"{sec['name']} — {name}", a["text"], url, "sadaļa"))
        if not cmid:
            return
        if mt == "resource":
            target = self.redirect_target(f"{self.site}/mod/resource/view.php?id={cmid}&redirect=1")
            if target and "pluginfile.php" in target:
                fn = unquote(urlparse(target).path.rsplit("/", 1)[-1]) or f"{name}"
                res.files.append(FileItem(c.id, sec["name"], sec["num"], name, "resource", fn,
                                          target.split("?")[0], target.split("?")[0], cmid, page_url=url))
        elif mt == "folder":
            soup = self.soup(url)
            for link in soup.select('a[href*="pluginfile.php"][href*="mod_folder"]'):
                href = urljoin(self.site, link["href"]).split("?")[0]
                path = unquote(urlparse(href).path)
                rest = path.split("/mod_folder/content/", 1)[-1].split("/")[1:]  # bez revīzijas nr.
                if not rest:
                    continue
                res.files.append(FileItem(c.id, sec["name"], sec["num"], name, "folder", rest[-1], href, href,
                                          cmid, subpath="/".join(rest[:-1]), page_url=url))
        elif mt == "assign":
            self._assign(c, cmid, name, url, res, sec["name"])
        elif mt == "quiz":
            soup = self.soup(url)
            dates = self._activity_dates(soup)
            due = dates.get("due") or dates.get("open")
            attempted = soup.select_one(".quizattemptsummary, table.quizattemptsummary") is not None
            if due:
                res.add_deadline(Deadline(f"cm-{cmid}", c.id, classify_kind(name, "Tests"), name, due,
                                          start=dates.get("open") if dates.get("due") else None, url=url,
                                          status="izpildīts" if attempted else "nav izpildīts",
                                          details=self._intro_text(soup)[:3000], section=sec["name"]))
        elif mt == "page":
            soup = self.soup(url)
            main = soup.select_one("div.box.generalbox, [role=main] .generalbox, #region-main")
            if main:
                res.texts.append(TextBlock(c.id, name, html_to_text(str(main)), url, "lapa"))
        elif mt == "url":
            target = self.redirect_target(f"{self.site}/mod/url/view.php?id={cmid}&redirect=1")
            res.links.append(Link(c.id, sec["name"], name, target or url))
        elif mt == "forum":
            if first_forum or re.search(r"paziņoj|announce|jaunum|news", name, re.I):
                self._forum(c, url, res)

    def _intro_text(self, soup: BeautifulSoup) -> str:
        el = soup.select_one(".activity-description, #intro, .box.generalbox")
        return html_to_text(str(el)) if el else ""

    def _activity_dates(self, soup: BeautifulSoup) -> dict[str, datetime]:
        box = soup.select_one('[data-region="activity-dates"], .activity-dates')
        out: dict[str, datetime] = {}
        if not box:
            return out
        for div in box.find_all("div"):
            if div.find("div"):
                continue
            t = div.get_text(" ", strip=True)
            dts = extract_dates(t, self.now_naive)
            if not dts:
                continue
            low = t.lower()
            if re.search(r"nogriešan|cut-?off|galīg", low):
                key = "cutoff"
            elif re.search(r"termiņ|due|jāiesniedz|aizvēr|aizver|clos|slēg|beidz", low):
                key = "due"
            elif re.search(r"atvēr|atver|open|pieejam|allow|sāk", low):
                key = "open"
            else:
                key = "other"
            out.setdefault(key, dts[0][0].replace(tzinfo=self.tz))
        return out

    def _assign(self, c: Course, cmid: str, name: str, url: str, res: CollectResult, section: str = "") -> None:
        soup = self.soup(url)
        kind = classify_kind(name, "Uzdevums")
        intro = self._intro_text(soup)
        dates = self._activity_dates(soup)
        for link in soup.select('a[href*="pluginfile.php"]'):
            href = urljoin(self.site, link["href"])
            if "introattachment" not in href and "/intro/" not in href:
                continue
            href = href.split("?")[0]
            fn = unquote(urlparse(href).path.rsplit("/", 1)[-1])
            res.files.append(FileItem(c.id, section or "Uzdevumi", 0, name, "assign", fn, href, href, cmid,
                                      page_url=url, kind_hint=kind))
        if soup.select_one(".submissionstatussubmitted"):
            status = "iesniegts"
        elif soup.select_one(".submissionstatusdraft"):
            status = "melnraksts (nav iesniegts!)"
        elif soup.select_one(".submissionstatustable, .submissionsummarytable"):
            status = "nav iesniegts"
        else:
            status = None
        lines = [f"{k}: {v:%d.%m.%Y %H:%M}" for k, v in
                 (("Atveras", dates.get("open")), ("Termiņš", dates.get("due")),
                  ("Galīgais termiņš", dates.get("cutoff"))) if v]
        res.texts.append(TextBlock(c.id, name, "\n".join(lines + ["", intro]).strip(), url, "uzdevums"))
        if dates.get("due"):
            res.add_deadline(Deadline(f"cm-{cmid}", c.id, kind, name, dates["due"], start=dates.get("open"),
                                      url=url, status=status, details=intro[:5000], section=section))

    def _forum(self, c: Course, url: str, res: CollectResult) -> None:
        soup = self.soup(url)
        links = []
        for a in soup.select('a[href*="discuss.php?d="]'):
            href = urljoin(self.site, a["href"]).split("#")[0]
            if href not in links:
                links.append(href)
        for href in links[:5]:
            ds = self.soup(href)
            title = _clean_name(ds.select_one("h2, h3.discussionname, .discussionname")) or "Paziņojums"
            post = ds.select_one(".post-content-container, .posting, .content .text_to_html")
            if post:
                res.texts.append(TextBlock(c.id, title, html_to_text(str(post)), href, "paziņojums"))

    def _calendar(self, courses: list[Course], res: CollectResult) -> None:
        ids = {c.id for c in courses}
        now = int(time.time())
        events, after = [], 0
        for _ in range(6):
            args = {"timesortfrom": now - 14 * 86400, "timesortto": now + self.cfg.lookahead_days * 86400,
                    "limitnum": 50, "limittononsuspendedevents": True}
            if after:
                args["aftereventid"] = after
            evs = (self.ajax("core_calendar_get_action_events_by_timesort", args) or {}).get("events", [])
            for e in evs:
                e["_action"] = True
            events += evs
            if len(evs) < 50:
                break
            after = evs[-1]["id"]
        try:
            events += (self.ajax("core_calendar_get_calendar_upcoming_view",
                                 {"courseid": 1, "categoryid": 0}) or {}).get("events", [])
        except MoodleError as e:
            log.info("upcoming view: %s", e)
        for e in events:
            cid = int((e.get("course") or {}).get("id") or e.get("courseid") or 0)
            if ids and cid not in ids and cid > 1:
                continue
            mod = e.get("modulename") or ""
            url = e.get("url") or e.get("viewurl") or ""
            ts = e.get("timesort") or e.get("timestart")
            if not ts:
                continue
            dt = datetime.fromtimestamp(int(ts), self.tz)
            name = (e.get("activityname") or e.get("name") or "").strip()
            m = CMID_RE.search(url) if "/mod/" in url else None
            if m and mod:
                uid = f"cm-{m.group(1)}"
                if e.get("eventtype") == "open":
                    if uid in res.deadlines and not res.deadlines[uid].start:
                        res.deadlines[uid].start = dt
                    continue
                status = None
                if e.get("_action"):
                    status = "nav iesniegts" if mod == "assign" else "nav izpildīts"
                res.add_deadline(Deadline(uid, cid, classify_kind(name, "Tests" if mod == "quiz" else "Uzdevums"),
                                          name, dt, url=url, status=status))
            else:
                dur = int(e.get("timeduration") or 0)
                desc = html_to_text(e.get("description"))
                res.add_deadline(Deadline(f"event-{e.get('id')}", cid, classify_kind(f"{name} {desc}", "Notikums"),
                                          name, dt + timedelta(seconds=dur) if dur else dt,
                                          start=dt if dur else None, url=url, details=desc[:3000]))

    # ---------------------------------------------------------------
    def download(self, item: FileItem, dest: Path, on_bytes=None) -> int:
        r = self._get(item.url + ("&" if "?" in item.url else "?") + "forcedownload=1")
        if r.status >= 400:
            raise MoodleError(f"HTTP {r.status}")
        body = r.body()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype and b"login" in body[:5000].lower() and not item.filename.lower().endswith((".html", ".htm")):
            raise LoginRequired("Pārlūka sesija beigusies.")
        write_atomic(dest, body)
        if on_bytes:
            on_bytes(len(body))
        return len(body)
