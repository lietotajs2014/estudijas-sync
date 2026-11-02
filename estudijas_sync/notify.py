"""Darbvirsmas/telefona paziņojums bez papildu bibliotēkām."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

_PS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml($env:ES_TOAST_XML)
$t = New-Object Windows.UI.Notifications.ToastNotification $x
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($t)
"""


def send(title: str, body: str, open_path: Path | None = None) -> bool:
    try:
        system = platform.system()
        if system == "Windows":
            launch = f' activationType="protocol" launch="{escape(open_path.resolve().as_uri())}"' if open_path else ""
            lines = "".join(f"<text>{escape(x)}</text>" for x in body.splitlines()[:3])
            xml = (f'<toast{launch}><visual><binding template="ToastGeneric"><text>{escape(title)}</text>'
                   f"{lines}</binding></visual></toast>")
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_TOAST],
                           env={**os.environ, "ES_TOAST_XML": xml}, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        if "com.termux" in os.environ.get("PREFIX", "") and shutil.which("termux-notification"):
            cmd = ["termux-notification", "--title", title, "--content", body, "--id", "estudijas-sync"]
            if open_path:
                cmd += ["--action", f"termux-open '{open_path}'"]
            subprocess.run(cmd, capture_output=True, timeout=30)
            return True
        if system == "Darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
            subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"'],
                           capture_output=True, timeout=30)
            return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "estudijas-sync", title, body], capture_output=True, timeout=30)
            return True
    except Exception as e:  # paziņojums nav kritisks
        log.info("Paziņojumu nosūtīt neizdevās: %s", e)
    return False
