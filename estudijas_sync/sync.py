"""Galvenā sinhronizācija: dati → faili mapēs → kopsavilkums → kalendārs."""
from __future__ import annotations

import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .classify import classify_file, compile_categories
from .config import Config, State, load_auth
from .model import Course, FileItem, LoginRequired
from .progress import NullProgress
from .relevance import OTHER, Matcher
from .outputs import course_dir_name, write_course_info, write_digest, write_ics
from .textdates import find_text_deadlines
from .util import sanitize

log = logging.getLogger(__name__)


class AlreadyRunning(Exception):
    pass


@contextmanager
def run_lock(cfg: Config):
    p = cfg.data_dir / "sync.lock"
    if p.exists() and time.time() - p.stat().st_mtime < 2 * 3600:
        raise AlreadyRunning(f"Sinhronizācija jau notiek (ja nē — izdzēs {p}).")
    p.write_text(str(os.getpid()))
    try:
        yield
    finally:
        p.unlink(missing_ok=True)


def make_source(cfg: Config, interactive: bool = True, prog=None):
    auth = load_auth(cfg)
    if not auth:
        raise LoginRequired("Nav pieteikšanās datu.")
    if auth.get("mode") == "api" and auth.get("token"):
        from .api_source import ApiSource
        return ApiSource(cfg, auth)
    from .web_source import WebSource
    return WebSource(cfg, interactive=interactive and cfg.login_popup, prog=prog)


def filter_courses(courses: list[Course], cfg: Config) -> list[Course]:
    out = []
    for c in courses:
        name = f"{c.fullname} {c.shortname}"
        if cfg.include_courses and not any(re.search(rx, name, re.I) for rx in cfg.include_courses):
            continue
        if any(re.search(rx, name, re.I) for rx in cfg.exclude_courses):
            continue
        out.append(c)
    return out


def describe_filter(cfg: Config, matchers: dict[int, Matcher]) -> str:
    prog = cfg.program.upper() or next((m.program for m in matchers.values() if m.program), "")
    groups = [cfg.group] if cfg.group else sorted({g for m in matchers.values() for g in m.groups})
    if not (prog or groups):
        return ""
    parts = [prog] if prog else []
    if groups:
        parts.append(", ".join(map(str, groups)) + (". grupa" if len(groups) == 1 else ". grupas"))
    return ", ".join(parts)


def plan_path(cfg: Config, item: FileItem, course_dir: Path, cats) -> tuple[str, Path]:
    cat = classify_file(item, cats)
    fname = sanitize(item.filename, 120)
    if cat == "Lekcijas" and item.modtype == "resource":
        fname = f"{item.section_num:02d}_{fname}"
    parts = [course_dir, Path(sanitize(cat))]
    if item.modtype == "folder":
        parts.append(Path(sanitize(item.module, 60)))
        parts += [Path(sanitize(p, 60)) for p in item.subpath.split("/") if p]
    return cat, Path(*parts) / fname


def sync_files(cfg: Config, src, files: list[FileItem], course_dirs: dict[int, Path], state: State,
               redownload: bool = False, matchers: dict[int, Matcher] | None = None, prog=None) -> dict:
    prog = prog or NullProgress()
    cats = compile_categories(cfg.categories)
    report = {"new": [], "updated": [], "skipped": [], "errors": [], "other": []}
    matchers = matchers or {}
    used: dict[Path, str] = {}
    max_bytes = cfg.download_max_mb * 1024 * 1024
    out = cfg.output_dir
    only = {c.casefold() for c in cfg.only_categories}
    todo: list[tuple[FileItem, Path, str, dict | None]] = []
    for item in files:
        cdir = course_dirs.get(item.course_id)
        if cdir is None:
            continue
        cat, path = plan_path(cfg, item, cdir, cats)
        if only and cat.casefold() not in only:
            continue
        m = matchers.get(item.course_id)
        if m and cfg.other_groups != "keep" and \
                m.first(f"{item.filename} {item.module}", item.subpath, item.section) == OTHER:
            if cfg.other_groups == "skip":
                report["other"].append(f"{item.filename} — {item.section} / {item.module}")
                continue
            path = cdir / "_Citām grupām" / path.relative_to(cdir)
        if path in used and used[path] != item.key:
            path = path.with_name(f"{path.stem} ({item.cmid}){path.suffix}")
        if used.get(path) == item.key:
            continue  # tas pats fails divreiz sarakstā
        used[path] = item.key
        rel = path.relative_to(out).as_posix()
        if os.path.splitext(item.filename)[1].lower() in cfg.skip_extensions:
            report["skipped"].append(f"{rel} (paplašinājums)")
            continue
        if item.size and item.size > max_bytes:
            report["skipped"].append(f"{rel} ({item.size / 1048576:.0f} MB)")
            continue
        entry = state.files.get(item.key)
        if entry and entry.get("version") == item.version and not redownload:
            continue  # nav mainījies (arī ja lietotājs to apzināti izdzēsa — nelādējam no jauna)
        todo.append((item, path, rel, entry))

    if not todo:
        return report
    prog.start("Lejupielādē", len(todo), sum(i.size or 0 for i, *_ in todo))
    for item, path, rel, entry in todo:
        prog.label(item.filename)
        try:
            src.download(item, path, on_bytes=prog.add_bytes)
        except LoginRequired:
            raise
        except Exception as e:
            log.warning("Lejupielāde neizdevās %s: %s", rel, e)
            report["errors"].append(f"Neizdevās lejupielādēt {rel}: {e}")
            prog.advance(item.filename)
            continue
        state.files[item.key] = {"version": item.version, "path": rel,
                                 "downloaded": datetime.now().isoformat(timespec="seconds")}
        report["updated" if entry else "new"].append(rel)
        log.info("%s: %s", "atjaunināts" if entry else "jauns", rel)
        prog.advance(item.filename)
    prog.finish(f"{len(report['new'])} jauni, {len(report['updated'])} atjaunināti"
                + (f", {len(report['errors'])} kļūdas" if report["errors"] else ""))
    return report


def run_sync(cfg: Config, redownload: bool = False, no_calendar: bool = False, prog=None,
             interactive: bool = True) -> dict:
    prog = prog or NullProgress()
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(tz)
    state = State(cfg.data_dir / "state.json")
    out = cfg.output_dir
    out.mkdir(parents=True, exist_ok=True)

    with run_lock(cfg), make_source(cfg, interactive, prog) as src:
        prog.note(f"Pieslēdzas estudijām ({src.name} režīms)…")
        info = src.site_info()
        courses = filter_courses(src.courses(), cfg)
        log.info("Kursi (%d): %s", len(courses), ", ".join(c.label for c in courses))
        result = src.collect(courses, prog)
        names: dict[int, str] = {}
        for c in courses:
            n = course_dir_name(c, cfg.course_folder_name)
            if n in names.values():
                n = f"{n} ({c.id})"
            names[c.id] = n
        course_dirs = {cid: out / n for cid, n in names.items()}
        matchers = {c.id: Matcher.build(cfg.program, cfg.group, cfg.my_groups, result.groups.get(c.id, []),
                                        cfg.other_program_pattern or None) for c in courses}
        report = sync_files(cfg, src, result.files, course_dirs, state, redownload, matchers, prog)

    by_id = {c.id: c for c in courses}
    window = [d for d in result.deadlines.values()
              if now - timedelta(days=21) <= d.due <= now + timedelta(days=cfg.lookahead_days)]
    for d in window:
        m = matchers.get(d.course_id)
        if m:
            d.relevance = m.first(d.title, d.section, d.details[:400])
    keep_all = cfg.other_groups == "keep"
    moodle = [d for d in window if keep_all or d.relevance != OTHER]
    others = [d for d in window if not keep_all and d.relevance == OTHER]
    hidden = {(d.course_id, d.title) for d in others}
    scan = [t for t in result.texts if not (t.kind == "uzdevums" and (t.course_id, t.title) in hidden)]
    text_dl = find_text_deadlines(scan, matchers, moodle, now, tz, cfg.lookahead_days)

    for c in courses:
        write_course_info(out, c, names[c.id], [d for d in moodle if d.course_id == c.id],
                          [t for t in result.texts if t.course_id == c.id],
                          [ln for ln in result.links if ln.course_id == c.id], result.groups.get(c.id, []),
                          [d for d in others if d.course_id == c.id])

    cal = list(moodle)
    if cfg.include_text_dates:
        cal += [d for d in text_dl if keep_all or d.relevance != OTHER]
    warnings = list(result.warnings)
    if cfg.ics:
        write_ics(out / "termini.ics", cal, by_id, cfg.reminders_minutes)
    gcal_changes = None
    if cfg.google and not no_calendar:
        try:
            from . import gcal
            prog.note("Atjaunina Google Calendar…")
            gcal_changes = gcal.sync(cfg, state, cal, by_id, now)
        except Exception as e:
            log.exception("Google Calendar")
            warnings.append(f"Google Calendar: {e}")

    from . import changes as chg
    ch = chg.compute(state, now, by_id, moodle, text_dl, result.texts, report)
    changes_md = chg.render_md(ch, by_id)
    chg.append_changelog(out, ch, changes_md)
    write_digest(out, now, info.get("fullname", ""), by_id, moodle, text_dl, report, warnings, names,
                 changes_md, ch.previous_run, others, describe_filter(cfg, matchers))
    if cfg.notify:
        note = chg.notification(ch, by_id)
        if note:
            from .notify import send
            send(*note, open_path=out / chg.CHANGELOG)

    drive_copied: list[str] = []
    if cfg.drive_enabled:
        try:
            from .drive import mirror
            prog.note("Kopē uz Drive…")
            drive_copied = mirror(cfg, state)
        except Exception as e:
            log.exception("Drive")
            warnings.append(f"Drive: {e}")

    write_view(cfg, now, info, by_id, names, moodle, text_dl, others, ch, changes_md, report, warnings,
               describe_filter(cfg, matchers), drive_copied, gcal_changes)

    state.data["last_run"] = now.isoformat(timespec="seconds")
    state.data["upcoming"] = [
        {"due": d.due.isoformat(), "title": d.title, "kind": d.kind,
         "course": by_id[d.course_id].label if d.course_id in by_id else "", "status": d.status}
        for d in sorted(cal, key=lambda d: d.due) if d.due >= now][:15]
    state.save()
    return {"courses": len(courses), "deadlines": len(moodle), "text_deadlines": len(text_dl),
            "new": len(report["new"]), "updated": len(report["updated"]), "errors": len(report["errors"]),
            "warnings": len(warnings), "gcal_changes": gcal_changes, "output": str(out),
            "changes_text": chg.render_console(ch, by_id), "drive_copied": len(drive_copied)}


def sync_with_relogin(cfg: Config, redownload: bool = False, no_calendar: bool = False, prog=None,
                      interactive: bool = True) -> dict:
    """Sinhronizē; ja API piekļuve beigusies, atver redzamu pieteikšanās logu (MFA kods) un mēģina vēlreiz."""
    try:
        return run_sync(cfg, redownload, no_calendar, prog, interactive)
    except LoginRequired:
        auth = load_auth(cfg) or {}
        if not (interactive and cfg.login_popup) or auth.get("mode") == "web":
            raise  # pārlūka režīmā logs jau tika atvērts WebSource iekšā
        from .auth import interactive_login
        interactive_login(cfg, prog=prog)
        return run_sync(cfg, redownload, no_calendar, prog, interactive)


def _dl_json(d, by_id: dict) -> dict:
    c = by_id.get(d.course_id)
    return {"uid": d.uid, "kind": d.kind, "title": d.title, "course": c.label if c else "",
            "course_full": c.fullname if c else "", "due": d.due.isoformat(),
            "start": d.start.isoformat() if d.start else None, "url": d.url, "status": d.status,
            "done": d.done, "source": d.source, "relevance": d.relevance, "section": d.section,
            "details": (d.details or "")[:700]}


def write_view(cfg: Config, now, info: dict, by_id: dict, names: dict, moodle, text_dl, others, ch, changes_md,
               report: dict, warnings: list[str], filter_desc: str, drive_copied: list[str], gcal_changes) -> None:
    """Dati web panelim (view.json profila mapē)."""
    import json
    lo = now - timedelta(days=14)
    view = {
        "generated": now.isoformat(timespec="seconds"),
        "user": info.get("fullname", ""),
        "filter": filter_desc,
        "deadlines": [_dl_json(d, by_id) for d in sorted(moodle, key=lambda d: d.due) if d.due >= lo],
        "text_dates": [_dl_json(d, by_id) for d in text_dl if d.relevance != OTHER],
        "hidden": [_dl_json(d, by_id) for d in sorted(others, key=lambda d: d.due) if d.due >= lo]
                  + [_dl_json(d, by_id) for d in text_dl if d.relevance == OTHER],
        "changes": {"md": changes_md, "counts": ch.counts(), "first_run": ch.first_run, "empty": ch.empty},
        "courses": [{"id": cid, "label": c.label, "full": c.fullname, "url": c.url, "dir": names.get(cid, "")}
                    for cid, c in sorted(by_id.items(), key=lambda kv: kv[1].fullname)],
        "report": {k: report.get(k, []) for k in ("new", "updated", "skipped", "errors", "other")},
        "warnings": warnings,
        "drive_copied": drive_copied,
        "gcal_changes": gcal_changes,
    }
    p = cfg.data_dir / "view.json"
    tmp = p.with_name("view.json.tmp")
    tmp.write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
