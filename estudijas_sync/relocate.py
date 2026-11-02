"""Izvades mapes maiņa: pārvietot jau lejupielādēto vai lejupielādēt no jauna."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, State, set_toml_values

log = logging.getLogger(__name__)
GENERATED = ("UZDEVUMI.md", "JAUNUMI.md", "termini.ics")

_PICKER = r"""
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    sys.exit(3)
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
p = filedialog.askdirectory(initialdir=sys.argv[1] if len(sys.argv) > 1 else None,
                            title="Izvēlies mapi RTU estudiju failiem", mustexist=False)
root.destroy()
sys.stdout.write(p or "")
"""


def pick_folder(initial: str = "") -> str | None:
    """Atver sistēmas mapes izvēles logu (atsevišķā procesā). None — atcelts; izmet RuntimeError, ja nav pieejams."""
    init = initial if initial and Path(initial).exists() else str(Path.home())
    r = subprocess.run([sys.executable, "-c", _PICKER, init], capture_output=True, text=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode == 3:
        raise RuntimeError("Mapes izvēles logs nav pieejams (nav tkinter). Ieraksti ceļu pats.")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:] or "Mapes izvēle neizdevās")
    path = r.stdout.strip()
    return str(Path(path)) if path else None


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def change_folder(cfg: Config, new_dir: str, mode: str = "move") -> dict:
    """mode: "move" — pārvietot esošos failus; "redownload" — nākamajā sinhronizācijā lejupielādēt visu no jauna
    (vecie faili paliek vecajā mapē, tos vari izdzēst pats)."""
    if mode not in ("move", "redownload"):
        raise ValueError("mode jābūt move vai redownload")
    new = Path(os.path.expandvars(os.path.expanduser(new_dir.strip().strip('"'))))
    if not new.is_absolute():
        raise ValueError("Vajag pilnu ceļu, piem. D:\\RTU estudijas")
    old = cfg.output_dir
    if _same(old, new):
        return {"moved": 0, "path": str(new), "message": "Mape nav mainījusies."}
    if new.exists() and new.is_file():
        raise ValueError("Norādītais ceļš ir fails, nevis mape")
    try:
        if old.exists() and old.resolve() in new.resolve().parents:
            raise ValueError("Jaunā mape nevar būt vecās mapes iekšienē")
    except OSError:
        pass
    new.mkdir(parents=True, exist_ok=True)
    test = new / ".estudijas_test"
    try:
        test.write_text("ok")
        test.unlink()
    except OSError as e:
        raise ValueError(f"Mapē nevar rakstīt: {e}") from e

    state = State(cfg.data_dir / "state.json")
    moved, failed = 0, []
    if mode == "move" and old.exists():
        rels = {e["path"] for e in state.files.values() if e.get("path")}
        # kursu _info mapes un kopsavilkumi
        for e in list(rels):
            course = e.split("/")[0]
            if (old / course / "_info").exists():
                rels.add(f"{course}/_info")
        rels.update(n for n in GENERATED if (old / n).exists())
        for rel in sorted(rels):
            src, dst = old / rel, new / rel
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    shutil.rmtree(src)
                else:
                    shutil.move(str(src), str(dst))
                moved += 1
            except OSError as ex:
                failed.append(f"{rel}: {ex}")
        # iztīra tukšās mapes vecajā vietā (lietotāja failus neaiztiek)
        for dirpath, _dirs, _files in sorted(os.walk(old), key=lambda t: -len(t[0])):
            try:
                if not os.listdir(dirpath) and Path(dirpath) != old:
                    os.rmdir(dirpath)
            except OSError:
                pass
    elif mode == "redownload":
        state.data["files"] = {}
        state.save()

    set_toml_values(cfg.config_path, {(None, "output_dir"): str(new).replace("\\", "/")})
    msg = {"move": f"Mape nomainīta, pārvietoti {moved} vienumi.",
           "redownload": "Mape nomainīta. Nākamajā sinhronizācijā viss tiks lejupielādēts no jauna."}[mode]
    if failed:
        msg += f" Neizdevās pārvietot {len(failed)}: " + "; ".join(failed[:5])
    log.info("Izvades mape: %s → %s (%s)", old, new, mode)
    return {"moved": moved, "failed": failed, "path": str(new), "message": msg}
