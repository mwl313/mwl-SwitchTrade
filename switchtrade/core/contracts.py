"""Small, endpoint-neutral types shared by the Phase B core."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Mapping, Protocol


MAX_PACKET_BYTES = 1 << 20
MAX_SETUP_BYTES = 1 << 16
_PROTOCOL = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\.v[1-9][0-9]*$")


class PairSeat(StrEnum):
    HOST = "host"
    GUEST = "guest"


class GenerationRole(StrEnum):
    ORIGIN = "origin"
    MIRROR = "mirror"


class EndpointKind(StrEnum):
    FAKE = "fake"


class RuntimeKind(StrEnum):
    IN_PROCESS = "in_process"


def validate_protocol_id(protocol_id: str) -> str:
    if not _PROTOCOL.fullmatch(protocol_id):
        raise ValueError("invalid protocol ID")
    return protocol_id


@dataclass(frozen=True)
class PairCredentials:
    pair_id: str
    seat: PairSeat
    access_token: str
    reconnect_expires_at: str
    code: str | None = None

    def __post_init__(self) -> None:
        if not self.pair_id or not self.access_token or not self.reconnect_expires_at:
            raise ValueError("pair credentials require non-empty identities")


@dataclass(frozen=True)
class EndpointCapabilities:
    endpoint_kind: EndpointKind
    runtime_kind: RuntimeKind
    protocols: tuple[str, ...]
    generation_roles: tuple[GenerationRole, ...]

    def __post_init__(self) -> None:
        if not self.protocols or not self.generation_roles:
            raise ValueError("capabilities require protocols and generation roles")
        validated = tuple(validate_protocol_id(item) for item in self.protocols)
        if len(set(validated)) != len(validated) or len(set(self.generation_roles)) != len(self.generation_roles):
            raise ValueError("capabilities contain duplicates")
        object.__setattr__(self, "protocols", validated)


@dataclass(frozen=True)
class GenerationOffer:
    generation_id: str
    protocol_id: str
    origin_endpoint_kind: EndpointKind
    setup_payload: bytes

    def __post_init__(self) -> None:
        if not self.generation_id or len(self.setup_payload) > MAX_SETUP_BYTES:
            raise ValueError("invalid generation offer")
        object.__setattr__(self, "protocol_id", validate_protocol_id(self.protocol_id))


@dataclass(frozen=True)
class LinkPacket:
    generation_id: str
    protocol_id: str
    payload: bytes
    flags: int = 0

    def __post_init__(self) -> None:
        if not self.generation_id or not 0 <= self.flags <= 0xFFFF or len(self.payload) > MAX_PACKET_BYTES:
            raise ValueError("invalid link packet")
        object.__setattr__(self, "protocol_id", validate_protocol_id(self.protocol_id))


@dataclass(frozen=True)
class CleanupReport:
    endpoint_stopped: bool
    local_resources_released: bool
    transport_drained: bool
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


Cancellation = asyncio.Event


class LocalGeneration(Protocol):
    offer: GenerationOffer

    async def receive(self) -> LinkPacket: ...
    async def send(self, packet: LinkPacket) -> None: ...
    async def close(self, outcome: str) -> CleanupReport: ...


class EndpointDriver(Protocol):
    capabilities: EndpointCapabilities

    async def prepare(self) -> None: ...
    async def discover(self, cancel: Cancellation) -> LocalGeneration: ...
    async def accept(self, offer: GenerationOffer, cancel: Cancellation) -> LocalGeneration: ...
    async def close(self) -> CleanupReport: ...
