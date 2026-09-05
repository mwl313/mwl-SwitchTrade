"""One Switch LDN generation and its local TunnelSim seam."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from collections.abc import Callable
import threading
import time
from typing import Protocol

from switchtrade.connection.stage_session import StageResources, StageSession
from switchtrade.core.contracts import CleanupReport, GenerationOffer, LinkPacket

from .errors import SwitchLdnEndpointError
from .tunnel_adapter import CoreTunnelAdapter


class Simulation(Protocol):
    def tick(self) -> None: ...
    def close(self) -> None: ...


SimulationFactory = Callable[[StageResources, CoreTunnelAdapter, bool], Simulation]
_VBLANK_SECONDS = 1 / 59.727
_RUNNER_STOP_TIMEOUT = 5


def build_tunnelsim(
    resources: StageResources, tunnel: CoreTunnelAdapter, parent: bool
) -> Simulation:
    """Create the existing Pia/Reliable simulation at the endpoint boundary only."""
    bridge = Path(__file__).resolve().parents[3] / "bridge"
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    from frlgsim import crypto as cryptomod
    from frlgsim import pia_connect
    from frlgsim.tunnel import TunnelSim

    transport = resources.transport
    our_var = max(2, int.from_bytes(os.urandom(2), "big"))
    crypto = cryptomod.PiaCrypto(transport.ssid)
    if parent:
        connection = pia_connect.HostConnectionManager(
            our_mac=transport.our_mac,
            our_ip=transport.our_ip,
            network_id=crypto.net_id,
            our_var=our_var,
            peer_provider=lambda: (transport.host_mac, transport.host_ip),
            player_name="SwitchTrade",
            log=lambda *_parts: None,
        )
    else:
        connection = pia_connect.ConnectionManager(
            our_mac=transport.our_mac,
            host_mac=transport.host_mac,
            our_ip=transport.our_ip,
            host_ip=transport.host_ip,
            our_var=our_var,
            player_name="SwitchTrade",
            random4=os.urandom(4),
            log=lambda *_parts: None,
        )
    return TunnelSim(
        transport, crypto, transport.our_ip, transport.host_ip, tunnel,
        conn=connection, our_var=our_var, parent=parent,
    )


class SwitchLdnGeneration:
    """Own a sustained Direct A/B session and map Core DATA to opaque RFU bytes."""

    def __init__(
        self,
        offer: GenerationOffer,
        session: StageSession,
        resources: StageResources,
        on_closed: Callable[[bool], None],
        *,
        parent: bool,
        simulation_factory: SimulationFactory = build_tunnelsim,
        tunnel_capacity: int = 256,
    ) -> None:
        self.offer = offer
        self.parent = parent
        self._session = session
        self._on_closed = on_closed
        self.tunnel = CoreTunnelAdapter(
            offer.generation_id, offer.protocol_id, capacity=tunnel_capacity
        )
        self.simulation = simulation_factory(resources, self.tunnel, parent)
        self._runner_stop = threading.Event()
        self._tick_failure: SwitchLdnEndpointError | None = None
        self._runner = threading.Thread(
            target=self._drive_simulation, name="switchtrade-tunnelsim", daemon=True
        )
        self._runner.start()
        self._report: CleanupReport | None = None

    @property
    def runner_alive(self) -> bool:
        return self._runner.is_alive()

    async def receive(self) -> LinkPacket:
        return await self.tunnel.receive_for_core()

    async def send(self, packet: LinkPacket) -> None:
        await self.tunnel.deliver_from_core(packet)

    async def close(self, outcome: str) -> CleanupReport:
        del outcome
        if self._report is not None:
            return self._report
        self.tunnel.seal()
        self._runner_stop.set()
        await asyncio.to_thread(self._runner.join, _RUNNER_STOP_TIMEOUT)
        failures: list[str] = []
        runner_timed_out = self._runner.is_alive()
        if runner_timed_out:
            failures.append("runner:timeout")
        try:
            self.simulation.close()
        except BaseException as error:
            failures.append(f"simulation:{type(error).__name__}")
        try:
            await asyncio.to_thread(self._session.stop)
        except BaseException as error:
            failures.append(f"stage_session:{type(error).__name__}")
        if runner_timed_out:
            await asyncio.to_thread(self._runner.join, _RUNNER_STOP_TIMEOUT)
        self.tunnel.close()
        cleaned = not failures
        self._on_closed(cleaned)
        self._report = CleanupReport(
            cleaned,
            cleaned,
            True,
            {
                "endpoint_kind": "switch_ldn",
                "tunnel_parent": self.parent,
                "primary_failure_code": self._tick_failure.code if self._tick_failure else None,
                "cleanup_errors": tuple(failures),
            },
        )
        return self._report

    def _drive_simulation(self) -> None:
        deadline = time.monotonic()
        while not self._runner_stop.is_set():
            try:
                self.simulation.tick()
            except BaseException as error:
                failure = SwitchLdnEndpointError(
                    "SWITCH_ENDPOINT_TICK_FAILED", "Switch LDN simulation tick failed"
                )
                failure.__cause__ = error
                self._tick_failure = failure
                self.tunnel.fail(failure)
                return
            deadline += _VBLANK_SECONDS
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                deadline = time.monotonic() + _VBLANK_SECONDS
                remaining = _VBLANK_SECONDS
            self._runner_stop.wait(remaining)


LeaderGeneration = SwitchLdnGeneration
MirrorGeneration = SwitchLdnGeneration


__all__ = (
    "LeaderGeneration",
    "MirrorGeneration",
    "SimulationFactory",
    "SwitchLdnGeneration",
    "build_tunnelsim",
)
