"""Thread-safe, opaque Core DATA boundary for a local ``TunnelSim``."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import threading
from typing import Deque

from switchtrade.core.contracts import LinkPacket
from switchtrade.rfu_tunnel import Kind, MAX_PAYLOAD_BYTES

from .errors import SwitchLdnEndpointError


@dataclass(frozen=True)
class CoreRfuFrame:
    """The minimum envelope shape consumed by ``TunnelSim``; payload stays opaque."""

    payload: bytes
    flags: int
    kind: Kind = Kind.RFU


class CoreTunnelAdapter:
    """Bridge one Core generation to a local RFU tunnel without decoding RFU bytes."""

    def __init__(self, generation_id: str, protocol_id: str, *, capacity: int = 256) -> None:
        if not generation_id or capacity < 1:
            raise ValueError("Core tunnel identity and capacity are required")
        self._generation_id = generation_id
        self._protocol_id = protocol_id
        self._capacity = capacity
        self._lock = threading.Lock()
        self._local_to_core: Deque[LinkPacket] = deque()
        self._core_to_local: Deque[CoreRfuFrame] = deque()
        self._local_ready = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._connection_generation = 1
        self.connected = threading.Event()
        self.connected.set()

    @property
    def connection_generation(self) -> int:
        with self._lock:
            return self._connection_generation

    def send_rfu(self, payload: bytes, *, flags: int) -> None:
        """Admit local Reliable bytes for Core delivery, or fail before dropping state."""
        payload = self._validated_payload(payload)
        self._validated_flags(flags)
        with self._lock:
            self._admit_open()
            if len(self._local_to_core) >= self._capacity:
                raise SwitchLdnEndpointError(
                    "SWITCH_ENDPOINT_BACKPRESSURE", "Core tunnel outbound queue is full"
                )
            self._local_to_core.append(
                LinkPacket(self._generation_id, self._protocol_id, payload, flags)
            )
        self._signal_local_ready()

    async def receive_for_core(self) -> LinkPacket:
        """Wait for one local RFU frame without creating orphan helper tasks."""
        loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._loop is None:
                    self._loop = loop
                elif self._loop is not loop:
                    raise RuntimeError("Core tunnel was bound to another event loop")
                if self._local_to_core:
                    return self._local_to_core.popleft()
                if self._closed:
                    raise RuntimeError("Switch LDN generation is closed")
                self._local_ready.clear()
            await self._local_ready.wait()

    async def deliver_from_core(self, packet: LinkPacket) -> None:
        """Admit Core DATA for the next synchronous ``TunnelSim.poll`` call."""
        self._validate_packet(packet)
        with self._lock:
            self._admit_open()
            if len(self._core_to_local) >= self._capacity:
                raise SwitchLdnEndpointError(
                    "SWITCH_ENDPOINT_BACKPRESSURE", "Core tunnel inbound queue is full"
                )
            self._core_to_local.append(CoreRfuFrame(bytes(packet.payload), packet.flags))

    def poll(self) -> list[CoreRfuFrame]:
        """Return the current Core DATA batch to TunnelSim in insertion order."""
        with self._lock:
            if self._closed or not self.connected.is_set():
                self._core_to_local.clear()
                return []
            frames = list(self._core_to_local)
            self._core_to_local.clear()
            return frames

    def reset(self, generation_id: str) -> None:
        """Drop both queues before admitting a new Core connection generation."""
        if not generation_id:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_GENERATION_INVALID", "Core generation identity is required"
            )
        with self._lock:
            self._generation_id = generation_id
            self._local_to_core.clear()
            self._core_to_local.clear()
            self._connection_generation += 1
            self._closed = False
            self.connected.set()
        self._signal_local_ready()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._local_to_core.clear()
            self._core_to_local.clear()
            self._connection_generation += 1
            self.connected.clear()
        self._signal_local_ready()

    def _validate_packet(self, packet: LinkPacket) -> None:
        if (
            packet.generation_id != self._generation_id
            or packet.protocol_id != self._protocol_id
        ):
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_GENERATION_MISMATCH", "Core DATA belongs to another generation"
            )
        self._validated_payload(packet.payload)
        self._validated_flags(packet.flags)

    @staticmethod
    def _validated_payload(payload: bytes) -> bytes:
        try:
            value = bytes(payload)
        except (TypeError, ValueError) as error:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_PAYLOAD_INVALID", "RFU payload is invalid"
            ) from error
        if len(value) > MAX_PAYLOAD_BYTES:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_PAYLOAD_INVALID", "RFU payload exceeds the reliable wire bound"
            )
        return value

    @staticmethod
    def _validated_flags(flags: int) -> None:
        if isinstance(flags, bool) or not isinstance(flags, int) or not 0 <= flags <= 0xFFFF:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_FLAGS_INVALID", "RFU flags are outside the Core wire bound"
            )

    def _admit_open(self) -> None:
        if self._closed or not self.connected.is_set():
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_TUNNEL_CLOSED", "Core tunnel is not connected"
            )

    def _signal_local_ready(self) -> None:
        with self._lock:
            loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._local_ready.set)


__all__ = ("CoreRfuFrame", "CoreTunnelAdapter")
