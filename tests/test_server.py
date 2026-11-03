"""Servera testi bez interneta: python -m pytest tests/test_server.py"""
import base64
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp())
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp / 'test.db'}",
    "DATA_DIR": str(_tmp / "data"),
    "ESTUDIJAS_SYNC_HOME": str(_tmp / "home"),
    "SECRET_KEY": "x" * 40,
    "ENCRYPTION_KEY": "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
    "GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "csecret",
    "ALLOWED_EMAILS": "students@example.com", "BASE_URL": "http://testserver",
})

from fastapi.testclient import TestClient  # noqa: E402

from server import app as appmod, google_oauth  # noqa: E402
from server.crypto import decrypt, encrypt  # noqa: E402
from server.db import SessionLocal, User  # noqa: E402
from server.moodle_link import LinkError, detect_identity, parse_token_input  # noqa: E402
from server.worker import due_slot  # noqa: E402

SITE = "https://estudijas.rtu.lv"


def test_detect_identity():
    r = detect_identity(["RMCE0 3. grupa", "RMCE0-3", "Visi studenti", "RDBM0 1.grupa", "RMCE0"])
    assert r["program"] == "RMCE0" and r["group"] == "3"
    r = detect_identity(["3. grupa", "Lekcijas"])
    assert r["program"] == "" and r["group"] == "3"
    assert detect_identity([])["program"] == ""


def test_parse_token():
    assert parse_token_input("a" * 32, SITE) == ("a" * 32, None)
    b64 = base64.b64encode(b"sig:::abcdefabcdefabcdefabcdefabcdef12:::priv").decode()
    assert parse_token_input(f"moodlemobile://token={b64}", SITE) == ("abcdefabcdefabcdefabcdefabcdef12", "priv")
    with pytest.raises(LinkError):
        parse_token_input("parole123", SITE)
    with pytest.raises(LinkError):
        parse_token_input("", SITE)


def test_crypto_roundtrip():
    blob = encrypt("slepens")
    assert blob != "slepens" and decrypt(blob) == "slepens"
    assert decrypt("bojāts") is None and encrypt(None) is None


def test_due_slot():
    t = ["07:30", "19:30"]
    assert due_slot(datetime(2026, 11, 2, 7, 29), t, None) is None
    assert due_slot(datetime(2026, 11, 2, 7, 30), t, None) == "2026-11-02 07:30"
    assert due_slot(datetime(2026, 11, 2, 12, 0), t, "2026-11-02 07:30") is None
    assert due_slot(datetime(2026, 11, 2, 20, 0), t, "2026-11-02 07:30") == "2026-11-02 19:30"


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture()
def client(monkeypatch):
    with TestClient(appmod.app) as c:
        yield c


def _login(client, monkeypatch, email="students@example.com", sub="g-1"):
    monkeypatch.setattr(google_oauth, "finish",
                        lambda s, st, code: ("login", {"sub": sub, "email": email, "name": "Students"}, {}))
    return client.get("/auth/google/callback?state=x&code=y", follow_redirects=False)


def test_full_flow(client, monkeypatch):
    assert client.get("/").status_code == 200
    r = client.get("/connect", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"

    r = _login(client, monkeypatch)
    assert r.status_code == 303
    page = client.get("/connect")
    assert page.status_code == 200 and "Pieslēdz e-studijas" in page.text
    csrf = _csrf(page.text)

    # bez CSRF žetona — atteikts
    assert client.post("/connect", data={"token": "a" * 32}).status_code == 400

    monkeypatch.setattr(appmod, "inspect_account", lambda site, tok: {
        "userid": 77, "fullname": "Jānis Bērziņš", "courses": [{"name": "Fizika", "groups": ["RMCE0 3. grupa"]}],
        "program": "RMCE0", "group": "3", "program_candidates": ["RMCE0"], "group_candidates": ["3"]})
    r = client.post("/connect", data={"token": "a" * 32, "csrf": csrf}, follow_redirects=False)
    assert r.headers["location"] == "/confirm"
    page = client.get("/confirm")
    assert 'value="RMCE0"' in page.text and "Jānis" in page.text

    r = client.post("/confirm", data={"program": "rmce0", "group": "3. grupa", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    dash = client.get("/")
    assert "Sinhronizēt tagad" in dash.text and "RMCE0" in dash.text

    with SessionLocal() as db:
        u = db.query(User).filter_by(google_sub="g-1").one()
        assert u.program == "RMCE0" and u.group == "3" and u.sync_requested
        assert u.moodle.token_enc != "a" * 32 and decrypt(u.moodle.token_enc) == "a" * 32
        secret = u.ics_secret

    assert client.get(f"/cal/{secret}.ics").text.startswith("BEGIN:VCALENDAR")
    assert client.get("/cal/" + "x" * 30 + ".ics").status_code == 404
    assert "Content-Security-Policy" in dash.headers


def test_not_allowed(client, monkeypatch):
    _login(client, monkeypatch, email="sveshs@example.com", sub="g-2")
    r = client.get("/")
    assert "nav piekļuves" in r.text
    assert client.get("/settings", follow_redirects=False).status_code == 303


def test_build_config(monkeypatch):
    from server.runner import build_config
    u = User(id=5, google_sub="s", email="e", program="RMCE0", group="3", extra_groups=["2"], exclude_courses=[])
    cfg = build_config(u)
    assert cfg.output_dir == Path(os.environ["DATA_DIR"]) / "users" / "5"
    assert cfg.program == "RMCE0" and cfg.my_groups == ["2"]
    assert not cfg.notify and not cfg.login_popup and not cfg.google and cfg.ics
    assert cfg.data_dir == cfg.output_dir / ".estudijas-sync"


def test_normalize_cookies():
    from server.moodle_link import normalize_cookies
    raw = [{"name": "MoodleSession", "value": "abc", "domain": "estudijas.rtu.lv"},
           {"name": "ESTSAUTHPERSISTENT", "value": "x", "domain": "login.microsoftonline.com"},
           {"name": "evil", "value": "y", "domain": "example.com"},
           {"name": "bad name", "value": "z", "domain": "rtu.lv"}]
    out = normalize_cookies(raw, SITE)
    assert [c["name"] for c in out] == ["MoodleSession", "ESTSAUTHPERSISTENT"]
    with pytest.raises(LinkError):
        normalize_cookies([{"name": "x", "value": "1", "domain": "rtu.lv"}], SITE)
    with pytest.raises(LinkError):
        normalize_cookies("nav saraksts", SITE)


def test_pairing_flow(client, monkeypatch):
    _login(client, monkeypatch, sub="g-pair")
    page = client.get("/connect")
    assert "Izveidot savienošanas kodu" in page.text
    client.post("/connect/code", data={"csrf": _csrf(page.text)})
    page = client.get("/connect")
    code = re.search(r'class="code">(\d{3} \d{3})<', page.text).group(1)
    assert client.get("/connect/status").json() == {"linked": False}

    monkeypatch.setattr(appmod, "inspect_session", lambda site, cookies: {
        "userid": 5, "fullname": "Anna", "courses": [], "program": "RMCE0", "group": "3",
        "program_candidates": ["RMCE0"], "group_candidates": ["3"]})
    cookies = [{"name": "MoodleSession", "value": "sess123", "domain": "estudijas.rtu.lv"}]
    # nepareizs kods
    r = client.post("/api/pair", json={"code": "000000", "cookies": cookies, "source": "android"})
    assert r.status_code == 400 and not r.json()["ok"]
    # pareizs kods (ar atstarpi, kā lapā)
    r = client.post("/api/pair", json={"code": code, "cookies": cookies, "source": "android"})
    assert r.json() == {"ok": True, "fullname": "Anna", "account": "students@example.com"}
    # otrreiz nedrīkst
    assert client.post("/api/pair", json={"code": code, "cookies": cookies}).status_code == 400

    assert client.get("/connect/status").json() == {"linked": True}
    with SessionLocal() as db:
        u = db.query(User).filter_by(google_sub="g-pair").one()
        assert u.moodle.mode == "web" and u.moodle.source == "android" and u.sync_requested
        assert "sess123" not in u.moodle.cookies_enc and "sess123" in decrypt(u.moodle.cookies_enc)
    assert 'value="RMCE0"' in client.get("/confirm").text


def test_web_mode_runner(monkeypatch):
    import json as _json

    from server import runner
    from server.crypto import encrypt as enc
    from server.db import MoodleLink

    seen = {}

    def fake_run_sync(cfg, **kw):
        f = cfg.data_dir / "cookies.json"
        seen["cookies"] = _json.loads(f.read_text())
        seen["auth"] = kw.get("auth")
        f.write_text(_json.dumps(seen["cookies"] + [{"name": "new", "value": "1", "domain": "rtu.lv"}]))
        return {"courses": 1, "deadlines": 2, "warning_list": []}

    monkeypatch.setattr("estudijas_sync.sync.run_sync", fake_run_sync)
    with SessionLocal() as db:
        u = User(google_sub="g-run", email="students@example.com", program="RMCE0", group="3")
        db.add(u)
        db.flush()
        db.add(MoodleLink(user_id=u.id, mode="web", token_enc="",
                          cookies_enc=enc(_json.dumps([{"name": "MoodleSession", "value": "s", "domain": "estudijas.rtu.lv"}]))))
        db.commit()
        res = runner.sync_user(db, u)
        assert res["deadlines"] == 2 and seen["auth"] == {"mode": "web"}
        assert seen["cookies"][0]["value"] == "s"
        cfg = runner.build_config(u)
        assert not (cfg.data_dir / "cookies.json").exists()          # sīkdatnes uz diska neatstājam
        assert "new" in decrypt(u.moodle.cookies_enc)                 # atjaunotās saglabātas DB


def test_pc_pair_module(monkeypatch, tmp_path):
    import json as _json

    from estudijas_sync import pair as pairmod

    class Cfg:
        data_dir = tmp_path
    (tmp_path / "cookies.json").write_text(_json.dumps([
        {"name": "MoodleSession", "value": "s", "domain": "estudijas.rtu.lv"},
        {"name": "other", "value": "x", "domain": "google.com"}]))
    sent = {}

    class R:
        status_code = 200

        def json(self):
            return {"ok": True, "fullname": "Anna"}

    monkeypatch.setattr(pairmod.requests, "post", lambda url, json, timeout: (sent.update(url=url, body=json), R())[1])
    assert pairmod.pair(Cfg, "123 456")["fullname"] == "Anna"
    assert sent["url"] == "https://estudijas.lodelo.de/api/pair" and sent["body"]["code"] == "123456"
    assert [c["name"] for c in sent["body"]["cookies"]] == ["MoodleSession"]
    with pytest.raises(pairmod.PairError):
        pairmod.pair(Cfg, "12")


def _panel(client, monkeypatch, sub):
    _login(client, monkeypatch, sub=sub)
    page = client.get("/")
    tok = re.search(r'const TOKEN = "([^"]+)"', page.text).group(1)
    return page, {"X-Token": tok}


def test_panel_web_mode(client, monkeypatch):
    page, h = _panel(client, monkeypatch, "g-panel")
    assert '"web" === "web"' in page.text and "__TOKEN__" not in page.text
    assert "unsafe-inline" in page.headers["Content-Security-Policy"]
    assert client.get("/api/status").status_code == 401                 # bez X-Token
    st = client.get("/api/status", headers=h).json()
    assert st["mode"] == "web" and st["auth"]["mode"] is None and st["job"] is None
    assert st["ics_url"].startswith("http://testserver/cal/")
    # bez e-studijām — sinhronizēt/ielādēt nevar
    assert client.post("/api/job/sync", headers=h).status_code == 400
    assert client.post("/api/download", json={"keys": ["a"]}, headers=h).status_code == 400

    cfg = client.post("/api/config", headers=h, json={
        "email": "janis@edu.rtu.lv", "program": "rmce0", "group": "3. grupa", "other_groups": "folder",
        "exclude_courses": ["Sports"], "lookahead_days": 3, "download_max_mb": 50, "reminders_minutes": "1440, 60",
        "drive_enabled": True}).json()["values"]
    assert cfg["program"] == "RMCE0" and cfg["group"] == "3" and cfg["other_groups"] == "folder"
    assert cfg["lookahead_days"] == 7 and cfg["reminders_minutes"] == [1440, 60]
    assert cfg["drive_enabled"] is False                                  # Drive nav pieslēgts
    assert client.post("/api/config", headers=h, json={"other_groups": "x"}).status_code == 400
    assert client.get("/api/status", headers=h).json()["rtu_email"] == "janis@edu.rtu.lv"

    # e-studijas pieslēgtas → "Sinhronizēt" un "Ielādēt atzīmētos" iet rindā worker
    from server.db import MoodleLink
    with SessionLocal() as db:
        u = db.query(User).filter_by(google_sub="g-panel").one()
        db.add(MoodleLink(user_id=u.id, mode="web", token_enc="", cookies_enc="x", fullname="Jānis"))
        u.sync_requested = False
        db.commit()
        uid = u.id
    r = client.post("/api/download", json={"keys": ["k1", "k2", "k1"]}, headers=h)
    assert r.json()["ok"]
    st = client.get("/api/status", headers=h).json()
    assert st["auth"]["fullname"] == "Jānis" and st["job"] == {"name": "Lejupielāde", "queued": True}
    with SessionLocal() as db:
        assert db.get(User, uid).download_requested == ["k1", "k2"]

    # faili: tikai lietotāja mapē, bez .estudijas-sync un ../
    from server.runner import user_dir
    d = user_dir(uid)
    (d / "Fizika").mkdir(parents=True, exist_ok=True)
    (d / "Fizika" / "MD1.pdf").write_bytes(b"%PDF-1.4 test")
    (d / ".estudijas-sync").mkdir(exist_ok=True)
    (d / ".estudijas-sync" / "state.json").write_text("{}")
    assert client.get("/api/file", params={"path": "Fizika/MD1.pdf"}).content == b"%PDF-1.4 test"
    assert client.get("/api/file", params={"path": ".estudijas-sync/state.json"}).status_code == 404
    assert client.get("/api/file", params={"path": "../../test.db"}).status_code == 404
    assert client.post("/api/zip", json={"keys": ["k1"]}, headers=h).status_code == 400   # nav ielādēts

    # "Aizmirst piekļuvi" izdzēš sesiju
    assert client.post("/api/logout", headers=h).json()["ok"]
    assert client.get("/api/status", headers=h).json()["auth"]["mode"] is None


def test_panel_ms_login_api(client, monkeypatch):
    from server import ms_login

    _page, h = _panel(client, monkeypatch, "g-ms")
    started = {}

    class FakeSession:
        id, active = "sid", True

        def snapshot(self, with_shot=False):
            return {"step": "password", "id": "sid", "email": started["email"]}

        def send(self, cmd):
            started.setdefault("cmds", []).append(cmd)

    def fake_start(uid, email, site, cb, manual=False, channel="", headed=False):
        started.update(uid=uid, email=email, cb=cb)
        return FakeSession()

    monkeypatch.setattr(ms_login.registry, "start", fake_start)
    monkeypatch.setattr(ms_login.registry, "get", lambda uid: FakeSession() if started else None)
    assert client.get("/api/ms/state", headers=h).json() == {"step": "none"}
    r = client.post("/api/ms/start", json={"email": "anna@edu.rtu.lv"}, headers=h).json()
    assert r["ok"] and r["step"] == "password" and started["email"] == "anna@edu.rtu.lv"
    assert client.post("/api/ms/input", json={"a": "password", "v": "slepena"}, headers=h).json()["ok"]
    assert client.post("/api/ms/input", json={"a": "rm -rf"}, headers=h).status_code == 400
    assert started["cmds"] == [{"a": "password", "v": "slepena"}]

    # veiksmīga pieteikšanās saglabā šifrētu sesiju un atpazīto programmu/grupu
    name = started["cb"](started["uid"], [{"name": "MoodleSession", "value": "zzz", "domain": "estudijas.rtu.lv",
                                            "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}],
                         {"userid": 9, "fullname": "Anna", "courses": [], "program": "RMCE0", "group": "3",
                          "program_candidates": [], "group_candidates": []})
    assert name == "Anna"
    with SessionLocal() as db:
        u = db.get(User, started["uid"])
        assert u.program == "RMCE0" and u.group == "3" and u.moodle.source == "lapa" and u.sync_requested
        assert "zzz" not in u.moodle.cookies_enc and "zzz" in decrypt(u.moodle.cookies_enc)
        assert (u.prefs or {}).get("rtu_email") == "anna@edu.rtu.lv"


def test_google_connect_and_calendar_sync(client, monkeypatch):
    from server import gdrive, google_oauth as go, runner

    _page, h = _panel(client, monkeypatch, "g-goo")
    with SessionLocal() as db:
        from server.db import MoodleLink
        u = db.query(User).filter_by(google_sub="g-goo").one()
        db.add(MoodleLink(user_id=u.id, mode="web", token_enc="", cookies_enc=encrypt("[]")))
        u.sync_requested = False
        db.commit()
        uid = u.id
    # Google ar Drive + kalendāru (tas pats konts)
    monkeypatch.setattr(go, "finish", lambda s, st, code: ("google", {"sub": "g-goo", "email": "students@example.com"},
                        {"refresh_token": "rt", "scope": f"openid {go.DRIVE_SCOPE} {go.CALENDAR_SCOPE}"}))
    r = client.get("/auth/google/callback?state=x&code=y", follow_redirects=False)
    assert r.headers["location"] == "/"
    st = client.get("/api/status", headers=h).json()
    assert st["gcal"] == {"connected": True, "enabled": True} and st["drive"]["enabled"]
    assert "Google Calendar" in st["flash"]["msg"] and st["ics_download"].endswith("?download=1")
    with SessionLocal() as db:
        u = db.get(User, uid)
        assert u.sync_requested and decrypt(u.google.refresh_token_enc) == "rt"
        # sinhronizācija → kalendārs un Drive tiek atjaunināti
        calls = []
        monkeypatch.setattr(gdrive, "calendar_sync", lambda user, cfg, view: calls.append(("cal", cfg.reminders_minutes)) or 3)
        monkeypatch.setattr(gdrive, "mirror", lambda user, cfg: calls.append(("drive",)) or 0)
        monkeypatch.setattr("estudijas_sync.sync.run_sync", lambda cfg, **kw: {"courses": 1, "warning_list": []})
        res = runner.sync_user(db, u)
        assert res["gcal_changes"] == 3 and ("drive",) in calls and calls[-1][0] == "cal"
    # atgādinājumi: cik grib, līdz 28 d.
    cfg = client.post("/api/config", headers=h, json={"reminders_minutes": [10, 1440, 2 * 1440 + 90, 99999, 10],
                                                       "gcal_enabled": False}).json()["values"]
    assert cfg["reminders_minutes"] == [2970, 1440, 10] and cfg["gcal_enabled"] is False
    secret = client.get("/api/status", headers=h).json()["ics_url"].rsplit("/", 1)[1]
    assert "attachment" in client.get(f"/cal/{secret}?download=1").headers.get("content-disposition", "")


def test_gcal_body_max_5_reminders():
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from estudijas_sync import gcal
    from estudijas_sync.model import Deadline
    from server.runner import build_config

    u = User(id=99, google_sub="x", email="e", prefs={"reminders_minutes": [5, 10, 60, 120, 1440, 2880, 50000]})
    cfg = build_config(u)
    now = datetime.now(ZoneInfo("Europe/Riga"))
    d = Deadline(uid="a", course_id=1, kind="MD", title="MD1", due=now + timedelta(days=3), url="https://x")
    mins = [o["minutes"] for o in gcal._body(d, {}, cfg, now)["reminders"]["overrides"]]
    assert mins == [5, 10, 60, 120, 1440] and cfg.google_calendar_name == "RTU estudijas"
