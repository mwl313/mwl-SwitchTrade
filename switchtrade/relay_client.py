"""Small HTTP client for private SwitchTrade relay sessions."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class RelayError(RuntimeError):
    pass


class RelayClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        parts = urlsplit(base_url.strip())
        if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
            raise ValueError("relay URL must use http(s) or ws(s)")
        scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
        self.base_url = urlunsplit((scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        self.timeout = timeout

    def _request(self, method: str, path: str) -> dict:
        try:
            with urlopen(Request(f"{self.base_url}{path}", method=method),
                         timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                detail = json.loads(error.read())["detail"]
            except Exception:
                detail = error.reason
            raise RelayError(f"relay returned {error.code}: {detail}") from error
        except (URLError, OSError, ValueError) as error:
            raise RelayError(f"relay unavailable: {error}") from error

    def create_session(self) -> str:
        return self._request("POST", "/session/create")["session_id"]

    def status(self, session_id: str) -> dict:
        return self._request("GET", f"/session/{session_id}")
