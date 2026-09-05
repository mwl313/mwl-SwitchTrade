from __future__ import annotations

import asyncio
import unittest

from switchtrade.core.contracts import CleanupReport, EndpointCapabilities, EndpointKind, GenerationOffer, GenerationRole, LinkPacket, PairCredentials, PairSeat, RuntimeKind
from switchtrade.core.supervisor import CoreSupervisor, SupervisorError, SupervisorState
from switchtrade.endpoints.fake import FAKE_PROTOCOL
from switchtrade.transport import Envelope, FrameKind, TransportError, WireClient


class MemorySocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes | Exception] = asyncio.Queue()
        self.peer: MemorySocket | None = None
        self.closed = 0

    async def send(self, data: bytes) -> None:
        await self.peer.incoming.put(data)  # type: ignore[union-attr]

    async def recv(self) -> bytes:
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed += 1


class TestGeneration:
    def __init__(self, offer: GenerationOffer, *, clean: bool = True, close_error: bool = False, close_wait: asyncio.Event | None = None) -> None:
        self.offer, self.clean = offer, clean
        self.close_error = close_error
        self.close_wait = close_wait
        self.incoming: asyncio.Queue[LinkPacket] = asyncio.Queue()
        self.sent: list[LinkPacket] = []
        self.sent_event = asyncio.Event()
        self.closed = 0
        self.closed_event = asyncio.Event()

    async def receive(self) -> LinkPacket:
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, packet: LinkPacket) -> None:
        self.sent.append(packet)
        self.sent_event.set()

    async def close(self, outcome: str) -> CleanupReport:
        self.closed += 1
        self.closed_event.set()
        if self.close_wait is not None:
            await self.close_wait.wait()
        if self.close_error:
            raise RuntimeError("close failed")
        return CleanupReport(self.clean, self.clean, self.clean, {"outcome": outcome})


class TestDriver:
    capabilities = EndpointCapabilities(EndpointKind.FAKE, RuntimeKind.IN_PROCESS, (FAKE_PROTOCOL,), (GenerationRole.ORIGIN, GenerationRole.MIRROR))

    def __init__(self, generation: TestGeneration, *, discoveries: list[TestGeneration] | None = None, fail_prepare: bool = False, fail_close: bool = False) -> None:
        self.generation, self.fail_prepare, self.fail_close, self.closed = generation, fail_prepare, fail_close, 0
        self.discoveries = list(discoveries or ())

    async def prepare(self) -> None:
        if self.fail_prepare:
            raise RuntimeError("prepare failed")

    async def discover(self, cancel: asyncio.Event) -> TestGeneration:
        if self.discoveries:
            self.generation = self.discoveries.pop(0)
        return self.generation

    async def accept(self, offer: GenerationOffer, cancel: asyncio.Event) -> TestGeneration:
        self.generation.offer = offer
        return self.generation

    async def close(self) -> CleanupReport:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("driver close failed")
        return CleanupReport(True, True, True, {})


class ClosingSocket(MemorySocket):
    async def close(self) -> None:
        if self.closed == 0 and self.peer is not None:
            await self.peer.incoming.put(ConnectionError("peer closed"))
        await super().close()


class SocketFactory:
    def __init__(self) -> None:
        self.pending: dict[PairSeat, ClosingSocket] = {}

    async def connect(self, seat: PairSeat) -> ClosingSocket:
        socket = self.pending.pop(seat, None)
        if socket is None:
            host, guest = ClosingSocket(), ClosingSocket()
            host.peer, guest.peer = guest, host
            self.pending = {PairSeat.HOST: host, PairSeat.GUEST: guest}
            socket = self.pending.pop(seat)
        return socket


def credentials(seat: PairSeat) -> PairCredentials:
    return PairCredentials("pair", seat, f"{seat}-token", "2099-01-01T00:00:00+00:00", "123456" if seat is PairSeat.HOST else None)


class CoreSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_for_packet(self, generation: TestGeneration, expected: LinkPacket) -> None:
        async with asyncio.timeout(1):
            while expected not in generation.sent:
                generation.sent_event.clear()
                if expected not in generation.sent:
                    await generation.sent_event.wait()

    async def _wait_for_close(self, generation: TestGeneration) -> None:
        await asyncio.wait_for(generation.closed_event.wait(), timeout=1)

    async def _wait_for_state(self, supervisor: CoreSupervisor, state: SupervisorState) -> None:
        async with asyncio.timeout(1):
            while supervisor.state is not state:
                await asyncio.sleep(0)

    async def asyncSetUp(self) -> None:
        first, second = MemorySocket(), MemorySocket()
        first.peer, second.peer = second, first
        self.host_socket = first
        self.host_wire, self.guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await self.host_wire.connect(first)
        await self.guest_wire.connect(second)
        self.host_generation = TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        self.guest_generation = TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))
        self.host_driver, self.guest_driver = TestDriver(self.host_generation), TestDriver(self.guest_generation)
        self.host = CoreSupervisor(credentials(PairSeat.HOST), self.host_driver, self.host_wire)
        self.guest = CoreSupervisor(credentials(PairSeat.GUEST), self.guest_driver, self.guest_wire)

    async def asyncTearDown(self) -> None:
        await asyncio.gather(self.host.stop(), self.guest.stop(), return_exceptions=True)

    async def test_local_before_peer_offer_accept_and_bidirectional_pump(self) -> None:
        await self.host.prepare()
        offer = await self.host.discover_local()
        self.assertEqual(self.host.pair_code, "123456")
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        self.assertEqual((self.host.state, self.guest.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        await self.host_generation.incoming.put(LinkPacket(offer.generation_id, FAKE_PROTOCOL, b"host"))
        await self.guest_generation.incoming.put(LinkPacket(offer.generation_id, FAKE_PROTOCOL, b"guest", 0x0100))
        await self._wait_for_packet(self.guest_generation, LinkPacket(offer.generation_id, FAKE_PROTOCOL, b"host"))
        await self._wait_for_packet(self.host_generation, LinkPacket(offer.generation_id, FAKE_PROTOCOL, b"guest", 0x0100))

    async def test_cleanup_failure_blocks_next_generation_and_first_failure_wins(self) -> None:
        bad = TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"), clean=False)
        supervisor = CoreSupervisor(credentials(PairSeat.HOST), TestDriver(bad), self.host_wire)
        await supervisor.prepare()
        await supervisor.discover_local()
        with self.assertRaisesRegex(SupervisorError, "S_CLEANUP_FAILED"):
            await supervisor.close_generation()
        first = supervisor.failure
        with self.assertRaises(SupervisorError) as blocked:
            await supervisor.discover_local()
        self.assertIs(blocked.exception, first)

    async def test_clean_close_permits_a_next_generation(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host.close_generation()
        self.assertIsNone(self.host.generation_id)
        self.assertEqual(self.host.state, SupervisorState.PAIRED)
        self.host_driver.generation = TestGeneration(GenerationOffer("generation-2", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        offer = await self.host.discover_local()
        self.assertEqual(offer.generation_id, "generation-2")

    async def test_close_discards_queued_old_data_before_next_generation(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        release_close = asyncio.Event()
        self.host_generation.close_wait = release_close
        close_task = asyncio.create_task(self.host.close_generation())
        await self._wait_for_close(self.host_generation)
        await self.host_wire._incoming.put(Envelope(FrameKind.DATA, PairSeat.GUEST, 1, 1, "generation-1", b"old"))
        release_close.set()
        await close_task
        await self._wait_for_close(self.guest_generation)
        self.assertEqual(self.host.discarded_remote_packets, 1)
        self.host_driver.generation = TestGeneration(GenerationOffer("generation-2", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        self.guest_driver.generation = TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host_driver.generation.incoming.put(LinkPacket("generation-2", FAKE_PROTOCOL, b"fresh"))
        await self._wait_for_packet(self.guest_driver.generation, LinkPacket("generation-2", FAKE_PROTOCOL, b"fresh"))

    async def test_local_failure_cleans_generation_and_preserves_first_failure(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host_generation.incoming.put(RuntimeError("local failed"))
        await self._wait_for_close(self.host_generation)
        self.assertEqual(self.host.failure.code, "S_PUMP_FAILED")  # type: ignore[union-attr]
        self.assertIsNone(self.host.generation_id)
        self.assertEqual(self.host.state, SupervisorState.FAILED)

    async def test_wait_generation_end_surfaces_pump_failure(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host_generation.incoming.put(RuntimeError("local failed"))
        with self.assertRaisesRegex(SupervisorError, "S_PUMP_FAILED"):
            await self.host.wait_generation_end()

    async def test_wait_generation_end_returns_after_clean_peer_close(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host.close_generation()
        await self.guest.wait_generation_end()
        self.assertEqual(self.guest.state, SupervisorState.PAIRED)

    async def test_failure_stop_preserves_failed_terminal_state(self) -> None:
        failed = CoreSupervisor(credentials(PairSeat.HOST), TestDriver(self.host_generation, fail_prepare=True), self.host_wire)
        with self.assertRaisesRegex(SupervisorError, "S_ENDPOINT_FAILED"):
            await failed.prepare()
        failure = failed.failure
        await failed.stop()
        self.assertIs(failed.failure, failure)
        self.assertEqual(failed.state, SupervisorState.FAILED)

    async def test_cleanup_exceptions_still_close_driver_and_transport(self) -> None:
        bad = TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"), close_error=True)
        driver = TestDriver(bad)
        supervisor = CoreSupervisor(credentials(PairSeat.HOST), driver, self.host_wire)
        await supervisor.prepare()
        await supervisor.discover_local()
        with self.assertRaisesRegex(SupervisorError, "S_CLEANUP_FAILED"):
            await supervisor.stop()
        self.assertEqual((driver.closed, self.host_socket.closed), (1, 1))
        self.assertEqual(supervisor.state, SupervisorState.FAILED)

    async def test_driver_cleanup_failure_still_closes_transport(self) -> None:
        driver = TestDriver(self.host_generation, fail_close=True)
        supervisor = CoreSupervisor(credentials(PairSeat.HOST), driver, self.host_wire)
        with self.assertRaisesRegex(SupervisorError, "S_CLEANUP_FAILED"):
            await supervisor.stop()
        self.assertEqual((driver.closed, self.host_socket.closed), (1, 1))

    async def test_malformed_offer_keeps_offer_error_identity(self) -> None:
        await asyncio.gather(self.host.wait_for_peer(), self.guest.wait_for_peer())
        await self.host_wire.send(FrameKind.GENERATION_OFFER, "generation-1", b"{")
        with self.assertRaisesRegex(SupervisorError, "S_OFFER_INVALID"):
            await self.guest.accept_next_offer()
        self.assertEqual(self.guest.failure.code, "S_OFFER_INVALID")  # type: ignore[union-attr]

    async def test_transport_receive_and_accept_send_keep_transport_error_identity(self) -> None:
        self.guest_wire._fail(RuntimeError("receive failed"))
        with self.assertRaisesRegex(SupervisorError, "S_TRANSPORT_FAILED"):
            await self.guest.accept_next_offer()
        self.assertEqual(self.guest.failure.code, "S_TRANSPORT_FAILED")  # type: ignore[union-attr]

        first, second = MemorySocket(), MemorySocket()
        first.peer, second.peer = second, first
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(first)
        await guest_wire.connect(second)
        host = CoreSupervisor(credentials(PairSeat.HOST), TestDriver(TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))), host_wire)
        guest = CoreSupervisor(credentials(PairSeat.GUEST), TestDriver(TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))), guest_wire)
        await asyncio.gather(host.wait_for_peer(), guest.wait_for_peer())
        await host_wire.send(FrameKind.GENERATION_OFFER, "generation-1", b'{"origin_endpoint_kind":"fake","protocol_id":"switchtrade.fake.v1","setup_payload":""}')

        async def failed_send(*args: object, **kwargs: object) -> None:
            raise TransportError("T_TRANSPORT_FAILED")

        guest_wire.send = failed_send  # type: ignore[method-assign]
        with self.assertRaisesRegex(SupervisorError, "S_TRANSPORT_FAILED"):
            await guest.accept_next_offer()
        self.assertEqual(guest.failure.code, "S_TRANSPORT_FAILED")  # type: ignore[union-attr]
        await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_peer_before_local_offer_accepts(self) -> None:
        guest_task = asyncio.create_task(self.guest.accept_next_offer())
        await self.host.offer_generation()
        await guest_task
        self.assertEqual((self.host.state, self.guest.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))

    async def test_transport_loss_recovers_pair_and_allows_a_new_generation(self) -> None:
        factory = SocketFactory()
        host_socket = await factory.connect(PairSeat.HOST)
        guest_socket = await factory.connect(PairSeat.GUEST)
        host_wire, guest_wire = WireClient(PairSeat.HOST), WireClient(PairSeat.GUEST)
        await host_wire.connect(host_socket)
        await guest_wire.connect(guest_socket)
        host_driver = TestDriver(TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup")))
        guest_driver = TestDriver(TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b"")))
        host = CoreSupervisor(credentials(PairSeat.HOST), host_driver, host_wire, connector=lambda: factory.connect(PairSeat.HOST), reconnect_timeout=1)
        guest = CoreSupervisor(credentials(PairSeat.GUEST), guest_driver, guest_wire, connector=lambda: factory.connect(PairSeat.GUEST), reconnect_timeout=1)
        await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
        await host_socket.incoming.put(ConnectionError("relay lost"))
        await asyncio.gather(self._wait_for_state(host, SupervisorState.PAIRED), self._wait_for_state(guest, SupervisorState.PAIRED))
        self.assertIsNone(host.failure)
        host_driver.generation = TestGeneration(GenerationOffer("generation-2", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        guest_driver.generation = TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))
        await asyncio.gather(host.offer_generation(), guest.accept_next_offer())
        await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_host_waits_for_peer_without_failing(self) -> None:
        factory = SocketFactory()
        host_socket = await factory.connect(PairSeat.HOST)
        host_wire = WireClient(PairSeat.HOST)
        await host_wire.connect(host_socket)
        host_driver = TestDriver(TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup")))
        host = CoreSupervisor(credentials(PairSeat.HOST), host_driver, host_wire)
        offer_task = asyncio.create_task(host.offer_generation())
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(offer_task), timeout=0.25)
        self.assertEqual(host.state, SupervisorState.WAITING_FOR_PEER)
        self.assertIsNone(host.failure)
        guest_socket = await factory.connect(PairSeat.GUEST)
        guest_wire = WireClient(PairSeat.GUEST)
        await guest_wire.connect(guest_socket)
        guest = CoreSupervisor(credentials(PairSeat.GUEST), TestDriver(TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))), guest_wire)
        await asyncio.gather(offer_task, guest.accept_next_offer())
        self.assertEqual((host.state, guest.state), (SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_local_before_peer_transport_loss_rediscoveries_before_offer(self) -> None:
        factory = SocketFactory()
        host_socket = await factory.connect(PairSeat.HOST)
        host_wire = WireClient(PairSeat.HOST)
        await host_wire.connect(host_socket)
        first = TestGeneration(GenerationOffer("generation-1", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        second = TestGeneration(GenerationOffer("generation-2", FAKE_PROTOCOL, EndpointKind.FAKE, b"setup"))
        host_driver = TestDriver(first, discoveries=[first, second])
        host = CoreSupervisor(credentials(PairSeat.HOST), host_driver, host_wire, connector=lambda: factory.connect(PairSeat.HOST), reconnect_timeout=0.1)
        offer_task = asyncio.create_task(host.offer_generation())
        await self._wait_for_state(host, SupervisorState.WAITING_FOR_PEER)
        await host_socket.incoming.put(ConnectionError("relay lost"))
        await self._wait_for_close(first)
        await self._wait_for_state(host, SupervisorState.WAITING_FOR_PEER)
        guest_socket = await factory.connect(PairSeat.GUEST)
        guest_wire = WireClient(PairSeat.GUEST)
        await guest_wire.connect(guest_socket)
        guest = CoreSupervisor(credentials(PairSeat.GUEST), TestDriver(TestGeneration(GenerationOffer("placeholder", FAKE_PROTOCOL, EndpointKind.FAKE, b""))), guest_wire)
        await asyncio.gather(offer_task, guest.accept_next_offer())
        self.assertEqual(host.generation_id, "generation-2")
        self.assertEqual((first.closed, host.state, guest.state), (1, SupervisorState.ACTIVE, SupervisorState.ACTIVE))
        await asyncio.gather(host.stop(), guest.stop(), return_exceptions=True)

    async def test_stop_is_idempotent_and_prepare_failure_is_preserved(self) -> None:
        await self.guest.prepare()
        await self.guest.stop()
        await self.guest.stop()
        self.assertEqual(self.guest_driver.closed, 1)


if __name__ == "__main__":
    unittest.main()
