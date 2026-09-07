from __future__ import annotations

import asyncio
import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn
import websockets
from fastapi import WebSocket

from relay.core_server import create_app
from switchtrade.core.contracts import LinkPacket, PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor, SupervisorState
from switchtrade.endpoints.fake import FAKE_PROTOCOL, FakeEndpointDriver, FakeEndpointHub
from switchtrade.transport import FrameKind, WireClient
from switchtrade.core_cli import _socket as cli_socket


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

    async def test_relay_hello_precedes_concurrent_peer_wire_frames(self) -> None:
        _, created = await self._post("/core/v1/pairs", {"capabilities": CAPABILITIES})
        _, joined = await self._post("/core/v1/pairs:join", {
            "code": created["code"], "capabilities": MIRROR})
        credentials = [PairCredentials(data["pair_id"], seat, data["access_token"],
                                       data["reconnect_expires_at"])
                       for data, seat in ((created, PairSeat.HOST), (joined, PairSeat.GUEST))]
        relay = f"http://127.0.0.1:{self.port}"
        entered, release, host_frames = asyncio.Event(), asyncio.Event(), asyncio.Event()
        draining, drain_release, tail_received = asyncio.Event(), asyncio.Event(), asyncio.Event()
        forwarded = []
        hello_sent, premature, received = False, [], 0
        send_json, send_bytes, receive_bytes = (WebSocket.send_json, WebSocket.send_bytes,
                                               WebSocket.receive_bytes)

        async def delayed_hello(socket, data, *args, **kwargs):
            nonlocal hello_sent
            if data == {"seat": "guest"}:
                entered.set()
                await release.wait()
                await send_json(socket, data, *args, **kwargs)
                hello_sent = True
            else:
                await send_json(socket, data, *args, **kwargs)

        async def observed_send(socket, data):
            if socket.headers.get("authorization") == f"Bearer {joined['access_token']}":
                forwarded.append(data)
                if not hello_sent:
                    premature.append(data)
                elif not draining.is_set():
                    draining.set()
                    await drain_release.wait()
            await send_bytes(socket, data)

        async def observed_receive(socket):
            nonlocal received
            raw = await receive_bytes(socket)
            if socket.headers.get("authorization") == f"Bearer {created['access_token']}":
                received += 1
                if received == 2:
                    host_frames.set()  # First relay forwarding iteration has completed.
                elif received == 3:
                    tail_received.set()
            return raw

        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        with patch.object(WebSocket, "send_json", delayed_hello), \
                patch.object(WebSocket, "send_bytes", observed_send), \
                patch.object(WebSocket, "receive_bytes", observed_receive):
            host_socket = await cli_socket(relay, credentials[0])
            opening = asyncio.create_task(cli_socket(relay, credentials[1]))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await host_wire.connect(host_socket)
                await asyncio.wait_for(host_frames.wait(), 2)
                self.assertEqual(premature, [], "binary wire frame overtook the seat hello")
                self.assertFalse(opening.done())
                release.set()
                await guest_wire.connect(await asyncio.wait_for(asyncio.shield(opening), 2))
                await asyncio.wait_for(draining.wait(), 2)
                await host_wire.send(FrameKind.HEARTBEAT)
                await asyncio.wait_for(tail_received.wait(), 2)
                self.assertEqual(len(forwarded), 1, "live frame overtook the pending tail")
                drain_release.set()
                await asyncio.gather(host_wire.wait_ready(), guest_wire.wait_ready())
                await host_wire.send(FrameKind.GENERATION_OFFER, "ordered", b"offer")
                self.assertEqual((await guest_wire.receive()).payload, b"offer")
            finally:
                release.set()
                drain_release.set()
                sockets = await asyncio.gather(opening, return_exceptions=True)
                await asyncio.gather(host_wire.close(), guest_wire.close())
                await host_socket.close()
                if not isinstance(sockets[0], BaseException):
                    await sockets[0].close()

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
        host_driver, guest_driver = FakeEndpointDriver(hub), FakeEndpointDriver(hub)
        host_supervisor = CoreSupervisor(host, host_driver, host_wire)
        guest_supervisor = CoreSupervisor(guest, guest_driver, guest_wire)
        await asyncio.gather(host_supervisor.offer_generation(), guest_supervisor.accept_next_offer())
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        host_generation, guest_generation = host_driver.generation, guest_driver.generation
        self.assertIsNotNone(host_generation)
        self.assertIsNotNone(guest_generation)
        host_packet = LinkPacket(host_supervisor.generation_id, FAKE_PROTOCOL, b"host", 0x0100)
        await host_generation.inject_local(host_packet)  # type: ignore[union-attr]
        self.assertEqual(await guest_generation.receive_delivered(), host_packet)  # type: ignore[union-attr]
        guest_packet = LinkPacket(guest_supervisor.generation_id, FAKE_PROTOCOL, b"guest")
        await guest_generation.inject_local(guest_packet)  # type: ignore[union-attr]
        self.assertEqual(await host_generation.receive_delivered(), guest_packet)  # type: ignore[union-attr]
        await host_supervisor.close_generation()
        await self._wait_for_state(guest_supervisor, SupervisorState.PAIRED)
        self.assertIsNone(host_supervisor.failure)
        self.assertIsNone(guest_supervisor.failure)
        await asyncio.gather(host_supervisor.offer_generation(), guest_supervisor.accept_next_offer())
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        second_packet = LinkPacket(host_supervisor.generation_id, FAKE_PROTOCOL, b"second")
        await host_driver.generation.inject_local(second_packet)  # type: ignore[union-attr]
        self.assertEqual(await guest_driver.generation.receive_delivered(), second_packet)  # type: ignore[union-attr]
        await host_supervisor.stop()
        await guest_supervisor.stop()
        self.assertEqual((host_supervisor.state, guest_supervisor.state), (SupervisorState.STOPPED, SupervisorState.STOPPED))
        async with asyncio.timeout(1):
            while self.app.state.core_sockets:
                await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
