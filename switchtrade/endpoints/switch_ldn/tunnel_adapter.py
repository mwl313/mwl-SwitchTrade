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
        self._remote_space = asyncio.Event()
        self._deliver_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sealed = False
        self._failure: BaseException | None = None
        self._closed = False
        self._connection_generation = 1
        self._remote_waits = self._local_deferrals = 0
        self.connected = threading.Event()
        self.connected.set()

    @property
    def connection_generation(self) -> int:
        with self._lock:
            return self._connection_generation

    def send_rfu(self, payload: bytes, *, flags: int) -> None:
        """Admit local Reliable bytes for Core delivery, or fail before dropping state."""
        if not self.try_send_rfu(payload, flags=flags):
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_BACKPRESSURE", "Core tunnel outbound queue is full"
            )

    def try_send_rfu(self, payload: bytes, *, flags: int) -> bool:
        """False leaves the local Reliable sender responsible for retransmission."""
        payload = self._validated_payload(payload)
        self._validated_flags(flags)
        with self._lock:
            self._admit_open()
            if len(self._local_to_core) >= self._capacity:
                self._local_deferrals += 1
                return False
            self._local_to_core.append(
                LinkPacket(self._generation_id, self._protocol_id, payload, flags)
            )
        self._signal_local_ready()
        return True

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
                if self._failure is not None:
                    raise self._failure
                if self._sealed or self._closed:
                    raise RuntimeError("Switch LDN generation is closed")
                self._local_ready.clear()
            await self._local_ready.wait()

    async def deliver_from_core(self, packet: LinkPacket) -> None:
        """Wait for bounded local capacity without blocking the radio/ACK thread."""
        # Copy before waiting: admission cannot later observe caller mutations.
        packet = LinkPacket(packet.generation_id, packet.protocol_id,
                            self._validated_payload(packet.payload), packet.flags)
        with self._lock:
            self._validate_packet(packet)
            self._admit_open()
            epoch = self._connection_generation
            loop = asyncio.get_running_loop()
            if self._loop is None:
                self._loop = loop
            elif self._loop is not loop:
                raise RuntimeError("Core tunnel was bound to another event loop")
        # Serialize waiting producers so cancellation cannot reorder survivors.
        async with self._deliver_lock:
            while True:
                with self._lock:
                    self._admit_open()
                    self._validate_packet(packet)
                    if epoch != self._connection_generation:
                        raise SwitchLdnEndpointError(
                            "SWITCH_ENDPOINT_GENERATION_MISMATCH", "Core connection was replaced"
                        )
                    if len(self._core_to_local) < self._capacity:
                        self._core_to_local.append(CoreRfuFrame(packet.payload, packet.flags))
                        return
                    self._remote_space.clear()
                    self._remote_waits += 1
                await self._remote_space.wait()

    def flow_status(self) -> dict[str, int]:
        """Counts only, safe for diagnostic logs; no game or device identity."""
        with self._lock:
            return {"core_to_local_queue": len(self._core_to_local),
                    "local_to_core_queue": len(self._local_to_core),
                    "queue_capacity": self._capacity, "remote_waits": self._remote_waits,
                    "local_deferrals": self._local_deferrals}

    def poll(self, limit: int | None = None) -> list[CoreRfuFrame]:
        """Take only downstream demand, retaining the rest in insertion order."""
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("poll limit must be a non-negative integer")
        with self._lock:
            if self._sealed or self._closed or not self.connected.is_set():
                self._core_to_local.clear()
                return []
            count = len(self._core_to_local) if limit is None else min(limit, len(self._core_to_local))
            frames = [self._core_to_local.popleft() for _ in range(count)]
        if frames:
            self._signal_local_ready()
        return frames

    def reset(self, generation_id: str) -> None:
        """Drop both queues before admitting a new Core connection generation."""
        if not generation_id:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_GENERATION_INVALID", "Core generation identity is required"
            )
        with self._lock:
            if self._failure is not None:
                raise self._failure
            if self._sealed or self._closed:
                raise SwitchLdnEndpointError(
                    "SWITCH_ENDPOINT_TUNNEL_CLOSED", "Core tunnel is not connected"
                )
            self._generation_id = generation_id
            self._local_to_core.clear()
            self._core_to_local.clear()
            self._connection_generation += 1
            self._remote_waits = self._local_deferrals = 0
            self.connected.set()
        self._signal_local_ready()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._sealed = True
            self._closed = True
            self._local_to_core.clear()
            self._core_to_local.clear()
            self._connection_generation += 1
            self.connected.clear()
        self._signal_local_ready()

    def seal(self) -> None:
        """Stop DATA admission before local simulation teardown."""
        with self._lock:
            self._sealed = True
            self._local_to_core.clear()
            self._core_to_local.clear()
        self._signal_local_ready()

    def fail(self, error: BaseException) -> None:
        """Wake Core receive with the first local simulation failure."""
        with self._lock:
            if self._failure is None:
                self._failure = error
            self._sealed = True
            self._local_to_core.clear()
            self._core_to_local.clear()
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
        if isinstance(flags, bool) or not isinstance(flags, int) or not 0 <= flags <= 0xFF or not flags & 1:
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_FLAGS_INVALID", "RFU requires uint8 Reliable AppData flags"
            )

    def _admit_open(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self._sealed or self._closed or not self.connected.is_set():
            raise SwitchLdnEndpointError(
                "SWITCH_ENDPOINT_TUNNEL_CLOSED", "Core tunnel is not connected"
            )

    def _signal_local_ready(self) -> None:
        with self._lock:
            loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._local_ready.set)
            loop.call_soon_threadsafe(self._remote_space.set)


__all__ = ("CoreRfuFrame", "CoreTunnelAdapter")
