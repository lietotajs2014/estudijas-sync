"""Vienkārša progresa josla terminālī (bez papildu bibliotēkām).

Rāda tikai tad, ja palaists interaktīvā terminālī — automātiskajās palaišanās klusē.
"""
from __future__ import annotations

import shutil
import sys
import time


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Progress:
    def __init__(self, enabled: bool | None = None, stream=None):
        self.stream = stream or sys.stderr
        if enabled is None:
            enabled = bool(self.stream) and hasattr(self.stream, "isatty") and self.stream.isatty()
        self.enabled = enabled
        self.total = 0
        self.count = 0
        self.title = ""
        self.bytes_total = 0
        self.bytes_done = 0
        self._label = ""
        self._last = 0.0
        self._t0 = 0.0
        self._active = False

    # ---- fāzes ----
    def start(self, title: str, total: int, bytes_total: int = 0) -> None:
        self.finish()
        self.title, self.total, self.count = title, max(total, 0), 0
        self.bytes_total, self.bytes_done = bytes_total, 0
        self._label, self._t0, self._active = "", time.time(), True
        self._draw(force=True)

    def advance(self, label: str = "", n: int = 1) -> None:
        self.count = min(self.count + n, self.total) if self.total else self.count + n
        self._label = label
        self._draw(force=True)

    def label(self, label: str) -> None:
        self._label = label
        self._draw()

    def add_bytes(self, n: int) -> None:
        self.bytes_done += n
        self._draw()

    def finish(self, summary: str = "") -> None:
        if not self._active:
            return
        self._active = False
        if self.enabled:
            dur = time.time() - self._t0
            msg = summary or f"{self.count}/{self.total}"
            self._write(f"✔ {self.title}: {msg} ({dur:.0f} s)", end="\n")

    def note(self, text: str) -> None:
        """Rinda virs joslas (piem., brīdinājums), josla turpinās zem tās."""
        if self.enabled:
            self._write(text, end="\n")
            if self._active:
                self._draw(force=True)

    # ---- zīmēšana ----
    def _write(self, text: str, end: str = "") -> None:
        width = shutil.get_terminal_size((100, 20)).columns
        try:
            self.stream.write("\r" + text[: width - 1].ljust(width - 1) + end)
            self.stream.flush()
        except Exception:
            self.enabled = False

    def _draw(self, force: bool = False) -> None:
        if not (self.enabled and self._active):
            return
        now = time.time()
        if not force and now - self._last < 0.1:
            return
        self._last = now
        width = shutil.get_terminal_size((100, 20)).columns
        if self.bytes_total:
            frac = min(self.bytes_done / self.bytes_total, 1.0)
        elif self.total:
            frac = self.count / self.total
        else:
            frac = 0.0
        bar_w = max(10, min(30, width // 4))
        filled = int(bar_w * frac)
        bar = "█" * filled + "░" * (bar_w - filled)
        info = f"{self.count}/{self.total}"
        if self.bytes_total:
            info += f" · {_fmt_bytes(self.bytes_done)}/{_fmt_bytes(self.bytes_total)}"
        elif self.bytes_done:
            info += f" · {_fmt_bytes(self.bytes_done)}"
        head = f"{self.title} {bar} {int(frac * 100):3d}% {info}"
        lab = f" · {self._label}" if self._label else ""
        self._write(head + lab)


class NullProgress(Progress):
    def __init__(self):
        super().__init__(enabled=False)
