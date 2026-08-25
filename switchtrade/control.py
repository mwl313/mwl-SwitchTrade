"""Local SwitchTrade control API for the desktop UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import os
import json
import subprocess
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from switchtrade import __version__
from switchtrade.diagnostics import RunLogger
from switchtrade.endpoint import runtime_plan
from switchtrade.hardware import DEFAULT_PROFILE_PATH, load_profiles
from switchtrade.relay_client import RelayClient, RelayError


UI_ROOT = Path(__file__).resolve().parents[1] / "ui" / "dist-desktop"


class CreateGroup(BaseModel):
    name: str = Field(min_length=1, max_length=22)
    visibility: str = Field(pattern="^(private|public)$")


class JoinGroup(BaseModel):
    passcode: str = Field(min_length=4, max_length=8, pattern="^[A-Za-z0-9]+$")


class StartSession(BaseModel):
    role: str = Field(pattern="^(host|guest)$")
    passcode: str = Field(min_length=4, max_length=8, pattern="^[A-Za-z0-9]+$")
    usb_id: str | None = Field(default=None, pattern="^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")


@dataclass
class Group:
    name: str
    passcode: str
    visibility: str
    state: str = "waiting_for_switch"
    participants: int = 1

    def public(self) -> dict:
        data = asdict(self)
        if self.visibility != "public":
            data.pop("passcode")
        return data


class Runtime:
    def __init__(self, profile_path: Path, runs_root: Path | None, relay_url: str):
        self.profiles = load_profiles(profile_path)
        self.groups: dict[str, Group] = {}
        self.lock = threading.Lock()
        self.log = RunLogger("control-api", runs_root, {"profile_path": str(profile_path)})
        self.relay_url = relay_url
        self.relay = RelayClient(relay_url)
        self.endpoint: subprocess.Popen | None = None
        self.endpoint_session: str | None = None
        self.endpoint_state = self.log.run_dir / "endpoint-state.json"

def _wsl_path(path: Path) -> str:
    value = str(path.resolve())
    if len(value) >= 3 and value[1:3] == ":\\":
        return f"/mnt/{value[0].lower()}/{value[3:].replace(chr(92), '/')}"
    return value


def endpoint_command(role: str, passcode: str, relay_url: str,
                     usb_id: str | None = None, state_file: Path | None = None) -> list[str]:
    args = ["--role", role, "--session-id", passcode, "--relay-url", relay_url]
    if usb_id:
        args += ["--usb-id", usb_id.lower()]
    if state_file:
        args += ["--state-file", _wsl_path(state_file) if os.name == "nt" else str(state_file)]
    if os.name == "nt":
        distro = os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade")
        root = os.environ.get("SWITCHTRADE_WSL_ROOT", "/opt/switchtrade")
        return ["wsl.exe", "-d", distro, "--cd", root, "--", "sudo",
                "./scripts/run-beta-endpoint.sh", *args]
    return [str(Path(__file__).resolve().parents[1] / "scripts" / "run-beta-endpoint.sh"), *args]


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
        if runtime.endpoint and runtime.endpoint.poll() is None:
            runtime.endpoint.terminate()
        runtime.log.close("api_stopped")

    app = FastAPI(title="SwitchTrade Control API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def runtime(request: Request) -> Runtime:
        return request.app.state.runtime

    @app.get("/api/status")
    def status(request: Request) -> dict:
        state = runtime(request)
        endpoint = {}
        try:
            endpoint = json.loads(state.endpoint_state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        running = bool(state.endpoint and state.endpoint.poll() is None)
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

    @app.get("/api/hardware/profiles")
    def hardware_profiles(request: Request) -> dict:
        state = runtime(request)
        return {"profiles": [profile.public() for profile in state.profiles]}

    @app.get("/api/groups/public")
    def public_groups(request: Request) -> dict:
        state = runtime(request)
        with state.lock:
            groups = [group.public() for group in state.groups.values() if group.visibility == "public"]
        return {"scope": "local_demo", "groups": groups}

    @app.post("/api/groups")
    def create_group(payload: CreateGroup, request: Request) -> dict:
        state = runtime(request)
        try:
            code = state.relay.create_session()
        except RelayError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        group = Group(payload.name.strip(), code, payload.visibility)
        with state.lock:
            state.groups[code] = group
        state.log.event("group_created", group_name=group.name, visibility=group.visibility, passcode=code)
        return {"scope": "local_demo", "group": asdict(group), "run_id": state.log.run_id}

    @app.post("/api/groups/join")
    def join_group(payload: JoinGroup, request: Request) -> dict:
        state = runtime(request)
        code = payload.passcode.upper()
        try:
            state.relay.status(code)
        except RelayError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        with state.lock:
            group = state.groups.get(code)
            if group is None:
                group = Group("Private Trade Group", code, "private")
                state.groups[code] = group
            if group.participants >= 2:
                raise HTTPException(status_code=409, detail="group is full")
            group.participants += 1
        state.log.event("group_joined", group_name=group.name, passcode=code)
        return {"scope": "local_demo", "group": asdict(group), "run_id": state.log.run_id}

    @app.post("/api/session/stop")
    def stop_session(request: Request) -> dict:
        state = runtime(request)
        state.log.event("session_stop_requested")
        if state.endpoint and state.endpoint.poll() is None:
            state.endpoint.terminate()
            try:
                state.endpoint.wait(timeout=10)
            except subprocess.TimeoutExpired:
                state.endpoint.kill()
        state.endpoint = None
        state.endpoint_session = None
        return {"status": "stopped", "run_id": state.log.run_id}

    @app.post("/api/session/start")
    def start_session(payload: StartSession, request: Request) -> dict:
        state = runtime(request)
        if state.endpoint and state.endpoint.poll() is None:
            raise HTTPException(status_code=409, detail="a session is already running")
        code = payload.passcode.upper()
        try:
            state.relay.status(code)
            plan = runtime_plan(payload.role, payload.usb_id)
        except (RelayError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        state.endpoint_state.unlink(missing_ok=True)
        command = endpoint_command(payload.role, code, state.relay_url, payload.usb_id,
                                   state.endpoint_state)
        try:
            state.endpoint = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1])
        except OSError as error:
            raise HTTPException(status_code=503, detail=f"endpoint launch failed: {error}") from error
        state.endpoint_session = code
        state.log.event("session_started", role=payload.role, passcode=code,
                        usb_id=plan["usb_id"], pid=state.endpoint.pid)
        return {"status": "starting", "session_id": code, "hardware": plan,
                "run_id": state.log.run_id}

    @app.post("/api/support-bundle")
    def support_bundle(request: Request) -> dict:
        state = runtime(request)
        path = state.log.support_bundle()
        return {"status": "created", "path": str(path), "run_id": state.log.run_id}

    if UI_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=UI_ROOT, html=True), name="frontend")

    return app


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run("switchtrade.control:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
