import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from fastapi import BackgroundTasks
import hashlib
import io
import ipaddress
import os
from pathlib import Path
import json
import logging
import secrets
import string
import threading
import time
import uuid
import zipfile
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from switchtrade.rfu_tunnel import (
    Direction, Envelope, Kind, MAX_ENVELOPE_BYTES, direction_for_role,
)
from switchtrade.rfu_tunnel_v2 import (
    MAX_ENVELOPE_BYTES as MAX_V2_ENVELOPE_BYTES,
    Envelope as EnvelopeV2,
    Kind as KindV2,
    SequenceGate as SequenceGateV2,
    SourceSeat,
    TunnelV2Error,
)
from switchtrade.c2_protocol import SideReady, launch_identity_hash
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
MAX_MESSAGE_BYTES = MAX_ENVELOPE_BYTES
SESSION_TTL = 6 * 60 * 60
MAX_SESSIONS = 4096
MAX_CONTROL_BODY_BYTES = 64 * 1024
MAX_DIAGNOSTIC_UPLOAD_BYTES = 16 * 1024 * 1024
RFU_CONTRACT = "rfu-tunnel.v1"
RFU_V2_CONTRACT = "rfu-tunnel.v2"
DIAGNOSTIC_CONTRACT = "diagnostic-upload.v1"
V2_RECONNECT_SECONDS = float(os.environ.get("SWITCHTRADE_V2_RECONNECT_SECONDS", "15"))
V2_RETAINED_FRAMES = 32
V2_RETAINED_BYTES = 128 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        authority.close()

app = FastAPI(title="SwitchTrade Relay", version="0.3.0-validation.1", lifespan=lifespan)
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
    "attempt phase cannot move backward": (
        "attempt_phase_conflict", "coordination", True, "refresh_room"),
    "member credential is required": ("member_credential_required", "authentication", False, "rejoin_room"),
    "member credential is invalid": ("member_credential_invalid", "authentication", True, "reconnect"),
    "reconnect credential is invalid": ("reconnect_credential_invalid", "authentication", False, "rejoin_room"),
    "reconnect deadline expired": (
        "reconnect_deadline_expired", "authentication", False, "rejoin_room"),
    "rate limit exceeded": ("rate_limited", "relay", True, "retry_later"),
    "rate limit capacity exceeded": ("rate_limited", "relay", True, "retry_later"),
    "relay session capacity exceeded": ("relay_capacity", "relay", True, "retry_later"),
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


@app.exception_handler(Exception)
async def unexpected_error(request: Request, _error: Exception) -> JSONResponse:
    return _error_response(request, 500, "internal relay error")


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


class V2P0Proof(StrictPayload):
    contract_version: Literal["p0-attestation.v2"]
    run_id: uuid.UUID
    release: str = Field(min_length=1, max_length=64)
    run_generation: int = Field(ge=1)
    stage_generation: int = Field(ge=1)
    adapter_instance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class V2ReadyPayload(StrictPayload):
    ready: bool = True
    switch_room_role: Literal["creator", "finder"] | None = None
    p0: V2P0Proof | None = None


class TransferPayload(StrictPayload):
    target_member_id: str = Field(min_length=36, max_length=36)


class PhasePayload(StrictPayload):
    phase: Literal[
        "discovering_real_room", "advertising_mirror_room", "connecting_switches",
        "trading_room", "reconnecting", "recovering", "closing", "completed",
        "canceled", "failed",
    ]
    failure_code: str | None = Field(default=None, max_length=128)


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
diagnostic_rate_limiter = RateLimiter(limit=12, window=60 * 60)


def _diagnostic_root() -> Path:
    configured = os.environ.get("SWITCHTRADE_DIAGNOSTICS_ROOT")
    return Path(configured) if configured else Path(_authority_path()).parent / "diagnostics"


def _validate_diagnostic(kind: str, body: bytes) -> str:
    if kind == "hardware-diagnostic":
        try:
            report = json.loads(body)
        except (UnicodeDecodeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="diagnostic payload is invalid") from error
        if not isinstance(report, dict) or report.get("contract_version") != "hardware-diagnostic.v1":
            raise HTTPException(status_code=422, detail="diagnostic payload is invalid")
        return "json"
    if kind == "support-bundle":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                unsafe = any(
                    name.startswith(("/", "\\")) or
                    ".." in name.replace("\\", "/").split("/")
                    for name in names
                )
                if (len(entries) > 512 or unsafe or "privacy-manifest.json" not in names or
                        sum(entry.file_size for entry in entries) > 64 * 1024 * 1024):
                    raise ValueError("unsafe support archive")
        except (ValueError, zipfile.BadZipFile) as error:
            raise HTTPException(status_code=422, detail="diagnostic payload is invalid") from error
        return "zip"
    raise HTTPException(status_code=404, detail="diagnostic kind is not supported")


def _store_diagnostic(kind: str, body: bytes, request: Request) -> dict:
    extension = _validate_diagnostic(kind, body)
    root = _diagnostic_root().resolve()
    destination = (root / kind).resolve()
    if destination.parent != root:
        raise HTTPException(status_code=500, detail="diagnostic storage is unavailable")
    destination.mkdir(parents=True, exist_ok=True)
    upload_id = str(uuid.uuid4())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    artifact = destination / f"{stamp}-{upload_id}.{extension}"
    temporary = destination / f".{upload_id}.tmp"
    metadata = destination / f"{stamp}-{upload_id}.metadata.json"
    release_id = request.headers.get("x-switchtrade-release", "unknown")[:128]
    if not all(character.isalnum() or character in "._-" for character in release_id):
        release_id = "invalid"
    client_hash = hashlib.sha256(_client_id(request).encode("utf-8")).hexdigest()[:24]
    try:
        temporary.write_bytes(body)
        os.replace(temporary, artifact)
        metadata.write_text(json.dumps({
            "schema": 1,
            "upload_id": upload_id,
            "kind": kind,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "release_id": release_id,
            "client_hash": client_hash,
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "correlation_id": getattr(request.state, "correlation_id", ""),
        }, separators=(",", ":")) + "\n", encoding="utf-8")
    except OSError as error:
        temporary.unlink(missing_ok=True)
        artifact.unlink(missing_ok=True)
        raise HTTPException(status_code=507, detail="diagnostic storage is unavailable") from error
    return {
        "contract_version": DIAGNOSTIC_CONTRACT,
        "status": "stored",
        "upload_id": upload_id,
        "correlation_id": getattr(request.state, "correlation_id", ""),
    }


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


def _rate_identity(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    configured = os.environ.get("SWITCHTRADE_TRUSTED_PROXIES", "")
    try:
        peer_address = ipaddress.ip_address(peer)
        networks = [
            ipaddress.ip_network(value.strip(), strict=False)
            for value in configured.split(",") if value.strip()
        ]
    except ValueError:
        return peer
    if any(peer_address in network for network in networks):
        try:
            chain = [
                ipaddress.ip_address(value.strip())
                for value in request.headers.get("x-forwarded-for", "").split(",")
                if value.strip()
            ]
        except ValueError:
            return peer
        for address in reversed(chain):
            if not any(address in network for network in networks):
                return str(address)
    return peer


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
        "storage_status": "writable",
        "worker_model": "single-writer",
        "service": "switchtrade-relay",
        "room_contract": "room-control.v1",
        "rfu_contract": RFU_CONTRACT,
        "rfu_contracts": [RFU_CONTRACT, RFU_V2_CONTRACT],
        "server_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "capabilities": [
            "manual-switch-role.v1", "public-directory.v1", DIAGNOSTIC_CONTRACT,
            "passive-websocket-health.v1", RFU_V2_CONTRACT,
        ],
        "payload_mode": "opaque",
    }


@app.websocket("/health/ws")
async def websocket_health(websocket: WebSocket) -> None:
    """Prove the passive WebSocket path without creating a room or retaining state."""
    await websocket.accept()
    await websocket.send_json({
        "contract_version": "passive-websocket-health.v1",
        "status": "ready",
    })
    await websocket.close(code=1000)


@app.post("/v1/diagnostics/{kind}")
async def upload_diagnostic(kind: str, request: Request) -> dict:
    diagnostic_rate_limiter.check(f"diagnostic:{_rate_identity(request)}")
    content_length = request.headers.get("content-length", "")
    try:
        declared_length = int(content_length) if content_length else None
    except ValueError as error:
        raise HTTPException(status_code=400, detail="diagnostic content length is invalid") from error
    if declared_length is not None and declared_length > MAX_DIAGNOSTIC_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="diagnostic upload is too large")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_DIAGNOSTIC_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="diagnostic upload is too large")
        body.extend(chunk)
    if not body:
        raise HTTPException(status_code=422, detail="diagnostic payload is invalid")
    stored = _store_diagnostic(kind, bytes(body), request)
    logger.info(json.dumps({
        "event": "diagnostic_stored", "kind": kind,
        "upload_id": stored["upload_id"], "size": len(body),
    }, separators=(",", ":")))
    return stored


@app.get("/metrics")
async def metrics() -> dict:
    return {"service": "switchtrade-relay", **authority.operational_stats(),
            "live_rfu_sessions": len(sessions), "live_rfu_v2_attempts": len(v2_sessions),
            "admitted_rfu_v2_attempts": len(v2_attempt_admissions)}


@app.middleware("http")
async def structured_request_log(request: Request, call_next):
    started = time.monotonic()
    request.state.correlation_id = request.headers.get("x-correlation-id", "").strip() or str(uuid.uuid4())
    diagnostic_upload = request.url.path.startswith("/v1/diagnostics/")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not diagnostic_upload:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_CONTROL_BODY_BYTES:
                return _error_response(request, 413, "request body is too large")
            body.extend(chunk)
        request._body = bytes(body)
    authority.sweep_presence()
    _prune_sessions()
    route = request.url.path.split("?")[0]
    try:
        response = await call_next(request)
    except Exception as error:
        logger.error(json.dumps({
            "event": "http_request_failed", "method": request.method, "route": route,
            "error_type": type(error).__name__,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }, separators=(",", ":")))
        return _error_response(request, 500, "internal relay error")
    logger.info(json.dumps({
        "event": "http_request", "method": request.method, "route": route,
        "status": response.status_code,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }, separators=(",", ":")))
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


@app.post("/v1/trade-rooms")
async def create_trade_room(payload: CreateRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"create:{_rate_identity(request)}")
    response = _translate_authority(
        lambda: authority.create(payload.model_dump(), _command_id(request), _client_id(request)))
    return response


@app.post("/v1/trade-rooms:join")
async def join_trade_room(payload: JoinRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"join:{_rate_identity(request)}")
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
    identity = _rate_identity(request)
    rate_limiter.check(f"public-list:{identity}")
    return _translate_authority(lambda: authority.list_public(
        query=query, game=game, language=language, availability=availability,
        sort=sort, cursor=cursor, limit=limit))


@app.get("/v1/public-trade-rooms/{listing_id}")
async def get_public_trade_room(listing_id: str, request: Request) -> dict:
    identity = _rate_identity(request)
    rate_limiter.check(f"public-details:{identity}")
    return _translate_authority(lambda: authority.public_details(listing_id))


@app.post("/v1/public-trade-rooms/{listing_id}:join")
async def join_public_trade_room(
        listing_id: str, payload: JoinPublicRoomPayload, request: Request) -> dict:
    rate_limiter.check(f"public-join:{_rate_identity(request)}")
    return _translate_authority(lambda: authority.join_public(
        listing_id, payload.trainer_display_name, _command_id(request), _client_id(request)))


@app.post("/v1/trade-rooms/{room_id}:reconnect")
async def reconnect_trade_room(room_id: str, payload: ReconnectPayload, request: Request) -> dict:
    rate_limiter.check(f"reconnect:{room_id}:{_rate_identity(request)}")
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


@app.post("/v2/trade-rooms/{room_id}/ready")
async def ready_trade_room_v2(room_id: str, payload: V2ReadyPayload,
                              request: Request) -> dict:
    """Admit role readiness only after this member presents bound local P0 evidence."""
    token = _bearer(request)
    command_id = _command_id(request)
    expected_version = _expected_version(request)
    before = _translate_authority(lambda: authority.snapshot(room_id, token))
    member_id = before["local_member_id"]
    room_code = before["room_code"]
    if payload.ready and (payload.p0 is None or payload.switch_room_role is None):
        raise HTTPException(status_code=422, detail="v2 readiness requires P0 evidence and a role")

    with v2_admission_lock:
        admission = v2_pending_admissions.get(room_id)
        existing_attempt = before.get("attempt") or {}
        existing_active = (
            existing_attempt.get("attempt_id") and
            existing_attempt.get("phase") not in {"completed", "canceled", "failed"}
        )
        if (payload.ready and existing_active and
                (admission is None or admission.attempt_id != existing_attempt["attempt_id"])):
            raise HTTPException(
                status_code=409, detail="v2 P0 readiness must precede attempt creation")
        if admission is None:
            admission = V2Admission(room_code, room_id)
            v2_pending_admissions[room_id] = admission
        if admission.room_code != room_code:
            raise HTTPException(status_code=409, detail="v2 room identity changed")
        proof = payload.p0.model_dump(mode="json") if payload.p0 is not None else None
        if proof is not None:
            other_releases = {
                value["release"] for key, value in admission.proofs.items()
                if key != member_id
            }
            if other_releases and proof["release"] not in other_releases:
                raise HTTPException(status_code=409, detail="v2 endpoint releases do not match")
            if any(value["run_id"] == proof["run_id"] for key, value in admission.proofs.items()
                   if key != member_id):
                raise HTTPException(status_code=409, detail="v2 members must use distinct P0 runs")

        room = _translate_authority(lambda: authority.mutate(
            room_id, token, command_id, "ready", {
                "ready": payload.ready,
                "switch_room_role": payload.switch_room_role,
            }, expected_version=expected_version))
        admission.last_activity = time.monotonic()
        if payload.ready:
            admission.proofs[member_id] = proof
            admission.roles[member_id] = str(payload.switch_room_role)
        else:
            admission.proofs.clear()
            admission.roles.clear()
            admission.launches.clear()
            _retire_v2_admission(room_code)

        attempt = room.get("attempt") or {}
        attempt_id = attempt.get("attempt_id")
        active = (attempt_id and attempt.get("role_locked") is True and
                  attempt.get("phase") not in {"completed", "canceled", "failed"})
        if active:
            active_ids = {
                member["member_id"] for member in room["members"]
                if member.get("online_state") != "left"
            }
            if len(active_ids) != 2 or set(admission.proofs) != active_ids:
                raise HTTPException(status_code=409, detail="both v2 P0 proofs are required")
            admission.attempt_id = attempt_id
            admission.role_lock_version = attempt.get("role_lock_version")
            admission.activation_generation = attempt.get("activation_generation")
            v2_attempt_admissions[(room_code, attempt_id)] = admission

        room["v2_admission"] = {
            "contract_version": "app-readiness.v2",
            "p0_ready_members": len(admission.proofs),
            "attempt_admitted": bool(active),
            "activation_generation": admission.activation_generation if active else None,
        }
        return room


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
        await _disconnect_v2_room(room["room_code"], f"attempt {payload.phase}", attempt_id)
    return room


@app.post("/v1/trade-rooms/{room_id}/members:remove-offline")
async def remove_offline_member(room_id: str, payload: RemoveOfflinePayload,
                                request: Request) -> dict:
    room = await _mutate(room_id, request, "remove_offline", payload.model_dump())
    await _disconnect_session(room["room_code"], "room membership changed")
    await _disconnect_v2_room(room["room_code"], "room membership changed")
    return room


@app.delete("/v1/trade-rooms/{room_id}/members/me")
async def leave_trade_room(room_id: str, request: Request) -> dict:
    room = await _mutate(room_id, request, "leave")
    await _disconnect_session(room["room_code"], "member left")
    await _disconnect_v2_room(room["room_code"], "member left")
    return room


@app.delete("/v1/trade-rooms/{room_id}")
async def close_trade_room(room_id: str, request: Request) -> dict:
    room = await _mutate(room_id, request, "close")
    await _disconnect_session(room["room_code"], "room closed")
    await _disconnect_v2_room(room["room_code"], "room closed")
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


@dataclass(frozen=True)
class V2Peer:
    websocket: WebSocket
    reset_event: asyncio.Event


class V2Session:
    """One process-local, attempt-scoped v2 transport namespace."""

    def __init__(self, room_code: str, room_id: str, attempt_id: str) -> None:
        self.room_code = room_code
        self.room_id = room_id
        self.attempt_id = attempt_id
        self.peers: dict[SourceSeat, V2Peer | None] = {
            SourceSeat.MEMBER_A: None, SourceSeat.MEMBER_B: None,
        }
        self.generations = {SourceSeat.MEMBER_A: 0, SourceSeat.MEMBER_B: 0}
        self.gates = {
            seat: SequenceGateV2(attempt_id, seat)
            for seat in (SourceSeat.MEMBER_A, SourceSeat.MEMBER_B)
        }
        self.retained: dict[SourceSeat, list[bytes]] = {
            SourceSeat.MEMBER_A: [], SourceSeat.MEMBER_B: [],
        }
        self.retained_bytes = {SourceSeat.MEMBER_A: 0, SourceSeat.MEMBER_B: 0}
        self.side_ready_epochs: dict[SourceSeat, int | None] = {
            SourceSeat.MEMBER_A: None, SourceSeat.MEMBER_B: None,
        }
        self.advertisement_hash: str | None = None
        self.lock = asyncio.Lock()
        self.created = self.last_activity = time.monotonic()


class V2Admission:
    """Process-local P0 and attempt binding; relay restart invalidates it by design."""

    def __init__(self, room_code: str, room_id: str) -> None:
        self.room_code = room_code
        self.room_id = room_id
        self.proofs: dict[str, dict] = {}
        self.roles: dict[str, str] = {}
        self.launches: dict[str, dict] = {}
        self.attempt_id: str | None = None
        self.role_lock_version: int | None = None
        self.activation_generation: int | None = None
        self.last_activity = time.monotonic()


v2_sessions: dict[tuple[str, str], V2Session] = {}
v2_pending_admissions: dict[str, V2Admission] = {}
v2_attempt_admissions: dict[tuple[str, str], V2Admission] = {}
v2_admission_lock = threading.RLock()


def _retire_v2_admission(room_code: str, attempt_id: str | None = None) -> None:
    with v2_admission_lock:
        for key in [
                key for key in v2_attempt_admissions
                if key[0] == room_code and (attempt_id is None or key[1] == attempt_id)]:
            v2_attempt_admissions.pop(key, None)
        for room_id, admission in list(v2_pending_admissions.items()):
            if (admission.room_code == room_code and
                    (attempt_id is None or admission.attempt_id == attempt_id)):
                v2_pending_admissions.pop(room_id, None)


async def _disconnect_v2_session(session: V2Session, reason: str) -> None:
    v2_sessions.pop((session.room_code, session.attempt_id), None)
    async with session.lock:
        peers = [peer.websocket for peer in session.peers.values() if peer is not None]
        for seat in session.peers:
            if session.peers[seat] is not None:
                session.peers[seat].reset_event.set()
            session.peers[seat] = None
            session.retained[seat].clear()
            session.retained_bytes[seat] = 0
    for peer in peers:
        try:
            await peer.close(code=CLOSE_PEER_OFFLINE, reason=reason)
        except RuntimeError:
            pass


async def _receive_v2_or_reset(websocket: WebSocket,
                               reset_event: asyncio.Event) -> bytes | None:
    """Receive until the socket closes or its run-scoped session ownership is revoked."""
    receive_task = asyncio.create_task(websocket.receive_bytes())
    reset_task = asyncio.create_task(reset_event.wait())
    tasks = {receive_task, reset_task}
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if reset_task in done:
            return None
        return receive_task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _disconnect_v2_room(room_code: str, reason: str,
                              attempt_id: str | None = None) -> None:
    targets = [
        session for (code, attempt), session in list(v2_sessions.items())
        if code == room_code and (attempt_id is None or attempt == attempt_id)
    ]
    for session in targets:
        await _disconnect_v2_session(session, reason)
    _retire_v2_admission(room_code, attempt_id)


async def _expire_v2_peer(session: V2Session, seat: SourceSeat, generation: int) -> None:
    await asyncio.sleep(V2_RECONNECT_SECONDS)
    async with session.lock:
        expired = (session.peers[seat] is None and session.generations[seat] == generation)
    if not expired or v2_sessions.get((session.room_code, session.attempt_id)) is not session:
        return
    authority.fail_transport_attempt(session.room_id, session.attempt_id, "relay.peer_lost")
    _retire_v2_admission(session.room_code, session.attempt_id)
    await _disconnect_v2_session(session, "v2 peer reconnect deadline expired")


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


def _session(sid: str) -> Session:
    _prune_sessions()
    if existing := sessions.get(sid):
        return existing
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=503, detail="relay session capacity exceeded")
    session = Session(sid)
    sessions[sid] = session
    return session


@app.post("/session/create")
async def create_session() -> dict:
    _require_legacy()
    _prune_sessions()
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=503, detail="relay session capacity exceeded")
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
        session = _session(sid)
    else:
        _require_legacy()
        session = sessions.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    session.last_activity = time.monotonic()
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
        try:
            _session(sid)
        except HTTPException:
            await websocket.close(code=1013, reason="relay session capacity exceeded")
            return
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


@app.websocket("/v2/trade-rooms/{room_code}/attempts/{attempt_id}/ws")
async def ws_attempt_v2(websocket: WebSocket, room_code: str, attempt_id: str) -> None:
    """Attempt-scoped v2 path; the credential, never a query role, selects the source seat."""
    authorization = websocket.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    try:
        rate_limiter.check(f"ws-v2:{token[-16:] or 'missing'}")
        identity = authority.member_for_code(room_code, token, attempt_id)
        if identity is None:
            raise AuthorityError(404, "trade room not found")
        seat = SourceSeat.parse(identity["seat"])
    except HTTPException:
        await websocket.close(code=CLOSE_RATE_LIMITED, reason="rate limit exceeded")
        return
    except (AuthorityError, TunnelV2Error):
        await websocket.close(code=4401, reason="member credential is invalid")
        return

    key = (room_code, attempt_id)
    try:
        run_id = str(uuid.UUID(websocket.headers.get("x-switchtrade-run-id", "")))
        stage_generation = int(websocket.headers.get("x-switchtrade-stage-generation", ""))
        endpoint_pid = int(websocket.headers.get("x-switchtrade-endpoint-pid", ""))
        launch_nonce = websocket.headers.get("x-switchtrade-launch-nonce", "")
        if (stage_generation < 1 or endpoint_pid < 1 or not 32 <= len(launch_nonce) <= 128 or
                "\x00" in launch_nonce):
            raise ValueError("invalid launch identity")
    except (TypeError, ValueError, AttributeError):
        await websocket.close(code=4403, reason="v2 launch identity is invalid")
        return
    with v2_admission_lock:
        admission = v2_attempt_admissions.get(key)
        proof = admission.proofs.get(identity["member_id"]) if admission is not None else None
        admitted = bool(
            admission is not None and admission.room_id == identity["room_id"] and
            proof is not None and proof["run_id"] == run_id and
            proof["stage_generation"] == stage_generation
        )
        launch = {
            "run_id": run_id,
            "stage_generation": stage_generation,
            "launch_nonce": launch_nonce,
            "endpoint_pid": endpoint_pid,
        }
        prior_launch = admission.launches.get(identity["member_id"]) if admission is not None else None
        launch_matches = prior_launch is None or prior_launch == launch
        if admitted and launch_matches and prior_launch is None:
            admission.launches[identity["member_id"]] = launch
    if not admitted or not launch_matches:
        await websocket.close(code=4403, reason="v2 attempt is not P0-admitted")
        return
    session = v2_sessions.get(key)
    if session is None:
        if len(v2_sessions) >= MAX_SESSIONS:
            await websocket.close(code=1013, reason="relay session capacity exceeded")
            return
        session = V2Session(room_code, identity["room_id"], attempt_id)
        v2_sessions[key] = session
    elif session.room_id != identity["room_id"]:
        await websocket.close(code=CLOSE_BAD_FRAME, reason="attempt identity mismatch")
        return

    peer_seat = seat.peer
    reset_event = asyncio.Event()
    try:
        async with session.lock:
            if session.peers[seat] is not None:
                await websocket.close(code=CLOSE_SLOT_TAKEN, reason="seat already connected")
                return
            session.generations[seat] += 1
            session.peers[seat] = V2Peer(websocket, reset_event)
            session.last_activity = time.monotonic()
            await websocket.accept()
            for retained in session.retained[peer_seat]:
                await asyncio.wait_for(websocket.send_bytes(retained), timeout=PEER_SEND_TIMEOUT)
    except (asyncio.TimeoutError, RuntimeError):
        async with session.lock:
            if (session.peers[seat] is not None and
                    session.peers[seat].websocket is websocket):
                session.peers[seat] = None
        await websocket.close(code=CLOSE_PEER_OFFLINE, reason="retained replay timed out")
        return

    frames = bytes_forwarded = 0
    disconnect_reason = "peer_disconnected"
    fatal_code = None
    logger.info(json.dumps({
        "event": "rfu_v2_peer_connected", "room_id": identity["room_id"],
        "attempt_id": attempt_id, "source_seat": seat.label,
    }, separators=(",", ":")))
    try:
        while True:
            raw = await _receive_v2_or_reset(websocket, reset_event)
            if raw is None:
                disconnect_reason = "peer_reset"
                try:
                    await websocket.close(
                        code=CLOSE_PEER_OFFLINE, reason="peer transport is reconnecting"
                    )
                except RuntimeError:
                    pass
                break
            if not isinstance(raw, bytes) or len(raw) > MAX_V2_ENVELOPE_BYTES:
                raise TunnelV2Error("C_ENVELOPE_INVALID", "v2 frame size is invalid")
            envelope = EnvelopeV2.decode(raw)
            if envelope.attempt_id != attempt_id or envelope.source_seat is not seat:
                raise TunnelV2Error("C_IDENTITY_MISMATCH", "v2 frame identity is invalid")

            peer_send_failed = False
            async with session.lock:
                gate = session.gates[seat]
                prior_epoch = gate.epoch
                gate.accept(envelope)
                if prior_epoch != gate.epoch:
                    session.retained[seat].clear()
                    session.retained_bytes[seat] = 0
                    session.side_ready_epochs[seat] = None

                if envelope.kind is KindV2.ADVERTISEMENT:
                    digest = hashlib.sha256(envelope.payload).hexdigest()
                    if session.advertisement_hash not in {None, digest}:
                        raise TunnelV2Error(
                            "C_ADVERTISEMENT_CHANGED", "advertisement changed inside one attempt"
                        )
                    session.advertisement_hash = digest
                elif envelope.kind is KindV2.SIDE_READY:
                    ready = SideReady.decode(envelope.payload)
                    expected_role = {
                        "creator": "a_room_joiner", "finder": "b_ap_host",
                    }.get(admission.roles.get(identity["member_id"]))
                    expected_launch_hash = launch_identity_hash(
                        launch["run_id"], launch["stage_generation"],
                        launch["launch_nonce"], launch["endpoint_pid"],
                    )
                    if (ready.attempt_id != attempt_id or ready.source_seat != seat.label or
                            ready.switch_role != expected_role or ready.run_id != launch["run_id"] or
                            ready.stage_generation != launch["stage_generation"] or
                            ready.launch_identity_sha256 != expected_launch_hash or
                            ready.activation_generation != admission.activation_generation):
                        raise TunnelV2Error(
                            "C_SIDE_READY_IDENTITY", "SIDE_READY does not match its admitted launch"
                        )
                    if (session.advertisement_hash is None or
                            ready.advertisement_sha256 != session.advertisement_hash):
                        raise TunnelV2Error(
                            "C_SIDE_READY_ADVERTISEMENT",
                            "SIDE_READY does not match the admitted advertisement",
                        )
                    if session.side_ready_epochs[seat] == envelope.source_epoch:
                        raise TunnelV2Error(
                            "C_SIDE_READY_DUPLICATE", "SIDE_READY is duplicate in this source epoch"
                        )
                    session.side_ready_epochs[seat] = envelope.source_epoch
                elif envelope.kind is KindV2.RFU:
                    if any(
                            session.side_ready_epochs[source] != session.gates[source].epoch
                            for source in (SourceSeat.MEMBER_A, SourceSeat.MEMBER_B)):
                        raise TunnelV2Error(
                            "C_BRIDGE_NOT_READY", "RFU arrived before both current SIDE_READY frames"
                        )

                if envelope.kind in {KindV2.PEER_READY, KindV2.ADVERTISEMENT}:
                    if (len(session.retained[seat]) >= V2_RETAINED_FRAMES or
                            session.retained_bytes[seat] + len(raw) > V2_RETAINED_BYTES):
                        raise TunnelV2Error(
                            "C_RETENTION_OVERFLOW", "v2 retained frame bound exceeded"
                        )
                    session.retained[seat].append(raw)
                    session.retained_bytes[seat] += len(raw)
                peer = session.peers[peer_seat]
                if peer is not None:
                    try:
                        await asyncio.wait_for(
                            peer.websocket.send_bytes(raw), timeout=PEER_SEND_TIMEOUT
                        )
                    except (asyncio.TimeoutError, RuntimeError):
                        peer_send_failed = True
                session.last_activity = time.monotonic()
            frames += 1
            bytes_forwarded += len(raw)
            if peer_send_failed:
                disconnect_reason = "peer_send_failed"
                try:
                    await websocket.close(
                        code=CLOSE_PEER_OFFLINE, reason="peer send failed; reprove both sides"
                    )
                except RuntimeError:
                    pass
                break
    except TunnelV2Error as error:
        fatal_code = error.code
        disconnect_reason = error.code.lower()
        try:
            await websocket.close(code=CLOSE_BAD_FRAME, reason=error.code[:123])
        except RuntimeError:
            pass
    except WebSocketDisconnect as error:
        disconnect_reason = f"websocket_{error.code}"
    except RuntimeError:
        disconnect_reason = "websocket_runtime_error"
    finally:
        expire_targets: list[tuple[SourceSeat, int]] = []
        async with session.lock:
            if (session.peers[seat] is not None and
                    session.peers[seat].websocket is websocket):
                session.peers[seat] = None
                if not fatal_code and v2_sessions.get(key) is session:
                    for retained_seat in session.retained:
                        session.retained[retained_seat].clear()
                        session.retained_bytes[retained_seat] = 0
                        session.side_ready_epochs[retained_seat] = None
                    expire_targets.append((seat, session.generations[seat]))
                    peer = session.peers[peer_seat]
                    if peer is not None:
                        gate = session.gates[seat]
                        if gate.epoch is not None:
                            close_envelope = EnvelopeV2(
                                attempt_id, seat, gate.epoch, gate.next_sequence,
                                KindV2.PEER_CLOSE, b"peer transport reset",
                            )
                            gate.accept(close_envelope)
                            try:
                                await asyncio.wait_for(
                                    peer.websocket.send_bytes(close_envelope.encode()),
                                    timeout=PEER_SEND_TIMEOUT,
                                )
                            except (asyncio.TimeoutError, RuntimeError):
                                pass
                        peer.reset_event.set()
                        session.peers[peer_seat] = None
                        expire_targets.append((peer_seat, session.generations[peer_seat]))
            session.last_activity = time.monotonic()
        if fatal_code:
            authority.fail_transport_attempt(
                identity["room_id"], attempt_id, f"relay.{fatal_code.lower()}"
            )
            _retire_v2_admission(room_code, attempt_id)
            await _disconnect_v2_session(session, fatal_code)
        elif v2_sessions.get(key) is session:
            for target_seat, generation in expire_targets:
                asyncio.create_task(_expire_v2_peer(session, target_seat, generation))
        logger.info(json.dumps({
            "event": "rfu_v2_peer_disconnected", "room_id": identity["room_id"],
            "attempt_id": attempt_id, "source_seat": seat.label,
            "reason": disconnect_reason, "frames_forwarded": frames,
            "bytes_forwarded": bytes_forwarded,
        }, separators=(",", ":")))


def main() -> None:
    import uvicorn
    uvicorn.run(
        "relay.server:app",
        host=os.environ.get("SWITCHTRADE_RELAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("SWITCHTRADE_RELAY_PORT", "8788")),
        proxy_headers=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
