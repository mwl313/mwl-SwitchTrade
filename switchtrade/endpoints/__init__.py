"""Endpoint implementations for the endpoint-neutral core."""

from .fake import FakeEndpointDriver, FakeEndpointHub

__all__ = ("FakeEndpointDriver", "FakeEndpointHub")
