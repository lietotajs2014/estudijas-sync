"""Testi bez interneta: python -m pytest tests  (vai python tests/test_all.py)"""
import base64
import hashlib
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ESTUDIJAS_SYNC_HOME"] = tempfile.mkdtemp()

from estudijas_sync.auth import decode_launch_token  # noqa: E402
from estudijas_sync.classify import classify_file, compile_categories  # noqa: E402
from estudijas_sync.config import load_config  # noqa: E402
from estudijas_sync.model import FileItem, TextBlock  # noqa: E402
from estudijas_sync.moodle_api import flatten  # noqa: E402
from estudijas_sync.relevance import MINE, OTHER, Matcher  # noqa: E402
from estudijas_sync.textdates import extract_dates, find_text_deadlines  # noqa: E402
from estudijas_sync.util import html_to_text, sanitize  # noqa: E402

TZ = ZoneInfo("Europe/Riga")
NOW = datetime(2026, 11, 2, 11, 0)


def d(line):
    return [(x[0].strftime("%Y-%m-%d %H:%M"), x[1]) for x in extract_dates(line, NOW)]


def test_dates():
    assert d("MD3 jāiesniedz līdz 12.11. plkst. 23:59") == [("2026-11-12 23:59", True)]
    assert d("KD2 notiks 20. novembrī") == [("2026-11-20 00:00", False)]
    assert d("Tests 2026-11-25 10:00") == [("2026-11-25 10:00", True)]
    assert d("pirmdiena, 2026. gada 3. novembris, 00:00") == [("2026-11-03 00:00", True)]
    assert d("Monday, 3 November 2026, 11:59 PM") == [("2026-11-03 23:59", True)]
    assert d("Eksāmens 15.01. 9:00") == [("2027-01-15 09:00", True)]       # nākamais gads
    assert d("2.1. Uzdevums: aprēķināt") == []                              # numerācija, ne datums
    assert d("termiņš 12.11.2026., KD 20.11.") == [("2026-11-12 00:00", False), ("2026-11-20 00:00", False)]
    assert d("Versija 3.5 un 31.02. nav datums") == []


def test_relevance():
    m = Matcher.build("rmce0", "3", [], [])
    cases = {"KD1 RMCE0 20.11.": MINE, "RMMB0 MD1": OTHER, "RMCE0 1. grupa": OTHER, "RMCE0-3 lab": MINE,
             "1. un 2. grupa": OTHER, "1.–3. grupa": MINE, "grupa 3": MINE, "MD1_RMMB0.pdf": OTHER,
             "RMCE0, RMMB0 KD": MINE, "TEMA1 lekcija": None, "KD visiem": None}
    for t, want in cases.items():
        assert m.evaluate(t) == want, (t, m.evaluate(t))
    auto = Matcher.build("RMCE0", "", [], ["RMCE0 3. grupa"])
    assert auto.groups == {3}


def test_text_deadlines_and_groups():
    texts = [TextBlock(5, "Paziņojums", "Sveiki!\nMD3 jāiesniedz līdz 12.11. plkst. 23:59, bet KD2 notiks 20. novembrī.\n"
                                        "Laboratorijas darbs: 1. grupa 18.11. 10:00, 3. grupa 19.11. 10:00\n"
                                        "RMMB0 kontroldarbs 24.11.", "u", "paziņojums")]
    out = find_text_deadlines(texts, {5: Matcher.build("RMCE0", "3", [], [])}, [], NOW.replace(tzinfo=TZ), TZ, 150)
    got = [(x.kind, x.due.strftime("%d.%m %H:%M"), x.relevance) for x in out]
    assert got == [("MD", "12.11 23:59", None), ("LD", "18.11 10:00", OTHER), ("LD", "19.11 10:00", MINE),
                   ("KD", "20.11 23:59", None), ("KD", "24.11 23:59", OTHER)], got


def test_classify():
    cfg = load_config("t")
    cats = compile_categories(cfg.categories)

    def c(fn, mod="", sec="", mt="resource"):
        return classify_file(FileItem(1, sec, 1, mod, mt, fn, "u", "v"), cats)
    assert c("MD3_uzdevums.pdf") == "Mājas darbi"
    assert c("x.pdf", mod="2. kontroldarbs") == "Kontroldarbi"
    assert c("Lekcija 4.pdf") == "Lekcijas"
    assert c("tema4.pptx") == "Lekcijas"
    assert c("tema4.pdf", sec="Lekciju materiāli") == "Lekcijas"
    assert c("ld2.docx", mod="LD2 apraksts") == "Laboratorijas darbi"
    assert c("noteikumi.pdf") == "Citi"
    assert c("forma.docx", mod="Projekts", mt="assign") == "Uzdevumi"


def test_misc():
    assert list(flatten({"courseids": [1, 2], "options": {"a": True, "b": 3}})) == \
        [("courseids[0]", 1), ("courseids[1]", 2), ("options[a]", 1), ("options[b]", 3)]
    site, passport = "https://estudijas.rtu.lv", "123456789"
    sig = hashlib.md5((site + passport).encode()).hexdigest()
    b64 = base64.b64encode(f"{sig}:::TOKEN123:::PRIV".encode()).decode()
    assert decode_launch_token(f"moodlemobile://token={b64}", site, passport) == ("TOKEN123", "PRIV")
    assert html_to_text("<p>MD1 <b>līdz</b> 12.11.</p><ul><li>a</li><li>b</li></ul>") == "MD1 līdz 12.11.\n\n- a\n- b"
    assert sanitize('Kurss: "Elektro"/1?') == "Kurss_ _Elektro__1_"
    assert sanitize("CON.txt") == "_CON.txt"


# ---------- pilns cikls ar viltotu Moodle API ----------
def fake_api_responses():
    now = int(time.time())
    day = 86400
    fu = "https://estudijas.rtu.lv/webservice/pluginfile.php/1/mod_resource/content/1/"
    return {
        "core_webservice_get_site_info": {"userid": 7, "fullname": "Jānis Bērziņš"},
        "core_course_get_enrolled_courses_by_timeline_classification": {"courses": [
            {"id": 10, "shortname": "EEB201", "fullname": "Elektrotehnikas pamati",
             "viewurl": "https://estudijas.rtu.lv/course/view.php?id=10"}]},
        "core_course_get_contents": [
            {"section": 0, "name": "Vispārīgi", "summary": "<p>KD1 notiks 20.11. plkst. 10:00 aud. 101</p>",
             "modules": [{"id": 100, "modname": "forum", "name": "Paziņojumi"}]},
            {"section": 1, "name": "1. tēma", "summary": "", "modules": [
                {"id": 101, "modname": "resource", "name": "Lekcija 1", "url": "u", "contents": [
                    {"type": "file", "filename": "L1 Omu likums.pptx", "fileurl": fu + "L1.pptx",
                     "timemodified": 111, "filesize": 1000}]},
                {"id": 102, "modname": "folder", "name": "MD materiāli", "contents": [
                    {"type": "file", "filename": "MD1.pdf", "filepath": "/sagataves/", "fileurl": fu + "MD1.pdf",
                     "timemodified": 5, "filesize": 10}]},
                {"id": 103, "modname": "label", "description": "<p>Laboratorijas darbs 2. grupai 25.11.</p>"},
                {"id": 104, "modname": "url", "name": "Simulators", "contents": [
                    {"type": "url", "fileurl": "https://falstad.com"}]},
                {"id": 105, "modname": "resource", "name": "Video", "uservisible": True, "contents": [
                    {"type": "file", "filename": "video.mp4", "fileurl": fu + "v.mp4", "timemodified": 1}]},
            ]},
            {"section": 2, "name": "RMMB0 laboratorijas darbi", "summary": "", "modules": [
                {"id": 106, "modname": "resource", "name": "LD1 apraksts", "contents": [
                    {"type": "file", "filename": "LD1.pdf", "fileurl": fu + "LD1.pdf", "timemodified": 1}]},
                {"id": 205, "modname": "assign", "name": "LD1 atskaite"}]},
            {"section": 3, "name": "RMCE0 3. grupa", "summary": "", "modules": [
                {"id": 107, "modname": "resource", "name": "LD1 apraksts", "contents": [
                    {"type": "file", "filename": "LD1.pdf", "fileurl": fu + "LD1b.pdf", "timemodified": 1}]}]},
        ],
        "core_group_get_course_user_groups": {"groups": [{"name": "RMCE0 3. grupa"}]},
        "mod_assign_get_assignments": {"courses": [{"id": 10, "assignments": [
            {"id": 1, "cmid": 201, "name": "MD1 — Kirhofa likumi", "duedate": now + 3 * day,
             "allowsubmissionsfromdate": now - 5 * day, "cutoffdate": 0, "intro": "<p>Atrisināt 5 uzdevumus.</p>",
             "introattachments": [{"filename": "MD1_uzdevumi.pdf", "fileurl": fu + "a.pdf", "timemodified": 9}]},
            {"id": 2, "cmid": 202, "name": "Referāts", "duedate": now + 40 * day, "intro": ""},
            {"id": 5, "cmid": 205, "name": "LD1 atskaite", "duedate": now + 4 * day, "intro": ""},
            {"id": 6, "cmid": 206, "name": "MD1 (1. grupai)", "duedate": now + 2 * day, "intro": ""}]}]},
        "mod_assign_get_submission_status": {"lastattempt": {"submission": {"status": "new"}}},
        "mod_quiz_get_quizzes_by_courses": {"quizzes": [
            {"id": 3, "coursemodule": 301, "course": 10, "name": "Tests 1", "timeopen": now + 6 * day,
             "timeclose": now + 6 * day + 3600, "timelimit": 1800, "attempts": 1, "intro": ""}]},
        "mod_quiz_get_user_attempts": {"attempts": []},
        "core_calendar_get_calendar_events": {"events": [
            {"id": 9, "name": "Eksāmens", "courseid": 10, "eventtype": "course", "timestart": now + 60 * day,
             "timeduration": 7200, "description": ""}]},
        "mod_forum_get_forums_by_courses": [{"id": 50, "course": 10, "type": "news", "name": "Paziņojumi"}],
        "mod_forum_get_forum_discussions": {"discussions": [
            {"name": "Izmaiņas", "message": "<p>MD2 termiņš pagarināts līdz 30.11. plkst. 23:59</p>",
             "created": now - day, "discussion": 77}]},
    }


def test_full_sync(tmp_path=None):
    tmp = Path(tmp_path or tempfile.mkdtemp())
    cfg = load_config("full")
    cfg.output_dir = tmp / "RTU"
    cfg.notify = False
    cfg.program, cfg.group = "RMCE0", "3"
    from estudijas_sync import sync as syncmod
    from estudijas_sync.api_source import ApiSource
    from estudijas_sync.config import save_auth

    save_auth(cfg, {"mode": "api", "token": "T", "userid": 7})
    responses = fake_api_responses()
    downloads = []

    def fake_call(self, fn, **kw):
        return responses[fn]

    def fake_download(self, item, dest, on_bytes=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        if on_bytes:
            on_bytes(item.size or 1)
        downloads.append(item.filename)
        return 1

    from estudijas_sync import moodle_api
    moodle_api.MoodleAPI.call = fake_call
    ApiSource.download = fake_download
    import io
    from estudijas_sync.progress import Progress
    buf = io.StringIO()
    r = syncmod.run_sync(cfg, prog=Progress(enabled=True, stream=buf))
    shown = buf.getvalue()
    assert "Nolasa estudijas" in shown and "Lejupielādē" in shown and "100%" in shown, shown
    assert r["courses"] == 1 and r["new"] == 4, r
    out = cfg.output_dir
    c = out / "Elektrotehnikas pamati"
    assert (c / "Lekcijas" / "01_L1 Omu likums.pptx").exists()
    assert (c / "Mājas darbi" / "MD materiāli" / "sagataves" / "MD1.pdf").exists()
    assert (c / "Mājas darbi" / "MD1_uzdevumi.pdf").exists()
    assert not any("video" in x for x in downloads)
    assert (c / "Laboratorijas darbi" / "LD1.pdf").exists() and downloads.count("LD1.pdf") == 1   # tikai RMCE0 3. gr.
    dg = (out / "UZDEVUMI.md").read_text(encoding="utf-8")
    top, hidden = dg.split("<details><summary>Citām grupām")[0], dg.split("<details><summary>Citām grupām")[1]
    assert "LD1 atskaite" not in top and "MD1 (1. grupai)" not in top and "LD1 atskaite" in hidden
    assert "atlase: **RMCE0, 3. grupa**" in dg
    assert "LD1 atskaite" not in (out / "termini.ics").read_text(encoding="utf-8")
    digest = (out / "UZDEVUMI.md").read_text(encoding="utf-8")
    assert "MD1 — Kirhofa likumi" in digest and "Tests 1" in digest
    assert "KD" in digest and "30.11." in digest          # no teksta
    ics = (out / "termini.ics").read_text(encoding="utf-8")
    assert ics.count("BEGIN:VEVENT") >= 5
    assert (c / "_info" / "Paziņojumi.md").exists() and (c / "_info" / "Saites.md").exists()
    assert r["changes_text"].startswith("Pirmā sinhronizācija"), r["changes_text"]
    # otrreiz — nekas jauns
    r2 = syncmod.run_sync(cfg)
    assert r2["new"] == 0 and r2["updated"] == 0, r2
    assert r2["changes_text"] == "Nekā jauna.", r2["changes_text"]
    # izmaiņas: fails atjaunināts, jauns MD, pārcelts tests, vērtējums, jauns paziņojums
    now = int(time.time())
    responses["core_course_get_contents"][1]["modules"][0]["contents"][0]["timemodified"] = 222
    responses["mod_assign_get_assignments"]["courses"][0]["assignments"].append(
        {"id": 4, "cmid": 204, "name": "MD2 — Tevenina teorēma", "duedate": now + 9 * 86400, "intro": ""})
    q = responses["mod_quiz_get_quizzes_by_courses"]["quizzes"][0]
    q["timeclose"] += 2 * 86400
    responses["mod_forum_get_forum_discussions"]["discussions"].insert(0, {
        "name": "Lekcija pārcelta", "message": "<p>Ceturtdienas lekcija būs aud. 210.</p>",
        "created": now, "discussion": 78})
    orig_call = moodle_api.MoodleAPI.call

    def call_graded(self, fn, **kw):
        if fn == "mod_assign_get_submission_status" and kw.get("assignid") == 1:
            return {"lastattempt": {"submission": {"status": "submitted"}},
                    "feedback": {"gradefordisplay": "9 / 10"}}
        return orig_call(self, fn, **kw)
    moodle_api.MoodleAPI.call = call_graded
    r3 = syncmod.run_sync(cfg)
    assert r3["updated"] == 1, r3
    t = r3["changes_text"]
    print(t)
    assert "MD2 — Tevenina" in t and "Tests 1" in t and "9 / 10" in t and "Lekcija pārcelta" in t, t
    log = (out / "JAUNUMI.md").read_text(encoding="utf-8")
    assert log.count("<!-- palaišana -->") == 2      # 1. palaišana + 3. (otrā bez izmaiņām netiek rakstīta)
    assert "Kopš iepriekšējās reizes" in (out / "UZDEVUMI.md").read_text(encoding="utf-8")
    moodle_api.MoodleAPI.call = fake_call
    # telefona režīms: tikai mājas darbi
    cfg2 = load_config("phone")
    cfg2.output_dir = tmp / "PHONE"
    cfg2.only_categories = ["Mājas darbi"]
    cfg2.notify = False
    save_auth(cfg2, {"mode": "api", "token": "T", "userid": 7})
    downloads.clear()
    syncmod.run_sync(cfg2)
    assert sorted(downloads) == ["MD1.pdf", "MD1_uzdevumi.pdf"], downloads   # bez program: nekas netiek atlasīts
    assert (cfg2.output_dir / "UZDEVUMI.md").exists()
    print((out / "UZDEVUMI.md").read_text(encoding="utf-8")[:1500])


def test_webui():
    import json as _json
    import threading
    import urllib.request
    from estudijas_sync.webui import serve
    holder, ready = [], threading.Event()
    threading.Thread(target=serve, args=("webtest", None), kwargs=dict(port=8931, open_browser=False, ready=ready,
                     app_holder=holder), daemon=True).start()
    assert ready.wait(10)
    app = holder[0]
    base = f"http://127.0.0.1:{app.port}"

    def req(path, body=None, token=True):
        r = urllib.request.Request(base + path, data=_json.dumps(body).encode() if body is not None else None,
                                   headers={"X-Token": app.token if token else "x", "Content-Type": "application/json"},
                                   method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    code, html = req("/")
    assert code == 200 and app.token in html
    assert req("/api/status", token=False)[0] == 401
    code, st = req("/api/status")
    assert code == 200 and _json.loads(st)["profile"] == "webtest"
    code, cfgj = req("/api/config", {"program": "rmce0", "group": "3. grupa", "schedule_times": "08:00, 20:00",
                                     "drive_enabled": True, "drive_categories": ["Mājas darbi"], "notify": False})
    v = _json.loads(cfgj)["values"]
    assert code == 200 and v["program"] == "RMCE0" and v["group"] == "3" and v["schedule_times"] == ["08:00", "20:00"]
    assert v["drive_enabled"] is True and v["notify"] is False
    assert req("/api/config", {"schedule_times": "25:99"})[0] == 400
    assert req("/api/open", {"path": "../../etc"})[0] == 400
    assert _json.loads(req("/api/view")[1]) == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("✔", name)
