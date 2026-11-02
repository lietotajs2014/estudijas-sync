"""Fona sinhronizācija: python -m server.worker

- plānotajos laikos (SCHEDULE_TIMES, noklusējumā 07:30 un 19:30 Rīgas laikā) sinhronizē visus lietotājus;
- ik pa 3 s pārbauda, vai kāds nav nospiedis "Sinhronizēt tagad" vai atzīmējis failus lejupielādei.
Viens process, lietotāji pa vienam — lai nepārslogotu e-studijas un drauga datoru.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .db import MoodleLink, SessionLocal, User, init_db
from .runner import FileProgress, download_for_user, sync_user
from .settings import settings

log = logging.getLogger("worker")
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True


def due_slot(now: datetime, times: list[str], last_slot: str | None) -> str | None:
    """Atgriež plānotā laika atslēgu (piem. "2026-11-02 07:30"), ja tas ir pienācis un vēl nav izpildīts."""
    current = None
    for t in sorted(times):
        h, m = map(int, t.split(":"))
        if (now.hour, now.minute) >= (h, m):
            current = f"{now:%Y-%m-%d} {h:02d}:{m:02d}"
    if current and current != last_slot:
        return current
    return None


def run_one(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return
        user.sync_requested = False
        db.commit()
        fp = FileProgress(user_id, "Sinhronizācija")
        try:
            res = sync_user(db, user, prog=fp.prog)
            log.info("user %s: %s kursi, %s termiņi", user.id, res.get("courses"), res.get("deadlines"))
            fp.done(True, res.get("changes_text") or "Gatavs.")
        except Exception as e:
            log.exception("user %s sinhronizācija neizdevās", user_id)
            db.rollback()
            user = db.get(User, user_id)
            if user and not user.last_error:
                user.last_error = str(e)[:2000]
                db.commit()
            fp.done(False, (user.last_error if user else None) or str(e))


def download_one(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return
        keys = [str(k) for k in (user.download_requested or [])][:2000]
        user.download_requested = None
        db.commit()
        if not keys:
            return
        fp = FileProgress(user_id, "Lejupielāde")
        try:
            r = download_for_user(db, user, keys, prog=fp.prog)
            msg = f"Lejupielādēti {len(r['done'])} faili."
            if r.get("drive_uploaded"):
                msg += f" Uz Google Drive: {r['drive_uploaded']}."
            if r["errors"]:
                msg += f" Neizdevās {len(r['errors'])}: " + "; ".join(r["errors"][:5])
            for w in r.get("warnings") or []:
                msg += f"\n{w}"
            fp.done(not r["errors"] or bool(r["done"]), msg)
        except Exception as e:
            log.exception("user %s lejupielāde neizdevās", user_id)
            db.rollback()
            fp.done(False, str(e)[:2000])


def linked_user_ids(only_requested: bool = False) -> list[int]:
    with SessionLocal() as db:
        q = select(User.id).join(MoodleLink).where(MoodleLink.valid.is_(True))
        if only_requested:
            q = q.where(User.sync_requested.is_(True))
        return list(db.scalars(q.order_by(User.id)))


def download_user_ids() -> list[int]:
    with SessionLocal() as db:
        q = select(User.id, User.download_requested).join(MoodleLink).where(MoodleLink.valid.is_(True))
        return [uid for uid, req in db.execute(q.order_by(User.id)) if req]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    init_db()
    tz = ZoneInfo(settings.timezone)
    # Startējot neskrienam uzreiz visiem — sākam ar pašreizējo slotu kā izpildītu.
    last_slot = due_slot(datetime.now(tz), settings.schedule_times, None)
    log.info("Worker palaists; plānotie laiki %s (%s)", ", ".join(settings.schedule_times), settings.timezone)
    while not _stop:
        slot = due_slot(datetime.now(tz), settings.schedule_times, last_slot)
        if slot:
            last_slot = slot
            ids = linked_user_ids()
            log.info("Plānotā sinhronizācija %s: %d lietotāji", slot, len(ids))
            for uid in ids:
                if _stop:
                    break
                run_one(uid)
        for uid in download_user_ids():   # atzīmētie faili — ātri, tāpēc pirms sinhronizācijām
            if _stop:
                break
            download_one(uid)
        for uid in linked_user_ids(only_requested=True):
            if _stop:
                break
            run_one(uid)
        for _ in range(3):
            if _stop:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
