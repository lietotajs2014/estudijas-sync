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
    schedule_times: list[str] = field(default_factory=lambda: ["07:30", "19:30"])
    ics: bool = True
    include_text_dates: bool = True
    reminders_minutes: list[int] = field(default_factory=lambda: [1440, 120])
    google: bool = False
    google_credentials: Path = APP_HOME / "credentials.json"
    google_calendar_name: str = "RTU estudijas"
    categories: dict[str, str] = field(default_factory=dict)


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
    cfg = Config(
        profile=profile, data_dir=data_dir, config_path=path,
        site=str(raw.get("site", "https://estudijas.rtu.lv")).rstrip("/"),
        output_dir=_path(raw.get("output_dir", "~/Documents/RTU estudijas")),
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
        schedule_times=list(sched.get("times", ["07:30", "19:30"])),
        ics=bool(cal.get("ics", True)),
        include_text_dates=bool(cal.get("include_text_dates", True)),
        reminders_minutes=[int(x) for x in cal.get("reminders_minutes", [1440, 120])][:5],
        google=bool(cal.get("google", False)),
        google_credentials=_path(cal.get("google_credentials", str(APP_HOME / "credentials.json"))),
        google_calendar_name=cal.get("google_calendar_name", "RTU estudijas"),
        categories=dict(raw["categories"]),
    )
    if created:
        print(f"Izveidots konfigurācijas fails: {path}")
    return cfg


def set_config_values(path: Path, values: dict[str, str]) -> None:
    """Ieraksta vienkāršas augšējā līmeņa vērtības config.toml, saglabājot komentārus."""
    text = path.read_text(encoding="utf-8")
    for key, val in values.items():
        val = str(val).replace("\\", "\\\\").replace('"', '\\"')
        line = f'{key} = "{val}"'
        rx = re.compile(rf'^({re.escape(key)}\s*=\s*)("[^"\n]*"|[^\s#]*)', re.M)
        if rx.search(text):
            text = rx.sub(lambda m: m.group(1) + f'"{val}"', text, count=1)
        else:
            text = re.sub(r"^(site\s*=.*)$", lambda m: m.group(1) + "\n" + line, text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


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
