"""Concrete Switch LDN endpoint boundary; Direct A/B integration follows in C2/C3."""

from __future__ import annotations

from switchtrade.core.contracts import (
    Cancellation,
    CleanupReport,
    EndpointCapabilities,
    EndpointKind,
    GenerationOffer,
    GenerationRole,
    LocalGeneration,
    RuntimeKind,
)


SWITCH_LDN_PROTOCOL = "switchtrade.gba-frame.v1"


class SwitchLdnEndpointDriver:
    """Phase-B-compatible boundary for the managed-WSL Switch LDN endpoint."""

    capabilities = EndpointCapabilities(
        EndpointKind.SWITCH_LDN,
        RuntimeKind.MANAGED_WSL,
        (SWITCH_LDN_PROTOCOL,),
        (GenerationRole.ORIGIN, GenerationRole.MIRROR),
    )

    async def prepare(self) -> None:
        """C2 adds leader-side policy and runtime validation."""

    async def discover(self, cancel: Cancellation) -> LocalGeneration:
        del cancel
        raise NotImplementedError("Switch LDN discovery is implemented in C2")

    async def accept(
        self, offer: GenerationOffer, cancel: Cancellation
    ) -> LocalGeneration:
        del offer, cancel
        raise NotImplementedError("Switch LDN acceptance is implemented in C3")

    async def close(self) -> CleanupReport:
        return CleanupReport(True, True, True, {"endpoint_kind": EndpointKind.SWITCH_LDN})
