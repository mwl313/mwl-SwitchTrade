"""Hardware-independent pairing and generation contracts."""

from .contracts import (
    CleanupReport, EndpointCapabilities, EndpointDriver, EndpointKind, GenerationOffer,
    GenerationRole, LinkPacket, LocalGeneration, PairCredentials, PairSeat, RuntimeKind,
)

__all__ = (
    "CleanupReport", "EndpointCapabilities", "EndpointDriver", "EndpointKind", "GenerationOffer",
    "GenerationRole", "LinkPacket", "LocalGeneration", "PairCredentials", "PairSeat", "RuntimeKind",
)
