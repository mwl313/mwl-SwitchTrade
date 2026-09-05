"""In-memory endpoint used only by software tests for the Phase B core."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from switchtrade.core.contracts import (
    CleanupReport,
    EndpointCapabilities,
    EndpointKind,
    GenerationOffer,
    GenerationRole,
    LinkPacket,
    RuntimeKind,
)


FAKE_PROTOCOL = "switchtrade.fake.v1"


@dataclass
class _Channel:
    origin_to_core: asyncio.Queue[LinkPacket | None]
    origin_delivered: asyncio.Queue[LinkPacket]
    mirror_to_core: asyncio.Queue[LinkPacket | None]
    mirror_delivered: asyncio.Queue[LinkPacket]


class FakeEndpointHub:
    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._next_id = 0

    def offer(self) -> tuple[str, _Channel]:
        self._next_id += 1
        generation_id = f"fake-{self._next_id}"
        channel = _Channel(*(asyncio.Queue(maxsize=32) for _ in range(4)))
        self._channels[generation_id] = channel
        return generation_id, channel

    def accept(self, generation_id: str) -> _Channel:
        try:
            return self._channels.pop(generation_id)
        except KeyError as error:
            raise ValueError("unknown fake generation") from error


class FakeGeneration:
    def __init__(self, offer: GenerationOffer, incoming: asyncio.Queue[LinkPacket | None], outgoing: asyncio.Queue[LinkPacket | None]) -> None:
        self.offer = offer
        self._incoming = incoming
        self._outgoing = outgoing
        self._closed = False

    async def receive(self) -> LinkPacket:
        if self._closed:
            raise RuntimeError("fake generation closed")
        packet = await self._incoming.get()
        if packet is None:
            raise RuntimeError("fake generation closed")
        return packet

    async def send(self, packet: LinkPacket) -> None:
        if self._closed or packet.generation_id != self.offer.generation_id or packet.protocol_id != self.offer.protocol_id:
            raise ValueError("packet does not belong to this generation")
        await self._outgoing.put(packet)

    async def inject_local(self, packet: LinkPacket) -> None:
        if (
            self._closed
            or packet.generation_id != self.offer.generation_id
            or packet.protocol_id != self.offer.protocol_id
        ):
            raise ValueError("packet does not belong to this generation")
        await self._incoming.put(packet)

    async def receive_delivered(self) -> LinkPacket:
        return await self._outgoing.get()

    async def close(self, outcome: str) -> CleanupReport:
        discarded = 0
        if not self._closed:
            self._closed = True
            while not self._outgoing.empty():
                self._outgoing.get_nowait()
                discarded += 1
            while not self._incoming.empty():
                self._incoming.get_nowait()
                discarded += 1
            self._incoming.put_nowait(None)
        return CleanupReport(True, True, True, {"outcome": outcome, "discarded_packets": discarded})


class FakeEndpointDriver:
    capabilities = EndpointCapabilities(EndpointKind.FAKE, RuntimeKind.IN_PROCESS, (FAKE_PROTOCOL,), (GenerationRole.ORIGIN, GenerationRole.MIRROR))

    def __init__(self, hub: FakeEndpointHub, *, fail_prepare: bool = False, fail_discover: bool = False, fail_accept: bool = False) -> None:
        self._hub = hub
        self._fail_prepare = fail_prepare
        self._fail_discover = fail_discover
        self._fail_accept = fail_accept
        self._prepared = False
        self.generation: FakeGeneration | None = None

    async def prepare(self) -> None:
        if self._fail_prepare:
            raise RuntimeError("fake prepare failure")
        self._prepared = True

    async def discover(self, cancel: asyncio.Event) -> FakeGeneration:
        if cancel.is_set():
            raise asyncio.CancelledError()
        if not self._prepared or self._fail_discover:
            raise RuntimeError("fake discover failure")
        generation_id, channel = self._hub.offer()
        offer = GenerationOffer(generation_id, FAKE_PROTOCOL, EndpointKind.FAKE, generation_id.encode())
        self.generation = FakeGeneration(offer, channel.origin_to_core, channel.origin_delivered)
        return self.generation

    async def accept(self, offer: GenerationOffer, cancel: asyncio.Event) -> FakeGeneration:
        if cancel.is_set():
            raise asyncio.CancelledError()
        if not self._prepared or self._fail_accept or offer.protocol_id != FAKE_PROTOCOL:
            raise RuntimeError("fake accept failure")
        channel = self._hub.accept(offer.generation_id)
        self.generation = FakeGeneration(offer, channel.mirror_to_core, channel.mirror_delivered)
        return self.generation

    async def close(self) -> CleanupReport:
        self._prepared = False
        return CleanupReport(True, True, True, {})
