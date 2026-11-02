"""Kas jauns kopš iepriekšējās palaišanas: termiņi, faili, paziņojumi, vērtējumi."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import State
from .model import Course, Deadline, TextBlock
from .relevance import OTHER
from .util import write_if_changed

KIND_ICON = {"KD": "🟥", "Eksāmens": "🟥", "Tests": "🟧", "MD": "🟦", "LD": "🟩", "PD": "🟩"}
WEEKDAYS = ["P", "O", "T", "C", "Pk", "S", "Sv"]
RUN_SEP = "\n<!-- palaišana -->\n"
CHANGELOG = "JAUNUMI.md"
KEEP_RUNS = 60


def _fmt(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m.} {dt:%H:%M}"


def _ann_key(t: TextBlock) -> str:
    return hashlib.sha1(f"{t.course_id}|{t.url}|{t.title}".encode()).hexdigest()[:16]


@dataclass
class Changes:
    now: datetime
    first_run: bool = False
    previous_run: str | None = None
    new_courses: list[Course] = field(default_factory=list)
    new_deadlines: list[Deadline] = field(default_factory=list)
    moved: list[tuple[Deadline, datetime]] = field(default_factory=list)
    graded: list[Deadline] = field(default_factory=list)
    new_text: list[Deadline] = field(default_factory=list)
    announcements: list[TextBlock] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.new_courses or self.new_deadlines or self.moved or self.graded or self.new_text
                    or self.announcements or self.new_files or self.updated_files)

    def counts(self) -> list[str]:
        parts = []
        for n, one, many in ((len(self.new_deadlines), "jauns termiņš", "jauni termiņi"),
                             (len(self.moved), "mainīts termiņš", "mainīti termiņi"),
                             (len(self.graded), "jauns vērtējums", "jauni vērtējumi"),
                             (len(self.announcements), "jauns paziņojums", "jauni paziņojumi"),
                             (len(self.new_text), "datums tekstā", "datumi tekstā"),
                             (len(self.new_files), "jauns fails", "jauni faili"),
                             (len(self.updated_files), "atjaunināts fails", "atjaunināti faili")):
            if n:
                parts.append(f"{n} {one if n == 1 else many}")
        return parts


def compute(state: State, now: datetime, courses: dict[int, Course], moodle: list[Deadline],
            text_dl: list[Deadline], texts: list[TextBlock], report: dict) -> Changes:
    seen = state.data.get("seen")
    ch = Changes(now=now, previous_run=state.data.get("last_run"))
    ch.new_files, ch.updated_files = list(report.get("new", [])), list(report.get("updated", []))
    anns = [t for t in texts if t.kind == "paziņojums"]
    new_seen = {
        "courses": sorted(courses),
        "deadlines": {d.uid: {"due": d.due.isoformat(), "status": d.status} for d in moodle},
        "text": sorted({d.uid for d in text_dl}),
        "announcements": [],
    }
    if seen is None:
        ch.first_run = True
        ch.totals = {"kursi": len(courses), "termiņi": len([d for d in moodle if d.due >= now]),
                     "paziņojumi": len(anns), "faili": len(ch.new_files)}
        new_seen["announcements"] = sorted({_ann_key(t) for t in anns})
        state.data["seen"] = new_seen
        return ch

    old_dl: dict = seen.get("deadlines", {})
    old_courses = set(seen.get("courses", []))
    ch.new_courses = [c for cid, c in courses.items() if cid not in old_courses]
    for d in sorted(moodle, key=lambda d: d.due):
        prev = old_dl.get(d.uid)
        if prev is None:
            if d.due >= now:
                ch.new_deadlines.append(d)
            continue
        try:
            old_due = datetime.fromisoformat(prev.get("due"))
        except (TypeError, ValueError):
            old_due = d.due
        if abs((old_due - d.due).total_seconds()) >= 60 and d.due >= now:
            ch.moved.append((d, old_due))
        st, old_st = (d.status or ""), (prev.get("status") or "")
        if st.startswith("novērtēts") and st != old_st:
            ch.graded.append(d)
    old_text = set(seen.get("text", []))
    ch.new_text = [d for d in text_dl if d.uid not in old_text and d.due >= now and d.relevance != OTHER]
    old_ann = set(seen.get("announcements", []))
    ch.announcements = [t for t in anns if _ann_key(t) not in old_ann]
    # paturam arī vecās atslēgas (paziņojumi pazūd no "pēdējo 10" saraksta), bet ne bezgalīgi
    new_seen["announcements"] = sorted(old_ann | {_ann_key(t) for t in anns})[-3000:]
    # nepazaudējam vecos termiņus, kas īslaicīgi nav redzami (piem., API kļūda vienā kursā)
    for uid, v in old_dl.items():
        new_seen["deadlines"].setdefault(uid, v)
    new_seen["text"] = sorted(old_text | set(new_seen["text"]))[-3000:]
    state.data["seen"] = new_seen
    return ch


def _label(d: Deadline, courses: dict[int, Course]) -> str:
    c = courses.get(d.course_id)
    return f"{c.label}: " if c else ""


def render_md(ch: Changes, courses: dict[int, Course]) -> list[str]:
    L: list[str] = []
    if ch.first_run:
        t = ch.totals
        return [f"Pirmā sinhronizācija: {t['kursi']} kursi, {t['termiņi']} gaidāmi termiņi, "
                f"{t['paziņojumi']} paziņojumi, lejupielādēti {t['faili']} faili. "
                "Turpmāk šeit būs redzams tikai tas, kas mainījies."]
    if ch.empty:
        return ["Nekā jauna."]
    if ch.new_courses:
        L += [f"**Jauni kursi ({len(ch.new_courses)})**"] + [f"- [{c.fullname}]({c.url})" for c in ch.new_courses] + [""]
    if ch.new_deadlines:
        L.append(f"**Jauni termiņi ({len(ch.new_deadlines)})**")
        for d in ch.new_deadlines:
            L.append(f"- {KIND_ICON.get(d.kind, '▫️')} {d.kind} · {_label(d, courses)}[{d.title}]({d.url}) — **{_fmt(d.due)}**")
        L.append("")
    if ch.moved:
        L.append(f"**Mainīti termiņi ({len(ch.moved)})**")
        for d, old in ch.moved:
            L.append(f"- {_label(d, courses)}[{d.title}]({d.url}): ~~{_fmt(old)}~~ → **{_fmt(d.due)}**")
        L.append("")
    if ch.graded:
        L.append(f"**Jauni vērtējumi ({len(ch.graded)})**")
        L += [f"- {_label(d, courses)}[{d.title}]({d.url}) — {d.status}" for d in ch.graded] + [""]
    if ch.announcements:
        L.append(f"**Jauni paziņojumi ({len(ch.announcements)})**")
        for t in ch.announcements:
            c = courses.get(t.course_id)
            snippet = " ".join(t.text.split())[:160] + ("…" if len(t.text) > 160 else "")
            L.append(f"- {c.label + ': ' if c else ''}[{t.title}]({t.url}) — {snippet}")
        L.append("")
    if ch.new_text:
        L.append(f"**❓ Jauni datumi kursu tekstos ({len(ch.new_text)})**")
        L += [f"- {_fmt(d.due)} · {d.kind} · {_label(d, courses)}{' '.join(d.details.split())[:140]}"
              for d in ch.new_text] + [""]
    for title, items in ((f"Jauni faili ({len(ch.new_files)})", ch.new_files),
                         (f"Atjaunināti faili ({len(ch.updated_files)})", ch.updated_files)):
        if items:
            L.append(f"**{title}**")
            L += [f"- [{rel}](<{rel}>)" for rel in items] + [""]
    return L


def render_console(ch: Changes, courses: dict[int, Course]) -> str:
    if ch.first_run or ch.empty:
        return render_md(ch, courses)[0]
    out = ["Jaunumi: " + ", ".join(ch.counts())]
    for d in ch.new_deadlines:
        out.append(f"  + {d.kind:<8} {_label(d, courses)}{d.title}  → {_fmt(d.due)}")
    for d, old in ch.moved:
        out.append(f"  ~ termiņš  {_label(d, courses)}{d.title}: {_fmt(old)} → {_fmt(d.due)}")
    for d in ch.graded:
        out.append(f"  ★ vērtējums {_label(d, courses)}{d.title}: {d.status}")
    for t in ch.announcements:
        c = courses.get(t.course_id)
        out.append(f"  ✉ paziņojums {c.label + ': ' if c else ''}{t.title}")
    for d in ch.new_text:
        out.append(f"  ? {d.kind:<8} {_label(d, courses)}{_fmt(d.due)} — {' '.join(d.details.split())[:90]}")
    for rel in ch.new_files:
        out.append(f"  + fails    {rel}")
    for rel in ch.updated_files:
        out.append(f"  ~ fails    {rel}")
    return "\n".join(out)


def notification(ch: Changes, courses: dict[int, Course]) -> tuple[str, str] | None:
    if ch.empty or ch.first_run:
        return None
    title = "RTU estudijas: " + ", ".join(ch.counts()[:3])
    lines = [f"{d.kind} {_label(d, courses)}{d.title} → {_fmt(d.due)}" for d in ch.new_deadlines]
    lines += [f"Termiņš mainīts: {d.title} → {_fmt(d.due)}" for d, _ in ch.moved]
    lines += [f"Vērtējums: {d.title} — {d.status}" for d in ch.graded]
    lines += [f"Paziņojums: {t.title}" for t in ch.announcements]
    if ch.new_files and len(lines) < 3:
        lines.append(f"{len(ch.new_files)} jauni faili")
    body = "\n".join(lines[:4]) + ("\n…" if len(lines) > 4 else "")
    return title, body


def append_changelog(out: Path, ch: Changes, md_lines: list[str]) -> None:
    """JAUNUMI.md — visu palaišanu jaunumi, jaunākie augšā. Palaišanas bez izmaiņām netiek rakstītas."""
    if ch.empty and not ch.first_run:
        return
    path = out / CHANGELOG
    header = "# Jaunumi estudijās\n\n_Jaunākie augšā. Tiek rakstīts tikai tad, ja kaut kas mainījies._\n"
    runs: list[str] = []
    if path.exists():
        parts = path.read_text(encoding="utf-8").split(RUN_SEP)
        runs = [p for p in parts[1:] if p.strip()]
    block = f"## {ch.now:%d.%m.%Y %H:%M}\n\n" + "\n".join(md_lines).rstrip() + "\n"
    runs = [block] + runs[: KEEP_RUNS - 1]
    write_if_changed(path, header + "".join(RUN_SEP + r for r in runs))
