"""C2 activation barrier and bounded feature-neutral RFU bridge."""

from __future__ import annotations

from collections import deque
import queue
import threading
import time
from typing import Callable

from switchtrade.c2_protocol import CONTRACT, ROLE_GATES, SHA256, SideReady, launch_identity_hash
from switchtrade.rfu_tunnel import MAX_PAYLOAD_BYTES as MAX_RFU_PAYLOAD_BYTES
from switchtrade.rfu_tunnel_v2 import Envelope, Kind, SourceSeat, TunnelV2Error
from switchtrade.tunnel_client_v2 import TunnelClientV2


MAX_PRE_BARRIER_FRAMES = 256
GATES = ("C_LOCAL_SIDE_READY", "C_BRIDGE_READY", "C_RFU_ACTIVE")


class C2StageError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


class C2Bridge:
    """Queue local Reliable bytes until matching A/B readiness activates this attempt."""

    def __init__(self, run_id: str, attempt_id: str, source_seat: SourceSeat | str,
                 switch_role: str, client: TunnelClientV2, *, activation_generation: int,
                 advertisement_sha256: str,
                 gate_sink: Callable[[dict], None] = lambda _value: None):
        seat = SourceSeat.parse(source_seat)
        if switch_role not in ROLE_GATES:
            raise ValueError("switch role is invalid")
        if client.attempt_id != attempt_id or client.source_seat is not seat or client.run_id != run_id:
            raise ValueError("tunnel client identity does not match the C2 bridge")
        if activation_generation < 1:
            raise ValueError("activation generation must be positive")
        if not isinstance(advertisement_sha256, str) or not SHA256.fullmatch(advertisement_sha256):
            raise ValueError("advertisement hash is invalid")
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.source_seat = seat
        self.switch_role = switch_role
        self.client = client
        self.activation_generation = activation_generation
        self.advertisement_sha256 = advertisement_sha256
        self.gate_sink = gate_sink
        self.started = time.monotonic()
        self.connected = threading.Event()
        self.rfu_active = threading.Event()
        self.connection_generation = 0
        self.last_passed_gate: str | None = None
        self.failure: dict | None = None
        self._local_gate: str | None = None
        self._local_sent_proof = 0
        self._proof_generation = 0
        self._peer_ready_key: tuple[int, int] | None = None
        self._pending_local: deque[tuple[bytes, int]] = deque()
        self._pending_remote: deque[Envelope] = deque()
        self._canceled = False
        self._generation_tx = 0
        self._generation_rx = 0
        self.stats = {
            "queued_local_peak": 0, "tx_rfu_frames": 0, "rx_rfu_frames": 0,
            "activation_count": 0, "invalidations": 0,
        }

    def _pass(self, gate: str) -> None:
        if self.last_passed_gate == gate:
            return
        self.last_passed_gate = gate
        self.gate_sink({
            "gate": gate,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
        })

    def _fail(self, code: str, gate: str, message: str):
        if self.failure is None:
            self.failure = {"code": code, "gate": gate, "message": message}
        self.connected.clear()
        self.rfu_active.clear()
        raise C2StageError(**self.failure)

    def mark_local_ready(self, local_gate: str) -> None:
        expected = ROLE_GATES[self.switch_role]
        if local_gate != expected:
            self._fail("C_SIDE_READY_ROLE", GATES[0], "local A/B readiness gate is invalid")
        if self._canceled:
            self._fail("C_CANCELED", GATES[0], "C2 activation was canceled")
        if self._local_gate is not None and self._local_gate != local_gate:
            self._fail("C_SIDE_READY_CHANGED", GATES[0], "local readiness changed inside the attempt")
        self._local_gate = local_gate
        self._pass(GATES[0])
        self.pump()

    def _invalidate(self) -> None:
        if self.connected.is_set():
            self.stats["invalidations"] += 1
        self.connected.clear()
        self.rfu_active.clear()
        self._peer_ready_key = None
        self._local_sent_proof = 0
        self._pending_remote.clear()
        self._generation_tx = 0
        self._generation_rx = 0
        self.connection_generation += 1

    def _sync_proof(self) -> None:
        if self.client.last_error_code:
            self._fail(
                self.client.last_error_code, GATES[1],
                self.client.last_error or "v2 tunnel failed",
            )
        proof = self.client.proof_generation if self.client.data_plane_proven.is_set() else 0
        if proof != self._proof_generation:
            self._invalidate()
            self._proof_generation = proof
        if proof and self._local_gate and self._local_sent_proof != proof:
            ready = SideReady(
                CONTRACT, self.attempt_id, self.activation_generation,
                self.source_seat.label, self.switch_role, self._local_gate,
                self.run_id, self.client.stage_generation,
                launch_identity_hash(
                    self.run_id, self.client.stage_generation,
                    self.client.launch_nonce, self.client.endpoint_pid,
                ),
                self.advertisement_sha256, proof,
            )
            try:
                self.client.send_side_ready(ready.encode())
            except (ConnectionError, queue.Full, TunnelV2Error, ValueError) as error:
                self._fail("C_SIDE_READY_SEND_FAILED", GATES[1], str(error))
            self._local_sent_proof = proof

    def _accept_side_ready(self, envelope: Envelope) -> None:
        try:
            ready = SideReady.decode(envelope.payload)
        except TunnelV2Error as error:
            self._fail(error.code, GATES[1], str(error))
        expected_role = (
            "b_ap_host" if self.switch_role == "a_room_joiner" else "a_room_joiner"
        )
        if (ready.attempt_id != self.attempt_id or
                ready.source_seat != self.source_seat.peer.label or
                ready.switch_role != expected_role or
                ready.activation_generation != self.activation_generation):
            self._fail("C_SIDE_READY_STALE", GATES[1], "peer readiness is for another binding")
        if ready.advertisement_sha256 != self.advertisement_sha256:
            self._fail(
                "C_SIDE_READY_ADVERTISEMENT", GATES[1],
                "peer readiness references another advertisement",
            )
        if ready.run_id == self.run_id:
            self._fail("C_SIDE_READY_IDENTITY", GATES[1], "both sides cannot share one run identity")
        key = (envelope.source_epoch, ready.proof_generation)
        if self._peer_ready_key == key:
            self._fail("C_SIDE_READY_DUPLICATE", GATES[1], "peer readiness was duplicated")
        self._peer_ready_key = key

    def _send_now(self, payload: bytes, flags: int) -> None:
        try:
            self.client.send_rfu(payload, flags=flags)
        except (ConnectionError, queue.Full, TunnelV2Error, ValueError) as error:
            self._fail("C_RFU_BACKPRESSURE", GATES[2], str(error))
        self.stats["tx_rfu_frames"] += 1
        self._generation_tx += 1

    def _maybe_activate(self) -> None:
        if (self._local_sent_proof == self._proof_generation and self._peer_ready_key is not None and
                self._proof_generation and self.client.data_plane_proven.is_set() and
                not self.connected.is_set()):
            self.connected.set()
            self.stats["activation_count"] += 1
            self._pass(GATES[1])
        if self.connected.is_set():
            for _ in range(min(32, len(self._pending_local))):
                payload, flags = self._pending_local.popleft()
                self._send_now(payload, flags)
        if (self.connected.is_set() and self._generation_tx and
                self._generation_rx and not self.rfu_active.is_set()):
            self.rfu_active.set()
            self._pass(GATES[2])

    def pump(self) -> None:
        if self.failure is not None:
            raise C2StageError(**self.failure)
        if self._canceled:
            return
        self._sync_proof()
        for envelope in self.client.poll():
            if envelope.kind is Kind.SIDE_READY:
                self._accept_side_ready(envelope)
                self._maybe_activate()
            elif envelope.kind is Kind.RFU:
                if not self.connected.is_set():
                    self._fail("C_RFU_EARLY", GATES[1], "RFU arrived before C_BRIDGE_READY")
                if not envelope.flags & 0x01 or len(envelope.payload) > MAX_RFU_PAYLOAD_BYTES:
                    self._fail("C_RFU_INVALID", GATES[2], "RFU payload or Reliable flags are invalid")
                if len(self._pending_remote) >= MAX_PRE_BARRIER_FRAMES:
                    self._fail("C_RFU_BACKLOG_OVERFLOW", GATES[2], "RFU receive backlog overflow")
                self._pending_remote.append(envelope)
                self.stats["rx_rfu_frames"] += 1
                self._generation_rx += 1
            elif envelope.kind is Kind.PEER_CLOSE:
                self._fail("C_PEER_CLOSED", GATES[1], "peer closed before C2 completed")
        self._maybe_activate()

    def send_rfu(self, payload: bytes, *, flags: int) -> None:
        payload = bytes(payload)
        if not payload or len(payload) > MAX_RFU_PAYLOAD_BYTES or not 0 <= flags <= 0xFF:
            self._fail("C_RFU_INVALID", GATES[2], "RFU payload or Reliable flags are invalid")
        if not flags & 0x01:
            self._fail("C_RFU_INVALID", GATES[2], "RFU frame is not Reliable AppData")
        self.pump()
        if self.connected.is_set():
            self._send_now(payload, flags)
            self._maybe_activate()
            return
        if len(self._pending_local) >= MAX_PRE_BARRIER_FRAMES:
            self._fail(
                "C_PRE_BARRIER_OVERFLOW", GATES[1],
                "bounded pre-barrier RFU queue overflowed",
            )
        self._pending_local.append((payload, flags))
        self.stats["queued_local_peak"] = max(
            self.stats["queued_local_peak"], len(self._pending_local)
        )

    def poll(self, limit: int = 32) -> list[Envelope]:
        self.pump()
        frames = []
        for _ in range(min(limit, len(self._pending_remote))):
            frames.append(self._pending_remote.popleft())
        return frames

    def wait_bridge(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.connected.is_set():
            self.pump()
            time.sleep(0.01)
        return self.connected.is_set()

    def wait_rfu_active(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.rfu_active.is_set():
            self.pump()
            time.sleep(0.01)
        return self.rfu_active.is_set()

    def cancel(self) -> None:
        if self._canceled:
            return
        self._canceled = True
        self._pending_local.clear()
        self._pending_remote.clear()
        self.connected.clear()
        self.rfu_active.clear()
        if self.failure is None:
            self.failure = {
                "code": "C_CANCELED", "gate": GATES[1], "message": "C2 activation was canceled",
            }

    def report(self) -> dict:
        return {
            "contract_version": "c2-stage.v1",
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "source_seat": self.source_seat.label,
            "switch_role": self.switch_role,
            "activation_generation": self.activation_generation,
            "advertisement_sha256": self.advertisement_sha256,
            "last_passed_gate": self.last_passed_gate,
            "local_ready_gate": self._local_gate,
            "proof_generation": self._proof_generation,
            "queued_local_frames": len(self._pending_local),
            "stats": dict(self.stats),
            "failure": self.failure,
        }
