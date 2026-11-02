"""Augšupielāde lietotāja Google Drive caur API (scope drive.file).

Drive mapē "RTU estudijas" tiek atspoguļota tā pati struktūra kā darbvirsmas versijā
(<kurss>/<kategorija>/...). Tiek augšupielādētas tikai izvēlētās kategorijas (noklusējumā Mājas darbi).
Kas jau augšupielādēts, glabājas <lietotāja mape>/.estudijas-sync/drive_index.json.
"""
from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path

from estudijas_sync.config import State
from estudijas_sync.drive import file_category

from .crypto import decrypt
from .google_oauth import CALENDAR_SCOPE, DRIVE_SCOPE, TOKEN_URL
from .settings import settings

log = logging.getLogger(__name__)
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_NAME = "RTU estudijas"


def _service(user, api: str = "drive"):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    refresh = decrypt(user.google.refresh_token_enc) if user.google else None
    if not refresh:
        raise RuntimeError("Google nav pieslēgts (vai piekļuve atsaukta).")
    scope = DRIVE_SCOPE if api == "drive" else CALENDAR_SCOPE
    creds = Credentials(None, refresh_token=refresh, token_uri=TOKEN_URL, client_id=settings.google_client_id,
                        client_secret=settings.google_client_secret, scopes=[scope])
    return build(*(("drive", "v3") if api == "drive" else ("calendar", "v3")), credentials=creds, cache_discovery=False)


def has_scope(user, scope: str) -> bool:
    return bool(user.google and scope in (user.google.scopes or ""))


def folder_url(cfg) -> str:
    try:
        fid = json.loads((cfg.data_dir / "drive_index.json").read_text(encoding="utf-8"))["folders"][""]
        return f"https://drive.google.com/drive/folders/{fid}"
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def calendar_sync(user, cfg, view: dict) -> int:
    """Termiņi tavā Google kalendārā "RTU estudijas" (tas pats kods, ko izmanto darbvirsmas versija)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from estudijas_sync import gcal

    svc = _service(user, "calendar")
    state = State(cfg.data_dir / "state.json")
    dls, courses = gcal.deadlines_from_view(view, cfg.include_text_dates)
    n = gcal.sync(cfg, state, dls, courses, datetime.now(ZoneInfo(cfg.timezone)), svc=svc)
    state.save()
    return n


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class _Folders:
    def __init__(self, svc, index: dict):
        self.svc, self.index = svc, index.setdefault("folders", {})

    def _exists(self, fid: str) -> bool:
        try:
            f = self.svc.files().get(fileId=fid, fields="id,trashed").execute()
            return not f.get("trashed")
        except Exception:
            return False

    def get(self, rel: str) -> str:
        """rel = "" (sakne) vai "Kurss/Mājas darbi"; izveido trūkstošās mapes."""
        if rel in self.index and self._exists(self.index[rel]):
            return self.index[rel]
        if rel == "":
            parent, name = "root", ROOT_NAME
        else:
            head, _, name = rel.rpartition("/")
            parent = self.get(head)
        q = (f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and '{parent}' in parents and trashed = false")
        found = self.svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        fid = found[0]["id"] if found else self.svc.files().create(
            body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]}, fields="id").execute()["id"]
        self.index[rel] = fid
        return fid


def mirror(user, cfg) -> int:
    from googleapiclient.http import MediaFileUpload

    svc = _service(user)
    idx_path = cfg.data_dir / "drive_index.json"
    try:
        index = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        index = {}
    files = index.setdefault("files", {})
    folders = _Folders(svc, index)
    cats = {c.casefold() for c in (user.drive_categories or [])}
    state = State(cfg.data_dir / "state.json")
    uploaded = 0
    try:
        # mape "RTU estudijas" un kursu apakšmapes — arī, ja vēl nekas nav ielādēts
        folders.get("")
        for d in sorted(cfg.output_dir.iterdir()) if cfg.output_dir.exists() else []:
            if d.is_dir() and not d.name.startswith("."):
                folders.get(d.name)
        for entry in state.files.values():
            rel = entry.get("path")
            # pašu atzīmētie (web lapā "Ielādēt atzīmētos") — vienmēr; pārējie pēc kategorijām
            if not rel or (cats and not entry.get("manual") and file_category(rel).casefold() not in cats):
                continue
            src: Path = cfg.output_dir / rel
            if not src.is_file():
                continue
            sig = f"{src.stat().st_size}:{int(src.stat().st_mtime)}"
            known = files.get(rel)
            if known and known.get("sig") == sig:
                continue
            mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
            media = MediaFileUpload(str(src), mimetype=mime, resumable=src.stat().st_size > 5 * 2**20)
            if known and known.get("id"):
                try:
                    svc.files().update(fileId=known["id"], media_body=media).execute()
                    files[rel] = {"id": known["id"], "sig": sig}
                    uploaded += 1
                    continue
                except Exception:
                    pass  # izdzēsts Drive pusē — augšupielādē no jauna
            head, _, name = rel.rpartition("/")
            fid = svc.files().create(body={"name": name, "parents": [folders.get(head)]},
                                     media_body=media, fields="id").execute()["id"]
            files[rel] = {"id": fid, "sig": sig}
            uploaded += 1
    finally:
        idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return uploaded
