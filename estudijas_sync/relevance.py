"""Vai informācija attiecas uz tevi — studiju programmu/plūsmu (piem. RMCE0) un grupu (piem. 3).

Vienā Moodle kursā bieži ir vairāku programmu un grupu uzdevumi. Teksts, faila,
uzdevuma vai sadaļas nosaukums tiek novērtēts šādi:
  - minēta tava programma (RMCE0, RMCE0-3, RMCE03 ...) → tev, ja vien nav norādīta cita grupa;
  - minētas tikai citas programmas (RMMB0, RDBM0 ...) → citiem;
  - minētas grupas ("1. un 2. grupa", "3.gr.", "grupa 3", "1.–3. grupa") → tev, ja tava ir starp tām;
  - nekas no tā → vispārīgs (paturam).
"""
from __future__ import annotations

import re

MINE, OTHER = "tev", "citai grupai/programmai"

_GROUP_BEFORE = re.compile(
    r"((?:(?<![\d.])\d{1,2}\.?\s*(?:,|un|–|-|/|&)\s*)*(?<![\d.])\d{1,2})\.?\s*(?:grup\w*|gr\b\.?)", re.I)
_GROUP_AFTER = re.compile(r"\b(?:grup\w*|gr\.)\s*(?:nr\.?\s*)?(\d{1,2})(?![\d.,]\d)(?!\d)", re.I)
_RANGE = re.compile(r"(\d{1,2})\.?\s*[–-]\s*(\d{1,2})")


def group_numbers(text: str) -> set[int]:
    out: set[int] = set()
    for m in _GROUP_BEFORE.finditer(text or ""):
        chunk = m.group(1)
        for a, b in _RANGE.findall(chunk):
            a, b = int(a), int(b)
            if 0 < b - a < 15:
                out.update(range(a, b + 1))
        out.update(int(x) for x in re.findall(r"\d{1,2}", chunk))
    for m in _GROUP_AFTER.finditer(text or ""):
        out.add(int(m.group(1)))
    return {g for g in out if 0 < g < 50}


def _code_regex(program: str, override: str | None) -> re.Pattern | None:
    """Regex, kas atrod jebkuru tādas pašas formas programmas kodu (RMCE0 → R + 3 burti + cipars),
    ar neobligātu grupas numuru: RMCE0-3, RMCE0/3, RMCE03."""
    if override:
        core = override
    else:
        m = re.fullmatch(r"([A-ZĀ-Ž])([A-ZĀ-Ž]+)(\d)", program or "")
        if not m:
            return None
        core = rf"{m.group(1)}[A-ZĀ-Ž]{{{len(m.group(2))}}}\d"
    return re.compile(rf"(?<![^\W\d_])({core})(?:\s?[-/]\s?(\d{{1,2}})(?![\d.]\d)|(\d{{1,2}})(?![\d.]\d))?(?![^\W\d_])")


class Matcher:
    def __init__(self, program: str = "", groups: set[int] | None = None, other_pattern: str | None = None):
        self.program = (program or "").strip().upper()
        self.groups = set(groups or ())
        self.code_rx = _code_regex(self.program, other_pattern)

    @property
    def active(self) -> bool:
        return bool(self.program or self.groups)

    @classmethod
    def build(cls, program: str, group: str, extra_groups: list[str], moodle_groups: list[str],
              other_pattern: str | None = None) -> "Matcher":
        program = (program or "").strip().upper()
        groups: set[int] = set()
        for g in [group, *extra_groups]:
            g = str(g or "").strip()
            if g.isdigit():
                groups.add(int(g))
            elif g:
                groups |= group_numbers(g)
        tmp = cls(program, set(), other_pattern)
        for name in moodle_groups:  # Moodle grupas, kurās tu esi (piem. "RMCE0 3. grupa")
            groups |= group_numbers(name)
            if tmp.code_rx:
                for code, g1, g2 in tmp.code_rx.findall(name):
                    if code == program and (g1 or g2):
                        groups.add(int(g1 or g2))
        return cls(program, groups, other_pattern)

    def evaluate(self, text: str) -> str | None:
        if not text or not self.active:
            return None
        mine_code = False
        other_codes = False
        groups = group_numbers(text)
        if self.program:
            if self.code_rx:
                for code, g1, g2 in self.code_rx.findall(text):
                    if code == self.program:
                        mine_code = True
                        if g1 or g2:
                            groups.add(int(g1 or g2))
                    else:
                        other_codes = True
            elif self.program.lower() in text.lower():
                mine_code = True
        if mine_code:
            if groups and self.groups and not (groups & self.groups):
                return OTHER
            return MINE
        if other_codes:
            return OTHER
        if groups and self.groups:
            return MINE if groups & self.groups else OTHER
        return None

    def first(self, *texts: str) -> str | None:
        """Pirmais nenulles vērtējums (no specifiskākā uz vispārīgāko)."""
        for t in texts:
            r = self.evaluate(t)
            if r:
                return r
        return None
