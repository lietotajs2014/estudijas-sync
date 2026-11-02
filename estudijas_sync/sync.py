"""Galvenā sinhronizācija: dati → faili mapēs → kopsavilkums → kalendārs."""
from __future__ import annotations

import logging
import os
import re
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


from .lock import AlreadyRunning, file_lock  # noqa: E402  AlreadyRunning izmanto cli/webui

__all__ = ["AlreadyRunning", "run_sync", "sync_with_relogin", "download_selected"]


def run_lock(cfg: Config):
    return file_lock(cfg.data_dir / "sync.lock")


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


def assignment_folder(name: str, due: datetime | None) -> str:
    """Uzdevuma mape ar termiņu nosaukumā, piem. "MD1 — Kirhofa likumi (līdz 05.11.)"."""
    base = sanitize(name, 70)
    return sanitize(f"{base} (līdz {due:%d.%m.})", 90) if due else base


def plan_path(cfg: Config, item: FileItem, course_dir: Path, cats, dues: dict | None = None) -> tuple[str, Path]:
    cat = classify_file(item, cats)
    fname = sanitize(item.filename, 120)
    if cat == "Lekcijas" and item.modtype == "resource":
        fname = f"{item.section_num:02d}_{fname}"
    parts = [course_dir, Path(sanitize(cat))]
    if item.modtype == "assign":
        parts.append(Path(assignment_folder(item.module, (dues or {}).get(f"cm-{item.cmid}"))))
    if item.modtype == "folder":
        parts.append(Path(sanitize(item.module, 60)))
        parts += [Path(sanitize(p, 60)) for p in item.subpath.split("/") if p]
    return cat, Path(*parts) / fname


def _shortcut(path: Path, url: str) -> None:
    """Windows interneta saīsne (.url) — dubultklikšķis atver saiti pārlūkā."""
    from .util import write_if_changed
    try:
        write_if_changed(path, f"[InternetShortcut]\r\nURL={url}\r\n")
    except OSError:
        pass


def _relocate(out: Path, old_rel: str, new_rel: str) -> bool:
    """Pārvieto jau lejupielādētu failu uz jauno vietu (piem., mainījies termiņš uzdevuma mapes nosaukumā)."""
    import shutil
    src, dst = out / old_rel, out / new_rel
    if not src.exists() or dst.exists():
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        old_dir = src.parent
        for leftover in old_dir.glob("*.url"):
            leftover.unlink(missing_ok=True)
        while old_dir != out and old_dir.exists() and not any(old_dir.iterdir()):
            old_dir.rmdir()
            old_dir = old_dir.parent
        return True
    except OSError:
        return False


def sync_files(cfg: Config, src, files: list[FileItem], course_dirs: dict[int, Path], state: State,
               redownload: bool = False, matchers: dict[int, Matcher] | None = None, prog=None,
               dues: dict | None = None) -> dict:
    """Lejupielādē jaunos/mainītos failus un atgriež arī pilnu katalogu (visi estudiju faili ar statusu)."""
    prog = prog or NullProgress()
    cats = compile_categories(cfg.categories)
    report = {"new": [], "updated": [], "skipped": [], "errors": [], "other": [], "catalog": []}
    matchers = matchers or {}
    used: dict[Path, str] = {}
    max_bytes = cfg.download_max_mb * 1024 * 1024
    out = cfg.output_dir
    only = {c.casefold() for c in cfg.only_categories}
    first_seen: dict = state.data.setdefault("first_seen", {})
    now_iso = datetime.now().isoformat(timespec="seconds")
    todo: list[tuple[FileItem, Path, str, dict | None, dict]] = []
    for item in files:
        cdir = course_dirs.get(item.course_id)
        if cdir is None:
            continue
        cat, path = plan_path(cfg, item, cdir, cats, dues)
        status = None
        m = matchers.get(item.course_id)
        is_other = bool(m and cfg.other_groups != "keep" and
                        m.first(f"{item.filename} {item.module}", item.subpath, item.section) == OTHER)
        if is_other and cfg.other_groups in ("skip", "folder"):
            path = cdir / "_Citām grupām" / path.relative_to(cdir)
        if path in used and used[path] != item.key:
            path = path.with_name(f"{path.stem} ({item.cmid}){path.suffix}")
        if used.get(path) == item.key:
            continue  # tas pats fails divreiz sarakstā
        used[path] = item.key
        rel = path.relative_to(out).as_posix()
        first_seen.setdefault(item.key, now_iso)
        entry = state.files.get(item.key)
        # jau lejupielādēts, bet plānotā vieta mainījusies (piem., termiņš mapes nosaukumā) — pārvieto
        if entry and entry.get("path") and entry["path"] != rel and entry.get("version") == item.version:
            if _relocate(out, entry["path"], rel):
                entry["path"] = rel
                report.setdefault("moved", []).append(rel)
        if item.modtype == "assign" and item.page_url and entry and (out / entry.get("path", "")).exists():
            _shortcut((out / entry["path"]).parent / "Atvērt uzdevumu estudijās.url", item.page_url)
        row = {"key": item.key, "course_id": item.course_id, "category": cat, "filename": item.filename,
               "module": item.module, "section": item.section, "modtype": item.modtype, "cmid": str(item.cmid),
               "page_url": item.page_url, "created": item.created,
               "deadline_uid": f"cm-{item.cmid}" if item.modtype == "assign" else None,
               "size": item.size, "modified": item.modified, "first_seen": first_seen[item.key],
               "path": (entry or {}).get("path") or rel, "planned": rel, "other_group": is_other,
               "downloaded_at": (entry or {}).get("downloaded")}
        report["catalog"].append(row)
        if only and cat.casefold() not in only:
            status = "unselected"
        elif is_other and cfg.other_groups == "skip":
            status = "other"
            report["other"].append(f"{item.filename} — {item.section} / {item.module}")
        elif os.path.splitext(item.filename)[1].lower() in cfg.skip_extensions:
            status = "ext"
            report["skipped"].append(f"{rel} (paplašinājums)")
        elif item.size and item.size > max_bytes:
            status = "big"
            report["skipped"].append(f"{rel} ({item.size / 1048576:.0f} MB)")
        elif entry and entry.get("version") == item.version and not redownload:
            status = "downloaded"  # nav mainījies (arī ja lietotājs to apzināti izdzēsa — nelādējam no jauna)
        if status:
            # ja agrāk lejupielādēts (piem., pēc izvēles), tas joprojām ir pieejams
            row["status"] = "downloaded" if entry and status != "downloaded" and entry.get("manual") else status
            continue
        row["status"] = "pending"
        todo.append((item, path, rel, entry, row))

    if todo:
        prog.start("Lejupielādē", len(todo), sum(i.size or 0 for i, *_ in todo))
        for item, path, rel, entry, row in todo:
            prog.label(item.filename)
            try:
                src.download(item, path, on_bytes=prog.add_bytes)
            except LoginRequired:
                raise
            except Exception as e:
                log.warning("Lejupielāde neizdevās %s: %s", rel, e)
                report["errors"].append(f"Neizdevās lejupielādēt {rel}: {e}")
                row["status"] = "error"
                prog.advance(item.filename)
                continue
            state.files[item.key] = {"version": item.version, "path": rel, "downloaded": now_iso}
            row.update(status="downloaded", path=rel, downloaded_at=now_iso)
            if item.modtype == "assign" and item.page_url:
                _shortcut(path.parent / "Atvērt uzdevumu estudijās.url", item.page_url)
            report["updated" if entry else "new"].append(rel)
            log.info("%s: %s", "atjaunināts" if entry else "jauns", rel)
            prog.advance(item.filename)
        prog.finish(f"{len(report['new'])} jauni, {len(report['updated'])} atjaunināti"
                    + (f", {len(report['errors'])} kļūdas" if report["errors"] else ""))
    _save_catalog(cfg, files, report["catalog"])
    return report


def _save_catalog(cfg: Config, files: list[FileItem], rows: list[dict]) -> None:
    """Pilnie failu dati (ar URL) lejupielādei pēc pieprasījuma no paneļa."""
    import json
    from dataclasses import asdict
    by_key = {f.key: f for f in files}
    data = {r["key"]: {"item": asdict(by_key[r["key"]]), "planned": r["planned"]} for r in rows if r["key"] in by_key}
    p = cfg.data_dir / "catalog.json"
    tmp = p.with_name("catalog.json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def download_selected(cfg: Config, keys: list[str], prog=None, interactive: bool = True) -> dict:
    """Lejupielādē paneļa atzīmētos failus (arī tos, kas citādi tiktu izlaisti)."""
    import json
    prog = prog or NullProgress()
    try:
        catalog = json.loads((cfg.data_dir / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("Failu saraksts vēl nav izveidots — vispirms sinhronizē.")
    picked = [(FileItem(**catalog[k]["item"]), catalog[k]["planned"]) for k in keys if k in catalog]
    if not picked:
        raise ValueError("Neviens no atzīmētajiem failiem vairs nav atrodams estudijās — sinhronizē no jauna.")
    state = State(cfg.data_dir / "state.json")
    done, errors = [], []
    now_iso = datetime.now().isoformat(timespec="seconds")
    with run_lock(cfg), make_source(cfg, interactive, prog) as src:
        prog.start("Lejupielādē atzīmētos", len(picked), sum(i.size or 0 for i, _ in picked))
        for item, rel in picked:
            prog.label(item.filename)
            try:
                src.download(item, cfg.output_dir / rel, on_bytes=prog.add_bytes)
                state.files[item.key] = {"version": item.version, "path": rel, "downloaded": now_iso, "manual": True}
                if item.modtype == "assign" and item.page_url:
                    _shortcut((cfg.output_dir / rel).parent / "Atvērt uzdevumu estudijās.url", item.page_url)
                done.append(rel)
            except LoginRequired:
                raise
            except Exception as e:
                errors.append(f"{item.filename}: {e}")
            prog.advance(item.filename)
        prog.finish(f"{len(done)} lejupielādēti" + (f", {len(errors)} kļūdas" if errors else ""))
    state.save()
    # atjauno statusu panelī bez pilnas sinhronizācijas
    vp = cfg.data_dir / "view.json"
    try:
        view = json.loads(vp.read_text(encoding="utf-8"))
        idx = {r["key"]: r for r in view.get("files", [])}
        for item, rel in picked:
            if item.key in state.files and item.key in idx:
                idx[item.key].update(status="downloaded", path=rel, downloaded_at=now_iso)
        vp.write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass
    return {"done": done, "errors": errors}


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
        dues = {uid: d.due for uid, d in result.deadlines.items()}
        report = sync_files(cfg, src, result.files, course_dirs, state, redownload, matchers, prog, dues)

    by_id = {c.id: c for c in courses}
    window = list(result.deadlines.values())  # visi zināmie termiņi (kursi ir tikai pašreizējie)
    from . import consult
    window, consult_events = consult.split_consult_events(window)
    consult_data = consult.build([c.id for c in courses], result.teachers, result.texts, consult_events, now)
    for c in courses:
        from .util import write_if_changed
        write_if_changed(out / names[c.id] / "_info" / "Konsultācijas un pasniedzēji.md",
                         consult.to_markdown(c.fullname, c.url, consult_data[c.id]))
    for d in window:
        m = matchers.get(d.course_id)
        if m:
            d.relevance = m.first(d.title, d.section, d.details[:400])
    keep_all = cfg.other_groups == "keep"
    moodle = [d for d in window if keep_all or d.relevance != OTHER]
    others = [d for d in window if not keep_all and d.relevance == OTHER]
    hidden = {(d.course_id, d.title) for d in others}
    scan = [t for t in result.texts if not (t.kind == "uzdevums" and (t.course_id, t.title) in hidden)]
    text_dl = find_text_deadlines(scan, matchers, moodle, now, tz, cfg.lookahead_days, cfg.lookback_days)

    for c in courses:
        write_course_info(out, c, names[c.id], [d for d in moodle if d.course_id == c.id],
                          [t for t in result.texts if t.course_id == c.id],
                          [ln for ln in result.links if ln.course_id == c.id], result.groups.get(c.id, []),
                          [d for d in others if d.course_id == c.id],
                          [r for r in report.get("catalog", []) if r["course_id"] == c.id and r.get("status") == "downloaded"])

    cal = list(moodle) + [d for d in consult_events if keep_all or d.relevance != OTHER]
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
            from .gcal import friendly_error
            warnings.append(f"Google Calendar: {friendly_error(e)}")

    from . import changes as chg
    ch = chg.compute(state, now, by_id, moodle, text_dl, result.texts, report)
    changes_md = chg.render_md(ch, by_id)
    chg.append_changelog(out, ch, changes_md)
    write_digest(out, now, info.get("fullname", ""), by_id, moodle, text_dl, report, warnings, names,
                 changes_md, ch.previous_run, others, describe_filter(cfg, matchers),
                 cfg.drive_link if cfg.drive_enabled else "")
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
               describe_filter(cfg, matchers), drive_copied, gcal_changes, consult_data)

    state.data["last_run"] = now.isoformat(timespec="seconds")
    state.data["upcoming"] = [
        {"due": d.due.isoformat(), "title": d.title, "kind": d.kind,
         "course": by_id[d.course_id].label if d.course_id in by_id else "", "status": d.status}
        for d in sorted(cal, key=lambda d: d.due) if d.due >= now][:15]
    state.save()
    return {"courses": len(courses), "deadlines": len(moodle), "text_deadlines": len(text_dl),
            "new": len(report["new"]), "updated": len(report["updated"]), "errors": len(report["errors"]),
            "warnings": len(warnings), "gcal_changes": gcal_changes, "output": str(out),
            "changes_text": chg.render_console(ch, by_id), "drive_copied": len(drive_copied),
            "warning_list": warnings}


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
    return {"uid": d.uid, "kind": d.kind, "title": d.title, "course": c.label if c else "", "course_id": d.course_id,
            "course_full": c.fullname if c else "", "due": d.due.isoformat(),
            "start": d.start.isoformat() if d.start else None, "url": d.url, "status": d.status,
            "done": d.done, "source": d.source, "relevance": d.relevance, "section": d.section,
            "details": (d.details or "")[:5000]}


def write_view(cfg: Config, now, info: dict, by_id: dict, names: dict, moodle, text_dl, others, ch, changes_md,
               report: dict, warnings: list[str], filter_desc: str, drive_copied: list[str], gcal_changes,
               consult_data: dict | None = None) -> None:
    """Dati web panelim (view.json profila mapē)."""
    import json
    lo = now - timedelta(days=cfg.lookback_days)
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
        "consult": [dict(data, course_id=cid, course=by_id[cid].label, course_full=by_id[cid].fullname, url=by_id[cid].url)
                    for cid, data in sorted((consult_data or {}).items(), key=lambda kv: by_id[kv[0]].fullname)
                    if cid in by_id],
        "files": [dict(r, course=by_id[r["course_id"]].label if r["course_id"] in by_id else "",
                       course_full=by_id[r["course_id"]].fullname if r["course_id"] in by_id else "")
                  for r in report.get("catalog", [])],
        "gcal_changes": gcal_changes,
    }
    p = cfg.data_dir / "view.json"
    tmp = p.with_name("view.json.tmp")
    tmp.write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
