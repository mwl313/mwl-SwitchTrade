"""Generation-bound, endpoint-neutral pair transport."""

from switchtrade.transport.client import WireClient
from switchtrade.transport.wire import Envelope, FrameKind, TransportError, WireState

__all__ = ("Envelope", "FrameKind", "TransportError", "WireClient", "WireState")
