"""Real endpoint/relay/LDN/Reliable under RFU pressure, without physical devices.

Only Linux OS/radio primitives and console/frontend input are modeled. This
is not stock-process qualification or evidence of a commercial Pokemon trade.
"""
import asyncio
from contextlib import ExitStack
import json
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
from bridge.frlgsim import ni, rfu as native


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

    async def timed_ni_finish(self, generation, game, ticker, timestamp):
        """Real path: 60Hz retries, 400ms radio service, lost first native ACK.

        Only console/frontend inputs and the console's scheduling are modeled.
        A Netplay receipt cannot trigger the native END_ACK/NULL transitions.
        """
        game.output.clear()
        loop = asyncio.get_running_loop()
        started = loop.time()
        end = native.child_ni_llsf(native.LCOM_NI_END, 0, 0, 0, 0)
        null = native.child_ni_llsf(native.LCOM_NULL, 1, 0, 0, 0)
        end_ack = ni.parent_recv_ack_slot(native.LCOM_NI_END, 0, 0)
        old_ack = ni.parent_recv_ack_slot(native.LCOM_NI, 1, 2)
        got_end_ack = asyncio.Event()
        null_arrived = asyncio.Event()
        parent_sent = parent_received = 0
        end_deliveries = 0
        first_timestamp = timestamp

        async def console():
            nonlocal timestamp, parent_sent, end_deliveries
            cursor = 0
            while not null_arrived.is_set():
                for payload, _ in game.output[cursor:]:
                    if payload.startswith(b"WT"):
                        slot = payload[12:12 + payload[9]]
                        end_deliveries += slot == end
                        if slot == null:
                            null_arrived.set()
                cursor = len(game.output)
                if null_arrived.is_set():
                    break
                # Drop the first native END reply. Only delivery of another
                # actual END retry permits the physical input to acknowledge it.
                game.press(parent_t(timestamp, end_ack if end_deliveries >= 2 else old_ack), 7)
                timestamp += 1
                parent_sent += 1
                await asyncio.sleep(1 / 60)

        async def frontend_receive():
            nonlocal parent_received
            while True:
                packet = await self.peer.receive(r.RFU1_HOST_SEND)
                await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
                parent_received += 1
                if packet[2][:len(end_ack)] == end_ack:
                    got_end_ack.set()

        async def frontend_send():
            while not got_end_ack.is_set():
                await self.peer.send(r.RFU1_CLIENT_SEND, len(end) << 24 | generation.child, end)
                await asyncio.sleep(1 / 60)
            await self.peer.send(r.RFU1_CLIENT_SEND, len(null) << 24 | generation.child, null)

        tasks = [asyncio.create_task(fn()) for fn in (console, frontend_receive, frontend_send)]
        try:
            await eventually(null_arrived.is_set, tasks=(ticker, tasks[1]), timeout=4.5)
            self.assertGreaterEqual(end_deliveries, 2)
            self.assertLess(loop.time() - started, 4.5)
            await tasks[0]
            await tasks[2]
            await eventually(lambda: parent_received == parent_sent, tasks=(ticker, tasks[1]))
            await eventually(lambda: any(p.startswith(b"WK") and
                int.from_bytes(p[12:16], "little") == timestamp - 1 for p, _ in game.output), tasks=(ticker,))
            game.output.clear()
            # A deferred/lost receipt can be requested again, without pushing
            # the same timestamp into gpSP's game-facing buffer a second time.
            game.press(parent_t(first_timestamp, old_ack), 7)
            await eventually(lambda: any(p.startswith(b"WK") and
                int.from_bytes(p[12:16], "little") == first_timestamp for p, _ in game.output), tasks=(ticker,))
            self.assertEqual(parent_received, parent_sent)
            self.assertGreater(generation.cadence.ni_paced, 0)
            self.assertGreater(generation.cadence.receipts_coalesced, 0)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return timestamp

    async def ni_roundtrip(self, generation, game, ticker, set_period):
        """Drive native NI at the game boundary, not a replacement endpoint.

        Receiver ACKs are emitted only after the actual end-to-end delivery.
        This covers the modeled handshake, not the commercial game's outcome.
        """
        timestamp = 1

        async def from_child(slot, repeats=1):
            game.output.clear()
            paced_before = generation.cadence.ni_paced
            received_before = generation._received
            for _ in range(repeats):
                await self.peer.send(r.RFU1_CLIENT_SEND, len(slot) << 24 | generation.child, slot)
            await self.driver.local.barrier()
            await eventually(lambda: generation._received >= received_before + repeats, tasks=(ticker,))
            admitted = repeats - (generation.cadence.ni_paced - paced_before)
            self.assertGreaterEqual(admitted, 1)
            await eventually(lambda: sum(p.startswith(b"WT") for p, _ in game.output) == admitted,
                             tasks=(ticker,))
            frames = [p for p, _ in game.output if p.startswith(b"WT")]
            self.assertEqual([p[12:12 + len(slot)] for p in frames], [slot] * admitted)
            timestamps = [int.from_bytes(p[4:8], "little") for p in frames]
            self.assertTrue(all(a < b for a, b in zip(timestamps, timestamps[1:])))

        async def from_parent(slot):
            nonlocal timestamp
            game.output.clear()
            game.press(parent_t(timestamp, slot), 7)
            self.assertEqual((await self.peer.receive(r.RFU1_HOST_SEND))[2][:len(slot)], slot)
            await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
            await eventually(lambda: any(p.startswith(b"WK") for p, _ in game.output), tasks=(ticker,))
            timestamp += 1

        sender = ni.NISender(bytes(range(26)))
        timed_finish = False
        while not sender.done:
            slot = sender.next_slot()
            header = native.parse_llsf_child(slot)
            if header["state"] == native.LCOM_NI_END:
                set_period(.4)
                try:
                    timestamp = await self.timed_ni_finish(generation, game, ticker, timestamp)
                finally:
                    set_period(1 / 60)
                timed_finish = True
                continue
            if header["state"] == native.LCOM_NULL and timed_finish:
                continue  # Already sent in response to an actual native END_ACK.
            # Changed NI data must pass; identical rapid copies may be paced.
            repeats = 20 if header["state"] == native.LCOM_NI else 1
            await from_child(slot, repeats)
            if header["state"] != native.LCOM_NULL:
                await from_parent(ni.parent_recv_ack_slot(header["state"], header["n"], header["phase"]))
        for slot in ni.parent_join_status_slots():
            await from_parent(slot)
            word = int.from_bytes(slot[:3], "little")
            if (word >> 14) & 15 != native.LCOM_NULL:
                await from_child(ni.recv_ack_slot((word >> 14) & 15, (word >> 11) & 3, (word >> 9) & 3))
        await from_child(native.uni_slot(bytes(14)))
        await from_parent(native.parent_uni_slot([bytes(14)]))
        progress = generation.translator.progress.snapshot()
        for side in ("child", "parent"):
            self.assertEqual(progress[side]["unknown_slots"], 0)
            for kind in ("ni_start", "ni", "ni_end", "null", "ni_start_ack", "ni_ack", "ni_end_ack", "uni"):
                self.assertGreater(progress[side]["kinds"][kind], 0)
        game.output.clear()
        return timestamp

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
                        # An independent local sender, not our endpoint's FFF0
                        # default. The first room also crosses the 16-bit wrap.
                        sim.rel.out_seq = sim.rel.window_lo = 0xFFFE if number == 1 else 0x2345
                        period = 1 / 60
                        def set_period(value):
                            nonlocal period
                            period = value
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
                    parent_timestamp = await self.ni_roundtrip(generation, game, ticker, set_period)
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
                        game.press(parent_t(parent_timestamp + index, slot), 7)
                        self.assertEqual((await self.peer.receive(r.RFU1_HOST_SEND))[2][:8], slot)
                        await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
                    await eventually(lambda: any(p.startswith(b"WK") and
                        int.from_bytes(p[12:16], "little") == parent_timestamp + 8
                        for p, _ in game.output),
                                     tasks=(ticker,))
                    status = origin._generation.simulation.flow_status()
                    self.assertGreater(status["reliable_tx_new"], count)
                    self.assertGreaterEqual(status["reliable_tx_retransmits"], 0)
                    self.assertGreater(status["reliable_rto_ms"], 0)
                    ticker.cancel()
                    await asyncio.gather(ticker, return_exceptions=True)
                    with self.assertLogs("switchtrade.endpoints.switch_ldn.generation", level="INFO") as logs:
                        sim.close()
                        await asyncio.to_thread(session.stop)  # Physical room ends, not a Core shortcut.
                        await asyncio.wait_for(asyncio.gather(host.wait_generation_end(), guest.wait_generation_end()), 20)
                    stopped = [json.loads(line.split(" ", 2)[2]) for line in logs.output
                               if '"event": "stopped"' in line]
                    self.assertEqual(len(stopped), 1, logs.output)
                    self.assertGreater(stopped[0]["reliable_tx_new"], count)
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
