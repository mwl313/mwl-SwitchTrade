"""Small HTTP client for private SwitchTrade relay sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from switchtrade import __version__


USER_AGENT = f"SwitchTrade/{__version__}"


class RelayError(RuntimeError):
    def __init__(self, message: str, *, status: int = 503, code: str = "relay_unavailable",
                 stage: str = "relay", recoverable: bool = True,
                 primary_action: str | None = "retry", correlation_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.stage = stage
        self.recoverable = recoverable
        self.primary_action = primary_action
        self.correlation_id = correlation_id


class RelayClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        if os.name == "posix":
            options = os.environ.get("RES_OPTIONS", "").split()
            if "single-request-reopen" not in options:
                os.environ["RES_OPTIONS"] = " ".join([*options, "single-request-reopen"])
        parts = urlsplit(base_url.strip())
        if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
            raise ValueError("relay URL must use http(s) or ws(s)")
        scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
        self.base_url = urlunsplit((scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None,
                 headers: dict[str, str] | None = None, *, raw_body: bytes | None = None) -> dict:
        request_headers = {**(headers or {}), "User-Agent": USER_AGENT}
        data = None
        if payload is not None and raw_body is not None:
            raise ValueError("payload and raw_body are mutually exclusive")
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            data = raw_body
        try:
            with urlopen(Request(f"{self.base_url}{path}", method=method, data=data,
                                 headers=request_headers),
                         timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                problem = json.loads(error.read())
                detail = problem.get("message") or problem.get("detail") or error.reason
            except Exception:
                problem = {}
                detail = error.reason
            raise RelayError(
                str(detail), status=error.code,
                code=str(problem.get("code") or f"relay_http_{error.code}"),
                stage=str(problem.get("stage") or "relay"),
                recoverable=bool(problem.get("recoverable", error.code >= 500)),
                primary_action=problem.get("primary_action"),
                correlation_id=problem.get("correlation_id"),
            ) from error
        except (URLError, OSError, ValueError) as error:
            raise RelayError(f"relay unavailable: {error}") from error

    def create_session(self) -> str:
        return self._request("POST", "/session/create")["session_id"]

    def status(self, session_id: str) -> dict:
        return self._request("GET", f"/session/{session_id}")

    def shutdown(self) -> dict:
        return self._request("POST", "/shutdown")

    def health(self) -> dict:
        return self._request("GET", "/health")

    def websocket_health(self) -> bool:
        """Check WebSocket egress without creating relay state."""
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect

        parts = urlsplit(self.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        url = urlunsplit((scheme, parts.netloc, f"{parts.path}/health/ws", "", ""))
        try:
            with connect(url, open_timeout=self.timeout, close_timeout=self.timeout) as socket:
                message = json.loads(socket.recv(timeout=self.timeout))
        except (OSError, TimeoutError, ValueError, WebSocketException) as error:
            raise RelayError(f"relay WebSocket health unavailable: {error}") from error
        return (
            isinstance(message, dict) and message.get("status") == "ready" and
            message.get("contract_version") == "passive-websocket-health.v1"
        )

    def upload_diagnostic(self, kind: str, path: str | Path, client_id: str,
                          release_id: str) -> dict:
        content_types = {
            "support-bundle": "application/zip",
            "hardware-diagnostic": "application/json",
        }
        if kind not in content_types:
            raise ValueError("unsupported diagnostic kind")
        artifact = Path(path)
        if artifact.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("diagnostic artifact exceeds 16 MiB")
        return self._request(
            "POST", f"/v1/diagnostics/{kind}", headers={
                "Content-Type": content_types[kind],
                "X-SwitchTrade-Client": client_id,
                "X-SwitchTrade-Release": release_id,
            }, raw_body=artifact.read_bytes())

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

    def public_trade_rooms(self, *, query: str = "", game: str = "", language: str = "",
                           availability: str = "open", sort: str = "recent",
                           cursor: int = 0, limit: int = 25) -> dict:
        parameters = urlencode({
            "query": query, "game": game, "language": language,
            "availability": availability, "sort": sort,
            "cursor": max(0, cursor), "limit": max(1, min(limit, 50)),
        })
        return self._request("GET", f"/v1/public-trade-rooms?{parameters}")

    def public_trade_room(self, listing_id: str) -> dict:
        return self._request("GET", f"/v1/public-trade-rooms/{quote(listing_id, safe='')}")

    def join_public_trade_room(self, listing_id: str, display_name: str, client_id: str,
                               command_id: str | None = None) -> dict:
        return self._request(
            "POST", f"/v1/public-trade-rooms/{quote(listing_id, safe='')}:join",
            {"trainer_display_name": display_name}, {
                "Idempotency-Key": command_id or self.command_id(),
                "X-SwitchTrade-Client": client_id,
            })

    def room(self, room_id: str, token: str) -> dict:
        return self._request("GET", f"/v1/trade-rooms/{room_id}", headers=self._auth(token))

    def room_events(self, room_id: str, token: str, after: int = 0) -> dict:
        return self._request("GET", f"/v1/trade-rooms/{room_id}/events?after={max(0, after)}",
                             headers=self._auth(token))

    def reconnect_trade_room(self, room_id: str, reconnect_token: str,
                             command_id: str | None = None) -> dict:
        return self._request("POST", f"/v1/trade-rooms/{room_id}:reconnect",
                             {"reconnect_token": reconnect_token}, {
                                 "Idempotency-Key": command_id or self.command_id(),
                             })

    def room_command(self, room_id: str, token: str, path: str,
                     payload: dict | None = None, command_id: str | None = None,
                     method: str = "POST", expected_version: int | None = None) -> dict:
        headers = self._auth(token, command_id or self.command_id())
        if expected_version is not None:
            headers["If-Match"] = str(expected_version)
        return self._request(method, f"/v1/trade-rooms/{room_id}{path}", payload,
                             headers)

    def v2_ready(self, room_id: str, token: str, payload: dict, *,
                 expected_version: int, command_id: str | None = None) -> dict:
        headers = self._auth(token, command_id or self.command_id())
        headers["If-Match"] = str(expected_version)
        return self._request(
            "POST", f"/v2/trade-rooms/{room_id}/ready", payload, headers)

    def begin_distributed_d(self, room_id: str, attempt_id: str, token: str,
                            payload: dict, *, expected_version: int,
                            command_id: str | None = None) -> dict:
        headers = self._auth(token, command_id or self.command_id())
        headers["If-Match"] = str(expected_version)
        return self._request(
            "POST", f"/v2/trade-rooms/{room_id}/attempts/{attempt_id}/closing",
            payload, headers,
        )

    def acknowledge_distributed_d(self, room_id: str, attempt_id: str, token: str,
                                  payload: dict, *, expected_version: int,
                                  command_id: str | None = None) -> dict:
        headers = self._auth(token, command_id or self.command_id())
        headers["If-Match"] = str(expected_version)
        return self._request(
            "POST", f"/v2/trade-rooms/{room_id}/attempts/{attempt_id}/quiescent",
            payload, headers,
        )
