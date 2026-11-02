"""Datumu un termiņu atrašana brīvā tekstā (latviski un angliski).

Piemēri, ko atpazīst:
  "MD3 jāiesniedz līdz 12.11. plkst. 23:59"
  "KD2 notiks 20. novembrī"
  "Tests 2026-11-25 10:00"
  "pirmdiena, 2026. gada 3. novembris, 00:00"   (Moodle LV formāts)
  "Monday, 3 November 2026, 11:59 PM"            (Moodle EN formāts)
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, tzinfo

from .model import Deadline, TextBlock

MONTH_WORD = (r"(?:janv\w*|jan(?:uary)?|febr\w*|feb|mart\w*|march|mar|apr\w*|maij\w*|may|"
              r"jūn\w*|june?|jūl\w*|july?|aug\w*|sept?\w*|okt\w*|oct\w*|nov\w*|dec\w*)")

_MONTH_PREFIXES = [("janv", 1), ("jan", 1), ("febr", 2), ("feb", 2), ("mar", 3), ("apr", 4),
                   ("maij", 5), ("may", 5), ("jūn", 6), ("jun", 6), ("jūl", 7), ("jul", 7),
                   ("aug", 8), ("sep", 9), ("okt", 10), ("oct", 10), ("nov", 11), ("dec", 12)]

RE_ISO = re.compile(r"(?<!\d)(20\d\d)-(\d{1,2})-(\d{1,2})(?!\d)")
RE_LVGADA = re.compile(rf"(?<!\d)(20\d\d)\.\s*g(?:ada|\.)?\s+(\d{{1,2}})\.\s*({MONTH_WORD})", re.I)
RE_DAYMON = re.compile(rf"(?<![\d.])(\d{{1,2}})\.?\s+({MONTH_WORD})\b(?:\s+(20\d\d))?", re.I)
RE_NUM = re.compile(r"(?<![\d.:])(\d{1,2})\.(\d{1,2})(\.(?:(20\d\d|\d\d)(?!\d))?)?(?![\d:])")
RE_TIME = re.compile(r"^[\s,.]*(?:g\.\s*)?(?:plkst\.?|pulksten\w*|at|līdz|until)?\s*"
                     r"([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)(?:\s*([ap])\.?\s?m\b\.?)?", re.I)

# Veidi, pēc kuriem saprot, ka rinda runā par termiņu. "Termiņš" ir vispārīgs (zemāka prioritāte).
KIND_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("KD", re.compile(r"(?<![^\W\d_])KD(?:\s*\d+)?(?![^\W\d_])|kontroldarb|kolokvij", re.I)),
    ("Eksāmens", re.compile(r"eksām|ieskait|\bexam", re.I)),
    ("Tests", re.compile(r"\btest\w*|\bquiz", re.I)),
    ("MD", re.compile(r"(?<![^\W\d_])MD(?:\s*\d+)?(?![^\W\d_])|mājas\s*darb|majas\s*darb|mājasdarb|homework", re.I)),
    ("LD", re.compile(r"(?<![^\W\d_])LD(?:\s*\d+)?(?![^\W\d_])|laborator", re.I)),
    ("PD", re.compile(r"(?<![^\W\d_])PD(?:\s*\d+)?(?![^\W\d_])|praktisk\w*\s+(?:darb|uzdev)", re.I)),
    ("Termiņš", re.compile(r"termiņ|iesnie[gd]|nodo[tš]|deadline|\bdue\b|aizstāvē", re.I)),
]


def month_num(word: str) -> int | None:
    w = word.lower()
    for prefix, n in _MONTH_PREFIXES:
        if w.startswith(prefix):
            return n
    return None


def _resolve_year(month: int, day: int, now: datetime) -> datetime | None:
    best, best_delta = None, None
    for y in (now.year - 1, now.year, now.year + 1):
        try:
            dt = datetime(y, month, day)
        except ValueError:
            continue
        delta = (dt - now).days
        if -150 <= delta <= 250 and (best_delta is None or abs(delta) < abs(best_delta)):
            best, best_delta = dt, delta
    return best


def _parse_time(text: str, pos: int) -> tuple[int, int] | None:
    m = RE_TIME.match(text[pos:pos + 30])
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").lower()
    if ap == "p" and h < 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    return h, mi


def extract_dates(line: str, now: datetime) -> list[tuple[datetime, bool, tuple[int, int]]]:
    """Atgriež [(datums (naivs, vietējais), vai_ir_laiks, (sākums, beigas))].
    `now` — naivs vietējais laiks (gada noteikšanai, ja tas nav norādīts)."""
    now = now.replace(tzinfo=None)
    found: list[tuple[datetime, bool, tuple[int, int]]] = []
    taken: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < y and x < b for x, y in taken)

    def add(dt: datetime | None, start: int, end: int) -> None:
        if dt is None or overlaps(start, end):
            return
        t = _parse_time(line, end)
        if t:
            dt = dt.replace(hour=t[0], minute=t[1])
        taken.append((start, end))
        found.append((dt, t is not None, (start, end)))

    def mk(y: int, mo: int, d: int) -> datetime | None:
        try:
            return datetime(y, mo, d)
        except ValueError:
            return None

    for m in RE_ISO.finditer(line):
        add(mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.start(), m.end())
    for m in RE_LVGADA.finditer(line):
        mo = month_num(m.group(3))
        if mo:
            add(mk(int(m.group(1)), mo, int(m.group(2))), m.start(), m.end())
    for m in RE_DAYMON.finditer(line):
        mo = month_num(m.group(2))
        if not mo:
            continue
        day = int(m.group(1))
        dt = mk(int(m.group(3)), mo, day) if m.group(3) else _resolve_year(mo, day, now)
        add(dt, m.start(), m.end())
    for m in RE_NUM.finditer(line):
        day, mo, yr = int(m.group(1)), int(m.group(2)), m.group(4)
        if not (1 <= day <= 31 and 1 <= mo <= 12):
            continue
        before = line[: m.start()]
        if not yr and not before.strip() and not (len(m.group(1)) == 2 and len(m.group(2)) == 2):
            continue  # rindas sākumā "2.1." visticamāk ir virsraksta numerācija ("30.10." gan ir datums)
        if not m.group(3) and len(m.group(2)) < 2:
            continue  # "3.5" bez beigu punkta — skaitlis, nevis datums
        if not m.group(3) and re.search(r"(plkst\.?|pulksten\w*|no|līdz)\s*$", before, re.I):
            continue  # "plkst. 9.10" — laiks
        if yr:
            y = int(yr) + (2000 if len(yr) == 2 else 0)
            dt = mk(y, mo, day)
        else:
            dt = _resolve_year(mo, day, now)
        add(dt, m.start(), m.end())
    found.sort(key=lambda x: x[2][0])
    return found


def parse_first(text: str, now: datetime) -> datetime | None:
    r = extract_dates(text, now)
    return r[0][0] if r else None


def nearest_kind(line: str, pos: int) -> str | None:
    best, best_score = None, None
    for kind, rx in KIND_PATTERNS:
        for m in rx.finditer(line):
            k = m.start()
            score = (pos - k) if k <= pos else (k - pos) * 1.5
            if kind == "Termiņš":
                score += 40
            if best_score is None or score < best_score:
                best, best_score = kind, score
    return best


def classify_kind(text: str, default: str = "Uzdevums") -> str:
    for kind, rx in KIND_PATTERNS:
        if kind != "Termiņš" and rx.search(text or ""):
            return kind
    return default


# Rindas, ko pats skripts pievieno uzdevumu aprakstiem (dati jau ir no Moodle — nav jādublē)
GENERATED_PREFIXES = ("Iesniegšana no:", "Termiņš:", "Galīgais termiņš", "Atveras:", "Aizveras:")


def find_text_deadlines(texts: list[TextBlock], matchers: dict, existing: list[Deadline], now: datetime,
                        tz: tzinfo, lookahead_days: int, lookback_days: int = 1) -> list[Deadline]:
    """Meklē kursu tekstos (paziņojumos, lapās, aprakstos) termiņus, kas nav Moodle kalendārā.
    `matchers` — {kursa_id: relevance.Matcher}, lai atšķirtu tavas grupas/programmas datumus."""
    from .relevance import OTHER, Matcher
    out: dict[tuple, Deadline] = {}
    now_naive = now.astimezone(tz).replace(tzinfo=None)
    lo, hi = now - timedelta(days=lookback_days), now + timedelta(days=lookahead_days)
    moodle_days = {(d.course_id, d.due.astimezone(tz).date()) for d in existing}
    for tb in texts:
        m = matchers.get(tb.course_id) or Matcher()
        for line in tb.text.splitlines():
            line = line.strip()
            if len(line) < 6 or line.startswith(GENERATED_PREFIXES):
                continue
            dates = extract_dates(line, now_naive)
            prev_end = 0
            for dt, has_time, (s, e) in dates:
                window = line[prev_end:e + 3]  # piem. "1. grupa 12.11., 3. grupa 19.11." — katram datumam savs
                prev_end = e
                kind = nearest_kind(line, s)
                if not kind:
                    continue
                if not has_time:
                    dt = dt.replace(hour=23, minute=59)
                aware = dt.replace(tzinfo=tz)
                if not (lo <= aware <= hi) or (tb.course_id, aware.date()) in moodle_days:
                    continue
                rel = m.first(window, line, tb.title)
                key = (tb.course_id, aware.date(), kind)
                if key in out and not (out[key].relevance == OTHER and rel != OTHER):
                    continue
                ctx = line if len(line) <= 220 else line[:217] + "…"
                uid = "txt-" + hashlib.sha1(f"{tb.course_id}|{aware.date()}|{kind}".encode()).hexdigest()[:16]
                out[key] = Deadline(uid=uid, course_id=tb.course_id, kind=kind,
                                    title=f"{kind} ({tb.title})", due=aware, url=tb.url,
                                    source="teksts", details=ctx, relevance=rel)
    return sorted(out.values(), key=lambda d: d.due)
