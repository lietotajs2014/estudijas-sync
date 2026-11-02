"""Lokāls web panelis: python run.py web  →  http://127.0.0.1:8765

Darbojas tikai tavā datorā (piesaistīts 127.0.0.1). Katram startam tiek ģenerēts slepens
žetons, bez kura API nestrādā — citas pārlūka lapas nevar palaist darbības tavā vārdā.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import secrets
import subprocess
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import Config, State, load_auth, load_config, set_toml_values
from .model import LoginRequired
from .progress import Progress

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).with_name("web")
PROJECT_DIR = Path(__file__).resolve().parent.parent

# lauks UI → (TOML sadaļa, atslēga, tips)
FIELDS: dict[str, tuple[str | None, str, str]] = {
    "email": (None, "email", "str"),
    "program": (None, "program", "upper"),
    "group": (None, "group", "group"),
    "output_dir": (None, "output_dir", "str"),
    "other_groups": (None, "other_groups", "other"),
    "exclude_courses": (None, "exclude_courses", "list"),
    "only_categories": (None, "only_categories", "list"),
    "notify": (None, "notify", "bool"),
    "lookahead_days": (None, "lookahead_days", "int"),
    "download_max_mb": (None, "download_max_mb", "float"),
    "schedule_times": ("schedule", "times", "times"),
    "ics": ("calendar", "ics", "bool"),
    "google": ("calendar", "google", "bool"),
    "google_calendar_name": ("calendar", "google_calendar_name", "str"),
    "include_text_dates": ("calendar", "include_text_dates", "bool"),
    "reminders_minutes": ("calendar", "reminders_minutes", "intlist"),
    "drive_enabled": ("drive", "enabled", "bool"),
    "drive_folder": ("drive", "folder", "str"),
    "drive_categories": ("drive", "categories", "list"),
    "drive_include_digest": ("drive", "include_digest", "bool"),
}


def _coerce(kind: str, v):
    if kind == "bool":
        return bool(v)
    if kind == "int":
        return int(v)
    if kind == "float":
        return float(v)
    if kind == "upper":
        return str(v).strip().upper()
    if kind == "group":
        return str(v).strip().lower().replace("grupa", "").replace("gr", "").strip(" .")
    if kind == "other":
        v = str(v).strip().lower()
        if v not in ("skip", "folder", "keep"):
            raise ValueError("other_groups jābūt skip/folder/keep")
        return v
    if kind in ("list", "times", "intlist"):
        items = v if isinstance(v, list) else re.split(r"[,\n]", str(v))
        items = [str(x).strip() for x in items if str(x).strip()]
        if kind == "times":
            for t in items:
                if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
                    raise ValueError(f"Nepareizs laiks: {t} (vajag HH:MM)")
        if kind == "intlist":
            return [int(x) for x in items]
        return items
    return str(v).strip()


class WebProgress(Progress):
    """Progress, ko nolasa panelis (nevis terminālis)."""

    def __init__(self):
        super().__init__(enabled=True)
        self.lines: list[str] = []

    def _write(self, text: str, end: str = "") -> None:
        if end == "\n":
            self.lines = (self.lines + [text.strip()])[-40:]

    def _draw(self, force: bool = False) -> None:
        pass

    def reset(self) -> None:
        self.lines, self._active, self.title, self.total, self.count = [], False, "", 0, 0
        self.bytes_total = self.bytes_done = 0
        self._label = ""

    def snapshot(self) -> dict:
        if self.bytes_total:
            frac = min(self.bytes_done / self.bytes_total, 1.0)
        elif self.total:
            frac = self.count / self.total
        else:
            frac = 0.0
        return {"active": self._active, "title": self.title, "count": self.count, "total": self.total,
                "bytes_done": self.bytes_done, "bytes_total": self.bytes_total, "label": self._label,
                "percent": round(frac * 100), "lines": self.lines[-12:]}


class App:
    def __init__(self, profile: str, config_path: Path | None):
        self.profile = profile
        self.config_path = config_path
        self.token = secrets.token_urlsafe(24)
        self.prog = WebProgress()
        self.lock = threading.Lock()
        self.job: dict | None = None
        self.last_job: dict | None = None
        self.port = 0

    def cfg(self) -> Config:
        return load_config(self.profile, self.config_path)

    # ---- fona darbi ----
    def start_job(self, name: str, fn) -> tuple[bool, str]:
        with self.lock:
            if self.job:
                return False, f"Jau notiek: {self.job['name']}"
            self.prog.reset()
            self.job = {"name": name, "started": datetime.now().isoformat(timespec="seconds")}

        def run():
            ok, msg = True, ""
            try:
                msg = fn() or "Gatavs."
            except LoginRequired as e:
                ok, msg = False, f"Jāpiesakās no jauna: {e}"
            except Exception as e:
                log.exception("Darbs %s", name)
                ok, msg = False, f"{e}\n\n{traceback.format_exc(limit=3)}"
            with self.lock:
                done = dict(self.job or {}, ok=ok, message=msg,
                            finished=datetime.now().isoformat(timespec="seconds"))
                self.last_job, self.job = done, None
        threading.Thread(target=run, daemon=True, name=f"job-{name}").start()
        return True, "Sākts"

    def job_sync(self) -> str:
        from .sync import AlreadyRunning, sync_with_relogin
        cfg = self.cfg()
        try:
            r = sync_with_relogin(cfg, prog=self.prog)
        except LoginRequired as e:
            from .cli import _relogin_needed
            _relogin_needed(cfg, str(e))
            raise
        except AlreadyRunning as e:
            return str(e)
        return r["changes_text"]

    def job_login(self) -> str:
        from .auth import interactive_login
        auth = interactive_login(self.cfg(), prog=self.prog)
        return ("Pieteikšanās izdevās — API režīms (pārlūks turpmāk nav vajadzīgs)." if auth["mode"] == "api"
                else "Pieteikšanās izdevās — pārlūka režīms (ik pa laikam būs jāpiesakās no jauna).")

    def job_gcal(self) -> str:
        from . import gcal
        cfg = self.cfg()
        st = State(cfg.data_dir / "state.json")
        svc = gcal.get_service(cfg, interactive=True)
        cid = gcal.ensure_calendar(svc, cfg, st)
        st.save()
        set_toml_values(cfg.config_path, {("calendar", "google"): True})
        return f"Google Calendar savienots (kalendārs '{cfg.google_calendar_name}', {cid})."

    def job_update(self) -> str:
        from .updater import do_update
        ok, msg = do_update()
        if not ok:
            raise RuntimeError(msg)
        return msg

    # ---- dati ----
    def status(self) -> dict:
        from . import schedule, updater
        cfg = self.cfg()
        auth = load_auth(cfg) or {}
        st = State(cfg.data_dir / "state.json").data
        return {
            "version": __version__, "git_version": updater.current_version(), "is_repo": updater.is_repo(),
            "profile": cfg.profile, "config_path": str(cfg.config_path), "output_dir": str(cfg.output_dir),
            "data_dir": str(cfg.data_dir),
            "auth": {"mode": auth.get("mode"), "obtained": auth.get("obtained"), "fullname": auth.get("fullname")},
            "last_run": st.get("last_run"),
            "job": self.job, "last_job": self.last_job, "progress": self.prog.snapshot(),
            "schedule": {"installed": schedule.status(cfg), "times": cfg.schedule_times},
            "google_credentials": cfg.google_credentials.exists(),
            "google_token": (cfg.data_dir / "google_token.json").exists(),
            "platform": platform.system(),
        }

    def config_dict(self) -> dict:
        cfg = self.cfg()
        vals = {
            "email": cfg.email, "program": cfg.program, "group": cfg.group, "output_dir": str(cfg.output_dir),
            "other_groups": cfg.other_groups, "exclude_courses": cfg.exclude_courses,
            "only_categories": cfg.only_categories, "notify": cfg.notify, "lookahead_days": cfg.lookahead_days,
            "download_max_mb": cfg.download_max_mb, "schedule_times": cfg.schedule_times, "ics": cfg.ics,
            "google": cfg.google, "google_calendar_name": cfg.google_calendar_name,
            "include_text_dates": cfg.include_text_dates, "reminders_minutes": cfg.reminders_minutes,
            "drive_enabled": cfg.drive_enabled, "drive_folder": str(cfg.drive_folder or ""),
            "drive_categories": cfg.drive_categories, "drive_include_digest": cfg.drive_include_digest,
        }
        cats = list(cfg.categories) + ["Lekcijas", "Uzdevumi", "Citi"]
        return {"values": vals, "categories": list(dict.fromkeys(cats))}

    def save_config(self, body: dict) -> dict:
        updates = {}
        for k, v in body.items():
            if k not in FIELDS:
                continue
            section, key, kind = FIELDS[k]
            updates[(section, key)] = _coerce(kind, v)
        if updates:
            cfg = self.cfg()
            set_toml_values(cfg.config_path, updates)
            if ("schedule", "times") in updates:
                from . import schedule
                if schedule.status(cfg):
                    schedule.install(self.cfg())
        return self.config_dict()

    def view(self) -> dict:
        p = self.cfg().data_dir / "view.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def recent_files(self) -> list[dict]:
        from .drive import file_category
        st = State(self.cfg().data_dir / "state.json")
        rows = [{"path": e.get("path", ""), "downloaded": e.get("downloaded", ""),
                 "category": file_category(e.get("path", "")), "course": e.get("path", "").split("/")[0]}
                for e in st.files.values() if e.get("path")]
        rows.sort(key=lambda r: r["downloaded"], reverse=True)
        return rows[:300]

    def doc(self, name: str) -> str:
        cfg = self.cfg()
        paths = {"README": PROJECT_DIR / "README.md", "UZDEVUMI": cfg.output_dir / "UZDEVUMI.md",
                 "JAUNUMI": cfg.output_dir / "JAUNUMI.md", "CONFIG": cfg.config_path}
        p = paths.get(name)
        if not p or not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def log_tail(self, n: int = 250) -> str:
        p = self.cfg().data_dir / "sync.log"
        if not p.exists():
            return ""
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])

    def open_path(self, rel: str) -> str:
        cfg = self.cfg()
        if rel == "@config":
            target = cfg.config_path
        elif rel == "@data":
            target = cfg.data_dir
        else:
            base = cfg.output_dir.resolve()
            target = (base / rel).resolve() if rel else base
            if base != target and base not in target.parents:
                raise PermissionError("Ceļš ārpus izvades mapes")
        if not target.exists():
            raise FileNotFoundError(f"Nav atrasts: {target}")
        system = platform.system()
        if system == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return str(target)

    def save_credentials(self, content: str) -> str:
        data = json.loads(content)
        if not ("installed" in data or "web" in data):
            raise ValueError("Tas neizskatās pēc Google OAuth klienta JSON (vajag 'Desktop app' tipu).")
        cfg = self.cfg()
        cfg.google_credentials.parent.mkdir(parents=True, exist_ok=True)
        cfg.google_credentials.write_text(content, encoding="utf-8")
        return str(cfg.google_credentials)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "estudijas-sync"

        def log_message(self, fmt, *args):
            log.debug("web: " + fmt, *args)

        # ---- palīgi ----
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def _auth_ok(self) -> bool:
            return self._host_ok() and secrets.compare_digest(self.headers.get("X-Token", ""), app.token)

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("Pārāk liels pieprasījums")
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        # ---- GET ----
        def do_GET(self):
            u = urlparse(self.path)
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            if u.path in ("/", "/index.html"):
                html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                                  {"Content-Security-Policy":
                                   "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                                   "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                   "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'"})
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if not u.path.startswith("/api/"):
                return self._send(404, b"Not found", "text/plain")
            if not self._auth_ok():
                return self._json({"error": "unauthorized"}, 401)
            q = parse_qs(u.query)
            try:
                if u.path == "/api/status":
                    return self._json(app.status())
                if u.path == "/api/view":
                    return self._json(app.view())
                if u.path == "/api/config":
                    return self._json(app.config_dict())
                if u.path == "/api/files":
                    return self._json(app.recent_files())
                if u.path == "/api/doc":
                    return self._json({"text": app.doc(q.get("name", [""])[0])})
                if u.path == "/api/log":
                    return self._json({"text": app.log_tail()})
                if u.path == "/api/drive/detect":
                    from .drive import detect_folders
                    return self._json(detect_folders())
                if u.path == "/api/ics":
                    p = app.cfg().output_dir / "termini.ics"
                    if not p.exists():
                        return self._json({"error": "termini.ics vēl nav izveidots"}, 404)
                    return self._send(200, p.read_bytes(), "text/calendar; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="termini.ics"'})
            except Exception as e:
                log.exception("GET %s", u.path)
                return self._json({"error": str(e)}, 500)
            return self._json({"error": "not found"}, 404)

        # ---- POST ----
        def do_POST(self):
            u = urlparse(self.path)
            if not self._auth_ok():
                return self._json({"error": "unauthorized"}, 401)
            try:
                body = self._body()
                jobs = {"/api/job/sync": ("Sinhronizācija", app.job_sync),
                        "/api/job/login": ("Pieteikšanās", app.job_login),
                        "/api/job/gcal": ("Google Calendar", app.job_gcal),
                        "/api/job/update": ("Atjaunināšana", app.job_update)}
                if u.path in jobs:
                    ok, msg = app.start_job(*jobs[u.path])
                    return self._json({"ok": ok, "message": msg}, 200 if ok else 409)
                if u.path == "/api/config":
                    return self._json(app.save_config(body))
                if u.path == "/api/schedule":
                    from . import schedule
                    cfg = app.cfg()
                    msg = schedule.install(cfg) if body.get("enable") else schedule.uninstall(cfg)
                    return self._json({"ok": True, "message": msg, "installed": schedule.status(cfg)})
                if u.path == "/api/open":
                    return self._json({"ok": True, "path": app.open_path(str(body.get("path", "")))})
                if u.path == "/api/credentials":
                    return self._json({"ok": True, "path": app.save_credentials(str(body.get("content", "")))})
                if u.path == "/api/logout":
                    from .config import auth_path
                    auth_path(app.cfg()).unlink(missing_ok=True)
                    return self._json({"ok": True})
            except (ValueError, PermissionError, FileNotFoundError, json.JSONDecodeError) as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                log.exception("POST %s", u.path)
                return self._json({"ok": False, "error": str(e)}, 500)
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(profile: str, config_path: Path | None, port: int = 8765, open_browser: bool = True,
          ready: threading.Event | None = None, app_holder: list | None = None) -> None:
    app = App(profile, config_path)
    server = None
    for p in range(port, port + 15):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError(f"Nav brīva porta {port}–{port + 14}")
    app.port = server.server_address[1]
    url = f"http://127.0.0.1:{app.port}/"
    if app_holder is not None:
        app_holder.append(app)
    print(f"Web panelis: {url}\n(Ctrl+C, lai apturētu. Automātiskā sinhronizācija darbojas arī bez paneļa.)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if ready:
        ready.set()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        time.sleep(0.1)
