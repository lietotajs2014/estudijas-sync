"""Viena lietotāja sinhronizācija serverī, izmantojot to pašu kodolu, ko darbvirsmas versija.

Katram lietotājam sava mape DATA_DIR/users/<id>/ (faili, termini.ics, view.json, state.json).
Žetons tiek atšifrēts tikai atmiņā un padots run_sync(auth=...) — uz diska tas netiek rakstīts.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .crypto import decrypt
from .db import User
from .settings import settings

log = logging.getLogger(__name__)


def user_dir(user_id: int) -> Path:
    return settings.data_dir / "users" / str(int(user_id))


def ics_path(user_id: int) -> Path:
    return user_dir(user_id) / "termini.ics"


def view_path(user_id: int) -> Path:
    return user_dir(user_id) / ".estudijas-sync" / "view.json"


def load_view(user_id: int) -> dict | None:
    try:
        return json.loads(view_path(user_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def prefs(user: User) -> dict:
    """Lietotāja papildu iestatījumi (tie paši, kas localhost panelī) ar noklusējumiem."""
    p = dict(user.prefs or {})
    p.setdefault("other_groups", "skip")
    p.setdefault("only_categories", [])
    p.setdefault("download_max_mb", 200)
    p.setdefault("lookahead_days", 150)
    p.setdefault("include_text_dates", True)
    p.setdefault("reminders_minutes", [1440, 120])
    return p


def build_config(user: User):
    """Config objekts bez darbvirsmas lietām (paziņojumi, pārlūka logs, lokālais Google Calendar).
    auto_download=False: sinhronizācija dokumentus tikai uzskaita, lejupielādē tikai atzīmētos."""
    os.environ.setdefault("ESTUDIJAS_SYNC_HOME", str(settings.data_dir / "app_home"))
    from estudijas_sync import config as core

    out = user_dir(user.id)
    data = out / core.DATA_DIRNAME
    data.mkdir(parents=True, exist_ok=True)
    cfg = core.load_config(f"user{user.id}", data / "config.toml")
    p = prefs(user)
    return replace(
        cfg, data_dir=data, config_path=data / "config.toml", site=settings.moodle_site, output_dir=out, timezone=settings.timezone,
        program=user.program or "", group=user.group or "",
        my_groups=[str(g) for g in (user.extra_groups or [])],
        exclude_courses=list(user.exclude_courses or []),
        other_groups=p["other_groups"], only_categories=list(p["only_categories"]),
        download_max_mb=float(p["download_max_mb"]), lookahead_days=int(p["lookahead_days"]),
        include_text_dates=bool(p["include_text_dates"]), reminders_minutes=[int(x) for x in p["reminders_minutes"]],
        notify=False, login_popup=False, google=False, drive_enabled=False, ics=True, auto_download=False,
    )


# ---------------------------------------------------------------- progress un darba stāvoklis (lapai)

def job_path(user_id: int) -> Path:
    return user_dir(user_id) / ".estudijas-sync" / "job.json"


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def read_job(user_id: int) -> dict:
    """{"job": {...} vai None, "last_job": {...} vai None, "progress": {...}}"""
    try:
        return json.loads(job_path(user_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


class FileProgress:
    """Tāds pats progress kā localhost panelī, bet worker to ieraksta failā, ko nolasa web process."""

    def __init__(self, user_id: int, name: str):
        from estudijas_sync.webui import WebProgress

        self.user_id, self.name = user_id, name
        self.started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prev = read_job(user_id).get("last_job")
        self.last_job = prev
        outer = self

        class _P(WebProgress):
            def _draw(self, force: bool = False) -> None:
                outer.flush(force)

            def _write(self, text: str, end: str = "") -> None:
                super()._write(text, end)
                outer.flush(True)

        self.prog = _P()
        self._last = 0.0
        self.flush(True)

    def flush(self, force: bool = False) -> None:
        import time
        now = time.time()
        if not force and now - self._last < 0.7:
            return
        self._last = now
        try:
            _write_json(job_path(self.user_id), {"job": {"name": self.name, "started": self.started},
                                                 "last_job": self.last_job, "progress": self.prog.snapshot()})
        except OSError:
            pass

    def done(self, ok: bool, message: str) -> None:
        self.last_job = {"name": self.name, "started": self.started, "ok": ok, "message": message,
                         "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            _write_json(job_path(self.user_id), {"job": None, "last_job": self.last_job, "progress": self.prog.snapshot()})
        except OSError:
            pass


# ---------------------------------------------------------------- e-studiju piekļuve uz darba laiku

@contextmanager
def moodle_auth(db: Session, user: User, cfg):
    """Atšifrē piekļuvi tikai uz darba laiku.
    Pārlūka režīms: sīkdatnes ieliek failā, pēc darba atjaunotās (Moodle pagarina sesiju) atkal šifrē DB,
    failu un pārlūka profilu dzēš. API režīms: žetons tikai atmiņā."""
    import shutil

    from .crypto import encrypt

    link = user.moodle
    if not link or not link.valid:
        raise RuntimeError("E-studijas nav pieslēgtas.")
    if link.mode != "web":
        token = decrypt(link.token_enc)
        if not token:
            raise RuntimeError("Žetonu neizdevās atšifrēt (vai ENCRYPTION_KEY ir mainīts?).")
        yield {"mode": "api", "token": token, "privatetoken": decrypt(link.privatetoken_enc),
               "userid": link.moodle_userid, "fullname": link.fullname}
        return
    raw = decrypt(link.cookies_enc)
    if not raw:
        raise RuntimeError("Sesiju neizdevās atšifrēt (vai ENCRYPTION_KEY ir mainīts?).")
    cookie_file = cfg.data_dir / "cookies.json"
    cookie_file.write_text(raw, encoding="utf-8")
    os.chmod(cookie_file, 0o600)
    try:
        yield {"mode": "web"}
    finally:
        try:
            fresh = cookie_file.read_text(encoding="utf-8")
            if fresh.strip().startswith("[") and fresh != raw:
                link.cookies_enc = encrypt(fresh)
                db.commit()
        except OSError:
            pass
        cookie_file.unlink(missing_ok=True)
        shutil.rmtree(cfg.data_dir / "browser", ignore_errors=True)


def _login_expired(db: Session, user: User) -> None:
    link = user.moodle
    link.valid = False
    user.last_error = ("E-studiju piekļuve beigusies. Iestatījumos spied “Pieteikties no jauna” "
                       "(pietiek ar telefonu, dators nav vajadzīgs).")
    user.last_sync = datetime.now(timezone.utc)
    db.commit()


def _drive(user: User, cfg, warnings: list) -> int | None:
    if not (user.drive_enabled and user.google):
        return None
    try:
        from .gdrive import mirror
        return mirror(user, cfg)
    except Exception as e:
        log.exception("Drive (user %s)", user.id)
        warnings.append(f"Google Drive: {e}")
        return None


def sync_user(db: Session, user: User, prog=None) -> dict:
    from estudijas_sync.model import LoginRequired
    from estudijas_sync.sync import run_sync

    cfg = build_config(user)
    try:
        with moodle_auth(db, user, cfg) as auth:
            res = run_sync(cfg, no_calendar=True, interactive=False, auth=auth, prog=prog)
    except LoginRequired:
        _login_expired(db, user)
        raise
    warnings = list(res.pop("warning_list", []) or [])
    up = _drive(user, cfg, warnings)
    if up is not None:
        res["drive_uploaded"] = up
    res["warning_list"] = warnings
    res.pop("output", None)
    user.last_result = json.loads(json.dumps(res, default=str))
    user.last_error = None
    user.last_sync = datetime.now(timezone.utc)
    db.commit()
    return res


def download_for_user(db: Session, user: User, keys: list[str], prog=None) -> dict:
    """Lejupielādē lietotāja atzīmētos failus serverī (pēc tam tos var lejupielādēt no lapas / Drive)."""
    from estudijas_sync.model import LoginRequired
    from estudijas_sync.sync import download_selected

    cfg = build_config(user)
    try:
        with moodle_auth(db, user, cfg) as auth:
            res = download_selected(cfg, keys, prog=prog, interactive=False, auth=auth)
    except LoginRequired:
        _login_expired(db, user)
        raise
    warnings: list[str] = []
    up = _drive(user, cfg, warnings)
    res["drive_uploaded"] = up
    res["warnings"] = warnings
    return res
