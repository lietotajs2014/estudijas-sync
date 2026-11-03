"""RTU/Microsoft pieteikšanās caur servera pārlūku — pret viltotu e-studiju + Microsoft lapu (bez interneta).

Vajag Playwright Chromium (Docker image / CI to ir). Ja pārlūka nav, tests tiek izlaists.
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ESTUDIJAS_SYNC_HOME", tempfile.mkdtemp())

STATE = {"approved": False, "passwords": []}

PAGE = "<!doctype html><html><head><meta charset=utf-8><title>{t}</title></head><body>{b}</body></html>"


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _html(self, body, title="Sign in", code=200, headers=None):
        data = PAGE.format(t=title, b=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, cookies=()):
        self.send_response(303)
        self.send_header("Location", to)
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/my/":
            if "MoodleSession=ok" in (self.headers.get("Cookie") or ""):
                return self._html('<script>window.M={"cfg":{"sesskey":"SK123"}}</script>'
                                  '<div data-userid="77"></div><span class="usertext">Jānis Bērziņš</span>', "Dashboard")
            return self._redirect("/ms/login")
        if p == "/ms/login":
            # kā īstajā Microsoft lapā: nākamie soļi jau DOM, nobīdīti ārpus ekrāna
            return self._html('<div style="position:absolute;left:-9999px;top:0"><input type=email name=other>'
                              '<input type=password name=passwd></div>'
                              '<form method=post action=/ms/email><input type=email name=loginfmt id=i0116>'
                              '<input type=submit id=idSIButton9 value=Next></form>')
        if p == "/ms/pwd":
            return self._html('<div id=displayName>janis@edu.rtu.lv</div><input type=email name=loginfmt style="display:none">'
                              '<form method=post action=/ms/pass><input type=password name=passwd id=i0118></form>')
        if p == "/ms/mfa":
            return self._html('<div id=idDiv_SAOTCAS_Title>Approve sign in request</div><div id=idRichContext_DisplaySign>42</div>'
                              '<script>setInterval(()=>fetch("/ms/approved").then(r=>r.text()).then(t=>{if(t==="yes")location="/ms/kmsi"}),300)</script>')
        if p == "/ms/approved":
            data = b"yes" if STATE["approved"] else b"no"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if p == "/ms/kmsi":
            return self._html('<div id=KmsiDescription>Stay signed in?</div>'
                              '<form method=post action=/ms/kmsi_yes><input type=submit id=idSIButton9 value=Yes></form>')
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/ms/email":
            f = self._form()
            if f.get("loginfmt", "").endswith("@edu.rtu.lv"):
                return self._redirect("/ms/pwd")
            return self._html('<div id=usernameError>Šāds konts nav atrasts.</div>'
                              '<form method=post action=/ms/email><input type=email name=loginfmt></form>')
        if p == "/ms/pass":
            pw = self._form().get("passwd", "")
            STATE["passwords"].append(pw)
            if pw == "pareizi":
                return self._redirect("/ms/mfa")
            return self._html('<div id=passwordError>Parole nav pareiza.</div>'
                              '<form method=post action=/ms/pass><input type=password name=passwd></form>')
        if p == "/ms/kmsi_yes":
            return self._redirect("/my/", ["MoodleSession=ok; Path=/; HttpOnly", "ESTSAUTHPERSISTENT=p; Path=/; Max-Age=999999"])
        if p.startswith("/lib/ajax/service.php"):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"[]")[0]
            data = ({"courses": [{"id": 1, "fullname": "Fizika", "shortname": "RMCE0-3 Fizika"}]}
                    if "enrolled" in req["methodname"] else {"groups": [{"name": "RMCE0 3. grupa"}]})
            body = json.dumps([{"error": False, "data": data}]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self.send_response(404)
        self.end_headers()


@pytest.fixture()
def fake_site(monkeypatch):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Chromium nav pieejams: {e}")
    from server import moodle_link
    monkeypatch.setattr(moodle_link, "ALLOWED_COOKIE_DOMAINS", moodle_link.ALLOWED_COOKIE_DOMAINS + ("127.0.0.1",))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STATE.update(approved=False, passwords=[])
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _wait(s, step, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        st = s.snapshot()
        if st["step"] == step:
            return st
        if st["step"] in ("error", "cancelled") and step not in ("error", "cancelled"):
            raise AssertionError(st)
        time.sleep(0.2)
    raise AssertionError(f"Negaidīja {step}: {s.snapshot()}")


def test_ms_login_flow(fake_site):
    from server.ms_login import LoginSession

    saved = {}

    def on_success(uid, cookies, info):
        saved.update(uid=uid, cookies=cookies, info=info)
        return info["fullname"]

    s = LoginSession(7, "janis@edu.rtu.lv", fake_site, on_success)
    s.start()
    st = _wait(s, "password")                         # e-pasts ievadīts automātiski
    assert "janis" in (st.get("who") or "")
    s.send({"a": "password", "v": "nepareizi"})
    st = _wait(s, "password")
    deadline = time.time() + 10
    while "error" not in st and time.time() < deadline:
        time.sleep(0.2)
        st = s.snapshot()
    assert "nav pareiza" in st["error"]
    s.send({"a": "password", "v": "pareizi"})
    st = _wait(s, "number")
    assert st["number"] == "42"
    s.send({"a": "shot", "on": True})
    time.sleep(1.5)
    assert s.snapshot(with_shot=True).get("shot", "").startswith("data:image/jpeg;base64,")
    STATE["approved"] = True                          # "apstiprināts telefonā"
    st = _wait(s, "done")
    assert st["fullname"] == "Jānis Bērziņš" and st["program"] == "RMCE0" and st["group"] == "3"
    assert {c["name"] for c in saved["cookies"]} >= {"MoodleSession", "ESTSAUTHPERSISTENT"}
    assert STATE["passwords"] == ["nepareizi", "pareizi"]
    s.thread.join(10)
    assert not s.active and s.shot is None             # pārlūks aizvērts, ekrānuzņēmums izmests
    assert "pareizi" not in json.dumps(s.snapshot())   # parole stāvoklī neparādās


def test_ms_login_cancel(fake_site):
    from server.ms_login import LoginSession

    s = LoginSession(8, "", fake_site, lambda *a: "")
    s.start()
    _wait(s, "email")                                 # bez e-pasta — prasa lietotājam
    s.send({"a": "email", "v": "kads@example.com"})
    deadline = time.time() + 10
    st = s.snapshot()
    while not st.get("error") and time.time() < deadline:
        time.sleep(0.2)
        st = s.snapshot()
    assert st["step"] == "email" and "nav atrasts" in st["error"]
    s.send({"a": "cancel"})
    _wait(s, "cancelled")
    s.thread.join(10)
    assert not s.active


def test_ms_login_debug_remote(fake_site):
    """Debug serverī: neko neievada pats, rāda ekrānu; lietotājs raksta caur click/type/key."""
    from server.ms_login import LoginSession

    before = list(STATE["passwords"])
    s = LoginSession(9, "janis@edu.rtu.lv", fake_site, lambda *a: "", manual=True)
    s.start()
    st = _wait(s, "manual")
    assert st.get("remote") is True
    time.sleep(1.5)
    assert s.snapshot(with_shot=True).get("shot", "").startswith("data:image/jpeg;base64,")
    time.sleep(2)
    assert s.snapshot()["step"] == "manual"            # e-pasts netika ievadīts pats — joprojām gaida lietotāju
    assert STATE["passwords"] == before
    s.send({"a": "cancel"})
    _wait(s, "cancelled")
    s.thread.join(10)
    assert not s.active and s.shot is None
