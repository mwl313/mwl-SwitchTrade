import asyncio
from contextlib import asynccontextmanager
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
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from switchtrade.rfu_tunnel import Direction, Envelope, Kind, direction_for_role
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
from relay.authority import AuthorityError, AuthorityStore

HEARTBEAT_TIMEOUT = 30.0
PEER_SEND_TIMEOUT = 2.0
SESSION_ID_CHARS = string.ascii_uppercase + string.digits

CLOSE_NOT_FOUND = 4404
CLOSE_SLOT_TAKEN = 4409
CLOSE_HEARTBEAT_TIMEOUT = 4408
CLOSE_PEER_OFFLINE = 4000
CLOSE_BAD_FRAME = 4400
CLOSE_RATE_LIMITED = 4429
MAX_MESSAGE_BYTES = (1 << 20) + 256
SESSION_TTL = 6 * 60 * 60
MAX_CONTROL_BODY_BYTES = 64 * 1024
RFU_CONTRACT = "rfu-tunnel.v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        authority.close()

app = FastAPI(title="SwitchTrade Relay", version="0.2.0-beta.1", lifespan=lifespan)
logger = logging.getLogger("uvicorn.error")


ERROR_CODES = {
    "trade room not found": ("room_not_found", "room", False, "check_room_code"),
    "public room not found": ("room_not_found", "room", False, "refresh_rooms"),
    "trade room is full": ("room_full", "room", False, "choose_another_room"),
    "trade room is not active": ("room_not_active", "room", False, "leave_room"),
    "trade room is no longer available": ("room_not_active", "room", False, "leave_room"),
    "room version conflict": ("room_version_conflict", "room", True, "refresh_room"),
    "both members must be ready": ("waiting_for_partner_role", "coordination", True, "wait"),
    "one trainer must choose Group Leader and the other must choose Joining": (
        "complementary_role_required", "coordination", True, "choose_role"),
    "a connection attempt is already active": ("attempt_active", "coordination", True, "refresh_room"),
    "connection attempt is stale": ("attempt_stale", "coordination", True, "retry"),
    "member credential is required": ("member_credential_required", "authentication", False, "rejoin_room"),
    "member credential is invalid": ("member_credential_invalid", "authentication", True, "reconnect"),
    "reconnect credential is invalid": ("reconnect_credential_invalid", "authentication", False, "rejoin_room"),
    "rate limit exceeded": ("rate_limited", "relay", True, "retry_later"),
    "rate limit capacity exceeded": ("rate_limited", "relay", True, "retry_later"),
}


def _error_fields(status: int, detail: str) -> tuple[str, str, bool, str | None]:
    if detail in ERROR_CODES:
        return ERROR_CODES[detail]
    if status == 404:
        return "not_found", "relay", False, "check_request"
    if status == 409:
        return "state_conflict", "coordination", True, "refresh_room"
    if status == 429:
        return "rate_limited", "relay", True, "retry_later"
    if status >= 500:
        return "relay_internal_error", "relay", True, "retry"
    return "invalid_request", "relay", False, "check_request"


def _error_response(request: Request, status: int, detail: str) -> JSONResponse:
    code, stage, recoverable, action = _error_fields(status, detail)
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    return JSONResponse(status_code=status, content={
        "code": code, "message": detail, "detail": detail, "stage": stage,
        "recoverable": recoverable, "primary_action": action,
        "correlation_id": correlation_id,
    }, headers={"X-Correlation-ID": correlation_id})


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException) -> JSONResponse:
    return _error_response(request, error.status_code, str(error.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
    return _error_response(request, 422, "request validation failed")


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRoomPayload(StrictPayload):
    name: str = Field(min_length=1, max_length=22)
    visibility: Literal["private", "public"] = "private"
    trainer_display_name: str = Field(min_length=1, max_length=20)
    game: Literal["FireRed", "LeafGreen"]
    language: Literal["English", "Japanese", "French", "German", "Italian", "Spanish"]
    offering: str = Field(default="", max_length=80)
    wanted: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=120)


class JoinRoomPayload(StrictPayload):
    room_code: str = Field(pattern=r"^[A-Za-z0-9]{6}$")
    trainer_display_name: str = Field(min_length=1, max_length=40)


class JoinPublicRoomPayload(StrictPayload):
    trainer_display_name: str = Field(min_length=1, max_length=20)


class ReconnectPayload(StrictPayload):
    reconnect_token: str = Field(min_length=32, max_length=128)


class ReadyPayload(StrictPayload):
    ready: bool = True
    switch_room_role: Literal["creator", "finder"] | None = None


class TransferPayload(StrictPayload):
    target_member_id: str = Field(min_length=36, max_length=36)


class PhasePayload(StrictPayload):
    phase: Literal[
        "discovering_real_room", "advertising_mirror_room", "connecting_switches",
        "trading_room", "reconnecting", "recovering", "closing", "completed",
        "canceled", "failed",
    ]


class RemoveOfflinePayload(StrictPayload):
    target_member_id: str = Field(min_length=36, max_length=36)


def _legacy_enabled() -> bool:
    return os.environ.get("SWITCHTRADE_ENABLE_LEGACY_RELAY") == "1"


def _require_legacy() -> None:
    if not _legacy_enabled():
        raise HTTPException(status_code=404, detail="not found")


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
authority.fail_active_attempts("relay.restart")


class RateLimiter:
    def __init__(self, limit: int = 120, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, identity: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= 4096 and identity not in self._hits:
                self._hits = {
                    key: [stamp for stamp in stamps if now - stamp < self.window]
                    for key, stamps in self._hits.items()
                    if any(now - stamp < self.window for stamp in stamps)
                }
                if len(self._hits) >= 4096:
                    raise HTTPException(status_code=429, detail="rate limit capacity exceeded")
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


def _expected_version(request: Request) -> int:
    value = request.headers.get("if-match", "").strip().strip('"')
    if not value:
        raise HTTPException(status_code=428, detail="If-Match room version is required")
    try:
        version = int(value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="If-Match must be a room version") from error
    if version < 1:
        raise HTTPException(status_code=400, detail="If-Match must be a room version")
    return version


def _translate_authority(call):
    try:
        return call()
    except AuthorityError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error


@app.get("/health")
async def health() -> dict:
    authority.ping()
    return {
        "status": "ready",
        "service": "switchtrade-relay",
        "room_contract": "room-control.v1",
        "rfu_contract": RFU_CONTRACT,
        "capabilities": ["manual-switch-role.v1", "public-directory.v1"],
        "payload_mode": "opaque",
    }


@app.get("/metrics")
async def metrics() -> dict:
    return {"service": "switchtrade-relay", **authority.operational_stats(),
            "live_rfu_sessions": len(sessions)}


@app.middleware("http")
async def structured_request_log(request: Request, call_next):
    started = time.monotonic()
    request.state.correlation_id = request.headers.get("x-correlation-id", "").strip() or str(uuid.uuid4())
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_CONTROL_BODY_BYTES:
                return _error_response(request, 413, "request body is too large")
            body.extend(chunk)
        request._body = bytes(body)
    authority.sweep_presence()
    route = request.url.path.split("?")[0]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(json.dumps({
            "event": "http_request_failed", "method": request.method, "route": route,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }, separators=(",", ":")))
        raise
    logger.info(json.dumps({
        "event": "http_request", "method": request.method, "route": route,
        "status": response.status_code,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }, separators=(",", ":")))
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


@app.post("/v1/trade-rooms")
async def create_trade_room(payload: CreateRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"create:{_client_id(request)}")
    response = _translate_authority(
        lambda: authority.create(payload.model_dump(), _command_id(request), _client_id(request)))
    sessions.setdefault(response["room"]["room_code"], Session(response["room"]["room_code"]))
    return response


@app.post("/v1/trade-rooms:join")
async def join_trade_room(payload: JoinRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"join:{_client_id(request)}")
    return _translate_authority(
        lambda: authority.join(payload.model_dump(), _command_id(request), _client_id(request)))


@app.get("/v1/public-trade-rooms")
async def list_public_trade_rooms(
        request: Request,
        query: str = Query(default="", max_length=80),
        game: str = Query(default="", pattern=r"^(|FireRed|LeafGreen)$"),
        language: str = Query(
            default="", pattern=r"^(|English|Japanese|French|German|Italian|Spanish)$"),
        availability: Literal["open", "all"] = "open",
        sort: Literal["recent", "oldest", "name"] = "recent",
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=50),
) -> dict:
    identity = request.client.host if request.client else "unknown"
    rate_limiter.check(f"public-list:{identity}")
    return _translate_authority(lambda: authority.list_public(
        query=query, game=game, language=language, availability=availability,
        sort=sort, cursor=cursor, limit=limit))


@app.get("/v1/public-trade-rooms/{listing_id}")
async def get_public_trade_room(listing_id: str, request: Request) -> dict:
    identity = request.client.host if request.client else "unknown"
    rate_limiter.check(f"public-details:{identity}")
    return _translate_authority(lambda: authority.public_details(listing_id))


@app.post("/v1/public-trade-rooms/{listing_id}:join")
async def join_public_trade_room(
        listing_id: str, payload: JoinPublicRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"public-join:{_client_id(request)}")
    return _translate_authority(lambda: authority.join_public(
        listing_id, payload.trainer_display_name, _command_id(request), _client_id(request)))


@app.post("/v1/trade-rooms/{room_id}:reconnect")
async def reconnect_trade_room(room_id: str, payload: ReconnectPayload, request: Request) -> dict:
    rate_limiter.check(f"reconnect:{room_id}")
    return _translate_authority(
        lambda: authority.reconnect(room_id, payload.reconnect_token, _command_id(request)))


@app.get("/v1/trade-rooms/{room_id}")
async def get_trade_room(room_id: str, request: Request) -> dict:
    return _translate_authority(lambda: authority.snapshot(room_id, _bearer(request)))


@app.get("/v1/trade-rooms/{room_id}/events")
async def get_trade_room_events(room_id: str, request: Request, after: int = 0) -> dict:
    return _translate_authority(lambda: authority.events(room_id, _bearer(request), after))


async def _mutate(room_id: str, request: Request, action: str, payload: dict | None = None) -> dict:
    return _translate_authority(lambda: authority.mutate(
        room_id, _bearer(request), _command_id(request), action, payload,
        expected_version=_expected_version(request)))


@app.post("/v1/trade-rooms/{room_id}/ready")
async def ready_trade_room(room_id: str, payload: ReadyPayload, request: Request) -> dict:
    return await _mutate(room_id, request, "ready", payload.model_dump())


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
async def transfer_creator(room_id: str, attempt_id: str, payload: TransferPayload,
                           request: Request) -> dict:
    return await _mutate(room_id, request, "transfer_creator",
                         {**payload.model_dump(), "attempt_id": attempt_id})


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:lock-role")
async def lock_role(room_id: str, attempt_id: str, request: Request) -> dict:
    return await _mutate(room_id, request, "lock_role", {"attempt_id": attempt_id})


@app.post("/v1/trade-rooms/{room_id}/attempts/{attempt_id}:phase")
async def set_attempt_phase(room_id: str, attempt_id: str, payload: PhasePayload,
                            request: Request) -> dict:
    room = await _mutate(room_id, request, "phase",
                         {**payload.model_dump(), "attempt_id": attempt_id})
    if payload.phase in {"completed", "canceled", "failed"}:
        await _disconnect_session(room["room_code"], f"attempt {payload.phase}")
    return room


@app.post("/v1/trade-rooms/{room_id}/members:remove-offline")
async def remove_offline_member(room_id: str, payload: RemoveOfflinePayload,
                                request: Request) -> dict:
    room = await _mutate(room_id, request, "remove_offline", payload.model_dump())
    await _disconnect_session(room["room_code"], "room membership changed")
    return room


@app.delete("/v1/trade-rooms/{room_id}/members/me")
async def leave_trade_room(room_id: str, request: Request) -> dict:
    room = await _mutate(room_id, request, "leave")
    await _disconnect_session(room["room_code"], "member left")
    return room


@app.delete("/v1/trade-rooms/{room_id}")
async def close_trade_room(room_id: str, request: Request) -> dict:
    room = await _mutate(room_id, request, "close")
    await _disconnect_session(room["room_code"], "room closed")
    return room


@app.post("/shutdown")
async def shutdown(background_tasks: BackgroundTasks) -> dict:
    if os.environ.get("SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN") != "1":
        raise HTTPException(status_code=409, detail="relay shutdown is not enabled")
    def close_and_stop() -> None:
        time.sleep(0.1)
        authority.close()
        os.kill(os.getpid(), 15)

    background_tasks.add_task(close_and_stop)
    return {"status": "stopping"}


class Session:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.host: WebSocket | None = None
        self.guest: WebSocket | None = None
        self.participants = 0
        self.advertisement: bytes | None = None
        self.ready_frames: dict[str, bytes] = {}
        self.lock = asyncio.Lock()
        self.created = self.last_activity = time.monotonic()


sessions: dict[str, Session] = {}


async def _disconnect_session(sid: str, reason: str) -> None:
    session = sessions.pop(sid, None)
    if session is None:
        return
    async with session.lock:
        peers = [peer for peer in (session.host, session.guest) if peer is not None]
        session.host = session.guest = None
        session.advertisement = None
        session.ready_frames.clear()
    for peer in peers:
        try:
            await peer.close(code=CLOSE_PEER_OFFLINE, reason=reason)
        except RuntimeError:
            pass


def _prune_sessions() -> None:
    cutoff = time.monotonic() - SESSION_TTL
    for sid, session in list(sessions.items()):
        if session.host is None and session.guest is None and session.last_activity < cutoff:
            sessions.pop(sid, None)


@app.post("/session/create")
async def create_session() -> dict:
    _require_legacy()
    _prune_sessions()
    while True:
        sid = "".join(secrets.choice(SESSION_ID_CHARS) for _ in range(6))
        if sid not in sessions:
            break
    sessions[sid] = Session(sid)
    return {"session_id": sid}


@app.post("/session/{sid}/join")
async def join_session(sid: str) -> dict:
    _require_legacy()
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
async def session_status(sid: str, request: Request) -> dict:
    if authority.has_code(sid):
        _translate_authority(lambda: authority.member_for_code(sid, _bearer(request)))
        sessions.setdefault(sid, Session(sid))
    else:
        _require_legacy()
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
                     protocol: str = "mwlb", attempt_id: str | None = None) -> None:
    identity = None
    if role not in {"host", "guest"}:
        await websocket.close(code=CLOSE_NOT_FOUND, reason="invalid role")
        return

    authoritative = authority.has_code(sid)
    if authoritative:
        authorization = websocket.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        try:
            rate_limiter.check(f"ws:{token[-16:] or 'missing'}")
            if not attempt_id:
                raise AuthorityError(409, "connection attempt is required")
            identity = authority.member_for_code(sid, token, attempt_id)
        except HTTPException:
            await websocket.close(code=CLOSE_RATE_LIMITED, reason="rate limit exceeded")
            return
        except AuthorityError:
            await websocket.close(code=4401, reason="member credential is invalid")
            return
        expected_role = "host" if identity and identity["seat"] == "member_a" else "guest"
        if role != expected_role:
            await websocket.close(code=4403, reason="relay seat does not match member credential")
            return
        sessions.setdefault(sid, Session(sid))
    elif not _legacy_enabled():
        await websocket.close(code=CLOSE_NOT_FOUND, reason="session not found")
        return

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
    frames = bytes_forwarded = 0
    disconnect_reason = "peer_disconnected"
    logger.info(json.dumps({
        "event": "rfu_peer_connected", "room_id": identity["room_id"] if identity else None,
        "attempt_id": attempt_id, "role": role, "protocol": protocol,
    }, separators=(",", ":")))
    if protocol == "rfu" and role == "guest" and session.advertisement is not None:
        await websocket.send_bytes(session.advertisement)
    peer_ready = session.ready_frames.get(peer_role)
    if protocol == "rfu" and getattr(session, peer_role) is not None and peer_ready is not None:
        await websocket.send_bytes(peer_ready)

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=HEARTBEAT_TIMEOUT)
            except asyncio.TimeoutError:
                disconnect_reason = "heartbeat_timeout"
                await websocket.close(code=CLOSE_HEARTBEAT_TIMEOUT, reason="heartbeat timeout")
                break

            if not isinstance(data, bytes) or len(data) > MAX_MESSAGE_BYTES:
                disconnect_reason = "invalid_frame_size"
                await websocket.close(code=CLOSE_BAD_FRAME, reason="invalid frame size")
                break
            if protocol == "rfu":
                try:
                    envelope = Envelope.decode(data)
                    expected = direction_for_role(role)
                    if envelope.session_id != sid or envelope.direction != expected:
                        raise ValueError("session or direction mismatch")
                except (TypeError, ValueError):
                    disconnect_reason = "invalid_rfu_envelope"
                    await websocket.close(code=CLOSE_BAD_FRAME, reason="invalid RFU envelope")
                    break
                if role == "host" and envelope.kind == Kind.ADVERTISEMENT:
                    session.advertisement = data
                if envelope.kind == Kind.PEER_READY:
                    session.ready_frames[role] = data

            peer = getattr(session, peer_role)
            if peer is None:
                continue
            try:
                await asyncio.wait_for(peer.send_bytes(data), timeout=PEER_SEND_TIMEOUT)
            except (asyncio.TimeoutError, RuntimeError):
                disconnect_reason = "peer_send_timeout"
                await peer.close(code=CLOSE_PEER_OFFLINE, reason="peer send timed out")
                continue
            frames += 1
            bytes_forwarded += len(data)
            session.last_activity = time.monotonic()
    except WebSocketDisconnect as error:
        disconnect_reason = f"websocket_{error.code}"
    except RuntimeError:
        disconnect_reason = "websocket_runtime_error"
    finally:
        async with session.lock:
            if getattr(session, role) is websocket:
                setattr(session, role, None)
                session.ready_frames.pop(role, None)
            session.last_activity = time.monotonic()
        if (protocol == "rfu" and identity and attempt_id and
                authority.fail_transport_attempt(
                    identity["room_id"], attempt_id, "relay.peer_lost")):
            await _disconnect_session(sid, "RFU peer disconnected")
        logger.info(json.dumps({
            "event": "rfu_peer_disconnected", "room_id": identity["room_id"] if identity else None,
            "attempt_id": attempt_id, "role": role, "protocol": protocol,
            "reason": disconnect_reason, "frames_forwarded": frames,
            "bytes_forwarded": bytes_forwarded,
        }, separators=(",", ":")))


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
