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
# Google Calendar krāsas: 10 zaļa (Basil), 11 sarkana (Tomato), 8 pelēka (Graphite), 3 violeta (Grape),
# 9 zila (Blueberry), 5 dzeltena (Banana), 7 tirkīza (Peacock)
COLOR_DONE, COLOR_OVERDUE, COLOR_PAST = "10", "11", "8"
KIND_COLORS = {"KD": "3", "Eksāmens": "3", "Tests": "5", "MD": "9", "LD": "7", "PD": "7", "Konsultācija": "2"}


def color_for(d: Deadline, now: datetime) -> str | None:
    """Krāsa pēc stāvokļa: iesniegts → zaļš, nokavēts → sarkans, pagājis → pelēks, citādi pēc veida."""
    if d.done:
        return COLOR_DONE
    if d.due < now:
        return COLOR_OVERDUE if d.status is not None else COLOR_PAST
    return KIND_COLORS.get(d.kind)


class GCalNotAuthorized(Exception):
    pass


def friendly_error(e: Exception) -> str:
    """Saprotams paskaidrojums biežākajām Google API kļūdām."""
    import re
    text = str(e)
    if "accessNotConfigured" in text or "has not been used in project" in text:
        m = re.search(r"project[= ](\d+)", text)
        link = ("https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview"
                + (f"?project={m.group(1)}" if m else ""))
        return (f"Google Cloud projektā nav ieslēgts Google Calendar API. Atver {link}, spied 'Enable', "
                "pagaidi 1–2 minūtes un mēģini vēlreiz.")
    if "invalid_grant" in text:
        return "Google Calendar savienojums beidzies. Panelī spied 'Savienot ar Google'."
    if "access_denied" in text:
        return ("Google liedza piekļuvi. Pārbaudi, vai tavs Gmail ir pievienots kā Test user "
                "(Google Auth Platform → Audience → Test users).")
    return text


def get_service(cfg: Config, interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GCalNotAuthorized("Nav instalētas Google bibliotēkas: pip install -r requirements.txt") from e
    tok = cfg.data_dir / "google_token.json"
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tok.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:  # piem. invalid_grant: Testing režīmā Google atsauc piekļuvi pēc 7 dienām
            log.warning("Google piekļuve beigusies: %s", e)
            tok.unlink(missing_ok=True)
            creds = None
            if not interactive:
                raise GCalNotAuthorized("Google Calendar savienojums beidzies (Testing režīmā tas notiek ik pēc "
                                        "7 dienām). Panelī spied 'Savienot ar Google'.") from e
    if not creds or not creds.valid:
        if interactive:
            if not cfg.google_credentials.exists():
                raise GCalNotAuthorized(f"Nav atrasts {cfg.google_credentials} (skat. README).")
            flow = InstalledAppFlow.from_client_secrets_file(str(cfg.google_credentials), SCOPES)
            try:
                creds = flow.run_local_server(
                    port=0, timeout_seconds=300,
                    authorization_prompt_message=("\nGoogle pieteikšanās saite (ja pārlūks rāda kļūdu, atver to "
                                                  "inkognito logā):\n{url}\n"),
                    success_message="Google Calendar savienots. Šo logu var aizvērt.")
            except Exception as e:
                raise GCalNotAuthorized(f"Google pieteikšanās netika pabeigta ({e}). Mēģini vēlreiz.") from e
            if creds is None:
                raise GCalNotAuthorized("Google pieteikšanās netika pabeigta 5 minūšu laikā. Mēģini vēlreiz.")
        else:
            raise GCalNotAuthorized("Google Calendar nav autorizēts — palaid: python run.py gcal-auth")
        tok.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def account_email(svc) -> str:
    try:
        return svc.calendarList().get(calendarId="primary").execute().get("id", "")
    except Exception:
        return ""


def deadlines_from_view(view: dict, include_text: bool) -> tuple[list[Deadline], dict[int, Course]]:
    """Termiņi no pēdējās sinhronizācijas (view.json) — lai kalendāru aizpildītu uzreiz pēc savienošanas."""
    courses = {int(c["id"]): Course(int(c["id"]), c.get("label", ""), c.get("full", ""), c.get("url", ""))
               for c in view.get("courses", [])}
    rows = list(view.get("deadlines", [])) + (list(view.get("text_dates", [])) if include_text else [])
    out = []
    for r in rows:
        try:
            out.append(Deadline(uid=r["uid"], course_id=int(r.get("course_id") or 0), kind=r["kind"], title=r["title"],
                                due=datetime.fromisoformat(r["due"]),
                                start=datetime.fromisoformat(r["start"]) if r.get("start") else None,
                                url=r.get("url", ""), status=r.get("status"), source=r.get("source", "moodle"),
                                details=r.get("details", ""), relevance=r.get("relevance"), section=r.get("section", "")))
        except (KeyError, ValueError):
            continue
    return out, courses


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


def _body(d: Deadline, courses: dict[int, Course], cfg: Config, now: datetime) -> dict:
    s, e = event_span(d)
    future = d.due > now
    body = {
        "summary": summary_line(d, courses, now),
        "description": event_description(d, courses),
        "start": {"dateTime": s.isoformat(), "timeZone": cfg.timezone},
        "end": {"dateTime": e.isoformat(), "timeZone": cfg.timezone},
        "reminders": {"useDefault": False, "overrides": [] if d.done or not future else
                      [{"method": "popup", "minutes": m} for m in cfg.reminders_minutes]},
        "status": "confirmed",
        "source": {"title": "estudijas.rtu.lv", "url": d.url} if d.url.startswith("http") else None,
    }
    color = color_for(d, now)
    if color:
        body["colorId"] = color
    return {k: v for k, v in body.items() if v is not None}


def _execute(req, tries: int = 4):
    """Izpilda Google pieprasījumu; ja pārsniegts ātruma limits, pagaida un mēģina vēlreiz."""
    import time
    from googleapiclient.errors import HttpError
    for i in range(tries):
        try:
            return req.execute()
        except HttpError as e:
            text = str(e)
            if e.resp.status in (403, 429) and ("rateLimit" in text or "RateLimit" in text or e.resp.status == 429) \
                    and i < tries - 1:
                time.sleep(2 ** i)
                continue
            raise


def sync(cfg: Config, state: State, deadlines: list[Deadline], courses: dict[int, Course], now: datetime) -> int:
    from googleapiclient.errors import HttpError

    svc = get_service(cfg)
    cid = ensure_calendar(svc, cfg, state)
    synced: dict = state.data.setdefault("gcal_events", {})
    current: dict[str, dict] = {}
    changed = 0
    for d in deadlines:
        eid = _event_id(d.uid)
        body = _body(d, courses, cfg, now)
        h = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        current[eid] = {"due": d.due.isoformat(), "hash": h}
        if synced.get(eid, {}).get("hash") == h:
            continue
        try:
            _execute(svc.events().update(calendarId=cid, eventId=eid, body=body))
        except HttpError as e:
            if e.resp.status != 404:
                raise
            _execute(svc.events().insert(calendarId=cid, body={**body, "id": eid}))
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
