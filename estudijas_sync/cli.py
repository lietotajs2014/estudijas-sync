"""Komandrinda: python run.py [--profile VĀRDS] <komanda>"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import auth_path, load_auth, load_config
from .model import LoginRequired

log = logging.getLogger("estudijas_sync")


def setup_logging(cfg, verbose: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):  # atkārtoti izsaucot (piem., pēc mapes maiņas) — aizver veco žurnālu
        if isinstance(h, (RotatingFileHandler, logging.StreamHandler)):
            root.removeHandler(h)
            h.close()
    fh = RotatingFileHandler(cfg.data_dir / "sync.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setLevel(logging.DEBUG if verbose else logging.WARNING)
        sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(sh)


def ask_identity(cfg, program: str | None = None, group: str | None = None, force: bool = False):
    """Pajautā (vai paņem no argumentiem) studiju programmu un grupu un saglabā konfigurācijā."""
    from .config import set_config_values
    interactive = sys.stdin is not None and sys.stdin.isatty()
    if program is None and interactive and (force or not cfg.program):
        cur = f" [{cfg.program}]" if cfg.program else ""
        program = input(f"Tava studiju programma/plūsma (piem. RMCE0){cur}: ").strip() or cfg.program
    if group is None and interactive and (force or not cfg.group):
        cur = f" [{cfg.group}]" if cfg.group else ""
        group = input(f"Tava grupa (piem. 3){cur}: ").strip() or cfg.group
    vals = {}
    if program is not None:
        vals["program"] = program.strip().upper()
    if group is not None:
        g = group.strip().rstrip(".").lower().replace("grupa", "").replace("gr", "").strip(" .")
        vals["group"] = g
    if vals:
        set_config_values(cfg.config_path, vals)
        cfg = load_config(cfg.profile, cfg.config_path)
    return cfg


def _relogin_needed(cfg, msg: str) -> int:
    from .outputs import write_banner
    text = f"Jāpiesakās no jauna: palaid `python run.py --profile {cfg.profile} login` ({msg})"
    print("⚠ " + text)
    log.error(text)
    try:
        write_banner(cfg.output_dir, text)
    except Exception:
        log.exception("banner")
    if cfg.google:
        try:
            from . import gcal
            from .config import State
            st = State(cfg.data_dir / "state.json")
            gcal.add_notice(cfg, st, "jāpiesakās estudijās no jauna", datetime.now(ZoneInfo(cfg.timezone)))
            st.save()
        except Exception:
            log.exception("gcal notice")
    return 2


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="run.py", description="RTU estudiju (Moodle) sinhronizācija")
    ap.add_argument("--profile", default="default", help="profila nosaukums (vairāki konti vienā datorā)")
    ap.add_argument("--config", help="cits konfigurācijas faila ceļš")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ip0 = sub.add_parser("init", help="izveidot konfigurāciju un ievadīt programmu/grupu")
    ip0.add_argument("--program", help="studiju programma/plūsma, piem. RMCE0")
    ip0.add_argument("--group", help="grupa, piem. 3")
    lp = sub.add_parser("login", help="pieteikties ar Microsoft (atver pārlūku)")
    lp.add_argument("--web", action="store_true", help="neizmantot API, tikai pārlūka sesiju")
    sp = sub.add_parser("sync", help="sinhronizēt")
    sp.add_argument("--redownload", action="store_true", help="lejupielādēt visus failus no jauna")
    sp.add_argument("--no-calendar", action="store_true", help="neatjaunināt Google Calendar")
    sp.add_argument("-q", "--quiet", action="store_true", help="bez progresa joslas")
    sp.add_argument("--no-login-window", action="store_true",
                    help="neatvērt pārlūka logu, ja vajag pieteikties (tikai brīdināt)")
    sub.add_parser("status", help="parādīt stāvokli un tuvākos termiņus")
    gp = sub.add_parser("gcal-auth", help="autorizēt Google Calendar")
    gp.add_argument("--credentials", help="ceļš uz Google OAuth credentials.json (ja nav norādīts — iestatījumos esošais)")
    sub.add_parser("install-schedule", help="palaist automātiski (laiki no konfigurācijas)")
    sub.add_parser("uninstall-schedule", help="noņemt automātisko palaišanu")
    sub.add_parser("update", help="atjaunināt skriptu uz jaunāko versiju (git pull)")
    fp = sub.add_parser("set-folder", help="nomainīt mapi, kurā tiek lejupielādēti faili")
    fp.add_argument("path", nargs="?", help="jaunā mape (ja nav norādīta — atver izvēles logu)")
    g = fp.add_mutually_exclusive_group()
    g.add_argument("--move", action="store_true", help="pārvietot jau lejupielādētos failus (noklusējums)")
    g.add_argument("--redownload", action="store_true", help="nepārvietot; nākamreiz lejupielādēt visu no jauna")
    wp = sub.add_parser("web", help="atvērt web paneli pārlūkā")
    wp.add_argument("--port", type=int, default=8765)
    wp.add_argument("--no-browser", action="store_true")
    ip = sub.add_parser("import-auth", help="iekopēt auth.json no cita datora (piem., Android/Termux)")
    ip.add_argument("file")
    args = ap.parse_args(argv)

    cfg = load_config(args.profile, Path(args.config).expanduser() if args.config else None)
    if not args.config:
        # viss vienā mapē: profila dati → <izvades mape>/.estudijas-sync (ja sinhronizācija tobrīd nenotiek)
        from .config import migrate_data_dir
        from .lock import is_locked
        if not is_locked(cfg.data_dir / "sync.lock"):
            try:
                cfg = migrate_data_dir(cfg)
            except OSError as e:
                print(f"Datu mapi neizdevās pārcelt: {e}")
    setup_logging(cfg, args.verbose)

    if args.cmd == "init":
        cfg = ask_identity(cfg, args.program, args.group, force=True)
        print(f"Konfigurācija: {cfg.config_path}\nIzvades mape: {cfg.output_dir}\n"
              f"Atlase: {cfg.program or '—'} · grupa {cfg.group or '—'}\n"
              "Rediģē failu, ja vajag citu mapi, tad palaid: python run.py login")
        return 0

    if args.cmd == "login":
        cfg = ask_identity(cfg)
        from .auth import interactive_login
        try:
            auth = interactive_login(cfg, force_web=args.web)
        except LoginRequired as e:
            print(f"✖ {e}")
            return 2
        print(f"\nRežīms: {auth['mode']}. Tagad palaid: python run.py --profile {cfg.profile} sync")
        return 0

    if args.cmd == "web":
        from .webui import serve
        serve(cfg.profile, Path(args.config).expanduser() if args.config else None,
              port=args.port, open_browser=not args.no_browser)
        return 0

    if args.cmd == "set-folder":
        from .relocate import change_folder, pick_folder
        path = args.path
        if not path:
            try:
                path = pick_folder(str(cfg.output_dir))
            except RuntimeError as e:
                print(f"✖ {e}")
                return 1
            if not path:
                print("Atcelts.")
                return 0
        try:
            r = change_folder(cfg, path, "redownload" if args.redownload else "move")
        except ValueError as e:
            print(f"✖ {e}")
            return 1
        print(f"✔ {r['message']}\n  Jaunā mape: {r['path']}")
        return 0

    if args.cmd == "update":
        from .updater import do_update
        ok, msg = do_update()
        print(("✔ " if ok else "✖ ") + msg)
        return 0 if ok else 1

    if args.cmd == "import-auth":
        src = Path(args.file).expanduser()
        data = json.loads(src.read_text(encoding="utf-8"))
        if data.get("mode") != "api":
            print("✖ Pārnest var tikai API režīma pieteikšanos (pārlūka sesija ir piesaistīta datoram).")
            return 1
        shutil.copyfile(src, auth_path(cfg))
        print(f"✔ Iekopēts: {auth_path(cfg)}")
        return 0

    if args.cmd == "sync":
        from .sync import AlreadyRunning, sync_with_relogin
        try:
            from .progress import Progress
            r = sync_with_relogin(cfg, redownload=args.redownload, no_calendar=args.no_calendar,
                         prog=Progress(enabled=False if args.quiet else None),
                         interactive=not args.no_login_window)
        except LoginRequired as e:
            return _relogin_needed(cfg, str(e))
        except AlreadyRunning as e:
            print(e)
            return 0
        except Exception as e:
            log.exception("Sinhronizācija neizdevās")
            print(f"✖ Kļūda: {e} (sīkāk: {cfg.data_dir / 'sync.log'})")
            return 1
        print(f"✔ {r['courses']} kursi · {r['deadlines']} termiņi (+{r['text_deadlines']} no teksta) · "
              f"{r['new']} jauni, {r['updated']} atjaunināti faili"
              + (f" · {r['errors']} kļūdas" if r["errors"] else "")
              + (f" · Google: {r['gcal_changes']} izmaiņas" if r["gcal_changes"] is not None else ""))
        print("\n" + r["changes_text"] + "\n")
        print(f"  Kopsavilkums: {Path(r['output']) / 'UZDEVUMI.md'}")
        print(f"  Jaunumu vēsture: {Path(r['output']) / 'JAUNUMI.md'}")
        return 0

    if args.cmd == "status":
        from .config import State
        auth = load_auth(cfg) or {}
        st = State(cfg.data_dir / "state.json").data
        print(f"Profils: {cfg.profile}\nKonfigurācija: {cfg.config_path}\nIzvade: {cfg.output_dir}")
        print(f"Pieteikšanās: {auth.get('mode', 'nav')} (kopš {auth.get('obtained', '—')})"
              + (f", {auth.get('fullname')}" if auth.get("fullname") else ""))
        print(f"Pēdējā sinhronizācija: {st.get('last_run', '—')}\n")
        for u in st.get("upcoming", []):
            due = datetime.fromisoformat(u["due"])
            print(f"  {due:%d.%m %H:%M}  [{u['kind']}] {u['course']}: {u['title']}"
                  + (f"  ({u['status']})" if u.get("status") else ""))
        return 0

    if args.cmd == "gcal-auth":
        from . import gcal
        from .config import State
        st = State(cfg.data_dir / "state.json")
        if args.credentials:
            from .config import set_toml_values
            from .webui import check_credentials_file
            p = Path(args.credentials).expanduser()
            try:
                check_credentials_file(p)
            except ValueError as e:
                print(f"✖ {e}")
                return 1
            set_toml_values(cfg.config_path, {("calendar", "google_credentials"): str(p.resolve()).replace("\\", "/")})
            cfg = load_config(cfg.profile, cfg.config_path)
        svc = gcal.get_service(cfg, interactive=True)
        cid = gcal.ensure_calendar(svc, cfg, st)
        st.save()
        print(f"✔ Google Calendar gatavs (kalendārs '{cfg.google_calendar_name}', id {cid}).\n"
              f"  Ieslēdz konfigurācijā [calendar] google = true")
        return 0

    if args.cmd in ("install-schedule", "uninstall-schedule"):
        from . import schedule
        try:
            print(schedule.install(cfg) if args.cmd == "install-schedule" else schedule.uninstall(cfg))
        except Exception as e:
            print(f"✖ {e}")
            return 1
        return 0
    return 1
