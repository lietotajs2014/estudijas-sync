"""Savieno šo PC programmu ar web lapu (estudijas.lodelo.de): nosūta e-studiju sesiju uz serveri.

Lapā spied "Izveidot savienošanas kodu", tad:  python run.py pair 123456
Tiek sūtītas tikai estudijas.rtu.lv un Microsoft pieteikšanās sīkdatnes (parole netiek glabāta nekur).
"""
from __future__ import annotations

import json
import re

import requests

from .auth import cookies_path
from .config import Config

DEFAULT_SERVER = "https://estudijas.lodelo.de"
DOMAINS = ("rtu.lv", "microsoftonline.com", "microsoft.com", "live.com")


class PairError(Exception):
    pass


def load_session_cookies(cfg: Config) -> list[dict]:
    p = cookies_path(cfg)
    try:
        cookies = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cookies = []
    cookies = [c for c in cookies if any(d in c.get("domain", "") for d in DOMAINS)]
    if not any(c.get("name", "").startswith("MoodleSession") for c in cookies):
        raise PairError("Nav saglabātas e-studiju sesijas. Vispirms piesakies: python run.py login --web "
                        "(vai paneļa poga 'Pieteikties').")
    return cookies


def pair(cfg: Config, code: str, server: str = DEFAULT_SERVER) -> dict:
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        raise PairError("Kodam jābūt 6 cipariem (to redzi web lapā).")
    server = (server or DEFAULT_SERVER).rstrip("/")
    if not server.startswith("https://"):
        raise PairError("Servera adresei jāsākas ar https://")
    cookies = load_session_cookies(cfg)
    try:
        r = requests.post(f"{server}/api/pair", json={"code": code, "source": "pc", "cookies": cookies}, timeout=60)
    except requests.RequestException as e:
        raise PairError(f"Neizdevās sazināties ar {server}: {e}") from e
    try:
        j = r.json()
    except ValueError:
        raise PairError(f"Serveris atbildēja ar kļūdu (HTTP {r.status_code}).")
    if not j.get("ok"):
        raise PairError(j.get("error") or f"HTTP {r.status_code}")
    return j
