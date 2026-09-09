"""Real loopback sockets with synthetic stock peers; real stock proof is separate."""
import asyncio
from contextlib import suppress
import socket
import struct
import unittest
from unittest.mock import patch

from switchtrade.endpoints.retroarch_gpsp.errors import GpspError
from switchtrade.endpoints.retroarch_gpsp import netplay as n


class Observer:
    failure = None
    def check(self):
        if self.failure:
            raise self.failure
    def check_connection(self, local, remote):
        self.check()
        assert local != remote


def command(kind, payload=b""):
    return struct.pack("!II", kind, len(payload)) + payload


def core_packet(payload=b"abcdefghijklmnop"):
    return struct.pack("!III", n.NETPACKET, len(payload), 0) + payload


async def take(reader, kind, size):
    assert struct.unpack("!II", await reader.readexactly(8)) == (kind, size)
    return await reader.readexactly(size)


class NetplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.observer = Observer()
        self.session = n.LocalNetplay(self.observer, self.port, handshake_timeout=3)
        self.cancel = asyncio.Event()
        self.opening = None
        self.client = None

    async def asyncTearDown(self):
        self.cancel.set()
        await self.session.close()
        if self.opening:
            await asyncio.gather(self.opening, return_exceptions=True)
        if self.client:
            self.client[1].close()
            with suppress(ConnectionError):  # Expected after injected abort/reset.
                await self.client[1].wait_closed()
            self.assertTrue(self.client[1].is_closing())

    async def dial(self):
        self.opening = asyncio.create_task(self.session.open(self.cancel))
        await asyncio.sleep(0)
        self.client = await asyncio.open_connection("127.0.0.1", self.port)
        return self.client

    async def connect(self):
        reader, writer = await self.dial()
        writer.write(struct.pack("!6I", n.MAGIC, 0, 0, 8, 6, n._impl_magic()))
        response = struct.unpack("!6I", await reader.readexactly(24))
        assert response[4] == 7
        writer.write(command(n.NICK, b"tester\0" + b"x" * 25))
        await take(reader, n.NICK, 32)
        await take(reader, n.INFO, 68)
        # Like stock strlcpy, bytes beyond the terminating NUL needn't be zero.
        info = b"\0" * 4 + b"gpSP\0" + b"x" * 27 + b"gpSP v1.0\0" + b"y" * 22
        writer.write(command(n.INFO, info))
        await take(reader, n.SYNC, 184)
        writer.write(command(n.PLAY, b"\0" * 4))
        await take(reader, n.MODE, 60)
        await self.opening
        return reader, writer

    async def test_partial_header_and_payload_survive_polling_delays(self):
        reader, writer = await self.connect()
        raw = core_packet()
        writer.write(raw[:3])
        await writer.drain()
        await asyncio.sleep(.3)
        self.assertIsNone(self.session.failure)
        writer.write(raw[3:14])
        await writer.drain()
        await asyncio.sleep(.3)
        self.assertIsNone(self.session.failure)
        writer.write(raw[14:])
        packet = await asyncio.wait_for(self.session.receive(), 2)
        self.assertEqual((packet.payload, packet.peer_id, packet.sequence), (b"abcdefghijklmnop", 1, 1))
        await self.session.send(b"0123456789abcdef")
        self.assertEqual(await reader.readexactly(28), core_packet(b"0123456789abcdef"))

    async def test_no_connection_wait_remains_cancellable(self):
        self.opening = asyncio.create_task(self.session.open(self.cancel))
        await asyncio.sleep(.35)
        self.assertFalse(self.opening.done())
        self.cancel.set()
        with self.assertRaises(asyncio.CancelledError):
            await self.opening
        self.assertIsNone(self.session.failure)
        self.assertTrue((await self.session.close()).local_resources_released)

    async def test_cancel_mid_handshake_and_repeated_close(self):
        _, writer = await self.dial()
        writer.write(b"RAN")
        self.cancel.set()
        with self.assertRaises(asyncio.CancelledError):
            await self.opening
        first = await self.session.close()
        self.assertIs(first, await self.session.close())
        self.assertTrue(first.transport_drained)
        self.assertTrue(self.session._opening.done())

    async def test_close_owns_incomplete_accept(self):
        self.opening = asyncio.create_task(self.session.open(self.cancel))
        await asyncio.sleep(0)
        await self.session.close()
        self.assertTrue(self.session._opening.done())
        self.assertEqual(self.session._listener.fileno(), -1)

    async def test_port_collision_never_selects_another_port(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", self.port))
            occupied.listen(1)
            with self.assertRaises(GpspError) as result:
                await self.session.open(self.cancel)
        self.assertEqual(result.exception.code, "EMULATOR_PORT_UNAVAILABLE")
        self.assertEqual(self.session.port, self.port)

    async def test_malformed_huge_header_fails_before_body_read(self):
        _, writer = await self.connect()
        writer.write(struct.pack("!II", 0xFFFF, 0xFFFFFFFF))
        with self.assertRaises(GpspError) as result:
            await asyncio.wait_for(self.session.wait_ended(), 2)
        self.assertEqual(result.exception.code, "EMULATOR_PACKET_COMMAND")

    async def test_oversized_netpacket_is_rejected_before_payload(self):
        _, writer = await self.connect()
        writer.write(struct.pack("!II", n.NETPACKET, 105))
        with self.assertRaises(GpspError) as result:
            await asyncio.wait_for(self.session.wait_ended(), 2)
        self.assertEqual(result.exception.code, "EMULATOR_PACKET_LENGTH")

    async def test_wrong_handshake_version_is_not_ready(self):
        _, writer = await self.dial()
        writer.write(struct.pack("!6I", n.MAGIC, 0, 0, 6, 6, n._impl_magic()))
        with self.assertRaises(GpspError) as result:
            await self.opening
        self.assertEqual(result.exception.code, "EMULATOR_NETPLAY_PROTOCOL_MISMATCH")
        self.assertFalse(self.session.connected)

    async def test_foreign_socket_owner_is_never_accepted(self):
        self.observer.check_connection = lambda *args: (_ for _ in ()).throw(
            GpspError("EMULATOR_SOCKET_IDENTITY_MISMATCH", "foreign"))
        await self.dial()
        with self.assertRaises(GpspError) as result:
            await self.opening
        self.assertEqual(result.exception.code, "EMULATOR_SOCKET_IDENTITY_MISMATCH")
        self.assertFalse(self.session.connected)

    async def test_queue_saturation_stays_bounded(self):
        _, writer = await self.connect()
        payloads = [i.to_bytes(16, "big") for i in range(n.MAX_QUEUE + 5)]
        writer.write(b"".join(core_packet(p) for p in payloads))
        await writer.drain()
        async with asyncio.timeout(2):
            while not self.session._packets.full():
                await asyncio.sleep(0)
        self.assertEqual(self.session._packets.qsize(), n.MAX_QUEUE)
        self.assertIsNone(self.session.failure)
        async with asyncio.timeout(2):
            packets = [await self.session.receive() for _ in payloads]
        self.assertEqual([p.payload for p in packets], payloads)
        self.assertEqual([p.sequence for p in packets], list(range(1, len(payloads) + 1)))

    async def test_full_queue_close_or_process_failure_releases_reader(self):
        for ending in ("close", "process"):
            with self.subTest(ending=ending):
                if ending == "process":
                    self.session = n.LocalNetplay(self.observer, self.port, handshake_timeout=3)
                _, writer = await self.connect()
                writer.write(core_packet() * (n.MAX_QUEUE + 5))
                await writer.drain()
                async with asyncio.timeout(2):
                    while not self.session._packets.full():
                        await asyncio.sleep(0)
                if ending == "process":
                    first = GpspError("EMULATOR_EXITED", "synthetic process exit")
                    self.observer.failure = first
                    with self.assertRaises(GpspError) as failure:
                        await asyncio.wait_for(self.session.wait_ended(), 2)
                    self.assertIs(failure.exception, first)
                report = await asyncio.wait_for(self.session.close(), 2)
                self.assertTrue(report.local_resources_released)
                writer.close()
                with suppress(ConnectionError):
                    await writer.wait_closed()

    async def test_ordered_barrier_and_uncorrelated_pong(self):
        reader, writer = await self.connect()
        barrier = asyncio.create_task(self.session.barrier())
        await take(reader, n.PING, 0)
        writer.write(core_packet() + command(n.PONG))
        await asyncio.wait_for(barrier, 2)
        self.assertEqual(len(self.session.drain()), 1)
        writer.write(command(n.PONG))
        with self.assertRaises(GpspError) as result:
            await asyncio.wait_for(self.session.wait_ended(), 2)
        self.assertEqual(result.exception.code, "EMULATOR_PACKET_COMMAND")

    async def test_process_failure_while_waiting_or_active(self):
        self.opening = asyncio.create_task(self.session.open(self.cancel))
        await asyncio.sleep(0)
        original = GpspError("EMULATOR_EXITED", "gone")
        self.observer.failure = original
        with self.assertRaises(GpspError) as result:
            await asyncio.wait_for(self.opening, 2)
        self.assertIs(result.exception, original)
        self.assertTrue((await self.session.close()).local_resources_released)

    async def test_active_process_failure_preserves_first_error(self):
        await self.connect()
        original = GpspError("EMULATOR_IDENTITY_CHANGED", "replaced")
        self.observer.failure = original
        with self.assertRaises(GpspError) as result:
            await asyncio.wait_for(self.session.receive(), 2)
        self.assertIs(result.exception, original)

    async def test_cleanup_failure_cannot_turn_into_success_on_retry(self):
        await self.connect()
        with patch.object(self.session._writer, "close", side_effect=OSError("test close failure")):
            first = await self.session.close()
        self.assertFalse(first.local_resources_released)
        self.assertIs(first, await self.session.close())
        # Only the test owner releases the injected failing stream afterward.
        self.session._writer.close()
        with suppress(ConnectionError):
            await self.session._writer.wait_closed()
        self.assertTrue(self.session._writer.is_closing())
        self.assertEqual(self.session._socket.fileno(), -1)
