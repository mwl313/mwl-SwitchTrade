"""Headless production owner for one deterministic ABC+D connection run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from typing import Callable
import uuid

from switchtrade.connection.p0 import atomic_json
from switchtrade.session_evidence import ApplicationEvidence


CONTRACT = "production-connection-run.v1"
TERMINAL_PHASE = "terminal"
TERMINAL_ACTIONS = {"stop", "end", "leave", "close"}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _copy(value):
    return json.loads(json.dumps(value))


def _uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise ConnectionRunServiceError("COMMAND_ID_INVALID", f"{name} must be a UUID") from error


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _failure(value: dict | None, *, component: str = "connection") -> dict | None:
    if not isinstance(value, dict):
        return None
    gate = str(value.get("gate") or value.get("stage") or "unknown")[:96]
    return {
        "component": str(value.get("component") or component)[:96],
        "stage": str(value.get("stage") or gate)[:96],
        "gate": gate,
        "code": str(value.get("code") or "CONNECTION_FAILED")[:96],
        "message": str(value.get("message") or "connection failed")[:500],
    }


class ConnectionRunServiceError(RuntimeError):
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


class RunControl:
    """In-memory, identity-bound endpoint command channel; never reads console or files."""

    def __init__(self, run_id: str, publish: Callable[[str, dict], None]):
        self.run_id = run_id
        self._publish = publish
        self._condition = threading.Condition()
        self._checkpoint: str | None = None
        self._continued: set[str] = set()
        self._termination: str | None = None
        self._role: str | None = None
        self._cleanup = False
        self._heartbeat = time.monotonic()
        self._endpoint_started = False
        self._authority_fingerprint: str | None = None

    @property
    def termination(self) -> str | None:
        with self._condition:
            return self._termination

    @property
    def heartbeat_age(self) -> float:
        with self._condition:
            return time.monotonic() - self._heartbeat

    @property
    def endpoint_started(self) -> bool:
        with self._condition:
            return self._endpoint_started

    def heartbeat(self, gate: str) -> None:
        with self._condition:
            self._heartbeat = time.monotonic()

    def authority(self, room: dict) -> None:
        fingerprint = _fingerprint(room)
        with self._condition:
            if self._authority_fingerprint == fingerprint:
                return
            self._authority_fingerprint = fingerprint
        self._publish("authority", {"room": room})

    def mark_endpoint_started(self, identity: dict) -> None:
        with self._condition:
            self._endpoint_started = True
            self._heartbeat = time.monotonic()
        self._publish("endpoint", {"identity": identity})

    def choose_role(self, role: str, *, publish: bool = True) -> None:
        if role not in {"a_room_joiner", "b_ap_host"}:
            raise ConnectionRunServiceError("ROLE_INVALID", "Switch role is invalid")
        with self._condition:
            if self._role is not None and self._role != role:
                raise ConnectionRunServiceError("ROLE_LOCKED", "Switch role is already selected")
            self._role = role
            self._condition.notify_all()
        if publish:
            self._publish("role", {"role": role})

    def wait_for_role(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._role is None:
                if self._termination == "stop":
                    raise ConnectionRunServiceError("CONNECTION_CANCELED", "connection was stopped")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConnectionRunServiceError("ROLE_TIMEOUT", "Switch role was not selected")
                self._condition.wait(min(remaining, 0.5))
            return self._role

    def phase(self, phase: str, *, gate: str | None = None,
              last_passed_gate: str | None = None, peer_state: str | None = None) -> None:
        self._publish("phase", {
            "phase": phase, "gate": gate,
            "last_passed_gate": last_passed_gate, "peer_state": peer_state,
        })

    def await_user(self, checkpoint: str, instructions: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            self._checkpoint = checkpoint
            self._publish("checkpoint", {
                "checkpoint": checkpoint, "instructions": instructions,
                "deadline_utc": datetime.fromtimestamp(
                    time.time() + timeout, timezone.utc).isoformat().replace("+00:00", "Z"),
            })
            while checkpoint not in self._continued:
                if self._termination == "stop":
                    raise ConnectionRunServiceError("CONNECTION_CANCELED", "connection was stopped")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConnectionRunServiceError(
                        "USER_CHECKPOINT_TIMEOUT", f"checkpoint {checkpoint} timed out")
                self._condition.wait(min(remaining, 0.5))
            self._continued.remove(checkpoint)
            self._checkpoint = None
        self._publish("checkpoint_cleared", {"checkpoint": checkpoint})

    def continue_checkpoint(self, checkpoint: str) -> None:
        with self._condition:
            if self._checkpoint != checkpoint:
                raise ConnectionRunServiceError(
                    "CHECKPOINT_STALE", "the user checkpoint is no longer active")
            self._continued.add(checkpoint)
            self._condition.notify_all()

    def request_termination(self, action: str) -> None:
        if action not in TERMINAL_ACTIONS:
            raise ConnectionRunServiceError("COMMAND_INVALID", "unsupported connection action")
        with self._condition:
            if self._cleanup:
                raise ConnectionRunServiceError(
                    "CLEANUP_IN_PROGRESS", "connection cleanup is already in progress")
            if self._termination is not None and self._termination != action:
                raise ConnectionRunServiceError(
                    "COMMAND_CONFLICT", "a different terminal action is already pending")
            self._termination = action
            self._condition.notify_all()
        self._publish("termination_requested", {"action": action})

    def wait_for_termination(self, timeout: float, heartbeat=None) -> str:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._termination is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConnectionRunServiceError(
                        "TERMINATION_TIMEOUT", "connection action was not confirmed")
                self._condition.wait(min(remaining, 1.0))
                if heartbeat is not None:
                    heartbeat()
            return self._termination

    def begin_cleanup(self) -> None:
        with self._condition:
            self._cleanup = True
            self._checkpoint = None
            self._condition.notify_all()
        self._publish("cleanup_started", {})


Runner = Callable[[str, dict, RunControl], dict]
Recovery = Callable[[dict], dict]


class ConnectionRunService:
    """Serialized production facade over the proven connection executor."""

    def __init__(self, root: str | Path, runner: Runner, *, recovery: Recovery | None = None,
                 heartbeat_timeout: float = 10.0, command_timeout: float = 10.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "connection-service-state.json"
        self.runner = runner
        self.recovery = recovery
        self.heartbeat_timeout = heartbeat_timeout
        self.command_timeout = command_timeout
        self.evidence = ApplicationEvidence.from_environment("connection-service")
        self._condition = threading.Condition(threading.RLock())
        self._queue: queue.Queue[_Command | None] = queue.Queue()
        self._record = self._load()
        self._controls: dict[str, RunControl] = {}
        self._closed = False
        self._thread = threading.Thread(
            target=self._command_loop, name="switchtrade-connection-service", daemon=True)
        self._thread.start()
        with self._condition:
            self._recover_startup()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
        current = self.snapshot()
        cleanup_complete = current is None or current["phase"] == TERMINAL_PHASE
        if not cleanup_complete:
            with self._condition:
                control = self._controls.get(current["run_id"])
                already_stopping = control is not None and control.termination is not None
            if not already_stopping:
                try:
                    self.command(
                        command_id=str(uuid.uuid4()), run_id=current["run_id"],
                        expected_revision=current["revision"], action="stop")
                except ConnectionRunServiceError:
                    pass
            deadline = time.monotonic() + self.command_timeout
            while time.monotonic() < deadline:
                current = self.snapshot()
                if current is None or current["phase"] == TERMINAL_PHASE:
                    cleanup_complete = True
                    break
                time.sleep(0.05)
        with self._condition:
            self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=self.command_timeout)
        if self._thread.is_alive():
            raise ConnectionRunServiceError(
                "SERVICE_STOP_TIMEOUT", "connection service did not stop")
        if cleanup_complete:
            close = getattr(self.runner, "close", None)
            if callable(close):
                close()
        else:
            if self.evidence is not None:
                self.evidence.event(
                    "service_cleanup_timeout", run_id=current["run_id"],
                    gate=current.get("current_gate"), code="SERVICE_CLEANUP_TIMEOUT")
            raise ConnectionRunServiceError(
                "SERVICE_CLEANUP_TIMEOUT", "connection cleanup did not finish before shutdown")

    def __enter__(self) -> "ConnectionRunService":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def start(self, *, command_id: str, expected_revision: int, request: dict) -> dict:
        return self._submit("start", command_id=command_id,
                            expected_revision=expected_revision, request=request)

    def command(self, *, command_id: str, run_id: str, expected_revision: int,
                action: str, checkpoint: str | None = None,
                switch_role: str | None = None) -> dict:
        return self._submit(
            "command", command_id=command_id, run_id=run_id,
            expected_revision=expected_revision, action=action, checkpoint=checkpoint,
            switch_role=switch_role)

    def retry(self, *, command_id: str, run_id: str, expected_revision: int) -> dict:
        return self._submit(
            "retry", command_id=command_id, run_id=run_id,
            expected_revision=expected_revision)

    def shutdown(self, *, command_id: str, run_id: str | None,
                 expected_revision: int) -> dict:
        return self._submit(
            "shutdown", command_id=command_id, run_id=run_id,
            expected_revision=expected_revision)

    def snapshot(self, run_id: str | None = None) -> dict | None:
        """Pure immutable projection: no heartbeat, recovery, retry, launch, or USB work."""
        with self._condition:
            if self._record is None or (run_id is not None and self._record["run_id"] != run_id):
                return None
            return _copy(self._project(self._record))

    def wait_for_authority(self, run_id: str, timeout: float = 30.0) -> dict:
        """Wait on state publication only; this never launches or mutates connection work."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._record is None or self._record["run_id"] != run_id:
                    raise ConnectionRunServiceError("RUN_NOT_FOUND", "connection run was not found")
                if self._record.get("room") is not None:
                    return _copy(self._project(self._record))
                failure = self._record["functional"].get("failure")
                if failure is not None:
                    raise ConnectionRunServiceError(failure["code"], failure["message"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConnectionRunServiceError(
                        "AUTHORITY_TIMEOUT", "relay room authority was not established")
                self._condition.wait(min(remaining, 0.5))

    def _submit(self, operation: str, **arguments) -> dict:
        with self._condition:
            if self._closed:
                raise ConnectionRunServiceError("SERVICE_STOPPED", "connection service is stopped")
        command = _Command(operation, arguments)
        self._queue.put(command)
        if not command.done.wait(self.command_timeout):
            raise ConnectionRunServiceError("COMMAND_TIMEOUT", "connection command timed out")
        if command.error is not None:
            raise command.error
        return _copy(command.result or {})

    def _submit_internal(self, operation: str, **arguments) -> None:
        if self._closed:
            return
        self._queue.put(_Command(operation, arguments))

    def _command_loop(self) -> None:
        while True:
            command = self._queue.get()
            if command is None:
                return
            try:
                handler = getattr(self, f"_cmd_{command.operation}")
                with self._condition:
                    command.result = handler(**command.arguments)
            except BaseException as error:
                command.error = error
            finally:
                command.done.set()

    def _cmd_start(self, *, command_id: str, expected_revision: int, request: dict) -> dict:
        payload = {"operation": "start", "request": request,
                   "expected_revision": expected_revision}
        if cached := self._idempotent(command_id, payload):
            return cached
        if self._record is not None and (
                self._record["phase"] != TERMINAL_PHASE or
                self._record["cleanup"]["status"] != "verified"):
            raise ConnectionRunServiceError(
                "CONNECTION_RUN_ACTIVE", "another run or unresolved cleanup owns the service")
        if expected_revision != (0 if self._record is None else self._record["revision"]):
            raise ConnectionRunServiceError("REVISION_STALE", "the UI revision is stale")
        normalized = self._validate_request(request)
        run_id = str(uuid.uuid4())
        prior_commands = {} if self._record is None else _copy(self._record.get("commands", {}))
        self._record = {
            "contract_version": CONTRACT, "schema": 1, "run_id": run_id,
            "revision": expected_revision + 1, "phase": "created",
            "current_gate": None, "last_passed_gate": None,
            "local_role": normalized["switch_role"], "peer_state": "waiting",
            "user_checkpoint": None, "request": normalized,
            "functional": {"status": "pending", "failure": None},
            "cleanup": {"status": "pending", "verified": False, "failures": []},
            "created_utc": _utc(), "updated_utc": _utc(),
            "commands": prior_commands, "endpoint": None, "room": None,
        }
        control = RunControl(run_id, lambda event, value: self._submit_internal(
            "event", run_id=run_id, event=event, value=value))
        self._controls[run_id] = control
        self._persist("run_created")
        result = self._project(self._record)
        self._remember(command_id, payload, result)
        threading.Thread(
            target=self._run, args=(run_id, normalized, control),
            name=f"switchtrade-run-{run_id[:8]}", daemon=True).start()
        return result

    def _cmd_command(self, *, command_id: str, run_id: str, expected_revision: int,
                     action: str, checkpoint: str | None, switch_role: str | None) -> dict:
        payload = {"operation": "command", "run_id": run_id, "action": action,
                   "checkpoint": checkpoint, "switch_role": switch_role,
                   "expected_revision": expected_revision}
        if cached := self._idempotent(command_id, payload):
            return cached
        record = self._require(run_id, expected_revision)
        if action not in self._project(record)["allowed_actions"]:
            raise ConnectionRunServiceError(
                "ACTION_NOT_ALLOWED", "the action is not allowed in the current run state")
        control = self._controls.get(run_id)
        if record["phase"] == TERMINAL_PHASE and action in {"leave", "close"}:
            release = getattr(self.runner, "release_authority", None)
            if not callable(release):
                raise ConnectionRunServiceError(
                    "AUTHORITY_RELEASE_UNAVAILABLE", "room authority cannot be released")
            release(action)
            record["room"] = None
        elif control is None:
            raise ConnectionRunServiceError("RUN_NOT_ACTIVE", "connection run is not active")
        elif action == "continue":
            if not checkpoint or record["user_checkpoint"] is None:
                raise ConnectionRunServiceError("CHECKPOINT_STALE", "no user checkpoint is active")
            control.continue_checkpoint(checkpoint)
        elif action == "connect":
            control.choose_role(switch_role or "", publish=False)
            record["local_role"] = switch_role
        else:
            control.request_termination(action)
        record["revision"] += 1
        record["updated_utc"] = _utc()
        self._persist("command_accepted")
        result = self._project(record)
        self._remember(command_id, payload, result)
        return result

    def _cmd_retry(self, *, command_id: str, run_id: str, expected_revision: int) -> dict:
        payload = {"operation": "retry", "run_id": run_id,
                   "expected_revision": expected_revision}
        if cached := self._idempotent(command_id, payload):
            return cached
        record = self._require(run_id, expected_revision)
        if record["phase"] != TERMINAL_PHASE or record["cleanup"]["verified"] is not True:
            raise ConnectionRunServiceError(
                "CLEANUP_UNVERIFIED", "retry requires verified cleanup")
        request = _copy(record["request"])
        if record.get("room") is not None:
            request = {
                "kind": "resume",
                "switch_role": request.get("switch_role"),
                "client_id": request.get("client_id"),
            }
        result = self._cmd_start(
            command_id=str(uuid.uuid5(uuid.UUID(command_id), "retry-run")),
            expected_revision=record["revision"], request=request)
        self._remember(command_id, payload, result)
        return result

    def _cmd_shutdown(self, *, command_id: str, run_id: str | None,
                      expected_revision: int) -> dict:
        payload = {"operation": "shutdown", "run_id": run_id,
                   "expected_revision": expected_revision}
        command_id = _uuid(command_id, "command_id")
        if cached := self._idempotent(command_id, payload):
            return cached
        if self._record is None:
            if run_id is not None or expected_revision != 0:
                raise ConnectionRunServiceError("REVISION_STALE", "the UI revision is stale")
            return {"status": "accepted", "run_id": None, "revision": 0}
        record = self._require(run_id or "", expected_revision)
        if record["phase"] != TERMINAL_PHASE:
            control = self._controls.get(record["run_id"])
            if control is None:
                raise ConnectionRunServiceError("RUN_NOT_ACTIVE", "connection run is not active")
            control.request_termination("stop")
        record["revision"] += 1
        record["updated_utc"] = _utc()
        self._persist("shutdown_accepted")
        result = self._project(record)
        self._remember(command_id, payload, result)
        return result

    def _cmd_event(self, *, run_id: str, event: str, value: dict) -> dict:
        if self._record is None or self._record["run_id"] != run_id:
            return {}
        record = self._record
        if event == "phase":
            record["phase"] = value.get("phase") or record["phase"]
            record["current_gate"] = value.get("gate")
            record["last_passed_gate"] = value.get("last_passed_gate") or record["last_passed_gate"]
            record["peer_state"] = value.get("peer_state") or record["peer_state"]
        elif event == "checkpoint":
            record["phase"] = "awaiting_user"
            record["user_checkpoint"] = value
        elif event == "checkpoint_cleared":
            record["phase"] = "running"
            record["user_checkpoint"] = None
        elif event == "cleanup_started":
            record["phase"] = "cleaning"
            record["user_checkpoint"] = None
            record["cleanup"]["status"] = "running"
        elif event == "authority":
            room = value.get("room")
            if not isinstance(room, dict):
                raise ConnectionRunServiceError(
                    "AUTHORITY_INVALID", "relay authority projection is invalid")
            record["room"] = room
        elif event == "role":
            record["local_role"] = value.get("role")
        elif event == "endpoint":
            record["endpoint"] = value.get("identity")
        elif event == "watchdog_failed":
            if record["functional"]["failure"] is None:
                record["functional"]["failure"] = _failure(
                    value.get("failure"), component="endpoint")
        record["revision"] += 1
        record["updated_utc"] = _utc()
        self._persist(event)
        self._condition.notify_all()
        return self._project(record)

    def _cmd_finished(self, *, run_id: str, report: dict | None,
                      failure: dict | None) -> dict:
        if self._record is None or self._record["run_id"] != run_id:
            return {}
        record = self._record
        if failure is not None and record["functional"]["failure"] is None:
            record["functional"]["failure"] = _failure(failure, component="connection-service")
        report_failure = (report or {}).get("primary_failure")
        if report_failure is not None and record["functional"]["failure"] is None:
            record["functional"]["failure"] = _failure(report_failure)
        functional = (report or {}).get("functional_status") or (
            "failed" if record["functional"]["failure"] else "interrupted")
        if record["functional"]["failure"] is not None and functional == "canceled":
            functional = "failed"
        cleanup_status = (report or {}).get("cleanup_status") or "failed"
        record["functional"]["status"] = functional
        record["cleanup"]["status"] = cleanup_status
        record["cleanup"]["verified"] = cleanup_status == "verified"
        room_finalization = (((report or {}).get("cleanup") or {}).get("distributed") or {}).get(
            "room_finalization")
        if room_finalization in {"room_closed", "member_left"}:
            record["room"] = None
        if not record["cleanup"]["verified"]:
            record["cleanup"]["failures"].append({
                "code": "CLEANUP_UNVERIFIED", "message": "cleanup was not verified"})
        record["phase"] = TERMINAL_PHASE if record["cleanup"]["verified"] else "cleaning"
        record["revision"] += 1
        record["updated_utc"] = _utc()
        self._controls.pop(run_id, None)
        self._persist("run_finished")
        if self.evidence is not None:
            self.evidence.write_failure_summary({
                "run_id": run_id,
                "attempt_id": ((record.get("endpoint") or {}).get("attempt_id") or
                               "not-created"),
                "release_id": (record.get("request") or {}).get("release") or "unknown",
                "last_passed_gate": record.get("last_passed_gate") or "none",
                "primary_failure": record["functional"].get("failure"),
                "endpoint_identity": record.get("endpoint"),
                "functional_outcome": record["functional"]["status"],
                "cleanup": record["cleanup"],
                "startup_recovery": {"required": False},
                "evidence": ([] if not (report or {}).get("report_path") else
                             [report["report_path"]]),
            })
        return self._project(record)

    def _run(self, run_id: str, request: dict, control: RunControl) -> None:
        report = None
        failure = None
        finished = threading.Event()

        def watchdog() -> None:
            while not finished.wait(0.25):
                if not control.endpoint_started or control.heartbeat_age < self.heartbeat_timeout:
                    continue
                value = {
                    "component": "endpoint", "stage": "supervision",
                    "gate": "ENDPOINT_HEARTBEAT", "code": "ENDPOINT_HEARTBEAT_TIMEOUT",
                    "message": "identity-bound endpoint heartbeat stopped",
                }
                self._submit_internal(
                    "event", run_id=run_id, event="watchdog_failed",
                    value={"failure": value})
                try:
                    control.request_termination("stop")
                except ConnectionRunServiceError:
                    pass
                return

        monitor = threading.Thread(
            target=watchdog, name=f"switchtrade-watchdog-{run_id[:8]}", daemon=True)
        monitor.start()
        try:
            control.phase("preflight", gate="P0a_release")
            report = self.runner(run_id, request, control)
            if not isinstance(report, dict):
                raise ConnectionRunServiceError(
                    "RUNNER_RESULT_INVALID", "connection executor returned invalid evidence")
        except Exception as error:
            failure = {
                "component": "connection-service",
                "stage": getattr(error, "gate", "connection"),
                "gate": getattr(error, "gate", "unknown"),
                "code": getattr(error, "code", "CONNECTION_INTERNAL_ERROR"),
                "message": getattr(error, "message", type(error).__name__),
            }
            recover = getattr(self.runner, "recover_failed_run", None)
            if callable(recover):
                try:
                    recovered = recover({"run_id": run_id, "failure": failure})
                except Exception:
                    recovered = {"cleanup_verified": False}
                report = {
                    "functional_status": "failed",
                    "cleanup_status": (
                        "verified" if recovered.get("cleanup_verified") is True else "failed"),
                }
        finally:
            finished.set()
            monitor.join(timeout=1)
            control.begin_cleanup()
            self._submit_internal("finished", run_id=run_id, report=report, failure=failure)

    def _recover_startup(self) -> None:
        if self._record is None or self._record["phase"] == TERMINAL_PHASE:
            return
        previous = _copy(self._record)
        try:
            result = self.recovery(previous) if self.recovery is not None else {
                "status": "failed", "cleanup_verified": False,
            }
        except Exception as error:
            result = {
                "status": "failed", "cleanup_verified": False,
                "code": getattr(error, "code", "STARTUP_RECOVERY_FAILED"),
            }
        if result.get("cleanup_verified") is True:
            self._record["phase"] = TERMINAL_PHASE
            self._record["functional"] = {
                "status": "interrupted", "failure": {
                    "component": "connection-service", "stage": "startup_recovery",
                    "gate": self._record.get("current_gate") or "unknown",
                    "code": "CONNECTION_RUN_INTERRUPTED",
                    "message": "the previous application session ended during a connection",
                },
            }
            self._record["cleanup"] = {"status": "verified", "verified": True, "failures": []}
        else:
            self._record["phase"] = "cleaning"
            self._record["cleanup"] = {
                "status": "failed", "verified": False,
                "failures": [{"code": "CLEANUP_UNVERIFIED",
                              "message": "startup recovery could not prove cleanup"}],
            }
        self._record["revision"] += 1
        self._record["updated_utc"] = _utc()
        self._persist("startup_recovery")

    def _require(self, run_id: str, expected_revision: int) -> dict:
        if self._record is None or self._record["run_id"] != _uuid(run_id, "run_id"):
            raise ConnectionRunServiceError("RUN_NOT_FOUND", "connection run was not found")
        if self._record["revision"] != expected_revision:
            raise ConnectionRunServiceError("REVISION_STALE", "the UI revision is stale")
        return self._record

    @staticmethod
    def _validate_request(request: dict) -> dict:
        if not isinstance(request, dict):
            raise ConnectionRunServiceError("REQUEST_INVALID", "connection request is invalid")
        kind = request.get("kind")
        role = request.get("switch_role")
        if kind not in {"create", "join", "public_join", "resume"} or role not in {
                None, "a_room_joiner", "b_ap_host"}:
            raise ConnectionRunServiceError("REQUEST_INVALID", "connection request is invalid")
        value = _copy(request)
        value["kind"] = kind
        value["switch_role"] = role
        return value

    def _idempotent(self, command_id: str, payload: dict) -> dict | None:
        command_id = _uuid(command_id, "command_id")
        if self._record is None:
            return None
        existing = self._record.get("commands", {}).get(command_id)
        if existing is None:
            return None
        if existing["fingerprint"] != _fingerprint(payload):
            raise ConnectionRunServiceError(
                "COMMAND_ID_CONFLICT", "command ID was reused with different content")
        return _copy(existing["result"])

    def _remember(self, command_id: str, payload: dict, result: dict) -> None:
        command_id = _uuid(command_id, "command_id")
        commands = self._record.setdefault("commands", {})
        commands[command_id] = {"fingerprint": _fingerprint(payload), "result": _copy(result)}
        while len(commands) > 128:
            commands.pop(next(iter(commands)))
        self._persist("command_recorded")

    @staticmethod
    def _project(record: dict) -> dict:
        phase = record["phase"]
        cleanup_verified = record["cleanup"]["verified"]
        actions = []
        if phase in {"created", "preflight", "running", "awaiting_user"}:
            actions.append("stop")
        if record.get("room") is not None and record.get("local_role") is None and phase in {
                "preflight", "running"}:
            actions.append("connect")
        if phase == "awaiting_user":
            actions.append("continue")
        if phase == "running":
            actions.extend(["end", "leave", "close"])
        if phase == TERMINAL_PHASE and cleanup_verified:
            actions.append("retry")
            room = record.get("room") or {}
            if room.get("membership_role") == "owner":
                actions.append("close")
            elif room.get("membership_role") == "member":
                actions.append("leave")
        return {
            key: _copy(record[key]) for key in (
                "contract_version", "schema", "run_id", "revision", "phase",
                "current_gate", "last_passed_gate", "local_role", "peer_state",
                "user_checkpoint", "functional", "cleanup", "created_utc", "updated_utc")
        } | {"room": _copy(record.get("room")), "allowed_actions": actions}

    def _persist(self, event: str) -> None:
        if self._record is None:
            return
        atomic_json(self.state_path, self._record, private=True)
        self._condition.notify_all()
        if self.evidence is not None:
            failure = self._record["functional"].get("failure")
            self.evidence.event(
                event, run_id=self._record["run_id"],
                gate=self._record.get("current_gate"),
                code=None if failure is None else failure.get("code"),
                phase=self._record["phase"], revision=self._record["revision"])

    def _load(self) -> dict | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise ConnectionRunServiceError(
                "SERVICE_STATE_INVALID", "connection service state is invalid") from error
        if not isinstance(value, dict) or value.get("contract_version") != CONTRACT:
            raise ConnectionRunServiceError(
                "SERVICE_STATE_INVALID", "connection service state is invalid")
        return value
