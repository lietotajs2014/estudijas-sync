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
