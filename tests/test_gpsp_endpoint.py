"""P2 modeled core/stock peer checks, not actual emulator qualification."""
import asyncio
import contextlib
import json
import socket
import struct
import unittest
from unittest.mock import AsyncMock, patch

from switchtrade.core.contracts import GenerationEnded, GenerationOffer, EndpointKind, LinkPacket, PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor, SupervisorError, SupervisorState
from switchtrade.endpoints.retroarch_gpsp.driver import RetroArchGpspEndpointDriver, PROTOCOL, clean
from switchtrade.endpoints.retroarch_gpsp.errors import GpspError
from switchtrade.endpoints.retroarch_gpsp import netplay as n
from switchtrade.endpoints.retroarch_gpsp import rfu as r
from switchtrade.transport import WireClient
from tests.test_gpsp_rfu import advertisement, gba, parent_t, HOST_SESSION
from tests.test_gpsp_netplay import Observer, command, take
from tests import test_core_end_to_end as relay_helpers
from tests import test_core_supervisor as core_helpers


class StockPeer:
    def __init__(self, port, mode="mirror"):
        self.port, self.mode = port, mode
        self.packets = asyncio.Queue()
        self.writer = self.task = None
        self.assignments = set()
        self.barriers = 0
        self.answer_barriers = True

    async def open(self):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writer.write(struct.pack("!6I", n.MAGIC, 0, 0, 8, 6, n._impl_magic()))
        await self.reader.readexactly(24)
        self.writer.write(command(n.NICK, n._field(b"test")))
        await take(self.reader, n.NICK, 32)
        await take(self.reader, n.INFO, 68)
        self.writer.write(command(n.INFO, b"\0" * 4 + n._field(n.CORE_NAME) + n._field(n.CORE_PROTOCOL)))
        await take(self.reader, n.SYNC, 184)
        self.writer.write(command(n.PLAY, b"\0" * 4))
        await take(self.reader, n.MODE, 60)
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while True:
                kind, size = struct.unpack("!II", await self.reader.readexactly(8))
                if kind == n.PING:
                    self.barriers += 1
                    if self.answer_barriers:
                        self.writer.write(command(n.PONG))
                else:
                    assert kind == n.NETPACKET
                    await self.reader.readexactly(4)
                    raw = await self.reader.readexactly(size)
                    ptype, header, body = r._parse_rfu1(raw)
                    if ptype == r.RFU1_CONNECT_REQ and header == 0:
                        if self.mode == "mirror":
                            await self.send(r.RFU1_CONNECT_NACK, 0)
                        elif self.mode == "host":
                            self.assignments.add(0x4321)
                            await self.send(r.RFU1_CONNECT_ACK, 0x4321)
                    else:
                        if ptype == r.RFU1_DISCONNECT:
                            self.assignments.discard(header)
                        self.packets.put_nowait((ptype, header, body))
        except asyncio.IncompleteReadError:
            return

    async def send(self, kind, header, body=b""):
        raw = r._rfu1(kind, header, body)
        self.writer.write(struct.pack("!III", n.NETPACKET, len(raw), 0) + raw)
        await self.writer.drain()

    async def receive(self, kind):
        async with asyncio.timeout(2):
            while True:
                value = await self.packets.get()
                if value[0] == kind:
                    return value

    async def close(self):
        if self.writer is not None:
            self.writer.close()
            with contextlib.suppress(ConnectionError):
                await self.writer.wait_closed()
        if self.task is not None:
            await self.task


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.observer = Observer()
        self.driver = RetroArchGpspEndpointDriver(observer=self.observer, port=self.port)
        self.peer = StockPeer(self.port)

    async def asyncTearDown(self):
        await self.driver.close()
        await self.peer.close()

    async def ready(self, mode="mirror"):
        await self.driver.prepare()
        self.peer.mode = mode
        await self.peer.open()
        await asyncio.wait_for(self.driver._wait(self.driver._ready.wait()), 2)

    def offer(self, index=1):
        return GenerationOffer(f"room-{index}", PROTOCOL, EndpointKind.SWITCH_LDN, advertisement())

    async def test_search_diagnostics_are_bounded_private_and_generation_scoped(self):
        await self.ready()
        with self.assertLogs("switchtrade.endpoints.retroarch_gpsp.driver", level="INFO") as logs:
            generation = await self.driver.accept(self.offer(), asyncio.Event())
            generation.activate()
            await self.peer.receive(r.RFU1_BROADCAST)
            self.assertEqual((await generation.receive()).payload, r.METADATA_FRAME)
            # Force just the diagnostic deadline; no human timeout or extra packets.
            generation._diagnostic_due = 0
            generation._diagnose("periodic")
            before = len(logs.output)
            for _ in range(100):
                generation._diagnose("periodic")
            self.assertEqual(len(logs.output), before)
            snapshot = json.loads(logs.output[-1].split(" ", 2)[2])
            self.assertEqual(snapshot["state"], "searching")
            self.assertGreaterEqual(snapshot["advertisement_writes"], 1)
            self.assertEqual(snapshot["gpsp_kinds"], {})
            self.assertEqual(snapshot["gpsp_packets"], 0)
            self.assertEqual(snapshot["core_dequeued"], 1)
            self.assertFalse(snapshot["link_ready"])
            self.assertTrue(clean(await generation.close("test_end")))
            next_generation = await self.driver.accept(self.offer(2), asyncio.Event())
            next_generation.activate()
            fresh = json.loads(logs.output[-1].split(" ", 2)[2])
            self.assertEqual(fresh["advertisement_writes"], 0)
            self.assertEqual(fresh["core_dequeued"], 0)
            self.assertEqual(fresh["gpsp_kinds"], {})
            self.assertTrue(clean(await next_generation.close("test_end")))
        combined = "\n".join(logs.output)
        self.assertNotIn(advertisement().hex(), combined)
        self.assertNotIn("HOST", combined)
        self.assertNotIn("payload", combined)
        self.assertNotIn("ProcessIdentity", combined)
        progress = [line for line in logs.output if "gpsp_rfu_progress" in line]
        self.assertEqual(sum('"event": "closed"' in line for line in progress), 2)

    async def test_rfu_diagnostics_show_handshake_data_and_failure_without_payloads(self):
        await self.ready()
        with self.assertLogs("switchtrade.endpoints.retroarch_gpsp.driver", level="INFO") as logs:
            generation = await self.driver.accept(self.offer(), asyncio.Event())
            generation.activate()
            await generation.receive()
            await self.peer.receive(r.RFU1_BROADCAST)
            await self.peer.send(r.RFU1_CONNECT_REQ, generation.host)
            await generation.receive()
            accept = gba(r.GBA_ACCEPT, HOST_SESSION.to_bytes(2, "little") +
                generation.child.to_bytes(2, "little") + b"\0\0")
            await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, accept, 15))
            await self.peer.receive(r.RFU1_CONNECT_ACK)
            await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child, b"PRIVATE!")
            await generation.receive()
            await generation.wait_link_ready()
            with self.assertRaises(r.TranslatorError) as failed:
                await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, accept, 0x100))
            self.assertEqual(failed.exception.code, "TRANSLATOR_RELIABLE_FLAGS")
            self.assertTrue(clean(await generation.close("test_end")))
        snapshots = [json.loads(line.split(" ", 2)[2]) for line in logs.output
                     if "gpsp_rfu_progress" in line]
        self.assertTrue(any(row["state"] == "connecting" for row in snapshots))
        self.assertTrue(any(row["state"] == "connected" and row["link_ready"] for row in snapshots))
        self.assertTrue(any(row["state"] == "failed" for row in snapshots))
        self.assertEqual(snapshots[-1]["gpsp_kinds"], {"connect_request": 1, "client_send": 1})
        self.assertEqual(snapshots[-1]["switch_packets"], 2)
        self.assertNotIn("PRIVATE!", "\n".join(logs.output))
        self.assertNotIn(b"PRIVATE!".hex(), "\n".join(logs.output))

    async def test_failed_advertisement_is_not_counted_as_written(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        first = GpspError("EMULATOR_NETPLAY_CLOSED", "test send failed")
        with self.assertLogs("switchtrade.endpoints.retroarch_gpsp.driver", level="INFO") as logs:
            with patch.object(self.driver.local, "send", new=AsyncMock(side_effect=first)):
                generation.activate()
                with self.assertRaises(GpspError) as failure:
                    await asyncio.wait_for(self.driver.wait_failed(), 1)
            self.assertIs(failure.exception, first)
            self.assertEqual(generation._advertisements, 0)
            self.assertEqual(generation._local_writes, 0)
        self.assertTrue(any('"event": "advertiser_failed"' in line for line in logs.output))

    async def test_prepare_proves_bind_or_fails_before_pair_admission(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", self.port))
            occupied.listen()
            with self.assertRaises(GpspError) as failure:
                await self.driver.prepare()
        self.assertEqual(failure.exception.code, "EMULATOR_PORT_UNAVAILABLE")

    async def connected_generation(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        generation.activate()
        await generation.receive()
        await self.peer.receive(r.RFU1_BROADCAST)
        await self.peer.send(r.RFU1_CONNECT_REQ, generation.host)
        await generation.receive()
        accept = gba(r.GBA_ACCEPT, HOST_SESSION.to_bytes(2, "little") +
            generation.child.to_bytes(2, "little") + b"\0\0")
        await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, accept, 15))
        await self.peer.receive(r.RFU1_CONNECT_ACK)
        return generation

    async def test_ni_first_stage_and_disconnect_log_before_periodic_deadline(self):
        from bridge.frlgsim import ni, rfu as native
        generation = await self.connected_generation()
        slot = ni.NISender(bytes(range(26))).next_slot()
        with self.assertLogs("switchtrade.endpoints.retroarch_gpsp.driver", level="INFO") as logs:
            for _ in range(3):
                await self.peer.send(r.RFU1_CLIENT_SEND, len(slot) << 24 | generation.child, slot)
                await generation.receive()
            ack = ni.parent_recv_ack_slot(native.LCOM_NI_START, 1, 0)
            await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, parent_t(1, ack), 7))
            await self.peer.receive(r.RFU1_HOST_SEND)
            await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
            await generation.receive()
            await self.peer.send(r.RFU1_DISCONNECT, generation.child)
            await generation.receive()
            self.assertTrue(clean(await generation.close("local_ended")))
        snapshots = [json.loads(line.split(" ", 2)[2]) for line in logs.output if "gpsp_rfu_progress" in line]
        self.assertTrue(any(row["llsf"]["parent"]["kinds"] == {"ni_start_ack": 1} for row in snapshots))
        self.assertEqual(snapshots[-1]["disconnected_by"], "gpsp")
        self.assertEqual(snapshots[-1]["llsf"]["child"]["kinds"], {"ni_start": 3})
        self.assertEqual(snapshots[-1]["llsf"]["child"]["repeated_slots"], 2)
        self.assertTrue(generation._link_ready.is_set())  # Traffic, not NI success.
        self.assertNotIn("payload", "\n".join(logs.output))

    async def test_core_queue_pressure_resumes_without_reordering(self):
        generation = await self.connected_generation()
        count = generation._out.maxsize + n.MAX_QUEUE + 20
        for index in range(count):
            await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child,
                                 index.to_bytes(8, "little"))
        async with asyncio.timeout(3):
            while not (generation._out.full() and self.driver.local._packets.full()):
                await asyncio.sleep(0)
        self.assertTrue(generation._out.full())
        self.assertIsNone(self.driver.failure)
        async with asyncio.timeout(5):
            packets = [await generation.receive() for _ in range(count)]
        # WT contains the translator timestamp and slot lengths before the slot.
        self.assertEqual([p.payload[-8:] for p in packets],
                         [i.to_bytes(8, "little") for i in range(count)])
        self.assertTrue(clean(await generation.close("test_end")))

    async def test_full_queues_can_close_generation_and_reuse_same_netplay(self):
        generation = await self.connected_generation()
        for _ in range(generation._out.maxsize + n.MAX_QUEUE + 20):
            await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child, b"old-data")
        async with asyncio.timeout(3):
            while not (generation._out.full() and self.driver.local._packets.full()):
                await asyncio.sleep(0)
        first = await asyncio.wait_for(generation.close("test_end"), 3)
        self.assertTrue(clean(first), first)
        self.assertIs(first, await generation.close("retry"))
        self.assertTrue(self.driver.local.connected)
        second = await self.driver.accept(self.offer(2), asyncio.Event())
        second.activate()
        self.assertEqual((await second.receive()).payload, r.METADATA_FRAME)
        await self.driver.local.barrier()
        self.assertEqual(second._out.qsize(), 0)
        self.assertTrue(clean(await second.close("test_end")))

    async def test_waiting_for_peer_observes_long_lived_endpoint_failure(self):
        await self.ready()
        wire = WireClient(PairSeat.GUEST)
        local_socket = core_helpers.MemorySocket()
        local_socket.peer = core_helpers.MemorySocket()
        await wire.connect(local_socket)
        supervisor = CoreSupervisor(core_helpers.credentials(PairSeat.GUEST), self.driver, wire)
        waiting = asyncio.create_task(supervisor.wait_for_peer())
        first = GpspError("EMULATOR_EXITED", "test process ended")
        self.observer.failure = first
        try:
            with self.assertRaises(SupervisorError) as failure:
                await asyncio.wait_for(waiting, 1)
            self.assertEqual(failure.exception.code, "EMULATOR_EXITED")
            self.assertIs(failure.exception.__cause__, first)
        finally:
            await supervisor.stop()

    async def test_peer_close_while_waiting_for_local_netplay_retains_listener(self):
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        a, b = core_helpers.MemorySocket(), core_helpers.MemorySocket()
        a.peer, b.peer = b, a
        await host_wire.connect(a)
        await guest_wire.connect(b)
        origin_driver = core_helpers.TestDriver(core_helpers.TestGeneration(self.offer()))
        host = CoreSupervisor(core_helpers.credentials(PairSeat.HOST), origin_driver, host_wire)
        guest = CoreSupervisor(core_helpers.credentials(PairSeat.GUEST), self.driver, guest_wire)
        offering = asyncio.create_task(host.offer_generation())
        accepting = asyncio.create_task(guest.accept_next_offer())
        try:
            async with asyncio.timeout(2):
                while guest.state is not SupervisorState.OPENING_LOCAL:
                    await asyncio.sleep(0)
            await host.close_generation()
            with self.assertRaises(GenerationEnded):
                await asyncio.wait_for(accepting, 1)
            self.assertIsNone(self.driver._closing)
            self.assertTrue(guest._prepared)
            self.assertTrue(self.driver.local.listening.is_set())
            offering.cancel()
            await asyncio.gather(offering, return_exceptions=True)
            await self.peer.open()
            await self.driver._wait(self.driver._ready.wait())
            self.assertTrue(self.driver.rfu_mode_verified)
        finally:
            for task in (offering, accepting):
                task.cancel()
            await asyncio.gather(offering, accepting, return_exceptions=True)
            await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_silent_rfu_mode_is_not_human_wait(self):
        with self.assertRaises(GpspError) as failed:
            await self.ready("disabled")
        self.assertEqual(failed.exception.code, "EMULATOR_RFU_MODE_UNPROVEN")
        self.assertEqual(self.peer.barriers, 1)
        self.assertFalse(self.driver.rfu_mode_verified)

    async def test_wrong_game_role_retires_only_probe_assignment(self):
        with self.assertRaises(GpspError) as failed:
            await self.ready("host")
        self.assertEqual(failed.exception.code, "EMULATOR_ROLE_UNSUPPORTED")
        self.assertEqual(self.peer.assignments, set())
        self.assertEqual(self.peer.barriers, 2)

    async def test_accept_returns_before_game_ack_and_cancel_does_not_close_frontend(self):
        await self.ready()
        generation = await asyncio.wait_for(self.driver.accept(self.offer(), asyncio.Event()), .5)
        self.assertFalse(generation._link_ready.is_set())
        self.assertEqual(generation.translator.state, "searching")
        self.assertTrue(clean(await self.driver.abort_opening()))
        self.assertTrue(self.driver.local.connected)
        self.assertIsNone(self.driver._generation)

    async def test_cancel_unbounded_local_connect_wait(self):
        await self.driver.prepare()
        cancel = asyncio.Event()
        opening = asyncio.create_task(self.driver.accept(self.offer(), cancel))
        await asyncio.sleep(.03)
        self.assertFalse(opening.done())
        cancel.set()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        self.assertIsNone(self.driver._generation)
        self.assertTrue(clean(await self.driver.abort_opening()))

    async def test_two_generations_same_local_connection_stale_rejected(self):
        await self.ready()
        local = self.driver.local
        previous = None
        for number in (1, 2):
            generation = await self.driver.accept(self.offer(number), asyncio.Event())
            generation.activate()
            self.assertEqual((await generation.receive()).payload, r.METADATA_FRAME)
            _, host, _ = await self.peer.receive(r.RFU1_BROADCAST)
            self.assertEqual(host, generation.host)
            if previous:
                await self.peer.send(r.RFU1_CONNECT_REQ, previous.host)
                await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | previous.child, b"old-data")
                await self.driver.local.barrier()
                self.assertEqual(generation.translator.state, "searching")
            await self.peer.send(r.RFU1_CONNECT_REQ, host)
            self.assertEqual((await generation.receive()).payload,
                gba(r.GBA_CONNECT, generation.child.to_bytes(2, "little")))
            accept = gba(r.GBA_ACCEPT, HOST_SESSION.to_bytes(2, "little") + generation.child.to_bytes(2, "little") + b"\0\0")
            await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, accept, 15))
            self.assertEqual((await self.peer.receive(r.RFU1_CONNECT_ACK))[1], generation.child)
            await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child, b"child123")
            outgoing = await generation.receive()
            self.assertTrue(outgoing.payload.endswith(b"child123"))
            await generation.wait_link_ready()
            await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL, parent_t(1, b"parent12"), 7))
            self.assertEqual((await self.peer.receive(r.RFU1_HOST_SEND))[2][:8], b"parent12")
            await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
            self.assertEqual((await generation.receive()).payload[1], r.GBA_ACK)
            await self.peer.send(r.RFU1_DISCONNECT, generation.child)
            self.assertEqual((await generation.receive()).payload[1], r.GBA_DISCONNECT)
            with self.assertRaises(GenerationEnded):
                await generation.receive()
            self.assertTrue(clean(await generation.close("local_ended")))
            self.assertIs(self.driver.local, local)
            self.assertTrue(local.connected)
            previous = generation
        self.assertIsNone(self.driver.failure)

    async def test_remote_disconnect_wakes_empty_receive(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        generation.activate()
        await generation.receive()
        await self.peer.send(r.RFU1_CONNECT_REQ, generation.host)
        await generation.receive()
        receiving = asyncio.create_task(generation.receive())
        await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL,
            gba(r.GBA_DISCONNECT, generation.child.to_bytes(2, "little")), 7))
        with self.assertRaises(GenerationEnded):
            await asyncio.wait_for(receiving, .5)

    async def test_local_disconnect_retires_inflight_data_before_close_tail_drains(self):
        generation = await self.connected_generation()
        await generation.feed(n.CorePacket(r._rfu1(r.RFU1_DISCONNECT, generation.child), 1, 1))
        self.assertTrue(generation._finished)
        self.assertEqual(generation._out.qsize(), 1)  # final disconnect not sent yet
        sent = generation._sent
        await generation.send(LinkPacket(generation.offer.generation_id, PROTOCOL,
            parent_t(1, b"late1234"), 7))
        self.assertEqual(generation.translator.state, "closed")
        self.assertEqual(generation._sent, sent)
        with self.assertRaises(GpspError) as stale:
            await generation.send(LinkPacket("other-room", PROTOCOL, parent_t(2, b"stale123"), 7))
        self.assertEqual(stale.exception.code, "EMULATOR_GENERATION_STALE")
        self.assertEqual((await generation.receive()).payload[1], r.GBA_DISCONNECT)
        with self.assertRaises(GenerationEnded):
            await generation.receive()
        self.assertTrue(clean(await generation.close("local_ended")))
        self.assertIsNone(self.driver.failure)
        self.assertTrue(self.driver.local.connected)

    async def test_lost_cleanup_barrier_remains_dirty_and_blocks_next_generation(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        self.driver.local.handshake_timeout = .05
        self.peer.answer_barriers = False
        first = await generation.close("cancelled")
        self.assertFalse(clean(first))
        self.peer.answer_barriers = True
        self.assertIs(first, await generation.close("again"))
        with self.assertRaises(Exception):
            await self.driver.accept(self.offer(2), asyncio.Event())
        self.assertFalse(clean(await self.driver.close()))

    async def test_first_process_failure_separate_from_cleanup(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        first = GpspError("EMULATOR_EXITED", "test process ended")
        self.observer.failure = first
        with self.assertRaises(GpspError) as failed:
            await asyncio.wait_for(self.driver.wait_failed(), 1)
        self.assertIs(first, failed.exception)
        report = await generation.close("failed")
        self.assertFalse(clean(report))
        self.assertIs(first, self.driver.failure)

    async def test_transport_loss_during_opening_cancels_owned_wait(self):
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        a, b = core_helpers.MemorySocket(), core_helpers.MemorySocket()
        a.peer, b.peer = b, a
        await host_wire.connect(a)
        await guest_wire.connect(b)
        origin_driver = core_helpers.TestDriver(core_helpers.TestGeneration(self.offer()))
        host = CoreSupervisor(core_helpers.credentials(PairSeat.HOST), origin_driver, host_wire)
        guest = CoreSupervisor(core_helpers.credentials(PairSeat.GUEST), self.driver, guest_wire)
        offering = asyncio.create_task(host.offer_generation())
        accepting = asyncio.create_task(guest.accept_next_offer())
        try:
            async with asyncio.timeout(2):
                while guest.state is not SupervisorState.OPENING_LOCAL:
                    await asyncio.sleep(0)
            guest_wire._fail(ConnectionError("test relay loss"))
            with self.assertRaises(SupervisorError) as failed:
                await asyncio.wait_for(accepting, 1)
            self.assertEqual(failed.exception.code, "S_TRANSPORT_FAILED")
            self.assertIsNone(self.driver._opening)
            self.assertIsNone(self.driver._generation)
        finally:
            for task in (offering, accepting):
                task.cancel()
            await asyncio.gather(offering, accepting, return_exceptions=True)
            await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_generation_cleanup_cannot_orphan_its_barrier_on_repeated_cancel(self):
        await self.ready()
        generation = await self.driver.accept(self.offer(), asyncio.Event())
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.driver.local.barrier
        async def delayed():
            entered.set()
            await release.wait()
            await original()
        self.driver.local.barrier = delayed
        closing = asyncio.create_task(generation.close("cancelled"))
        await entered.wait()
        closing.cancel()
        await asyncio.sleep(0)
        closing.cancel()
        self.assertFalse(closing.done())
        release.set()
        report = await closing
        self.assertTrue(clean(report))
        self.assertIs(report, await generation.close("again"))

    async def test_pair_recovery_keeps_local_netplay_and_admits_fresh_generation(self):
        await self.ready()
        local = self.driver.local
        factory = core_helpers.SocketFactory()
        a, b = await factory.connect(PairSeat.HOST), await factory.connect(PairSeat.GUEST)
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(a)
        await guest_wire.connect(b)
        origin_driver = core_helpers.TestDriver(core_helpers.TestGeneration(self.offer()))
        host = CoreSupervisor(core_helpers.credentials(PairSeat.HOST), origin_driver, host_wire,
            connector=lambda: factory.connect(PairSeat.HOST), reconnect_timeout=1)
        guest = CoreSupervisor(core_helpers.credentials(PairSeat.GUEST), self.driver, guest_wire,
            connector=lambda: factory.connect(PairSeat.GUEST), reconnect_timeout=1)
        try:
            await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
            old = self.driver._generation
            await a.incoming.put(ConnectionError("test relay loss"))
            async with asyncio.timeout(3):
                while host.state is not SupervisorState.PAIRED or guest.state is not SupervisorState.PAIRED:
                    await asyncio.sleep(.01)
            self.assertIsNone(guest.failure)
            self.assertIs(self.driver.local, local)
            self.assertTrue(local.connected)
            self.assertTrue(clean(await old.close("again")))
            origin_driver.generation = core_helpers.TestGeneration(self.offer(2))
            await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
            self.assertNotEqual(self.driver._generation.host, old.host)
            self.assertEqual(guest.state, SupervisorState.ACTIVE)
        finally:
            await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)


class RelayEndpointTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = EndpointTests.asyncSetUp
    asyncTearDown = EndpointTests.asyncTearDown
    ready = EndpointTests.ready
    offer = EndpointTests.offer
    # Reuse only the existing real-relay helpers, not its fake-path test cases.
    _post = relay_helpers.CoreEndToEndTests._post
    _socket = relay_helpers.CoreEndToEndTests._socket

    async def test_real_relay_core_supervisor_conversion_twice(self):
        await self.ready()
        local_port = self.port
        await relay_helpers.CoreEndToEndTests.asyncSetUp(self)
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        host = guest = None
        try:
            capability = {"endpoint_kind": "switch_ldn", "runtime_kind": "managed_wsl",
                "protocols": [PROTOCOL], "generation_roles": ["origin"]}
            _, h = await self._post("/core/v1/pairs", {"capabilities": capability})
            _, g = await self._post("/core/v1/pairs:join", {"code": h["code"], "capabilities": {
                **capability, "endpoint_kind": "retroarch_gpsp", "runtime_kind": "native", "generation_roles": ["mirror"]}})
            hc = PairCredentials(h["pair_id"], PairSeat.HOST, h["access_token"], h["reconnect_expires_at"])
            gc = PairCredentials(g["pair_id"], PairSeat.GUEST, g["access_token"], g["reconnect_expires_at"])
            await host_wire.connect(await self._socket(hc))
            await guest_wire.connect(await self._socket(gc))
            origin_driver = core_helpers.TestDriver(core_helpers.TestGeneration(self.offer()))
            host = CoreSupervisor(hc, origin_driver, host_wire)
            guest = CoreSupervisor(gc, self.driver, guest_wire)
            for number in (1, 2):
                origin = core_helpers.TestGeneration(self.offer(number))
                origin_driver.generation = origin
                await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
                generation = self.driver._generation
                await self.peer.receive(r.RFU1_BROADCAST)
                await self.peer.send(r.RFU1_CONNECT_REQ, generation.host)
                async with asyncio.timeout(2):
                    while not any(p.payload[:2] == b"WC" for p in origin.sent):
                        await asyncio.sleep(0)
                await origin.incoming.put(LinkPacket(origin.offer.generation_id, PROTOCOL,
                    gba(r.GBA_ACCEPT, HOST_SESSION.to_bytes(2, "little") + generation.child.to_bytes(2, "little") + b"\0\0"), 15))
                await self.peer.receive(r.RFU1_CONNECT_ACK)
                await self.peer.send(r.RFU1_CLIENT_SEND, 8 << 24 | generation.child, b"child123")
                async with asyncio.timeout(2):
                    while not any(p.payload.endswith(b"child123") for p in origin.sent):
                        await asyncio.sleep(0)
                await origin.incoming.put(LinkPacket(origin.offer.generation_id, PROTOCOL, parent_t(number, b"parent12"), 7))
                self.assertEqual((await self.peer.receive(r.RFU1_HOST_SEND))[2][:8], b"parent12")
                await self.peer.send(r.RFU1_CLIENT_ACK, generation.child)
                # Hold only the final outbound disconnect. A same-generation
                # parent frame arrives through the real relay before Core can
                # finish retirement (the physical trial09 interleaving).
                entered, release, late_seen = asyncio.Event(), asyncio.Event(), asyncio.Event()
                send_wire, send_local = guest_wire.send, generation.send
                async def held_send(kind, generation_id="", payload=b"", flags=0):
                    if payload[:2] == b"WD":
                        entered.set()
                        await release.wait()
                    return await send_wire(kind, generation_id, payload, flags)
                async def observed_send(packet):
                    try:
                        return await send_local(packet)
                    finally:
                        late_seen.set()
                with patch.object(guest_wire, "send", held_send), patch.object(generation, "send", observed_send):
                    try:
                        await self.peer.send(r.RFU1_DISCONNECT, generation.child)
                        await asyncio.wait_for(entered.wait(), 2)
                        await origin.incoming.put(LinkPacket(origin.offer.generation_id, PROTOCOL,
                            parent_t(number + 100, b"late1234"), 7))
                        await asyncio.wait_for(late_seen.wait(), 2)
                        self.assertEqual(generation.translator.state, "closed")
                        self.assertIsNone(guest.failure)
                    finally:
                        release.set()
                await asyncio.wait_for(asyncio.gather(host.wait_generation_end(), guest.wait_generation_end()), 2)
                self.assertEqual((host.state, guest.state), (SupervisorState.PAIRED, SupervisorState.PAIRED))
                self.assertIsNone(guest.failure)
                self.assertTrue(self.driver.local.connected)
            self.assertEqual(host.credentials.pair_id, guest.credentials.pair_id)
        finally:
            if host is not None:
                await host.stop()
            if guest is not None:
                with contextlib.suppress(SupervisorError):
                    await guest.stop()
            await asyncio.gather(host_wire.close(), guest_wire.close())
            await relay_helpers.CoreEndToEndTests.asyncTearDown(self)
            self.port = local_port
