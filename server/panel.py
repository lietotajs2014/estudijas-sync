"""Tas pats panelis kā localhost (estudijas_sync/web/index.html), tikai dati ir serverī un katram lietotājam savi.

Atšķirības no localhost:
- dokumenti netiek lejupielādēti automātiski: sinhronizācija tos tikai uzskaita, serveris ielādē tikai
  atzīmētos (tad tos var atvērt lapā, saglabāt ZIP vai tie nonāk Google Drive);
- e-studijas pieslēdz ar RTU pieteikšanos tieši lapā (ms_login.py), dators nav vajadzīgs;
- nav darbvirsmas lietu (mapes izvēle, Explorer, plānotājs, atjaunināšana no GitHub).

Aizsardzība: Google pieteikšanās sesija + X-Token galvene (= CSRF žetons sesijā) visiem /api/ pieprasījumiem,
izņemot tikai lasāmos failu atvēršanas GET (tos sedz sesijas sīkdatne ar SameSite=Lax).
"""
from __future__ import annotations

import io
import json
import logging
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from .db import SessionLocal, User, get_db
from .gdrive import folder_url, has_scope
from .google_oauth import CALENDAR_SCOPE, DRIVE_SCOPE
from .runner import build_config, ics_path, load_view, prefs, read_job, user_dir
from .settings import settings

log = logging.getLogger(__name__)
router = APIRouter()
PANEL_HTML = Path(__file__).resolve().parent.parent / "estudijas_sync" / "web" / "index.html"
HELP_MD = Path(__file__).with_name("HELP.md")

PANEL_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
             "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
             "img-src 'self' data: blob:; connect-src 'self'; form-action 'self' https://accounts.google.com; "
             "frame-ancestors 'none'; base-uri 'none'")


# ---------------------------------------------------------------- piekļuve

def _session_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user or not user.allowed:
        return None
    return user


def api_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_user(request, db)
    if not user:
        raise HTTPException(401, "Sesija beigusies. Pārlādē lapu un piesakies vēlreiz.")
    tok = request.headers.get("x-token", "")
    if not tok or not secrets.compare_digest(tok, request.session.get("csrf", "")):
        raise HTTPException(401, "Lapa ir novecojusi. Pārlādē to.")
    return user


def view_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_user(request, db)
    if not user:
        raise HTTPException(401, "Sesija beigusies. Pārlādē lapu un piesakies vēlreiz.")
    return user


def panel_page(request: Request, csrf: str) -> HTMLResponse:
    html = PANEL_HTML.read_text(encoding="utf-8").replace("__TOKEN__", csrf).replace("__MODE__", "web")
    return HTMLResponse(html, headers={"Content-Security-Policy": PANEL_CSP, "Cache-Control": "no-store"})


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")


# ---------------------------------------------------------------- stāvoklis

IDLE_PROGRESS = {"active": False, "title": "", "count": 0, "total": 0, "bytes_done": 0, "bytes_total": 0,
                 "label": "", "percent": 0, "lines": []}


def status_dict(user: User) -> dict:
    from estudijas_sync import __version__

    link = user.moodle
    jobinfo = read_job(user.id)
    job = jobinfo.get("job")
    if job:   # worker nobrucis darba vidū — neturam pogu bloķētu mūžīgi
        try:
            if datetime.now(timezone.utc) - datetime.fromisoformat(job["started"]) > timedelta(hours=2):
                job = None
        except (KeyError, ValueError, TypeError):
            job = None
    progress = jobinfo.get("progress") or IDLE_PROGRESS
    if not job and link and link.valid and (user.sync_requested or user.download_requested):
        job = {"name": "Lejupielāde" if user.download_requested and not user.sync_requested else "Sinhronizācija",
               "queued": True}
        progress = dict(IDLE_PROGRESS, lines=["Rindā — sāksies pēc dažām sekundēm…"])
    p = prefs(user)
    return {
        "version": __version__, "git_version": "", "mode": "web",
        "auth": {"mode": link.mode if link and link.valid else None, "obtained": _iso(link.linked) if link else None,
                 "fullname": link.fullname if link else None, "source": link.source if link else None,
                 "expired": bool(link and not link.valid)},
        "last_run": _iso(user.last_sync), "last_error": user.last_error,
        "job": job, "last_job": jobinfo.get("last_job"), "progress": progress,
        "output_dir": "serverī (tikai atzīmētie faili)",
        "account": {"email": user.email, "name": user.name},
        "test_mode": user.is_test,
        "rtu_email": p.get("rtu_email", ""),
        "drive": {"connected": has_scope(user, DRIVE_SCOPE), "enabled": bool(user.drive_enabled and has_scope(user, DRIVE_SCOPE)),
                  "folder_url": folder_url(build_config(user)) if user.google else ""},
        "gcal": {"connected": has_scope(user, CALENDAR_SCOPE),
                 "enabled": bool(p.get("gcal_enabled") and has_scope(user, CALENDAR_SCOPE))},
        "google": {"connected": user.google is not None},
        "ics_download": f"{settings.base_url}/cal/{user.ics_secret}.ics?download=1",
        "ics_url": f"{settings.base_url}/cal/{user.ics_secret}.ics",
        "schedule": {"installed": True, "times": settings.schedule_times},
        "warnings": list((user.last_result or {}).get("warning_list") or []),
    }


@router.get("/api/status")
def api_status(request: Request, user: User = Depends(api_user)):
    out = status_dict(user)
    out["flash"] = request.session.pop("flash", None)     # paziņojumi pēc Google Drive / formu darbībām
    out["tab"] = request.session.pop("tab", None)
    return out


@router.get("/api/view")
def api_view(user: User = Depends(api_user)):
    return load_view(user.id) or {}


def _files(user: User) -> dict:
    from estudijas_sync.config import State

    cfg = build_config(user)
    rows = (load_view(user.id) or {}).get("files") or []
    st = State(cfg.data_dir / "state.json").files
    for r in rows:
        e = st.get(r["key"])
        if e and e.get("path"):
            r["path"] = e["path"]
            if e.get("manual"):
                r["status"] = "downloaded"
        r["exists"] = bool(r.get("path")) and r.get("status") == "downloaded" and (cfg.output_dir / r["path"]).is_file()
        if r.get("status") == "downloaded" and not r["exists"]:
            r["status"] = "available"        # serverī vairs nav (piem., dzēsts) — var ielādēt no jauna
    return {"output_dir": "serverī", "exists": True, "files": rows}


@router.get("/api/files")
def api_files(user: User = Depends(api_user)):
    return _files(user)


@router.get("/api/doc")
def api_doc(name: str = "", user: User = Depends(api_user)):
    if name == "README":
        return {"text": HELP_MD.read_text(encoding="utf-8") if HELP_MD.exists() else ""}
    p = {"UZDEVUMI": user_dir(user.id) / "UZDEVUMI.md", "JAUNUMI": user_dir(user.id) / "JAUNUMI.md"}.get(name)
    return {"text": p.read_text(encoding="utf-8") if p and p.exists() else ""}


@router.get("/api/log")
def api_log(user: User = Depends(api_user)):
    parts = []
    if user.last_error:
        parts.append(f"Pēdējā kļūda: {user.last_error}")
    res = user.last_result or {}
    if res:
        parts.append("Pēdējā sinhronizācija: " + ", ".join(
            f"{k}: {res[k]}" for k in ("courses", "deadlines", "files", "drive_uploaded") if k in res))
        parts += [f"Brīdinājums: {w}" for w in res.get("warning_list") or []]
    return {"text": "\n".join(parts)}


@router.get("/api/ics")
def api_ics(user: User = Depends(api_user)):
    p = ics_path(user.id)
    if not p.exists():
        return JSONResponse({"error": "termini.ics vēl nav izveidots — sinhronizē vispirms"}, 404)
    return FileResponse(p, media_type="text/calendar; charset=utf-8", filename="termini.ics")


# ---------------------------------------------------------------- iestatījumi

def config_dict(user: User) -> dict:
    cfg = build_config(user)
    p = prefs(user)
    vals = {
        "email": p.get("rtu_email", ""), "program": user.program or "", "group": user.group or "",
        "extra_groups": list(user.extra_groups or []),
        "other_groups": p["other_groups"], "exclude_courses": list(user.exclude_courses or []),
        "only_categories": list(p["only_categories"]), "lookahead_days": int(p["lookahead_days"]),
        "download_max_mb": float(p["download_max_mb"]), "include_text_dates": bool(p["include_text_dates"]),
        "reminders_minutes": list(p["reminders_minutes"]),
        "drive_enabled": bool(user.drive_enabled and user.google), "output_dir": "serverī",
        "gcal_enabled": bool(p.get("gcal_enabled") and has_scope(user, CALENDAR_SCOPE)),
    }
    cats = list(cfg.categories) + ["Lekcijas", "Uzdevumi", "Citi"]
    return {"values": vals, "categories": list(dict.fromkeys(cats))}


@router.get("/api/config")
def api_config(user: User = Depends(api_user)):
    return config_dict(user)


@router.post("/api/config")
def api_config_save(body: dict = Body(...), user: User = Depends(api_user), db: Session = Depends(get_db)):
    from estudijas_sync.webui import _coerce

    try:
        p = dict(user.prefs or {})
        if "email" in body:
            p["rtu_email"] = _coerce("str", body["email"])[:200]
        if "program" in body:
            user.program = _coerce("upper", body["program"])[:20]
        if "group" in body:
            user.group = _coerce("group", body["group"])[:10]
        if "extra_groups" in body:
            user.extra_groups = _coerce("list", body["extra_groups"])[:10]
        if "exclude_courses" in body:
            user.exclude_courses = _coerce("list", body["exclude_courses"])[:30]
        for k, kind in (("other_groups", "other"), ("only_categories", "list"), ("lookahead_days", "int"),
                        ("download_max_mb", "float"), ("include_text_dates", "bool"), ("reminders_minutes", "intlist")):
            if k in body:
                p[k] = _coerce(kind, body[k])
        p["lookahead_days"] = max(7, min(int(p.get("lookahead_days", 150)), 400))
        p["download_max_mb"] = max(1.0, min(float(p.get("download_max_mb", 200)), 500.0))
        # atgādinājumi: cik grib (ICS visi; Google kalendārā tuvākie 5), līdz 28 dienām
        p["reminders_minutes"] = sorted({m for m in p.get("reminders_minutes", [1440, 120]) if 0 <= m <= 40320},
                                        reverse=True)[:20]
        if "gcal_enabled" in body:
            p["gcal_enabled"] = bool(body["gcal_enabled"]) and has_scope(user, CALENDAR_SCOPE)
        if "drive_enabled" in body:
            user.drive_enabled = bool(body["drive_enabled"]) and user.google is not None
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    user.prefs = p
    db.commit()
    return config_dict(user)


# ---------------------------------------------------------------- darbības

@router.post("/api/job/sync")
def api_sync(user: User = Depends(api_user), db: Session = Depends(get_db)):
    if not (user.moodle and user.moodle.valid):
        return JSONResponse({"ok": False, "error": "Vispirms piesakies ar RTU kontu."}, 400)
    if status_dict(user)["job"]:
        return JSONResponse({"ok": False, "error": "Jau notiek sinhronizācija."}, 409)
    user.sync_requested = True
    db.commit()
    return {"ok": True, "message": "Rindā"}


@router.post("/api/download")
def api_download(body: dict = Body(...), user: User = Depends(api_user), db: Session = Depends(get_db)):
    keys = [str(k) for k in body.get("keys", [])][:500]
    if not keys:
        return JSONResponse({"ok": False, "error": "Nav atzīmēts neviens fails"}, 400)
    if not (user.moodle and user.moodle.valid):
        return JSONResponse({"ok": False, "error": "Vispirms piesakies ar RTU kontu."}, 400)
    user.download_requested = list(dict.fromkeys(list(user.download_requested or []) + keys))[:2000]
    db.commit()
    return {"ok": True, "message": "Rindā"}


@router.post("/api/logout")
def api_forget(user: User = Depends(api_user), db: Session = Depends(get_db)):
    """“Aizmirst piekļuvi”: izdzēš e-studiju sesiju no servera (dati un faili paliek)."""
    if user.moodle:
        db.delete(user.moodle)
        db.commit()
    return {"ok": True}


def _safe_file(user: User, rel: str) -> Path:
    base = user_dir(user.id).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or any(part.startswith(".") for part in target.relative_to(base).parts):
        raise HTTPException(404, "Fails nav atrasts")
    if not target.is_file():
        raise HTTPException(404, "Fails serverī nav ielādēts. Atzīmē to un spied “Ielādēt atzīmētos”.")
    return target


@router.get("/api/file")
def api_file(path: str = "", download: int = 0, user: User = Depends(view_user)):
    target = _safe_file(user, path)
    return FileResponse(target, filename=target.name, content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@router.post("/api/zip")
def api_zip(body: dict = Body(...), user: User = Depends(api_user)):
    keys = {str(k) for k in body.get("keys", [])}
    rows = [r for r in _files(user)["files"] if r["key"] in keys and r.get("exists")]
    if not rows:
        return JSONResponse({"ok": False, "error": "Neviens no atzīmētajiem failiem vēl nav ielādēts serverī."}, 400)
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in rows:
            p = _safe_file(user, r["path"])
            total += p.stat().st_size
            if total > 400 * 2**20:
                break
            z.write(p, r["path"])
    name = f"estudijas-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------- RTU pieteikšanās lapā

def _on_login_success(user_id: int, cookies: list[dict], info: dict) -> str:
    from .app import _save_link

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise RuntimeError("Konts nav atrasts.")
        _save_link(db, user, info, mode="web", source="lapa", cookies=cookies)
        return info.get("fullname") or ""


@router.post("/api/ms/start")
def ms_start(body: dict = Body(...), user: User = Depends(api_user), db: Session = Depends(get_db)):
    from .ms_login import registry

    email = str(body.get("email") or prefs(user).get("rtu_email") or "").strip()[:200]
    if email:
        p = dict(user.prefs or {})
        p["rtu_email"] = email
        user.prefs = p
        db.commit()
    try:
        s = registry.start(user.id, email, settings.moodle_site, _on_login_success)
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 429)
    return {"ok": True, **s.snapshot()}


@router.get("/api/ms/state")
def ms_state(shot: int = 0, user: User = Depends(api_user)):
    from .ms_login import registry

    s = registry.get(user.id)
    if not s:
        return {"step": "none"}
    return s.snapshot(with_shot=bool(shot))


@router.post("/api/ms/input")
def ms_input(body: dict = Body(...), user: User = Depends(api_user)):
    from .ms_login import registry

    s = registry.get(user.id)
    if not s or not s.active:
        return JSONResponse({"ok": False, "error": "Pieteikšanās vairs nav aktīva. Sāc no jauna."}, 400)
    a = str(body.get("a", ""))
    if a not in ("email", "password", "otp", "choose", "other", "click", "type", "key", "back", "cancel", "shot"):
        return JSONResponse({"ok": False, "error": "Nezināma darbība"}, 400)
    cmd = {"a": a, "v": body.get("v"), "i": body.get("i"), "x": body.get("x"), "y": body.get("y"), "on": body.get("on")}
    s.send({k: v for k, v in cmd.items() if v is not None})
    return {"ok": True}
