"""Servera iestatījumi no vides mainīgajiem (.env). Nekas slepens netiek glabāts kodā."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.environ.get(name, "").replace(";", ",").split(",") if x.strip()]


@dataclass
class Settings:
    base_url: str = field(default_factory=lambda: os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"))
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))
    encryption_key: str = field(default_factory=lambda: os.environ.get("ENCRYPTION_KEY", ""))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./data/dev.db"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "./data")))
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    # Kas drīkst pieteikties. Tukšs = neviens (drošs noklusējums). "*" = jebkurš Google konts.
    allowed_emails: list[str] = field(default_factory=lambda: _list("ALLOWED_EMAILS"))
    admin_emails: list[str] = field(default_factory=lambda: _list("ADMIN_EMAILS"))
    moodle_site: str = field(default_factory=lambda: os.environ.get("MOODLE_SITE", "https://estudijas.rtu.lv").rstrip("/"))
    timezone: str = field(default_factory=lambda: os.environ.get("TZ", "Europe/Riga"))
    schedule_times: list[str] = field(default_factory=lambda: _list("SCHEDULE_TIMES") or ["07:30", "19:30"])
    # Debug pieteikšanās (tikai ADMIN_EMAILS): neko neievada pats, visu dari tu.
    #   lokāli (BASE_URL = localhost) → atver REDZAMU pārlūka logu (der arī Windows passkey);
    #   serverī (dev.lodelo.de)       → lapā rāda servera pārlūka ekrānu, uz kura klikšķini un raksti.
    # Oficiālajā lapā (main) LOGIN_DEBUG neiestata.
    login_debug: bool = field(default_factory=lambda: os.environ.get("LOGIN_DEBUG", "").strip().lower() in ("1", "true", "yes"))
    # "msedge" vai "chrome" = uzstādītais pārlūks (tikai tas var lietot Windows Hello passkey); tukšs = Playwright Chromium
    login_browser_channel: str = field(default_factory=lambda: os.environ.get("LOGIN_BROWSER_CHANNEL", "").strip())

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def is_local(self) -> bool:
        from urllib.parse import urlparse

        return (urlparse(self.base_url).hostname or "") in ("localhost", "127.0.0.1", "::1")

    def manual_login_allowed(self, email: str) -> bool:
        """Debug pieteikšanās: tikai ieslēgts LOGIN_DEBUG un admins."""
        return self.login_debug and (email or "").lower() in self.admin_emails

    def email_allowed(self, email: str) -> bool:
        email = (email or "").lower()
        return "*" in self.allowed_emails or email in self.allowed_emails or email in self.admin_emails

    def check(self) -> list[str]:
        """Ko vēl vajag iestatīt (rāda sākumlapā, nevis krīt ar kļūdu)."""
        missing = []
        if len(self.secret_key) < 32:
            missing.append("SECRET_KEY (vismaz 32 simboli)")
        if not self.encryption_key:
            missing.append("ENCRYPTION_KEY")
        if not (self.google_client_id and self.google_client_secret):
            missing.append("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET")
        if not (self.allowed_emails or self.admin_emails):
            missing.append("ALLOWED_EMAILS")
        return missing


settings = Settings()
