from __future__ import annotations

import asyncio
import json
import socket
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import uvicorn
import websockets

from relay.core_server import create_app
from switchtrade.connection.stage_session import StageResources
from switchtrade.core import CoreSupervisor, PairCredentials, PairSeat
from switchtrade.core.supervisor import SupervisorError, SupervisorState
from switchtrade.endpoints.switch_ldn import SWITCH_LDN_PROTOCOL, SwitchLdnEndpointDriver, SwitchLdnEndpointError, SwitchLdnPolicy
from switchtrade.transport import WireClient


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


class FakeSession:
    def __init__(self, resources: StageResources) -> None:
        self.resources = resources
        self.started = self.stopped = False

    def start(self) -> "FakeSession":
        self.started = True
        return self

    def wait_ready(self) -> StageResources:
        return self.resources

    def stop(self) -> None:
        self.stopped = True


class FakeSimulation:
    def __init__(self, tunnel: object) -> None:
        self.tunnel = tunnel
        self.closed = False

    def tick(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class QualifiedDriver:
    def __init__(self, *, advertisement: bytes) -> None:
        self.sessions: list[FakeSession] = []
        self.simulations: list[FakeSimulation] = []
        self.mirror_offers = []
        resources = StageResources(object(), object(), advertisement)

        def session_factory(_stage: object, **_kwargs: object) -> FakeSession:
            session = FakeSession(resources)
            self.sessions.append(session)
            return session

        def simulation_factory(_resources: StageResources, tunnel: object, _parent: bool) -> FakeSimulation:
            simulation = FakeSimulation(tunnel)
            self.simulations.append(simulation)
            return simulation

        def mirror_stage(_policy: SwitchLdnPolicy, offer: object) -> object:
            self.mirror_offers.append(offer)
            return object()

        policy = SwitchLdnPolicy(
            run_id="c5-test", release="test-release", usb_id="0bda:818b",
            hardware_profile="RTL8192EU", phy="phy7", ifname="wlan7",
            keys_path="/runtime/config/prod.keys",
        )
        self.driver = SwitchLdnEndpointDriver(
            policy, stage_factory=lambda _policy: object(), mirror_stage_factory=mirror_stage,
            session_factory=session_factory, simulation_factory=simulation_factory,
        )


class SwitchCoreCompositionTests(unittest.IsolatedAsyncioTestCase):
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

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        def request() -> dict[str, object]:
            raw = json.dumps(body).encode("utf-8")
            with urlopen(Request(f"http://127.0.0.1:{self.port}{path}", raw, {"content-type": "application/json"}), timeout=2) as response:
                return json.loads(response.read())

        return await asyncio.to_thread(request)

    async def _socket(self, credentials: PairCredentials) -> WebSocketSocket:
        connection = await websockets.connect(f"ws://127.0.0.1:{self.port}/core/v1/pairs/{credentials.pair_id}/ws", additional_headers={"authorization": f"Bearer {credentials.access_token}"}, proxy=None)
        self.assertEqual(json.loads(await connection.recv()), {"seat": credentials.seat.value})
        return WebSocketSocket(connection)

    @staticmethod
    def _capabilities(role: str) -> dict[str, object]:
        return {"endpoint_kind": "switch_ldn", "runtime_kind": "managed_wsl", "protocols": [SWITCH_LDN_PROTOCOL], "generation_roles": [role]}

    async def _pair(self) -> tuple[PairCredentials, PairCredentials]:
        created = await self._post("/core/v1/pairs", {"capabilities": self._capabilities("origin")})
        host = PairCredentials(str(created["pair_id"]), PairSeat.HOST, str(created["access_token"]), str(created["reconnect_expires_at"]), str(created["code"]))
        joined = await self._post("/core/v1/pairs:join", {"code": host.code, "capabilities": self._capabilities("mirror")})
        return host, PairCredentials(str(joined["pair_id"]), PairSeat.GUEST, str(joined["access_token"]), str(joined["reconnect_expires_at"]))

    async def _wait_for_frames(self, tunnel: object, expected: list[tuple[bytes, int]]) -> None:
        async with asyncio.timeout(1):
            frames = []
            while [(frame.payload, frame.flags) for frame in frames] != expected:
                frames.extend(tunnel.poll())  # type: ignore[union-attr]
                if [(frame.payload, frame.flags) for frame in frames] != expected:
                    await asyncio.sleep(0.01)

    async def _wait_for_state(self, supervisor: CoreSupervisor, state: SupervisorState) -> None:
        async with asyncio.timeout(1):
            while supervisor.state is not state:
                await asyncio.sleep(0)

    async def test_real_core_transport_qualifies_two_start_orders_and_cleanup(self) -> None:
        host_credentials, guest_credentials = await self._pair()
        host_driver, guest_driver = QualifiedDriver(advertisement=b"leader-advertisement"), QualifiedDriver(advertisement=b"mirror")
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(await self._socket(host_credentials))
        await guest_wire.connect(await self._socket(guest_credentials))
        host = CoreSupervisor(host_credentials, host_driver.driver, host_wire)
        guest = CoreSupervisor(guest_credentials, guest_driver.driver, guest_wire)
        try:
            with patch("switchtrade.relay_client.RelayClient.room_command") as checkpoint:
                host_offer = asyncio.create_task(host.offer_generation())
                async with asyncio.timeout(1):
                    while not host_driver.sessions:
                        await asyncio.sleep(0)
                self.assertFalse(guest_driver.sessions)
                await asyncio.gather(host_offer, guest.accept_next_offer())
                self.assertEqual((host.state, guest.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
                self.assertEqual(guest_driver.mirror_offers[0].setup_payload, b"leader-advertisement")
                host_generation, guest_generation = host_driver.driver._generation, guest_driver.driver._generation
                host_generation.tunnel.send_rfu(b"host", flags=0x7F)  # type: ignore[union-attr]
                await self._wait_for_frames(guest_generation.tunnel, [(b"host", 0x7F)])  # type: ignore[union-attr]
                guest_generation.tunnel.send_rfu(b"guest", flags=0x00)  # type: ignore[union-attr]
                await self._wait_for_frames(host_generation.tunnel, [(b"guest", 0x00)])  # type: ignore[union-attr]
                checkpoint.assert_not_called()

            await host.close_generation()
            await guest.wait_generation_end()
            self.assertTrue(all(session.stopped for session in host_driver.sessions + guest_driver.sessions))
            self.assertTrue(all(simulation.closed for simulation in host_driver.simulations + guest_driver.simulations))

            guest_offer = asyncio.create_task(guest.accept_next_offer())
            await host.offer_generation()
            await guest_offer
            self.assertEqual((host.state, guest.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
            await host.stop()
            await self._wait_for_state(guest, SupervisorState.PAIRED)
            await guest.stop()
            self.assertTrue(all(session.stopped for session in host_driver.sessions + guest_driver.sessions))
            self.assertTrue(all(simulation.closed for simulation in host_driver.simulations + guest_driver.simulations))
        finally:
            await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_local_tunnel_failure_preserves_core_failure_and_cleanup(self) -> None:
        host_credentials, guest_credentials = await self._pair()
        host_driver, guest_driver = QualifiedDriver(advertisement=b"leader"), QualifiedDriver(advertisement=b"mirror")
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(await self._socket(host_credentials))
        await guest_wire.connect(await self._socket(guest_credentials))
        host = CoreSupervisor(host_credentials, host_driver.driver, host_wire)
        guest = CoreSupervisor(guest_credentials, guest_driver.driver, guest_wire)
        try:
            await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
            generation = host_driver.driver._generation
            generation.tunnel.fail(SwitchLdnEndpointError("SWITCH_ENDPOINT_TICK_FAILED", "injected"))  # type: ignore[union-attr]
            with self.assertRaisesRegex(SupervisorError, "S_PUMP_FAILED"):
                await host.wait_generation_end()
            self.assertEqual(host.failure.code, "S_PUMP_FAILED")  # type: ignore[union-attr]
            self.assertTrue(host_driver.sessions[0].stopped)
            self.assertTrue(host_driver.simulations[0].closed)
        finally:
            await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
