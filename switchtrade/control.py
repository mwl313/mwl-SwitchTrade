"""Local SwitchTrade control API for the desktop UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import secrets
import string
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from switchtrade import __version__
from switchtrade.diagnostics import RunLogger
from switchtrade.hardware import DEFAULT_PROFILE_PATH, load_profiles


CODE_CHARS = string.ascii_uppercase + string.digits


class CreateGroup(BaseModel):
    name: str = Field(min_length=1, max_length=22)
    visibility: str = Field(pattern="^(private|public)$")


class JoinGroup(BaseModel):
    passcode: str = Field(min_length=4, max_length=8, pattern="^[A-Za-z0-9]+$")


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
    def __init__(self, profile_path: Path, runs_root: Path | None):
        self.profiles = load_profiles(profile_path)
        self.groups: dict[str, Group] = {}
        self.lock = threading.Lock()
        self.log = RunLogger("control-api", runs_root, {"profile_path": str(profile_path)})

    def new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(6))
            if code not in self.groups:
                return code


def create_app(profile_path: str | Path = DEFAULT_PROFILE_PATH, runs_root: str | Path | None = None) -> FastAPI:
    profile_path = Path(profile_path)
    run_path = Path(runs_root) if runs_root else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = Runtime(profile_path, run_path)
        app.state.runtime = runtime
        yield
        runtime.log.close("api_stopped")

    app = FastAPI(title="SwitchTrade Control API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def runtime(request: Request) -> Runtime:
        return request.app.state.runtime

    @app.get("/api/status")
    def status(request: Request) -> dict:
        state = runtime(request)
        return {
            "status": "offline_demo_ready",
            "version": __version__,
            "run_id": state.log.run_id,
            "radio_checked": False,
            "tunnel_connected": False,
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
        with state.lock:
            code = state.new_code()
            group = Group(payload.name.strip(), code, payload.visibility)
            state.groups[code] = group
        state.log.event("group_created", group_name=group.name, visibility=group.visibility, passcode=code)
        return {"scope": "local_demo", "group": asdict(group), "run_id": state.log.run_id}

    @app.post("/api/groups/join")
    def join_group(payload: JoinGroup, request: Request) -> dict:
        state = runtime(request)
        code = payload.passcode.upper()
        with state.lock:
            group = state.groups.get(code)
            if group is None:
                raise HTTPException(status_code=404, detail="group not found")
            if group.participants >= 2:
                raise HTTPException(status_code=409, detail="group is full")
            group.participants += 1
        state.log.event("group_joined", group_name=group.name, passcode=code)
        return {"scope": "local_demo", "group": asdict(group), "run_id": state.log.run_id}

    @app.post("/api/session/stop")
    def stop_session(request: Request) -> dict:
        state = runtime(request)
        state.log.event("session_stop_requested")
        return {"status": "stopped", "run_id": state.log.run_id}

    @app.post("/api/support-bundle")
    def support_bundle(request: Request) -> dict:
        state = runtime(request)
        path = state.log.support_bundle()
        return {"status": "created", "path": str(path), "run_id": state.log.run_id}

    return app


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run("switchtrade.control:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
