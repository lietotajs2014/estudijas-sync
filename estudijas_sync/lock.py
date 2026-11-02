"""Sinhronizācijas slēdzene, ko operētājsistēma atbrīvo pati, ja process beidzas vai tiek aizvērts.
(Agrāk tas bija vienkāršs fails, kas palika pēc pārtrauktas sinhronizācijas.)"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(Exception):
    pass


def _try_lock(fh) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def file_lock(path: Path, message: str = "Sinhronizācija jau notiek (piem., automātiskā). Pagaidi, kamēr tā beigsies."):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    if not _try_lock(fh):
        fh.close()
        raise AlreadyRunning(message)
    try:
        yield
    finally:
        _unlock(fh)
        fh.close()


def is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with file_lock(path):
            return False
    except AlreadyRunning:
        return True
