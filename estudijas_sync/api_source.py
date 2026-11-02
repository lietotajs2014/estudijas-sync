"""Avots, kas strādā caur oficiālo Moodle API (mobilās lietotnes žetons)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config
from .model import (CollectResult, Course, Deadline, FileItem, Link, LoginRequired,
                    MoodleError, TextBlock)
from .moodle_api import MoodleAPI
from .progress import NullProgress
from .textdates import classify_kind
from .util import html_to_text, write_stream_atomic

log = logging.getLogger(__name__)

STATUS_LV = {"submitted": "iesniegts", "draft": "melnraksts (nav iesniegts!)",
             "new": "nav iesniegts", "reopened": "atvērts atkārtoti", "": "nav iesniegts"}


class ApiSource:
    name = "api"

    def __init__(self, cfg: Config, auth: dict):
        self.cfg = cfg
        self.site = cfg.site
        self.tz = ZoneInfo(cfg.timezone)
        self.api = MoodleAPI(cfg.site, auth["token"])
        self.userid: int | None = auth.get("userid")
        self.cm_section: dict[int, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.api.s.close()

    def ts(self, t) -> datetime | None:
        return datetime.fromtimestamp(int(t), self.tz) if t else None

    # ---------------------------------------------------------------
    def site_info(self) -> dict:
        info = self.api.call("core_webservice_get_site_info")
        self.userid = info.get("userid")
        return {"fullname": info.get("fullname", ""), "userid": self.userid}

    def courses(self) -> list[Course]:
        res = self.api.call("core_course_get_enrolled_courses_by_timeline_classification",
                            classification="inprogress", limit=0, offset=0, sort="fullname")
        return [Course(int(c["id"]), c.get("shortname", ""), c.get("fullname", ""),
                       c.get("viewurl") or f"{self.site}/course/view.php?id={c['id']}")
                for c in res.get("courses", [])]

    def collect(self, courses: list[Course], prog=None) -> CollectResult:
        prog = prog or NullProgress()
        res = CollectResult()
        ids = [c.id for c in courses]
        global_steps = (("pasniedzēji", self._teachers), ("uzdevumi", self._assignments), ("testi", self._quizzes),
                        ("kalendārs", self._calendar), ("paziņojumi", self._forums))
        prog.start("Nolasa estudijas", len(courses) + len(global_steps))
        for c in courses:
            prog.label(c.label)
            for step in (self._contents, self._groups):
                try:
                    step(c, res)
                except LoginRequired:
                    raise
                except Exception as e:
                    log.exception("%s: %s", c.fullname, step.__name__)
                    res.warnings.append(f"{c.label}: {step.__name__.strip('_')} — {e}")
            prog.advance(c.label)
        for label, step in global_steps:
            prog.label(label)
            try:
                if ids:
                    step(ids, res)
            except LoginRequired:
                raise
            except Exception as e:
                log.exception(step.__name__)
                res.warnings.append(f"{label}: {e}")
            prog.advance(label)
        prog.finish(f"{len(courses)} kursi, {len(res.files)} faili, {len(res.deadlines)} termiņi")
        return res

    # ---------------------------------------------------------------
    def _teachers(self, ids: list[int], res: CollectResult) -> None:
        data = self.api.call("core_course_get_courses_by_field", field="ids", value=",".join(map(str, ids)))
        contacts: dict[int, list[dict]] = {}
        uids: set[int] = set()
        for c in data.get("courses", []):
            lst = [{"id": int(x["id"]), "name": x.get("fullname", "")} for x in c.get("contacts", []) or []]
            contacts[int(c["id"])] = lst
            uids.update(x["id"] for x in lst)
        users: dict[int, dict] = {}
        if uids:
            try:
                for u in self.api.call("core_user_get_users_by_field", field="id", values=sorted(uids)):
                    users[int(u["id"])] = u
            except MoodleError as e:
                log.info("Pasniedzēju profili: %s", e)
        for cid, lst in contacts.items():
            res.teachers[cid] = [{
                "name": users.get(x["id"], {}).get("fullname") or x["name"],
                "email": users.get(x["id"], {}).get("email", ""),
                "department": users.get(x["id"], {}).get("department", ""),
                "url": f"{self.site}/user/view.php?id={x['id']}&course={cid}",
                "role": "pasniedzējs"} for x in lst]

    def _groups(self, c: Course, res: CollectResult) -> None:
        if not self.userid:
            return
        try:
            g = self.api.call("core_group_get_course_user_groups", courseid=c.id, userid=self.userid)
        except MoodleError:
            return
        res.groups[c.id] = [x.get("name", "") for x in g.get("groups", [])]

    def _contents(self, c: Course, res: CollectResult) -> None:
        sections = self.api.call("core_course_get_contents", courseid=c.id)
        for idx, sec in enumerate(sections):
            secnum = int(sec.get("section", idx) or 0)
            secname = (sec.get("name") or f"Sadaļa {secnum}").strip()
            summary = html_to_text(sec.get("summary"))
            if summary:
                res.texts.append(TextBlock(c.id, secname, summary, c.url, "sadaļa"))
            for m in sec.get("modules", []):
                if m.get("uservisible") is False:
                    continue
                mod, mname = m.get("modname", ""), (m.get("name") or "").strip()
                self.cm_section[int(m.get("id", 0))] = secname
                murl = m.get("url") or ""
                contents = m.get("contents") or []
                desc = html_to_text(m.get("description"))
                if mod == "label":
                    if desc:
                        res.texts.append(TextBlock(c.id, secname, desc, c.url, "sadaļa"))
                    continue
                if mod in ("resource", "folder"):
                    for f in contents:
                        if f.get("type") != "file":
                            continue
                        res.files.append(FileItem(
                            course_id=c.id, section=secname, section_num=secnum, module=mname,
                            modtype=mod, filename=f.get("filename", "fails"), url=f["fileurl"],
                            version=str(f.get("timemodified") or f.get("fileurl")), cmid=m.get("id", 0),
                            subpath=(f.get("filepath") or "/").strip("/") if mod == "folder" else "",
                            size=f.get("filesize"), page_url=murl, modified=f.get("timemodified"),
                            created=f.get("timecreated") or f.get("timemodified")))
                    if desc:
                        res.texts.append(TextBlock(c.id, f"{secname} — {mname}", desc, murl, "sadaļa"))
                elif mod == "page":
                    for f in contents:
                        if f.get("type") == "file" and f.get("filename") == "index.html":
                            try:
                                html = self.api.get_file(f["fileurl"]).text
                                res.texts.append(TextBlock(c.id, mname, html_to_text(html), murl, "lapa"))
                            except MoodleError as e:
                                log.info("Lapa %s: %s", mname, e)
                elif mod == "url":
                    for f in contents:
                        if f.get("type") == "url" and f.get("fileurl"):
                            res.links.append(Link(c.id, secname, mname, f["fileurl"]))
                else:
                    if desc and mod not in ("assign", "quiz"):
                        res.texts.append(TextBlock(c.id, f"{secname} — {mname}", desc, murl, "sadaļa"))
                    # Citu aktivitāšu (workshop, lesson, feedback...) datumi, ja Moodle tos dod
                    if mod not in ("assign", "quiz", "forum"):
                        for dd in m.get("dates") or []:
                            label = (dd.get("label") or "").lower()
                            if any(k in label for k in ("due", "close", "termiņ", "aizvēr", "beig")):
                                due = self.ts(dd.get("timestamp"))
                                if due:
                                    res.add_deadline(Deadline(
                                        uid=f"cm-{m.get('id')}", course_id=c.id,
                                        kind=classify_kind(mname, "Uzdevums"), title=mname, due=due, url=murl))

    def _assignments(self, ids: list[int], res: CollectResult) -> None:
        data = self.api.call("mod_assign_get_assignments", courseids=ids)
        for course in data.get("courses", []):
            cid = int(course["id"])
            for a in course.get("assignments", []):
                name = (a.get("name") or "").strip()
                url = f"{self.site}/mod/assign/view.php?id={a['cmid']}"
                sec = self.cm_section.get(int(a["cmid"]), "")
                kind = classify_kind(name, "Uzdevums")
                intro = html_to_text(a.get("intro"))
                due = a.get("duedate") or 0
                lines = []
                if a.get("allowsubmissionsfromdate"):
                    lines.append(f"Iesniegšana no: {self._fmt(a['allowsubmissionsfromdate'])}")
                if due:
                    lines.append(f"Termiņš: {self._fmt(due)}")
                if a.get("cutoffdate"):
                    lines.append(f"Galīgais termiņš (cut-off): {self._fmt(a['cutoffdate'])}")
                res.texts.append(TextBlock(cid, name, "\n".join(lines + ["", intro]).strip(), url, "uzdevums"))
                for att in a.get("introattachments", []) or []:
                    res.files.append(FileItem(
                        course_id=cid, section=sec or "Uzdevumi", section_num=0, module=name, modtype="assign",
                        filename=att.get("filename", "pielikums"), url=att["fileurl"],
                        version=str(att.get("timemodified") or att["fileurl"]), cmid=a["cmid"],
                        size=att.get("filesize"), page_url=url, kind_hint=kind, modified=att.get("timemodified"),
                        created=att.get("timecreated") or att.get("timemodified")))
                if not due:
                    continue
                status = None
                status = self._assign_status(a["id"])
                details = intro[:5000]
                if a.get("cutoffdate"):
                    details = f"Galīgais termiņš: {self._fmt(a['cutoffdate'])}\n{details}"
                res.add_deadline(Deadline(
                    uid=f"cm-{a['cmid']}", course_id=cid, kind=kind, title=name, due=self.ts(due),
                    start=self.ts(a.get("allowsubmissionsfromdate")), url=url, status=status,
                    details=details, section=sec))

    def _assign_status(self, assignid: int) -> str | None:
        try:
            st = self.api.call("mod_assign_get_submission_status", assignid=assignid)
        except MoodleError:
            return None
        la = st.get("lastattempt") or {}
        sub = la.get("submission") or la.get("teamsubmission") or {}
        status = STATUS_LV.get(sub.get("status", ""), sub.get("status"))
        grade = ((st.get("feedback") or {}).get("gradefordisplay") or "").strip()
        if grade:
            status = f"novērtēts: {html_to_text(grade)}"
        return status

    def _quizzes(self, ids: list[int], res: CollectResult) -> None:
        data = self.api.call("mod_quiz_get_quizzes_by_courses", courseids=ids)
        for q in data.get("quizzes", []):
            close, open_ = q.get("timeclose") or 0, q.get("timeopen") or 0
            if not (close or open_):
                continue
            name = (q.get("name") or "").strip()
            details = []
            if open_:
                details.append(f"Atveras: {self._fmt(open_)}")
            if close:
                details.append(f"Aizveras: {self._fmt(close)}")
            if q.get("timelimit"):
                details.append(f"Laika limits: {int(q['timelimit']) // 60} min")
            att = q.get("attempts")
            if att is not None:
                details.append("Mēģinājumi: " + ("neierobežoti" if int(att) == 0 else str(att)))
            details.append(html_to_text(q.get("intro"))[:3000])
            status = None
            try:
                at = self.api.call("mod_quiz_get_user_attempts", quizid=q["id"], status="finished")
                n = len(at.get("attempts", []))
                status = f"izpildīts ({n} mēģ.)" if n else "nav izpildīts"
            except MoodleError:
                pass
            url = f"{self.site}/mod/quiz/view.php?id={q['coursemodule']}"
            res.add_deadline(Deadline(
                uid=f"cm-{q['coursemodule']}", course_id=int(q["course"]),
                kind=classify_kind(name, "Tests"), title=name if close else f"{name} (atveras)",
                due=self.ts(close or open_), start=self.ts(open_) if close else None,
                url=url, status=status, details="\n".join(details).strip(),
                section=self.cm_section.get(int(q["coursemodule"]), "")))

    def _calendar(self, ids: list[int], res: CollectResult) -> None:
        now = int(time.time())
        data = self.api.call("core_calendar_get_calendar_events",
                             events={"courseids": ids},
                             options={"userevents": 1, "siteevents": 1, "timestart": now - self.cfg.lookback_days * 86400,
                                      "timeend": now + self.cfg.lookahead_days * 86400})
        for e in data.get("events", []):
            mod = e.get("modulename") or ""
            if mod in ("assign", "quiz"):
                continue  # jau no precīzākiem avotiem
            if e.get("eventtype") == "open" and mod:
                continue
            name = (e.get("name") or "").strip()
            desc = html_to_text(e.get("description"))
            start = self.ts(e.get("timestart"))
            dur = int(e.get("timeduration") or 0)
            res.add_deadline(Deadline(
                uid=f"event-{e['id']}", course_id=int(e.get("courseid") or 0),
                kind=classify_kind(f"{name} {desc}", "Notikums"), title=name,
                due=start + timedelta(seconds=dur) if dur else start, start=start if dur else None,
                url=e.get("url") or f"{self.site}/calendar/view.php?view=day&time={e.get('timestart')}",
                details=(f"Vieta: {e['location']}\n" if e.get("location") else "") + desc[:3000]))

    def _forums(self, ids: list[int], res: CollectResult) -> None:
        forums = self.api.call("mod_forum_get_forums_by_courses", courseids=ids)
        for f in forums:
            if f.get("type") != "news":
                continue
            try:
                d = self.api.call("mod_forum_get_forum_discussions", forumid=f["id"], page=0, perpage=10)
            except MoodleError:
                try:
                    d = self.api.call("mod_forum_get_forum_discussions_paginated", forumid=f["id"],
                                      sortby="timemodified", sortdirection="DESC", page=0, perpage=10)
                except MoodleError as e:
                    log.info("Forums %s: %s", f.get("name"), e)
                    continue
            for disc in d.get("discussions", []):
                res.texts.append(TextBlock(
                    int(f["course"]), (disc.get("name") or disc.get("subject") or "Paziņojums").strip(),
                    html_to_text(disc.get("message")),
                    f"{self.site}/mod/forum/discuss.php?d={disc.get('discussion')}", "paziņojums",
                    self.ts(disc.get("created") or disc.get("timemodified"))))

    def _fmt(self, t) -> str:
        return self.ts(t).strftime("%d.%m.%Y %H:%M")

    # ---------------------------------------------------------------
    def download(self, item: FileItem, dest: Path, on_bytes=None) -> int:
        def chunks(r):
            for c in r.iter_content(1 << 16):
                if on_bytes:
                    on_bytes(len(c))
                yield c
        with self.api.get_file(item.url, stream=True) as r:
            return write_stream_atomic(dest, chunks(r))
