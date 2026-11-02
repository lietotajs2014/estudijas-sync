"""Web lapa: uvicorn server.app:app

Plūsma: Google pieteikšanās (allowlist) → panelis (tas pats, kas localhost, sk. panel.py) →
"Pieteikties" ar RTU kontu tieši lapā (ms_login.py) vai savienošanas kods no Android/PC → sinhronizācija serverī.
"""
from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import google_oauth
from .crypto import encrypt
from .db import GoogleLink, MoodleLink, PairingCode, User, get_db, init_db, utcnow
from .panel import panel_page, router as panel_router
from .moodle_link import LinkError, inspect_account, inspect_session, normalize_cookies, parse_token_input
from .runner import ics_path, load_view, user_dir
from .settings import settings

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
TZ = ZoneInfo(settings.timezone)

@asynccontextmanager
async def lifespan(_app):
    init_db()
    missing = settings.check()
    if missing:
        log.warning("Trūkst iestatījumu: %s", ", ".join(missing))
    yield


app = FastAPI(title="estudijas-sync", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key or secrets.token_hex(32),
                   session_cookie="es_session", max_age=30 * 24 * 3600, same_site="lax",
                   https_only=settings.secure_cookies)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
app.include_router(panel_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                            "form-action 'self' https://accounts.google.com; frame-ancestors 'none'; base-uri 'none'")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if settings.secure_cookies:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


# ---------------------------------------------------------------- palīgi

def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(24)
    return tok


def check_csrf(request: Request, csrf: str = Form("")) -> None:
    if not csrf or not secrets.compare_digest(csrf, request.session.get("csrf", "")):
        raise HTTPException(400, "Nederīgs formas žetons — atjauno lapu un mēģini vēlreiz.")


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if not user or not settings.email_allowed(user.email):
        request.session.clear()
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if not user:
        raise HTTPException(303, headers={"Location": "/"})
    return user


def render(request: Request, name: str, user: User | None = None, status: int = 200, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request),
                                                      "settings": settings, **ctx}, status_code=status)


def flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session["flash"] = {"msg": msg, "kind": kind}


def pop_flash(request: Request) -> dict | None:
    return request.session.pop("flash", None)


def _split(v: str) -> list[str]:
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


def _parse_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def dashboard_data(user: User) -> dict:
    view = load_view(user.id) or {}
    now = datetime.now(TZ)
    upcoming, overdue = [], []
    for d in view.get("deadlines", []) + view.get("text_dates", []):
        due = _parse_dt(d.get("due"))
        if not due:
            continue
        d = dict(d, due_dt=due)
        if due >= now and due <= now + timedelta(days=30):
            upcoming.append(d)
        elif due < now and not d.get("done") and due >= now - timedelta(days=21):
            overdue.append(d)
    upcoming.sort(key=lambda d: d["due_dt"])
    overdue.sort(key=lambda d: d["due_dt"])
    return {"view": view, "upcoming": upcoming[:40], "overdue": overdue, "now": now,
            "ics_url": f"{settings.base_url}/cal/{user.ics_secret}.ics",
            "has_ics": ics_path(user.id).exists()}


# ---------------------------------------------------------------- lapas

@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: User | None = Depends(current_user)):
    if not user:
        return render(request, "index.html", missing=settings.check(), flash=pop_flash(request))
    return panel_page(request, csrf_token(request))


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, user: User | None = Depends(current_user)):
    return render(request, "privacy.html", user)


@app.get("/login")
def login(request: Request):
    if settings.check():
        flash(request, "Serveris vēl nav pilnībā iestatīts.", "err")
        return RedirectResponse("/", 303)
    return RedirectResponse(google_oauth.start(request.session, "login"), 303)


@app.get("/auth/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = "",
                    db: Session = Depends(get_db)):
    if error or not code:
        flash(request, "Pieteikšanās atcelta.", "err")
        return RedirectResponse("/", 303)
    try:
        purpose, ident, tokens = google_oauth.finish(request.session, state, code)
    except google_oauth.OAuthError as e:
        flash(request, str(e), "err")
        return RedirectResponse("/", 303)
    email = ident.get("email", "").lower()

    if purpose in ("drive", "google"):
        user = db.get(User, request.session.get("uid") or 0)
        if not user or user.google_sub != ident.get("sub"):
            flash(request, "Google jāpieslēdz ar to pašu Google kontu, ar kuru esi pieteicies lapā.", "err")
            return RedirectResponse("/", 303)
        refresh = tokens.get("refresh_token")
        scopes = tokens.get("scope", "")
        has_drive, has_cal = google_oauth.DRIVE_SCOPE in scopes, google_oauth.CALENDAR_SCOPE in scopes
        if not refresh or not (has_drive or has_cal):
            flash(request, "Google nedeva atļauju. Mēģini vēlreiz un atzīmē Drive un kalendāru.", "err")
            return RedirectResponse("/", 303)
        if user.google:
            user.google.refresh_token_enc = encrypt(refresh)
            user.google.scopes = scopes
            user.google.linked = utcnow()
        else:
            db.add(GoogleLink(user_id=user.id, refresh_token_enc=encrypt(refresh), scopes=scopes))
        user.drive_enabled = has_drive
        p = dict(user.prefs or {})
        p["gcal_enabled"] = has_cal
        user.prefs = p
        if user.moodle and user.moodle.valid:
            user.sync_requested = True          # uzreiz aizpilda kalendāru un izveido Drive mapes
        db.commit()
        what = " un ".join(x for x, ok in (("Google Calendar", has_cal), ("Google Drive", has_drive)) if ok)
        flash(request, f"Pieslēgts {what}. Sinhronizēju — termiņi kalendārā parādīsies pēc pāris minūtēm.")
        return RedirectResponse("/", 303)

    if not settings.email_allowed(email):
        log.info("Atteikta pieteikšanās: %s", email)
        flash(request, f"Kontam {email} nav piekļuves. Palūdz administratoram tevi pievienot.", "err")
        return RedirectResponse("/", 303)
    user = db.scalar(select(User).where(User.google_sub == ident["sub"]))
    if not user:
        user = User(google_sub=ident["sub"], email=email, name=ident.get("name", ""))
        db.add(user)
    user.email, user.name, user.last_login = email, ident.get("name", user.name), utcnow()
    db.commit()
    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse("/", 303)


@app.post("/logout")
def logout(request: Request, _=Depends(check_csrf)):
    request.session.clear()
    return RedirectResponse("/", 303)


# ---- e-studiju pieslēgšana

PAIR_TTL = timedelta(minutes=10)
_pair_attempts: dict[str, list[float]] = {}


def _hash_code(code: str) -> str:
    import hashlib
    return hashlib.sha256(("pair:" + code).encode()).hexdigest()


def _save_link(db: Session, user: User, info: dict, *, mode: str, source: str, token: str | None = None,
               private: str | None = None, cookies: list[dict] | None = None) -> None:
    detected = {k: info[k] for k in ("program", "group", "program_candidates", "group_candidates")}
    detected["courses"] = [{"name": c["name"], "groups": c.get("groups", [])} for c in info["courses"]]
    link = user.moodle or MoodleLink(user_id=user.id)
    link.mode, link.source = mode, source
    link.token_enc = encrypt(token) or ""
    link.privatetoken_enc = encrypt(private)
    link.cookies_enc = encrypt(json.dumps(cookies)) if cookies else None
    link.moodle_userid, link.fullname, link.detected = info["userid"], info["fullname"] or link.fullname or "", detected
    link.valid, link.linked = True, utcnow()
    if not user.program and info.get("program"):   # atpazītais — lietotājs var izlabot iestatījumos
        user.program = info["program"]
    if not user.group and info.get("group"):
        user.group = info["group"]
    if not user.moodle:
        db.add(link)
    user.last_error = None
    user.sync_requested = True
    db.commit()


@app.get("/connect", response_class=HTMLResponse)
def connect_page(request: Request, user: User = Depends(require_user)):
    pair = request.session.get("pair")
    if pair and datetime.fromisoformat(pair["expires"]) < datetime.now(TZ):
        pair = request.session["pair"] = None
    return render(request, "connect.html", user, flash=pop_flash(request), site=settings.moodle_site, pair=pair)


@app.post("/connect/code")
def connect_code(request: Request, _=Depends(check_csrf), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    db.query(PairingCode).filter(PairingCode.user_id == user.id).delete()
    for _try in range(20):
        code = f"{secrets.randbelow(10**6):06d}"
        if not db.scalar(select(PairingCode).where(PairingCode.code_hash == _hash_code(code))):
            break
    expires = utcnow() + PAIR_TTL
    db.add(PairingCode(user_id=user.id, code_hash=_hash_code(code), expires=expires))
    db.commit()
    request.session["pair"] = {"code": f"{code[:3]} {code[3:]}", "expires": expires.astimezone(TZ).isoformat(),
                               "started": utcnow().isoformat()}
    return RedirectResponse("/connect", 303)


@app.get("/connect/status")
def connect_status(request: Request, user: User = Depends(require_user)):
    pair = request.session.get("pair") or {}
    link = user.moodle
    started = datetime.fromisoformat(pair["started"]) if pair.get("started") else None
    linked = bool(link and link.valid and started and link.linked and
                  link.linked.replace(tzinfo=link.linked.tzinfo or started.tzinfo) >= started)
    if linked:
        request.session.pop("pair", None)
        request.session.pop("confirmed", None)
    return {"linked": linked}


@app.post("/api/pair")
def api_pair(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    """Android lietotne / PC programma: {code, cookies:[...], source}. Bez sesijas sīkdatnēm — aizsargā kods."""
    import time as _time
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    now = _time.time()
    hits = [t for t in _pair_attempts.get(ip, []) if now - t < 600]
    if len(hits) >= 20:
        return JSONResponse({"ok": False, "error": "Pārāk daudz mēģinājumu. Pagaidi 10 minūtes."}, 429)
    _pair_attempts[ip] = hits + [now]
    if int(request.headers.get("content-length") or 0) > 512_000:
        return JSONResponse({"ok": False, "error": "Pārāk liels pieprasījums."}, 413)

    code = "".join(ch for ch in str(body.get("code", "")) if ch.isdigit())
    row = db.scalar(select(PairingCode).where(PairingCode.code_hash == _hash_code(code))) if len(code) == 6 else None
    if not row or row.used or row.expires.replace(tzinfo=row.expires.tzinfo or timezone.utc) < utcnow():
        return JSONResponse({"ok": False, "error": "Kods nav derīgs vai ir beidzies. Izveido jaunu lapā."}, 400)
    user = db.get(User, row.user_id)
    if not user or not settings.email_allowed(user.email):
        return JSONResponse({"ok": False, "error": "Konts nav atrasts."}, 400)
    source = str(body.get("source", ""))[:20] or "app"
    try:
        cookies = normalize_cookies(body.get("cookies"), settings.moodle_site)
        info = inspect_session(settings.moodle_site, cookies)
    except LinkError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)
    row.used = True
    _save_link(db, user, info, mode="web", source=source, cookies=cookies)
    log.info("user %s: e-studijas pieslēgtas no %s", user.id, source)
    return {"ok": True, "fullname": info["fullname"], "account": user.email}


@app.post("/connect")
def connect_submit(request: Request, token: str = Form(""), _=Depends(check_csrf),
                   user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        tok, private = parse_token_input(token, settings.moodle_site)
        info = inspect_account(settings.moodle_site, tok)
    except LinkError as e:
        flash(request, str(e), "err")
        return RedirectResponse("/connect", 303)
    _save_link(db, user, info, mode="api", source="token", token=tok, private=private)
    request.session.pop("confirmed", None)
    return RedirectResponse("/confirm", 303)


@app.get("/confirm", response_class=HTMLResponse)
def confirm_page(request: Request, user: User = Depends(require_user)):
    if not user.moodle:
        return RedirectResponse("/connect", 303)
    det = user.moodle.detected or {}
    return render(request, "confirm.html", user, det=det, fullname=user.moodle.fullname,
                  program=user.program or det.get("program", ""), group=user.group or det.get("group", ""))


@app.post("/confirm")
def confirm_submit(request: Request, program: str = Form(""), group: str = Form(""),
                   extra_groups: str = Form(""), _=Depends(check_csrf),
                   user: User = Depends(require_user), db: Session = Depends(get_db)):
    user.program = program.strip().upper()[:20]
    user.group = group.strip().lower().replace("grupa", "").replace("gr", "").strip(" .")[:10]
    user.extra_groups = _split(extra_groups)[:10]
    user.sync_requested = True
    db.commit()
    request.session["confirmed"] = True
    flash(request, "Saglabāts. Pirmā sinhronizācija sākas — tā var aizņemt dažas minūtes.")
    return RedirectResponse("/", 303)


# ---- darbības

@app.post("/sync")
def sync_now(request: Request, _=Depends(check_csrf), user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    user.sync_requested = True
    db.commit()
    flash(request, "Sinhronizācija ielikta rindā. Atjauno lapu pēc minūtes.")
    return RedirectResponse("/", 303)


@app.get("/settings")
def settings_page(request: Request, user: User = Depends(require_user)):
    request.session["tab"] = "iestatijumi"
    return RedirectResponse("/", 303)


@app.post("/settings")
def settings_submit(request: Request, program: str = Form(""), group: str = Form(""),
                    extra_groups: str = Form(""), exclude_courses: str = Form(""),
                    drive_categories: str = Form(""), drive_enabled: str = Form(""),
                    _=Depends(check_csrf), user: User = Depends(require_user), db: Session = Depends(get_db)):
    user.program = program.strip().upper()[:20]
    user.group = group.strip().lower().replace("grupa", "").replace("gr", "").strip(" .")[:10]
    user.extra_groups = _split(extra_groups)[:10]
    user.exclude_courses = _split(exclude_courses)[:30]
    user.drive_categories = _split(drive_categories)[:15] or ["Mājas darbi"]
    user.drive_enabled = bool(drive_enabled) and user.google is not None
    db.commit()
    flash(request, "Iestatījumi saglabāti.")
    return RedirectResponse("/settings", 303)


@app.post("/settings/drive/connect")
@app.post("/settings/google/connect")
def google_connect(request: Request, _=Depends(check_csrf), user: User = Depends(require_user)):
    return RedirectResponse(google_oauth.start(request.session, "google"), 303)


@app.post("/settings/drive/disconnect")
@app.post("/settings/google/disconnect")
def drive_disconnect(request: Request, _=Depends(check_csrf), user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    if user.google:
        db.delete(user.google)
    user.drive_enabled = False
    user.prefs = {**(user.prefs or {}), "gcal_enabled": False}
    db.commit()
    flash(request, "Google atvienots (Drive un kalendārs). Pilnībā atsaukt piekļuvi var myaccount.google.com → Security → Third-party apps.")
    return RedirectResponse("/settings", 303)


@app.post("/settings/moodle/disconnect")
def moodle_disconnect(request: Request, _=Depends(check_csrf), user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    if user.moodle:
        db.delete(user.moodle)
        db.commit()
    flash(request, "E-studijas atvienotas, sesija no servera izdzēsta.")
    return RedirectResponse("/settings", 303)


@app.post("/settings/ics/reset")
def ics_reset(request: Request, _=Depends(check_csrf), user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    user.ics_secret = secrets.token_urlsafe(32)
    db.commit()
    flash(request, "Kalendāra saite nomainīta. Vecā vairs nestrādā — pievieno jauno Google Calendar.")
    return RedirectResponse("/settings", 303)


@app.post("/settings/delete")
def delete_account(request: Request, confirm: str = Form(""), _=Depends(check_csrf),
                   user: User = Depends(require_user), db: Session = Depends(get_db)):
    if confirm.strip().lower() != "dzēst":
        flash(request, "Lai dzēstu kontu, ieraksti “dzēst”.", "err")
        return RedirectResponse("/settings", 303)
    import shutil
    shutil.rmtree(user_dir(user.id), ignore_errors=True)
    db.delete(user)
    db.commit()
    request.session.clear()
    flash(request, "Konts un visi dati dzēsti.")
    return RedirectResponse("/", 303)


# ---- kalendārs (bez pieteikšanās; aizsargā slepenais identifikators saitē)

@app.get("/cal/{secret}.ics")
def calendar_feed(secret: str, download: int = 0, db: Session = Depends(get_db)):
    if len(secret) < 20:
        raise HTTPException(404)
    user = db.scalar(select(User).where(User.ics_secret == secret))
    if not user or not settings.email_allowed(user.email):
        raise HTTPException(404)
    p = ics_path(user.id)
    headers = {"Cache-Control": "private, max-age=900"}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="termini.ics"'
    if not p.exists():
        return Response("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//estudijas-sync//LV\r\nEND:VCALENDAR\r\n",
                        media_type="text/calendar; charset=utf-8", headers=headers)
    return FileResponse(p, media_type="text/calendar; charset=utf-8", headers=headers)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], 303)
    return render(request, "error.html", None, status=exc.status_code,
                  message=exc.detail if isinstance(exc.detail, str) else "Kļūda")
