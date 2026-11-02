"""Pieteikšanās caur Microsoft (RTU konts) atvērtā pārlūkā.

1. Atver Chromium ar šī profila pārlūka datiem, lietotājs pats ielogojas (arī MFA).
2. Mēģina iegūt Moodle mobilās lietotnes žetonu (tas pats, ko izmanto oficiālā Moodle
   lietotne). Ar žetonu sinhronizācija iet caur oficiālo API, bez pārlūka, ~3 mēnešus.
3. Ja žetonu dabūt neizdodas, paliek "web" režīms: sinhronizācija izmanto saglabāto
   pārlūka sesiju (headless) un nolasa lapas.

Parole nekur netiek glabāta.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import re
import time
from datetime import datetime

from .config import Config, save_auth
from .model import LoginRequired, MoodleError

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SESSKEY_JS = "() => (window.M && M.cfg && M.cfg.sesskey) || null"


def browser_dir(cfg: Config):
    d = cfg.data_dir / "browser"
    d.mkdir(parents=True, exist_ok=True)
    return d


def launch_context(pw, cfg: Config, headless: bool):
    return pw.chromium.launch_persistent_context(
        str(browser_dir(cfg)), headless=headless, user_agent=UA, locale="lv-LV",
        viewport={"width": 1280, "height": 900}, accept_downloads=True)


# ---- sīkdatņu saglabāšana ----
# Chromium pēc aizvēršanas aizmirst "sesijas" sīkdatnes (arī Moodle sesiju), tāpēc katra
# sinhronizācija prasītu Microsoft pieteikšanos ar MFA no jauna. Saglabājam tās paši.

def cookies_path(cfg: Config):
    return cfg.data_dir / "cookies.json"


def save_cookies(ctx, cfg: Config) -> None:
    try:
        cookies = [c for c in ctx.cookies()
                   if any(d in c.get("domain", "") for d in ("rtu.lv", "microsoftonline.com", "microsoft.com", "live.com"))]
        p = cookies_path(cfg)
        p.write_text(json.dumps(cookies), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    except Exception as e:
        log.info("Sīkdatnes nesaglabājās: %s", e)


def restore_cookies(ctx, cfg: Config) -> None:
    p = cookies_path(cfg)
    if not p.exists():
        return
    try:
        now = time.time()
        cookies = [c for c in json.loads(p.read_text(encoding="utf-8"))
                   if c.get("expires", -1) in (-1, None) or c["expires"] > now]
        if cookies:
            ctx.add_cookies(cookies)
    except Exception as e:
        log.info("Sīkdatnes neatjaunojās: %s", e)


def prefill_email(page, email: str) -> None:
    """Ieraksta e-pastu Microsoft logā (paroli un MFA lietotājs ievada pats)."""
    if not email:
        return
    try:
        page.wait_for_selector("input[type=email]", timeout=15000)
        if not page.input_value("input[type=email]"):
            page.fill("input[type=email]", email)
            page.keyboard.press("Enter")
    except Exception:
        pass


def _accept_stay_signed_in(page) -> None:
    """Microsoft "Stay signed in?" → Yes, lai nākamreiz MFA nebūtu jāapstiprina tik bieži."""
    try:
        if "login.microsoftonline.com" in page.url and page.query_selector("#KmsiCheckboxField, #KmsiDescription"):
            page.click("#idSIButton9", timeout=2000)
    except Exception:
        pass


def login_window(pw, cfg: Config, timeout_s: int = 600, prog=None):
    """Atver REDZAMU pārlūka logu, lai var ievadīt paroli un redzēt/apstiprināt MFA kodu.
    Atgriež (ctx, page, sesskey) — ctx paliek atvērts; vai izmet LoginRequired."""
    try:
        ctx = launch_context(pw, cfg, headless=False)
    except Exception as e:
        raise LoginRequired(f"Nevar atvērt pārlūka logu pieteikšanās veikšanai ({e}). "
                            "Palaid sinhronizāciju pats vai paneļa pogu 'Pieteikties'.") from e
    restore_cookies(ctx, cfg)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.bring_to_front()
    except Exception:
        pass
    msg = ("Atvērts pārlūka logs: piesakies ar RTU kontu. Ja Microsoft rāda skaitli, ievadi to "
           "Authenticator lietotnē telefonā.")
    print("\n➡  " + msg + f" Gaidu līdz {timeout_s // 60} min…")
    if prog:
        prog.note(msg)
    page.goto(cfg.site + "/my/")
    prefill_email(page, cfg.email)
    sesskey = wait_logged_in(page, cfg.site, timeout_s)
    if not sesskey:
        ctx.close()
        raise LoginRequired(f"Pieteikšanās netika pabeigta {timeout_s // 60} minūšu laikā.")
    save_cookies(ctx, cfg)
    print("✔  Pieteikšanās estudijās izdevās.")
    return ctx, page, sesskey


def is_site_page(url: str, site: str) -> bool:
    return url.startswith(site) and "/login/" not in url and "/auth/" not in url


def safe_sesskey(page) -> str | None:
    try:
        return page.evaluate(SESSKEY_JS)
    except Exception:
        return None


def wait_logged_in(page, site: str, timeout_s: int) -> str | None:
    end = time.time() + timeout_s
    while time.time() < end:
        _accept_stay_signed_in(page)
        if is_site_page(page.url, site):
            sk = safe_sesskey(page)
            if sk:
                return sk
        page.wait_for_timeout(1000)
    return None


def decode_launch_token(text: str, site: str, passport: str) -> tuple[str, str | None]:
    """No `moodlemobile://token=BASE64` izvelk žetonu. BASE64 = sig:::token[:::privatetoken]."""
    m = re.search(r"[a-z][a-z0-9+.\-]*://token=([A-Za-z0-9+/=_\-]+)", text)
    if not m:
        raise MoodleError("Atbildē nav žetona")
    b64 = m.group(1)
    b64 += "=" * (-len(b64) % 4)
    try:
        decoded = base64.b64decode(b64).decode()
    except Exception:
        decoded = base64.urlsafe_b64decode(b64).decode()
    parts = decoded.split(":::")
    if len(parts) < 2:
        raise MoodleError("Nesaprotams žetona formāts")
    sig = parts[0]
    if sig != hashlib.md5((site + passport).encode()).hexdigest():
        log.info("Žetona paraksts nesakrīt ar gaidīto (tas nav kritiski)")
    return parts[1], (parts[2] if len(parts) > 2 else None)


def try_get_token(ctx, site: str) -> tuple[str, str | None]:
    passport = str(random.randint(10**8, 10**9 - 1))
    url = (f"{site}/admin/tool/mobile/launch.php?service=moodle_mobile_app"
           f"&passport={passport}&urlscheme=moodlemobile")
    r = ctx.request.get(url, max_redirects=0, timeout=60000)
    loc = r.headers.get("location", "") or ""
    if "token=" in loc:
        return decode_launch_token(loc, site, passport)
    body = ""
    try:
        body = r.text()
    except Exception:
        pass
    if "token=" in body:
        return decode_launch_token(body, site, passport)
    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:300]
    raise MoodleError(f"Mobilās lietotnes žetonu neizdevās iegūt (HTTP {r.status}, "
                      f"redirect='{loc[:120]}'). {snippet}")


def interactive_login(cfg: Config, force_web: bool = False, prog=None) -> dict:
    from playwright.sync_api import sync_playwright

    from .moodle_api import MoodleAPI

    site = cfg.site
    with sync_playwright() as pw:
        ctx, page, _sk = login_window(pw, cfg, 600, prog)
        try:
            auth = {"mode": "web", "obtained": datetime.now().isoformat(timespec="seconds")}
            if not force_web:
                try:
                    token, private = try_get_token(ctx, site)
                    info = MoodleAPI(site, token).call("core_webservice_get_site_info")
                    auth.update(mode="api", token=token, privatetoken=private,
                                userid=info.get("userid"), fullname=info.get("fullname"))
                    print(f"✔  API piekļuve iegūta ({info.get('fullname')}). Pārlūks turpmāk nav vajadzīgs.")
                except Exception as e:
                    log.warning("API žetons nav pieejams: %s", e)
                    print(f"ℹ  API žetonu iegūt neizdevās ({e}).\n"
                          "   Izmantošu pārlūka režīmu (saglabātā sesija). Tas strādā, bet ik pa laikam\n"
                          "   var nākties pieteikties no jauna.")
            save_auth(cfg, auth)
            return auth
        finally:
            ctx.close()
