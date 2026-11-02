"""Viena lietotāja sinhronizācija serverī, izmantojot to pašu kodolu, ko darbvirsmas versija.

Katram lietotājam sava mape DATA_DIR/users/<id>/ (faili, termini.ics, view.json, state.json).
Žetons tiek atšifrēts tikai atmiņā un padots run_sync(auth=...) — uz diska tas netiek rakstīts.
"""
from __future__ import annotations

import json
import logging
import os
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


def build_config(user: User):
    """Config objekts bez darbvirsmas lietām (paziņojumi, pārlūka logs, lokālais Google Calendar)."""
    os.environ.setdefault("ESTUDIJAS_SYNC_HOME", str(settings.data_dir / "app_home"))
    from estudijas_sync import config as core

    out = user_dir(user.id)
    data = out / core.DATA_DIRNAME
    data.mkdir(parents=True, exist_ok=True)
    cfg = core.load_config(f"user{user.id}", data / "config.toml")
    return replace(
        cfg, data_dir=data, config_path=data / "config.toml", site=settings.moodle_site, output_dir=out, timezone=settings.timezone,
        program=user.program or "", group=user.group or "",
        my_groups=[str(g) for g in (user.extra_groups or [])],
        exclude_courses=list(user.exclude_courses or []),
        notify=False, login_popup=False, google=False, drive_enabled=False, ics=True,
    )


def sync_user(db: Session, user: User) -> dict:
    from estudijas_sync.model import LoginRequired
    from estudijas_sync.sync import run_sync

    link = user.moodle
    if not link or not link.valid:
        raise RuntimeError("E-studijas nav pieslēgtas.")
    token = decrypt(link.token_enc)
    if not token:
        raise RuntimeError("Žetonu neizdevās atšifrēt (vai ENCRYPTION_KEY ir mainīts?).")
    auth = {"mode": "api", "token": token, "privatetoken": decrypt(link.privatetoken_enc),
            "userid": link.moodle_userid, "fullname": link.fullname}
    cfg = build_config(user)
    try:
        res = run_sync(cfg, no_calendar=True, interactive=False, auth=auth)
    except LoginRequired as e:
        link.valid = False
        user.last_error = f"E-studiju žetons vairs nav derīgs — pieslēdz e-studijas no jauna. ({e})"
        user.last_sync = datetime.now(timezone.utc)
        db.commit()
        raise
    warnings = list(res.pop("warning_list", []) or [])
    if user.drive_enabled and user.google:
        try:
            from .gdrive import mirror
            res["drive_uploaded"] = mirror(user, cfg)
        except Exception as e:
            log.exception("Drive (user %s)", user.id)
            warnings.append(f"Google Drive: {e}")
    res["warning_list"] = warnings
    res.pop("output", None)
    user.last_result = json.loads(json.dumps(res, default=str))
    user.last_error = None
    user.last_sync = datetime.now(timezone.utc)
    db.commit()
    return res
