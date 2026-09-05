"""Leader generation ownership before C3 adds the TunnelSim data path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from switchtrade.connection.stage_session import StageSession
from switchtrade.core.contracts import CleanupReport, GenerationOffer, LinkPacket


class LeaderGeneration:
    def __init__(
        self,
        offer: GenerationOffer,
        session: StageSession,
        on_closed: Callable[[bool], None],
    ) -> None:
        self.offer = offer
        self._session = session
        self._on_closed = on_closed
        self._closed = False
        self._report: CleanupReport | None = None
        self._incoming: asyncio.Queue[LinkPacket | None] = asyncio.Queue()

    async def receive(self) -> LinkPacket:
        packet = await self._incoming.get()
        if packet is None:
            raise RuntimeError("leader generation is closed")
        return packet

    async def send(self, packet: LinkPacket) -> None:
        del packet
        raise NotImplementedError("Switch LDN data transport is implemented in C3")

    async def close(self, outcome: str) -> CleanupReport:
        del outcome
        if self._report is not None:
            return self._report
        self._closed = True
        self._incoming.put_nowait(None)
        try:
            await asyncio.to_thread(self._session.stop)
        except BaseException as error:
            self._on_closed(False)
            self._report = CleanupReport(
                False,
                False,
                True,
                {"endpoint_kind": "switch_ldn", "cleanup_error": type(error).__name__},
            )
            return self._report
        self._on_closed(True)
        self._report = CleanupReport(True, True, True, {"endpoint_kind": "switch_ldn"})
        return self._report
