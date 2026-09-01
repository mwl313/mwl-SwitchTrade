"""Local SwitchTrade control API for the desktop UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import base64
import hashlib
import os
import json
import re
import subprocess
import threading
import time
import signal
import secrets
import sys
import uuid
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from switchtrade import __version__
from switchtrade.diagnostics import RunLogger, default_runs_root, redact_text
from switchtrade.endpoint import runtime_plan
from switchtrade.hardware import DEFAULT_PROFILE_PATH, host_engines_public, load_profiles
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
from switchtrade.production_diagnostics import (
    AP_FIXTURE, DIAGNOSTIC_CONTRACT, DEFINITIONS, DiagnosticD7Resources, DiagnosticFailure,
    ProductionDiagnostics, SyntheticDiagnosticPeer, TIMEOUTS, diagnostic_member_pair,
    fixture_metadata,
)
from switchtrade.connection.production_run import ProductionRunner
from switchtrade.connection.service import (
    ConnectionRunService, ConnectionRunServiceError,
)
from switchtrade.relay_client import RelayClient, RelayError
from switchtrade.session_evidence import ApplicationEvidence


READINESS_CONTRACT = "app-readiness.v1"
PRODUCTION_READINESS_CONTRACT = "local-app-readiness.v2"


class RelayReadinessMonitor:
    """Lifespan-owned relay capability probe; HTTP GET handlers only read its snapshot."""

    def __init__(self, probe, *, success_interval: float = 30.0,
                 failure_interval: float = 5.0):
        self._probe = probe
        self._success_interval = success_interval
        self._failure_interval = failure_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready: bool | None = None
        self._thread = threading.Thread(
            target=self._run, name="switchtrade-relay-readiness", daemon=True)
        self._thread.start()

    def snapshot(self) -> bool | None:
        with self._lock:
            return self._ready

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=6)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                health = self._probe()
                ready = (
                    health.get("status") == "ready" and
                    "rfu-tunnel.v2" in health.get("rfu_contracts", []))
            except (RelayError, OSError, ValueError, TypeError):
                ready = False
            with self._lock:
                self._ready = ready
            self._stop.wait(
                self._success_interval if ready else self._failure_interval)
ROOM_CONTRACT = "room-control.v1"
PARTY_CONTRACT = "party-commit.v1"
PUBLIC_DIRECTORY_CONTRACT = "public-directory.v1"
RFU_CONTRACT = "rfu-tunnel.v1"
LINUX_RADIO_ATTACH_TIMEOUT_SECONDS = 30
LINUX_USB_ENUMERATION_TIMEOUT_SECONDS = 8
LINUX_RADIO_CLEANUP_TIMEOUT_SECONDS = 8
LINUX_DRIVER_QUIESCE_TIMEOUT_SECONDS = 20
LINUX_DRIVER_PREPARE_TIMEOUT_SECONDS = 40

ATTEMPT_FAILURES = {
    "relay.peer_lost": ("relay", True, "retry"),
    "relay.restart": ("relay", True, "retry"),
    "member.reconnect_expired": ("coordination", True, "wait_for_partner"),
    "radio.switch_room_not_found": ("radio", True, "recreate_switch_room"),
    "radio.failed": ("radio", True, "recheck_adapter"),
    "session.failed": ("session", True, "retry"),
    "cleanup.failed": ("cleanup", True, "restart_backend"),
}

ATTEMPT_FAILURE_MESSAGES = {
    "relay.peer_lost": "The partner connection was lost.",
    "relay.restart": "The online relay restarted during the connection.",
    "member.reconnect_expired": "The partner did not reconnect in time.",
    "radio.switch_room_not_found": (
        "The Group Leader's Switch room was not found on the supported 2.4 GHz channels."
    ),
    "radio.failed": "The partner's local Switch radio failed.",
    "session.failed": "The partner's Switch connection failed.",
    "cleanup.failed": "The partner's local connection did not shut down cleanly.",
}

TERMINAL_ATTEMPT_PHASES = {"completed", "canceled", "failed"}
ENDPOINT_STARTUP_TIMEOUT_SECONDS = 45.0

LOCAL_ERROR_CODES = {
    "no active trade room": ("room_not_active", "room", False, "return_home"),
    "no active authoritative trade room": ("room_not_active", "room", False, "return_home"),
    "both trainers must choose their Switch role before connecting": (
        "waiting_for_partner_role", "coordination", True, "wait"),
    "one trainer must choose Group Leader and the other must choose Joining": (
        "complementary_role_required", "coordination", True, "choose_role"),
    "the two Switch role choices do not match": (
        "role_choice_conflict", "coordination", True, "choose_role"),
    "the online room service must be updated for manual Switch roles": (
        "relay_contract_incompatible", "relay", False, "update"),
    "a session is already running": ("session_active", "session", True, "end_session"),
    "Select an available Wi-Fi adapter in Settings": (
        "adapter_selection_required", "hardware", True, "select_adapter"),
    "The selected adapter is no longer connected": (
        "adapter_disconnected", "hardware", True, "select_adapter"),
    "This adapter is quarantined and cannot trade": (
        "adapter_quarantined", "hardware", False, "select_adapter"),
    "End the current connection before changing adapters": (
        "session_active", "hardware", True, "end_session"),
    "Windows must authorize the selected adapter before SwitchTrade can use it": (
        "adapter_not_shared", "hardware_share", True, "authorize_adapter"),
    "The selected adapter could not be attached to WSL": (
        "adapter_attach_failed", "hardware_attach", True, "repair_adapter"),
}


class ControlApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, *, stage: str = "control",
                 recoverable: bool = False, primary_action: str | None = None,
                 correlation_id: str | None = None):
        super().__init__(status_code=status, detail=message)
        self.code = code
        self.message = message
        self.stage = stage
        self.recoverable = recoverable
        self.primary_action = primary_action
        self.correlation_id = correlation_id


def relay_api_error(error: RelayError) -> ControlApiError:
    return ControlApiError(
        error.status, error.code, error.message, stage=error.stage,
        recoverable=error.recoverable, primary_action=error.primary_action,
        correlation_id=error.correlation_id,
    )


def control_room(room: dict) -> dict:
    """Add the stable local recovery contract to an authoritative room snapshot."""
    attempt = room.get("attempt")
    if not isinstance(attempt, dict) or attempt.get("phase") != "failed":
        return room
    code = str(attempt.get("recoverable_error") or "session.failed")
    stage, recoverable, action = ATTEMPT_FAILURES.get(code, ("session", True, "retry"))
    return {**room, "attempt": {**attempt, "failure": {
        "code": code, "stage": stage, "recoverable": recoverable,
        "primary_action": action,
    }}}


def runtime_release_id() -> str:
    """Return the immutable packaged-runtime identity used by setup/launcher gates."""
    root = Path(os.environ.get("SWITCHTRADE_RELEASE_ROOT", Path(__file__).resolve().parents[1]))
    marker = root / ".switchtrade-release.json"
    if not marker.is_file():
        return "development"
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("RUNTIME_RELEASE_MARKER_INVALID") from error
    release_id = value.get("release_id", "")
    if value.get("schema") != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_id):
        raise RuntimeError("RUNTIME_RELEASE_MARKER_INVALID")
    return release_id


class CreateGroup(BaseModel):
    name: str = Field(min_length=1, max_length=22)
    visibility: str = Field(pattern="^(private|public)$")
    trainer_display_name: str = Field(default="", max_length=20)
    game: str = Field(default="None", pattern="^(None|FireRed|LeafGreen)$")
    language: str = Field(
        default="None", pattern="^(None|English|Japanese|French|German|Italian|Spanish)$")
    offering: str = Field(default="", max_length=80)
    wanted: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=120)


class JoinGroup(BaseModel):
    passcode: str = Field(min_length=4, max_length=8, pattern="^[A-Za-z0-9]+$")
    trainer_display_name: str = Field(default="Trainer", min_length=1, max_length=40)


class JoinPublicRoom(BaseModel):
    trainer_display_name: str = Field(min_length=1, max_length=20)


class ConnectTradeRoom(BaseModel):
    switch_room_role: str = Field(pattern="^(creator|finder)$")


class StartSession(BaseModel):
    tunnel_seat: str | None = Field(default=None, pattern="^(member_a|member_b)$")
    switch_room_role: str | None = Field(default=None, pattern="^(creator|finder)$")
    role: str | None = Field(default=None, pattern="^(host|guest)$")
    passcode: str = Field(min_length=4, max_length=8, pattern="^[A-Za-z0-9]+$")
    usb_id: str | None = Field(default=None, pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
    attempt_id: str | None = Field(default=None, max_length=80)
    allow_experimental_hardware: bool = False


class RepairRequest(BaseModel):
    action: str = Field(pattern="^recheck_adapter$")
    usb_id: str | None = Field(default=None, pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
    allow_experimental_hardware: bool = False


class HardwareDiagnosticRequest(BaseModel):
    usb_id: str | None = Field(default=None, pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
    mode: str = Field(default="quick", pattern="^(quick|certify|full)$")
    role: str = Field(default="host", pattern="^(host|guest|relay)$")
    allow_experimental_hardware: bool = False


class HardwareSelectionRequest(BaseModel):
    usb_id: str = Field(pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
    bus_id: str = Field(pattern=r"^\d+-\d+$")
    instance_id: str = Field(min_length=1, max_length=512, pattern=r"^[^\x00-\x1f\x7f]+$")


class ProductionDiagnosticRequest(BaseModel):
    test: str = Field(pattern="^(automated|room_detection|ap_association|recommended)$")
    usb_id: str = Field(pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")


class ContinueRunRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")


@dataclass
class Group:
    name: str
    passcode: str
    visibility: str
    state: str = "waiting_for_switch"
    participants: int = 1
    trainer_display_name: str = ""
    game: str = "None"
    language: str = "None"
    offering: str = ""
    wanted: str = ""
    note: str = ""

    def public(self) -> dict:
        data = asdict(self)
        data.pop("passcode", None)
        return data


class Runtime:
    def __init__(self, profile_path: Path, runs_root: Path | None, relay_url: str,
                 *, enable_legacy_diagnostics: bool = True):
        self.profiles = load_profiles(profile_path)
        self.groups: dict[str, Group] = {}
        self.lock = threading.RLock()
        self.hardware_lock = threading.RLock()
        self.release_hardware: Callable[[], dict] = lambda: {}
        self.attempt_lock = threading.Lock()
        self.launch_lock = threading.Lock()
        self.launch_cancel_generation = 0
        self.log = RunLogger("control-api", runs_root, {"profile_path": str(profile_path)})
        self.relay_url = relay_url
        self.relay = RelayClient(relay_url)
        self.relay_capabilities: set[str] = set()
        self.relay_capability_error: str | None = None
        self.relay_failure: RelayError | None = None
        self.next_capability_probe = 0.0
        self.endpoint: subprocess.Popen | None = None
        self.endpoint_session: str | None = None
        runtime_root = (Path(runs_root) / "runtime" if runs_root else
                        default_runs_root().parent / "runtime")
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.diagnostics = ProductionDiagnostics(
            self.log.run_dir / "production-diagnostics",
            recovery_file=runtime_root / "production-diagnostic-recovery.json",
            report_root=self.log.root,
        ) if enable_legacy_diagnostics else None
        self.endpoint_state = runtime_root / "endpoint-state.json"
        self.party_state = runtime_root / "party-state.json"
        self.authority_state = runtime_root / "room-authority.json"
        self.member_token_file = runtime_root / "member-token"
        self.client_id_file = runtime_root / "client-id"
        self.hardware_selection_file = runtime_root / "hardware-selection.json"
        self.hardware_attachment_file = runtime_root / "hardware-attachment.json"
        self.owned_hardware = self.read_hardware_attachment()
        self.endpoint_launch_ack = runtime_root / "endpoint-launch-ack.json"
        self.endpoint_launches = self.log.run_dir / "endpoint-launches"
        self.endpoint_launches.mkdir(exist_ok=True)
        try:
            self.client_id = self.client_id_file.read_text(encoding="utf-8").strip()
        except OSError:
            self.client_id = secrets.token_hex(16)
            self.client_id_file.write_text(self.client_id + "\n", encoding="utf-8")
            os.chmod(self.client_id_file, 0o600)
        self.shutdown_requested = False
        self.last_published_phase: tuple[str | None, str] | None = None
        self.last_authority_heartbeat = 0.0
        previous = self.read_endpoint()
        if self._verified_endpoint_pid(previous) is not None:
            self.endpoint_session = previous.get("session_id")
            self.log.event("orphan_endpoint_recovered", pid=previous.get("pid"),
                           stage=previous.get("state"))

    def public_capabilities(self) -> list[str]:
        now = time.monotonic()
        if now < self.next_capability_probe:
            return sorted(self.relay_capabilities)
        try:
            health = RelayClient(self.relay_url, timeout=0.5).health()
            if (health.get("status") != "ready" or health.get("room_contract") != ROOM_CONTRACT or
                    health.get("rfu_contract") != RFU_CONTRACT):
                raise RelayError(
                    "the online room service uses an incompatible contract",
                    status=503, code="relay_contract_incompatible", stage="relay",
                    recoverable=False, primary_action="update",
                )
            advertised = health.get("capabilities", [])
            self.relay_capabilities = {
                str(capability) for capability in advertised if isinstance(capability, str)
            }
            self.relay_capability_error = None
            self.relay_failure = None
            self.next_capability_probe = now + 30
        except RelayError as error:
            self.relay_capabilities = set()
            self.relay_capability_error = str(error)
            self.relay_failure = error
            self.next_capability_probe = now + 5
        return sorted(self.relay_capabilities)

    def require_relay_contract(self) -> None:
        self.public_capabilities()
        if self.relay_failure is not None:
            raise relay_api_error(self.relay_failure)

    def read_hardware_selection(self) -> dict:
        try:
            # Windows PowerShell 5.1 writes -Encoding UTF8 with a BOM; accept both setup and
            # Python-authored state without weakening JSON validation.
            value = json.loads(self.hardware_selection_file.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_hardware_selection(self, usb_id: str, instance_id: str, bus_id: str) -> None:
        self.hardware_selection_file.write_text(
            json.dumps({
                "schema": 1, "usb_id": usb_id.lower(),
                "instance_id": instance_id, "bus_id": bus_id,
            }) + "\n", encoding="utf-8")

    def read_hardware_attachment(self) -> dict | None:
        try:
            value = json.loads(self.hardware_attachment_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        required = ("usb_id", "instance_id", "bus_id")
        return value if (
            isinstance(value, dict) and value.get("schema") == 1 and
            all(isinstance(value.get(name), str) and value[name] for name in required)
        ) else None

    def write_hardware_attachment(self, usb_id: str, instance_id: str, bus_id: str) -> None:
        value = {
            "schema": 1, "usb_id": usb_id.lower(), "instance_id": instance_id,
            "bus_id": bus_id, "owner_run_id": self.log.run_id,
        }
        temporary = self.hardware_attachment_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
        temporary.replace(self.hardware_attachment_file)
        self.owned_hardware = value

    def clear_hardware_attachment(self) -> None:
        self.hardware_attachment_file.unlink(missing_ok=True)
        self.owned_hardware = None

    def read_endpoint(self) -> dict:
        with self.lock:
            try:
                value = json.loads(self.endpoint_state.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}

    def write_endpoint(self, value: dict) -> None:
        with self.lock:
            temporary = self.endpoint_state.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
            temporary.replace(self.endpoint_state)

    def current_launch_generation(self) -> int:
        with self.lock:
            return self.launch_cancel_generation

    def cancel_launch(self) -> None:
        with self.lock:
            self.launch_cancel_generation += 1

    def launch_was_canceled(self, generation: int) -> bool:
        with self.lock:
            return generation != self.launch_cancel_generation

    def read_parties(self) -> dict:
        try:
            value = json.loads(self.party_state.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def read_authority(self) -> dict:
        try:
            value = json.loads(self.authority_state.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_authority(self, response: dict) -> dict:
        room = response.get("room") or {}
        if room.get("contract_version") != ROOM_CONTRACT:
            raise ControlApiError(
                503, "relay_contract_incompatible",
                "the online room service returned an incompatible room contract",
                stage="relay", recoverable=False, primary_action="update",
            )
        value = {
            "room_id": room.get("room_id"),
            "room_code": room.get("room_code"),
            "member_token": response.get("member_token"),
            "reconnect_token": response.get("reconnect_token"),
        }
        with self.lock:
            temporary = self.authority_state.with_suffix(".tmp")
            temporary.write_text(json.dumps(value), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.authority_state)
            token = response.get("member_token")
            if token:
                self.member_token_file.write_text(str(token), encoding="utf-8")
                os.chmod(self.member_token_file, 0o600)
        return control_room(room)

    def clear_authority(self) -> None:
        with self.lock:
            self.authority_state.unlink(missing_ok=True)
            self.member_token_file.unlink(missing_ok=True)

    def transition_terminal_authority(self, credentials: dict) -> None:
        release_hardware = False
        with self.lock:
            current = self.read_authority()
            if any(current.get(key) != credentials.get(key) for key in (
                    "room_id", "member_token", "reconnect_token")):
                raise RelayError(
                    "saved room authority changed while reconnecting",
                    status=409, code="state_conflict", stage="authentication",
                    recoverable=True, primary_action="retry",
                )
            self.endpoint_running()
            if self.endpoint_session == credentials.get("room_code"):
                self.stop_endpoint()
                release_hardware = True
            self.clear_authority()
        if release_hardware:
            self.release_hardware()

    def authoritative_room(self, *, terminal_cleanup: bool = True) -> dict:
        credentials = self.read_authority()
        if not credentials.get("room_id") or not credentials.get("member_token"):
            raise RelayError("no active trade room")
        try:
            return control_room(
                self.relay.room(credentials["room_id"], credentials["member_token"]))
        except RelayError as error:
            if error.status != 401 or not credentials.get("reconnect_token"):
                raise
            try:
                response = self.relay.reconnect_trade_room(
                    credentials["room_id"], credentials["reconnect_token"])
            except RelayError as reconnect_error:
                if reconnect_error.status not in {404, 410}:
                    raise
                if terminal_cleanup:
                    self.transition_terminal_authority(credentials)
                if reconnect_error.code == "reconnect_deadline_expired":
                    raise
                raise RelayError(
                    "trade room is no longer active",
                    status=410,
                    code="room_not_active",
                    stage="room",
                    recoverable=False,
                    primary_action="return_home",
                    correlation_id=reconnect_error.correlation_id,
                ) from reconnect_error
            return self.save_authority(response)

    def sync_authoritative_phase(self, endpoint: dict, parties: dict) -> None:
        phase = (
            "trading_room" if parties.get("trading_room_confirmed") else
            "failed" if endpoint.get("state") == "failed" else
            "completed" if endpoint.get("state") == "completed" else None
        )
        attempt_id = endpoint.get("attempt_id")
        published = (attempt_id if isinstance(attempt_id, str) else None, phase)
        if phase is None or published == self.last_published_phase:
            return
        if not self.read_authority().get("member_token"):
            return
        try:
            room = self.authoritative_room(terminal_cleanup=False)
            credentials = self.read_authority()
            attempt = room.get("attempt")
            failure_code = str(endpoint.get("error_code") or (
                f"{endpoint.get('failure_stage') or 'session'}.failed"))
            same_failure_needs_refinement = (
                phase == "failed" and attempt and attempt.get("phase") == "failed" and
                attempt.get("recoverable_error") == "relay.peer_lost" and
                failure_code != "relay.peer_lost"
            )
            if (not attempt or
                    (attempt.get("phase") == phase and not same_failure_needs_refinement) or
                    (attempt.get("phase") in TERMINAL_ATTEMPT_PHASES and
                     not same_failure_needs_refinement)):
                self.last_published_phase = published
                return
            payload = {"phase": phase}
            if phase == "failed":
                payload["failure_code"] = failure_code
            self.relay.room_command(
                room["room_id"], credentials["member_token"],
                f"/attempts/{attempt['attempt_id']}:phase", payload,
                expected_version=room["room_version"],
            )
            self.last_published_phase = published
        except RelayError as error:
            self.log.event("authority_phase_sync_failed", level="warning", phase=phase,
                           error=type(error).__name__, code=error.code,
                           correlation_id=error.correlation_id)

    def record_authoritative_failure(self, attempt: dict) -> None:
        code = str(attempt.get("recoverable_error") or "session.failed")
        stage, _recoverable, action = ATTEMPT_FAILURES.get(
            code, ("session", True, "retry"))
        with self.lock:
            current = self.read_endpoint()
            if current.get("state") == "failed":
                existing_code = str(current.get("error_code") or "session.failed")
                same_attempt = current.get("attempt_id") == attempt.get("attempt_id")
                if existing_code == code or (
                        same_attempt and code == "relay.peer_lost" and
                        existing_code != "relay.peer_lost"):
                    return
            current.update({
                "state": "failed",
                "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tunnel_connected": False,
                "error_code": code,
                "error": ATTEMPT_FAILURE_MESSAGES.get(
                    code, "The partner's Switch connection failed."),
                "failure_stage": stage,
                "recovery_action": action,
            })
            self.write_endpoint(current)

    def endpoint_running(self) -> bool:
        if self.endpoint and self.endpoint.poll() is None:
            return True
        endpoint = self.read_endpoint()
        if self._verified_endpoint_pid(endpoint) is None:
            return False
        observed_session = endpoint.get("session_id")
        if self.endpoint_session != observed_session:
            self.endpoint_session = observed_session
            self.log.event("late_endpoint_adopted", pid=endpoint.get("pid"),
                           session_id=observed_session, stage=endpoint.get("state"))
        return True

    @staticmethod
    def _verified_endpoint_pid(endpoint: dict) -> int | None:
        pid = endpoint.get("pid")
        if not isinstance(pid, int) or pid <= 1 or endpoint.get("process_kind") != "rfu-endpoint":
            return None
        nonce = endpoint.get("launch_nonce")
        session_id = endpoint.get("session_id")
        start_ticks = endpoint.get("process_start_ticks")
        if (not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce) or
                not isinstance(session_id, str) or not session_id or
                not isinstance(start_ticks, int) or start_ticks <= 0):
            return None
        if os.name == "nt":
            distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
            if endpoint.get("wsl_distro") != distro:
                return None
            probe = (
                "import base64,json,pathlib,sys;"
                "p=pathlib.Path('/proc')/sys.argv[1];"
                "a=(p/'stat').read_text();c=(p/'cmdline').read_bytes();b=(p/'stat').read_text();"
                "print(json.dumps({'stat':a,'cmdline':base64.b64encode(c).decode()})) if a==b else sys.exit(2)"
            )
            try:
                result = subprocess.run(
                    ["wsl.exe", "-d", distro, "--", "python3", "-c", probe, str(pid)],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                identity = json.loads(result.stdout) if result.returncode == 0 else {}
                stat_value = str(identity.get("stat", ""))
                command = base64.b64decode(str(identity.get("cmdline", "")), validate=True)
            except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
                return None
        else:
            try:
                process = Path(f"/proc/{pid}")
                before = (process / "stat").read_text(encoding="ascii")
                command = (process / "cmdline").read_bytes()
                stat_value = (process / "stat").read_text(encoding="ascii")
                if before != stat_value:
                    return None
            except OSError:
                return None
        try:
            observed_start = int(stat_value[stat_value.rfind(")") + 2:].split()[19])
        except (ValueError, IndexError):
            return None
        arguments = command.rstrip(b"\0").split(b"\0")
        exact_module = any(
            arguments[index:index + 2] == [b"-m", b"switchtrade.endpoint"]
            for index in range(max(0, len(arguments) - 1))
        )
        exact_nonce = any(
            arguments[index:index + 2] == [b"--launch-nonce", nonce.encode("ascii")]
            for index in range(max(0, len(arguments) - 1))
        )
        exact_session = any(
            arguments[index:index + 2] == [b"--session-id", session_id.encode("utf-8")]
            for index in range(max(0, len(arguments) - 1))
        )
        return pid if observed_start == start_ticks and exact_module and exact_nonce and exact_session else None

    @staticmethod
    def _signal_endpoint_pid(pid: int, signal_name: str, endpoint: dict) -> bool:
        if os.name != "nt":
            selected_signal = signal.SIGTERM if signal_name == "TERM" else signal.SIGKILL
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    return False
                try:
                    if Runtime._verified_endpoint_pid(endpoint) != pid:
                        try:
                            signal.pidfd_send_signal(descriptor, 0)
                        except ProcessLookupError:
                            return False
                        raise RuntimeError("endpoint process identity changed before shutdown")
                    try:
                        signal.pidfd_send_signal(descriptor, selected_signal)
                    except ProcessLookupError:
                        return False
                finally:
                    os.close(descriptor)
            else:
                if Runtime._verified_endpoint_pid(endpoint) != pid:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        return False
                    raise RuntimeError("endpoint process identity changed before shutdown")
                try:
                    os.kill(pid, selected_signal)
                except ProcessLookupError:
                    return False
            return True
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        if endpoint.get("wsl_distro") != distro:
            raise RuntimeError("endpoint WSL identity is not verified")
        start_ticks = endpoint.get("process_start_ticks")
        nonce = endpoint.get("launch_nonce")
        session_id = endpoint.get("session_id")
        if (not isinstance(start_ticks, int) or start_ticks <= 0 or
                not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce) or
                not isinstance(session_id, str) or not session_id):
            raise RuntimeError("endpoint WSL identity is not verified")
        helper = (
            "import os,pathlib,signal,sys\n"
            "p=int(sys.argv[1]); expected_start=int(sys.argv[2])\n"
            "nonce=sys.argv[3].encode(); session=sys.argv[4].encode()\n"
            "selected=getattr(signal,'SIG'+sys.argv[5])\n"
            "try:\n"
            " fd=os.pidfd_open(p)\n"
            " signal.pidfd_send_signal(fd,0)\n"
            " root=pathlib.Path('/proc')/str(p)\n"
            " a=(root/'stat').read_text(); cmd=(root/'cmdline').read_bytes()\n"
            " b=(root/'stat').read_text()\n"
            " parts=cmd.rstrip(b'\\0').split(b'\\0')\n"
            " start=int(a[a.rfind(')')+2:].split()[19])\n"
            " pairs=list(zip(parts,parts[1:]))\n"
            " ok=(a==b and start==expected_start and "
            "(b'-m',b'switchtrade.endpoint') in pairs and "
            "(b'--launch-nonce',nonce) in pairs and "
            "(b'--session-id',session) in pairs)\n"
            " if not ok: sys.exit(4)\n"
            " signal.pidfd_send_signal(fd,selected)\n"
            "except (ProcessLookupError,FileNotFoundError):\n"
            " sys.exit(3)\n"
        )
        result = subprocess.run(
            ["wsl.exe", "-d", distro, "-u", "root", "--", "python3", "-c", helper, str(pid),
             str(start_ticks), nonce, session_id, signal_name],
            capture_output=True, timeout=5, check=False, text=True,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 3:
            return False
        if result.returncode == 4:
            raise RuntimeError("endpoint process identity changed before shutdown")
        if result.returncode != 0:
            raise RuntimeError("verified WSL endpoint could not be stopped")
        return True

    def stop_endpoint(self) -> dict:
        self.cancel_launch()
        forced = False
        process = self.endpoint
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forced = True
                process.kill()
                process.wait(timeout=5)
        endpoint = self.read_endpoint()
        pid = endpoint.get("pid")
        if (isinstance(pid, int) and pid > 1 and
                endpoint.get("process_kind") == "rfu-endpoint" and
                (os.name != "nt" or endpoint.get("wsl_distro") ==
                 os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"))):
            signaled = self._signal_endpoint_pid(pid, "TERM", endpoint)
            deadline = time.monotonic() + 10
            while (signaled and time.monotonic() < deadline and
                   self._verified_endpoint_pid(self.read_endpoint()) == pid):
                time.sleep(0.1)
            if signaled and self._verified_endpoint_pid(self.read_endpoint()) == pid:
                forced = True
                self._signal_endpoint_pid(pid, "KILL", self.read_endpoint())
                deadline = time.monotonic() + 5
                while (time.monotonic() < deadline and
                       self._verified_endpoint_pid(self.read_endpoint()) == pid):
                    time.sleep(0.1)
                if self._verified_endpoint_pid(self.read_endpoint()) == pid:
                    raise RuntimeError("verified endpoint did not stop")
        self.endpoint = None
        self.endpoint_session = None
        return {"endpoint_stopped": True, "endpoint_forced": forced}

    def clear_session_state(self) -> None:
        with self.lock:
            self.endpoint_state.unlink(missing_ok=True)
            self.party_state.unlink(missing_ok=True)
            self.endpoint_launch_ack.unlink(missing_ok=True)
            self.endpoint_session = None
            self.last_published_phase = None

def _wsl_path(path: Path) -> str:
    value = str(path.resolve())
    if len(value) >= 3 and value[1:3] == ":\\":
        return f"/mnt/{value[0].lower()}/{value[3:].replace(chr(92), '/')}"
    return value


def endpoint_command(identity: str, passcode: str, relay_url: str,
                     usb_id: str | None = None, state_file: Path | None = None,
                     *, switch_room_role: str | None = None,
                     party_state_file: Path | None = None,
                     attempt_id: str | None = None,
                     member_token_file: Path | None = None,
                     allow_experimental_hardware: bool = False,
                     launch_nonce: str | None = None,
                     launch_ack_file: Path | None = None,
                     diagnostic_run_id: str | None = None,
                     diagnostic_checkpoint: str | None = None,
                     diagnostic_nonce: str | None = None) -> list[str]:
    if identity in {"host", "guest"} and switch_room_role is None:
        args = ["--role", identity]
    else:
        args = ["--tunnel-seat", identity, "--switch-room-role", switch_room_role or ""]
    args += ["--session-id", passcode, "--relay-url", relay_url,
             "--launch-nonce", launch_nonce or secrets.token_hex(16)]
    if launch_ack_file:
        args += ["--launch-ack-file", _wsl_path(launch_ack_file)
                 if os.name == "nt" else str(launch_ack_file)]
    if usb_id:
        args += ["--usb-id", usb_id.lower()]
    if allow_experimental_hardware:
        args += ["--allow-experimental-hardware"]
    if state_file:
        args += ["--state-file", _wsl_path(state_file) if os.name == "nt" else str(state_file)]
    if party_state_file:
        args += ["--party-state-file", _wsl_path(party_state_file)
                 if os.name == "nt" else str(party_state_file)]
    if attempt_id:
        args += ["--attempt-id", attempt_id]
    if member_token_file:
        args += ["--member-token-file", _wsl_path(member_token_file)
                 if os.name == "nt" else str(member_token_file)]
    if diagnostic_run_id:
        args += ["--diagnostic-run-id", diagnostic_run_id]
    if diagnostic_checkpoint:
        args += ["--diagnostic-checkpoint", diagnostic_checkpoint]
    if diagnostic_nonce:
        args += ["--diagnostic-nonce", diagnostic_nonce]
    if os.name == "nt":
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
        return ["wsl.exe", "-d", distro, "--cd", root, "--", "sudo",
                "./scripts/run-beta-endpoint.sh", *args]
    return [str(Path(__file__).resolve().parents[1] / "scripts" / "run-beta-endpoint.sh"), *args]


def hardware_diagnostic_command(usb_id: str, mode: str, role: str,
                                runs_root: Path,
                                *, allow_experimental_hardware: bool = False,
                                active_check: bool = False) -> list[str]:
    args = [
        "-m", "switchtrade.hardware_diagnostics", "--usb-id", usb_id.lower(),
        "--mode", mode, "--role", role, "--runs-root",
        _wsl_path(runs_root) if os.name == "nt" else str(runs_root),
    ]
    if allow_experimental_hardware:
        args.append("--allow-experimental-hardware")
    if active_check:
        args.append("--active-check")
    if os.name == "nt":
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
        python = os.environ.get("SWITCHTRADE_WSL_PYTHON", "./bridge/.venv/bin/python")
        return ["wsl.exe", "-d", distro, "--cd", root, "--", "sudo", python, *args]
    return [sys.executable, *args]


def create_app(profile_path: str | Path = DEFAULT_PROFILE_PATH, runs_root: str | Path | None = None,
               relay_url: str | None = None, *, production_contract: bool = False,
               connection_runner=None) -> FastAPI:
    profile_path = Path(profile_path)
    run_path = Path(runs_root) if runs_root else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = Runtime(profile_path, run_path, relay_url or os.environ.get(
            "SWITCHTRADE_RELAY_URL", "http://127.0.0.1:8788"),
            enable_legacy_diagnostics=not production_contract)
        runtime.release_hardware = lambda: release_owned_hardware(runtime)
        if runtime.diagnostics is not None and runtime.diagnostics.cleanup_incomplete:
            recover_incomplete_diagnostic(runtime)
        elif runtime.owned_hardware is not None and not runtime.endpoint_running():
            try:
                runtime.release_hardware()
            except ControlApiError as error:
                runtime.log.event(
                    "hardware_startup_cleanup_failed", level="error", code=error.code,
                )
        app.state.runtime = runtime
        app.state.connection_service = None
        app.state.relay_readiness_monitor = None
        if production_contract:
            runtime_root = runtime.hardware_selection_file.parent
            runner = connection_runner or ProductionRunner(
                root=runtime_root / "production-connection",
                release=runtime_release_id(), relay=runtime.relay,
                selection_file=runtime.hardware_selection_file,
                distro=os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"),
                runtime_root=os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade"),
                evidence_root=os.environ.get("SWITCHTRADE_SESSION_WSL_PATH") or None,
            )
            app.state.connection_service = ConnectionRunService(
                runtime_root / "connection-service", runner,
                recovery=getattr(runner, "recover", None),
            )
            relay_probe = RelayClient(runtime.relay.base_url, timeout=2.0)
            app.state.relay_readiness_monitor = RelayReadinessMonitor(relay_probe.health)
        yield
        if app.state.connection_service is not None:
            try:
                app.state.connection_service.close()
            except ConnectionRunServiceError as error:
                runtime.log.event(
                    "connection_service_shutdown_failed", level="error", code=error.code)
        if app.state.relay_readiness_monitor is not None:
            app.state.relay_readiness_monitor.close()
        if not production_contract:
            runtime.diagnostics.cancel_active()
            runtime.cancel_launch()
            cleanup_idle = runtime.diagnostics.wait_for_idle(TIMEOUTS["cleanup"])
            if not cleanup_idle:
                runtime.log.event(
                    "diagnostic_shutdown_cleanup_timeout", level="error",
                    code="DIAG_CLEANUP_FAILED",
                )
            if cleanup_idle:
                runtime.stop_endpoint()
                try:
                    runtime.release_hardware()
                except ControlApiError as error:
                    runtime.log.event(
                        "hardware_shutdown_cleanup_failed", level="error", code=error.code,
                    )
        runtime.log.close("api_stopped")

    app = FastAPI(title="SwitchTrade Control API", version=__version__, lifespan=lifespan)

    def error_response(request: Request, status: int, message: str, *, code: str | None = None,
                       stage: str | None = None, recoverable: bool | None = None,
                       primary_action: str | None = None,
                       correlation_id: str | None = None) -> JSONResponse:
        if code is None:
            mapped = LOCAL_ERROR_CODES.get(message)
            if mapped:
                code, stage, recoverable, primary_action = mapped
            elif status == 404:
                code, stage, recoverable, primary_action = "not_found", "control", False, "check_request"
            elif status == 409:
                code, stage, recoverable, primary_action = "state_conflict", "control", True, "retry"
            elif status >= 500:
                code, stage, recoverable, primary_action = "control_unavailable", "control", True, "retry"
            else:
                code, stage, recoverable, primary_action = "invalid_request", "control", False, "check_request"
        correlation_id = correlation_id or getattr(
            request.state, "correlation_id", secrets.token_hex(16))
        return JSONResponse(status_code=status, content={
            "code": code, "message": message, "detail": message,
            "stage": stage or "control", "recoverable": bool(recoverable),
            "primary_action": primary_action, "correlation_id": correlation_id,
        }, headers={"X-Correlation-ID": correlation_id})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        if isinstance(error, ControlApiError):
            return error_response(
                request, error.status_code, error.message, code=error.code, stage=error.stage,
                recoverable=error.recoverable, primary_action=error.primary_action,
                correlation_id=error.correlation_id,
            )
        return error_response(request, error.status_code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        return error_response(
            request, 422, "request validation failed", code="validation_failed",
            stage="control", recoverable=False, primary_action="check_request",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", secrets.token_hex(16))
        try:
            app.state.runtime.log.event(
                "control_internal_error", level="error", error_type=type(error).__name__,
                correlation_id=correlation_id)
        except Exception:
            pass
        return error_response(
            request, 500, "SwitchTrade’s local service could not complete the request.",
            code="control_internal_error", stage="control", recoverable=True,
            primary_action="export_support_bundle", correlation_id=correlation_id,
        )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def reject_cross_origin_control(request: Request, call_next):
        request.state.correlation_id = (
            request.headers.get("x-correlation-id", "").strip() or secrets.token_hex(16))
        origin = request.headers.get("origin")
        # The supported native WPF client sends no Origin header. Browser origins, including
        # arbitrary loopback pages, are never trusted to mutate the local control service.
        if origin:
            return error_response(
                request, 403, "cross-origin control is blocked", code="cross_origin_blocked",
                stage="control", recoverable=False, primary_action="use_desktop_app")
        response = await call_next(request)
        if "X-Correlation-ID" not in response.headers:
            response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    def runtime(request: Request) -> Runtime:
        return request.app.state.runtime

    def publish_diagnostic(state: Runtime, kind: str, path: Path) -> dict:
        try:
            result = state.relay.upload_diagnostic(
                kind, path, state.client_id, runtime_release_id())
        except (OSError, RelayError, RuntimeError, ValueError) as error:
            state.log.event(
                "diagnostic_upload_failed", level="warning", kind=kind,
                error=type(error).__name__, code=getattr(error, "code", None),
                correlation_id=getattr(error, "correlation_id", None),
            )
            return {"status": "unavailable"}
        state.log.event(
            "diagnostic_upload_completed", kind=kind,
            upload_id=result.get("upload_id"),
            correlation_id=result.get("correlation_id"),
        )
        return {"status": "stored", "upload_id": result.get("upload_id")}

    def readiness_axis(status: str, message: str, code: str,
                       action: str | None = None) -> dict:
        return {
            "status": status,
            "user_message": message,
            "technical_code": code,
            "primary_action": action,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def readiness_payload(state: Runtime) -> dict:
        capabilities = state.public_capabilities()
        endpoint = state.read_endpoint()
        parties = state.read_parties()
        state.sync_authoritative_phase(endpoint, parties)
        running = state.endpoint_running()
        endpoint_status = endpoint.get("state", "starting" if running else "idle")
        tunnel_connected = bool(endpoint.get("tunnel_connected", False))
        radio_checked = bool(endpoint.get("radio_checked", False))
        failure_stage = endpoint.get("failure_stage")
        failure_action = endpoint.get("recovery_action")
        failed = endpoint_status == "failed"
        relay_probe_failed = state.relay_capability_error is not None
        relay_status = "ready" if tunnel_connected or not relay_probe_failed else "failed"
        relay_message = (
            "The online relay is connected." if tunnel_connected else
            "The online relay is reachable." if not relay_probe_failed else
            "The online relay is currently unavailable."
        )
        relay_code = (
            "relay.ready" if tunnel_connected else
            "relay.available" if not relay_probe_failed else
            "relay.unavailable"
        )
        axes = {
            "control": readiness_axis(
                "ready", "The local SwitchTrade service is ready.", "control.ready"),
            "relay": readiness_axis(
                "failed" if failed and failure_stage == "relay" else relay_status,
                endpoint.get("error", "The relay connection failed.")
                if failed and failure_stage == "relay" else relay_message,
                endpoint.get("error_code", "relay.failed")
                if failed and failure_stage == "relay" else relay_code,
                failure_action if failure_stage == "relay" else None),
            "radio": readiness_axis(
                "ready" if radio_checked else ("failed" if failed and failure_stage == "radio" else "unknown"),
                "The Switch radio is ready." if radio_checked else
                endpoint.get("error", "The Switch radio failed.") if failed and failure_stage == "radio" else
                "The adapter is checked when a connection starts.",
                "radio.ready" if radio_checked else
                endpoint.get("error_code", "radio.failed") if failed and failure_stage == "radio" else
                "radio.not_checked",
                failure_action if failure_stage == "radio" else None),
            "session": readiness_axis(
                "ready" if endpoint_status == "session_ready" else
                ("checking" if running and not failed else "failed" if failed else "unavailable"),
                "Both endpoint layers are active." if endpoint_status == "session_ready" else
                endpoint.get("error", "The Switch connection failed.") if failed else
                "No Switch connection is active." if not running else "The Switch connection is being prepared.",
                f"session.{endpoint_status}", failure_action if failed else None),
            "decoder": readiness_axis(
                "ready" if parties.get("observer_status") == "ready" else
                ("degraded" if parties.get("observer_status") == "degraded" else "unavailable"),
                "Party observation is active." if parties.get("observer_status") == "ready" else
                "Party display is unavailable; trading is unaffected.",
                f"decoder.{parties.get('observer_status', 'unavailable')}"),
        }
        return {
            "contract_version": READINESS_CONTRACT,
            "product_version": __version__,
            "release_id": runtime_release_id(),
            "compatible": True,
            "supported_contracts": [
                READINESS_CONTRACT, ROOM_CONTRACT, PARTY_CONTRACT, PUBLIC_DIRECTORY_CONTRACT],
            "capabilities": capabilities,
            "run_id": state.log.run_id,
            "endpoint_process_running": running,
            "session_id": state.endpoint_session,
            "states": axes,
            "failure": None if not failed else {
                "stage": failure_stage or "session",
                "code": endpoint.get("error_code") or f"{failure_stage or 'session'}.failed",
                "message": endpoint.get("error") or "The connection failed.",
                "recoverable": bool(failure_action),
                "primary_action": failure_action,
            },
            "role_assignment": {
                "tunnel_seat": endpoint.get("tunnel_seat"),
                "switch_room_role": endpoint.get("switch_room_role"),
                "role_locked": radio_checked and running,
            },
            "counters": {
                "tunnel": endpoint.get("tunnel_counters", {}),
                "rfu": endpoint.get("rfu_counters", {}),
                "decoder": endpoint.get("decoder_counters", parties.get("stats", {})),
            },
        }

    def usbipd_inventory(state: Runtime) -> list[dict]:
        try:
            result = subprocess.run(
                ["usbipd.exe", "state"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlApiError(
                503, "adapter_inventory_unavailable", "Windows USB inventory is unavailable",
                stage="hardware_inventory", recoverable=True, primary_action="retry",
            ) from error
        if result.returncode != 0:
            raise ControlApiError(
                503, "adapter_inventory_unavailable", "Windows USB inventory is unavailable",
                stage="hardware_inventory", recoverable=True, primary_action="retry",
            )
        try:
            devices = json.loads(result.stdout).get("Devices", [])
        except (AttributeError, ValueError) as error:
            raise ControlApiError(
                503, "adapter_inventory_invalid", "Windows USB inventory is invalid",
                stage="hardware_inventory", recoverable=True, primary_action="retry",
            ) from error
        if not isinstance(devices, list):
            raise ControlApiError(
                503, "adapter_inventory_invalid", "Windows USB inventory is invalid",
                stage="hardware_inventory", recoverable=True, primary_action="retry",
            )
        profiles = {profile.usb_id: profile for profile in state.profiles}
        selected = state.read_hardware_selection()
        inventory = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", device.get("InstanceId", ""), re.I)
            if not match or not device.get("BusId"):
                continue
            usb_id = f"{match.group(1)}:{match.group(2)}".lower()
            profile = profiles.get(usb_id)
            if profile is None:
                continue
            public = profile.public()
            instance_id = str(device["InstanceId"])
            selected_instance = str(selected.get("instance_id", ""))
            is_selected = (
                selected.get("usb_id") == usb_id and
                (selected_instance.casefold() == instance_id.casefold() if selected_instance else
                 selected.get("bus_id") == device["BusId"])
            )
            inventory.append({
                "bus_id": device["BusId"], "instance_id": instance_id, "usb_id": usb_id,
                "description": device.get("Description") or profile.model,
                "model": profile.model, "status": profile.status,
                "selectable": public["selectable"], "experimental": public["experimental"],
                "shared": bool(device.get("PersistedGuid") or device.get("StubInstanceId")),
                "attached": bool(device.get("ClientIPAddress")),
                "selected": is_selected,
            })
        return inventory

    def linux_radio_probe(usb_id: str, timeout: float = 2) -> dict:
        script = (
            "import json,pathlib,sys\n"
            "wanted=sys.argv[1].lower(); devices=[]\n"
            "for vendor in pathlib.Path('/sys/bus/usb/devices').glob('*/idVendor'):\n"
            " try:\n"
            "  dev=vendor.parent; found=(vendor.read_text().strip()+':'+(dev/'idProduct').read_text().strip()).lower()\n"
            "  if found==wanted: devices.append(dev.resolve())\n"
            " except OSError: pass\n"
            "def linked(root):\n"
            " for item in root.glob('*/device'):\n"
            "  try:\n"
            "   target=item.resolve()\n"
            "   if any(target==dev or dev in target.parents for dev in devices): return True\n"
            "  except OSError: pass\n"
            " return False\n"
            "print(json.dumps({'status':'present' if devices else 'absent',"
            "'interface_present':linked(pathlib.Path('/sys/class/net')),"
            "'phy_present':linked(pathlib.Path('/sys/class/ieee80211'))},separators=(',',':')))\n"
        )
        command = ["python3", "-c", script, usb_id]
        if os.name == "nt":
            command = [
                "wsl.exe", "-d", os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"),
                "--", *command,
            ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "unknown", "interface_present": None, "phy_present": None}
        if result.returncode != 0:
            return {"status": "unknown", "interface_present": None, "phy_present": None}
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError):
            return {"status": "unknown", "interface_present": None, "phy_present": None}
        if (not isinstance(value, dict) or value.get("status") not in {"present", "absent"} or
                not isinstance(value.get("interface_present"), bool) or
                not isinstance(value.get("phy_present"), bool)):
            return {"status": "unknown", "interface_present": None, "phy_present": None}
        return value

    def wait_linux_radio_state(usb_id: str, desired: str, timeout: float = 8,
                               *, require_radio: bool = True) -> dict:
        deadline = time.monotonic() + timeout
        consecutive = 0
        last = {"status": "unknown", "interface_present": None, "phy_present": None}
        while time.monotonic() < deadline:
            last = linux_radio_probe(usb_id, timeout=min(2, max(0.2, deadline - time.monotonic())))
            matches = last["status"] == desired
            if desired == "present" and require_radio:
                # usbipd reports the device before the kernel driver has necessarily
                # finished registering its netdev and PHY. Starting lsusb/iw during
                # that probe window can wedge this adapter's next enumeration.
                matches = matches and last["interface_present"] and last["phy_present"]
            if desired == "absent":
                matches = matches and not last["interface_present"] and not last["phy_present"]
            consecutive = consecutive + 1 if matches else 0
            if consecutive >= 2:
                return last
            time.sleep(0.1)
        return last

    def prepare_linux_radio_driver(state: Runtime, usb_id: str) -> None:
        root = Path(__file__).resolve().parents[1]
        command = [str(root / "scripts" / "wsl-radio-prepare.sh"),
                   "--driver-only", "--usb-id", usb_id]
        if os.name == "nt":
            distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
            wsl_root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
            command = [
                "wsl.exe", "-d", distro, "-u", "root", "--cd", wsl_root, "--",
                "./scripts/wsl-radio-prepare.sh", "--driver-only", "--usb-id", usb_id,
            ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=LINUX_DRIVER_PREPARE_TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlApiError(
                503, "adapter_linux_driver_prepare_unavailable",
                "Linux could not prepare the selected radio driver",
                stage="hardware_attach", recoverable=True,
                primary_action="retry_attach",
            ) from error
        if result.returncode != 0:
            state.log.event(
                "hardware_driver_prepare_failed", level="error", usb_id=usb_id,
                exit_code=result.returncode,
                output=redact_text((result.stderr or result.stdout)[-2000:]),
            )
            raise ControlApiError(
                503, "adapter_linux_driver_prepare_failed",
                "Linux could not prepare the selected radio driver",
                stage="hardware_attach", recoverable=True,
                primary_action="repair_adapter",
            )
        state.log.event("hardware_gate_passed", gate="driver_prepared", usb_id=usb_id)

    def quiesce_linux_driver(usb_id: str) -> None:
        """Synchronously unbind only the selected USB device before usbipd detaches it."""
        script = (
            "import pathlib,sys\n"
            "wanted=sys.argv[1].lower(); failures=[]\n"
            "for vendor in pathlib.Path('/sys/bus/usb/devices').glob('*/idVendor'):\n"
            " try:\n"
            "  dev=vendor.parent; found=(vendor.read_text().strip()+':'+(dev/'idProduct').read_text().strip()).lower()\n"
            " except OSError: continue\n"
            " if found!=wanted: continue\n"
            " for interface in list(dev.glob('*:*')):\n"
            "  driver=interface/'driver'\n"
            "  if not driver.is_symlink(): continue\n"
            "  try: (driver.resolve()/'unbind').write_text(interface.name)\n"
            "  except FileNotFoundError: pass\n"
            "  except OSError as error: failures.append(type(error).__name__)\n"
            "sys.exit(4 if failures else 0)\n"
        )
        command = ["python3", "-c", script, usb_id, "switchtrade-radio-quiesce"]
        if os.name == "nt":
            command = [
                "wsl.exe", "-d", os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"),
                "-u", "root", "--", *command,
            ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=LINUX_DRIVER_QUIESCE_TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlApiError(
                503, "adapter_linux_quiesce_unavailable",
                "Linux could not quiesce the selected radio driver before USB detachment",
                stage="hardware_cleanup", recoverable=True,
                primary_action="restart_backend",
            ) from error
        if result.returncode != 0:
            raise ControlApiError(
                503, "adapter_linux_quiesce_failed",
                "Linux could not release the selected radio driver before USB detachment",
                stage="hardware_cleanup", recoverable=True,
                primary_action="restart_backend",
            )

    def release_owned_hardware(state: Runtime) -> dict:
        if state.owned_hardware is None:
            return {
                "hardware_owned": False, "windows_usb_detached": True,
                "linux_driver_quiesced": True,
                "linux_usb_absent": True, "interface_absent": True,
                "phy_absent": True, "radio_quiescent": True,
            }
        with state.hardware_lock:
            owned = state.owned_hardware
            if owned is None:
                return {
                    "hardware_owned": False, "windows_usb_detached": True,
                    "linux_driver_quiesced": True,
                    "linux_usb_absent": True, "interface_absent": True,
                    "phy_absent": True, "radio_quiescent": True,
                }
            inventory = usbipd_inventory(state)
            device = next((item for item in inventory if
                           item["instance_id"].casefold() == owned["instance_id"].casefold()), None)
            already_detached = device is None or not device["attached"]
            detach_bus = device["bus_id"] if device is not None else owned["bus_id"]
            quiesce_linux_driver(owned["usb_id"])
            if not already_detached:
                try:
                    result = subprocess.run(
                        ["usbipd.exe", "detach", "--busid", detach_bus],
                        capture_output=True, text=True, timeout=15, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    state.log.event(
                        "hardware_detach_failed", level="error", usb_id=owned["usb_id"],
                        bus_id=detach_bus, error_type=type(error).__name__,
                    )
                    raise ControlApiError(
                        503, "adapter_detach_unavailable",
                        "Windows USB detachment did not complete",
                        stage="hardware_cleanup", recoverable=True,
                        primary_action="retry_cleanup",
                    ) from error
                if result.returncode != 0:
                    state.log.event(
                        "hardware_detach_failed", level="error", usb_id=owned["usb_id"],
                        bus_id=detach_bus, exit_code=result.returncode,
                        output=result.stdout[-2000:], error=result.stderr[-2000:],
                    )
                    raise ControlApiError(
                        503, "adapter_detach_failed",
                        "The selected adapter could not be returned to Windows",
                        stage="hardware_cleanup", recoverable=True,
                        primary_action="retry_cleanup",
                    )
            windows_detached = False
            for _attempt in range(40):
                current_inventory = usbipd_inventory(state)
                current = next((item for item in current_inventory if
                                item["instance_id"].casefold() == owned["instance_id"].casefold()), None)
                if current is None or not current["attached"]:
                    windows_detached = True
                    break
                time.sleep(0.1)
            if not windows_detached:
                raise ControlApiError(
                    503, "adapter_detach_verification_failed",
                    "Windows did not confirm that the selected adapter returned from WSL",
                    stage="hardware_cleanup", recoverable=True,
                    primary_action="retry_cleanup",
                )
            linux = wait_linux_radio_state(
                owned["usb_id"], "absent", timeout=LINUX_RADIO_CLEANUP_TIMEOUT_SECONDS)
            linux_clean = (
                linux["status"] == "absent" and
                linux["interface_present"] is False and
                linux["phy_present"] is False
            )
            if not linux_clean:
                code = ("adapter_linux_cleanup_unavailable" if linux["status"] == "unknown" else
                        "adapter_linux_cleanup_timeout")
                raise ControlApiError(
                    503, code,
                    "Linux did not confirm that the selected adapter and radio interfaces were released",
                    stage="hardware_cleanup", recoverable=True,
                    primary_action="restart_backend",
                )
            state.clear_hardware_attachment()
            state.log.event(
                "hardware_attachment_released", usb_id=owned["usb_id"],
                bus_id=detach_bus, already_detached=already_detached,
                linux_driver_quiesced=True, linux_usb_absent=True,
                interface_absent=True, phy_absent=True,
            )
            return {
                "hardware_owned": True, "windows_usb_detached": True,
                "linux_driver_quiesced": True,
                "linux_usb_absent": True, "interface_absent": True,
                "phy_absent": True, "radio_quiescent": True,
            }

    def recover_incomplete_diagnostic(state: Runtime) -> None:
        recovery = state.diagnostics.recovery_state()
        if not recovery:
            return
        evidence = {
            "endpoint_stopped": False, "synthetic_peer_stopped": True,
            "relay_room_closed": recovery.get("room") is None,
            "credential_file_deleted": recovery.get("token_file") is None,
            "hardware_owned": bool(recovery.get("adapter")),
            "windows_usb_detached": False, "linux_driver_quiesced": False,
            "linux_usb_absent": False,
            "interface_absent": False, "phy_absent": False, "radio_quiescent": False,
        }
        try:
            evidence.update(state.stop_endpoint())
            state.clear_session_state()
            recovery_run_id = recovery.get("run_id")
            if not isinstance(recovery_run_id, str) or not recovery_run_id:
                raise ValueError("diagnostic recovery run identity is invalid")
            d7 = DiagnosticD7Resources(
                close_room=lambda room: close_diagnostic_room(state, room),
                update_recovery=lambda **updates: state.diagnostics.update_recovery(
                    recovery_run_id, **updates),
            )
            room = recovery.get("room")
            if room is not None:
                if not isinstance(room, dict) or not room.get("room_id") or not room.get("owner_token"):
                    raise ValueError("diagnostic room recovery identity is invalid")
                d7.register_room(room)
            token_path = recovery.get("token_file")
            if token_path is not None:
                if not isinstance(token_path, str) or not token_path:
                    raise ValueError("diagnostic credential recovery identity is invalid")
                token = Path(token_path).resolve()
                report = Path(str(recovery.get("report_path", ""))).resolve()
                token.relative_to(report.parent)
                d7.register_credential(token)
            d7_evidence = d7.cleanup()
            evidence.update(
                synthetic_peer_stopped=d7_evidence["synthetic_peer_stopped"],
                relay_room_closed=d7_evidence["temporary_room_closed"],
                credential_file_deleted=d7_evidence["credential_file_absent"],
            )
            if not all(d7_evidence.values()):
                raise RuntimeError("diagnostic D7 resources remain active or unknown")
            adapter = recovery.get("adapter") or {}
            required = ("usb_id", "instance_id", "bus_id")
            if state.owned_hardware is None and all(isinstance(adapter.get(key), str) and
                                                    adapter[key] for key in required):
                state.write_hardware_attachment(
                    adapter["usb_id"], adapter["instance_id"], adapter["bus_id"])
            if state.owned_hardware is not None:
                evidence.update(state.release_hardware())
            elif isinstance(adapter.get("usb_id"), str):
                linux = wait_linux_radio_state(
                    adapter["usb_id"], "absent", timeout=LINUX_RADIO_CLEANUP_TIMEOUT_SECONDS)
                if (linux["status"] != "absent" or
                        linux["interface_present"] is not False or
                        linux["phy_present"] is not False):
                    raise RuntimeError("Linux radio state is not clean after interrupted diagnostic")
                evidence.update(
                    windows_usb_detached=True, linux_driver_quiesced=True,
                    linux_usb_absent=True,
                    interface_absent=True, phy_absent=True, radio_quiescent=True,
                )
            state.diagnostics.complete_recovery(evidence)
            state.log.event(
                "production_diagnostic_recovery_completed",
                diagnostic_run_id=recovery.get("run_id"),
            )
        except (ControlApiError, RelayError, OSError, RuntimeError, ValueError) as error:
            state.diagnostics.fail_recovery(type(error).__name__)
            state.log.event(
                "production_diagnostic_recovery_failed", level="error",
                diagnostic_run_id=recovery.get("run_id"), error_type=type(error).__name__,
            )

    def _attach_selected_hardware(state: Runtime, *, cleanup_on_failure: bool = True) -> str | None:
        selected = state.read_hardware_selection()
        if not selected:
            return None
        inventory = usbipd_inventory(state)
        selected_instance = str(selected.get("instance_id", ""))
        device = next((item for item in inventory if item["usb_id"] == selected.get("usb_id") and (
            item["instance_id"].casefold() == selected_instance.casefold() if selected_instance
            else item["bus_id"] == selected.get("bus_id"))), None)
        if device is None or not device["selectable"]:
            raise ControlApiError(
                409, "adapter_not_available", "Select an available Wi-Fi adapter in Settings",
                stage="hardware_attach", recoverable=True, primary_action="select_adapter",
            )
        if device["bus_id"] != selected.get("bus_id") or not selected_instance:
            state.write_hardware_selection(
                device["usb_id"], device["instance_id"], device["bus_id"])
        if any(item["attached"] and item["usb_id"] == device["usb_id"] and
               item["bus_id"] != device["bus_id"] for item in inventory):
            raise ControlApiError(
                409, "duplicate_adapter_attached",
                "Another identical Wi-Fi adapter is already attached to WSL",
                stage="hardware_attach", recoverable=True,
                primary_action="detach_other_adapter",
            )
        if not device["shared"]:
            state.log.event(
                "hardware_gate_failed", level="error", gate="shared",
                code="adapter_not_shared", usb_id=device["usb_id"],
                bus_id=device["bus_id"],
            )
            raise ControlApiError(
                409, "adapter_not_shared",
                "Windows must authorize the selected adapter before SwitchTrade can use it",
                stage="hardware_share", recoverable=True,
                primary_action="authorize_adapter",
            )
        if not device["attached"]:
            distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
            # Persist the exact-device ownership intent before invoking usbipd. If the control
            # process dies after usbipd succeeds, the next launch can safely return only this
            # physical adapter to Windows.
            state.write_hardware_attachment(
                device["usb_id"], device["instance_id"], device["bus_id"])
            try:
                result = subprocess.run(
                    ["usbipd.exe", "attach", f"--wsl={distro}", "--busid", device["bus_id"]],
                    capture_output=True, text=True, timeout=15, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                if cleanup_on_failure:
                    try:
                        release_owned_hardware(state)
                    except ControlApiError as cleanup_error:
                        state.log.event(
                            "hardware_attach_cleanup_failed", level="error",
                            code=cleanup_error.code, usb_id=device["usb_id"],
                            bus_id=device["bus_id"],
                        )
                state.log.event(
                    "hardware_attach_failed", level="error", usb_id=device["usb_id"],
                    bus_id=device["bus_id"], error_type=type(error).__name__,
                )
                raise ControlApiError(
                    503, "adapter_attach_unavailable",
                    "Windows USB attachment did not complete",
                    stage="hardware_attach", recoverable=True,
                    primary_action="retry_attach",
                ) from error
            if result.returncode != 0:
                if cleanup_on_failure:
                    try:
                        release_owned_hardware(state)
                    except ControlApiError as cleanup_error:
                        state.log.event(
                            "hardware_attach_cleanup_failed", level="error",
                            code=cleanup_error.code, usb_id=device["usb_id"],
                            bus_id=device["bus_id"],
                        )
                state.log.event(
                    "hardware_attach_failed", level="error", usb_id=device["usb_id"],
                    bus_id=device["bus_id"], exit_code=result.returncode,
                    output=result.stdout[-2000:], error=result.stderr[-2000:],
                )
                raise ControlApiError(
                    409, "adapter_attach_failed",
                    "The selected adapter could not be attached to WSL",
                    stage="hardware_attach", recoverable=True,
                    primary_action="repair_adapter",
                )
            attached = False
            for _attempt in range(20):
                current = next((item for item in usbipd_inventory(state)
                                if item["instance_id"].casefold() == device["instance_id"].casefold()), None)
                if current and current["attached"]:
                    attached = True
                    break
                time.sleep(0.1)
            if not attached:
                if cleanup_on_failure:
                    try:
                        release_owned_hardware(state)
                    except ControlApiError as cleanup_error:
                        state.log.event(
                            "hardware_attach_cleanup_failed", level="error",
                            code=cleanup_error.code, usb_id=device["usb_id"],
                            bus_id=device["bus_id"],
                        )
                state.log.event(
                    "hardware_attach_failed", level="error", usb_id=device["usb_id"],
                    bus_id=device["bus_id"], code="adapter_attach_verification_failed",
                )
                raise ControlApiError(
                    409, "adapter_attach_verification_failed",
                    "Windows did not confirm that the selected adapter reached WSL",
                    stage="hardware_attach", recoverable=True,
                    primary_action="retry_attach",
                )
            state.log.event(
                "hardware_gate_passed", gate="attached", usb_id=device["usb_id"],
                bus_id=device["bus_id"],
            )
        linux = wait_linux_radio_state(
            device["usb_id"], "present", timeout=LINUX_USB_ENUMERATION_TIMEOUT_SECONDS,
            require_radio=False)
        if linux["status"] != "present":
            state.log.event(
                "hardware_attach_failed", level="error", usb_id=device["usb_id"],
                bus_id=device["bus_id"], code="adapter_linux_enumeration_timeout",
                linux_status=linux["status"],
            )
            if cleanup_on_failure and state.owned_hardware is not None:
                release_owned_hardware(state)
            code = ("adapter_linux_enumeration_unavailable" if linux["status"] == "unknown" else
                    "adapter_linux_enumeration_timeout")
            raise ControlApiError(
                503, code,
                "Linux did not enumerate the selected adapter before the deadline",
                stage="hardware_attach", recoverable=True,
                primary_action="retry_attach",
            )
        try:
            prepare_linux_radio_driver(state, device["usb_id"])
        except ControlApiError:
            if cleanup_on_failure and state.owned_hardware is not None:
                release_owned_hardware(state)
            raise
        linux = wait_linux_radio_state(
            device["usb_id"], "present", timeout=LINUX_RADIO_ATTACH_TIMEOUT_SECONDS)
        linux_ready = (linux["status"] == "present" and
                       linux["interface_present"] is True and
                       linux["phy_present"] is True)
        if not linux_ready:
            state.log.event(
                "hardware_attach_failed", level="error", usb_id=device["usb_id"],
                bus_id=device["bus_id"], code="adapter_linux_enumeration_timeout",
                linux_status=linux["status"],
                interface_present=linux["interface_present"],
                phy_present=linux["phy_present"],
            )
            if cleanup_on_failure and state.owned_hardware is not None:
                release_owned_hardware(state)
            code = ("adapter_linux_enumeration_unavailable" if linux["status"] == "unknown" else
                    "adapter_linux_enumeration_timeout")
            raise ControlApiError(
                503, code,
                "Linux did not enumerate the selected adapter before the deadline",
                stage="hardware_attach", recoverable=True,
                primary_action="retry_attach",
            )
        state.log.event(
            "hardware_gate_passed", gate="linux_enumerated", usb_id=device["usb_id"],
            bus_id=device["bus_id"],
        )
        return device["usb_id"]

    def attach_selected_hardware(state: Runtime, *, cleanup_on_failure: bool = True) -> str | None:
        # usbipd bus ownership changes while attach is running. A single process-wide lock keeps
        # polling and button requests from issuing competing attach commands for the same device.
        with state.hardware_lock:
            return _attach_selected_hardware(state, cleanup_on_failure=cleanup_on_failure)

    def end_local_session(state: Runtime) -> None:
        with state.lock:
            state.stop_endpoint()
            state.clear_session_state()
        state.release_hardware()

    def launch_output_tail(path: Path, limit: int = 4096) -> str:
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - limit))
                value = stream.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return redact_text(value)

    def launch_failure_detail(stdout_path: Path, stderr_path: Path) -> str:
        stderr_lines = [
            line.strip() for line in launch_output_tail(stderr_path).splitlines()
            if line.strip()
        ]
        lines = stderr_lines or [
            line.strip() for line in launch_output_tail(stdout_path).splitlines()
            if line.strip()
        ]
        return lines[-1][:500] if lines else ""

    def launch_session(state: Runtime, *, code: str, tunnel_seat: str,
                       switch_room_role: str, usb_id: str | None,
                       attempt_id: str | None = None,
                       member_token_file: Path | None = None,
                       allow_experimental_hardware: bool = False,
                       retry: bool = False,
                       launch_generation: int | None = None,
                       diagnostic_run_id: str | None = None,
                       diagnostic_checkpoint: str | None = None,
                       diagnostic_nonce: str | None = None) -> dict:
        try:
            plan = runtime_plan(
                tunnel_seat, usb_id, switch_room_role=switch_room_role,
                allow_experimental_hardware=allow_experimental_hardware,
            )
        except RelayError as error:
            raise relay_api_error(error) from error
        except ValueError as error:
            raise ControlApiError(
                400, "runtime_plan_invalid", str(error), stage="endpoint",
                recoverable=False, primary_action="return_to_diagnostics",
            ) from error
        launch_key = attempt_id or code
        generation = (state.current_launch_generation()
                      if launch_generation is None else launch_generation)

        with state.launch_lock:
            if state.launch_was_canceled(generation):
                raise ControlApiError(
                    409, "endpoint_start_canceled", "the Switch endpoint start was canceled",
                    stage="endpoint", recoverable=True, primary_action="retry",
                )
            with state.lock:
                if state.endpoint_running():
                    current = state.read_endpoint()
                    same_attempt = (
                        state.endpoint_session == code and
                        current.get("attempt_id") in {None, launch_key}
                    )
                    if same_attempt:
                        return {"status": current.get("state", "starting"),
                                "session_id": code, "hardware": plan,
                                "run_id": state.log.run_id}
                    raise ControlApiError(
                        409, "session_active",
                        "a different Switch endpoint session is already running",
                        stage="session", recoverable=True, primary_action="end_session",
                    )

                current = state.read_endpoint()
                if not retry and current.get("attempt_id") == launch_key:
                    failure_code = str(current.get("error_code") or "endpoint_retry_required")
                    failure_stage = str(current.get("failure_stage") or "endpoint")
                    failure_action = str(current.get("recovery_action") or "retry")
                    failure_message = str(current.get("error") or
                                          "This connection attempt already launched. Select Retry to start again.")
                    if current.get("state") == "launching":
                        failure_code = "endpoint_start_incomplete"
                        failure_message = (
                            "The previous endpoint start did not reach initialization. "
                            "Select Retry to start a new attempt."
                        )
                        state.write_endpoint({
                            **current, "state": "failed",
                            "updated_utc": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "error_code": failure_code, "error": failure_message,
                            "failure_stage": "endpoint", "recovery_action": "retry",
                        })
                    raise ControlApiError(
                        409, failure_code, failure_message, stage=failure_stage,
                        recoverable=True, primary_action=failure_action,
                    )

                try:
                    if member_token_file is None:
                        state.relay.status(code)
                except RelayError as error:
                    raise relay_api_error(error) from error

                state.endpoint_state.unlink(missing_ok=True)
                state.party_state.unlink(missing_ok=True)
                launch_nonce = secrets.token_hex(16)
                state.endpoint_launch_ack.unlink(missing_ok=True)
                stdout_path = state.endpoint_launches / f"{launch_nonce}.out.log"
                stderr_path = state.endpoint_launches / f"{launch_nonce}.err.log"
                record_path = state.endpoint_launches / f"{launch_nonce}.json"
                launch_record = {
                    "schema": 1, "launch_nonce": launch_nonce,
                    "attempt_id": launch_key, "status": "launching",
                    "tunnel_seat": plan["tunnel_seat"],
                    "switch_room_role": plan["switch_room_role"],
                    "usb_id": plan["usb_id"],
                    "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "stdout": stdout_path.name, "stderr": stderr_path.name,
                }
                if diagnostic_run_id:
                    launch_record["diagnostic_run_id"] = diagnostic_run_id
                    launch_record["diagnostic_checkpoint"] = diagnostic_checkpoint

                def write_launch_record(**updates) -> None:
                    launch_record.update(updates)
                    temporary = record_path.with_suffix(".json.tmp")
                    temporary.write_text(
                        json.dumps(launch_record, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    temporary.replace(record_path)

                write_launch_record()
                state.write_endpoint({
                    "state": "launching",
                    "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "process_kind": "endpoint-launch",
                    "session_id": code, "attempt_id": launch_key,
                    "launch_nonce": launch_nonce,
                    "tunnel_seat": plan["tunnel_seat"],
                    "switch_room_role": plan["switch_room_role"],
                    "usb_id": plan["usb_id"],
                    "allow_experimental_hardware": allow_experimental_hardware,
                    "radio_checked": False, "tunnel_connected": False,
                    "failure_stage": None, "recovery_action": None,
                    "diagnostic_run_id": diagnostic_run_id,
                    "diagnostic_checkpoint": diagnostic_checkpoint,
                })
                command = endpoint_command(
                    plan["tunnel_seat"], code, state.relay_url, plan["usb_id"],
                    state.endpoint_state, switch_room_role=plan["switch_room_role"],
                    party_state_file=state.party_state, attempt_id=launch_key,
                    member_token_file=member_token_file,
                    allow_experimental_hardware=allow_experimental_hardware,
                    launch_nonce=launch_nonce,
                    launch_ack_file=state.endpoint_launch_ack,
                    diagnostic_run_id=diagnostic_run_id,
                    diagnostic_checkpoint=diagnostic_checkpoint,
                    diagnostic_nonce=diagnostic_nonce,
                )
                try:
                    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                        process = subprocess.Popen(
                            command, cwd=Path(__file__).resolve().parents[1],
                            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                        )
                except OSError as error:
                    message = f"The Switch endpoint process could not be launched: {error}"
                    state.write_endpoint({
                        **state.read_endpoint(), "state": "failed",
                        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "error_code": "endpoint_start_failed", "error": message,
                        "failure_stage": "endpoint", "recovery_action": "retry",
                    })
                    write_launch_record(status="failed", error_code="endpoint_start_failed")
                    state.log.event(
                        "endpoint_launch_failed", level="error", attempt_id=launch_key,
                        launch_nonce=launch_nonce, error=type(error).__name__,
                    )
                    if diagnostic_run_id is None:
                        state.release_hardware()
                    raise ControlApiError(
                        503, "endpoint_start_failed", message, stage="endpoint",
                        recoverable=True, primary_action="retry",
                    ) from error
                state.endpoint = process
                state.endpoint_session = code
                state.write_endpoint({
                    **state.read_endpoint(), "launcher_pid": process.pid,
                })
                write_launch_record(launcher_pid=process.pid)

            def stop_process() -> None:
                if process.poll() is not None:
                    return
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

            def fail_start(code_value: str, message: str, *, stage: str = "endpoint",
                           action: str = "retry", exit_code: int | None = None) -> None:
                stop_process()
                detail = launch_failure_detail(stdout_path, stderr_path)
                if detail and detail.casefold() not in message.casefold():
                    message = f"{message} {detail}"
                with state.lock:
                    current_state = state.read_endpoint()
                    if (current_state.get("launch_nonce") == launch_nonce and
                            current_state.get("state") == "failed" and
                            current_state.get("process_kind") == "rfu-endpoint"):
                        code_value = str(current_state.get("error_code") or code_value)
                        message = str(current_state.get("error") or message)
                        stage = str(current_state.get("failure_stage") or stage)
                        action = str(current_state.get("recovery_action") or action)
                    else:
                        state.write_endpoint({
                            **current_state, "state": "failed",
                            "updated_utc": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "process_kind": "endpoint-launch",
                            "session_id": code, "attempt_id": launch_key,
                            "launch_nonce": launch_nonce, "launcher_pid": process.pid,
                            "error_code": code_value, "error": message,
                            "failure_stage": stage, "recovery_action": action,
                            "launcher_exit_code": exit_code,
                            "radio_checked": False, "tunnel_connected": False,
                        })
                    if state.endpoint is process:
                        state.endpoint = None
                write_launch_record(
                    status="failed", error_code=code_value,
                    exit_code=exit_code, finished_utc=time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                state.log.event(
                    "endpoint_launch_failed", level="error", attempt_id=launch_key,
                    launch_nonce=launch_nonce, launcher_pid=process.pid,
                    exit_code=exit_code, code=code_value, stage=stage,
                    output=detail,
                )
                state.endpoint_launch_ack.unlink(missing_ok=True)
                if diagnostic_run_id is None:
                    state.release_hardware()
                raise ControlApiError(
                    503, code_value, message, stage=stage,
                    recoverable=True, primary_action=action,
                )

            # usbipd publishes a hot-attached USB device before some firmware-backed
            # Wi-Fi drivers finish probing. Keep this outer budget longer than the
            # radio wrapper's bounded 30-second probe gate, while still containing a
            # genuinely stuck endpoint launch.
            deadline = time.monotonic() + ENDPOINT_STARTUP_TIMEOUT_SECONDS
            acknowledgement = None
            initialized = None
            diagnostic_complete = False
            while time.monotonic() < deadline:
                if state.launch_was_canceled(generation):
                    fail_start(
                        "endpoint_start_canceled", "The Switch endpoint start was canceled.",
                        exit_code=process.poll(),
                    )
                try:
                    candidate = json.loads(
                        state.endpoint_launch_ack.read_text(encoding="utf-8-sig"))
                    if (
                        candidate.get("schema") == 2 and
                        candidate.get("stage") == "radio_gate_passed" and
                        candidate.get("launch_nonce") == launch_nonce and
                        isinstance(candidate.get("launcher_pid"), int)
                    ):
                        acknowledgement = candidate
                except (OSError, json.JSONDecodeError):
                    pass

                candidate_state = state.read_endpoint()
                if (
                    candidate_state.get("process_kind") == "rfu-endpoint" and
                    candidate_state.get("launch_nonce") == launch_nonce and
                    candidate_state.get("session_id") == code and
                    candidate_state.get("attempt_id") == launch_key and
                    isinstance(candidate_state.get("pid"), int) and
                    isinstance(candidate_state.get("process_start_ticks"), int)
                ):
                    initialized = candidate_state
                    diagnostic_complete = bool(
                        diagnostic_checkpoint and
                        candidate_state.get("state") == "diagnostic_checkpoint_passed" and
                        candidate_state.get("diagnostic_run_id") == diagnostic_run_id and
                        candidate_state.get("diagnostic_checkpoint") == diagnostic_checkpoint
                    )

                exit_code = process.poll()
                if initialized and initialized.get("state") == "failed":
                    fail_start(
                        str(initialized.get("error_code") or "endpoint_start_failed"),
                        str(initialized.get("error") or
                            "The Switch endpoint failed during initialization."),
                        stage=str(initialized.get("failure_stage") or "endpoint"),
                        action=str(initialized.get("recovery_action") or "retry"),
                        exit_code=exit_code,
                    )
                if acknowledgement and initialized and (exit_code is None or
                                                        (diagnostic_complete and exit_code == 0)):
                    break
                if exit_code is not None:
                    if state.launch_was_canceled(generation):
                        fail_start(
                            "endpoint_start_canceled",
                            "The Switch endpoint start was canceled.",
                            exit_code=exit_code,
                        )
                    stage = "radio" if acknowledgement is None else "endpoint"
                    action = "recheck_adapter" if stage == "radio" else "retry"
                    fail_start(
                        "endpoint_start_failed",
                        "The Switch endpoint exited before initialization.",
                        stage=stage, action=action, exit_code=exit_code,
                    )
                time.sleep(0.025)
            else:
                fail_start(
                    "endpoint_start_failed",
                    "The Switch endpoint did not initialize before the startup deadline.",
                    stage="endpoint" if acknowledgement else "radio",
                    action="retry" if acknowledgement else "recheck_adapter",
                    exit_code=process.poll(),
                )

            state.endpoint_launch_ack.unlink(missing_ok=True)
            write_launch_record(
                status="initialized", endpoint_pid=initialized["pid"],
                gate_launcher_pid=acknowledgement["launcher_pid"],
                initialized_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            state.log.event(
                "session_started", passcode=code, attempt_id=launch_key,
                launch_nonce=launch_nonce, tunnel_seat=plan["tunnel_seat"],
                switch_room_role=plan["switch_room_role"], usb_id=plan["usb_id"],
                host_engine=plan["host_engine"],
                experimental_hardware=plan["experimental_hardware"],
                launcher_pid=process.pid, endpoint_pid=initialized["pid"],
            )
            return {"status": initialized.get("state", "initializing"),
                    "session_id": code, "hardware": plan,
                    "attempt_id": launch_key, "launch_nonce": launch_nonce,
                    "endpoint_pid": initialized["pid"],
                    "run_id": state.log.run_id}

    def launch_authoritative_attempt(state: Runtime, room: dict, *,
                                     allow_launch: bool = True,
                                     retry: bool = False,
                                     prepared_usb_id: str | None = None,
                                     launch_generation: int | None = None) -> dict | None:
        with state.attempt_lock:
            attempt = room.get("attempt") or {}
            endpoint_running = state.endpoint_running()
            if attempt.get("phase") in TERMINAL_ATTEMPT_PHASES:
                if attempt.get("phase") == "failed":
                    state.record_authoritative_failure(attempt)
                if state.endpoint_session == room.get("room_code"):
                    state.stop_endpoint()
                    state.release_hardware()
                return None
            if not attempt.get("role_locked") or attempt.get("phase") is None:
                return None
            switch_role = attempt.get("local_switch_role")
            local = next(
                (member for member in room.get("members", []) if member.get("is_local")), None)
            if switch_role not in {"creator", "finder"} or local is None:
                raise ControlApiError(
                    409, "role_choice_conflict", "the two Switch role choices do not match",
                    stage="coordination", recoverable=True, primary_action="choose_role",
                )
            if endpoint_running:
                if state.endpoint_session == room.get("room_code"):
                    return {"status": "starting", "session_id": room.get("room_code"),
                            "run_id": state.log.run_id}
                raise ControlApiError(
                    409, "session_active", "a different Switch endpoint session is already running",
                    stage="session", recoverable=True, primary_action="end_session",
                )
            if not allow_launch:
                return None
            generation = (state.current_launch_generation() if launch_generation is None
                          else launch_generation)
            selected_usb_id = (attach_selected_hardware(state) if prepared_usb_id is None
                               else prepared_usb_id)
            try:
                return launch_session(
                    state, code=room["room_code"], tunnel_seat=local["seat"],
                    switch_room_role=switch_role, usb_id=selected_usb_id,
                    attempt_id=attempt["attempt_id"], member_token_file=state.member_token_file,
                    retry=retry, launch_generation=generation,
                )
            except Exception:
                if not state.endpoint_running():
                    state.release_hardware()
                raise

    def authoritative_command(state: Runtime, path: str, payload: dict | None = None,
                              method: str = "POST") -> dict:
        credentials = state.read_authority()
        if not credentials.get("room_id") or not credentials.get("member_token"):
            raise ControlApiError(
                410, "room_not_active", "no active authoritative trade room",
                stage="room", recoverable=False, primary_action="return_home",
            )
        try:
            room = state.authoritative_room()
            credentials = state.read_authority()
            return state.relay.room_command(
                credentials["room_id"], credentials["member_token"], path,
                payload, method=method, expected_version=room["room_version"],
            )
        except RelayError as error:
            raise relay_api_error(error) from error

    def release_authoritative_room(state: Runtime, path: str) -> dict:
        try:
            return authoritative_command(state, path, method="DELETE")
        except HTTPException as error:
            already_released = (
                isinstance(error, ControlApiError) and error.code in {
                    "room_not_active", "room_not_found",
                }
            )
            if not already_released:
                raise
            return {}

    def group_from_room(room: dict) -> dict:
        profile = room.get("profile") or {}
        return {
            "name": room.get("name", "Private Trade Room"),
            "passcode": room.get("room_code", ""),
            "visibility": room.get("visibility", "private"),
            "state": room.get("state", "waiting_for_switch"),
            "participants": len([m for m in room.get("members", []) if m.get("online_state") != "left"]),
            "trainer_display_name": profile.get("owner_display_name", ""),
            "game": profile.get("game", "None"),
            "language": profile.get("language", "None"),
            "offering": (room.get("directory") or {}).get("offering", ""),
            "wanted": (room.get("directory") or {}).get("wanted", ""),
            "note": (room.get("directory") or {}).get("note", ""),
            "room_id": room.get("room_id"),
            "room_version": room.get("room_version"),
            "local_member_id": room.get("local_member_id"),
            "local_seat": next((m.get("seat") for m in room.get("members", []) if m.get("is_local")), None),
            "is_owner": room.get("owner_member_id") == room.get("local_member_id"),
            "switch_room_role": (room.get("attempt") or {}).get("local_switch_role"),
        }

    @app.get("/api/status")
    def status(request: Request) -> dict:
        state = runtime(request)
        endpoint = state.read_endpoint()
        running = state.endpoint_running()
        return {
            "status": endpoint.get("state", "starting" if running else "ready"),
            "version": __version__,
            "run_id": state.log.run_id,
            "endpoint_process_running": running,
            "radio_checked": bool(endpoint.get("radio_checked", False)),
            "tunnel_connected": bool(endpoint.get("tunnel_connected", False)),
            "session_id": state.endpoint_session,
            "error": endpoint.get("error"),
        }

    @app.get("/api/v1/app/readiness")
    def app_readiness(request: Request) -> dict:
        return readiness_payload(runtime(request))

    @app.get("/api/v1/trade-room/parties")
    def trade_room_parties(request: Request) -> dict:
        state = runtime(request)
        parties = state.read_parties()
        if parties:
            return parties
        return {
            "contract_version": PARTY_CONTRACT,
            "attempt_id": state.endpoint_session,
            "observer_status": "unavailable",
            "trading_room_confirmed": False,
            "parties": {
                seat: {"status": "unavailable", "reason": "session_not_active", "snapshot": None}
                for seat in ("member_a", "member_b")
            },
            "stats": {},
        }

    def require_no_active_room(state: Runtime) -> None:
        if not state.read_authority().get("member_token"):
            return
        try:
            room = state.authoritative_room()
        except RelayError as error:
            if error.code == "room_not_active":
                return
            raise relay_api_error(error) from error
        if room.get("state") not in {"closed", "expired"}:
            raise ControlApiError(
                409, "room_already_active",
                "an existing Trade Room must be resumed or released before opening another",
                stage="room", recoverable=True, primary_action="resume_room",
            )
        state.clear_authority()

    def require_no_diagnostic(state: Runtime) -> None:
        if state.diagnostics is not None and state.diagnostics.running():
            raise ControlApiError(
                409, "diagnostic_active", "Finish or cancel the active production diagnostic first.",
                stage="diagnostics", recoverable=True, primary_action="return_to_diagnostics",
            )

    def require_no_production_connection(request: Request) -> None:
        connection = getattr(request.app.state, "connection_service", None)
        current = None if connection is None else connection.snapshot()
        if current is not None and (
                current["phase"] != "terminal" or current["cleanup"]["verified"] is not True):
            raise ControlApiError(
                409, "connection_run_active",
                "End the current connection before using adapter maintenance.",
                stage="hardware", recoverable=True, primary_action="end_session")

    @app.post("/api/v1/trade-room")
    def create_trade_room(payload: CreateGroup, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_active_room(state)
        state.require_relay_contract()
        try:
            response = state.relay.create_trade_room({
                "name": payload.name.strip(),
                "visibility": payload.visibility,
                "trainer_display_name": payload.trainer_display_name.strip(),
                "game": payload.game,
                "language": payload.language,
                "offering": payload.offering.strip(),
                "wanted": payload.wanted.strip(),
                "note": payload.note.strip(),
            }, state.client_id)
        except RelayError as error:
            raise relay_api_error(error) from error
        room = state.save_authority(response)
        state.log.event("authoritative_room_created", room_id=room.get("room_id"))
        return {"contract_version": ROOM_CONTRACT, "room": room, "run_id": state.log.run_id}

    @app.post("/api/v1/trade-room/join")
    def join_trade_room(payload: JoinGroup, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_active_room(state)
        state.require_relay_contract()
        try:
            response = state.relay.join_trade_room(
                payload.passcode.upper(), payload.trainer_display_name.strip(), state.client_id)
        except RelayError as error:
            raise relay_api_error(error) from error
        room = state.save_authority(response)
        state.log.event("authoritative_room_joined", room_id=room.get("room_id"))
        return {"contract_version": ROOM_CONTRACT, "room": room, "run_id": state.log.run_id}

    @app.get("/api/v1/public-trade-rooms")
    def list_public_trade_rooms(
            request: Request, query: str = "", game: str = "", language: str = "",
            availability: str = "open", sort: str = "recent", cursor: int = 0,
            limit: int = 25) -> dict:
        state = runtime(request)
        state.require_relay_contract()
        if availability not in {"open", "all"} or sort not in {"recent", "oldest", "name"}:
            raise HTTPException(status_code=400, detail="public room filter is invalid")
        if game not in {"", "FireRed", "LeafGreen"}:
            raise HTTPException(status_code=400, detail="public room game filter is invalid")
        if language not in {"", "English", "Japanese", "French", "German", "Italian", "Spanish"}:
            raise HTTPException(status_code=400, detail="public room language filter is invalid")
        try:
            return state.relay.public_trade_rooms(
                query=query[:80], game=game, language=language,
                availability=availability, sort=sort, cursor=max(0, cursor),
                limit=max(1, min(limit, 50)))
        except RelayError as error:
            raise relay_api_error(error) from error

    @app.get("/api/v1/public-trade-rooms/{listing_id}")
    def get_public_trade_room(listing_id: str, request: Request) -> dict:
        state = runtime(request)
        state.require_relay_contract()
        try:
            return state.relay.public_trade_room(listing_id)
        except RelayError as error:
            raise relay_api_error(error) from error

    @app.post("/api/v1/public-trade-rooms/{listing_id}/join")
    def join_public_trade_room(
            listing_id: str, payload: JoinPublicRoom, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_active_room(state)
        state.require_relay_contract()
        try:
            response = state.relay.join_public_trade_room(
                listing_id, payload.trainer_display_name.strip(), state.client_id)
        except RelayError as error:
            raise relay_api_error(error) from error
        room = state.save_authority(response)
        state.log.event("authoritative_public_room_joined", room_id=room.get("room_id"))
        return {"contract_version": ROOM_CONTRACT, "room": room, "run_id": state.log.run_id}

    @app.get("/api/v1/trade-room")
    def get_trade_room(request: Request) -> dict:
        state = runtime(request)
        try:
            room = state.authoritative_room()
            if time.monotonic() - state.last_authority_heartbeat >= 10:
                credentials = state.read_authority()
                room = state.relay.room_command(
                    room["room_id"], credentials["member_token"], "/heartbeat",
                    expected_version=room["room_version"])
                state.last_authority_heartbeat = time.monotonic()
            room = control_room(room)
            launch_authoritative_attempt(state, room, allow_launch=False)
            return room
        except RelayError as error:
            raise relay_api_error(error) from error

    @app.get("/api/v1/trade-room/events")
    def get_trade_room_events(request: Request, after: int = 0) -> dict:
        state = runtime(request)
        credentials = state.read_authority()
        if not credentials.get("room_id") or not credentials.get("member_token"):
            raise HTTPException(status_code=404, detail="no active trade room")
        try:
            return state.relay.room_events(
                credentials["room_id"], credentials["member_token"], after)
        except RelayError as error:
            raise relay_api_error(error) from error

    @app.post("/api/v1/trade-room/connect")
    def connect_trade_room(payload: ConnectTradeRoom, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        state.require_relay_contract()
        if "manual-switch-role.v1" not in state.relay_capabilities:
            raise ControlApiError(
                503, "relay_capability_missing",
                "the online room service must be updated for manual Switch roles",
                stage="relay", recoverable=False, primary_action="update",
            )
        launch_generation = state.current_launch_generation()
        selected_usb_id = attach_selected_hardware(state)
        if selected_usb_id is None:
            raise ControlApiError(
                409, "adapter_selection_required",
                "Select an available Wi-Fi adapter in Settings",
                stage="hardware", recoverable=True, primary_action="select_adapter",
            )
        if state.launch_was_canceled(launch_generation):
            state.release_hardware()
            raise ControlApiError(
                409, "endpoint_start_canceled", "the Switch endpoint start was canceled",
                stage="endpoint", recoverable=True, primary_action="retry",
            )
        ready_published = False
        try:
            room = state.authoritative_room()
            credentials = state.read_authority()
            room = state.relay.room_command(
                room["room_id"], credentials["member_token"], "/ready", {
                    "ready": True, "switch_room_role": payload.switch_room_role,
                }, expected_version=room["room_version"])
            ready_published = True
            result = launch_authoritative_attempt(
                state, room, prepared_usb_id=selected_usb_id,
                launch_generation=launch_generation,
            ) or {
                "status": room.get("state", "waiting_for_complementary_role"),
                "run_id": state.log.run_id,
            }
            return {**result, "room": room}
        except RelayError as error:
            state.release_hardware()
            raise relay_api_error(error) from error
        except Exception as error:
            # Once both members become ready, a failed local launch must become the one
            # authoritative terminal failure. Publishing that phase also rolls both readiness
            # flags back without immediately erasing the failure that the partner must see.
            if ready_published:
                try:
                    current_room = state.authoritative_room(terminal_cleanup=False)
                    attempt = current_room.get("attempt")
                    if attempt and attempt.get("phase") not in TERMINAL_ATTEMPT_PHASES:
                        credentials = state.read_authority()
                        failure_code = (
                            error.code if isinstance(error, ControlApiError) else
                            str(state.read_endpoint().get("error_code") or "session.failed")
                        )
                        state.relay.room_command(
                            current_room["room_id"], credentials["member_token"],
                            f"/attempts/{attempt['attempt_id']}:phase", {
                                "phase": "failed", "failure_code": failure_code,
                            }, expected_version=current_room["room_version"],
                        )
                except RelayError as rollback_error:
                    state.log.event(
                        "authoritative_launch_failure_sync_failed", level="warning",
                        code=rollback_error.code,
                        correlation_id=rollback_error.correlation_id,
                    )
            state.release_hardware()
            raise

    @app.delete("/api/v1/trade-room/members/me")
    def leave_trade_room(request: Request) -> dict:
        state = runtime(request)
        end_local_session(state)
        room = release_authoritative_room(state, "/members/me")
        state.clear_authority()
        return {"status": "left", "room_version": room.get("room_version"),
                "run_id": state.log.run_id}

    @app.delete("/api/v1/trade-room")
    def close_trade_room(request: Request) -> dict:
        state = runtime(request)
        end_local_session(state)
        room = release_authoritative_room(state, "")
        state.clear_authority()
        return {"status": "closed", "room_version": room.get("room_version"),
                "run_id": state.log.run_id}

    @app.delete("/api/v1/trade-room/local-authority")
    def abandon_local_authority(request: Request) -> dict:
        state = runtime(request)
        end_local_session(state)
        with state.lock:
            state.clear_authority()
        return {"status": "abandoned", "run_id": state.log.run_id}

    @app.get("/api/hardware/profiles")
    def hardware_profiles(request: Request) -> dict:
        state = runtime(request)
        return {
            "profiles": [profile.public() for profile in state.profiles],
            "host_engines": host_engines_public(),
        }

    @app.get("/api/v1/hardware/devices")
    def hardware_devices(request: Request) -> dict:
        state = runtime(request)
        return {"devices": usbipd_inventory(state), "run_id": state.log.run_id}

    @app.post("/api/v1/hardware/selection")
    def select_hardware(payload: HardwareSelectionRequest, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_production_connection(request)
        if state.endpoint_running():
            raise ControlApiError(
                409, "session_active", "End the current connection before changing adapters",
                stage="hardware_selection", recoverable=True, primary_action="end_session",
            )
        usb_id = payload.usb_id.lower()
        device = next((item for item in usbipd_inventory(state)
                       if item["bus_id"] == payload.bus_id and item["usb_id"] == usb_id and
                       item["instance_id"].casefold() == payload.instance_id.casefold()), None)
        if device is None:
            raise ControlApiError(
                404, "adapter_not_available", "The selected adapter is no longer connected",
                stage="hardware_selection", recoverable=True, primary_action="refresh_adapters",
            )
        if not device["selectable"]:
            raise ControlApiError(
                409, "adapter_quarantined", "This adapter is quarantined and cannot trade",
                stage="hardware_selection", recoverable=False, primary_action="select_adapter",
            )
        state.write_hardware_selection(usb_id, device["instance_id"], device["bus_id"])
        state.log.event("hardware_selected", usb_id=usb_id, bus_id=payload.bus_id,
                        experimental=device["experimental"])
        return {"device": {**device, "selected": True}, "run_id": state.log.run_id}

    @app.post("/api/v1/hardware/diagnostics")
    def hardware_diagnostics(payload: HardwareDiagnosticRequest, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_production_connection(request)
        if state.endpoint_running():
            raise ControlApiError(
                409, "session_active", "End the current connection before checking the adapter",
                stage="hardware", recoverable=True, primary_action="end_session",
            )
        requested_usb_id = payload.usb_id.lower() if payload.usb_id else None
        selected_usb_id = attach_selected_hardware(state)
        release_after = state.owned_hardware is not None
        try:
            if selected_usb_id is None:
                raise ControlApiError(
                    409, "adapter_selection_required",
                    "Select an available Wi-Fi adapter in Settings",
                    stage="hardware", recoverable=True, primary_action="select_adapter",
                )
            if requested_usb_id and requested_usb_id != selected_usb_id:
                raise ControlApiError(
                    409, "adapter_selection_mismatch",
                    "The diagnostic profile does not match the selected Windows adapter",
                    stage="hardware", recoverable=True, primary_action="select_adapter",
                )
            usb_id = selected_usb_id
            diagnostic_root = state.log.run_dir / "hardware-diagnostics"
            command = hardware_diagnostic_command(
                usb_id, payload.mode, payload.role, diagnostic_root,
                allow_experimental_hardware=payload.allow_experimental_hardware,
                active_check=True,
            )
            state.log.event(
                "hardware_diagnostic_started", usb_id=usb_id, mode=payload.mode,
                experimental_hardware=payload.allow_experimental_hardware,
            )
            try:
                result = subprocess.run(
                    command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                    text=True, timeout={"quick": 35, "certify": 70, "full": 130}[payload.mode],
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                state.log.event(
                    "hardware_diagnostic_failed", level="error", usb_id=usb_id,
                    error=type(error).__name__,
                )
                raise ControlApiError(
                    503, "hardware_diagnostic_unavailable",
                    "The adapter check did not complete",
                    stage="hardware", recoverable=True, primary_action="retry",
                ) from error
            report = None
            for line in reversed(result.stdout.splitlines()):
                try:
                    candidate = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(candidate, dict) and
                        candidate.get("contract_version") == "hardware-diagnostic.v1"):
                    report = candidate
                    break
            if report is None:
                state.log.event(
                    "hardware_diagnostic_failed", level="error", usb_id=usb_id,
                    exit_code=result.returncode, output=result.stdout[-2000:],
                    error=result.stderr[-2000:],
                )
                raise ControlApiError(
                    503, "hardware_diagnostic_invalid",
                    "The adapter check produced no machine-readable report",
                    stage="hardware", recoverable=True,
                    primary_action="export_support_bundle",
                )
            report_path = diagnostic_root / report["run_id"] / "diagnostic-report.json"
            state.log.event(
                "hardware_diagnostic_completed", usb_id=usb_id,
                diagnostic_run_id=report["run_id"], outcome=report["overall_status"],
            )
            upload = publish_diagnostic(state, "hardware-diagnostic", report_path)
            return {
                "report": report, "report_path": str(report_path),
                "relay_upload": upload, "run_id": state.log.run_id,
            }
        finally:
            if release_after:
                state.release_hardware()

    @app.post("/api/hardware/diagnostics")
    def hardware_diagnostics_legacy(payload: HardwareDiagnosticRequest, request: Request) -> dict:
        return hardware_diagnostics(payload, request)

    def validate_diagnostic_start(state: Runtime, usb_id: str) -> None:
        if state.endpoint_running() or state.read_authority().get("member_token"):
            raise DiagnosticFailure(
                "DIAG_NORMAL_SESSION_ACTIVE",
                "End the active Trade Room or connection before running production diagnostics.",
            )
        selected = state.read_hardware_selection()
        if not selected.get("usb_id"):
            raise DiagnosticFailure("DIAG_ADAPTER_NOT_SELECTED",
                                    "Select and authorize a USB Wi-Fi adapter first.")
        if selected.get("usb_id", "").lower() != usb_id.lower():
            raise DiagnosticFailure("DIAG_ADAPTER_CHANGED",
                                    "The selected adapter does not match the diagnostic adapter.")
        try:
            runtime_plan("member_a", usb_id, switch_room_role="creator")
            runtime_plan("member_b", usb_id, switch_room_role="finder")
        except ValueError as error:
            raise DiagnosticFailure("DIAG_RADIO_GATE_FAILED", str(error)) from error
        state.public_capabilities()
        if state.relay_failure is not None:
            raise DiagnosticFailure("DIAG_RELAY_UNREACHABLE",
                                    "The hosted relay is not ready for production diagnostics.")
        if "manual-switch-role.v1" not in state.relay_capabilities:
            raise DiagnosticFailure(
                "DIAG_RELAY_CONTRACT_INCOMPATIBLE",
                "The hosted relay does not support the production Switch-role contract.",
            )

    def diagnostic_preflight(state: Runtime, run, usb_id: str) -> None:
        run.transition("preflight", "preflight")
        validate_diagnostic_start(state, usb_id)
        run.stage("preflight", "passed", "DIAG_PREFLIGHT_PASSED",
                  "The selected adapter, installed contracts, and hosted relay are ready.")
        run.transition("running", "preflight")

    class DiagnosticResources:
        """Owns the one adapter and ephemeral resources for a diagnostic run."""

        def __init__(self, state: Runtime, run):
            self.state = state
            self.run = run
            self.selection = state.read_hardware_selection()
            self.hardware_acquired = False
            self.d7 = DiagnosticD7Resources(
                close_room=lambda room: close_diagnostic_room(state, room),
                update_recovery=lambda **updates: state.diagnostics.update_recovery(
                    run.run_id, **updates),
            )
            self.evidence = {
                "endpoint_stopped": True, "endpoint_forced": False,
                "synthetic_peer_stopped": True, "relay_room_closed": True,
                "credential_file_deleted": True, "hardware_owned": False,
                "windows_usb_detached": True, "linux_driver_quiesced": True,
                "linux_usb_absent": True,
                "interface_absent": True, "phy_absent": True,
                "radio_quiescent": True,
            }
            state.diagnostics.update_recovery(run.run_id, adapter={
                key: self.selection.get(key) for key in ("usb_id", "instance_id", "bus_id")
            })

        def ensure_hardware(self) -> str:
            selected = self.state.read_hardware_selection()
            expected_instance = str(self.selection.get("instance_id", ""))
            if (selected.get("usb_id", "").lower() != self.run.usb_id or
                    str(selected.get("instance_id", "")).casefold() != expected_instance.casefold()):
                raise DiagnosticFailure("DIAG_ADAPTER_CHANGED",
                                        "The selected adapter changed during the diagnostic.")
            if self.hardware_acquired:
                owned = self.state.owned_hardware or {}
                linux = linux_radio_probe(self.run.usb_id)
                if (str(owned.get("instance_id", "")).casefold() != expected_instance.casefold() or
                        linux["status"] != "present"):
                    raise DiagnosticFailure("DIAG_RADIO_GATE_FAILED",
                                            "The diagnostic lost ownership of the selected adapter.")
                return self.run.usb_id
            try:
                selected_usb_id = attach_selected_hardware(
                    self.state, cleanup_on_failure=False)
            except ControlApiError as error:
                owned = self.state.owned_hardware or {}
                self.hardware_acquired = (
                    str(owned.get("instance_id", "")).casefold() == expected_instance.casefold())
                raise DiagnosticFailure("DIAG_RADIO_GATE_FAILED",
                                        f"{error.code}: {error.message}") from error
            if selected_usb_id != self.run.usb_id:
                raise DiagnosticFailure("DIAG_ADAPTER_CHANGED",
                                        "The selected adapter changed before it reached Linux.")
            owned = self.state.owned_hardware or {}
            if str(owned.get("instance_id", "")).casefold() != expected_instance.casefold():
                raise DiagnosticFailure("DIAG_ADAPTER_CHANGED",
                                        "Hardware ownership does not match the selected adapter.")
            self.hardware_acquired = True
            self.evidence.update(
                hardware_owned=True, windows_usb_detached=False, linux_usb_absent=False,
                interface_absent=False, phy_absent=False, radio_quiescent=False,
            )
            self.state.diagnostics.update_recovery(
                self.run.run_id, status="hardware_owned", adapter={
                    key: owned.get(key) for key in ("usb_id", "instance_id", "bus_id")
                })
            return selected_usb_id

        def register_room(self, room: dict) -> None:
            self.d7.register_room(room)
            self.evidence["relay_room_closed"] = False

        def register_peer(self, peer: SyntheticDiagnosticPeer) -> None:
            self.d7.register_peer(peer)
            self.evidence["synthetic_peer_stopped"] = False

        def register_token_file(self, token_file: Path) -> None:
            self.d7.register_credential(token_file)
            self.evidence["credential_file_deleted"] = False

        def d7_cleanup(self) -> dict:
            result = self.d7.cleanup()
            self.evidence.update(
                synthetic_peer_stopped=result["synthetic_peer_stopped"],
                relay_room_closed=result["temporary_room_closed"],
                credential_file_deleted=result["credential_file_absent"],
            )
            return result

        def cleanup_stage(self, preceding: DiagnosticFailure | None = None) -> None:
            errors = []
            try:
                stopped = self.state.stop_endpoint()
                self.evidence.update(stopped)
                self.state.clear_session_state()
            except Exception as error:
                self.evidence["endpoint_stopped"] = False
                errors.append(f"endpoint:{type(error).__name__}")
            d7 = self.d7_cleanup()
            if not all(d7.values()):
                errors.append("diagnostic:D7")
            if errors:
                raise DiagnosticFailure(
                    "DIAG_CLEANUP_FAILED",
                    "The diagnostic stage did not release every endpoint or relay resource.",
                    preceding=preceding,
                )

        def final_cleanup(self) -> dict:
            started = time.monotonic()
            errors = []
            try:
                self.cleanup_stage()
            except DiagnosticFailure as error:
                errors.append(error.code)
            owned = self.state.owned_hardware or {}
            owns_selected = (
                str(owned.get("instance_id", "")).casefold() ==
                str(self.selection.get("instance_id", "")).casefold()
            )
            if self.hardware_acquired or owns_selected:
                try:
                    self.evidence.update(self.state.release_hardware())
                except ControlApiError as error:
                    errors.append(error.code)
                    self.evidence.update(
                        windows_usb_detached=False, linux_driver_quiesced=False,
                        linux_usb_absent=False,
                        interface_absent=False, phy_absent=False, radio_quiescent=False,
                    )
            self.evidence["duration_ms"] = round((time.monotonic() - started) * 1000)
            self.state.diagnostics.update_recovery(
                self.run.run_id, cleanup_evidence=self.evidence,
                status="cleaned" if not errors else "unresolved",
            )
            return {
                "status": "passed" if not errors else "failed",
                "evidence": dict(self.evidence),
                **({"failure_codes": errors} if errors else {}),
            }

    def diagnostic_hardware_gate(state: Runtime, run, resources: DiagnosticResources) -> None:
        selected_usb_id = resources.ensure_hardware()
        command = hardware_diagnostic_command(
            selected_usb_id, "quick", "host", state.log.run_dir / "hardware-diagnostics",
            active_check=True,
        )
        try:
            result = subprocess.run(
                command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                text=True, timeout=TIMEOUTS["preflight"], check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DiagnosticFailure("DIAG_RADIO_GATE_FAILED",
                                    "The production hardware gate did not complete.") from error
        report = None
        for line in reversed(result.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict) and candidate.get("contract_version") == "hardware-diagnostic.v1":
                report = candidate
                break
        if report is None or report.get("overall_status") == "failed":
            raise DiagnosticFailure("DIAG_RADIO_GATE_FAILED",
                                    "The production hardware gate did not pass.")
        run.stage("hardware", "passed", "DIAG_HARDWARE_GATE_PASSED",
                  "Hardware stage passed — the diagnostic suite is continuing.",
                  details={"overall_status": report.get("overall_status", "unknown"),
                           "hardware_run_id": report.get("run_id", "unknown")})
        run.set_result("hardware_gate_passed")

    def diagnostic_room_pair(state: Runtime, resources: DiagnosticResources,
                             local_switch_role: str) -> dict:
        """Create an ephemeral two-seat authoritative room without touching saved room authority."""
        try:
            local_is_owner = local_switch_role == "creator"
            owner = state.relay.create_trade_room({
                "name": "Production diagnostic", "visibility": "private",
                "trainer_display_name": "Diagnostic local" if local_is_owner else "Diagnostic peer",
                "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
            }, state.client_id)
            owner_room = owner["room"]
            resources.register_room({
                "room_id": owner_room["room_id"], "room_code": owner_room["room_code"],
                "owner_token": owner["member_token"],
                "owner_reconnect_token": owner.get("reconnect_token"),
            })
            joined = state.relay.join_trade_room(
                owner_room["room_code"], "Diagnostic peer" if local_is_owner else "Diagnostic local",
                f"{state.client_id}-diagnostic",
            )
            pair = diagnostic_member_pair(owner, joined, local_switch_role)
            room = owner_room
            for member, role in ((pair["local"], pair["local_role"]),
                                 (pair["peer"], pair["peer_role"])):
                room = state.relay.room_command(
                    owner_room["room_id"], member["member_token"], "/ready",
                    {"ready": True, "switch_room_role": role},
                    expected_version=room["room_version"],
                )
            local_room = state.relay.room(owner_room["room_id"], pair["local"]["member_token"])
            attempt = local_room.get("attempt") or {}
            local_member = next(
                (member for member in local_room.get("members", []) if member.get("is_local")), {})
            peer_member = next(
                (member for member in local_room.get("members", []) if not member.get("is_local")), {})
            valid = (
                attempt.get("role_locked") is True and bool(attempt.get("attempt_id")) and
                attempt.get("local_switch_role") == pair["local_role"] and
                local_member.get("seat") == pair["local_seat"] and
                local_member.get("switch_room_role") == pair["local_role"] and
                peer_member.get("switch_room_role") == pair["peer_role"]
            )
            if not valid:
                raise DiagnosticFailure(
                    "DIAG_PRIVATE_ROOM_FAILED",
                    "The private diagnostic room did not lock the expected seats and Switch roles.",
                )
            result = {
                "room_id": owner_room["room_id"], "room_code": owner_room["room_code"],
                "owner_token": owner["member_token"],
                "owner_reconnect_token": owner.get("reconnect_token"),
                "local_token": pair["local"]["member_token"],
                "peer_token": pair["peer"]["member_token"],
                "attempt_id": attempt["attempt_id"], "local_seat": pair["local_seat"],
            }
            resources.register_room(result)
            return result
        except DiagnosticFailure:
            raise
        except RelayError as error:
            raise DiagnosticFailure(
                "DIAG_PRIVATE_ROOM_FAILED",
                "The private diagnostic room could not be prepared.",
            ) from error

    def close_diagnostic_room(state: Runtime, room: dict) -> None:
        try:
            try:
                snapshot = state.relay.room(room["room_id"], room["owner_token"])
            except RelayError as error:
                if error.status in {404, 410} or error.code in {
                        "room_not_found", "room_not_active"}:
                    return
                reconnect_token = room.get("owner_reconnect_token")
                if (error.status != 401 or not isinstance(reconnect_token, str) or
                        not reconnect_token):
                    raise
                try:
                    reconnected = state.relay.reconnect_trade_room(
                        room["room_id"], reconnect_token)
                except RelayError as reconnect_error:
                    if (reconnect_error.status in {404, 410} or
                            reconnect_error.code in {"room_not_found", "room_not_active"}):
                        return
                    raise
                snapshot = reconnected.get("room") or {}
                owner_token = reconnected.get("member_token")
                if not snapshot.get("room_version") or not isinstance(owner_token, str):
                    raise DiagnosticFailure(
                        "DIAG_CLEANUP_FAILED",
                        "The relay returned invalid diagnostic room recovery state.",
                    )
                room["owner_token"] = owner_token
                rotated_reconnect = reconnected.get("reconnect_token")
                if isinstance(rotated_reconnect, str) and rotated_reconnect:
                    room["owner_reconnect_token"] = rotated_reconnect
            closed = state.relay.room_command(
                room["room_id"], room["owner_token"], "", method="DELETE",
                expected_version=snapshot["room_version"],
            )
            if closed.get("state") not in {"closed", "expired"}:
                raise DiagnosticFailure(
                    "DIAG_CLEANUP_FAILED",
                    "The relay did not confirm that the private diagnostic room is terminal.",
                )
        except RelayError as error:
            if error.status in {404, 410} or error.code in {"room_not_found", "room_not_active"}:
                return
            raise DiagnosticFailure("DIAG_CLEANUP_FAILED",
                                    "The private diagnostic room could not be closed.") from error

    def diagnostic_endpoint_failure(endpoint: dict, checkpoint: str) -> DiagnosticFailure:
        code = str(endpoint.get("error_code") or "")
        stage = str(endpoint.get("failure_stage") or endpoint.get("stage") or "")
        if code == "endpoint_start_canceled":
            return DiagnosticFailure("DIAG_CANCELED", "The diagnostic was canceled.")
        if code == "radio.switch_room_not_found":
            return DiagnosticFailure("DIAG_SWITCH_ROOM_NOT_FOUND",
                                     "No compatible Switch room was found before the deadline.")
        if code.startswith("relay"):
            return DiagnosticFailure("DIAG_RELAY_UNREACHABLE",
                                     "The endpoint could not connect to the hosted relay.")
        if code.startswith("cleanup"):
            return DiagnosticFailure("DIAG_CLEANUP_FAILED",
                                     "Endpoint cleanup did not complete.")
        if stage in {"radio", "hardware", "hardware_attach", "hardware_inventory"} or code.startswith(
                ("adapter_", "radio.")):
            return DiagnosticFailure("DIAG_RADIO_GATE_FAILED",
                                     "The production radio stage did not complete.")
        if checkpoint == "ap_association":
            return DiagnosticFailure("DIAG_AP_START_FAILED",
                                     "The production access point did not start or accept the Switch.")
        if checkpoint == "room_detection":
            return DiagnosticFailure("DIAG_SWITCH_ROOM_JOIN_FAILED",
                                     "The production wrapper could not join the detected Switch room.")
        return DiagnosticFailure("DIAG_WRAPPER_EARLY_EXIT",
                                 "The production wrapper exited before the diagnostic checkpoint.")

    def wait_for_diagnostic_endpoint(state: Runtime, run, checkpoint: str, timeout: int,
                                     identity: dict, nonce: str | None) -> dict:
        deadline = time.monotonic() + timeout
        ap_ready_reported = False
        while time.monotonic() < deadline:
            if run.canceled():
                state.cancel_launch()
                raise DiagnosticFailure("DIAG_CANCELED", "The diagnostic was canceled.")
            endpoint = state.read_endpoint()
            if (endpoint.get("diagnostic_run_id") == run.run_id and
                    endpoint.get("diagnostic_checkpoint") == checkpoint):
                expected = (
                    endpoint.get("attempt_id") == identity["attempt_id"] and
                    endpoint.get("launch_nonce") == identity["launch_nonce"] and
                    endpoint.get("pid") == identity["endpoint_pid"]
                )
                if nonce is not None:
                    expected = expected and endpoint.get("diagnostic_nonce_hash") == hashlib.sha256(
                        nonce.encode("ascii")).hexdigest()
                if not expected:
                    raise DiagnosticFailure(
                        "DIAG_LAUNCH_IDENTITY_MISMATCH",
                        "The endpoint acknowledgement did not match this diagnostic launch.",
                    )
                if (checkpoint == "ap_association" and
                        endpoint.get("state") == "diagnostic_ap_started" and not ap_ready_reported):
                    run.stage(
                        "ap_association", "running", "DIAG_AP_READY",
                        "The diagnostic access point is ready. Search for and join it from one Switch now.",
                        details={"fixture": fixture_metadata()},
                    )
                    ap_ready_reported = True
                if endpoint.get("state") == "diagnostic_checkpoint_passed":
                    return endpoint
                if endpoint.get("state") == "failed":
                    raise diagnostic_endpoint_failure(endpoint, checkpoint)
            process = state.endpoint
            if process is not None and process.poll() is not None:
                raise DiagnosticFailure("DIAG_WRAPPER_EARLY_EXIT",
                                        "The production wrapper exited before the diagnostic checkpoint.")
            time.sleep(0.1)
        raise DiagnosticFailure("DIAG_ENDPOINT_INIT_TIMEOUT",
                                "The production endpoint did not reach its diagnostic checkpoint.")

    def run_diagnostic_endpoint(state: Runtime, run, resources: DiagnosticResources,
                                local_switch_role: str, checkpoint: str,
                                *, fixture: bytes | None = None) -> dict:
        token_file = run.root / f"{local_switch_role}-member-token"
        failure = None
        try:
            if run.canceled():
                raise DiagnosticFailure("DIAG_CANCELED", "The diagnostic was canceled.")
            resources.ensure_hardware()
            room = diagnostic_room_pair(state, resources, local_switch_role)
            peer = SyntheticDiagnosticPeer(
                state.relay_url, room["room_code"],
                "guest" if room["local_seat"] == "member_a" else "host",
                room["peer_token"], room["attempt_id"], fixture=fixture,
            )
            resources.register_peer(peer)
            peer.start()
            token_file.write_text(room["local_token"], encoding="utf-8")
            os.chmod(token_file, 0o600)
            resources.register_token_file(token_file)
            nonce = secrets.token_hex(16) if checkpoint == "relay" else None
            try:
                identity = launch_session(
                    state, code=room["room_code"], tunnel_seat=room["local_seat"],
                    switch_room_role=local_switch_role, usb_id=run.usb_id,
                    attempt_id=room["attempt_id"], member_token_file=token_file, retry=True,
                    diagnostic_run_id=run.run_id, diagnostic_checkpoint=checkpoint,
                    diagnostic_nonce=nonce,
                )
            except ControlApiError as error:
                raise diagnostic_endpoint_failure({
                    "error_code": error.code, "failure_stage": error.stage,
                }, checkpoint) from error
            return wait_for_diagnostic_endpoint(
                state, run, checkpoint,
                TIMEOUTS["room_detection"] if checkpoint == "room_detection" else
                TIMEOUTS["ap_association"] if checkpoint == "ap_association" else TIMEOUTS["endpoint"],
                identity, nonce,
            )
        except DiagnosticFailure as error:
            failure = error
            raise
        finally:
            try:
                resources.cleanup_stage(preceding=failure)
            except DiagnosticFailure:
                raise

    def run_automated_diagnostic(state: Runtime, run, resources: DiagnosticResources) -> None:
        diagnostic_hardware_gate(state, run, resources)
        for switch_role in ("creator", "finder"):
            run.stage(f"{switch_role}_relay", "running", "DIAG_STAGE_RUNNING",
                      f"Running the production wrapper as {switch_role}.")
            endpoint = run_diagnostic_endpoint(state, run, resources, switch_role, "relay")
            run.stage(f"{switch_role}_relay", "passed", "DIAG_RELAY_EXCHANGE_PASSED",
                      f"The {switch_role} wrapper completed a real relay nonce exchange.",
                      details={"endpoint_pid": endpoint.get("pid")})
        run.set_result("relay_exchange_passed")

    def run_room_detection_diagnostic(state: Runtime, run, resources: DiagnosticResources) -> None:
        run.await_continue(
            "open_switch_room",
            "On one Switch only, open the Wireless Club Direct Corner and become Group Leader. Do not join from another Switch, then select Continue.",
        )
        run.stage("switch_room_detection", "running", "DIAG_STAGE_RUNNING",
                  "Scanning and joining the real Switch-hosted room.")
        endpoint = run_diagnostic_endpoint(state, run, resources, "creator", "room_detection")
        run.stage("switch_room_detection", "passed", "DIAG_SWITCH_ROOM_JOINED",
                  "The production wrapper detected, parsed, and joined the Switch room.",
                  details={"advertisement_sha256": endpoint.get("advertisement_sha256")})
        run.set_result("switch_room_joined")

    def run_ap_association_diagnostic(state: Runtime, run, resources: DiagnosticResources) -> None:
        run.await_continue(
            "search_diagnostic_ap",
            "Stop every Switch-hosted room, then select Continue to start the diagnostic access point. Wait for the AP-ready message before searching from one Switch.",
        )
        run.stage("ap_association", "running", "DIAG_STAGE_RUNNING",
                  "Starting the production LDN access point. Do not search from the Switch yet.",
                  details={"fixture": fixture_metadata()})
        run_diagnostic_endpoint(state, run, resources, "finder", "ap_association", fixture=AP_FIXTURE)
        run.stage("ap_association", "passed", "DIAG_SWITCH_ASSOCIATED",
                  "The Switch associated with the app-hosted diagnostic room.",
                  details={"fixture": fixture_metadata()})
        run.set_result("switch_associated")

    def run_production_diagnostic(state: Runtime, run) -> None:
        resources = None
        primary = None
        result = None
        try:
            diagnostic_preflight(state, run, run.usb_id)
            resources = DiagnosticResources(state, run)
            if run.test in {"automated", "recommended"}:
                run_automated_diagnostic(state, run, resources)
            if run.test in {"room_detection", "recommended"}:
                run_room_detection_diagnostic(state, run, resources)
            if run.test in {"ap_association", "recommended"}:
                run_ap_association_diagnostic(state, run, resources)
            result = ("local_prequalification_passed" if run.test == "recommended" else
                      DEFINITIONS[run.test].result_limit)
        except DiagnosticFailure as error:
            primary = error
        except ControlApiError as error:
            code = "DIAG_CLEANUP_FAILED" if error.stage == "hardware_cleanup" else "DIAG_RADIO_GATE_FAILED"
            primary = DiagnosticFailure(code, f"{error.code}: {error.message}")
        except Exception as error:
            state.log.event(
                "production_diagnostic_internal_error", level="error",
                diagnostic_run_id=run.run_id, error_type=type(error).__name__,
            )
            primary = DiagnosticFailure(
                "DIAG_INTERNAL_ERROR",
                f"The diagnostic stopped unexpectedly ({type(error).__name__}).",
            )
        finally:
            run.begin_cleanup()
            cleanup = resources.final_cleanup() if resources is not None else {
                "status": "passed", "evidence": {
                    "endpoint_stopped": True, "synthetic_peer_stopped": True,
                    "relay_room_closed": True, "credential_file_deleted": True,
                    "hardware_owned": False, "windows_usb_detached": True,
                    "linux_driver_quiesced": True,
                    "linux_usb_absent": True, "interface_absent": True,
                    "phy_absent": True, "radio_quiescent": True, "duration_ms": 0,
                },
            }
            cleanup_ok = cleanup["status"] == "passed"
            run.stage(
                "cleanup", "passed" if cleanup_ok else "failed",
                "DIAG_CLEANUP_PASSED" if cleanup_ok else "DIAG_CLEANUP_FAILED",
                "Diagnostic resources were released and verified." if cleanup_ok else
                "Diagnostic cleanup could not be fully verified.",
                details=cleanup.get("evidence", {}),
            )
            if not cleanup_ok:
                run.finish(
                    "failed", code="DIAG_CLEANUP_FAILED",
                    message="The diagnostic did not prove endpoint, relay, and radio cleanup.",
                    cleanup_ok=False, cleanup=cleanup, preceding_failure=primary,
                )
            elif primary is not None:
                run.finish(
                    "canceled" if primary.code == "DIAG_CANCELED" else "failed",
                    code=primary.code, message=primary.message, result_level=primary.result_level,
                    cleanup=cleanup, preceding_failure=primary.preceding,
                )
            else:
                run.finish("passed", result_level=result, cleanup=cleanup)
            state.log.event("production_diagnostic_finished", diagnostic_run_id=run.run_id,
                            test=run.test, cleanup=cleanup["status"])

    @app.post("/api/v1/production-diagnostics", status_code=202)
    def start_production_diagnostic(payload: ProductionDiagnosticRequest, request: Request) -> dict:
        state = runtime(request)
        try:
            validate_diagnostic_start(state, payload.usb_id.lower())
            run = state.diagnostics.start(
                payload.test, payload.usb_id.lower(),
                lambda diagnostic_run: run_production_diagnostic(state, diagnostic_run),
            )
        except DiagnosticFailure as error:
            raise ControlApiError(
                409, error.code.lower(), error.message, stage="diagnostics",
                recoverable=True, primary_action="return_to_diagnostics",
            ) from error
        state.log.event("production_diagnostic_started", diagnostic_run_id=run["run_id"],
                        test=payload.test, usb_id=payload.usb_id.lower())
        return run

    @app.get("/api/v1/production-diagnostics/{run_id}")
    def get_production_diagnostic(run_id: str, request: Request) -> dict:
        state = runtime(request)
        run = state.diagnostics.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="production diagnostic not found")
        return run

    @app.post("/api/v1/production-diagnostics/{run_id}/continue")
    def continue_production_diagnostic(
            run_id: str, payload: ContinueRunRequest, request: Request) -> dict:
        state = runtime(request)
        if not state.diagnostics.continue_run(run_id, payload.checkpoint_id):
            raise ControlApiError(
                409, "diagnostic_checkpoint_invalid", "This diagnostic checkpoint is no longer waiting.",
                stage="diagnostics", recoverable=True, primary_action="refresh_diagnostics",
            )
        return state.diagnostics.get(run_id) or {"run_id": run_id}

    @app.delete("/api/v1/production-diagnostics/{run_id}")
    def cancel_production_diagnostic(run_id: str, request: Request) -> dict:
        state = runtime(request)
        if not state.diagnostics.cancel(run_id):
            current = state.diagnostics.get(run_id)
            if current is None:
                raise HTTPException(status_code=404, detail="production diagnostic not found")
            return current
        state.cancel_launch()
        return state.diagnostics.get(run_id) or {"run_id": run_id, "status": "cleaning"}

    @app.get("/api/groups/public")
    def public_groups(request: Request) -> dict:
        state = runtime(request)
        with state.lock:
            groups = [group.public() for group in state.groups.values() if group.visibility == "public"]
        return {"scope": "local", "groups": groups}

    @app.post("/api/groups")
    def create_group(payload: CreateGroup, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        try:
            code = state.relay.create_session()
        except RelayError as error:
            raise relay_api_error(error) from error
        group = Group(
            payload.name.strip(), code, payload.visibility,
            trainer_display_name=payload.trainer_display_name.strip(),
            game=payload.game, language=payload.language,
            offering=payload.offering.strip(), wanted=payload.wanted.strip(), note=payload.note.strip(),
        )
        with state.lock:
            state.groups[code] = group
        return {"scope": "local", "group": asdict(group), "run_id": state.log.run_id}

    @app.post("/api/groups/join")
    def join_group(payload: JoinGroup, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        code = payload.passcode.upper()
        try:
            state.relay.status(code)
        except RelayError as error:
            raise relay_api_error(error) from error
        with state.lock:
            group = state.groups.get(code)
            if group is None:
                group = Group("Private Trade Group", code, "private")
                state.groups[code] = group
            if group.participants >= 2:
                raise HTTPException(status_code=409, detail="group is full")
            group.participants += 1
        return {"scope": "local", "group": asdict(group), "run_id": state.log.run_id}

    @app.delete("/api/groups/{passcode}")
    def close_group(passcode: str, request: Request) -> dict:
        state = runtime(request)
        with state.lock:
            group = state.groups.pop(passcode.upper(), None)
        if group is None:
            raise HTTPException(status_code=404, detail="group not found")
        return {"status": "closed", "run_id": state.log.run_id}

    @app.delete("/api/groups/{passcode}/members/me")
    def leave_group(passcode: str, request: Request) -> dict:
        state = runtime(request)
        code = passcode.upper()
        with state.lock:
            group = state.groups.get(code)
            if group is None:
                raise HTTPException(status_code=404, detail="group not found")
            group.participants = max(0, group.participants - 1)
            if group.participants == 0:
                state.groups.pop(code, None)
        return {"status": "left", "run_id": state.log.run_id}

    @app.post("/api/session/stop")
    def stop_session(request: Request) -> dict:
        state = runtime(request)
        state.log.event("session_stop_requested")
        end_local_session(state)
        try:
            room = state.authoritative_room()
            credentials = state.read_authority()
            attempt = room.get("attempt")
            if attempt and attempt.get("phase") not in {"completed", "canceled", "failed"}:
                state.relay.room_command(
                    room["room_id"], credentials["member_token"],
                    f"/attempts/{attempt['attempt_id']}:phase", {"phase": "canceled"},
                    expected_version=room["room_version"],
                )
                room = state.authoritative_room()
                credentials = state.read_authority()
            state.relay.room_command(
                room["room_id"], credentials["member_token"], "/ready", {"ready": False},
                expected_version=room["room_version"])
            state.last_published_phase = None
        except RelayError:
            state.log.event("authority_teardown_sync_failed", level="warning")
        return {"status": "stopped", "run_id": state.log.run_id}

    @app.post("/api/v1/session/stop")
    def stop_session_v1(request: Request) -> dict:
        return stop_session(request)

    @app.post("/api/session/start")
    def start_session(payload: StartSession, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        if payload.tunnel_seat and payload.switch_room_role:
            identity = payload.tunnel_seat
            switch_role = payload.switch_room_role
        elif payload.role:
            identity = payload.role
            switch_role = None
        else:
            raise HTTPException(
                status_code=400,
                detail="tunnel_seat and switch_room_role are required",
            )
        code = payload.passcode.upper()
        try:
            plan = runtime_plan(
                identity, payload.usb_id, switch_room_role=switch_role,
                allow_experimental_hardware=payload.allow_experimental_hardware,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return launch_session(
            state, code=code, tunnel_seat=plan["tunnel_seat"],
            switch_room_role=plan["switch_room_role"], usb_id=payload.usb_id,
            attempt_id=payload.attempt_id,
            allow_experimental_hardware=payload.allow_experimental_hardware,
        )

    @app.post("/api/v1/session/start")
    def start_session_v1(payload: StartSession, request: Request) -> dict:
        return start_session(payload, request)

    @app.post("/api/v1/app/retry")
    def retry_app(request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        previous = state.read_endpoint()
        if state.endpoint_running():
            raise HTTPException(status_code=409, detail="the current session is still running")
        if state.read_authority().get("member_token"):
            try:
                room = state.authoritative_room()
                if result := launch_authoritative_attempt(state, room, retry=True):
                    return {**result, "room": room}
                local = next(
                    (member for member in room.get("members", []) if member.get("is_local")), {})
                switch_role = local.get("switch_room_role") or previous.get("switch_room_role")
                if switch_role in {"creator", "finder"}:
                    return connect_trade_room(
                        ConnectTradeRoom(switch_room_role=switch_role), request)
            except RelayError as error:
                raise relay_api_error(error) from error
            raise ControlApiError(
                409, "no_recoverable_session", "no recoverable session is available",
                stage="session", recoverable=False, primary_action="choose_role",
            )
        required = ("session_id", "tunnel_seat", "switch_room_role")
        if any(not previous.get(name) for name in required):
            raise HTTPException(status_code=409, detail="no recoverable session is available")
        state.log.event("session_retry_requested", stage=previous.get("failure_stage"))
        return launch_session(
            state, code=previous["session_id"], tunnel_seat=previous["tunnel_seat"],
            switch_room_role=previous["switch_room_role"], usb_id=previous.get("usb_id"),
            attempt_id=previous.get("attempt_id"),
            allow_experimental_hardware=bool(previous.get("allow_experimental_hardware")),
            retry=True,
        )

    @app.post("/api/v1/app/repair")
    def repair_app(payload: RepairRequest, request: Request) -> dict:
        state = runtime(request)
        require_no_diagnostic(state)
        require_no_production_connection(request)
        if state.endpoint_running():
            raise ControlApiError(
                409, "session_active", "End the current connection before checking the adapter",
                stage="hardware", recoverable=True, primary_action="end_session",
            )
        previous = state.read_endpoint()
        switch_role = previous.get("switch_room_role", "creator")
        selected_usb_id = attach_selected_hardware(state)
        release_after = state.owned_hardware is not None
        try:
            if selected_usb_id is None:
                raise ControlApiError(
                    409, "adapter_selection_required",
                    "Select an available Wi-Fi adapter in Settings",
                    stage="hardware", recoverable=True, primary_action="select_adapter",
                )
            if payload.usb_id and payload.usb_id.lower() != selected_usb_id:
                raise ControlApiError(
                    409, "adapter_selection_mismatch",
                    "The adapter check does not match the selected Windows adapter",
                    stage="hardware", recoverable=True, primary_action="select_adapter",
                )
            try:
                plan = runtime_plan(
                    previous.get("tunnel_seat", "member_a"),
                    payload.usb_id or previous.get("usb_id") or selected_usb_id,
                    switch_room_role=switch_role,
                    allow_experimental_hardware=payload.allow_experimental_hardware,
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            prepare = Path(__file__).resolve().parents[1] / "scripts" / "wsl-radio-prepare.sh"
            command = [str(prepare), "--usb-id", plan["usb_id"], "--role", plan["radio_role"],
                       "--reset-on-rx-failure"]
            if payload.allow_experimental_hardware:
                command.append("--allow-experimental-hardware")
            state.log.event("repair_started", action=payload.action, usb_id=plan["usb_id"])
            result = subprocess.run(
                command, cwd=prepare.parent.parent, capture_output=True, text=True,
                timeout=45, check=False,
            )
            if result.returncode != 0:
                state.log.event(
                    "repair_failed", level="error", action=payload.action,
                    exit_code=result.returncode, output=result.stdout[-2000:],
                    error=result.stderr[-2000:],
                )
                raise ControlApiError(
                    503, "adapter_health_gate_failed",
                    "The adapter health gate did not pass",
                    stage="radio", recoverable=True,
                    primary_action="export_support_bundle",
                )
            state.log.event("repair_completed", action=payload.action, usb_id=plan["usb_id"])
            return {"status": "repaired", "action": payload.action,
                    "usb_id": plan["usb_id"], "run_id": state.log.run_id}
        except (OSError, subprocess.TimeoutExpired) as error:
            state.log.event("repair_failed", level="error", action=payload.action,
                            error=type(error).__name__)
            raise ControlApiError(
                503, "adapter_check_unavailable", "The adapter check did not complete",
                stage="radio", recoverable=True, primary_action="retry",
            ) from error
        finally:
            if release_after:
                state.release_hardware()

    @app.post("/api/support-bundle")
    def support_bundle(request: Request) -> dict:
        state = runtime(request)
        summary = readiness_payload(state)
        endpoint = state.read_endpoint()
        try:
            inventory = usbipd_inventory(state)
            selected = next((device for device in inventory if device["selected"]), None)
            summary["hardware"] = {
                "inventory_status": "ready",
                "selected": None if selected is None else {
                    name: selected[name] for name in (
                        "usb_id", "bus_id", "model", "status", "experimental",
                        "shared", "attached",
                    )
                },
            }
        except HTTPException as error:
            summary["hardware"] = {
                "inventory_status": "unavailable",
                "error": str(error.detail),
            }
        endpoint_run_id = endpoint.get("endpoint_run_id")
        related_run_ids = [endpoint_run_id] if isinstance(endpoint_run_id, str) else []
        path = state.log.support_bundle(summary=summary, related_run_ids=related_run_ids)
        upload = publish_diagnostic(state, "support-bundle", path)
        return {
            "status": "created", "path": str(path),
            "filename": f"SwitchTrade-{path.name}",
            "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "relay_upload": upload, "run_id": state.log.run_id,
        }

    @app.post("/api/v1/support-bundle")
    def support_bundle_v1(request: Request) -> dict:
        return support_bundle(request)

    @app.post("/api/v1/app/shutdown")
    def shutdown_app(request: Request, background_tasks: BackgroundTasks) -> dict:
        state = runtime(request)
        cleanup_code = None
        if state.diagnostics.cancel_active():
            state.cancel_launch()
        if not state.diagnostics.wait_for_idle(TIMEOUTS["cleanup"]):
            cleanup_code = "diagnostic_cleanup_timeout"
            state.log.event(
                "diagnostic_shutdown_cleanup_timeout", level="error",
                code="DIAG_CLEANUP_FAILED",
            )
        try:
            if cleanup_code is None:
                end_local_session(state)
        except ControlApiError as error:
            cleanup_code = error.code
            state.log.event(
                "hardware_shutdown_cleanup_failed", level="error", code=error.code,
            )
        with state.lock:
            state.shutdown_requested = True
        state.log.event("full_shutdown_requested")
        if state.relay.base_url in {"http://127.0.0.1:8788", "http://localhost:8788"}:
            try:
                state.relay.shutdown()
            except RelayError as error:
                state.log.event("development_relay_shutdown_skipped", reason=str(error))
        if os.environ.get("SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN") == "1":
            background_tasks.add_task(lambda: (time.sleep(0.1), os.kill(os.getpid(), 15)))
        return {"status": "stopping", "cleanup_code": cleanup_code,
                "run_id": state.log.run_id}

    if production_contract:
        _install_production_routes(app)
    return app


def _install_production_routes(app: FastAPI) -> None:
    """Replace legacy room/session mutations in the packaged production entry point."""
    replaced = {
        "/api/status", "/api/v1/app/readiness", "/api/v1/trade-room/parties",
        "/api/v1/trade-room", "/api/v1/trade-room/join",
        "/api/v1/trade-room/connect", "/api/v1/trade-room/events",
        "/api/v1/trade-room/members/me", "/api/v1/trade-room/local-authority",
        "/api/v1/public-trade-rooms/{listing_id}/join",
        "/api/v1/session/start", "/api/v1/session/stop", "/api/v1/app/retry",
        "/api/groups", "/api/groups/join", "/api/groups/{passcode}",
        "/api/groups/{passcode}/members/me", "/api/groups/public",
        "/api/session/start", "/api/session/stop", "/api/hardware/diagnostics",
        "/api/v1/support-bundle", "/api/support-bundle", "/api/v1/app/shutdown",
        "/api/v1/production-diagnostics",
        "/api/v1/production-diagnostics/{run_id}",
        "/api/v1/production-diagnostics/{run_id}/continue",
    }
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) not in replaced]
    def axis(status: str, message: str, code: str, action: str | None = None) -> dict:
        return {
            "status": status, "user_message": message, "technical_code": code,
            "primary_action": action,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def state(request: Request) -> Runtime:
        return request.app.state.runtime

    def service(request: Request) -> ConnectionRunService:
        value = request.app.state.connection_service
        if value is None:
            raise ControlApiError(
                503, "connection_service_unavailable", "the connection service is unavailable",
                stage="control", recoverable=True, primary_action="restart_app")
        return value

    def command_identity(request: Request, *, run_bound: bool) -> tuple[str, int, str | None]:
        command_id = request.headers.get("x-switchtrade-command-id", "")
        revision_text = request.headers.get("x-switchtrade-expected-revision", "")
        run_id = request.headers.get("x-switchtrade-run-id") if run_bound else None
        try:
            uuid.UUID(command_id)
            revision = int(revision_text)
            if revision < 0:
                raise ValueError
            if run_bound:
                uuid.UUID(run_id or "")
        except (TypeError, ValueError) as error:
            raise ControlApiError(
                422, "command_identity_invalid",
                "command ID, run ID, or expected revision is invalid",
                stage="control", recoverable=False, primary_action="refresh") from error
        return command_id, revision, run_id

    def invoke(call):
        try:
            return call()
        except ConnectionRunServiceError as error:
            status = 404 if error.code == "RUN_NOT_FOUND" else 422 if error.code in {
                "COMMAND_ID_INVALID", "REQUEST_INVALID", "ROLE_INVALID",
            } else 409
            raise ControlApiError(
                status, error.code.lower(), error.message, stage="connection",
                recoverable=error.code not in {"SERVICE_STATE_INVALID"},
                primary_action="refresh") from error

    def start_run(request: Request, payload: dict) -> dict:
        command_id, revision, _ = command_identity(request, run_bound=False)
        runtime = state(request)
        value = {
            **payload, "authority_command_id": command_id,
            "client_id": runtime.client_id, "release": runtime_release_id(),
        }
        started = invoke(lambda: service(request).start(
            command_id=command_id, expected_revision=revision, request=value))
        return invoke(lambda: service(request).wait_for_authority(started["run_id"], 45))

    def run_command(request: Request, action: str, *, checkpoint: str | None = None,
                    switch_role: str | None = None) -> dict:
        command_id, revision, run_id = command_identity(request, run_bound=True)
        return invoke(lambda: service(request).command(
            command_id=command_id, run_id=run_id or "", expected_revision=revision,
            action=action, checkpoint=checkpoint, switch_role=switch_role))

    @app.get("/api/status")
    @app.get("/api/v1/app/readiness")
    def production_readiness(request: Request) -> dict:
        runtime = state(request)
        current = service(request).snapshot()
        relay_ready = request.app.state.relay_readiness_monitor.snapshot()
        cleanup_required = bool(current and current["cleanup"]["verified"] is False and
                                current["phase"] in {"cleaning", "terminal"})
        failure = None if current is None else current["functional"].get("failure")
        phase = "idle" if current is None else current["phase"]
        return {
            "contract_version": PRODUCTION_READINESS_CONTRACT,
            "product_version": __version__, "release_id": runtime_release_id(),
            "compatible": True,
            "supported_contracts": [PRODUCTION_READINESS_CONTRACT, "production-connection-run.v1"],
            "capabilities": ["production-wrapper.v1", "support-checkpoint.v1"],
            "run_id": None if current is None else current["run_id"],
            "revision": 0 if current is None else current["revision"],
            "endpoint_process_running": bool(current and current["phase"] in {
                "running", "awaiting_user", "cleaning"}),
            "session_id": os.environ.get("SWITCHTRADE_APP_SESSION_ID"),
            "recovery_required": cleanup_required,
            "support_export_available": bool(os.environ.get("SWITCHTRADE_SESSION_WINDOWS_PATH")),
            "connection_run": current,
            "states": {
                "control": axis(
                    "ready", "The local SwitchTrade service is ready.", "control.ready"),
                "relay": axis(
                    "checking" if relay_ready is None else "ready" if relay_ready else "failed",
                    "Checking the online relay." if relay_ready is None else
                    "The online relay is reachable." if relay_ready else
                    "The online relay is currently unavailable.",
                    "relay.checking" if relay_ready is None else
                    "relay.ready" if relay_ready else "relay.unavailable",
                    None if relay_ready is not False else "retry"),
                "radio": axis(
                    "unknown" if current is None else
                    "ready" if current.get("last_passed_gate") == "P0_SIDE_READY" else "checking",
                    "The adapter is checked only by an explicit connection run.",
                    "radio.not_checked" if current is None else "radio.connection_run"),
                "session": axis(
                    "unavailable" if current is None else
                    "failed" if failure else "ready" if phase == "terminal" else "checking",
                    "No Switch connection is active." if current is None else
                    "The connection run failed." if failure else
                    "The connection run is complete." if phase == "terminal" else
                    "The connection run is in progress.",
                    f"session.{phase}"),
                "decoder": axis(
                    "unavailable", "Party display is not part of the production wrapper cutover.",
                    "decoder.unavailable"),
            },
            "failure": failure,
        }

    @app.post("/api/v1/trade-room")
    def production_create(payload: CreateGroup, request: Request) -> dict:
        return start_run(request, {
            "kind": "create", "switch_role": None,
            "name": payload.name.strip(), "visibility": payload.visibility,
            "trainer_display_name": payload.trainer_display_name.strip(),
            "game": payload.game, "language": payload.language,
            "offering": payload.offering.strip(), "wanted": payload.wanted.strip(),
            "note": payload.note.strip(),
        })

    @app.post("/api/v1/trade-room/join")
    def production_join(payload: JoinGroup, request: Request) -> dict:
        return start_run(request, {
            "kind": "join", "switch_role": None, "room_code": payload.passcode.upper(),
            "trainer_display_name": payload.trainer_display_name.strip(),
        })

    @app.post("/api/v1/public-trade-rooms/{listing_id}/join")
    def production_public_join(
            listing_id: str, payload: JoinPublicRoom, request: Request) -> dict:
        return start_run(request, {
            "kind": "public_join", "switch_role": None, "listing_id": listing_id,
            "trainer_display_name": payload.trainer_display_name.strip(),
        })

    @app.get("/api/v1/trade-room")
    def production_room(request: Request) -> dict:
        current = service(request).snapshot()
        if current is None or current.get("room") is None:
            raise ControlApiError(
                404, "room_not_active", "no active Trade Room",
                stage="room", recoverable=False, primary_action="return_home")
        return current

    @app.get("/api/v1/connection-runs/{run_id}")
    def production_run(run_id: str, request: Request) -> dict:
        current = service(request).snapshot(run_id)
        if current is None:
            raise ControlApiError(404, "run_not_found", "connection run was not found")
        return current

    @app.get("/api/v1/trade-room/parties")
    def production_parties(request: Request) -> dict:
        current = service(request).snapshot()
        return {
            "contract_version": PARTY_CONTRACT,
            "attempt_id": None if current is None else current["run_id"],
            "observer_status": "unavailable", "trading_room_confirmed": False,
            "parties": {seat: {"status": "unavailable", "reason": "not_projected",
                                "snapshot": None} for seat in ("member_a", "member_b")},
            "stats": {},
        }

    @app.post("/api/v1/trade-room/connect")
    def production_connect(payload: ConnectTradeRoom, request: Request) -> dict:
        role = "a_room_joiner" if payload.switch_room_role == "creator" else "b_ap_host"
        return run_command(request, "connect", switch_role=role)

    @app.post("/api/v1/connection-runs/{run_id}/continue")
    def production_continue(run_id: str, payload: ContinueRunRequest,
                            request: Request) -> dict:
        if request.headers.get("x-switchtrade-run-id") != run_id:
            raise ControlApiError(409, "run_identity_mismatch", "run identity changed")
        return run_command(request, "continue", checkpoint=payload.checkpoint_id)

    @app.post("/api/v1/session/stop")
    def production_stop(request: Request) -> dict:
        return run_command(request, "stop")

    @app.post("/api/v1/session/end")
    def production_end(request: Request) -> dict:
        return run_command(request, "end")

    @app.delete("/api/v1/trade-room/members/me")
    def production_leave(request: Request) -> dict:
        return run_command(request, "leave")

    @app.delete("/api/v1/trade-room")
    def production_close(request: Request) -> dict:
        return run_command(request, "close")

    @app.post("/api/v1/app/retry")
    def production_retry(request: Request) -> dict:
        command_id, revision, run_id = command_identity(request, run_bound=True)
        retried = invoke(lambda: service(request).retry(
            command_id=command_id, run_id=run_id or "", expected_revision=revision))
        return invoke(lambda: service(request).wait_for_authority(retried["run_id"], 45))

    @app.post("/api/v1/support-checkpoint")
    @app.post("/api/v1/support-bundle")
    def production_support_checkpoint(request: Request) -> dict:
        evidence = ApplicationEvidence.from_environment("control")
        current = service(request).snapshot()
        if evidence is not None:
            evidence.event(
                "support_checkpoint", run_id=None if current is None else current["run_id"],
                gate=None if current is None else current.get("current_gate"))
        return {
            "contract_version": "support-checkpoint.v1", "status": "flushed",
            "app_session_id": os.environ.get("SWITCHTRADE_APP_SESSION_ID"),
            "run_id": None if current is None else current["run_id"],
        }

    @app.post("/api/v1/app/shutdown")
    def production_shutdown(request: Request, background_tasks: BackgroundTasks) -> dict:
        connection = service(request)
        current = connection.snapshot()
        command_id, revision, run_id = command_identity(
            request, run_bound=current is not None)
        cleanup_code = None
        try:
            invoke(lambda: connection.shutdown(
                command_id=command_id, run_id=run_id, expected_revision=revision))
            connection.close()
        except ConnectionRunServiceError as error:
            cleanup_code = error.code
        runtime = state(request)
        with runtime.lock:
            runtime.shutdown_requested = True
        if os.environ.get("SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN") == "1":
            background_tasks.add_task(lambda: (time.sleep(0.1), os.kill(os.getpid(), 15)))
        return {"status": "stopping", "cleanup_code": cleanup_code,
                "run_id": None if connection.snapshot() is None else connection.snapshot()["run_id"]}


app = create_app(production_contract=True)


def main() -> None:
    import uvicorn
    port = int(os.environ.get("SWITCHTRADE_CONTROL_PORT", "8787"))
    instance = os.environ.get("SWITCHTRADE_CONTROL_INSTANCE", "control")
    try:
        with SingleInstanceLock(instance):
            uvicorn.run("switchtrade.control:app", host="127.0.0.1", port=port, reload=False)
    except AlreadyRunningError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
