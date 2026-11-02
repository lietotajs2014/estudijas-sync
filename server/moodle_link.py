"""E-studiju pieslēgšana: žetona nolasīšana no lietotāja ievades + programmas/grupas noteikšana.

Serveris nekad neredz RTU paroli. Lietotājs pats piesakās estudijās (ar Microsoft MFA)
un iedod mobilās lietotnes žetonu — vai nu tīru žetonu, vai `moodlemobile://token=...` saiti.
"""
from __future__ import annotations

import re
from collections import Counter

from estudijas_sync.auth import decode_launch_token
from estudijas_sync.model import LoginRequired, MoodleError
from estudijas_sync.moodle_api import MoodleAPI
from estudijas_sync.relevance import group_numbers

# RTU programmu/plūsmu kodi: burts + 3 burti + cipars (RMCE0, RDBM0, ...), neobligāti ar grupu: RMCE0-3, RMCE03
PROGRAM_RX = re.compile(r"(?<![^\W\d_])([A-ZĀ-Ž][A-ZĀ-Ž]{3}\d)(?:\s?[-/]\s?(\d{1,2})(?![\d.]\d)|(\d{1,2})(?![\d.]\d))?(?![^\W\d_])")
_TOKEN_RX = re.compile(r"^[A-Za-z0-9]{20,64}$")


class LinkError(ValueError):
    pass


def parse_token_input(text: str, site: str) -> tuple[str, str | None]:
    """Atgriež (token, privatetoken). Pieņem tīru žetonu vai moodlemobile://token=... saiti."""
    text = (text or "").strip()
    if not text:
        raise LinkError("Ievadi žetonu.")
    if "token=" in text:
        try:
            # passport nav zināms, tāpēc paraksta pārbaude tiek izlaista (decode_launch_token to tikai žurnalē)
            return decode_launch_token(text, site, "")
        except MoodleError as e:
            raise LinkError(f"Saiti neizdevās nolasīt: {e}") from e
    if _TOKEN_RX.fullmatch(text):
        return text, None
    raise LinkError("Tas neizskatās pēc e-studiju žetona (32 burti/cipari) vai moodlemobile:// saites.")


def detect_identity(names: list[str]) -> dict:
    """No Moodle grupu (un kursu) nosaukumiem uzmin programmu un grupu.

    Piem. ["RMCE0 3. grupa", "RMCE0-3", "Visi"] → {"program": "RMCE0", "group": "3"}.
    """
    programs: Counter[str] = Counter()
    groups_by_prog: Counter[tuple[str, int]] = Counter()
    loose_groups: Counter[int] = Counter()
    for name in names:
        name = name or ""
        found = PROGRAM_RX.findall(name.upper())
        for code, g1, g2 in found:
            programs[code] += 1
            if g1 or g2:
                groups_by_prog[(code, int(g1 or g2))] += 1
        for g in group_numbers(name):
            loose_groups[g] += 1
    program = programs.most_common(1)[0][0] if programs else ""
    group = ""
    with_prog = [(g, n) for (p, g), n in groups_by_prog.items() if p == program]
    if with_prog:
        group = str(max(with_prog, key=lambda x: x[1])[0])
    elif loose_groups:
        group = str(loose_groups.most_common(1)[0][0])
    return {"program": program, "group": group,
            "program_candidates": [p for p, _ in programs.most_common(5)],
            "group_candidates": sorted({str(g) for (_, g) in groups_by_prog} | {str(g) for g in loose_groups},
                                       key=int)}


def inspect_account(site: str, token: str) -> dict:
    """Pārbauda žetonu un savāc to, kas vajadzīgs programmas/grupas noteikšanai."""
    api = MoodleAPI(site, token)
    try:
        info = api.call("core_webservice_get_site_info")
    except LoginRequired as e:
        raise LinkError("Žetons nav derīgs vai ir beidzies.") from e
    except Exception as e:
        raise LinkError(f"Neizdevās sazināties ar e-studijām: {e}") from e
    userid = info.get("userid")
    courses = []
    group_names: list[str] = []
    try:
        res = api.call("core_course_get_enrolled_courses_by_timeline_classification",
                       classification="inprogress", limit=0, offset=0, sort="fullname")
        courses = [{"id": int(c["id"]), "name": c.get("fullname", ""), "short": c.get("shortname", "")}
                   for c in res.get("courses", [])]
    except MoodleError:
        pass
    for c in courses:
        try:
            g = api.call("core_group_get_course_user_groups", courseid=c["id"], userid=userid)
            c["groups"] = [x.get("name", "") for x in g.get("groups", [])]
            group_names += c["groups"]
        except MoodleError:
            c["groups"] = []
    api.s.close()
    guess = detect_identity(group_names + [c["short"] for c in courses])
    return {"userid": userid, "fullname": info.get("fullname", ""), "courses": courses, **guess}


# ---------------------------------------------------------------- pārlūka sesija (Android / PC)

ALLOWED_COOKIE_DOMAINS = ("rtu.lv", "microsoftonline.com", "microsoft.com", "live.com")
_COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128}$")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def normalize_cookies(raw, site: str) -> list[dict]:
    """Pieņem sīkdatnes no PC programmas (Playwright formāts) vai Android (name/value/domain)
    un atstāj tikai RTU un Microsoft pieteikšanās domēnu sīkdatnes Playwright formātā."""
    if not isinstance(raw, list):
        raise LinkError("Nepareizs sīkdatņu formāts.")
    site_host = re.sub(r"^https?://", "", site).split("/")[0]
    out, seen = [], set()
    for c in raw[:300]:
        if not isinstance(c, dict):
            continue
        name, value = str(c.get("name", "")), str(c.get("value", ""))
        domain = str(c.get("domain") or site_host).strip()
        if not _COOKIE_NAME.match(name) or len(value) > 8192 or not domain:
            continue
        bare = domain.lstrip(".").lower()
        if not any(bare == d or bare.endswith("." + d) for d in ALLOWED_COOKIE_DOMAINS):
            continue
        key = (name, domain, c.get("path") or "/")
        if key in seen:
            continue
        seen.add(key)
        try:
            expires = float(c.get("expires", -1))
        except (TypeError, ValueError):
            expires = -1
        out.append({"name": name, "value": value, "domain": domain, "path": str(c.get("path") or "/"),
                    "expires": expires, "httpOnly": bool(c.get("httpOnly", True)),
                    "secure": bool(c.get("secure", True)), "sameSite": "Lax"})
    if not any(c["name"].startswith("MoodleSession") for c in out):
        raise LinkError("Nav e-studiju sesijas. Vispirms piesakies e-studijās lietotnē/programmā.")
    return out


def inspect_session(site: str, cookies: list[dict]) -> dict:
    """Pārbauda, vai sesija ir derīga, un savāc datus programmas/grupas noteikšanai (bez pārlūka)."""
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = UA
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    try:
        r = s.get(f"{site}/my/", timeout=30, allow_redirects=True)
    except Exception as e:
        raise LinkError(f"Neizdevās sazināties ar e-studijām: {e}") from e
    m = re.search(r'"sesskey":"([A-Za-z0-9]+)"', r.text)
    if not r.url.startswith(site) or "/login/" in r.url or not m:
        raise LinkError("E-studiju sesija vairs nav derīga. Piesakies lietotnē/programmā no jauna un mēģini vēlreiz.")
    sesskey = m.group(1)
    um = re.search(r'data-userid="(\d+)"', r.text)
    nm = re.search(r'class="[^"]*usertext[^"]*"[^>]*>\s*([^<]+?)\s*<', r.text)
    userid = int(um.group(1)) if um else None

    def ajax(method: str, args: dict):
        rr = s.post(f"{site}/lib/ajax/service.php?sesskey={sesskey}&info={method}",
                    json=[{"index": 0, "methodname": method, "args": args}], timeout=30)
        j = rr.json()
        if not isinstance(j, list) or j[0].get("error"):
            raise MoodleError(f"{method} nav pieejams")
        return j[0].get("data")

    courses, group_names = [], []
    try:
        data = ajax("core_course_get_enrolled_courses_by_timeline_classification",
                    {"offset": 0, "limit": 0, "classification": "inprogress", "sort": "fullname"})
        courses = [{"id": int(c["id"]), "name": c.get("fullname", ""), "short": c.get("shortname", ""), "groups": []}
                   for c in (data or {}).get("courses", [])]
    except Exception:
        pass
    if userid:
        for c in courses:
            try:
                g = ajax("core_group_get_course_user_groups", {"courseid": c["id"], "userid": userid})
                c["groups"] = [x.get("name", "") for x in (g or {}).get("groups", [])]
                group_names += c["groups"]
            except Exception:
                break   # ja nav atļauts vienam kursam, nebūs arī pārējiem
    s.close()
    guess = detect_identity(group_names + [c["short"] for c in courses] + [c["name"] for c in courses])
    return {"userid": userid, "fullname": (nm.group(1).strip() if nm else ""), "courses": courses, **guess}
