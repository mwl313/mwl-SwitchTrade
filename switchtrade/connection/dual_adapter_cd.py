"""Pure contract for the single-PC, dual-adapter, Switchless C+D suite."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
import re
import secrets
import uuid

from .b_fixture import FIXTURE, FIXTURE_ID, FIXTURE_SHA256
from .p0 import USB_ID, UsbAdapter


CONTRACT_VERSION = "single-pc-dual-adapter-cd.v1"
SCHEMA_VERSION = 1
MAX_SECONDARY_FAILURES = 16
CHALLENGE_BYTES = 32
FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,95}$")


class SuitePhase(str, Enum):
    CREATED = "created"
    PASSIVE_PREFLIGHT = "passive_preflight"
    ACQUIRING_A = "acquiring_a"
    ACQUIRING_B = "acquiring_b"
    P0_READY = "p0_ready"
    AUTHORITY_LOCKED = "authority_locked"
    C0 = "c0"
    C1 = "c1"
    C2 = "c2"
    CLOSING = "closing"
    CLEANING_B = "cleaning_b"
    CLEANING_A = "cleaning_a"
    TERMINAL = "terminal"


RUNNING_PHASES = (
    SuitePhase.CREATED,
    SuitePhase.PASSIVE_PREFLIGHT,
    SuitePhase.ACQUIRING_A,
    SuitePhase.ACQUIRING_B,
    SuitePhase.P0_READY,
    SuitePhase.AUTHORITY_LOCKED,
    SuitePhase.C0,
    SuitePhase.C1,
    SuitePhase.C2,
)


class SuiteContractError(ValueError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


@dataclass(frozen=True)
class SuiteFixture:
    fixture_id: str = FIXTURE_ID
    advertisement_sha256: str = FIXTURE_SHA256
    advertisement_bytes: int = len(FIXTURE)

    def public(self) -> dict:
        return {
            "id": self.fixture_id,
            "advertisement_sha256": self.advertisement_sha256,
            "advertisement_bytes": self.advertisement_bytes,
            "rfu_payload": "per-run-random",
        }


def new_challenge() -> bytes:
    """Return a non-persisted challenge for a real two-way tunnel proof."""
    return secrets.token_bytes(CHALLENGE_BYTES)


def challenge_evidence(value: bytes) -> dict:
    value = bytes(value)
    if len(value) != CHALLENGE_BYTES:
        raise SuiteContractError(
            "CD_CHALLENGE_INVALID", "C0_DATA_PLANE_PROVEN",
            f"challenge must be exactly {CHALLENGE_BYTES} bytes",
        )
    return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def _adapter_evidence(adapter: UsbAdapter) -> dict:
    return {
        "usb_id": adapter.usb_id,
        "adapter_identity_sha256": adapter.instance_sha256,
        "last_passed_gate": None,
        "cleanup_verified": False,
    }


def validate_adapter_pair(room_side: UsbAdapter, ap_side: UsbAdapter) -> None:
    adapters = (room_side, ap_side)
    if any(adapter.usb_id != USB_ID for adapter in adapters):
        raise SuiteContractError(
            "CD_ADAPTER_PROFILE_UNSUPPORTED", "passive_preflight",
            "both adapters must match the qualified hardware profile",
        )
    if room_side.instance_id.casefold() == ap_side.instance_id.casefold():
        raise SuiteContractError(
            "CD_ADAPTER_IDENTITY_DUPLICATE", "passive_preflight",
            "the two suite sides must use distinct Windows adapter identities",
        )
    if not all(adapter.shared for adapter in adapters):
        raise SuiteContractError(
            "CD_ADAPTER_NOT_AUTHORIZED", "passive_preflight",
            "both adapters must be authorized before the suite starts",
        )
    if any(adapter.attached for adapter in adapters):
        raise SuiteContractError(
            "CD_ADAPTER_NOT_WINDOWS_OWNED", "passive_preflight",
            "both adapters must begin Windows-owned and unattached",
        )


class SwitchlessCdState:
    """In-memory suite projection; persistence and external work are later milestones."""

    _NEXT = {
        SuitePhase.CREATED: SuitePhase.PASSIVE_PREFLIGHT,
        SuitePhase.PASSIVE_PREFLIGHT: SuitePhase.ACQUIRING_A,
        SuitePhase.ACQUIRING_A: SuitePhase.ACQUIRING_B,
        SuitePhase.ACQUIRING_B: SuitePhase.P0_READY,
        SuitePhase.P0_READY: SuitePhase.AUTHORITY_LOCKED,
        SuitePhase.AUTHORITY_LOCKED: SuitePhase.C0,
        SuitePhase.C0: SuitePhase.C1,
        SuitePhase.C1: SuitePhase.C2,
    }

    def __init__(self, run_id: str, release: str,
                 room_side: UsbAdapter, ap_side: UsbAdapter):
        try:
            normalized_run_id = str(uuid.UUID(str(run_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise SuiteContractError(
                "CD_RUN_ID_INVALID", "created", "run_id must be a UUID") from error
        if not isinstance(release, str) or not release or len(release) > 128:
            raise SuiteContractError(
                "CD_RELEASE_INVALID", "created", "release identity is invalid")
        validate_adapter_pair(room_side, ap_side)
        self._record = {
            "contract_version": CONTRACT_VERSION,
            "schema": SCHEMA_VERSION,
            "run_id": normalized_run_id,
            "release": release,
            "revision": 1,
            "phase": SuitePhase.CREATED.value,
            "status": "running",
            "functional_status": "pending",
            "cleanup_status": "pending",
            "last_passed_gate": None,
            "fixture": SuiteFixture().public(),
            "sides": {
                "room_side": {
                    "source_seat": "member_a",
                    "switch_role": "a_room_joiner",
                    **_adapter_evidence(room_side),
                },
                "ap_side": {
                    "source_seat": "member_b",
                    "switch_role": "b_ap_host",
                    **_adapter_evidence(ap_side),
                },
            },
            "authority_cleanup_verified": False,
            "primary_failure": None,
            "secondary_failures": [],
            "recovery_required": False,
        }

    def snapshot(self) -> dict:
        """Return a read-only projection without changing revision or phase."""
        return deepcopy(self._record)

    def _changed(self) -> dict:
        self._record["revision"] += 1
        return self.snapshot()

    @staticmethod
    def _failure(code: str, gate: str, message: str) -> dict:
        if not isinstance(code, str) or FAILURE_CODE.fullmatch(code) is None:
            raise SuiteContractError(
                "CD_FAILURE_INVALID", "report", "failure code is invalid")
        if not isinstance(gate, str) or not gate or len(gate) > 96:
            raise SuiteContractError(
                "CD_FAILURE_INVALID", "report", "failure gate is invalid")
        if not isinstance(message, str) or len(message) > 500:
            raise SuiteContractError(
                "CD_FAILURE_INVALID", "report", "failure message is invalid")
        return {"code": code, "gate": gate, "message": message}

    def advance(self, phase: SuitePhase | str) -> dict:
        current = SuitePhase(self._record["phase"])
        try:
            selected = SuitePhase(phase)
        except (TypeError, ValueError) as error:
            raise SuiteContractError(
                "CD_PHASE_INVALID", current.value,
                "suite phase is invalid",
            ) from error
        if self._NEXT.get(current) is not selected:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", current.value,
                f"cannot advance from {current.value} to {selected.value}",
            )
        self._record["phase"] = selected.value
        return self._changed()

    def pass_gate(self, side: str, gate: str) -> dict:
        current = SuitePhase(self._record["phase"])
        if current not in RUNNING_PHASES:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", current.value,
                "a gate cannot pass outside an active suite phase",
            )
        if side not in self._record["sides"]:
            raise SuiteContractError(
                "CD_SIDE_INVALID", "report", "suite side is invalid")
        if not isinstance(gate, str) or not gate or len(gate) > 96:
            raise SuiteContractError(
                "CD_GATE_INVALID", "report", "gate identity is invalid")
        self._record["sides"][side]["last_passed_gate"] = gate
        self._record["last_passed_gate"] = gate
        return self._changed()

    def begin_closing(self, outcome: str, *, code: str | None = None,
                      gate: str | None = None, message: str = "") -> dict:
        current = SuitePhase(self._record["phase"])
        if current not in RUNNING_PHASES:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", current.value,
                "closing requires an active suite phase",
            )
        if outcome not in {"passed", "failed", "canceled"}:
            raise SuiteContractError(
                "CD_OUTCOME_INVALID", current.value, "functional outcome is invalid")
        if outcome == "passed" and current is not SuitePhase.C2:
            raise SuiteContractError(
                "CD_PASS_PREMATURE", current.value,
                "the normal suite cannot pass before C2 completes",
            )
        if outcome == "failed":
            failure = self._failure(code or "", gate or "", message)
            if self._record["primary_failure"] is None:
                self._record["primary_failure"] = failure
        elif code is not None or gate is not None or message:
            raise SuiteContractError(
                "CD_OUTCOME_INVALID", current.value,
                "only a failed outcome may carry a primary failure",
            )
        self._record["functional_status"] = outcome
        self._record["phase"] = SuitePhase.CLOSING.value
        return self._changed()

    def begin_cleanup(self) -> dict:
        if self._record["phase"] != SuitePhase.CLOSING.value:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", self._record["phase"],
                "cleanup requires closing intent",
            )
        self._record["phase"] = SuitePhase.CLEANING_B.value
        return self._changed()

    def mark_authority_cleanup(self) -> dict:
        if self._record["authority_cleanup_verified"]:
            return self.snapshot()
        if self._record["phase"] not in {
                SuitePhase.CLOSING.value, SuitePhase.CLEANING_B.value,
                SuitePhase.CLEANING_A.value}:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", self._record["phase"],
                "authority cleanup is outside D",
            )
        self._record["authority_cleanup_verified"] = True
        return self._changed()

    def mark_side_cleanup(self, side: str) -> dict:
        if side not in self._record["sides"]:
            raise SuiteContractError(
                "CD_SIDE_INVALID", "cleanup", "suite side is invalid")
        if self._record["sides"][side]["cleanup_verified"]:
            return self.snapshot()
        expected = (
            ("ap_side", SuitePhase.CLEANING_B, SuitePhase.CLEANING_A),
            ("room_side", SuitePhase.CLEANING_A, SuitePhase.CLEANING_A),
        )
        try:
            _, required, following = next(item for item in expected if item[0] == side)
        except StopIteration as error:
            raise SuiteContractError(
                "CD_SIDE_INVALID", "cleanup", "suite side is invalid") from error
        if self._record["phase"] != required.value:
            raise SuiteContractError(
                "CD_CLEANUP_ORDER_INVALID", self._record["phase"],
                "adapter cleanup must run in reverse acquisition order",
            )
        self._record["sides"][side]["cleanup_verified"] = True
        self._record["phase"] = following.value
        return self._changed()

    def finish_cleanup(self, verified: bool, *, code: str | None = None,
                       gate: str = "D11_RELEASE", message: str = "") -> dict:
        if self._record["phase"] not in {
                SuitePhase.CLEANING_B.value, SuitePhase.CLEANING_A.value}:
            raise SuiteContractError(
                "CD_TRANSITION_INVALID", self._record["phase"],
                "cleanup completion requires a cleaning phase",
            )
        if verified:
            complete = (
                self._record["authority_cleanup_verified"] and
                all(side["cleanup_verified"] for side in self._record["sides"].values())
            )
            if not complete:
                raise SuiteContractError(
                    "CD_CLEANUP_UNVERIFIED", "D11_RELEASE",
                    "both sides and authority must be verified before release",
                )
            self._record["cleanup_status"] = "verified"
            self._record["status"] = self._record["functional_status"]
        else:
            failure = self._failure(code or "", gate, message)
            self._record["secondary_failures"].append(failure)
            self._record["secondary_failures"] = self._record["secondary_failures"][
                -MAX_SECONDARY_FAILURES:]
            self._record["cleanup_status"] = "failed"
            self._record["status"] = "failed"
            self._record["recovery_required"] = True
        self._record["phase"] = SuitePhase.TERMINAL.value
        return self._changed()


__all__ = [
    "CHALLENGE_BYTES", "CONTRACT_VERSION", "SCHEMA_VERSION", "SuiteContractError",
    "SuiteFixture", "SuitePhase", "SwitchlessCdState", "challenge_evidence",
    "new_challenge", "validate_adapter_pair",
]
