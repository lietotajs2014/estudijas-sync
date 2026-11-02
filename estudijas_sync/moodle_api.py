"""Minimāls Moodle Web Services REST klients."""
from __future__ import annotations

from typing import Any, Iterator

import requests

from .model import LoginRequired, MoodleError

INVALID_TOKEN_CODES = {"invalidtoken", "invalidtimedtoken", "expiredtoken"}


def flatten(params: dict, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """{'courseids': [1,2], 'options': {'x': 1}} -> courseids[0]=1, courseids[1]=2, options[x]=1"""
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            yield from flatten(v, key)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, dict):
                    yield from flatten(x, f"{key}[{i}]")
                else:
                    yield f"{key}[{i}]", int(x) if isinstance(x, bool) else x
        elif isinstance(v, bool):
            yield key, int(v)
        elif v is not None:
            yield key, v


class MoodleAPI:
    def __init__(self, site: str, token: str):
        self.site = site.rstrip("/")
        self.token = token
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "MoodleMobile estudijas-sync"

    def call(self, function: str, **params) -> Any:
        data = list(flatten(params))
        data += [("wstoken", self.token), ("wsfunction", function), ("moodlewsrestformat", "json")]
        r = self.s.post(f"{self.site}/webservice/rest/server.php", data=data, timeout=90)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict) and "exception" in j:
            code = j.get("errorcode")
            if code in INVALID_TOKEN_CODES:
                raise LoginRequired(f"API žetons vairs nav derīgs ({code}).")
            raise MoodleError(f"{function}: {j.get('message')}", code)
        return j

    def file_url(self, url: str) -> str:
        if "/webservice/pluginfile.php" not in url and "/pluginfile.php" in url:
            url = url.replace("/pluginfile.php", "/webservice/pluginfile.php", 1)
        return f"{url}{'&' if '?' in url else '?'}token={self.token}"

    def get_file(self, url: str, stream: bool = False) -> requests.Response:
        r = self.s.get(self.file_url(url), stream=stream, timeout=180)
        r.raise_for_status()
        if "application/json" in r.headers.get("content-type", ""):
            try:
                j = r.json()
            except ValueError:
                j = {}
            if j.get("errorcode") in INVALID_TOKEN_CODES:
                raise LoginRequired("API žetons vairs nav derīgs.")
            raise MoodleError(f"Fails nav pieejams: {j.get('message') or r.text[:200]}", j.get("errorcode"))
        return r
