"""Automātiska palaišana: Windows Task Scheduler vai cron (Linux, macOS, Android/Termux)."""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config

PROJECT_DIR = Path(__file__).resolve().parent.parent
RUNNER = PROJECT_DIR / "run.py"


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def _task_name(cfg: Config) -> str:
    return f"EstudijasSync-{cfg.profile}"


def _python_windowless() -> str:
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


def install(cfg: Config) -> str:
    if platform.system() == "Windows":
        return _install_windows(cfg)
    return _install_cron(cfg)


def uninstall(cfg: Config) -> str:
    if platform.system() == "Windows":
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"Unregister-ScheduledTask -TaskName '{_task_name(cfg)}' -Confirm:$false"],
                           capture_output=True, text=True)
        return "Uzdevums noņemts." if r.returncode == 0 else r.stderr.strip()
    _write_cron(cfg, [])
    return "Cron ieraksti noņemti."


def _install_windows(cfg: Config) -> str:
    triggers = []
    for i, t in enumerate(cfg.schedule_times):
        triggers.append(f"$t{i} = New-ScheduledTaskTrigger -Daily -At '{t}'")
    tvars = ",".join(f"$t{i}" for i in range(len(cfg.schedule_times)))
    args = f'"{RUNNER}" --profile {cfg.profile} sync'
    ps = "\n".join([
        f"$a = New-ScheduledTaskAction -Execute '{_python_windowless()}' -Argument '{args}' "
        f"-WorkingDirectory '{PROJECT_DIR}'",
        *triggers,
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)",
        f"Register-ScheduledTask -TaskName '{_task_name(cfg)}' -Action $a -Trigger {tvars} -Settings $s "
        f"-Description 'RTU estudiju sinhronizācija ({cfg.profile})' -Force | Out-Null",
    ])
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return (f"Windows Task Scheduler uzdevums '{_task_name(cfg)}' izveidots: {', '.join(cfg.schedule_times)}. "
            "Ja dators tobrīd bija izslēgts, tas palaidīsies, kad dators ieslēgsies.")


def _cron_lines(cfg: Config) -> list[str]:
    log = cfg.data_dir / "cron.log"
    marker = f"# estudijas-sync:{cfg.profile}"
    lines = []
    for t in cfg.schedule_times:
        h, m = t.split(":")
        cmd = (f"cd {shlex.quote(str(PROJECT_DIR))} && {shlex.quote(sys.executable)} {shlex.quote(str(RUNNER))} "
               f"--profile {shlex.quote(cfg.profile)} sync >> {shlex.quote(str(log))} 2>&1")
        lines.append(f"{int(m)} {int(h)} * * * {cmd} {marker}")
    return lines


def _write_cron(cfg: Config, new_lines: list[str]) -> None:
    if not shutil.which("crontab"):
        hint = "pkg install cronie termux-services && sv-enable crond" if is_termux() else "instalē cron"
        raise RuntimeError(f"Nav atrasta 'crontab' komanda ({hint}).")
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = cur.stdout.splitlines() if cur.returncode == 0 else []
    marker = f"# estudijas-sync:{cfg.profile}"
    keep = [ln for ln in existing if not ln.rstrip().endswith(marker)]
    content = "\n".join(keep + new_lines).strip() + "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def _install_cron(cfg: Config) -> str:
    _write_cron(cfg, _cron_lines(cfg))
    msg = f"Cron ieraksti pievienoti: {', '.join(cfg.schedule_times)}."
    if is_termux():
        msg += ("\nTermux: pārliecinies, ka crond darbojas (sv-enable crond) un Termux nav "
                "akumulatora optimizācijā; ieteicams arī 'termux-wake-lock'.")
    elif platform.system() == "Darwin":
        msg += "\nmacOS: ja izvades mape ir Documents, dod cron 'Full Disk Access' (System Settings → Privacy)."
    return msg
