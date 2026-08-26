"""Local SwitchTrade control API for the desktop UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import os
import json
import re
import subprocess
import threading
import time
import signal
import secrets
import sys

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from switchtrade import __version__
from switchtrade.diagnostics import RunLogger, default_runs_root
from switchtrade.endpoint import runtime_plan
from switchtrade.hardware import DEFAULT_PROFILE_PATH, host_engines_public, load_profiles
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
from switchtrade.relay_client import RelayClient, RelayError


READINESS_CONTRACT = "app-readiness.v1"
ROOM_CONTRACT = "room-control.v1"
PARTY_CONTRACT = "party-commit.v1"
PUBLIC_DIRECTORY_CONTRACT = "public-directory.v1"
RFU_CONTRACT = "rfu-tunnel.v1"

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
    "The selected adapter could not be attached. Run SwitchTrade Setup Repair once if it is not shared.": (
        "adapter_attach_failed", "hardware", True, "repair_adapter"),
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
    def __init__(self, profile_path: Path, runs_root: Path | None, relay_url: str):
        self.profiles = load_profiles(profile_path)
        self.groups: dict[str, Group] = {}
        self.lock = threading.Lock()
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
        self.endpoint_state = runtime_root / "endpoint-state.json"
        self.party_state = runtime_root / "party-state.json"
        self.authority_state = runtime_root / "room-authority.json"
        self.member_token_file = runtime_root / "member-token"
        self.client_id_file = runtime_root / "client-id"
        self.hardware_selection_file = runtime_root / "hardware-selection.json"
        try:
            self.client_id = self.client_id_file.read_text(encoding="utf-8").strip()
        except OSError:
            self.client_id = secrets.token_hex(16)
            self.client_id_file.write_text(self.client_id + "\n", encoding="utf-8")
            os.chmod(self.client_id_file, 0o600)
        self.shutdown_requested = False
        self.last_published_phase: str | None = None
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

    def read_endpoint(self) -> dict:
        try:
            value = json.loads(self.endpoint_state.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

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
        temporary = self.authority_state.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.authority_state)
        token = response.get("member_token")
        if token:
            self.member_token_file.write_text(str(token), encoding="utf-8")
            os.chmod(self.member_token_file, 0o600)
        return room

    def clear_authority(self) -> None:
        self.authority_state.unlink(missing_ok=True)
        self.member_token_file.unlink(missing_ok=True)

    def authoritative_room(self) -> dict:
        credentials = self.read_authority()
        if not credentials.get("room_id") or not credentials.get("member_token"):
            raise RelayError("no active trade room")
        try:
            return self.relay.room(credentials["room_id"], credentials["member_token"])
        except RelayError as error:
            if error.status != 401 or not credentials.get("reconnect_token"):
                raise
            try:
                response = self.relay.reconnect_trade_room(
                    credentials["room_id"], credentials["reconnect_token"])
            except RelayError as reconnect_error:
                if reconnect_error.status not in {401, 404, 410}:
                    raise
                self.clear_authority()
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
        if phase is None or phase == self.last_published_phase:
            return
        credentials = self.read_authority()
        try:
            room = self.authoritative_room()
            attempt = room.get("attempt")
            if not attempt or attempt.get("phase") == phase:
                self.last_published_phase = phase
                return
            self.relay.room_command(
                room["room_id"], credentials["member_token"],
                f"/attempts/{attempt['attempt_id']}:phase", {"phase": phase},
                expected_version=room["room_version"],
            )
            self.last_published_phase = phase
        except RelayError as error:
            self.log.event("authority_phase_sync_failed", level="warning", phase=phase,
                           error=type(error).__name__)

    def endpoint_running(self) -> bool:
        if self.endpoint and self.endpoint.poll() is None:
            return True
        endpoint = self.read_endpoint()
        return self._verified_endpoint_pid(endpoint) is not None

    @staticmethod
    def _verified_endpoint_pid(endpoint: dict) -> int | None:
        pid = endpoint.get("pid")
        if not isinstance(pid, int) or pid <= 1 or endpoint.get("process_kind") != "rfu-endpoint":
            return None
        if os.name == "nt":
            distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
            if endpoint.get("wsl_distro") != distro:
                return None
            try:
                result = subprocess.run(
                    ["wsl.exe", "-d", distro, "--", "cat", f"/proc/{pid}/cmdline"],
                    capture_output=True, timeout=5, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            command = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout).encode()
            return pid if result.returncode == 0 and b"switchtrade.endpoint" in command else None
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return None
        return pid if b"switchtrade.endpoint" in command else None

    @staticmethod
    def _signal_endpoint_pid(pid: int, signal_name: str, endpoint: dict) -> None:
        if os.name != "nt":
            os.kill(pid, signal.SIGTERM if signal_name == "TERM" else signal.SIGKILL)
            return
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        if endpoint.get("wsl_distro") != distro:
            raise RuntimeError("endpoint WSL identity is not verified")
        result = subprocess.run(
            ["wsl.exe", "-d", distro, "--", "kill", f"-{signal_name}", str(pid)],
            capture_output=True, timeout=5, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("verified WSL endpoint could not be stopped")

    def stop_endpoint(self) -> None:
        process = self.endpoint
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if (pid := self._verified_endpoint_pid(endpoint := self.read_endpoint())) is not None:
            self._signal_endpoint_pid(pid, "TERM", endpoint)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self._verified_endpoint_pid(self.read_endpoint()) == pid:
                time.sleep(0.1)
            if self._verified_endpoint_pid(self.read_endpoint()) == pid:
                self._signal_endpoint_pid(pid, "KILL", self.read_endpoint())
        self.endpoint = None
        self.endpoint_session = None

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
                     allow_experimental_hardware: bool = False) -> list[str]:
    if identity in {"host", "guest"} and switch_room_role is None:
        args = ["--role", identity]
    else:
        args = ["--tunnel-seat", identity, "--switch-room-role", switch_room_role or ""]
    args += ["--session-id", passcode, "--relay-url", relay_url]
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
    if os.name == "nt":
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
        return ["wsl.exe", "-d", distro, "--cd", root, "--", "sudo",
                "./scripts/run-beta-endpoint.sh", *args]
    return [str(Path(__file__).resolve().parents[1] / "scripts" / "run-beta-endpoint.sh"), *args]


def hardware_diagnostic_command(usb_id: str, mode: str, role: str,
                                runs_root: Path,
                                *, allow_experimental_hardware: bool = False) -> list[str]:
    args = [
        "-m", "switchtrade.hardware_diagnostics", "--usb-id", usb_id.lower(),
        "--mode", mode, "--role", role, "--runs-root",
        _wsl_path(runs_root) if os.name == "nt" else str(runs_root),
    ]
    if allow_experimental_hardware:
        args.append("--allow-experimental-hardware")
    if os.name == "nt":
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
        python = os.environ.get("SWITCHTRADE_WSL_PYTHON", "./bridge/.venv/bin/python")
        return ["wsl.exe", "-d", distro, "--cd", root, "--", "sudo", python, *args]
    return [sys.executable, *args]


def create_app(profile_path: str | Path = DEFAULT_PROFILE_PATH, runs_root: str | Path | None = None,
               relay_url: str | None = None) -> FastAPI:
    profile_path = Path(profile_path)
    run_path = Path(runs_root) if runs_root else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = Runtime(profile_path, run_path, relay_url or os.environ.get(
            "SWITCHTRADE_RELAY_URL", "http://127.0.0.1:8788"))
        app.state.runtime = runtime
        yield
        runtime.stop_endpoint()
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
                relay_message,
                "relay.failed" if failed and failure_stage == "relay" else relay_code,
                failure_action if failure_stage == "relay" else None),
            "radio": readiness_axis(
                "ready" if radio_checked else ("failed" if failed and failure_stage == "radio" else "unknown"),
                "The Switch radio is ready." if radio_checked else "The adapter is checked when a connection starts.",
                "radio.ready" if radio_checked else "radio.not_checked",
                failure_action if failure_stage == "radio" else None),
            "session": readiness_axis(
                "ready" if endpoint_status == "session_ready" else
                ("checking" if running and not failed else "failed" if failed else "unavailable"),
                "Both endpoint layers are active." if endpoint_status == "session_ready" else
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
                "code": f"{failure_stage or 'session'}.failed",
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
            raise HTTPException(status_code=503, detail="Windows USB inventory is unavailable") from error
        if result.returncode != 0:
            raise HTTPException(status_code=503, detail="Windows USB inventory is unavailable")
        try:
            devices = json.loads(result.stdout).get("Devices", [])
        except (AttributeError, ValueError) as error:
            raise HTTPException(status_code=503, detail="Windows USB inventory is invalid") from error
        if not isinstance(devices, list):
            raise HTTPException(status_code=503, detail="Windows USB inventory is invalid")
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
                "attached": bool(device.get("ClientIPAddress")),
                "selected": is_selected,
            })
        if not any(device["selected"] for device in inventory):
            automatic = [device for device in inventory if profiles[device["usb_id"]].auto_select]
            if len(automatic) == 1:
                automatic[0]["selected"] = True
        return inventory

    def attach_selected_hardware(state: Runtime) -> str | None:
        selected = state.read_hardware_selection()
        if not selected:
            return None
        inventory = usbipd_inventory(state)
        selected_instance = str(selected.get("instance_id", ""))
        device = next((item for item in inventory if item["usb_id"] == selected.get("usb_id") and (
            item["instance_id"].casefold() == selected_instance.casefold() if selected_instance
            else item["bus_id"] == selected.get("bus_id"))), None)
        if device is None or not device["selectable"]:
            raise HTTPException(status_code=409, detail="Select an available Wi-Fi adapter in Settings")
        if device["bus_id"] != selected.get("bus_id") or not selected_instance:
            state.write_hardware_selection(
                device["usb_id"], device["instance_id"], device["bus_id"])
        if any(item["attached"] and item["usb_id"] == device["usb_id"] and
               item["bus_id"] != device["bus_id"] for item in inventory):
            raise HTTPException(
                status_code=409,
                detail="Detach the other identical Wi-Fi adapter from WSL, then try again.",
            )
        if not device["attached"]:
            distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
            result = subprocess.run(
                ["usbipd.exe", "attach", f"--wsl={distro}", "--busid", device["bus_id"]],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=409,
                    detail="The selected adapter could not be attached. Run SwitchTrade Setup Repair once if it is not shared.",
                )
        return device["usb_id"]

    def launch_session(state: Runtime, *, code: str, tunnel_seat: str,
                       switch_room_role: str, usb_id: str | None,
                       attempt_id: str | None = None,
                       member_token_file: Path | None = None,
                       allow_experimental_hardware: bool = False) -> dict:
        try:
            if member_token_file is None:
                state.relay.status(code)
            plan = runtime_plan(
                tunnel_seat, usb_id, switch_room_role=switch_room_role,
                allow_experimental_hardware=allow_experimental_hardware,
            )
        except RelayError as error:
            raise relay_api_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        with state.lock:
            if state.endpoint_running():
                raise HTTPException(status_code=409, detail="a session is already running")
            state.endpoint_state.unlink(missing_ok=True)
            state.party_state.unlink(missing_ok=True)
            command = endpoint_command(
                plan["tunnel_seat"], code, state.relay_url, plan["usb_id"],
                state.endpoint_state, switch_room_role=plan["switch_room_role"],
                party_state_file=state.party_state, attempt_id=attempt_id or code,
                member_token_file=member_token_file,
                allow_experimental_hardware=allow_experimental_hardware,
            )
            try:
                state.endpoint = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1])
            except OSError as error:
                raise HTTPException(status_code=503, detail=f"endpoint launch failed: {error}") from error
            if os.name == "nt":
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if state.endpoint.poll() is not None:
                        state.endpoint = None
                        raise ControlApiError(
                            503, "endpoint_start_failed", "the Switch endpoint stopped during startup",
                            stage="endpoint", recoverable=True, primary_action="retry",
                        )
                    if state._verified_endpoint_pid(state.read_endpoint()) is not None:
                        break
                    time.sleep(0.05)
                else:
                    state.endpoint.terminate()
                    state.endpoint = None
                    raise ControlApiError(
                        503, "endpoint_start_timeout", "the Switch endpoint did not finish starting",
                        stage="endpoint", recoverable=True, primary_action="restart_backend",
                    )
            state.endpoint_session = code
        state.log.event(
            "session_started", passcode=code, tunnel_seat=plan["tunnel_seat"],
            switch_room_role=plan["switch_room_role"], usb_id=plan["usb_id"],
            host_engine=plan["host_engine"],
            experimental_hardware=plan["experimental_hardware"],
            pid=state.endpoint.pid,
        )
        return {"status": "starting", "session_id": code, "hardware": plan,
                "run_id": state.log.run_id}

    def launch_authoritative_attempt(state: Runtime, room: dict) -> dict | None:
        attempt = room.get("attempt") or {}
        if attempt.get("phase") in {"completed", "canceled", "failed"}:
            if state.endpoint_session == room.get("room_code"):
                state.stop_endpoint()
            return None
        if not attempt.get("role_locked") or attempt.get("phase") is None:
            return None
        switch_role = attempt.get("local_switch_role")
        local = next((member for member in room.get("members", []) if member.get("is_local")), None)
        if switch_role not in {"creator", "finder"} or local is None:
            raise ControlApiError(
                409, "role_choice_conflict", "the two Switch role choices do not match",
                stage="coordination", recoverable=True, primary_action="choose_role",
            )
        if (state.endpoint_session == room.get("room_code") and
                state.endpoint_running()):
            return {"status": "starting", "session_id": room.get("room_code"),
                    "run_id": state.log.run_id}
        selected_usb_id = attach_selected_hardware(state)
        return launch_session(
            state, code=room["room_code"], tunnel_seat=local["seat"],
            switch_room_role=switch_role, usb_id=selected_usb_id,
            attempt_id=attempt["attempt_id"], member_token_file=state.member_token_file,
        )

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
                    "room_not_active", "room_not_found", "member_credential_invalid",
                    "reconnect_credential_invalid",
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

    @app.post("/api/v1/trade-room")
    def create_trade_room(payload: CreateGroup, request: Request) -> dict:
        state = runtime(request)
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
            launch_authoritative_attempt(state, room)
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
        credentials = state.read_authority()
        state.require_relay_contract()
        if "manual-switch-role.v1" not in state.relay_capabilities:
            raise ControlApiError(
                503, "relay_capability_missing",
                "the online room service must be updated for manual Switch roles",
                stage="relay", recoverable=False, primary_action="update",
            )
        try:
            room = state.authoritative_room()
            room = state.relay.room_command(
                room["room_id"], credentials["member_token"], "/ready", {
                    "ready": True, "switch_room_role": payload.switch_room_role,
                }, expected_version=room["room_version"])
            result = launch_authoritative_attempt(state, room) or {
                "status": room.get("state", "waiting_for_complementary_role"),
                "run_id": state.log.run_id,
            }
            return {**result, "room": room}
        except RelayError as error:
            raise relay_api_error(error) from error

    @app.delete("/api/v1/trade-room/members/me")
    def leave_trade_room(request: Request) -> dict:
        state = runtime(request)
        room = release_authoritative_room(state, "/members/me")
        state.clear_authority()
        return {"status": "left", "room_version": room.get("room_version"),
                "run_id": state.log.run_id}

    @app.delete("/api/v1/trade-room")
    def close_trade_room(request: Request) -> dict:
        state = runtime(request)
        room = release_authoritative_room(state, "")
        state.clear_authority()
        return {"status": "closed", "room_version": room.get("room_version"),
                "run_id": state.log.run_id}

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
        if state.endpoint_running():
            raise HTTPException(status_code=409, detail="End the current connection before changing adapters")
        usb_id = payload.usb_id.lower()
        device = next((item for item in usbipd_inventory(state)
                       if item["bus_id"] == payload.bus_id and item["usb_id"] == usb_id and
                       item["instance_id"].casefold() == payload.instance_id.casefold()), None)
        if device is None:
            raise HTTPException(status_code=404, detail="The selected adapter is no longer connected")
        if not device["selectable"]:
            raise HTTPException(status_code=409, detail="This adapter is quarantined and cannot trade")
        state.write_hardware_selection(usb_id, device["instance_id"], device["bus_id"])
        state.log.event("hardware_selected", usb_id=usb_id, bus_id=payload.bus_id,
                        experimental=device["experimental"])
        return {"device": {**device, "selected": True}, "run_id": state.log.run_id}

    @app.post("/api/v1/hardware/diagnostics")
    def hardware_diagnostics(payload: HardwareDiagnosticRequest, request: Request) -> dict:
        state = runtime(request)
        usb_id = payload.usb_id.lower() if payload.usb_id else next(
            profile.usb_id for profile in state.profiles if profile.auto_select)
        diagnostic_root = state.log.run_dir / "hardware-diagnostics"
        command = hardware_diagnostic_command(
            usb_id, payload.mode, payload.role, diagnostic_root,
            allow_experimental_hardware=payload.allow_experimental_hardware,
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
            raise HTTPException(status_code=503, detail="hardware diagnostics did not complete") from error
        report = None
        for line in reversed(result.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict) and candidate.get("contract_version") == "hardware-diagnostic.v1":
                report = candidate
                break
        if report is None:
            state.log.event(
                "hardware_diagnostic_failed", level="error", usb_id=usb_id,
                exit_code=result.returncode,
            )
            raise HTTPException(
                status_code=503,
                detail="hardware diagnostics produced no machine-readable report",
            )
        report_path = diagnostic_root / report["run_id"] / "diagnostic-report.json"
        state.log.event(
            "hardware_diagnostic_completed", usb_id=usb_id,
            diagnostic_run_id=report["run_id"], outcome=report["overall_status"],
        )
        return {"report": report, "report_path": str(report_path), "run_id": state.log.run_id}

    @app.post("/api/hardware/diagnostics")
    def hardware_diagnostics_legacy(payload: HardwareDiagnosticRequest, request: Request) -> dict:
        return hardware_diagnostics(payload, request)

    @app.get("/api/groups/public")
    def public_groups(request: Request) -> dict:
        state = runtime(request)
        with state.lock:
            groups = [group.public() for group in state.groups.values() if group.visibility == "public"]
        return {"scope": "local", "groups": groups}

    @app.post("/api/groups")
    def create_group(payload: CreateGroup, request: Request) -> dict:
        state = runtime(request)
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
        with state.lock:
            state.stop_endpoint()
        credentials = state.read_authority()
        try:
            room = state.authoritative_room()
            attempt = room.get("attempt")
            if attempt and attempt.get("phase") not in {"completed", "canceled", "failed"}:
                state.relay.room_command(
                    room["room_id"], credentials["member_token"],
                    f"/attempts/{attempt['attempt_id']}:phase", {"phase": "canceled"},
                    expected_version=room["room_version"],
                )
                room = state.authoritative_room()
            state.relay.room_command(
                room["room_id"], credentials["member_token"], "/ready", {"ready": False},
                expected_version=room["room_version"])
            state.last_published_phase = "canceled"
        except RelayError:
            state.log.event("authority_teardown_sync_failed", level="warning")
        return {"status": "stopped", "run_id": state.log.run_id}

    @app.post("/api/v1/session/stop")
    def stop_session_v1(request: Request) -> dict:
        return stop_session(request)

    @app.post("/api/session/start")
    def start_session(payload: StartSession, request: Request) -> dict:
        state = runtime(request)
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
        previous = state.read_endpoint()
        if state.endpoint_running():
            raise HTTPException(status_code=409, detail="the current session is still running")
        if state.read_authority().get("member_token"):
            try:
                room = state.authoritative_room()
                if result := launch_authoritative_attempt(state, room):
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
        )

    @app.post("/api/v1/app/repair")
    def repair_app(payload: RepairRequest, request: Request) -> dict:
        state = runtime(request)
        previous = state.read_endpoint()
        switch_role = previous.get("switch_room_role", "creator")
        selected_usb_id = attach_selected_hardware(state)
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
        try:
            result = subprocess.run(
                command, cwd=prepare.parent.parent, capture_output=True, text=True,
                timeout=45, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            state.log.event("repair_failed", level="error", action=payload.action,
                            error=type(error).__name__)
            raise HTTPException(status_code=503, detail="adapter repair did not complete") from error
        if result.returncode != 0:
            state.log.event("repair_failed", level="error", action=payload.action,
                            exit_code=result.returncode)
            raise HTTPException(status_code=503, detail="adapter health gate did not pass")
        state.log.event("repair_completed", action=payload.action, usb_id=plan["usb_id"])
        return {"status": "repaired", "action": payload.action,
                "usb_id": plan["usb_id"], "run_id": state.log.run_id}

    @app.post("/api/support-bundle")
    def support_bundle(request: Request) -> dict:
        state = runtime(request)
        path = state.log.support_bundle(summary=readiness_payload(state))
        return {"status": "created", "path": str(path), "run_id": state.log.run_id}

    @app.post("/api/v1/support-bundle")
    def support_bundle_v1(request: Request) -> dict:
        return support_bundle(request)

    @app.post("/api/v1/app/shutdown")
    def shutdown_app(request: Request, background_tasks: BackgroundTasks) -> dict:
        state = runtime(request)
        with state.lock:
            state.stop_endpoint()
            state.shutdown_requested = True
        state.log.event("full_shutdown_requested")
        if state.relay.base_url in {"http://127.0.0.1:8788", "http://localhost:8788"}:
            try:
                state.relay.shutdown()
            except RelayError as error:
                state.log.event("development_relay_shutdown_skipped", reason=str(error))
        if os.environ.get("SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN") == "1":
            background_tasks.add_task(lambda: (time.sleep(0.1), os.kill(os.getpid(), 15)))
        return {"status": "stopping", "run_id": state.log.run_id}

    return app


app = create_app()


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
