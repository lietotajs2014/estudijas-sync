"""Failu sadalīšana mapēs (Lekcijas, Mājas darbi, Kontroldarbi, ...)."""
from __future__ import annotations

import os
import re

from .model import FileItem

PRESENTATION_EXT = {".ppt", ".pptx", ".pps", ".ppsx", ".odp", ".key"}
FALLBACK = "Citi"
ASSIGN_FALLBACK = "Uzdevumi"


def compile_categories(cats: dict[str, str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for name, rx in cats.items():
        try:
            out.append((name, re.compile(rx, re.I)))
        except re.error as e:
            raise ValueError(f"Kļūdaina regex kategorijai '{name}': {e}") from e
    return out


def classify_file(item: FileItem, cats: list[tuple[str, re.Pattern]]) -> str:
    primary = f"{item.filename} {item.module} {item.subpath}"
    for name, rx in cats:
        if rx.search(primary):
            return name
    if item.kind_hint:
        for name, rx in cats:
            if rx.search(item.kind_hint):
                return name
    if item.modtype == "assign":
        return ASSIGN_FALLBACK
    for name, rx in cats:
        if rx.search(item.section or ""):
            return name
    ext = os.path.splitext(item.filename)[1].lower()
    if ext in PRESENTATION_EXT:
        return "Lekcijas"
    return FALLBACK
