"""Skripta atjaunināšana no GitHub (git pull)."""
from __future__ import annotations

import subprocess
import sys

from .schedule import PROJECT_DIR


def _git(*args: str) -> subprocess.CompletedProcess:
    # encoding=utf-8: commit ziņās ir latviešu burti; ar Windows noklusējuma kodējumu stdout būtu None
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=PROJECT_DIR, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    r.stdout, r.stderr = r.stdout or "", r.stderr or ""
    return r


def is_repo() -> bool:
    return (PROJECT_DIR / ".git").exists()


def current_version() -> str:
    if not is_repo():
        return ""
    r = _git("log", "-1", "--format=%h %cd", "--date=format:%d.%m.%Y %H:%M")
    return r.stdout.strip()


def do_update() -> tuple[bool, str]:
    if not is_repo():
        return False, "Šī mape nav git repozitorijs. Noklonē repozitoriju ar git clone (skat. README)."
    before = _git("rev-parse", "HEAD").stdout.strip()
    r = _git("pull", "--ff-only")
    if r.returncode != 0:
        return False, "git pull neizdevās:\n" + (r.stderr or r.stdout).strip()
    after = _git("rev-parse", "HEAD").stdout.strip()
    if before == after:
        return True, "Jau ir jaunākā versija."
    log = _git("log", "--oneline", f"{before}..{after}").stdout.strip()
    msg = "Atjaunināts. Izmaiņas:\n" + log
    changed = _git("diff", "--name-only", before, after).stdout.split()
    if any(f.startswith("requirements") for f in changed):
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(PROJECT_DIR / "requirements.txt")])
        msg += "\nBibliotēkas atjauninātas."
    if any(f.startswith("estudijas_sync/") for f in changed):
        msg += "\nJa web panelis ir atvērts, pārstartē to, lai izmaiņas stātos spēkā."
    return True, msg
