"""Hardware-independent pairing and generation contracts."""

from .contracts import (
    CleanupReport, EndpointCapabilities, EndpointDriver, EndpointKind, GenerationOffer,
    GenerationRole, LinkPacket, LocalGeneration, PairCredentials, PairSeat, RuntimeKind,
)
from .supervisor import CoreSupervisor, SupervisorError, SupervisorState

__all__ = (
    "CleanupReport", "EndpointCapabilities", "EndpointDriver", "EndpointKind", "GenerationOffer",
    "GenerationRole", "LinkPacket", "LocalGeneration", "PairCredentials", "PairSeat", "RuntimeKind",
    "CoreSupervisor", "SupervisorError", "SupervisorState",
)
