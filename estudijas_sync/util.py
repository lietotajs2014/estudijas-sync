"""Palīgfunkcijas: HTML→teksts, drošs failu nosaukums, atomiska rakstīšana."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

_BLOCK_TAGS = ["p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol",
               "section", "article", "blockquote", "pre", "hr"]


def html_to_text(html: str | None) -> str:
    """Pārvērš HTML lasāmā tekstā, saglabājot rindkopas kā atsevišķas rindas
    (svarīgi, lai datums un atslēgvārds paliktu vienā rindā)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "- ")
        li.append("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.append(" | ")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert(0, "\n")
        tag.append("\n")
    text = soup.get_text()
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t\u00a0\u200b]+", " ", line).strip()
        line = re.sub(r"(\s*\|\s*)+$", "", line)
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize(name: str, maxlen: int = 80) -> str:
    """Faila/mapes nosaukums, kas der Windows, macOS un Linux."""
    s = _BAD_CHARS.sub("_", name or "")
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip()
    if len(s) > maxlen:
        base, ext = os.path.splitext(s)
        if ext and len(ext) <= 8:
            s = base[: maxlen - len(ext)].rstrip() + ext
        else:
            s = s[:maxlen].rstrip()
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s or "_"


def write_atomic(path: Path, data: bytes) -> None:
    write_stream_atomic(path, [data])


def write_stream_atomic(path: Path, chunks: Iterable[bytes]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    n = 0
    with open(tmp, "wb") as fh:
        for c in chunks:
            if c:
                fh.write(c)
                n += len(c)
    os.replace(tmp, path)
    return n


def write_if_changed(path: Path, text: str) -> bool:
    """Raksta tikai, ja saturs mainījies (lai nemainītu faila laiku bez vajadzības)."""
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    write_atomic(path, text.encode("utf-8"))
    return True


def md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()
