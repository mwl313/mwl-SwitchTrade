"""Canonical, identity-bound SIDE_READY payload shared by endpoint and relay."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import uuid

from switchtrade.rfu_tunnel_v2 import SourceSeat, TunnelV2Error


CONTRACT = "side-ready.v1"
ROLE_GATES = {"a_room_joiner": "A_READY", "b_ap_host": "B_READY"}
FIELDS = {
    "contract_version", "attempt_id", "activation_generation", "source_seat",
    "switch_role", "local_gate", "run_id", "stage_generation",
    "launch_identity_sha256", "advertisement_sha256", "proof_generation",
}
SHA256 = re.compile(r"[0-9a-f]{64}")


def launch_identity_hash(run_id: str, stage_generation: int,
                         launch_nonce: str, endpoint_pid: int) -> str:
    if stage_generation < 1 or endpoint_pid < 1 or not 32 <= len(launch_nonce) <= 128:
        raise ValueError("launch identity is invalid")
    run_id = str(uuid.UUID(run_id))
    value = json.dumps(
        [run_id, stage_generation, launch_nonce, endpoint_pid],
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class SideReady:
    contract_version: str
    attempt_id: str
    activation_generation: int
    source_seat: str
    switch_role: str
    local_gate: str
    run_id: str
    stage_generation: int
    launch_identity_sha256: str
    advertisement_sha256: str
    proof_generation: int

    def validate(self) -> "SideReady":
        if self.contract_version != CONTRACT:
            raise TunnelV2Error("C_SIDE_READY_CONTRACT", "SIDE_READY contract is incompatible")
        if not isinstance(self.attempt_id, str):
            raise TunnelV2Error("C_SIDE_READY_IDENTITY", "SIDE_READY attempt is invalid")
        try:
            attempt_bytes = self.attempt_id.encode("utf-8")
        except UnicodeEncodeError as error:
            raise TunnelV2Error(
                "C_SIDE_READY_IDENTITY", "SIDE_READY attempt is invalid"
            ) from error
        if not 1 <= len(attempt_bytes) <= 128:
            raise TunnelV2Error("C_SIDE_READY_IDENTITY", "SIDE_READY attempt is invalid")
        try:
            seat = SourceSeat.parse(self.source_seat)
            run_id = str(uuid.UUID(self.run_id))
        except (TunnelV2Error, ValueError) as error:
            raise TunnelV2Error("C_SIDE_READY_IDENTITY", "SIDE_READY identity is invalid") from error
        if seat.label != self.source_seat or run_id != self.run_id:
            raise TunnelV2Error("C_SIDE_READY_IDENTITY", "SIDE_READY identity is not canonical")
        if self.switch_role not in ROLE_GATES or ROLE_GATES[self.switch_role] != self.local_gate:
            raise TunnelV2Error("C_SIDE_READY_ROLE", "SIDE_READY role and local gate do not match")
        for name, value in (
                ("activation_generation", self.activation_generation),
                ("stage_generation", self.stage_generation),
                ("proof_generation", self.proof_generation)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise TunnelV2Error("C_SIDE_READY_GENERATION", f"{name} is invalid")
        if not SHA256.fullmatch(self.launch_identity_sha256):
            raise TunnelV2Error("C_SIDE_READY_IDENTITY", "launch identity hash is invalid")
        if not SHA256.fullmatch(self.advertisement_sha256):
            raise TunnelV2Error("C_SIDE_READY_ADVERTISEMENT", "advertisement hash is invalid")
        return self

    def encode(self) -> bytes:
        self.validate()
        return json.dumps(
            asdict(self), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")

    @classmethod
    def decode(cls, payload: bytes) -> "SideReady":
        try:
            value = json.loads(bytes(payload).decode("ascii"))
            if not isinstance(value, dict) or set(value) != FIELDS:
                raise ValueError("SIDE_READY fields are invalid")
            return cls(**value).validate()
        except TunnelV2Error:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise TunnelV2Error("C_SIDE_READY_INVALID", "SIDE_READY payload is invalid") from error
