from __future__ import annotations

import asyncio
import json
import socket
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn
import websockets

from relay.core_server import create_app
from switchtrade.core.contracts import PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor, SupervisorState
from switchtrade.endpoints.fake import FakeEndpointDriver, FakeEndpointHub
from switchtrade.transport import FrameKind, WireClient


CAPABILITIES = {"endpoint_kind": "fake", "runtime_kind": "in_process", "protocols": ["switchtrade.fake.v1"], "generation_roles": ["origin"]}
MIRROR = {**CAPABILITIES, "generation_roles": ["mirror"]}


class WebSocketSocket:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def send(self, data: bytes) -> None:
        await self.connection.send(data)  # type: ignore[union-attr]

    async def recv(self) -> bytes:
        data = await self.connection.recv()  # type: ignore[union-attr]
        if not isinstance(data, bytes):
            raise TypeError("relay sent non-binary wire data")
        return data

    async def close(self) -> None:
        await self.connection.close()  # type: ignore[union-attr]


class CoreEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.app = create_app()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="critical", access_log=False))
        self.server_task = asyncio.create_task(self.server.serve())
        async with asyncio.timeout(2):
            while not self.server.started:
                await asyncio.sleep(0)

    async def asyncTearDown(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.server_task, timeout=2)

    async def _post(self, path: str, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        def request() -> tuple[int, dict[str, object]]:
            raw = json.dumps(body).encode("utf-8")
            try:
                with urlopen(Request(f"http://127.0.0.1:{self.port}{path}", raw, {"content-type": "application/json"}), timeout=2) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as error:
                return error.code, json.loads(error.read())

        return await asyncio.to_thread(request)

    async def _socket(self, credentials: PairCredentials) -> WebSocketSocket:
        connection = await websockets.connect(f"ws://127.0.0.1:{self.port}/core/v1/pairs/{credentials.pair_id}/ws", additional_headers={"authorization": f"Bearer {credentials.access_token}"}, proxy=None)
        self.assertEqual(json.loads(await connection.recv()), {"seat": credentials.seat.value})
        return WebSocketSocket(connection)

    async def _wait_for_state(self, supervisor: CoreSupervisor, state: SupervisorState) -> None:
        async with asyncio.timeout(1):
            while supervisor.state is not state:
                await asyncio.sleep(0)

    async def test_pair_generation_lifecycle_over_real_relay(self) -> None:
        created_status, created = await self._post("/core/v1/pairs", {"capabilities": CAPABILITIES})
        self.assertEqual(created_status, 200)
        self.assertRegex(str(created["code"]), r"^\d{6}$")
        host = PairCredentials(created["pair_id"], PairSeat.HOST, created["access_token"], created["reconnect_expires_at"], created["code"])
        joined_status, joined = await self._post("/core/v1/pairs:join", {"code": host.code, "capabilities": MIRROR})
        self.assertEqual(joined_status, 200)
        guest = PairCredentials(joined["pair_id"], PairSeat.GUEST, joined["access_token"], joined["reconnect_expires_at"])
        reused_status, _ = await self._post("/core/v1/pairs:join", {"code": host.code, "capabilities": MIRROR})
        self.assertGreaterEqual(reused_status, 400)

        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(await self._socket(host))
        await guest_wire.connect(await self._socket(guest))
        await asyncio.gather(host_wire.wait_ready(), guest_wire.wait_ready())
        await host_wire.send(FrameKind.GENERATION_OFFER, "wire-generation", b"setup")
        self.assertEqual((await guest_wire.receive()).kind, FrameKind.GENERATION_OFFER)
        await guest_wire.send(FrameKind.GENERATION_ACCEPT, "wire-generation")
        self.assertEqual((await host_wire.receive()).kind, FrameKind.GENERATION_ACCEPT)
        await host_wire.send(FrameKind.DATA, "wire-generation", b"host-packet")
        self.assertEqual((await guest_wire.receive()).payload, b"host-packet")
        await guest_wire.send(FrameKind.DATA, "wire-generation", b"guest-packet")
        self.assertEqual((await host_wire.receive()).payload, b"guest-packet")
        await host_wire.send(FrameKind.GENERATION_CLOSE, "wire-generation")
        self.assertEqual((await guest_wire.receive()).kind, FrameKind.GENERATION_CLOSE)

        hub = FakeEndpointHub()
        host_supervisor = CoreSupervisor(host, FakeEndpointDriver(hub), host_wire)
        guest_supervisor = CoreSupervisor(guest, FakeEndpointDriver(hub), guest_wire)
        await asyncio.gather(host_supervisor.offer_generation(), guest_supervisor.accept_next_offer())
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        await host_supervisor.close_generation()
        await self._wait_for_state(guest_supervisor, SupervisorState.PAIRED)
        self.assertIsNone(host_supervisor.failure)
        self.assertIsNone(guest_supervisor.failure)
        await asyncio.gather(host_supervisor.offer_generation(), guest_supervisor.accept_next_offer())
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        await host_supervisor.stop()
        await guest_supervisor.stop()
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.STOPPED, SupervisorState.STOPPED))
        async with asyncio.timeout(1):
            while self.app.state.core_sockets:
                await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
