from __future__ import annotations

import asyncio
import unittest

from switchtrade.core.contracts import CleanupReport, EndpointCapabilities, EndpointKind, GenerationOffer, GenerationRole, LinkPacket, PairCredentials, PairSeat, RuntimeKind
from switchtrade.core.supervisor import CoreSupervisor, SupervisorError, SupervisorState
from switchtrade.endpoints.fake import FAKE_PROTOCOL
from switchtrade.transport import WireClient


class MemorySocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.peer: MemorySocket | None = None
        self.closed = 0

    async def send(self, data: bytes) -> None:
        await self.peer.incoming.put(data)  # type: ignore[union-attr]

    async def recv(self) -> bytes:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed += 1


class TestGeneration:
    def __init__(self, offer: GenerationOffer, *, clean: bool = True) -> None:
        self.offer, self.clean = offer, clean
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
        return CleanupReport(self.clean, self.clean, self.clean, {"outcome": outcome})


class TestDriver:
    capabilities = EndpointCapabilities(EndpointKind.FAKE, RuntimeKind.IN_PROCESS, (FAKE_PROTOCOL,), (GenerationRole.ORIGIN, GenerationRole.MIRROR))

    def __init__(self, generation: TestGeneration, *, fail_prepare: bool = False) -> None:
        self.generation, self.fail_prepare, self.closed = generation, fail_prepare, 0

    async def prepare(self) -> None:
        if self.fail_prepare:
            raise RuntimeError("prepare failed")

    async def discover(self, cancel: asyncio.Event) -> TestGeneration:
        return self.generation

    async def accept(self, offer: GenerationOffer, cancel: asyncio.Event) -> TestGeneration:
        self.generation.offer = offer
        return self.generation

    async def close(self) -> CleanupReport:
        self.closed += 1
        return CleanupReport(True, True, True, {})


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

    async def asyncSetUp(self) -> None:
        first, second = MemorySocket(), MemorySocket()
        first.peer, second.peer = second, first
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

    async def test_local_failure_cleans_generation_and_preserves_first_failure(self) -> None:
        await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
        await self.host_generation.incoming.put(RuntimeError("local failed"))
        await self._wait_for_close(self.host_generation)
        self.assertEqual(self.host.failure.code, "S_PUMP_FAILED")  # type: ignore[union-attr]
        self.assertIsNone(self.host.generation_id)
        self.assertEqual(self.host.state, SupervisorState.FAILED)

    async def test_stop_is_idempotent_and_prepare_failure_is_preserved(self) -> None:
        failed = CoreSupervisor(credentials(PairSeat.HOST), TestDriver(self.host_generation, fail_prepare=True), self.host_wire)
        with self.assertRaisesRegex(SupervisorError, "S_ENDPOINT_FAILED"):
            await failed.prepare()
        self.assertEqual(failed.state, SupervisorState.FAILED)
        await self.guest.prepare()
        await self.guest.stop()
        await self.guest.stop()
        self.assertEqual(self.guest_driver.closed, 1)


if __name__ == "__main__":
    unittest.main()
