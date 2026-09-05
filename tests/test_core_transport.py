from __future__ import annotations

import asyncio
import unittest

from switchtrade.core.contracts import MAX_PACKET_BYTES, PairSeat
from switchtrade.transport import Envelope, FrameKind, TransportError, WireClient, WireState


class EnvelopeTests(unittest.TestCase):
    def test_round_trip_and_invalid_header(self) -> None:
        for flags in (0x0000, 0x00FF, 0x0100, 0xFFFF):
            frame = Envelope(FrameKind.GENERATION_OFFER, PairSeat.HOST, 7, 3, "generation-1", b"setup", flags)
            self.assertEqual(Envelope.decode(frame.encode()), frame)
        with self.assertRaisesRegex(TransportError, "T_MAGIC_INVALID"):
            Envelope.decode(b"BAD!" + frame.encode()[4:])
        with self.assertRaisesRegex(TransportError, "T_GENERATION_INVALID"):
            Envelope(FrameKind.DATA, PairSeat.HOST, 7, 3, "", b"data").encode()


class WireStateTests(unittest.TestCase):
    def test_probe_generation_and_stale_epoch_guards(self) -> None:
        host, guest = WireState(PairSeat.HOST), WireState(PairSeat.GUEST)
        host_ready, host_challenge = host.start(11)
        guest_ready, guest_challenge = guest.start(12)
        self.assertEqual(guest.accept(host_ready), ())
        self.assertEqual(host.accept(guest_ready), ())
        with self.assertRaisesRegex(TransportError, "T_PROBE_REQUIRED"):
            host.emit(FrameKind.GENERATION_OFFER, "generation-1", b"setup")
        host_response, = host.accept(guest_challenge)
        guest_response, = guest.accept(host_challenge)
        host.accept(guest_response)
        guest.accept(host_response)
        offer = host.emit(FrameKind.GENERATION_OFFER, "generation-1", b"setup")
        guest.accept(offer)
        accepted = guest.emit(FrameKind.GENERATION_ACCEPT, "generation-1")
        host.accept(accepted)
        guest.accept(host.emit(FrameKind.DATA, "generation-1", b"payload"))
        close = host.emit(FrameKind.GENERATION_CLOSE, "generation-1")
        guest.accept(close)
        with self.assertRaisesRegex(TransportError, "T_GENERATION_INACTIVE"):
            host.emit(FrameKind.DATA, "generation-1", b"late")
        next_ready, _ = host.start(13)
        guest.accept(next_ready)
        with self.assertRaisesRegex(TransportError, "T_EPOCH_STALE"):
            guest.accept(host_ready)

    def test_wrong_seat_and_sequence_fail_closed(self) -> None:
        guest = WireState(PairSeat.GUEST)
        host = WireState(PairSeat.HOST)
        ready, challenge = host.start(1)
        guest.accept(ready)
        with self.assertRaisesRegex(TransportError, "T_SEQUENCE_DUPLICATE"):
            guest.accept(ready)
        with self.assertRaisesRegex(TransportError, "T_SEQUENCE_GAP"):
            guest.accept(host.emit(FrameKind.HEARTBEAT))
        with self.assertRaisesRegex(TransportError, "T_SOURCE_SEAT_MISMATCH"):
            guest.accept(Envelope(FrameKind.PEER_READY, PairSeat.GUEST, 2, 0))
        self.assertIsNotNone(challenge)

    def test_invalid_offer_does_not_advance_local_state(self) -> None:
        state = WireState(PairSeat.HOST)
        state.start(1)
        sequence = state._next_sequence
        with self.assertRaisesRegex(TransportError, "T_FRAME_TOO_LARGE"):
            state.emit(FrameKind.GENERATION_OFFER, "generation-1", b"x" * (MAX_PACKET_BYTES + 1))
        self.assertEqual(state._next_sequence, sequence)
        self.assertIsNone(state._outbound_offer)

    def test_retiring_generation_discards_inflight_peer_data(self) -> None:
        host, guest = WireState(PairSeat.HOST), WireState(PairSeat.GUEST)
        host_ready, host_challenge = host.start(11)
        guest_ready, guest_challenge = guest.start(12)
        guest.accept(host_ready)
        host.accept(guest_ready)
        host_response, = host.accept(guest_challenge)
        guest_response, = guest.accept(host_challenge)
        host.accept(guest_response)
        guest.accept(host_response)
        guest.accept(host.emit(FrameKind.GENERATION_OFFER, "generation-1", b"setup"))
        host.accept(guest.emit(FrameKind.GENERATION_ACCEPT, "generation-1"))
        host.emit(FrameKind.GENERATION_CLOSE, "generation-1")
        host.accept(guest.emit(FrameKind.DATA, "generation-1", b"late"))
        self.assertTrue(host.is_retiring_generation("generation-1"))


class MemorySocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.peer: "MemorySocket | None" = None
        self.closed = 0

    async def send(self, data: bytes) -> None:
        if self.peer is None:
            await asyncio.Future()
        await self.peer.incoming.put(data)  # type: ignore[union-attr]

    async def recv(self) -> bytes:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed += 1


class WireClientTests(unittest.TestCase):
    def test_bidirectional_probe_and_generation_data(self) -> None:
        async def run() -> None:
            first, second = MemorySocket(), MemorySocket()
            first.peer, second.peer = second, first
            host, guest = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
            await host.connect(first)
            await guest.connect(second)
            await asyncio.gather(host.wait_ready(), guest.wait_ready())
            await host.send(FrameKind.GENERATION_OFFER, "generation-1", b"setup")
            self.assertEqual((await guest.receive()).kind, FrameKind.GENERATION_OFFER)
            await guest.send(FrameKind.GENERATION_ACCEPT, "generation-1")
            self.assertEqual((await host.receive()).kind, FrameKind.GENERATION_ACCEPT)
            await host.send(FrameKind.DATA, "generation-1", b"host-data", flags=0x0100)
            received = await guest.receive()
            self.assertEqual((received.payload, received.flags), (b"host-data", 0x0100))
            await guest.send(FrameKind.DATA, "generation-1", b"guest-data")
            self.assertEqual((await host.receive()).payload, b"guest-data")
            await asyncio.gather(host.close(), guest.close())

        asyncio.run(run())

    def test_run_stops_for_permanent_auth_and_respects_cancellation(self) -> None:
        async def run() -> None:
            client, cancel = WireClient(PairSeat.HOST), asyncio.Event()
            attempts = 0

            async def rejected() -> MemorySocket:
                nonlocal attempts
                attempts += 1
                raise TransportError("T_AUTH_INVALID")

            with self.assertRaisesRegex(TransportError, "T_AUTH_INVALID"):
                await client.run(rejected, cancel, backoff_base=0.001, backoff_cap=0.002)
            self.assertEqual(attempts, 1)
            cancel.set()
            await client.run(rejected, cancel)
            self.assertEqual(attempts, 1)

        asyncio.run(run())

    def test_run_retries_with_bounded_wait_until_cancelled(self) -> None:
        async def run() -> None:
            client, cancel = WireClient(PairSeat.HOST), asyncio.Event()
            attempts = 0

            async def connector() -> MemorySocket:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise TransportError("T_TRANSPORT_FAILED")
                cancel.set()
                return MemorySocket()

            await client.run(connector, cancel, backoff_base=0.001, backoff_cap=0.002)
            self.assertEqual(attempts, 2)

        asyncio.run(run())

    def test_reconnect_replaces_queues_and_starts_a_fresh_epoch(self) -> None:
        async def run() -> None:
            client = WireClient(PairSeat.HOST)
            await client.connect(MemorySocket())
            first_epoch, first_queue = client.state._epoch, client._outgoing
            await client.connect(MemorySocket())
            self.assertNotEqual(client.state._epoch, first_epoch)
            self.assertIsNot(client._outgoing, first_queue)
            await client.close()

        asyncio.run(run())

    def test_dropped_frame_reconnect_resyncs_each_epoch_once(self) -> None:
        async def run() -> None:
            host_socket, guest_socket = MemorySocket(), MemorySocket()
            host_socket.peer, guest_socket.peer = guest_socket, host_socket
            host, guest = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
            await host.connect(host_socket)
            await guest.connect(guest_socket)
            await asyncio.gather(host.wait_ready(), guest.wait_ready())
            host_epoch, guest_epoch = host.state._epoch, guest.state._epoch
            await host.send(FrameKind.GENERATION_OFFER, "old-generation", b"setup")
            self.assertEqual((await guest.receive()).kind, FrameKind.GENERATION_OFFER)
            await guest.send(FrameKind.GENERATION_ACCEPT, "old-generation")
            self.assertEqual((await host.receive()).kind, FrameKind.GENERATION_ACCEPT)
            await guest.close()
            await host.send(FrameKind.DATA, "old-generation", b"stale")
            dropped = Envelope.decode(await asyncio.wait_for(guest_socket.incoming.get(), timeout=1))
            self.assertEqual((dropped.kind, dropped.source_epoch, dropped.sequence), (FrameKind.DATA, host_epoch, 4))
            reconnected_guest = MemorySocket()
            host_socket.peer, reconnected_guest.peer = reconnected_guest, host_socket
            await guest.connect(reconnected_guest)
            await asyncio.gather(host.wait_ready(), guest.wait_ready())
            self.assertNotEqual(host.state._epoch, host_epoch)
            self.assertNotEqual(guest.state._epoch, guest_epoch)
            resynced_epochs = (host.state._epoch, guest.state._epoch)
            await asyncio.sleep(0)
            self.assertEqual((host.state._epoch, guest.state._epoch), resynced_epochs)
            await host.send(FrameKind.GENERATION_OFFER, "new-generation", b"setup")
            self.assertEqual((await guest.receive()).generation_id, "new-generation")
            await guest.send(FrameKind.GENERATION_ACCEPT, "new-generation")
            self.assertEqual((await host.receive()).generation_id, "new-generation")
            await asyncio.gather(host.close(), guest.close())

        asyncio.run(run())

    def test_queue_full_and_close_do_not_corrupt_client_state(self) -> None:
        async def run() -> None:
            socket = MemorySocket()
            client = WireClient(PairSeat.HOST, queue_limit=2)
            await client.connect(socket)
            sequence = client.state._next_sequence
            with self.assertRaisesRegex(TransportError, "T_SEND_QUEUE_FULL"):
                await client.send(FrameKind.GENERATION_OFFER, "generation-1", b"setup")
            self.assertEqual(client.state._next_sequence, sequence)
            self.assertIsNone(client.state._outbound_offer)
            await client.close()
            await client.close()
            self.assertEqual(socket.closed, 1)

        asyncio.run(run())

    def test_receive_queue_full_and_send_timeout_fail_closed(self) -> None:
        async def run() -> None:
            first, second = MemorySocket(), MemorySocket()
            first.peer, second.peer = second, first
            host, guest = WireClient(PairSeat.HOST, queue_limit=2), WireClient(PairSeat.GUEST)
            await host.connect(first)
            await guest.connect(second)
            await asyncio.gather(host.wait_ready(), guest.wait_ready())
            for _ in range(3):
                await guest.send(FrameKind.CAPABILITIES, payload=b"caps")
            await asyncio.sleep(0)
            with self.assertRaisesRegex(TransportError, "T_RECEIVE_QUEUE_FULL"):
                await host.receive()
            await asyncio.gather(host.close(), guest.close())
            timeout_socket = MemorySocket()
            timed_out = WireClient(PairSeat.HOST, send_timeout=0.001)
            await timed_out.connect(timeout_socket)
            await asyncio.wait_for(timed_out._failed.wait(), timeout=1)
            with self.assertRaisesRegex(TransportError, "T_TRANSPORT_FAILED"):
                await timed_out.send(FrameKind.HEARTBEAT)
            await timed_out.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
