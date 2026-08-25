import asyncio
from fastapi import BackgroundTasks
import os
from pathlib import Path
import json
import logging
import secrets
import string
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from switchtrade.rfu_tunnel import Direction, Envelope, Kind, direction_for_role
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
from relay.authority import AuthorityError, AuthorityStore

HEARTBEAT_TIMEOUT = 30.0
SESSION_ID_CHARS = string.ascii_uppercase + string.digits

CLOSE_NOT_FOUND = 4404
CLOSE_SLOT_TAKEN = 4409
CLOSE_HEARTBEAT_TIMEOUT = 4408
CLOSE_PEER_OFFLINE = 4000
CLOSE_BAD_FRAME = 4400
MAX_MESSAGE_BYTES = (1 << 20) + 256
SESSION_TTL = 6 * 60 * 60

app = FastAPI()
logger = logging.getLogger("switchtrade.relay")


def _authority_path() -> str:
    configured = os.environ.get("SWITCHTRADE_AUTH_DB")
    if configured:
        return configured
    root = Path(os.environ.get(
        "SWITCHTRADE_RELAY_STATE",
        Path.home() / ".local" / "state" / "switchtrade-relay",
    ))
    return str(root / "authority.sqlite3")


authority = AuthorityStore(_authority_path())


class RateLimiter:
    def __init__(self, limit: int = 120, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, identity: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = [stamp for stamp in self._hits.get(identity, []) if now - stamp < self.window]
            if len(hits) >= self.limit:
                raise HTTPException(status_code=429, detail="rate limit exceeded")
            hits.append(now)
            self._hits[identity] = hits


rate_limiter = RateLimiter()


def _bearer(request: Request) -> str:
    value = request.headers.get("authorization", "")
    if not value.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="member credential is required")
    token = value[7:].strip()
    identity = token[-16:] or (request.client.host if request.client else "unknown")
    rate_limiter.check(identity)
    return token


def _command_id(request: Request) -> str:
    value = request.headers.get("idempotency-key", "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be UUIDv7") from error
    if parsed.version != 7:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be UUIDv7")
    return value


def _client_id(request: Request) -> str:
    return request.headers.get("x-switchtrade-client", "anonymous")[:128]


def _translate_authority(call):
    try:
        return call()
    except AuthorityError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ready",
        "service": "switchtrade-relay",
        "room_contract": "room-control.v1",
        "payload_mode": "opaque",
    }


@app.get("/metrics")
async def metrics() -> dict:
    return {"service": "switchtrade-relay", **authority.operational_stats(),
            "live_rfu_sessions": len(sessions)}


@app.middleware("http")
async def structured_request_log(request: Request, call_next):
    started = time.monotonic()
    authority.sweep_presence()
    response = await call_next(request)
    logger.info(json.dumps({
        "event": "http_request", "method": request.method,
        "route": request.url.path.split("?")[0], "status": response.status_code,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }, separators=(",", ":")))
    return response


@app.post("/v1/trade-rooms")
async def create_trade_room(payload: dict, request: Request) -> dict:
    response = _translate_authority(
        lambda: authority.create(payload, _command_id(request), _client_id(request)))
    sessions.setdefault(response["room"]["room_code"], Session(response["room"]["room_code"]))
    return response


@app.post("/v1/trade-rooms:join")
async def join_trade_room(payload: dict, request: Request) -> dict:
    return _translate_authority(
        lambda: authority.join(payload, _command_id(request), _client_id(request)))


@app.post("/v1/trade-rooms/{room_id}:reconnect")
async def reconnect_trade_room(room_id: str, payload: dict) -> dict:
    return _translate_authority(
        lambda: authority.reconnect(room_id, str(payload.get("reconnect_token", ""))))


@app.get("/v1/trade-rooms/{room_id}")
async def get_trade_room(room_id: str, request: Request) -> dict:
    return _translate_authority(lambda: authority.snapshot(room_id, _bearer(request)))


@app.get("/v1/trade-rooms/{room_id}/events")
async def get_trade_room_events(room_id: str, request: Request, after: int = 0) -> dict:
    return _translate_authority(lambda: authority.events(room_id, _bearer(request), after))


async def _mutate(room_id: str, request: Request, action: str, payload: dict | None = None) -> dict:
    return _translate_authority(lambda: authority.mutate(
        room_id, _bearer(request), _command_id(request), action, payload))


@app.post("/v1/trade-rooms/{room_id}/ready")
async def ready_trade_room(room_id: str, payload: dict, request: Request) -> dict:
    return await _mutate(room_id, request, "ready", payload)


@app.post("/v1/trade-rooms/{room_id}/heartbeat")
async def heartbeat_trade_room(room_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "heartbeat")


@app.post("/v1/trade-rooms/{room_id}/attempts")
async def create_attempt(room_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "attempt")


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:claim-creator")
async def claim_creator(room_id: str, attempt_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "claim_creator", {"attempt_id": attempt_id})


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:transfer-creator")
async def transfer_creator(room_id: str, attempt_id: str, payload: dict, request: Request) -> dict:
    return await _mutate(room_id, request, "transfer_creator", {**payload, "attempt_id": attempt_id})


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:lock-role")
async def lock_role(room_id: str, attempt_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "lock_role", {"attempt_id": attempt_id})


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:phase")
async def set_attempt_phase(room_id: str, attempt_id: str, payload: dict, request: Request) -> dict:
    return await _mutate(room_id, request, "phase", {**payload, "attempt_id": attempt_id})


@app.delete("/v1/trade-rooms/{room_id}/members/me")
async def leave_trade_room(room_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "leave")


@app.delete("/v1/trade-rooms/{room_id}")
async def close_trade_room(room_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "close")


@app.post("/shutdown")
async def shutdown(background_tasks: BackgroundTasks) -> dict:
    if os.environ.get("SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN") != "1":
        raise HTTPException(status_code=409, detail="relay shutdown is not enabled")
    background_tasks.add_task(lambda: (time.sleep(0.1), os.kill(os.getpid(), 15)))
    return {"status": "stopping"}


class Session:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.host: WebSocket | None = None
        self.guest: WebSocket | None = None
        self.participants = 0
        self.advertisement: bytes | None = None
        self.lock = asyncio.Lock()
        self.created = self.last_activity = time.monotonic()


sessions: dict[str, Session] = {}


def _prune_sessions() -> None:
    cutoff = time.monotonic() - SESSION_TTL
    for sid, session in list(sessions.items()):
        if session.host is None and session.guest is None and session.last_activity < cutoff:
            sessions.pop(sid, None)


@app.post("/session/create")
async def create_session() -> dict:
    _prune_sessions()
    while True:
        sid = "".join(secrets.choice(SESSION_ID_CHARS) for _ in range(6))
        if sid not in sessions:
            break
    sessions[sid] = Session(sid)
    return {"session_id": sid}


@app.post("/session/{sid}/join")
async def join_session(sid: str) -> dict:
    session = sessions.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    async with session.lock:
        if session.participants >= 2:
            raise HTTPException(status_code=409, detail="session is full")
        session.participants += 1
        participants = session.participants
    return {"session_id": sid, "participants": participants}


@app.get("/session/{sid}")
async def session_status(sid: str) -> dict:
    if authority.has_code(sid):
        sessions.setdefault(sid, Session(sid))
    session = sessions.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": sid,
        "host_connected": session.host is not None,
        "guest_connected": session.guest is not None,
    }


@app.websocket("/session/{sid}/ws")
async def ws_session(websocket: WebSocket, sid: str, role: str = "host",
                     protocol: str = "mwlb") -> None:
    if role not in {"host", "guest"}:
        await websocket.close(code=CLOSE_NOT_FOUND, reason="invalid role")
        return

    if authority.has_code(sid):
        authorization = websocket.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        try:
            identity = authority.member_for_code(sid, token)
        except AuthorityError:
            await websocket.close(code=4401, reason="member credential is invalid")
            return
        expected_role = "host" if identity and identity["seat"] == "member_a" else "guest"
        if role != expected_role:
            await websocket.close(code=4403, reason="relay seat does not match member credential")
            return
        sessions.setdefault(sid, Session(sid))

    session = sessions.get(sid)
    if session is None:
        await websocket.close(code=CLOSE_NOT_FOUND, reason="session not found")
        return

    if protocol not in {"mwlb", "rfu"}:
        await websocket.close(code=CLOSE_NOT_FOUND, reason="invalid protocol")
        return

    peer_role = "guest" if role == "host" else "host"

    async with session.lock:
        if getattr(session, role) is not None:
            await websocket.close(code=CLOSE_SLOT_TAKEN, reason="slot already taken")
            return
        setattr(session, role, websocket)
        session.last_activity = time.monotonic()

    await websocket.accept()
    if protocol == "rfu" and role == "guest" and session.advertisement is not None:
        await websocket.send_bytes(session.advertisement)

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=HEARTBEAT_TIMEOUT)
            except asyncio.TimeoutError:
                await websocket.close(code=CLOSE_HEARTBEAT_TIMEOUT, reason="heartbeat timeout")
                break

            if not isinstance(data, bytes) or len(data) > MAX_MESSAGE_BYTES:
                await websocket.close(code=CLOSE_BAD_FRAME, reason="invalid frame size")
                break
            if protocol == "rfu":
                try:
                    envelope = Envelope.decode(data)
                    expected = direction_for_role(role)
                    if envelope.session_id != sid or envelope.direction != expected:
                        raise ValueError("session or direction mismatch")
                except (TypeError, ValueError):
                    await websocket.close(code=CLOSE_BAD_FRAME, reason="invalid RFU envelope")
                    break
                if role == "host" and envelope.kind == Kind.ADVERTISEMENT:
                    session.advertisement = data

            peer = getattr(session, peer_role)
            if peer is None:
                continue
            await peer.send_bytes(data)
            session.last_activity = time.monotonic()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        async with session.lock:
            if getattr(session, role) is websocket:
                setattr(session, role, None)
            session.last_activity = time.monotonic()


def main() -> None:
    import uvicorn
    try:
        with SingleInstanceLock("development-relay"):
            uvicorn.run(
                "relay.server:app",
                host=os.environ.get("SWITCHTRADE_RELAY_HOST", "127.0.0.1"),
                port=int(os.environ.get("SWITCHTRADE_RELAY_PORT", "8788")),
                proxy_headers=True,
                reload=False,
            )
    except AlreadyRunningError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
