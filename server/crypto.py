"""Žetonu šifrēšana DB. Atslēga ir tikai vides mainīgajā ENCRYPTION_KEY — nozagta DB bez tās ir nelietojama.

Jaunu atslēgu ģenerē: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Vairākas atslēgas (rotācijai) atdala ar komatu; pirmā tiek lietota šifrēšanai.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .settings import settings

_f: MultiFernet | None = None


def _fernet() -> MultiFernet:
    global _f
    if _f is None:
        keys = [k.strip() for k in settings.encryption_key.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("ENCRYPTION_KEY nav iestatīts")
        _f = MultiFernet([Fernet(k) for k in keys])
    return _f


def encrypt(text: str | None) -> str | None:
    if not text:
        return None
    return _fernet().encrypt(text.encode()).decode()


def decrypt(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken:
        return None
