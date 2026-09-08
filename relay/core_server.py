"""Minimal in-memory Core pair relay; intentionally separate from Room authority."""

from __future__ import annotations

import asyncio
from collections import deque
import os

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect

from relay.core_contracts import CreatePairRequest, JoinPairRequest
from relay.pair_store import PairStore, PairStoreError
from switchtrade.core.contracts import PairSeat
from switchtrade.transport.wire import Envelope, TransportError


def create_app(store: PairStore | None = None) -> FastAPI:
    app, pairs = FastAPI(), store or PairStore()
    sockets: dict[tuple[str, str], WebSocket] = {}
    ready: set[WebSocket] = set()
    pending: dict[tuple[str, str], deque[bytes]] = {}
    seen_seats: dict[str, set[str]] = {}
    app.state.core_sockets = sockets

    def clear_pending(pair_id: str) -> None:
        pending.pop((pair_id, PairSeat.HOST.value), None)
        pending.pop((pair_id, PairSeat.GUEST.value), None)

    def pending_count() -> int:
        # ponytail: bounded global scan; replace with a counter only if relay throughput warrants it.
        return sum(len(queue) for queue in pending.values())

    def token(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "PAIR_AUTH_INVALID")
        return authorization[7:]

    def error(error: PairStoreError) -> HTTPException:
        status = 429 if error.code == "PAIR_RATE_LIMITED" else 409 if error.code in {"PAIR_CODE_CONSUMED", "PAIR_CAPACITY"} else 401 if error.code == "PAIR_AUTH_INVALID" else 400
        return HTTPException(status, error.code)

    def client_id(request: Request) -> str:
        return request.client.host if request.client else "anonymous"

    @app.get("/core/health")
    def health() -> dict[str, str]:
        # Build/deployment identity only, never Pair identifiers or credentials.
        return {"status": "ok", "service": "switchtrade-core-relay",
                "contract_version": "switchtrade-pair.v1",
                "source_revision": os.environ.get("SWITCHTRADE_RELAY_REVISION", "unknown")}

    @app.post("/core/v1/pairs")
    def create(request: CreatePairRequest, http_request: Request) -> dict[str, object]:
        try:
            credentials = pairs.create(request.capabilities.as_domain(), client_id(http_request))
        except PairStoreError as exc:
            raise error(exc) from exc
        return {"contract_version": "switchtrade-pair.v1", **credentials.__dict__, "code_expires_at": pairs.code_expires_at(credentials.pair_id, credentials.access_token)}

    @app.post("/core/v1/pairs:join")
    def join(request: JoinPairRequest, http_request: Request) -> dict[str, object]:
        try:
            credentials = pairs.join(request.code, request.capabilities.as_domain(), client_id(http_request))
            status = pairs.status(credentials.pair_id, credentials.access_token)
        except PairStoreError as exc:
            raise error(exc) from exc
        return {"contract_version": "switchtrade-pair.v1", **credentials.__dict__, "negotiated_protocols": status["negotiated_protocols"]}

    @app.get("/core/v1/pairs/{pair_id}")
    def status(pair_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
        try:
            return pairs.status(pair_id, token(authorization))
        except PairStoreError as exc:
            raise error(exc) from exc

    @app.websocket("/core/v1/pairs/{pair_id}/ws")
    async def websocket(pair_id: str, websocket: WebSocket) -> None:
        connection_id = str(id(websocket))
        try:
            seat = pairs.attach(pair_id, token(websocket.headers.get("authorization")), connection_id)
        except (PairStoreError, HTTPException):
            await websocket.close(code=4401)
            return
        key = (pair_id, seat.value)
        try:
            if seat.value in seen_seats.get(pair_id, set()):
                clear_pending(pair_id)
            previous = sockets.get(key)
            # Publish the replacement first: the old socket's finally must not
            # retire a newer socket or disconnect that replacement's peer.
            sockets[key] = websocket
            if previous is not None:
                clear_pending(pair_id)
                await asyncio.wait_for(previous.close(code=4000), 5)
            seen_seats.setdefault(pair_id, set()).add(seat.value)
            await websocket.accept()
            # Ownership is published early for replacement cleanup, but peer
            # routing must wait for the seat hello and the entire pending tail.
            # Frames arriving during a drain stay queued, never overtake it.
            async with asyncio.timeout(5):
                await websocket.send_json({"seat": seat.value})
                while True:
                    if sockets.get(key) is not websocket:
                        return
                    queued = pending.get(key)
                    if not queued:
                        pending.pop(key, None)
                        break
                    await websocket.send_bytes(queued.popleft())
            ready.add(websocket)
            while True:
                raw = await websocket.receive_bytes()
                if sockets.get(key) is not websocket:
                    return
                try:
                    envelope = Envelope.decode(raw)
                except TransportError:
                    await websocket.close(code=4400)
                    return
                if envelope.source_seat is not seat:
                    await websocket.close(code=4403)
                    return
                peer = PairSeat.GUEST if seat is PairSeat.HOST else PairSeat.HOST
                peer_key = (pair_id, peer.value)
                target = sockets.get(peer_key)
                if target not in ready:
                    queue = pending.setdefault(peer_key, deque())
                    if len(queue) >= 8 or pending_count() >= 64:
                        await websocket.close(code=4408)
                        return
                    queue.append(raw)
                    continue
                await asyncio.wait_for(target.send_bytes(raw), timeout=5)
        except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError, OSError):
            pass
        finally:
            ready.discard(websocket)
            pairs.detach(pair_id, connection_id)
            if sockets.get(key) is websocket:
                sockets.pop(key, None)
                peer = PairSeat.GUEST if seat is PairSeat.HOST else PairSeat.HOST
                target = sockets.pop((pair_id, peer.value), None)
                clear_pending(pair_id)
                seen_seats.pop(pair_id, None)
                if target is not None:
                    ready.discard(target)
                    # A lost peer must interrupt pre-active/human waits even
                    # when neither side produces DATA. Never forge a peer wire
                    # frame/sequence; terminate only the captured old stream.
                    try:
                        await asyncio.wait_for(target.close(code=4001), 5)
                    except (RuntimeError, OSError, asyncio.TimeoutError):
                        pass
            try:
                await asyncio.wait_for(websocket.close(), 5)
            except (RuntimeError, OSError, asyncio.TimeoutError):
                pass

    return app


app = create_app()
