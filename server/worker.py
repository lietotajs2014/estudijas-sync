"""Fona sinhronizācija: python -m server.worker

- plānotajos laikos (SCHEDULE_TIMES, noklusējumā 07:30 un 19:30 Rīgas laikā) sinhronizē visus lietotājus;
- ik pa 15 s pārbauda, vai kāds nav nospiedis "Sinhronizēt tagad".
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
from .runner import sync_user
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
        try:
            res = sync_user(db, user)
            log.info("user %s: %s kursi, %s termiņi, %s jauni faili", user.id, res.get("courses"),
                     res.get("deadlines"), res.get("new"))
        except Exception as e:
            log.exception("user %s sinhronizācija neizdevās", user_id)
            db.rollback()
            user = db.get(User, user_id)
            if user and not user.last_error:
                user.last_error = str(e)[:2000]
                db.commit()


def linked_user_ids(only_requested: bool = False) -> list[int]:
    with SessionLocal() as db:
        q = select(User.id).join(MoodleLink).where(MoodleLink.valid.is_(True))
        if only_requested:
            q = q.where(User.sync_requested.is_(True))
        return list(db.scalars(q.order_by(User.id)))


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
        for uid in linked_user_ids(only_requested=True):
            if _stop:
                break
            run_one(uid)
        for _ in range(15):
            if _stop:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
