"""Real endpoint/relay/LDN/Reliable under RFU pressure, without physical devices.

Only Linux OS/radio primitives and console/frontend input are modeled. This
is not stock-process qualification or evidence of a commercial Pokemon trade.
"""
import asyncio
from contextlib import ExitStack
import unittest

from switchtrade.connection.b_stage import DirectBStage
from switchtrade.connection.stage_session import StageSession
from switchtrade.core.contracts import PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor
from switchtrade.endpoints.switch_ldn.driver import SwitchLdnEndpointDriver, SwitchLdnPolicy
from switchtrade.endpoints.switch_ldn.generation import build_tunnelsim
from switchtrade.transport import WireClient
from tests import test_gpsp_endpoint as endpoint_helpers
from tests import test_core_end_to_end as relay_helpers
from tests.test_gpsp_rfu import advertisement, gba, parent_t, HOST_SESSION
from tests.test_switch_physical_boundary import PhysicalGameInput, eventually
from tests.virtual_ldn_os import VirtualLdnOS
from switchtrade.endpoints.retroarch_gpsp import rfu as r


class RfuPressurePathTests(unittest.IsolatedAsyncioTestCase):
    _post = relay_helpers.CoreEndToEndTests._post
    _socket = relay_helpers.CoreEndToEndTests._socket
    ready = endpoint_helpers.EndpointTests.ready

    async def asyncSetUp(self):
        await endpoint_helpers.EndpointTests.asyncSetUp(self)
        await self.ready()
        self.local_port = self.port
        await relay_helpers.CoreEndToEndTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await endpoint_helpers.EndpointTests.asyncTearDown(self)
        await relay_helpers.CoreEndToEndTests.asyncTearDown(self)

    async def test_slow_radio_ack_two_generations_real_endpoint_path(self):
        # Use the production event-loop mode: debug task stack capture can
        # throttle the synthetic producer below the intended radio ACK rate.
        asyncio.get_running_loop().set_debug(False)
        os = VirtualLdnOS()
        with ExitStack() as stack:
            os.install(stack)
            origin = SwitchLdnEndpointDriver(SwitchLdnPolicy(
                run_id="pressure-test", release="test", usb_id="0bda:818b",
                hardware_profile="test", phy="phy0", ifname="test-sta",
                proven_radio_iface="proven0", keys_path="/synthetic-test.keys"))
            capability = {"endpoint_kind": "switch_ldn", "runtime_kind": "managed_wsl",
                "protocols": ["switchtrade.gba-frame.v1"], "generation_roles": ["origin"]}
            _, h = await self._post("/core/v1/pairs", {"capabilities": capability})
            _, g = await self._post("/core/v1/pairs:join", {"code": h["code"], "capabilities": {
                **capability, "endpoint_kind": "retroarch_gpsp", "runtime_kind": "native",
                "generation_roles": ["mirror"]}})
            hc = PairCredentials(h["pair_id"], PairSeat.HOST, h["access_token"], h["reconnect_expires_at"])
            gc = PairCredentials(g["pair_id"], PairSeat.GUEST, g["access_token"], g["reconnect_expires_at"])
            host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
            await host_wire.connect(await self._socket(hc))
            await guest_wire.connect(await self._socket(gc))
            host, guest = CoreSupervisor(hc, origin, host_wire), CoreSupervisor(gc, self.driver, guest_wire)
            local = self.driver.local
            session = sim = ticker = None
            failed = False
            try:
                for number in (1, 2):
                    session = StageSession(DirectBStage(run_id="console", release="test", phy="phy1",
                        ap_ifname="test-ap", monitor_ifname="test-mon", tap_ifname="test-tap",
                        keys_path="/synthetic-test.keys", application_data=advertisement()), timeout=25).start()
                    offering = asyncio.create_task(host.offer_generation())
                    accepting = asyncio.create_task(guest.accept_next_offer())
                    try:
                        resources = await asyncio.to_thread(session.wait_ready)
                        game = PhysicalGameInput()
                        sim = build_tunnelsim(resources, game, True)
                        period = 1 / 60
                        async def tick():
                            while True:
                                sim.tick()
                                await asyncio.sleep(period)
                        ticker = asyncio.create_task(tick())
                        await asyncio.wait_for(asyncio.gather(offering, accepting), 25)
                    finally:
                        for task in (offering, accepting):
                            task.cancel()
                        await asyncio.gather(offering, accepting, return_exceptions=True)
                    generation = self.driver.generation
                    await self.peer.receive(r.RFU1_BROADCAST)
                    await self.peer.send(r.RFU1_CONNECT_REQ, generation.host)
                    await eventually(lambda: any(p.startswith(b"WC") for p, _ in game.output), tasks=(ticker,))
                    game.press(gba(r.GBA_ACCEPT, HOST_SESSION.to_bytes(2, "little") +
                        generation.child.to_bytes(2, "little") + b"\0\0"), 15)
                    await self.peer.receive(r.RFU1_CONNECT_ACK)
                    game.output.clear()
                    # A progressing 100 ms console cadence slows local ACKs;
                    # no production scheduler, admission, or wire queue is mocked.
                    period = .1
                    count = 1024
                    for index in range(count):
                        await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child,
                            number.to_bytes(4, "little") + index.to_bytes(4, "little"))
                    high_water = 0
                    waited = False
                    async with asyncio.timeout(60):
                        while len(game.output) < count:
                            self.assertIsNone(host.failure)
                            self.assertIsNone(guest.failure)
                            pending = len(origin._generation.simulation._pending_remote)
                            status = origin._generation.tunnel.flow_status()
                            waited |= status["remote_waits"] > 0
                            self.assertLessEqual(status["core_to_local_queue"], 256)
                            self.assertLessEqual(status["local_to_core_queue"], 256)
                            high_water = max(high_water, pending)
                            self.assertLessEqual(pending, 256)
                            await asyncio.sleep(.01)
                    self.assertEqual(high_water, 256, "fixture did not exercise full RFU pressure")
                    self.assertTrue(waited, "fixture did not exercise waiting Core admission")
                    self.assertEqual([p[-8:] for p, _ in game.output],
                        [number.to_bytes(4, "little") + i.to_bytes(4, "little") for i in range(count)])
                    self.assertTrue(all(flags == 7 for _, flags in game.output))
                    for index in range(1, 9):
                        slot = number.to_bytes(4, "little") + index.to_bytes(4, "little")
                        game.press(parent_t(index, slot), 7)
                        self.assertEqual((await self.peer.receive(r.RFU1_HOST_SEND))[2][:8], slot)
                        await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
                    await eventually(lambda: sum(p.startswith(b"WK") for p, _ in game.output) == 8,
                                     tasks=(ticker,))
                    ticker.cancel()
                    await asyncio.gather(ticker, return_exceptions=True)
                    sim.close()
                    await asyncio.to_thread(session.stop)  # Physical room ends, not a Core shortcut.
                    await asyncio.wait_for(asyncio.gather(host.wait_generation_end(), guest.wait_generation_end()), 20)
                    self.assertIs(self.driver.local, local)
                    self.assertTrue(local.connected)
                    self.assertEqual(host.credentials.pair_id, guest.credentials.pair_id)
            except BaseException as error:
                failed = True
                error.add_note(str({"physical": sim.flow_status() if sim else None,
                    "endpoint": origin._generation.simulation.flow_status() if origin._generation else None,
                    "received": len(game.output) if sim else None}))
                raise
            finally:
                if ticker:
                    ticker.cancel()
                    await asyncio.gather(ticker, return_exceptions=True)
                if sim:
                    sim.close()
                cleanup = await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)
                if session:
                    await asyncio.to_thread(session.stop)
                await asyncio.gather(host_wire.close(), guest_wire.close())
                os.assert_clean()
                if not failed:
                    self.assertEqual(cleanup, [None, None])
