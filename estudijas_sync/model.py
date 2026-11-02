"""Kopīgie datu tipi, ko izmanto abi avoti (API un pārlūka režīms)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class LoginRequired(Exception):
    """Sesija/žetons vairs nav derīgs — jāpalaiž `login` no jauna."""


class MoodleError(Exception):
    def __init__(self, message: str, errorcode: str | None = None):
        super().__init__(message)
        self.errorcode = errorcode


@dataclass
class Course:
    id: int
    shortname: str
    fullname: str
    url: str

    @property
    def label(self) -> str:
        s = (self.shortname or "").strip()
        if s and len(s) <= 18:
            return s
        f = (self.fullname or s).strip()
        return f if len(f) <= 28 else f[:27] + "…"


@dataclass
class FileItem:
    course_id: int
    section: str
    section_num: int
    module: str          # moduļa (aktivitātes) nosaukums
    modtype: str         # resource | folder | assign | ...
    filename: str
    url: str
    version: str         # timemodified vai faila URL ar revīziju — ja mainās, fails atjaunināts
    cmid: int | str = 0
    subpath: str = ""    # apakšmapes ceļš "folder" moduļos
    size: int | None = None
    page_url: str = ""
    kind_hint: str = ""  # piem. uzdevuma veids (MD/KD) pielikumiem
    modified: int | None = None  # Moodle timemodified (ja zināms)

    @property
    def key(self) -> str:
        return f"{self.course_id}:{self.modtype}:{self.cmid}:{self.subpath}/{self.filename}"


@dataclass
class Deadline:
    uid: str
    course_id: int
    kind: str            # MD | KD | Tests | LD | PD | Eksāmens | Uzdevums | Notikums | Termiņš
    title: str
    due: datetime        # vienmēr ar laika joslu
    start: datetime | None = None
    url: str = ""
    status: str | None = None
    source: str = "moodle"   # moodle | teksts
    details: str = ""
    relevance: str | None = None
    section: str = ""

    @property
    def done(self) -> bool:
        s = (self.status or "").lower()
        return s.startswith("iesniegts") or s.startswith("izpildīts") or s.startswith("novērtēts")


@dataclass
class TextBlock:
    course_id: int
    title: str
    text: str
    url: str = ""
    kind: str = "teksts"     # sadaļa | lapa | paziņojums | uzdevums | teksts
    date: datetime | None = None


@dataclass
class Link:
    course_id: int
    section: str
    name: str
    url: str


@dataclass
class CollectResult:
    files: list[FileItem] = field(default_factory=list)
    deadlines: dict[str, Deadline] = field(default_factory=dict)
    texts: list[TextBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    groups: dict[int, list[str]] = field(default_factory=dict)
    teachers: dict[int, list[dict]] = field(default_factory=dict)  # {kurss: [{name, email, url, role}]}
    warnings: list[str] = field(default_factory=list)

    def add_deadline(self, d: Deadline) -> None:
        old = self.deadlines.get(d.uid)
        if old is None:
            self.deadlines[d.uid] = d
            return
        # Papildina trūkstošos laukus, nepārraksta jau zināmo
        for attr in ("start", "url", "status", "details"):
            if not getattr(old, attr) and getattr(d, attr):
                setattr(old, attr, getattr(d, attr))
