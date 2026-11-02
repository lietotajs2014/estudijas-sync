"""Konfigurācija un profila mapes (katram lietotājam atsevišķi)."""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_HOME = Path(os.environ.get("ESTUDIJAS_SYNC_HOME", Path.home() / ".estudijas_sync"))
TEMPLATE = Path(__file__).with_name("config_template.toml")


LEGACY_DEFAULT = "~/Documents/RTU estudijas"


def documents_dir() -> Path:
    """Īstā "Dokumenti" mape. Windows to bieži pārvirza uz OneDrive, tāpēc ~/Documents var būt cita mape."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                            ("Data4", ctypes.c_ubyte * 8)]
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            buf = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                path = Path(buf.value)
                ctypes.windll.ole32.CoTaskMemFree(buf)
                return path
        except Exception:
            pass
    return Path.home() / "Documents"


def resolve_output_dir(raw: str) -> Path:
    if raw and raw.strip() != LEGACY_DEFAULT:
        return _path(raw)
    legacy = _path(LEGACY_DEFAULT)
    if legacy.exists() and any(legacy.iterdir()):
        return legacy  # jau ir faili vecajā noklusējuma vietā — nepārceļam bez ziņas
    return documents_dir() / "RTU estudijas"


def _path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


@dataclass
class Config:
    profile: str
    data_dir: Path
    config_path: Path
    site: str = "https://estudijas.rtu.lv"
    output_dir: Path = Path.home() / "Documents" / "RTU estudijas"
    timezone: str = "Europe/Riga"
    course_folder_name: str = "fullname"
    include_courses: list[str] = field(default_factory=list)
    exclude_courses: list[str] = field(default_factory=list)
    program: str = ""
    group: str = ""
    other_groups: str = "skip"
    other_program_pattern: str = ""
    my_groups: list[str] = field(default_factory=list)
    only_categories: list[str] = field(default_factory=list)
    download_max_mb: float = 200
    skip_extensions: list[str] = field(default_factory=list)
    lookahead_days: int = 150
    notify: bool = True
    login_popup: bool = True
    schedule_times: list[str] = field(default_factory=lambda: ["07:30", "19:30"])
    ics: bool = True
    include_text_dates: bool = True
    reminders_minutes: list[int] = field(default_factory=lambda: [1440, 120])
    google: bool = False
    google_credentials: Path = APP_HOME / "credentials.json"
    google_calendar_name: str = "RTU estudijas"
    categories: dict[str, str] = field(default_factory=dict)
    email: str = ""
    drive_enabled: bool = False
    drive_folder: Path | None = None
    drive_categories: list[str] = field(default_factory=list)
    drive_include_digest: bool = True
    drive_link: str = ""


def load_config(profile: str = "default", path: Path | None = None) -> Config:
    data_dir = APP_HOME / profile
    data_dir.mkdir(parents=True, exist_ok=True)
    path = path or data_dir / "config.toml"
    created = False
    if not path.exists():
        path.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        created = True
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not raw.get("categories"):
        raw["categories"] = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))["categories"]
    sched = raw.get("schedule", {})
    cal = raw.get("calendar", {})
    drive = raw.get("drive", {})
    cfg = Config(
        profile=profile, data_dir=data_dir, config_path=path,
        site=str(raw.get("site", "https://estudijas.rtu.lv")).rstrip("/"),
        output_dir=resolve_output_dir(str(raw.get("output_dir", ""))),
        timezone=raw.get("timezone", "Europe/Riga"),
        course_folder_name=raw.get("course_folder_name", "fullname"),
        include_courses=list(raw.get("include_courses", [])),
        exclude_courses=list(raw.get("exclude_courses", [])),
        program=str(raw.get("program", "")).strip(),
        group=str(raw.get("group", "")).strip(),
        other_groups=str(raw.get("other_groups", "skip")).strip().lower(),
        other_program_pattern=str(raw.get("other_program_pattern", "")),
        my_groups=[str(g) for g in raw.get("my_groups", [])],
        only_categories=[str(x) for x in raw.get("only_categories", [])],
        download_max_mb=float(raw.get("download_max_mb", 200)),
        skip_extensions=[e.lower() for e in raw.get("skip_extensions", [])],
        lookahead_days=int(raw.get("lookahead_days", 150)),
        notify=bool(raw.get("notify", True)),
        login_popup=bool(raw.get("login_popup", True)),
        schedule_times=list(sched.get("times", ["07:30", "19:30"])),
        ics=bool(cal.get("ics", True)),
        include_text_dates=bool(cal.get("include_text_dates", True)),
        reminders_minutes=[int(x) for x in cal.get("reminders_minutes", [1440, 120])][:5],
        google=bool(cal.get("google", False)),
        google_credentials=_path(cal.get("google_credentials") or str(APP_HOME / "credentials.json")),
        google_calendar_name=cal.get("google_calendar_name", "RTU estudijas"),
        categories=dict(raw["categories"]),
        email=str(raw.get("email", "")).strip(),
        drive_enabled=bool(drive.get("enabled", False)),
        drive_folder=_path(drive["folder"]) if drive.get("folder") else None,
        drive_categories=[str(x) for x in drive.get("categories", ["Mājas darbi"])],
        drive_include_digest=bool(drive.get("include_digest", True)),
        drive_link=str(drive.get("link", "")).strip(),
    )
    if created:
        print(f"Izveidots konfigurācijas fails: {path}")
    return cfg


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, Path):
        v = str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


_VALUE = r'("(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'|\[[^\]\n]*\]|[^#\s]+)'


def set_toml_values(path: Path, values: dict[tuple[str | None, str], object]) -> None:
    """Ieraksta vērtības config.toml ({(sadaļa|None, atslēga): vērtība}), saglabājot komentārus."""
    lines = path.read_text(encoding="utf-8").split("\n")
    for (section, key), val in values.items():
        new_val = toml_value(val)
        # sadaļas robežas
        start, end = 0, len(lines)
        if section:
            hdr = next((i for i, ln in enumerate(lines) if ln.strip() == f"[{section}]"), None)
            if hdr is None:
                lines += ["", f"[{section}]"]
                hdr = len(lines) - 1
            start = hdr + 1
            end = next((i for i in range(start, len(lines)) if lines[i].lstrip().startswith("[")
                        and not lines[i].lstrip().startswith("[[") and "=" not in lines[i]), len(lines))
        else:
            end = next((i for i, ln in enumerate(lines) if re.match(r"^\s*\[[^\]]+\]\s*$", ln)), len(lines))
        rx = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*){_VALUE}(.*)$")
        for i in range(start, end):
            m = rx.match(lines[i])
            if m:
                lines[i] = m.group(1) + new_val + m.group(3)
                break
        else:
            ins = end
            while ins > start and not lines[ins - 1].strip():
                ins -= 1
            lines.insert(ins, f"{key} = {new_val}")
    path.write_text("\n".join(lines), encoding="utf-8")


def set_config_values(path: Path, values: dict[str, str]) -> None:
    set_toml_values(path, {(None, k): v for k, v in values.items()})


# ---- pieteikšanās dati ----

def auth_path(cfg: Config) -> Path:
    return cfg.data_dir / "auth.json"


def load_auth(cfg: Config) -> dict | None:
    p = auth_path(cfg)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_auth(cfg: Config, data: dict) -> None:
    p = auth_path(cfg)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


# ---- stāvoklis starp palaišanām ----

class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data: dict = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    @property
    def files(self) -> dict:
        return self.data.setdefault("files", {})

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
