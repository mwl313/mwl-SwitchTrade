"""Truthful C0/C1 stage projection over rfu-tunnel.v2."""

from __future__ import annotations

import time
from typing import Callable

from switchtrade.rfu_tunnel_v2 import Kind, SourceSeat, TunnelV2Error
from switchtrade.tunnel_client_v2 import TunnelClientV2


GATES = (
    "C0_AUTHENTICATED",
    "C0_PEER_READY",
    "C0_DATA_PLANE_PROVEN",
    "C1_ADVERTISEMENT_DELIVERED",
)


class CStageError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


class CStage:
    """One endpoint's C0/C1 state; physical A/B and C2 are deliberately outside it."""

    def __init__(self, run_id: str, attempt_id: str, source_seat: SourceSeat | str,
                 switch_role: str, client: TunnelClientV2, *,
                 gate_sink: Callable[[dict], None] = lambda _value: None):
        if not run_id or not attempt_id:
            raise ValueError("run and attempt identities are required")
        if switch_role not in {"a_room_joiner", "b_ap_host"}:
            raise ValueError("switch role is invalid")
        seat = SourceSeat.parse(source_seat)
        if (client.attempt_id != attempt_id or client.source_seat is not seat):
            raise ValueError("tunnel client identity does not match the C stage")
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.source_seat = seat
        self.switch_role = switch_role
        self.client = client
        self.gate_sink = gate_sink
        self.started = time.monotonic()
        self.last_passed_gate: str | None = None
        self.advertisement_hash: str | None = None
        self.failure: dict | None = None

    def _pass(self, gate: str) -> None:
        self.last_passed_gate = gate
        self.gate_sink({
            "gate": gate,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
        })

    def _wait(self, event, timeout: float, code: str, gate: str, message: str) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if event.wait(min(0.05, max(0.0, deadline - time.monotonic()))):
                self._pass(gate)
                return
            if self.client.last_error_code:
                raise CStageError(self.client.last_error_code, gate, self.client.last_error or message)
        raise CStageError(code, gate, message)

    def connect(self, timeout: float = 10.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.client.start()
        deadline = time.monotonic() + timeout
        waits = (
            (self.client.authenticated, "C_AUTHENTICATION_TIMEOUT", GATES[0],
             "relay authentication timed out"),
            (self.client.peer_ready, "C_PEER_READY_TIMEOUT", GATES[1],
             "ordered peer readiness timed out"),
            (self.client.data_plane_proven, "C_PROBE_TIMEOUT", GATES[2],
             "bidirectional relay probe timed out"),
        )
        try:
            for event, code, gate, message in waits:
                self._wait(event, max(0.001, deadline - time.monotonic()), code, gate, message)
        except CStageError as error:
            self.failure = {"code": error.code, "gate": error.gate, "message": error.message}
            raise

    def publish_advertisement(self, payload: bytes) -> str:
        if self.switch_role != "a_room_joiner":
            raise CStageError(
                "C_DIRECTION_INVALID", GATES[3], "only the A-side may publish an advertisement")
        try:
            self.advertisement_hash = self.client.advertise(payload)
        except (ConnectionError, TunnelV2Error) as error:
            code = getattr(error, "code", "C_DATA_PLANE_NOT_READY")
            raise CStageError(code, GATES[3], str(error)) from error
        return self.advertisement_hash

    def receive_advertisement_payload(self, timeout: float = 10.0) -> tuple[bytes, str]:
        if self.switch_role != "b_ap_host":
            raise CStageError(
                "C_DIRECTION_INVALID", GATES[3], "only the B-side may receive an advertisement")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in self.client.poll():
                if frame.kind is Kind.ADVERTISEMENT:
                    self.advertisement_hash = self.client.received_advertisement_hash
                    self._pass(GATES[3])
                    return bytes(frame.payload), self.advertisement_hash or ""
            if self.client.last_error_code:
                error = CStageError(
                    self.client.last_error_code, GATES[3],
                    self.client.last_error or "advertisement delivery failed")
                self.failure = {"code": error.code, "gate": error.gate, "message": error.message}
                raise error
            time.sleep(0.02)
        error = CStageError(
            "C_ADVERTISEMENT_TIMEOUT", GATES[3], "validated advertisement delivery timed out")
        self.failure = {"code": error.code, "gate": error.gate, "message": error.message}
        raise error

    def receive_advertisement(self, timeout: float = 10.0) -> str:
        return self.receive_advertisement_payload(timeout)[1]

    def stop(self) -> None:
        self.client.stop()

    def report(self) -> dict:
        return {
            "contract_version": "c0-c1-stage.v1",
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "source_seat": self.source_seat.label,
            "switch_role": self.switch_role,
            "last_passed_gate": self.last_passed_gate,
            "advertisement_sha256": self.advertisement_hash,
            "failure": self.failure,
        }
