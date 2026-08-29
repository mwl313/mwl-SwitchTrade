"""C0/C1 client for the attempt-scoped rfu-tunnel.v2 relay path."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import queue
import secrets
import threading
from urllib.parse import quote, urlsplit, urlunsplit

from switchtrade.rfu_tunnel_v2 import (
    Envelope,
    Kind,
    MAX_ENVELOPE_BYTES,
    MAX_PAYLOAD_BYTES,
    SequenceGate,
    SourceSeat,
    TunnelV2Error,
    advertisement_hash,
    new_probe,
    verify_advertisement,
    verify_probe,
)
from switchtrade.tunnel_client import permanent_connect_error


@dataclass(frozen=True)
class _Pending:
    kind: Kind
    payload: bytes


def relay_websocket_url(base: str, room_code: str, attempt_id: str) -> str:
    parts = urlsplit(base.strip())
    if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
        raise ValueError("relay URL must use http(s) or ws(s)")
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    root = parts.path.rstrip("/")
    path = (f"{root}/v2/trade-rooms/{quote(room_code, safe='')}"
            f"/attempts/{quote(attempt_id, safe='')}/ws")
    return urlunsplit((scheme, parts.netloc, path, "", ""))


class TunnelClientV2:
    """Authenticate, prove both directions, then deliver one verified advertisement."""

    def __init__(self, relay_url: str, room_code: str, attempt_id: str,
                 source_seat: SourceSeat | str, member_token: str, *,
                 run_id: str, stage_generation: int, launch_nonce: str, endpoint_pid: int,
                 expected_advertisement_hash: str | None = None,
                 capacity: int = 32, log=lambda *args: None):
        if not member_token:
            raise ValueError("member token is required")
        self.room_code = room_code
        self.attempt_id = attempt_id
        self.source_seat = SourceSeat.parse(source_seat)
        self.member_token = member_token
        self.run_id = run_id
        self.stage_generation = stage_generation
        self.launch_nonce = launch_nonce
        self.endpoint_pid = endpoint_pid
        if (stage_generation < 1 or endpoint_pid < 1 or
                not 32 <= len(launch_nonce) <= 128):
            raise ValueError("launch identity is invalid")
        self.url = relay_websocket_url(relay_url, room_code, attempt_id)
        self.expected_advertisement_hash = expected_advertisement_hash
        self.log = log
        self._outbox: queue.Queue[_Pending] = queue.Queue(maxsize=capacity)
        self._inbox: queue.Queue[Envelope] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.authenticated = threading.Event()
        self.peer_ready = threading.Event()
        self.data_plane_proven = threading.Event()
        self.connection_generation = 0
        self.proof_generation = 0
        self.last_error = ""
        self.last_error_type = ""
        self.last_error_code = ""
        self.received_advertisement_hash: str | None = None
        self._advertisement_sent_generation = 0
        self.stats = {
            "sent": 0, "received": 0, "reconnects": 0, "dropped": 0,
            "advertisement_replays": 0,
        }
        self._epoch = 0
        self._sequence = 0

    def start(self) -> "TunnelClientV2":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="switchtrade-rfu-v2", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._clear_readiness()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def wait_authenticated(self, timeout: float = 10.0) -> bool:
        return self.authenticated.wait(timeout)

    def wait_peer_ready(self, timeout: float = 10.0) -> bool:
        return self.peer_ready.wait(timeout)

    def wait_data_plane(self, timeout: float = 10.0) -> bool:
        return self.data_plane_proven.wait(timeout)

    def advertise(self, payload: bytes, timeout: float = 1.0) -> str:
        payload = bytes(payload)
        if not self.data_plane_proven.is_set():
            raise ConnectionError("C0 data plane is not proven")
        if self._advertisement_sent_generation == self.proof_generation:
            raise TunnelV2Error(
                "C_ADVERTISEMENT_DUPLICATE", "advertisement was already sent in this proof generation"
            )
        digest = advertisement_hash(payload)
        self._put(Kind.ADVERTISEMENT, payload, timeout)
        self._advertisement_sent_generation = self.proof_generation
        return digest

    def send_side_ready(self, payload: bytes, timeout: float = 1.0) -> None:
        if not self.data_plane_proven.is_set():
            raise ConnectionError("C0 data plane is not proven")
        self._put(Kind.SIDE_READY, bytes(payload), timeout)

    def poll(self, limit: int = 32) -> list[Envelope]:
        frames = []
        for _ in range(limit):
            try:
                frames.append(self._inbox.get_nowait())
            except queue.Empty:
                break
        return frames

    def _put(self, kind: Kind, payload: bytes, timeout: float) -> None:
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds the v2 bound")
        self._outbox.put(_Pending(kind, payload), timeout=timeout)

    def _clear_readiness(self) -> None:
        self.authenticated.clear()
        self.peer_ready.clear()
        self.data_plane_proven.clear()

    def _clear_queues(self) -> None:
        for target in (self._outbox, self._inbox):
            while True:
                try:
                    target.get_nowait()
                    self.stats["dropped"] += 1
                except queue.Empty:
                    break

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as error:  # pragma: no cover - final containment
            self.last_error = str(error)
            self.log(f"[tunnel-v2] thread stopped: {error}")
        finally:
            self._clear_readiness()

    async def _send(self, websocket, kind: Kind, payload: bytes = b"") -> None:
        raw = Envelope(
            self.attempt_id, self.source_seat, self._epoch,
            self._sequence, kind, payload,
        ).encode()
        self._sequence += 1
        await websocket.send(raw)
        self.stats["sent"] += 1

    async def _main(self) -> None:
        import websockets

        first = True
        while not self._stop.is_set():
            try:
                options = {"max_size": MAX_ENVELOPE_BYTES}
                header_name = ("additional_headers" if "additional_headers" in
                               inspect.signature(websockets.connect).parameters else "extra_headers")
                options[header_name] = {"Authorization": f"Bearer {self.member_token}"}
                options[header_name].update({
                    "X-SwitchTrade-Run-ID": self.run_id,
                    "X-SwitchTrade-Stage-Generation": str(self.stage_generation),
                    "X-SwitchTrade-Launch-Nonce": self.launch_nonce,
                    "X-SwitchTrade-Endpoint-PID": str(self.endpoint_pid),
                })
                async with websockets.connect(self.url, **options) as websocket:
                    self._epoch = secrets.randbits(64)
                    self._sequence = 0
                    self._clear_queues()
                    self._clear_readiness()
                    self.connection_generation += 1
                    if not first:
                        self.stats["reconnects"] += 1
                    first = False
                    self.authenticated.set()
                    self.last_error = self.last_error_code = ""
                    await self._send(websocket, Kind.PEER_READY)
                    await self._session(websocket)
            except TunnelV2Error as error:
                self.last_error_code = error.code
                self.last_error = str(error)
                self.last_error_type = type(error).__name__
                self._stop.set()
            except Exception as error:
                self.last_error = str(error)
                self.last_error_type = type(error).__name__
                received = getattr(error, "rcvd", None)
                close_code = getattr(received, "code", None)
                if close_code is None and not type(error).__name__.startswith("ConnectionClosed"):
                    close_code = getattr(error, "code", None)
                if permanent_connect_error(error) or close_code in {4401, 4403, 4404, 4409}:
                    self.last_error_code = "C_AUTHENTICATION_FAILED"
                    self._stop.set()
            finally:
                self._clear_readiness()
            if not self._stop.is_set():
                await asyncio.sleep(0.5)

    async def _session(self, websocket) -> None:
        gate = SequenceGate(self.attempt_id, self.source_seat.peer)
        challenge: bytes | None = None
        challenge_returned = answered_peer_challenge = False
        while not self._stop.is_set():
            for _ in range(8):
                try:
                    pending = self._outbox.get_nowait()
                except queue.Empty:
                    break
                await self._send(websocket, pending.kind, pending.payload)

            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.01)
            except asyncio.TimeoutError:
                continue
            envelope = Envelope.decode(raw)
            prior_peer_epoch = gate.epoch
            gate.accept(envelope)
            self.stats["received"] += 1
            if envelope.kind is Kind.PEER_READY:
                if prior_peer_epoch is not None and prior_peer_epoch != envelope.source_epoch:
                    self.peer_ready.clear()
                    self.data_plane_proven.clear()
                    challenge = None
                    challenge_returned = answered_peer_challenge = False
                    self._epoch = secrets.randbits(64)
                    self._sequence = 0
                    await self._send(websocket, Kind.PEER_READY)
                self.peer_ready.set()
                challenge = new_probe()
                await self._send(websocket, Kind.PROBE_CHALLENGE, challenge)
            elif envelope.kind is Kind.PROBE_CHALLENGE:
                await self._send(websocket, Kind.PROBE_RESPONSE, envelope.payload)
                answered_peer_challenge = True
            elif envelope.kind is Kind.PROBE_RESPONSE:
                if challenge is None or not verify_probe(challenge, envelope.payload):
                    raise TunnelV2Error("C_PROBE_MISMATCH", "probe response does not match challenge")
                challenge_returned = True
            elif envelope.kind is Kind.ADVERTISEMENT:
                digest = advertisement_hash(envelope.payload)
                if not self.data_plane_proven.is_set():
                    raise TunnelV2Error("C_ADVERTISEMENT_EARLY", "advertisement arrived before C0 probe")
                if (self.expected_advertisement_hash is not None and
                        not verify_advertisement(
                            envelope.payload, self.expected_advertisement_hash)):
                    raise TunnelV2Error(
                        "C_ADVERTISEMENT_HASH_MISMATCH", "advertisement hash does not match A evidence"
                    )
                if self.received_advertisement_hash is not None:
                    if self.received_advertisement_hash != digest:
                        raise TunnelV2Error(
                            "C_ADVERTISEMENT_CHANGED", "advertisement changed inside one attempt"
                        )
                    self.stats["advertisement_replays"] += 1
                    continue
                self.received_advertisement_hash = digest
                self._inbox.put_nowait(envelope)
            elif envelope.kind in {Kind.SIDE_READY, Kind.PEER_CLOSE}:
                self._inbox.put_nowait(envelope)
            if (challenge_returned and answered_peer_challenge and
                    not self.data_plane_proven.is_set()):
                self.proof_generation += 1
                self.data_plane_proven.set()
