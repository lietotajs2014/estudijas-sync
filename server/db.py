"""Datubāze (SQLAlchemy ORM — visi vaicājumi parametrizēti, nekāda SQL teksta salīmēšana).

Produkcijā PostgreSQL (docker-compose), lokāli izstrādei SQLite.
Žetoni glabājas tikai šifrēti (crypto.py).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .settings import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # slepens kalendāra (ICS) saites identifikators; mainot to, vecā saite pārstāj strādāt
    ics_secret: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(32))

    # kas tu esi (no e-studijām, lietotājs apstiprina)
    program: Mapped[str] = mapped_column(String(20), default="")
    group: Mapped[str] = mapped_column(String(10), default="")
    extra_groups: Mapped[list] = mapped_column(JSON, default=list)   # citas grupas, kuras arī rādīt
    exclude_courses: Mapped[list] = mapped_column(JSON, default=list)

    # Google Drive
    drive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    drive_categories: Mapped[list] = mapped_column(JSON, default=lambda: ["Mājas darbi"])

    # sinhronizācijas stāvoklis
    sync_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    moodle: Mapped["MoodleLink | None"] = relationship(back_populates="user", uselist=False,
                                                         cascade="all, delete-orphan")
    google: Mapped["GoogleLink | None"] = relationship(back_populates="user", uselist=False,
                                                         cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.email.lower() in settings.admin_emails


class MoodleLink(Base):
    """E-studiju (Moodle mobilās lietotnes) žetons. Parole netiek glabāta nekad."""
    __tablename__ = "moodle_links"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    token_enc: Mapped[str] = mapped_column(Text)
    privatetoken_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    moodle_userid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fullname: Mapped[str] = mapped_column(String(200), default="")
    detected: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ko atradām (programma, grupa, kursi)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    linked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="moodle")


class GoogleLink(Base):
    """Google refresh token Drive piekļuvei (scope drive.file — tikai app pašas izveidotie faili)."""
    __tablename__ = "google_links"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, default="")
    linked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="google")


engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        from pathlib import Path
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
