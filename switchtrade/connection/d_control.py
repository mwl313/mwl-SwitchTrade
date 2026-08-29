"""Control-owned, measured D5 acknowledgement for distributed ABC+D shutdown."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from typing import Callable

from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.connection.coordinator import ConnectionCoordinator, Phase, RunMode
from switchtrade.connection.p0 import atomic_json
from switchtrade.relay_client import RelayClient


CONTRACT_VERSION = "d5-control-state.v1"
ENDPOINT_CONTRACT = "d-endpoint-stage.v1"
QUIESCENT_CONTRACT = "d-side-quiescent.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[A-Z][A-Z0-9_.-]{0,95}")
_TERMINAL_ATTEMPT_PHASES = {"completed", "canceled", "failed"}
_SOFTWARE_ONLY_MODES = {RunMode.C_HARNESS.value}
_ENDPOINT_FIELDS = {
    "contract_version", "run_id", "attempt_id", "activation_generation", "source_seat",
    "stage_generation", "launch_identity_sha256", "outcome", "primary_failure_code",
    "last_passed_gate", "status", "forced", "evidence", "drain", "failures", "elapsed_ms",
}
_ENDPOINT_EVIDENCE_FIELDS = {
    "close_tail_required", "close_tail_observed", "bridge_admission_stopped",
    "bridge_transport_exited", "observer_stopped", "simulation_closed",
    "ldn_released", "radio_thread_exited",
}
_DRAIN_FIELDS = {
    "pending_local_frames", "flushed_local_frames", "discarded_local_frames",
    "discarded_remote_frames",
}


class DControlError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


def _read_json_bytes(path: Path, *, code: str = "D_ENDPOINT_REPORT_INVALID",
                     noun: str = "endpoint D2-D4 report", maximum: int = 262_144) -> tuple[dict, bytes]:
    try:
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise ValueError("state exceeds its bound")
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise DControlError(
            code, "D5_SIDE_QUIESCENT", f"the {noun} is unreadable",
        ) from error
    if not isinstance(value, dict):
        raise DControlError(
            code, "D5_SIDE_QUIESCENT", f"the {noun} is invalid",
        )
    return value, raw


def _read_json(path: Path, *, code: str = "D_ENDPOINT_REPORT_INVALID",
               noun: str = "endpoint D2-D4 report", maximum: int = 262_144) -> dict:
    return _read_json_bytes(path, code=code, noun=noun, maximum=maximum)[0]


def _endpoint_report(value: dict) -> dict:
    evidence = value.get("evidence")
    drain = value.get("drain")
    failures = value.get("failures")
    primary = value.get("primary_failure_code")
    last_gate = value.get("last_passed_gate")
    failure_items_valid = isinstance(failures, list) and len(failures) <= 16 and all(
        isinstance(item, dict) and set(item) == {"code", "gate", "message"} and
        isinstance(item.get("code"), str) and _CODE.fullmatch(item["code"]) is not None and
        item.get("gate") in {"D2_GAME_CLOSE_TAIL", "D3_BRIDGE_DRAIN", "D4_LDN_TEARDOWN"} and
        isinstance(item.get("message"), str) and len(item["message"]) <= 500
        for item in failures or []
    )
    valid = (
        set(value) == _ENDPOINT_FIELDS and value.get("contract_version") == ENDPOINT_CONTRACT and
        isinstance(value.get("run_id"), str) and isinstance(value.get("attempt_id"), str) and
        bool(value.get("attempt_id")) and
        isinstance(value.get("activation_generation"), int) and
        not isinstance(value.get("activation_generation"), bool) and
        value["activation_generation"] >= 1 and value.get("source_seat") in {"member_a", "member_b"} and
        isinstance(value.get("stage_generation"), int) and
        not isinstance(value.get("stage_generation"), bool) and value["stage_generation"] >= 1 and
        isinstance(value.get("launch_identity_sha256"), str) and
        _SHA256.fullmatch(value["launch_identity_sha256"]) is not None and
        value.get("outcome") in {"completed", "canceled", "failed"} and
        ((value.get("outcome") == "failed" and isinstance(primary, str) and
          _CODE.fullmatch(primary) is not None) or
         (value.get("outcome") != "failed" and primary is None)) and
        last_gate in {"D2_GAME_CLOSE_TAIL", "D3_BRIDGE_DRAIN", "D4_LDN_TEARDOWN", None} and
        value.get("status") in {"passed", "failed"} and isinstance(value.get("forced"), bool) and
        isinstance(value.get("elapsed_ms"), int) and not isinstance(value.get("elapsed_ms"), bool) and
        value["elapsed_ms"] >= 0 and isinstance(evidence, dict) and
        set(evidence) == _ENDPOINT_EVIDENCE_FIELDS and
        all(isinstance(item, bool) for item in evidence.values()) and
        isinstance(drain, dict) and set(drain) == _DRAIN_FIELDS and
        all(isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 256
            for item in drain.values()) and
        failure_items_valid and (value["status"] == "failed") == bool(failures) and
        value["forced"] == bool(failures)
    )
    try:
        uuid.UUID(str(value.get("run_id")))
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise DControlError(
            "D_ENDPOINT_REPORT_INVALID", "D5_SIDE_QUIESCENT",
            "the endpoint D2-D4 report does not match its strict contract",
        )
    return value


def _quiescent_payload(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "contract_version", "attempt_id", "activation_generation", "source_seat", "run_id",
        "stage_generation", "launch_identity_sha256", "evidence",
    }:
        return False
    evidence = value.get("evidence")
    valid = (
        value.get("contract_version") == QUIESCENT_CONTRACT and
        isinstance(value.get("attempt_id"), str) and bool(value["attempt_id"]) and
        value.get("source_seat") in {"member_a", "member_b"} and
        isinstance(value.get("activation_generation"), int) and
        not isinstance(value.get("activation_generation"), bool) and
        value["activation_generation"] >= 1 and
        isinstance(value.get("stage_generation"), int) and
        not isinstance(value.get("stage_generation"), bool) and value["stage_generation"] >= 1 and
        isinstance(value.get("launch_identity_sha256"), str) and
        _SHA256.fullmatch(value["launch_identity_sha256"]) is not None and
        isinstance(evidence, dict) and set(evidence) == {
            "endpoint_exited", "transport_exited", "threads_exited", "ldn_released",
            "interfaces_absent", "forced",
        } and all(isinstance(item, bool) for item in evidence.values())
    )
    try:
        uuid.UUID(str(value.get("run_id")))
    except (TypeError, ValueError, AttributeError):
        return False
    return valid


def load_d5_state(path: str | Path) -> dict:
    """Read the private retry record without accepting extra or malformed fields."""
    state = _read_json(
        Path(path), code="D_CONTROL_STATE_INVALID", noun="persisted D5 control state",
        maximum=65_536)
    valid = (
        set(state) == {
            "contract_version", "schema", "run_id", "room_id", "attempt_id",
            "expected_room_version", "command_id", "endpoint_report_sha256", "measurement",
            "payload",
        } and state.get("contract_version") == CONTRACT_VERSION and state.get("schema") == 1 and
        isinstance(state.get("run_id"), str) and isinstance(state.get("room_id"), str) and
        bool(state["room_id"]) and isinstance(state.get("attempt_id"), str) and
        bool(state["attempt_id"]) and isinstance(state.get("expected_room_version"), int) and
        not isinstance(state.get("expected_room_version"), bool) and
        state["expected_room_version"] >= 1 and isinstance(state.get("command_id"), str) and
        isinstance(state.get("endpoint_report_sha256"), str) and
        _SHA256.fullmatch(state["endpoint_report_sha256"]) is not None and
        isinstance(state.get("measurement"), dict) and
        set(state["measurement"]) == {
            "process_state_known", "temporary_interface_state_known"} and
        all(isinstance(item, bool) for item in state["measurement"].values()) and
        _quiescent_payload(state.get("payload"))
    )
    try:
        uuid.UUID(str(state.get("run_id")))
        if uuid.UUID(str(state.get("command_id"))).version != 7:
            valid = False
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise DControlError(
            "D_CONTROL_STATE_INVALID", "D5_SIDE_QUIESCENT",
            "the persisted D5 control state is invalid",
        )
    return state


def _authority_d(room: dict, identity: dict) -> dict:
    attempt = room.get("attempt") if isinstance(room, dict) else None
    state = attempt.get("d") if isinstance(attempt, dict) else None
    if (
        not isinstance(attempt, dict) or not isinstance(state, dict) or
        room.get("room_id") != identity["room_id"] or
        attempt.get("attempt_id") != identity["attempt_id"] or
        attempt.get("phase") not in {"closing", *_TERMINAL_ATTEMPT_PHASES} or
        not isinstance(room.get("room_version"), int) or room["room_version"] < 1 or
        not isinstance(state.get("activation_generation"), int) or
        state["activation_generation"] < 1 or
        state.get("outcome") not in {"completed", "canceled", "failed"}
    ):
        raise DControlError(
            "D_AUTHORITY_STATE_INVALID", "D5_SIDE_QUIESCENT",
            "the authority D1 state does not match this run",
        )
    return state


class MeasuredD5Control:
    """Build D5 from a persisted endpoint report and independent local probes.

    `radio_probe` measures endpoint-owned temporary interfaces on the bound PHY. The run-owned P0
    USB lease and its base interface remain attached until D9/D10.
    """

    def __init__(
        self,
        *,
        coordinator: ConnectionCoordinator,
        relay,
        run_id: str,
        member_token: str,
        endpoint_report_path: str | Path,
        state_path: str | Path,
        process_probe: Callable[[int], int | None],
        radio_probe: Callable[[dict], dict] | None = None,
        exit_timeout: float = 5.0,
        stable_samples: int = 3,
        sample_interval: float = 0.1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        try:
            self.run_id = str(uuid.UUID(str(run_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("D run identity is invalid") from error
        if not isinstance(member_token, str) or not member_token:
            raise ValueError("D member credential is unavailable")
        if exit_timeout <= 0 or stable_samples < 1 or sample_interval <= 0:
            raise ValueError("D measurement policy is invalid")
        self.coordinator = coordinator
        self.relay = relay
        self.member_token = member_token
        self.endpoint_report_path = Path(endpoint_report_path)
        self.state_path = Path(state_path)
        self.process_probe = process_probe
        self.radio_probe = radio_probe
        self.exit_timeout = exit_timeout
        self.stable_samples = stable_samples
        self.sample_interval = sample_interval
        self.monotonic = monotonic
        self.sleep = sleep

    def _run(self) -> dict:
        run = self.coordinator.snapshot(self.run_id)
        identity = run.get("identity") if isinstance(run, dict) else None
        if (
            not isinstance(run, dict) or not isinstance(identity, dict) or
            run.get("phase") not in {Phase.CLOSING.value, Phase.CLEANING.value} or
            run.get("functional", {}).get("status") == "pending" or
            not run.get("ownership", {}).get("endpoint_started") or
            not all(identity.get(key) is not None for key in (
                "room_id", "attempt_id", "authority_seat", "stage_generation",
                "launch_nonce", "endpoint_pid", "endpoint_start_ticks",
            ))
        ):
            raise DControlError(
                "D_RUN_STATE_INVALID", "D5_SIDE_QUIESCENT",
                "the coordinator run is not ready for measured D5",
            )
        return run

    @staticmethod
    def _validate_binding(run: dict, state: dict, report: dict) -> None:
        identity = run["identity"]
        expected_hash = launch_identity_hash(
            run["run_id"], identity["stage_generation"],
            identity["launch_nonce"], identity["endpoint_pid"],
        )
        expected = {
            "run_id": run["run_id"],
            "attempt_id": identity["attempt_id"],
            "activation_generation": state["activation_generation"],
            "source_seat": identity["authority_seat"],
            "stage_generation": identity["stage_generation"],
            "launch_identity_sha256": expected_hash,
            "outcome": state["outcome"],
            "primary_failure_code": state.get("primary_failure_code"),
        }
        if any(report.get(key) != value for key, value in expected.items()):
            raise DControlError(
                "D_ENDPOINT_IDENTITY_MISMATCH", "D5_SIDE_QUIESCENT",
                "the endpoint D2-D4 report is stale or belongs to another launch",
            )

    def _measure_process_exit(self, pid: int, start_ticks: int) -> tuple[bool, bool]:
        deadline = self.monotonic() + self.exit_timeout
        unknown = False
        while True:
            try:
                actual = self.process_probe(pid)
            except Exception:
                actual = start_ticks
                unknown = True
            if actual is None or actual != start_ticks:
                return True, unknown
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return False, unknown
            self.sleep(min(self.sample_interval, remaining))

    def _measure_interfaces(self, identity: dict) -> tuple[bool, bool]:
        if identity["mode"] in _SOFTWARE_ONLY_MODES:
            return True, False
        if self.radio_probe is None:
            return False, True
        deadline = self.monotonic() + self.exit_timeout
        stable = 0
        unknown = False
        probe_identity = {**identity, "run_id": self.run_id}
        while True:
            try:
                result = self.radio_probe(deepcopy(probe_identity))
            except Exception:
                result = {"status": "unknown", "owned_interfaces": None}
            if not isinstance(result, dict) or result.get("status") not in {
                    "quiescent", "active", "unknown"}:
                result = {"status": "unknown", "owned_interfaces": None}
            if result["status"] == "unknown":
                unknown = True
            clean = result["status"] == "quiescent" and result.get("owned_interfaces") == 0
            stable = stable + 1 if clean else 0
            if stable >= self.stable_samples:
                return True, unknown
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return False, unknown
            self.sleep(min(self.sample_interval, remaining))

    def _prepare(self, room: dict) -> dict:
        run = self._run()
        identity = run["identity"]
        authority = _authority_d(room, identity)
        functional = run["functional"]
        expected_outcome = {
            "passed": "completed", "canceled": "canceled",
            "failed": "failed", "interrupted": "failed",
        }.get(functional["status"])
        if (authority["outcome"] != expected_outcome or
                authority.get("primary_failure_code") !=
                (functional.get("code") if expected_outcome == "failed" else None)):
            raise DControlError(
                "D_OUTCOME_MISMATCH", "D5_SIDE_QUIESCENT",
                "the authority D1 outcome does not match the coordinator's preserved result",
            )
        report_value, report_bytes = _read_json_bytes(self.endpoint_report_path)
        report = _endpoint_report(report_value)
        self._validate_binding(run, authority, report)
        endpoint_exited, process_unknown = self._measure_process_exit(
            identity["endpoint_pid"], identity["endpoint_start_ticks"])
        interfaces_absent, radio_unknown = self._measure_interfaces(identity)
        endpoint = report["evidence"]
        evidence = {
            "endpoint_exited": endpoint_exited,
            "transport_exited": endpoint["bridge_transport_exited"],
            "threads_exited": all(endpoint[key] for key in (
                "observer_stopped", "simulation_closed", "radio_thread_exited")),
            "ldn_released": endpoint["ldn_released"],
            "interfaces_absent": interfaces_absent,
            "forced": bool(report["forced"] or process_unknown or radio_unknown or
                           not endpoint_exited or not interfaces_absent),
        }
        payload = {
            "contract_version": QUIESCENT_CONTRACT,
            "attempt_id": identity["attempt_id"],
            "activation_generation": authority["activation_generation"],
            "source_seat": identity["authority_seat"],
            "run_id": run["run_id"],
            "stage_generation": identity["stage_generation"],
            "launch_identity_sha256": report["launch_identity_sha256"],
            "evidence": evidence,
        }
        persisted = {
            "contract_version": CONTRACT_VERSION,
            "schema": 1,
            "run_id": run["run_id"],
            "room_id": identity["room_id"],
            "attempt_id": identity["attempt_id"],
            "expected_room_version": room["room_version"],
            # Generate once, persist before the request, and reuse after response loss.
            "command_id": RelayClient.command_id(),
            "endpoint_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "measurement": {
                "process_state_known": not process_unknown,
                "temporary_interface_state_known": not radio_unknown,
            },
            "payload": payload,
        }
        atomic_json(self.state_path, persisted, private=True)
        return persisted

    def _load_or_prepare(self, room: dict) -> dict:
        if not self.state_path.exists():
            return self._prepare(room)
        state = load_d5_state(self.state_path)
        run = self._run()
        authority = _authority_d(room, run["identity"])
        functional = run["functional"]
        expected_outcome = {
            "passed": "completed", "canceled": "canceled",
            "failed": "failed", "interrupted": "failed",
        }.get(functional["status"])
        valid = (
            state.get("run_id") == run["run_id"] and
            state.get("room_id") == run["identity"]["room_id"] and
            state.get("attempt_id") == run["identity"]["attempt_id"] and
            state["payload"]["activation_generation"] == authority["activation_generation"] and
            authority["outcome"] == expected_outcome and
            authority.get("primary_failure_code") ==
            (functional.get("code") if expected_outcome == "failed" else None)
        )
        if not valid:
            raise DControlError(
                "D_CONTROL_STATE_INVALID", "D5_SIDE_QUIESCENT",
                "the persisted D5 control state is invalid",
            )
        try:
            _value, current_report = _read_json_bytes(self.endpoint_report_path)
            current_report_sha256 = hashlib.sha256(current_report).hexdigest()
        except DControlError as error:
            raise DControlError(
                "D_CONTROL_STATE_INVALID", "D5_SIDE_QUIESCENT",
                "the report bound to the persisted D5 state is unavailable",
            ) from error
        if current_report_sha256 != state["endpoint_report_sha256"]:
            raise DControlError(
                "D_CONTROL_STATE_INVALID", "D5_SIDE_QUIESCENT",
                "the report bound to the persisted D5 state changed",
            )
        self._validate_binding(run, authority, {
            **state["payload"],
            "outcome": authority["outcome"],
            "primary_failure_code": authority.get("primary_failure_code"),
        })
        return state

    def acknowledge(self, room: dict) -> dict:
        """Submit one idempotent, measured acknowledgement; credentials never enter state."""
        state = self._load_or_prepare(room)
        response = self.relay.acknowledge_distributed_d(
            state["room_id"], state["attempt_id"], self.member_token,
            deepcopy(state["payload"]),
            expected_version=state["expected_room_version"],
            command_id=state["command_id"],
        )
        return {"room": response, "control": deepcopy(state)}


__all__ = ["CONTRACT_VERSION", "DControlError", "MeasuredD5Control", "load_d5_state"]
