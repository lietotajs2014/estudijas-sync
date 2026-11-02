"""Google OAuth 2.0 (web server flow).

- Pieteikšanās: scope `openid email profile` — tikai identitāte, refresh token netiek glabāts.
- Google pieslēgšana (pēc RTU pieteikšanās, pēc izvēles): `drive.file` — app redz tikai pašas izveidotos failus;
  `calendar.app.created` — app var veidot savu kalendāru "RTU estudijas" un mainīt tikai to (citus kalendārus neredz).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .settings import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LOGIN_SCOPES = "openid email profile"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"


def redirect_uri() -> str:
    return f"{settings.base_url}/auth/google/callback"


def start(session: dict, purpose: str) -> str:
    """Atgriež Google saiti. state + PKCE glabājas parakstītajā sesijas sīkdatnē."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    session["oauth"] = {"state": state, "verifier": verifier, "purpose": purpose}
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if purpose in ("drive", "google"):
        params.update(scope=f"{LOGIN_SCOPES} {DRIVE_SCOPE} {CALENDAR_SCOPE}", access_type="offline", prompt="consent",
                      include_granted_scopes="true")
    else:
        params.update(scope=LOGIN_SCOPES, prompt="select_account")
    return f"{AUTH_URL}?{urlencode(params)}"


class OAuthError(Exception):
    pass


def finish(session: dict, state: str, code: str) -> tuple[str, dict, dict]:
    """Atgriež (purpose, identitāte, tokenu atbilde)."""
    saved = session.pop("oauth", None) or {}
    if not saved or not state or not secrets.compare_digest(saved.get("state", ""), state):
        raise OAuthError("Nederīgs vai novecojis pieteikšanās pieprasījums. Mēģini vēlreiz.")
    r = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
        "code_verifier": saved["verifier"],
    }, timeout=20)
    if r.status_code != 200:
        raise OAuthError(f"Google atteica ({r.status_code}).")
    tokens = r.json()
    try:
        ident = id_token.verify_oauth2_token(tokens["id_token"], google_requests.Request(), settings.google_client_id)
    except Exception as e:
        raise OAuthError(f"Google identitāti neizdevās pārbaudīt: {e}") from e
    if not ident.get("email_verified"):
        raise OAuthError("Google kontam nav apstiprināta e-pasta adrese.")
    return saved.get("purpose", "login"), ident, tokens
