"""Kopēšana uz Google Drive / OneDrive sinhronizēto mapi (bez API — to augšupielādē Drive for desktop)."""
from __future__ import annotations

import glob
import logging
import os
import platform
import shutil
import string
from pathlib import Path

from .config import Config, State

log = logging.getLogger(__name__)
DIGEST_FILES = ("UZDEVUMI.md", "JAUNUMI.md", "termini.ics")


def file_category(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) > 3 and parts[1] == "_Citām grupām":
        return parts[2]
    return parts[1] if len(parts) > 2 else ""


def _needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    s, d = src.stat(), dst.stat()
    return s.st_size != d.st_size or s.st_mtime > d.st_mtime + 2


def mirror(cfg: Config, state: State) -> list[str]:
    """Atgriež nokopēto failu sarakstu (relatīvie ceļi)."""
    if not (cfg.drive_enabled and cfg.drive_folder):
        return []
    dst_root = Path(cfg.drive_folder)
    if not dst_root.parent.exists():
        raise FileNotFoundError(f"Drive mape nav atrasta: {dst_root.parent} (vai Drive for desktop ir palaists?)")
    out = cfg.output_dir
    cats = {c.casefold() for c in cfg.drive_categories}
    copied: list[str] = []
    for entry in state.files.values():
        rel = entry.get("path")
        if not rel:
            continue
        if cats and file_category(rel).casefold() not in cats:
            continue
        src, dst = out / rel, dst_root / rel
        if src.exists() and _needs_copy(src, dst):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
    if cfg.drive_include_digest:
        for name in DIGEST_FILES:
            src = out / name
            if src.exists() and _needs_copy(src, dst_root / name):
                dst_root.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_root / name)
    return copied


def detect_folders() -> list[dict]:
    """Atrod Google Drive / OneDrive mapes šajā datorā (ieteikumi iestatījumos)."""
    found: list[dict] = []
    home = Path.home()

    def add(kind: str, p: Path):
        if p.is_dir() and str(p) not in {f["path"] for f in found}:
            found.append({"kind": kind, "path": str(p), "suggest": str(p / "RTU estudijas")})

    if platform.system() == "Windows":
        for letter in string.ascii_uppercase[3:]:
            for name in ("My Drive", "Mans disks", "Мой диск"):
                add("Google Drive", Path(f"{letter}:/{name}"))
        for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
            if os.environ.get(var):
                add("OneDrive", Path(os.environ[var]))
    for p in glob.glob(str(home / "Library/CloudStorage/GoogleDrive-*")):
        for name in ("My Drive", "Mans disks"):
            add("Google Drive", Path(p) / name)
    for p in glob.glob(str(home / "Library/CloudStorage/OneDrive*")):
        add("OneDrive", Path(p))
    for p in (home / "Google Drive" / "My Drive", home / "Google Drive", home / "My Drive"):
        add("Google Drive", p)
    for p in glob.glob(str(home / "OneDrive*")):
        add("OneDrive", Path(p))
    return found
