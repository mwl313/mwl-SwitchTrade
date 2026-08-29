"""Attempt-scoped ABC+D connection state and serialized command ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import queue
import re
import threading
import uuid

from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock


CONTRACT_VERSION = "connection-run.v1"
SCHEMA_VERSION = 1
MAX_HISTORY = 128
_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,95}$")
_GATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class RunMode(str, Enum):
    NORMAL = "normal"
    P0_HARNESS = "p0_harness"
    DIRECT_A = "direct_a"
    DIRECT_B = "direct_b"
    C_HARNESS = "c_harness"
    DIAGNOSTIC_AUTOMATED = "diagnostic_automated"
    DIAGNOSTIC_A = "diagnostic_a"
    DIAGNOSTIC_B = "diagnostic_b"
    DIAGNOSTIC_SUITE = "diagnostic_suite"


class Phase(str, Enum):
    CREATED = "created"
    PREFLIGHT = "preflight"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"
    CLOSING = "closing"
    CLEANING = "cleaning"
    TERMINAL = "terminal"


class AuthoritySeat(str, Enum):
    MEMBER_A = "member_a"
    MEMBER_B = "member_b"


class SwitchRole(str, Enum):
    A_ROOM_JOINER = "a_room_joiner"
    B_AP_HOST = "b_ap_host"


class LdnRole(str, Enum):
    STATION = "station"
    AP = "ap"


class RfuRole(str, Enum):
    PARENT = "parent"
    CHILD = "child"


class TunnelDirection(str, Enum):
    A_TO_B = "a_to_b"
    B_TO_A = "b_to_a"


class FunctionalOutcome(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class CleanupOutcome(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class ConnectionCoordinatorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Command:
    operation: str
    arguments: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: BaseException | None = None


_ALLOWED_TRANSITIONS = {
    Phase.CREATED: {Phase.PREFLIGHT, Phase.CLOSING},
    Phase.PREFLIGHT: {Phase.RUNNING, Phase.CLOSING},
    Phase.RUNNING: {Phase.AWAITING_USER, Phase.CLOSING},
    Phase.AWAITING_USER: {Phase.RUNNING, Phase.CLOSING},
    Phase.CLOSING: {Phase.CLEANING},
    Phase.CLEANING: set(),
    Phase.TERMINAL: set(),
}

_DIRECT_MODES = {RunMode.P0_HARNESS, RunMode.DIRECT_A, RunMode.DIRECT_B}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _copy(value: dict) -> dict:
    return json.loads(json.dumps(value))


def _bounded(value: object, name: str, *, maximum: int = 500, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", f"{name} is invalid")
    return value


def _code(value: object, name: str = "code") -> str:
    text = _bounded(value, name, maximum=96)
    if not _CODE.fullmatch(text):
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", f"{name} is invalid")
    return text


def _gate(value: object) -> str:
    text = _bounded(value, "gate", maximum=96)
    if not _GATE.fullmatch(text):
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "gate is invalid")
    return text


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", f"{name} is invalid")
    return value


def _enum(enum_type, value, name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", f"{name} is invalid") from error


def _evidence(value: dict | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 64:
        raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "cleanup evidence is invalid")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _GATE.fullmatch(key):
            raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "cleanup evidence key is invalid")
        if item is not None and (not isinstance(item, (bool, int)) or isinstance(item, float)):
            raise ConnectionCoordinatorError(
                "CONNECTION_INPUT_INVALID", "cleanup evidence values must be Boolean or integer")
        result[key] = item
    return result


class ConnectionCoordinator:
    """One serialized owner for one local ABC+D run.

    Milestone 1 owns state and identities only. Hardware and endpoint actions are deliberately absent;
    later stages must report their evidence through these commands.
    """

    def __init__(self, root: str | Path, release: str, *, command_timeout: float = 10):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.release = _bounded(release, "release", maximum=64)
        self.command_timeout = command_timeout
        try:
            self._instance_lock = SingleInstanceLock("connection-coordinator", self.root).acquire()
        except AlreadyRunningError as error:
            raise ConnectionCoordinatorError(
                "CONNECTION_COORDINATOR_ACTIVE", "another connection coordinator owns this runtime") from error
        self._active_file = self.root / "active-run.json"
        self._lock = threading.RLock()
        self._commands: queue.Queue[_Command | None] = queue.Queue()
        self._closed = False
        self._current: dict | None = None
        try:
            self._recover()
            self._thread = threading.Thread(
                target=self._command_loop, name="switchtrade-connection-coordinator", daemon=True)
            self._thread.start()
        except BaseException:
            self._instance_lock.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._commands.put(None)
        self._thread.join(timeout=self.command_timeout)
        if self._thread.is_alive():
            raise ConnectionCoordinatorError(
                "CONNECTION_COORDINATOR_STOP_TIMEOUT", "connection coordinator did not stop")
        self._instance_lock.close()

    def __enter__(self) -> "ConnectionCoordinator":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def start(self, mode: RunMode | str, *, adapter_instance_id: str | None = None,
              usb_id: str | None = None, run_id: str | None = None) -> dict:
        return self._submit("start", mode=mode, adapter_instance_id=adapter_instance_id,
                            usb_id=usb_id, run_id=run_id)

    def transition(self, run_id: str, phase: Phase | str, gate: str | None = None) -> dict:
        return self._submit("transition", run_id=run_id, phase=phase, gate=gate)

    def pass_gate(self, run_id: str, gate: str) -> dict:
        return self._submit("pass_gate", run_id=run_id, gate=gate)

    def bind_authority(self, run_id: str, *, room_id: str, room_version: int,
                       seat: AuthoritySeat | str, switch_role: SwitchRole | str) -> dict:
        return self._submit(
            "bind_authority", run_id=run_id, room_id=room_id, room_version=room_version,
            seat=seat, switch_role=switch_role)

    def acquire_wrapper(self, run_id: str, *, wrapper_pid: int, process_start_ticks: int,
                        adapter_instance_id: str, usb_id: str, bus_id: str) -> dict:
        return self._submit(
            "acquire_wrapper", run_id=run_id, wrapper_pid=wrapper_pid,
            process_start_ticks=process_start_ticks, adapter_instance_id=adapter_instance_id,
            usb_id=usb_id, bus_id=bus_id)

    def mark_p0_ready(self, run_id: str, *, wrapper_pid: int, process_start_ticks: int,
                      phy: str, netdev: str) -> dict:
        return self._submit(
            "mark_p0_ready", run_id=run_id, wrapper_pid=wrapper_pid,
            process_start_ticks=process_start_ticks, phy=phy, netdev=netdev)

    def lock_attempt(self, run_id: str, *, attempt_id: str, role_lock_version: int) -> dict:
        return self._submit(
            "lock_attempt", run_id=run_id, attempt_id=attempt_id,
            role_lock_version=role_lock_version)

    def reserve_endpoint_launch(self, run_id: str, *, launch_nonce: str) -> dict:
        return self._submit("reserve_endpoint_launch", run_id=run_id, launch_nonce=launch_nonce)

    def acknowledge_endpoint(self, run_id: str, *, launch_nonce: str, endpoint_pid: int,
                             process_start_ticks: int) -> dict:
        return self._submit(
            "acknowledge_endpoint", run_id=run_id, launch_nonce=launch_nonce,
            endpoint_pid=endpoint_pid, process_start_ticks=process_start_ticks)

    def request_cancel(self, run_id: str, *, code: str = "CONNECTION_CANCELED",
                       message: str = "The connection was canceled.") -> dict:
        return self._submit("request_cancel", run_id=run_id, code=code, message=message)

    def close_run(self, run_id: str, outcome: FunctionalOutcome | str, *, code: str | None = None,
                  message: str | None = None) -> dict:
        return self._submit(
            "close_run", run_id=run_id, outcome=outcome, code=code, message=message)

    def begin_cleanup(self, run_id: str) -> dict:
        return self._submit("begin_cleanup", run_id=run_id)

    def retry_cleanup(self, run_id: str) -> dict:
        return self._submit("retry_cleanup", run_id=run_id)

    def complete_cleanup(self, run_id: str, *, verified: bool, evidence: dict | None = None,
                         code: str | None = None, message: str | None = None) -> dict:
        return self._submit(
            "complete_cleanup", run_id=run_id, verified=verified, evidence=evidence,
            code=code, message=message)

    def snapshot(self, run_id: str | None = None) -> dict | None:
        """Return a detached read-only projection without entering the command queue."""
        with self._lock:
            if run_id is None:
                return _copy(self._current) if self._current is not None else None
            normalized = self._run_id(run_id)
            if self._current is not None and self._current["run_id"] == normalized:
                return _copy(self._current)
        path = self._record_path(normalized)
        if not path.is_file():
            return None
        value = self._read_json(path)
        self._validate_record(value, normalized)
        return _copy(value)

    def _submit(self, operation: str, **arguments) -> dict:
        with self._lock:
            if self._closed:
                raise ConnectionCoordinatorError(
                    "CONNECTION_COORDINATOR_STOPPED", "connection coordinator is stopped")
        command = _Command(operation, arguments)
        self._commands.put(command)
        if not command.done.wait(self.command_timeout):
            raise ConnectionCoordinatorError(
                "CONNECTION_COMMAND_TIMEOUT", "connection coordinator command timed out")
        if command.error is not None:
            raise command.error
        return _copy(command.result or {})

    def _command_loop(self) -> None:
        while True:
            command = self._commands.get()
            if command is None:
                return
            try:
                handler = getattr(self, f"_cmd_{command.operation}")
                with self._lock:
                    command.result = handler(**command.arguments)
            except BaseException as error:  # return the exact structured failure to the caller
                command.error = error
            finally:
                command.done.set()

    def _cmd_start(self, *, mode, adapter_instance_id, usb_id, run_id) -> dict:
        selected_mode = _enum(RunMode, mode, "mode")
        if self._has_cleanup_guard():
            raise ConnectionCoordinatorError(
                "CONNECTION_RUN_ACTIVE", "another run or unresolved cleanup owns the coordinator")
        if selected_mode != RunMode.C_HARNESS:
            adapter_instance_id = _bounded(
                adapter_instance_id, "adapter_instance_id", maximum=512)
            usb_id = _bounded(usb_id, "usb_id", maximum=32).lower()
        else:
            adapter_instance_id = _bounded(
                adapter_instance_id, "adapter_instance_id", maximum=512, required=False)
            usb_id = _bounded(usb_id, "usb_id", maximum=32, required=False)
            usb_id = usb_id.lower() if usb_id else None
        normalized_run_id = self._run_id(run_id or str(uuid.uuid4()))
        if self._record_path(normalized_run_id).exists():
            raise ConnectionCoordinatorError(
                "CONNECTION_RUN_EXISTS", "the requested run identifier already exists")
        now = _utc()
        identity = {
            "release": self.release,
            "mode": selected_mode.value,
            "run_generation": 1,
            "stage_generation": 1,
            "room_id": None,
            "room_version": None,
            "attempt_id": None,
            "role_lock_version": None,
            "authority_seat": None,
            "switch_role": None,
            "ldn_role": None,
            "rfu_role": None,
            "tunnel_direction": None,
            "launch_nonce": None,
            "wrapper_pid": None,
            "endpoint_pid": None,
            "process_start_ticks": None,
            "endpoint_start_ticks": None,
            "adapter_instance_id": adapter_instance_id,
            "usb_id": usb_id,
            "bus_id": None,
            "phy": None,
            "netdev": None,
        }
        if selected_mode == RunMode.DIRECT_A:
            identity.update(switch_role=SwitchRole.A_ROOM_JOINER.value, ldn_role=LdnRole.STATION.value)
        elif selected_mode == RunMode.DIRECT_B:
            identity.update(switch_role=SwitchRole.B_AP_HOST.value, ldn_role=LdnRole.AP.value)
        self._current = {
            "contract_version": CONTRACT_VERSION,
            "schema": SCHEMA_VERSION,
            "run_id": normalized_run_id,
            "revision": 0,
            "created_utc": now,
            "updated_utc": now,
            "phase": Phase.CREATED.value,
            "current_gate": None,
            "last_passed_gate": None,
            "functional": {"status": FunctionalOutcome.PENDING.value, "code": None, "message": None},
            "cleanup": {
                "status": CleanupOutcome.PENDING.value, "verified": False,
                "code": None, "message": None, "evidence": {}, "failures": [],
            },
            "recovery_required": False,
            "cancel_requested": False,
            "identity": identity,
            "ownership": {
                "wrapper_acquired": False,
                "p0_side_ready": False,
                "launch_reserved": False,
                "endpoint_started": False,
                "wrapper_count": 0,
                "launch_count": 0,
            },
            "history": [],
        }
        return self._persist("run_created")

    def _cmd_transition(self, *, run_id, phase, gate) -> dict:
        record = self._require_run(run_id)
        target = _enum(Phase, phase, "phase")
        if target == Phase.TERMINAL:
            raise ConnectionCoordinatorError(
                "CONNECTION_TRANSITION_INVALID", "terminal state requires verified cleanup")
        current = Phase(record["phase"])
        next_gate = _gate(gate) if gate is not None else record["current_gate"]
        if target == current:
            if next_gate == record["current_gate"]:
                return _copy(record)
        elif target not in _ALLOWED_TRANSITIONS[current]:
            raise ConnectionCoordinatorError(
                "CONNECTION_TRANSITION_INVALID", f"cannot move from {current.value} to {target.value}")
        record["phase"] = target.value
        record["current_gate"] = next_gate
        return self._persist(f"phase_{target.value}")

    def _cmd_pass_gate(self, *, run_id, gate) -> dict:
        record = self._require_run(run_id)
        if Phase(record["phase"]) not in {Phase.PREFLIGHT, Phase.RUNNING, Phase.AWAITING_USER}:
            raise ConnectionCoordinatorError(
                "CONNECTION_GATE_INVALID", "a gate cannot pass in the current phase")
        passed = _gate(gate)
        if record["last_passed_gate"] == passed and record["current_gate"] == passed:
            return _copy(record)
        record["last_passed_gate"] = passed
        record["current_gate"] = passed
        return self._persist("gate_passed")

    def _cmd_bind_authority(self, *, run_id, room_id, room_version, seat, switch_role) -> dict:
        record = self._require_running(run_id)
        selected_seat = _enum(AuthoritySeat, seat, "authority seat")
        selected_role = _enum(SwitchRole, switch_role, "Switch role")
        updates = {
            "room_id": _bounded(room_id, "room_id", maximum=128),
            "room_version": _positive_int(room_version, "room_version"),
            "authority_seat": selected_seat.value,
            "switch_role": selected_role.value,
            "ldn_role": (LdnRole.STATION if selected_role == SwitchRole.A_ROOM_JOINER else LdnRole.AP).value,
            "tunnel_direction": (
                TunnelDirection.A_TO_B if selected_role == SwitchRole.A_ROOM_JOINER
                else TunnelDirection.B_TO_A).value,
        }
        if not self._bind_once(record["identity"], updates):
            return _copy(record)
        return self._persist("authority_bound")

    def _cmd_acquire_wrapper(self, *, run_id, wrapper_pid, process_start_ticks,
                             adapter_instance_id, usb_id, bus_id) -> dict:
        record = self._require_running(run_id)
        mode = RunMode(record["identity"]["mode"])
        if mode not in _DIRECT_MODES and not record["identity"]["room_id"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_AUTHORITY_REQUIRED", "authority must be bound before P0b")
        updates = {
            "wrapper_pid": _positive_int(wrapper_pid, "wrapper_pid"),
            "process_start_ticks": _positive_int(process_start_ticks, "process_start_ticks"),
            "adapter_instance_id": _bounded(
                adapter_instance_id, "adapter_instance_id", maximum=512),
            "usb_id": _bounded(usb_id, "usb_id", maximum=32).lower(),
            "bus_id": _bounded(bus_id, "bus_id", maximum=64),
        }
        identity = record["identity"]
        if identity["adapter_instance_id"] != updates["adapter_instance_id"] or identity["usb_id"] != updates["usb_id"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_IDENTITY_MISMATCH", "wrapper adapter identity does not match the run")
        if record["ownership"]["wrapper_acquired"]:
            self._assert_bound(identity, updates)
            return _copy(record)
        self._bind_once(identity, updates)
        record["ownership"].update(wrapper_acquired=True, wrapper_count=1)
        return self._persist("wrapper_acquired")

    def _cmd_mark_p0_ready(self, *, run_id, wrapper_pid, process_start_ticks, phy, netdev) -> dict:
        record = self._require_running(run_id)
        if not record["ownership"]["wrapper_acquired"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_WRAPPER_REQUIRED", "the wrapper must be acquired before P0 readiness")
        identity = record["identity"]
        self._assert_bound(identity, {
            "wrapper_pid": _positive_int(wrapper_pid, "wrapper_pid"),
            "process_start_ticks": _positive_int(process_start_ticks, "process_start_ticks"),
        })
        updates = {
            "phy": _bounded(phy, "phy", maximum=64),
            "netdev": _bounded(netdev, "netdev", maximum=64),
        }
        if record["ownership"]["p0_side_ready"]:
            self._assert_bound(identity, updates)
            return _copy(record)
        self._bind_once(identity, updates)
        record["ownership"]["p0_side_ready"] = True
        record["last_passed_gate"] = "P0_SIDE_READY"
        record["current_gate"] = "P0_SIDE_READY"
        return self._persist("p0_side_ready")

    def _cmd_lock_attempt(self, *, run_id, attempt_id, role_lock_version) -> dict:
        record = self._require_running(run_id)
        if not record["identity"]["room_id"] or not record["ownership"]["p0_side_ready"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_P0_REQUIRED", "authority and P0 readiness are required before attempt lock")
        updates = {
            "attempt_id": _bounded(attempt_id, "attempt_id", maximum=128),
            "role_lock_version": _positive_int(role_lock_version, "role_lock_version"),
        }
        if not self._bind_once(record["identity"], updates):
            return _copy(record)
        return self._persist("attempt_locked")

    def _cmd_reserve_endpoint_launch(self, *, run_id, launch_nonce) -> dict:
        record = self._require_running(run_id)
        if not record["ownership"]["p0_side_ready"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_P0_REQUIRED", "P0 readiness is required before endpoint launch")
        if RunMode(record["identity"]["mode"]) not in _DIRECT_MODES and not record["identity"]["attempt_id"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_ATTEMPT_REQUIRED", "a locked attempt is required before endpoint launch")
        nonce = _bounded(launch_nonce, "launch_nonce", maximum=128)
        if len(nonce) < 32:
            raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "launch_nonce is too short")
        if record["ownership"]["launch_reserved"]:
            self._assert_bound(record["identity"], {"launch_nonce": nonce})
            return _copy(record)
        self._bind_once(record["identity"], {"launch_nonce": nonce})
        record["ownership"].update(launch_reserved=True, launch_count=1)
        return self._persist("endpoint_launch_reserved")

    def _cmd_acknowledge_endpoint(self, *, run_id, launch_nonce, endpoint_pid,
                                  process_start_ticks) -> dict:
        record = self._require_running(run_id)
        if not record["ownership"]["launch_reserved"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_LAUNCH_REQUIRED", "endpoint launch must be reserved first")
        identity = record["identity"]
        self._assert_bound(identity, {
            "launch_nonce": _bounded(launch_nonce, "launch_nonce", maximum=128),
        })
        updates = {
            "endpoint_pid": _positive_int(endpoint_pid, "endpoint_pid"),
            "endpoint_start_ticks": _positive_int(process_start_ticks, "process_start_ticks"),
        }
        if record["ownership"]["endpoint_started"]:
            self._assert_bound(identity, updates)
            return _copy(record)
        self._bind_once(identity, updates)
        record["ownership"]["endpoint_started"] = True
        return self._persist("endpoint_started")

    def _cmd_request_cancel(self, *, run_id, code, message) -> dict:
        record = self._require_run(run_id)
        if record["phase"] == Phase.TERMINAL.value:
            return _copy(record)
        if record["cancel_requested"]:
            return _copy(record)
        record["cancel_requested"] = True
        self._set_functional(
            record, FunctionalOutcome.CANCELED, _code(code),
            _bounded(message, "message", maximum=500))
        if Phase(record["phase"]) not in {Phase.CLOSING, Phase.CLEANING}:
            record["phase"] = Phase.CLOSING.value
            record["current_gate"] = "D1_CLOSING_INTENT"
        return self._persist("cancel_requested")

    def _cmd_close_run(self, *, run_id, outcome, code, message) -> dict:
        record = self._require_run(run_id)
        selected = _enum(FunctionalOutcome, outcome, "functional outcome")
        if selected == FunctionalOutcome.PENDING:
            raise ConnectionCoordinatorError(
                "CONNECTION_INPUT_INVALID", "functional outcome cannot remain pending")
        normalized_code = _code(code) if code is not None else None
        normalized_message = _bounded(message, "message", maximum=500, required=False)
        if selected in {FunctionalOutcome.FAILED, FunctionalOutcome.INTERRUPTED} and normalized_code is None:
            raise ConnectionCoordinatorError(
                "CONNECTION_INPUT_INVALID", "failed and interrupted outcomes require a code")
        if record["phase"] == Phase.TERMINAL.value:
            return _copy(record)
        if (record["functional"]["status"] != FunctionalOutcome.PENDING.value and
                Phase(record["phase"]) in {Phase.CLOSING, Phase.CLEANING}):
            return _copy(record)
        self._set_functional(record, selected, normalized_code, normalized_message)
        if Phase(record["phase"]) not in {Phase.CLOSING, Phase.CLEANING}:
            record["phase"] = Phase.CLOSING.value
            record["current_gate"] = "D1_CLOSING_INTENT"
        return self._persist("closing_intent_recorded")

    def _cmd_begin_cleanup(self, *, run_id) -> dict:
        record = self._require_run(run_id)
        if record["phase"] == Phase.CLEANING.value:
            return _copy(record)
        if record["phase"] != Phase.CLOSING.value:
            raise ConnectionCoordinatorError(
                "CONNECTION_TRANSITION_INVALID", "cleanup requires closing intent")
        record["phase"] = Phase.CLEANING.value
        record["current_gate"] = "D8_LOCAL_RELEASE"
        return self._persist("cleanup_started")

    def _cmd_retry_cleanup(self, *, run_id) -> dict:
        record = self._require_run(run_id)
        if record["phase"] == Phase.CLEANING.value:
            return _copy(record)
        if record["phase"] != Phase.TERMINAL.value or record["cleanup"]["verified"]:
            raise ConnectionCoordinatorError(
                "CONNECTION_CLEANUP_RETRY_INVALID", "cleanup retry is not required")
        record["phase"] = Phase.CLEANING.value
        record["current_gate"] = "D8_LOCAL_RELEASE"
        record["cleanup"]["status"] = CleanupOutcome.PENDING.value
        return self._persist("cleanup_retry_started")

    def _cmd_complete_cleanup(self, *, run_id, verified, evidence, code, message) -> dict:
        record = self._require_run(run_id)
        if not isinstance(verified, bool):
            raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "verified must be Boolean")
        normalized_evidence = _evidence(evidence)
        cleanup_code = _code(code) if code is not None else None
        cleanup_message = _bounded(message, "message", maximum=500, required=False)
        if record["phase"] == Phase.TERMINAL.value:
            cleanup = record["cleanup"]
            if (cleanup["verified"] == verified and
                    cleanup["code"] == (None if verified else cleanup_code) and
                    cleanup["message"] == (None if verified else cleanup_message) and
                    cleanup["evidence"] == normalized_evidence):
                return _copy(record)
            raise ConnectionCoordinatorError(
                "CONNECTION_CLEANUP_RESULT_MISMATCH", "terminal cleanup evidence does not match")
        if record["phase"] != Phase.CLEANING.value:
            raise ConnectionCoordinatorError(
                "CONNECTION_TRANSITION_INVALID", "cleanup completion requires cleaning state")
        if record["functional"]["status"] == FunctionalOutcome.PENDING.value:
            raise ConnectionCoordinatorError(
                "CONNECTION_OUTCOME_REQUIRED", "functional outcome is required before terminal cleanup")
        if not verified and cleanup_code is None:
            raise ConnectionCoordinatorError(
                "CONNECTION_INPUT_INVALID", "failed cleanup requires a code")
        failures = list(record["cleanup"].get("failures", []))
        if not verified:
            failures.append({"code": cleanup_code, "message": cleanup_message, "utc": _utc()})
            failures = failures[-16:]
        record["cleanup"] = {
            "status": CleanupOutcome.VERIFIED.value if verified else CleanupOutcome.FAILED.value,
            "verified": verified,
            "code": None if verified else cleanup_code,
            "message": None if verified else cleanup_message,
            "evidence": normalized_evidence,
            "failures": failures,
        }
        record["recovery_required"] = not verified
        record["phase"] = Phase.TERMINAL.value
        record["current_gate"] = "D11_RELEASE" if verified else "D_CLEANUP_FAILED"
        return self._persist("cleanup_verified" if verified else "cleanup_failed")

    def _recover(self) -> None:
        if not self._active_file.exists():
            return
        pointer = self._read_json(self._active_file)
        if pointer.get("contract_version") != CONTRACT_VERSION:
            raise ConnectionCoordinatorError(
                "CONNECTION_RECOVERY_STATE_INVALID", "active connection pointer is invalid")
        run_id = self._run_id(pointer.get("run_id"))
        record = self._read_json(self._record_path(run_id))
        self._validate_record(record, run_id)
        self._current = record
        if record["phase"] == Phase.TERMINAL.value and record["cleanup"]["verified"]:
            self._active_file.unlink(missing_ok=True)
            return
        if record["functional"]["status"] == FunctionalOutcome.PENDING.value:
            record["functional"] = {
                "status": FunctionalOutcome.INTERRUPTED.value,
                "code": "CONNECTION_RUN_INTERRUPTED",
                "message": "The previous control process ended before the run became terminal.",
            }
        record["phase"] = Phase.CLEANING.value
        record["current_gate"] = "D8_LOCAL_RELEASE"
        record["cleanup"].update(
            status=CleanupOutcome.PENDING.value, verified=False,
            code=None, message=None)
        record["recovery_required"] = True
        self._persist("startup_recovery_required")

    def _persist(self, event: str) -> dict:
        record = self._current
        if record is None:
            raise ConnectionCoordinatorError("CONNECTION_RUN_NOT_FOUND", "connection run not found")
        record["revision"] += 1
        record["updated_utc"] = _utc()
        record["history"].append({
            "revision": record["revision"], "event": event,
            "phase": record["phase"], "gate": record["current_gate"],
            "utc": record["updated_utc"],
        })
        record["history"] = record["history"][-MAX_HISTORY:]
        self._write_json(self._record_path(record["run_id"]), record)
        if record["phase"] == Phase.TERMINAL.value and record["cleanup"]["verified"]:
            self._active_file.unlink(missing_ok=True)
        else:
            self._write_json(self._active_file, {
                "contract_version": CONTRACT_VERSION,
                "schema": SCHEMA_VERSION,
                "run_id": record["run_id"],
            })
        return _copy(record)

    def _has_cleanup_guard(self) -> bool:
        return self._active_file.exists() or bool(
            self._current and not (
                self._current["phase"] == Phase.TERMINAL.value and
                self._current["cleanup"]["verified"]))

    def _require_run(self, run_id: str) -> dict:
        normalized = self._run_id(run_id)
        if self._current is None or self._current["run_id"] != normalized:
            raise ConnectionCoordinatorError("CONNECTION_RUN_NOT_FOUND", "connection run not found")
        return self._current

    def _require_running(self, run_id: str) -> dict:
        record = self._require_run(run_id)
        if record["phase"] != Phase.RUNNING.value:
            raise ConnectionCoordinatorError(
                "CONNECTION_TRANSITION_INVALID", "the run is not in running state")
        return record

    @staticmethod
    def _set_functional(record: dict, outcome: FunctionalOutcome,
                        code: str | None, message: str | None) -> None:
        current = FunctionalOutcome(record["functional"]["status"])
        if current == FunctionalOutcome.PENDING:
            record["functional"] = {"status": outcome.value, "code": code, "message": message}

    @staticmethod
    def _bind_once(identity: dict, updates: dict) -> bool:
        changed = False
        for key, value in updates.items():
            current = identity.get(key)
            if current is not None and current != value:
                raise ConnectionCoordinatorError(
                    "CONNECTION_IDENTITY_MISMATCH", f"{key} does not match the bound run identity")
            if current is None:
                identity[key] = value
                changed = True
        return changed

    @staticmethod
    def _assert_bound(identity: dict, expected: dict) -> None:
        for key, value in expected.items():
            if identity.get(key) != value:
                raise ConnectionCoordinatorError(
                    "CONNECTION_IDENTITY_MISMATCH", f"{key} does not match the bound run identity")

    def _record_path(self, run_id: str) -> Path:
        return self.root / run_id / "connection-run.json"

    @staticmethod
    def _run_id(value: object) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ConnectionCoordinatorError("CONNECTION_INPUT_INVALID", "run_id is invalid") from error

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ConnectionCoordinatorError(
                "CONNECTION_RECOVERY_STATE_INVALID", "persisted connection state is unreadable") from error
        if not isinstance(value, dict):
            raise ConnectionCoordinatorError(
                "CONNECTION_RECOVERY_STATE_INVALID", "persisted connection state is invalid")
        return value

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    @staticmethod
    def _validate_record(value: dict, run_id: str) -> None:
        identity = value.get("identity")
        ownership = value.get("ownership")
        functional = value.get("functional")
        cleanup = value.get("cleanup")
        valid = (
            value.get("contract_version") == CONTRACT_VERSION and
            value.get("schema") == SCHEMA_VERSION and value.get("run_id") == run_id and
            value.get("phase") in {item.value for item in Phase} and
            isinstance(value.get("revision"), int) and value.get("revision", 0) >= 1 and
            isinstance(value.get("history"), list) and
            isinstance(identity, dict) and identity.get("mode") in {item.value for item in RunMode} and
            isinstance(ownership, dict) and
            all(isinstance(ownership.get(key), bool) for key in (
                "wrapper_acquired", "p0_side_ready", "launch_reserved", "endpoint_started")) and
            all(ownership.get(key) in {0, 1} for key in ("wrapper_count", "launch_count")) and
            isinstance(functional, dict) and
            functional.get("status") in {item.value for item in FunctionalOutcome} and
            isinstance(cleanup, dict) and
            cleanup.get("status") in {item.value for item in CleanupOutcome} and
            isinstance(cleanup.get("verified"), bool) and isinstance(cleanup.get("evidence"), dict) and
            isinstance(cleanup.get("failures"), list)
        )
        if not valid:
            raise ConnectionCoordinatorError(
                "CONNECTION_RECOVERY_STATE_INVALID", "persisted connection state is invalid")


__all__ = [
    "AuthoritySeat", "CleanupOutcome", "ConnectionCoordinator",
    "ConnectionCoordinatorError", "CONTRACT_VERSION", "FunctionalOutcome", "LdnRole", "Phase",
    "RfuRole", "RunMode", "SwitchRole", "TunnelDirection",
]
