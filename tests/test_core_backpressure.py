"""Burst delivery must not depend on a lucky event-loop scheduling turn."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import websockets
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from switchtrade.core.contracts import PairSeat
from switchtrade.core_cli import _WebSocketSocket
from switchtrade.transport import FrameKind, TransportError, WireClient
from tests.test_core_transport import MemorySocket


class CoreBackpressureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.first, self.second = MemorySocket(), MemorySocket()
        self.first.peer, self.second.peer = self.second, self.first
        self.host, self.guest = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await self.host.connect(self.first)
        await self.guest.connect(self.second)
        await asyncio.gather(self.host.wait_ready(), self.guest.wait_ready())
        await self.host.send(FrameKind.GENERATION_OFFER, "burst", b"setup")
        await self.guest.receive()
        await self.guest.send(FrameKind.GENERATION_ACCEPT, "burst")
        await self.host.receive()

    async def asyncTearDown(self):
        await asyncio.gather(self.host.close(), self.guest.close())

    async def test_send_burst_allows_live_writer_to_drain(self):
        async def consume():
            return [(await self.guest.receive()).payload for _ in range(64)]

        reader = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(2):
                for index in range(64):
                    await self.host.send(FrameKind.DATA, "burst", index.to_bytes(2, "big"))
                self.assertEqual(await reader, [i.to_bytes(2, "big") for i in range(64)])
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    async def test_buffered_receive_burst_allows_live_consumer_to_drain(self):
        # Model a network read delivering already-buffered valid frames together;
        # isolate the receiver from the sender's own queue/backpressure policy.
        for index in range(64):
            await self.first.send(self.host.state.emit(
                FrameKind.DATA, "burst", index.to_bytes(2, "big")).encode())
        async with asyncio.timeout(2):
            received = [(await self.guest.receive()).payload for _ in range(64)]
        self.assertEqual(received, [i.to_bytes(2, "big") for i in range(64)])

    async def test_concurrent_senders_preserve_each_stream_without_loss(self):
        async def send(group):
            for i in range(32):
                await self.host.send(FrameKind.DATA, "burst", bytes([group, i]))

        async def consume():
            return [(await self.guest.receive()).payload for _ in range(128)]

        # Total batch deadline, not the per-admission stall deadline. Windows
        # asyncio debug mode schedules hundreds of bounded waiter tasks here.
        async with asyncio.timeout(10):
            *_, received = await asyncio.gather(*(send(i) for i in range(4)), consume())
        for group in range(4):
            self.assertEqual([data[1] for data in received if data[0] == group], list(range(32)))

    async def fill_outgoing(self):
        await self.host.drain()
        self.host._writer.cancel()
        await asyncio.gather(self.host._writer, return_exceptions=True)
        for i in range(8):
            await self.host.send(FrameKind.DATA, "burst", bytes([i]))

    async def test_cancel_waiting_sender_does_not_advance_sequence(self):
        await self.fill_outgoing()
        sequence = self.host.state._next_sequence
        pending = asyncio.create_task(self.host.send(FrameKind.DATA, "burst", b"canceled"))
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(self.host.state._next_sequence, sequence)
        self.assertEqual(self.host._outgoing.qsize(), 8)
        self.assertTrue(self.host.connected)

    async def test_persistent_sender_stall_fails_without_sequence_or_drop(self):
        await self.fill_outgoing()
        sequence = self.host.state._next_sequence
        self.host._send_timeout = .03
        with self.assertRaisesRegex(TransportError, "T_SEND_BACKPRESSURE_TIMEOUT"):
            await self.host.send(FrameKind.DATA, "burst", b"blocked")
        self.assertFalse(self.host.connected)
        self.assertEqual(self.host.state._next_sequence, sequence)
        self.assertEqual(self.host._outgoing.qsize(), 8)

    async def test_invalid_data_does_not_wait_for_queue_or_advance_sequence(self):
        await self.fill_outgoing()
        sequence = self.host.state._next_sequence
        with self.assertRaisesRegex(TransportError, "T_ENVELOPE_INVALID"):
            await self.host.send(FrameKind.DATA, "burst", b"invalid", 0x10000)
        self.assertEqual(self.host.state._next_sequence, sequence)
        self.assertTrue(self.host.connected)

    async def test_close_interrupts_a_waiting_sender(self):
        await self.fill_outgoing()
        pending = asyncio.create_task(self.host.send(FrameKind.DATA, "burst", b"blocked"))
        await asyncio.sleep(0)
        await self.host.close()
        with self.assertRaisesRegex(TransportError, "T_CLOSED"):
            await asyncio.wait_for(pending, .5)
        self.assertTrue(self.host._outgoing.empty())

    async def test_peer_epoch_change_interrupts_a_waiting_sender(self):
        await self.fill_outgoing()
        pending = asyncio.create_task(self.host.send(FrameKind.DATA, "burst", b"old"))
        await asyncio.sleep(0)
        for frame in self.guest.state.start():
            await self.second.send(frame.encode())
        # The new epoch retires queued old DATA. The waiting sender cannot use
        # the freed slot to attach its old payload to the fresh epoch.
        with self.assertRaisesRegex(TransportError, "T_PEER_RECONNECTED"):
            await asyncio.wait_for(pending, .5)
        self.assertTrue(self.host.connected)
        self.assertNotIn(b"old", [frame.payload for frame in self.host._outgoing._queue])
        self.assertFalse(any(frame.kind is FrameKind.DATA for frame in self.host._outgoing._queue))

    async def test_expected_peer_resync_preserves_unsent_new_epoch_probe(self):
        await self.guest.connect(self.second)
        self.guest._writer.cancel()
        await asyncio.gather(self.guest._writer, return_exceptions=True)
        ready = self.guest._outgoing.get_nowait()
        self.guest._outgoing.task_done()
        self.assertEqual(ready.kind, FrameKind.PEER_READY)
        await self.second.send(ready.encode())
        async with asyncio.timeout(1):
            while not self.guest.state._responded_to_peer:
                await asyncio.sleep(0)
        pending = list(self.guest._outgoing._queue)
        self.assertEqual([frame.sequence for frame in pending], [1, 2])
        self.assertEqual(pending[0].kind, FrameKind.PROBE_CHALLENGE)
        self.guest._writer = asyncio.create_task(self.guest._write_loop())
        await asyncio.gather(self.host.wait_ready(1), self.guest.wait_ready(1))
        self.assertTrue(self.host.connected and self.guest.connected)

    async def test_close_after_send_burst_preserves_data_order(self):
        async def consume():
            return [await self.guest.receive() for _ in range(65)]

        reader = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(2):
                for index in range(64):
                    await self.host.send(FrameKind.DATA, "burst", bytes([index]))
                await self.host.send(FrameKind.GENERATION_CLOSE, "burst")
                frames = await reader
                self.assertEqual([frame.payload for frame in frames[:-1]], [bytes([i]) for i in range(64)])
                self.assertEqual(frames[-1].kind, FrameKind.GENERATION_CLOSE)
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    async def test_buffered_close_frame_waits_behind_data_burst(self):
        for i in range(8):
            await self.first.send(self.host.state.emit(FrameKind.DATA, "burst", bytes([i])).encode())
        await self.first.send(self.host.state.emit(FrameKind.GENERATION_CLOSE, "burst").encode())
        async with asyncio.timeout(2):
            frames = [await self.guest.receive() for _ in range(9)]
        self.assertEqual([frame.payload for frame in frames[:-1]], [bytes([i]) for i in range(8)])
        self.assertEqual(frames[-1].kind, FrameKind.GENERATION_CLOSE)

    async def test_persistent_receive_stall_fails_closed(self):
        self.guest._send_timeout = .03
        for i in range(9):
            await self.first.send(self.host.state.emit(FrameKind.DATA, "burst", bytes([i])).encode())
        await asyncio.wait_for(self.guest._failed.wait(), .5)
        with self.assertRaisesRegex(TransportError, "T_RECEIVE_BACKPRESSURE_TIMEOUT"):
            await self.guest.receive()
        self.assertEqual(self.guest._incoming.qsize(), 8)

    async def test_retired_generation_drops_waiting_tail_before_next_offer(self):
        for i in range(9):
            await self.first.send(self.host.state.emit(FrameKind.DATA, "burst", bytes([i])).encode())
        async with asyncio.timeout(1):
            while self.guest._incoming.qsize() != 8:
                await asyncio.sleep(0)
        await self.guest.send(FrameKind.GENERATION_CLOSE, "burst")
        self.assertEqual(self.guest.discard_generation("burst"), 8)
        self.assertEqual((await self.host.receive()).kind, FrameKind.GENERATION_CLOSE)
        await self.host.send(FrameKind.GENERATION_OFFER, "next", b"new")
        frame = await self.guest.receive(timeout=1)
        self.assertEqual((frame.kind, frame.generation_id), (FrameKind.GENERATION_OFFER, "next"))
        self.assertEqual(self.guest.discarded_generation_frames, 9)

    async def test_first_wire_failure_logs_codes_not_peer_reason(self):
        secret = "private-reason-with-token"
        first = ConnectionClosedError(Close(1011, secret), Close(1000, secret), True)
        with self.assertLogs("switchtrade.transport.client", "WARNING") as output:
            self.host._fail(first)
            self.host._fail(TimeoutError("secondary"))
        self.assertEqual(len(output.output), 1)
        line = output.output[0]
        self.assertIn("cause_type=ConnectionClosedError", line)
        self.assertIn("ws_received=1011 ws_sent=1000", line)
        self.assertNotIn(secret, line)
        self.assertIs(self.host._failure.__cause__, first)


class CoreSocketCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfirmed_close_is_sticky_and_blocks_reconnect(self):
        socket = MemorySocket()
        socket.close = AsyncMock(side_effect=TimeoutError("close failed"))
        wire = WireClient(PairSeat.HOST)
        await wire.connect(socket)
        failures = await asyncio.gather(wire.close(), wire.close(), return_exceptions=True)
        self.assertIs(failures[0], failures[1])
        self.assertEqual(failures[0].code, "T_CLOSE_UNCONFIRMED")
        self.assertIs(wire._socket, socket)
        self.assertFalse(wire.connected)
        with self.assertRaisesRegex(TransportError, "T_CLOSE_UNCONFIRMED"):
            await wire.connect(MemorySocket())
        socket.close.assert_awaited_once()
        self.assertIsNone(wire._reader)
        self.assertIsNone(wire._writer)

    async def test_adapter_timeout_aborts_only_owned_socket_and_waits_for_proof(self):
        async def stall():
            await asyncio.Future()

        connection = SimpleNamespace(close=AsyncMock(side_effect=stall),
            transport=SimpleNamespace(abort=Mock()), wait_closed=AsyncMock())
        await _WebSocketSocket(connection, close_timeout=.02).close()
        connection.transport.abort.assert_called_once()
        connection.wait_closed.assert_awaited_once()

    async def test_real_websocket_missing_close_reply_releases_local_tcp_owner(self):
        accepted = asyncio.get_running_loop().create_future()
        release = asyncio.Event()

        async def peer(connection):
            connection.transport.pause_reading()  # OS boundary: withhold close ACK.
            accepted.set_result(connection)
            try:
                await release.wait()
            finally:
                connection.transport.resume_reading()

        async with websockets.serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            connection = await websockets.connect(f"ws://127.0.0.1:{port}", proxy=None)
            await accepted
            try:
                await asyncio.wait_for(_WebSocketSocket(connection, close_timeout=.03).close(), 1)
                self.assertTrue(connection.transport.is_closing())
                await asyncio.wait_for(connection.wait_closed(), .5)
            finally:
                release.set()
                await connection.close()
