"""Minimal in-memory Core pair relay; intentionally separate from Room authority."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect

from relay.core_contracts import CreatePairRequest, JoinPairRequest
from relay.pair_store import PairStore, PairStoreError


def create_app(store: PairStore | None = None) -> FastAPI:
    app, pairs = FastAPI(), store or PairStore()
    sockets: dict[tuple[str, str], WebSocket] = {}

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
        return {"status": "ok"}

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
        try:
            seat = pairs.authenticate(pair_id, token(websocket.headers.get("authorization")))
        except (PairStoreError, HTTPException):
            await websocket.close(code=4401)
            return
        key = (pair_id, seat.value)
        previous = sockets.get(key)
        if previous is not None:
            await previous.close(code=4000)
        sockets[key] = websocket
        await websocket.accept()
        await websocket.send_json({"seat": seat.value})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            if sockets.get(key) is websocket:
                sockets.pop(key, None)

    return app


app = create_app()
