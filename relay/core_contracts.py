"""HTTP models for the isolated Phase B Core relay."""

from __future__ import annotations

from pydantic import BaseModel, Field

from switchtrade.core.contracts import EndpointCapabilities, EndpointKind, GenerationRole, RuntimeKind


class CapabilitiesModel(BaseModel):
    endpoint_kind: EndpointKind
    runtime_kind: RuntimeKind
    protocols: list[str] = Field(min_length=1)
    generation_roles: list[GenerationRole] = Field(min_length=1)

    def as_domain(self) -> EndpointCapabilities:
        return EndpointCapabilities(self.endpoint_kind, self.runtime_kind, tuple(self.protocols), tuple(self.generation_roles))


class CreatePairRequest(BaseModel):
    capabilities: CapabilitiesModel


class JoinPairRequest(BaseModel):
    code: str
    capabilities: CapabilitiesModel
