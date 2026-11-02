"""Neobligāta sinhronizācija ar Google Calendar (atsevišķā kalendārā)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

from .config import Config, State
from .model import Course, Deadline
from .outputs import event_description, event_span, summary_line

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/calendar"]
COLORS = {"KD": "11", "Eksāmens": "11", "Tests": "6", "MD": "9", "LD": "10", "PD": "10"}


class GCalNotAuthorized(Exception):
    pass


def get_service(cfg: Config, interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GCalNotAuthorized("Nav instalētas Google bibliotēkas: pip install -r requirements-google.txt") from e
    tok = cfg.data_dir / "google_token.json"
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            if not cfg.google_credentials.exists():
                raise GCalNotAuthorized(f"Nav atrasts {cfg.google_credentials} (skat. README).")
            flow = InstalledAppFlow.from_client_secrets_file(str(cfg.google_credentials), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise GCalNotAuthorized("Google Calendar nav autorizēts — palaid: python run.py gcal-auth")
        tok.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def ensure_calendar(svc, cfg: Config, state: State) -> str:
    cid = state.data.get("gcal_calendar_id")
    if cid:
        try:
            svc.calendars().get(calendarId=cid).execute()
            return cid
        except Exception:
            pass
    page = None
    while True:
        lst = svc.calendarList().list(pageToken=page).execute()
        for it in lst.get("items", []):
            if it.get("summary") == cfg.google_calendar_name:
                state.data["gcal_calendar_id"] = it["id"]
                return it["id"]
        page = lst.get("nextPageToken")
        if not page:
            break
    cal = svc.calendars().insert(body={"summary": cfg.google_calendar_name, "timeZone": cfg.timezone}).execute()
    state.data["gcal_calendar_id"] = cal["id"]
    return cal["id"]


def _event_id(uid: str) -> str:
    return "rtu" + hashlib.sha1(uid.encode()).hexdigest()  # tikai 0-9 a-v simboli


def _body(d: Deadline, courses: dict[int, Course], cfg: Config) -> dict:
    s, e = event_span(d)
    body = {
        "summary": summary_line(d, courses),
        "description": event_description(d, courses),
        "start": {"dateTime": s.isoformat(), "timeZone": cfg.timezone},
        "end": {"dateTime": e.isoformat(), "timeZone": cfg.timezone},
        "reminders": {"useDefault": False, "overrides": [] if d.done else
                      [{"method": "popup", "minutes": m} for m in cfg.reminders_minutes]},
        "status": "confirmed",
        "source": {"title": "estudijas.rtu.lv", "url": d.url} if d.url.startswith("http") else None,
    }
    if d.kind in COLORS:
        body["colorId"] = COLORS[d.kind]
    return {k: v for k, v in body.items() if v is not None}


def sync(cfg: Config, state: State, deadlines: list[Deadline], courses: dict[int, Course], now: datetime) -> int:
    from googleapiclient.errors import HttpError

    svc = get_service(cfg)
    cid = ensure_calendar(svc, cfg, state)
    synced: dict = state.data.setdefault("gcal_events", {})
    current: dict[str, dict] = {}
    changed = 0
    for d in deadlines:
        if d.due < now - timedelta(days=2):
            continue
        eid = _event_id(d.uid)
        body = _body(d, courses, cfg)
        h = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        current[eid] = {"due": d.due.isoformat(), "hash": h}
        if synced.get(eid, {}).get("hash") == h:
            continue
        try:
            svc.events().update(calendarId=cid, eventId=eid, body=body).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise
            svc.events().insert(calendarId=cid, body={**body, "id": eid}).execute()
        changed += 1
    # Nākotnes notikumi, kas vairs neeksistē (piem., pasniedzējs izdzēsa) — dzēš
    for eid, meta in list(synced.items()):
        if eid in current:
            continue
        try:
            due = datetime.fromisoformat(meta.get("due"))
        except (TypeError, ValueError):
            due = now
        if due > now:
            try:
                svc.events().delete(calendarId=cid, eventId=eid).execute()
                changed += 1
            except HttpError as e:
                if e.resp.status not in (404, 410):
                    log.warning("Neizdevās dzēst %s: %s", eid, e)
        synced.pop(eid, None)
    synced.update(current)
    return changed


def add_notice(cfg: Config, state: State, text: str, now: datetime) -> None:
    """Ievieto kalendārā brīdinājumu (piem., 'jāpiesakās no jauna'), lai to redz telefonā."""
    svc = get_service(cfg)
    cid = ensure_calendar(svc, cfg, state)
    eid = "rtunotice" + now.strftime("%Y%m%d")
    s = now + timedelta(minutes=5)
    body = {"summary": f"⚠ estudijas-sync: {text}", "description": "Palaid datorā: python run.py login",
            "start": {"dateTime": s.isoformat(), "timeZone": cfg.timezone},
            "end": {"dateTime": (s + timedelta(minutes=15)).isoformat(), "timeZone": cfg.timezone},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]}}
    from googleapiclient.errors import HttpError
    try:
        svc.events().insert(calendarId=cid, body={**body, "id": eid}).execute()
    except HttpError as e:
        if e.resp.status != 409:
            raise
