"""Izvades faili: UZDEVUMI.md (kopsavilkums), kursu _info mapes, termini.ics."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import Course, Deadline, Link, TextBlock
from .util import md_escape, sanitize, write_if_changed

WEEKDAYS = ["P", "O", "T", "C", "Pk", "S", "Sv"]
KIND_ICON = {"KD": "🟥", "Eksāmens": "🟥", "Tests": "🟧", "MD": "🟦", "LD": "🟩", "PD": "🟩"}
BANNER_START, BANNER_END = "<!-- brīdinājums -->", "<!-- /brīdinājums -->"
DIGEST_NAME = "UZDEVUMI.md"


def fmt_dt(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m.} {dt:%H:%M}"


def rel_days(dt: datetime, now: datetime) -> str:
    days = (dt.date() - now.date()).days
    if dt < now:
        return "**nokavēts**" if days <= -1 else "**šodien (beidzies)**"
    if days == 0:
        hrs = int((dt - now).total_seconds() // 3600)
        return f"**šodien** (~{hrs} h)"
    if days == 1:
        return "**rīt**"
    return f"pēc {days} d."


def course_dir_name(c: Course, how: str) -> str:
    base = c.shortname if how == "shortname" and c.shortname else c.fullname or c.shortname
    return sanitize(base, 80)


def summary_line(d: Deadline, courses: dict[int, Course]) -> str:
    c = courses.get(d.course_id)
    prefix = "✅ " if d.done else ("❓ " if d.source == "teksts" else "")
    label = f"{c.label}: " if c else ""
    return f"{prefix}[{d.kind}] {label}{d.title}"


# ------------------------------------------------------------------
def write_digest(out: Path, now: datetime, user: str, courses: dict[int, Course],
                 deadlines: list[Deadline], text_deadlines: list[Deadline], files_report: dict,
                 warnings: list[str], course_dirs: dict[int, str],
                 changes_md: list[str] | None = None, previous_run: str | None = None,
                 others: list[Deadline] | None = None, filter_desc: str = "", drive_link: str = "") -> Path:
    L: list[str] = ["# RTU estudijas — kas jādara", "",
                    f"Atjaunināts: {now:%d.%m.%Y %H:%M}" + (f" · {user}" if user else "")
                    + (f" · atlase: **{filter_desc}**" if filter_desc else ""), ""]
    if drive_link:
        L += [f"📁 Faili Google Drive: {drive_link}", ""]

    def table(rows: list[Deadline]) -> None:
        L.append("| Termiņš | Kad | Kurss | Veids | Uzdevums | Statuss |")
        L.append("|---|---|---|---|---|---|")
        for d in rows:
            c = courses.get(d.course_id)
            title = f"[{md_escape(d.title)}]({d.url})" if d.url else md_escape(d.title)
            st = d.status or ""
            st = f"✅ {st}" if d.done else (f"⏳ {st}" if st else "")
            L.append(f"| {fmt_dt(d.due)} | {rel_days(d.due, now)} | {md_escape(c.label if c else '—')} | "
                     f"{KIND_ICON.get(d.kind, '▫️')} {d.kind} | {title} | {md_escape(st)} |")
        L.append("")

    upcoming = sorted((d for d in deadlines if d.due >= now), key=lambda d: d.due)
    overdue = sorted((d for d in deadlines if now - timedelta(days=14) <= d.due < now and not d.done
                      and d.status is not None), key=lambda d: d.due)
    week = [d for d in upcoming if d.due <= now + timedelta(days=7)]
    month = [d for d in upcoming if now + timedelta(days=7) < d.due <= now + timedelta(days=30)]
    later = [d for d in upcoming if d.due > now + timedelta(days=30)]

    if changes_md:
        since = ""
        if previous_run:
            try:
                since = f" ({datetime.fromisoformat(previous_run):%d.%m. %H:%M})"
            except ValueError:
                pass
        L += [f"## 🆕 Kopš iepriekšējās reizes{since}", ""] + changes_md + ["", "_Visa vēsture: [JAUNUMI.md](JAUNUMI.md)_", ""]

    todo_week = [d for d in week if not d.done]
    L.append(f"**Šonedēļ jāizdara: {len(todo_week)}** · nokavēti: {len(overdue)} · "
             f"30 dienās kopā: {len(week) + len(month)}")
    L.append("")
    if overdue:
        L += ["## ⚠️ Nokavēts (nav atzīmēts kā iesniegts)", ""]
        table(overdue)
    L += ["## Nākamās 7 dienas", ""]
    table(week) if week else L.extend(["Nekā. 🎉", ""])
    if month:
        L += ["## 8–30 dienas", ""]
        table(month)
    if later:
        L += ["## Vēlāk", ""]
        table(later)

    td = [d for d in text_deadlines if d.due >= now]
    if td:
        L += ["## ❓ Datumi no kursu tekstiem (pārbaudi!)", "",
              "_Atrasti paziņojumos, lapās un aprakstos — Moodle kalendārā to nav._", ""]
        for d in td:
            c = courses.get(d.course_id)
            rel = f" · _{d.relevance}_" if d.relevance else ""
            link = f" — [avots]({d.url})" if d.url else ""
            L.append(f"- **{fmt_dt(d.due)}** ({rel_days(d.due, now)}) · {d.kind} · "
                     f"{c.label if c else ''}{rel}{link}  \n  > {md_escape(d.details)}")
        L.append("")

    new, upd = files_report.get("new", []), files_report.get("updated", [])
    if new or upd:
        L += ["## 📥 Jauni / atjaunināti faili", ""]
        for title, items in (("Jauni", new), ("Atjaunināti", upd)):
            if not items:
                continue
            L.append(f"**{title}:**")
            for rel in items:
                L.append(f"- [{rel}](<{rel}>)")
            L.append("")
    skipped = files_report.get("skipped", [])
    errors = files_report.get("errors", [])
    if skipped:
        L += ["<details><summary>Izlaisti faili</summary>", ""] + [f"- {s}" for s in skipped] + ["", "</details>", ""]
    if errors or warnings:
        L += ["## Problēmas", ""] + [f"- {e}" for e in errors + warnings] + [""]

    other_files = files_report.get("other", [])
    others = [d for d in (others or []) if d.due >= now - timedelta(days=1)]
    if others or other_files:
        L += [f"<details><summary>Citām grupām/programmām — paslēpts ({len(others)} termiņi, "
              f"{len(other_files)} faili)</summary>", ""]
        for d in sorted(others, key=lambda d: d.due):
            c = courses.get(d.course_id)
            L.append(f"- {fmt_dt(d.due)} · {d.kind} · {c.label if c else ''}: [{md_escape(d.title)}]({d.url})")
        L += [f"- fails (nelejupielādēts): {rel}" for rel in other_files]
        L += ["", "_Ja kaut kas te ir tavs, pārbaudi `program`/`group` konfigurācijā._", "", "</details>", ""]

    L += ["## Kursi", ""]
    for cid, c in sorted(courses.items(), key=lambda kv: kv[1].fullname):
        L.append(f"- [{md_escape(c.fullname)}]({c.url}) · mape: [{course_dirs.get(cid, '')}](<{course_dirs.get(cid, '')}>)")
    L.append("")
    path = out / DIGEST_NAME
    write_if_changed(path, "\n".join(L))
    return path


def write_banner(out: Path, message: str) -> None:
    """Brīdinājums UZDEVUMI.md augšā (piem., jāpiesakās no jauna); vecais saturs paliek."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / DIGEST_NAME
    old = path.read_text(encoding="utf-8") if path.exists() else "# RTU estudijas — kas jādara\n"
    old = re.sub(re.escape(BANNER_START) + r".*?" + re.escape(BANNER_END) + r"\n*", "", old, flags=re.S)
    banner = f"{BANNER_START}\n> ⚠️ **{message}**\n{BANNER_END}\n\n"
    write_if_changed(path, banner + old)


# ------------------------------------------------------------------
def write_course_info(out: Path, course: Course, dirname: str, deadlines: list[Deadline],
                      texts: list[TextBlock], links: list[Link], groups: list[str],
                      others: list[Deadline] | None = None) -> None:
    info = out / dirname / "_info"
    info.mkdir(parents=True, exist_ok=True)

    L = [f"# {course.fullname} — uzdevumi, testi, termiņi", "", f"[Atvērt kursu]({course.url})", ""]
    if groups:
        L += [f"Tavas grupas: {', '.join(groups)}", ""]
    for d in sorted(deadlines, key=lambda d: d.due):
        L.append(f"## {d.kind}: {d.title}")
        L.append(f"- Termiņš: **{d.due:%d.%m.%Y %H:%M}**" + (f" (atveras {d.start:%d.%m. %H:%M})" if d.start else ""))
        if d.status:
            L.append(f"- Statuss: {d.status}")
        if d.url:
            L.append(f"- Saite: {d.url}")
        if d.details:
            L += ["", d.details.strip()]
        L.append("")
    if others:
        L += ["# Citām grupām/programmām (paslēpts no kalendāra)", ""]
        L += [f"- {d.due:%d.%m.%Y %H:%M} · {d.kind}: [{d.title}]({d.url})" for d in sorted(others, key=lambda d: d.due)]
        L.append("")
    hidden = {d.title for d in others or []}
    other_tasks = [t for t in texts if t.kind == "uzdevums" and t.title not in {d.title for d in deadlines}
                   and t.title not in hidden]
    if other_tasks:
        L += ["# Citi uzdevumi (bez termiņa Moodle)", ""]
        for t in other_tasks:
            L += [f"## {t.title}", t.url, "", t.text, ""]
    write_if_changed(info / "Uzdevumi un testi.md", "\n".join(L))

    ann = sorted((t for t in texts if t.kind == "paziņojums"),
                 key=lambda t: t.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if ann:
        L = [f"# Paziņojumi — {course.fullname}", ""]
        for t in ann:
            L += [f"## {t.title}" + (f" ({t.date:%d.%m.%Y})" if t.date else ""), t.url, "", t.text, ""]
        write_if_changed(info / "Paziņojumi.md", "\n".join(L))

    sec = [t for t in texts if t.kind == "sadaļa"]
    if sec:
        L = [f"# Kursa saturs un apraksti — {course.fullname}", ""]
        for t in sec:
            L += [f"## {t.title}", "", t.text, ""]
        write_if_changed(info / "Kursa saturs.md", "\n".join(L))

    for t in texts:
        if t.kind == "lapa" and t.text:
            write_if_changed(info / "Lapas" / (sanitize(t.title, 70) + ".md"), f"# {t.title}\n\n{t.url}\n\n{t.text}\n")

    if links:
        L = [f"# Saites — {course.fullname}", ""]
        cur = None
        for ln in links:
            if ln.section != cur:
                cur = ln.section
                L += ["", f"## {cur}"]
            L.append(f"- [{ln.name}]({ln.url})")
        write_if_changed(info / "Saites.md", "\n".join(L) + "\n")


# ------------------------------------------------------------------
def event_span(d: Deadline) -> tuple[datetime, datetime]:
    if d.start and timedelta(0) < d.due - d.start <= timedelta(hours=12):
        return d.start, d.due
    return d.due - timedelta(minutes=30), d.due


def _ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return out


def event_description(d: Deadline, courses: dict[int, Course]) -> str:
    c = courses.get(d.course_id)
    parts = [c.fullname if c else "", f"Statuss: {d.status}" if d.status else "",
             f"Atveras: {d.start:%d.%m.%Y %H:%M}" if d.start else "",
             "⚠ Datums atrasts kursa tekstā — pārbaudi!" if d.source == "teksts" else "",
             d.relevance or "", d.url, "", d.details]
    return "\n".join(p for p in parts if p is not None).strip()


def write_ics(path: Path, deadlines: list[Deadline], courses: dict[int, Course], reminders: list[int],
              calname: str = "RTU estudijas") -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    utc = lambda dt: dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//estudijas-sync//LV", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(calname)}", "X-WR-TIMEZONE:Europe/Riga"]
    for d in sorted(deadlines, key=lambda d: d.due):
        s, e = event_span(d)
        lines += ["BEGIN:VEVENT", f"UID:{d.uid}@estudijas-sync", f"DTSTAMP:{stamp}",
                  f"DTSTART:{utc(s)}", f"DTEND:{utc(e)}",
                  f"SUMMARY:{_ics_escape(summary_line(d, courses))}",
                  f"DESCRIPTION:{_ics_escape(event_description(d, courses))}"]
        if d.url:
            lines.append(f"URL:{d.url}")
        if not d.done:
            for m in reminders:
                lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(d.title)}",
                          f"TRIGGER:-PT{int(m)}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for ln in lines:
        folded += _fold(ln)
    write_if_changed(path, "\r\n".join(folded) + "\r\n")
