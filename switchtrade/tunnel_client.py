"""Threaded WebSocket client for the feature-neutral RFU tunnel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import queue
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from switchtrade.rfu_tunnel import (
    BROADCAST_PLAYER,
    Direction,
    Envelope,
    Kind,
    SequenceGate,
    direction_for_role,
)


HEARTBEAT_INTERVAL = 10.0
RECONNECT_DELAY = 0.5
RECONNECT_DELAY_MAX = 15.0
STABLE_CONNECTION_SECONDS = 5.0
PERMANENT_HTTP_STATUSES = {400, 401, 403, 404, 409, 426}


def permanent_connect_error(error: Exception) -> bool:
    """Classify handshake failures that retries cannot repair without new state."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status in PERMANENT_HTTP_STATUSES or type(error).__name__ == "InvalidURI"


def relay_websocket_url(base: str, session_id: str, role: str,
                        attempt_id: str | None = None) -> str:
    """Accept an HTTP/WS relay base or a complete session WebSocket URL."""
    direction_for_role(role)  # validate before touching the URL
    parts = urlsplit(base.strip())
    if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
        raise ValueError("relay URL must use http(s) or ws(s)")
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    path = parts.path.rstrip("/")
    marker = f"/session/{session_id}/ws"
    if "/session/" not in path:
        path += marker
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(role=role, protocol="rfu")
    if attempt_id:
        query["attempt_id"] = attempt_id
    return urlunsplit((scheme, parts.netloc, path, urlencode(query), ""))


@dataclass(frozen=True)
class _Pending:
    kind: Kind
    payload: bytes
    flags: int
    source_player: int
    target_player: int


class TunnelClient:
    """Reconnectable RFU WebSocket with bounded cross-thread queues.

    Reconnects start a new epoch and discard unsent frames from the dead link. The
    endpoint must regenerate current state; stale game frames are never replayed.
    """

    def __init__(self, relay_url: str, session_id: str, role: str, *,
                 capacity: int = 256, log=lambda *args: None,
                 heartbeat_interval: float = HEARTBEAT_INTERVAL,
                 member_token: str | None = None, attempt_id: str | None = None):
        self.session_id = session_id
        self.role = role
        self.direction = direction_for_role(role)
        self.url = relay_websocket_url(relay_url, session_id, role, attempt_id)
        self.log = log
        self.heartbeat_interval = heartbeat_interval
        self.member_token = member_token
        self._outbox: queue.Queue[_Pending] = queue.Queue(maxsize=capacity)
        self._inbox: queue.Queue[Envelope] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self.connected = threading.Event()
        self._thread: threading.Thread | None = None
        self._epoch = secrets.randbits(32)
        self.connection_generation = 0
        self._sequence = 0
        self._gate = SequenceGate()
        self.last_error = ""
        self.stats = {
            "sent": 0, "received": 0, "reconnects": 0,
            "stale": 0, "invalid": 0, "dropped": 0,
        }

    def start(self) -> "TunnelClient":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="switchtrade-rfu", daemon=True)
        self._thread.start()
        return self

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self.connected.wait(timeout)

    def send(self, payload: bytes, *, kind: Kind = Kind.RFU, flags: int = 0,
             source_player: int | None = None, target_player: int | None = None,
             timeout: float = 1.0) -> None:
        if not self.connected.is_set():
            raise ConnectionError("RFU tunnel is not connected")
        source = (0 if self.role == "host" else 1) if source_player is None else source_player
        target = (1 if self.role == "host" else 0) if target_player is None else target_player
        self._outbox.put(_Pending(kind, bytes(payload), flags, source, target), timeout=timeout)

    def advertise(self, application_data: bytes) -> None:
        self.send(application_data, kind=Kind.ADVERTISEMENT,
                  source_player=0, target_player=BROADCAST_PLAYER)

    def poll(self, limit: int = 64) -> list[Envelope]:
        frames = []
        for _ in range(limit):
            try:
                frames.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return frames

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.connected.clear()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as error:  # pragma: no cover - final containment
            self.last_error = str(error)
            self.log(f"[tunnel] thread stopped: {error}")
        finally:
            self.connected.clear()

    def _clear_outbox(self) -> None:
        while True:
            try:
                self._outbox.get_nowait()
                self.stats["dropped"] += 1
            except queue.Empty:
                return

    def _clear_inbox(self) -> None:
        while True:
            try:
                self._inbox.get_nowait()
                self.stats["dropped"] += 1
            except queue.Empty:
                return

    def _encode(self, pending: _Pending) -> bytes:
        envelope = Envelope(
            session_id=self.session_id,
            direction=self.direction,
            epoch=self._epoch,
            sequence=self._sequence,
            source_player=pending.source_player,
            target_player=pending.target_player,
            payload=pending.payload,
            kind=pending.kind,
            flags=pending.flags,
        )
        self._sequence += 1
        return envelope.encode()

    async def _main(self) -> None:
        import websockets

        first = True
        reconnect_delay = RECONNECT_DELAY
        while not self._stop.is_set():
            connected_at = None
            try:
                connect_args = {"max_size": (1 << 20) + 256}
                if self.member_token:
                    header_name = ("additional_headers" if "additional_headers" in
                                   inspect.signature(websockets.connect).parameters else "extra_headers")
                    connect_args[header_name] = {"Authorization": f"Bearer {self.member_token}"}
                async with websockets.connect(self.url, **connect_args) as websocket:
                    self._epoch = (self._epoch + 1) & 0xFFFFFFFF
                    self.connection_generation += 1
                    self._sequence = 0
                    self._clear_outbox()
                    self._clear_inbox()
                    self._gate = SequenceGate()
                    if not first:
                        self.stats["reconnects"] += 1
                    first = False
                    connected_at = time.monotonic()
                    self.connected.set()
                    self.last_error = ""
                    self.log(f"[tunnel] connected epoch={self._epoch} role={self.role}")
                    ready = _Pending(Kind.PEER_READY, b"", 0,
                                     0 if self.role == "host" else 1,
                                     BROADCAST_PLAYER)
                    await websocket.send(self._encode(ready))
                    await self._session(websocket)
            except Exception as error:
                self.last_error = str(error)
                self.log(f"[tunnel] disconnected: {error}")
                if permanent_connect_error(error):
                    self.log("[tunnel] permanent relay rejection; retry requires new credentials or configuration")
                    self._stop.set()
            finally:
                self.connected.clear()
            if not self._stop.is_set():
                if connected_at is not None and time.monotonic() - connected_at >= STABLE_CONNECTION_SECONDS:
                    reconnect_delay = RECONNECT_DELAY
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(RECONNECT_DELAY_MAX, reconnect_delay * 2)

    async def _session(self, websocket) -> None:
        last_heartbeat = time.monotonic()
        while not self._stop.is_set():
            for _ in range(32):
                try:
                    pending = self._outbox.get_nowait()
                except queue.Empty:
                    break
                await websocket.send(self._encode(pending))
                self.stats["sent"] += 1

            now = time.monotonic()
            if now - last_heartbeat >= self.heartbeat_interval:
                heartbeat = _Pending(Kind.HEARTBEAT, b"", 0,
                                     0 if self.role == "host" else 1,
                                     BROADCAST_PLAYER)
                await websocket.send(self._encode(heartbeat))
                last_heartbeat = now

            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.005)
            except asyncio.TimeoutError:
                continue
            try:
                envelope = Envelope.decode(raw)
            except (TypeError, ValueError):
                self.stats["invalid"] += 1
                continue
            expected = (Direction.GUEST_TO_HOST if self.role == "host"
                        else Direction.HOST_TO_GUEST)
            if envelope.session_id != self.session_id or envelope.direction != expected:
                self.stats["invalid"] += 1
                continue
            if not self._gate.accept(envelope):
                self.stats["stale"] += 1
                continue
            if envelope.kind == Kind.HEARTBEAT:
                continue
            try:
                self._inbox.put_nowait(envelope)
                self.stats["received"] += 1
            except queue.Full:
                self.stats["dropped"] += 1
                raise RuntimeError("RFU receive queue overflow")
