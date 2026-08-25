"""Small HTTP client for private SwitchTrade relay sessions."""

from __future__ import annotations

import json
import secrets
import time
import uuid
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

    def _request(self, method: str, path: str, payload: dict | None = None,
                 headers: dict[str, str] | None = None) -> dict:
        request_headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(f"{self.base_url}{path}", method=method, data=data,
                                 headers=request_headers),
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

    def shutdown(self) -> dict:
        return self._request("POST", "/shutdown")

    @staticmethod
    def command_id() -> str:
        millis = int(time.time() * 1000) & ((1 << 48) - 1)
        value = millis << 80 | 0x7 << 76 | secrets.randbits(12) << 64
        value |= 0b10 << 62 | secrets.randbits(62)
        return str(uuid.UUID(int=value))

    @staticmethod
    def _auth(token: str, command_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}"}
        if command_id:
            headers["Idempotency-Key"] = command_id
        return headers

    def create_trade_room(self, payload: dict, client_id: str, command_id: str | None = None) -> dict:
        return self._request("POST", "/v1/trade-rooms", payload, {
            "Idempotency-Key": command_id or self.command_id(),
            "X-SwitchTrade-Client": client_id,
        })

    def join_trade_room(self, room_code: str, display_name: str, client_id: str,
                        command_id: str | None = None) -> dict:
        return self._request("POST", "/v1/trade-rooms:join", {
            "room_code": room_code, "trainer_display_name": display_name,
        }, {
            "Idempotency-Key": command_id or self.command_id(),
            "X-SwitchTrade-Client": client_id,
        })

    def room(self, room_id: str, token: str) -> dict:
        return self._request("GET", f"/v1/trade-rooms/{room_id}", headers=self._auth(token))

    def room_events(self, room_id: str, token: str, after: int = 0) -> dict:
        return self._request("GET", f"/v1/trade-rooms/{room_id}/events?after={max(0, after)}",
                             headers=self._auth(token))

    def room_command(self, room_id: str, token: str, path: str,
                     payload: dict | None = None, command_id: str | None = None,
                     method: str = "POST") -> dict:
        return self._request(method, f"/v1/trade-rooms/{room_id}{path}", payload,
                             self._auth(token, command_id or self.command_id()))
