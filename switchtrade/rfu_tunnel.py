"""Feature-neutral, versioned RFU tunnel envelope and endpoint ordering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import queue
import struct
import time


MAGIC = b"MWRF"
VERSION = 1
MAX_SESSION_BYTES = 64
HEADER = struct.Struct("!4sBBBBIIQBBHI")
# Pia Reliable stores its eight-byte header plus AppData in one uint16-sized
# message. Keep the opaque tunnel inside that actual downstream wire bound.
MAX_PAYLOAD_BYTES = 0xFFFF - 8
MAX_ENVELOPE_BYTES = HEADER.size + MAX_SESSION_BYTES + MAX_PAYLOAD_BYTES
BROADCAST_PLAYER = 0xFF


class Kind(IntEnum):
    RFU = 1
    HEARTBEAT = 2
    PEER_READY = 3
    PEER_CLOSE = 4
    ADVERTISEMENT = 5


class Direction(IntEnum):
    HOST_TO_GUEST = 1
    GUEST_TO_HOST = 2


@dataclass(frozen=True)
class Envelope:
    session_id: str
    direction: Direction
    epoch: int
    sequence: int
    source_player: int
    target_player: int
    payload: bytes
    kind: Kind = Kind.RFU
    timestamp_ns: int = 0
    flags: int = 0

    def encode(self) -> bytes:
        session = self.session_id.encode("utf-8")
        payload = bytes(self.payload)
        if not 1 <= len(session) <= MAX_SESSION_BYTES:
            raise ValueError("session_id must encode to 1..64 bytes")
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValueError("RFU payload exceeds 1 MiB")
        for name, value in (("source_player", self.source_player), ("target_player", self.target_player)):
            if not 0 <= value <= 0xFF:
                raise ValueError(f"{name} is outside uint8")
        timestamp = self.timestamp_ns or time.monotonic_ns()
        return HEADER.pack(
            MAGIC, VERSION, int(self.kind), int(self.direction), self.flags & 0xFF,
            self.epoch, self.sequence, timestamp, self.source_player, self.target_player,
            len(session), len(payload),
        ) + session + payload

    @classmethod
    def decode(cls, data: bytes) -> "Envelope":
        if len(data) < HEADER.size:
            raise ValueError("truncated RFU envelope header")
        (magic, version, kind, direction, flags, epoch, sequence, timestamp, source, target,
         session_len, payload_len) = HEADER.unpack_from(data)
        if magic != MAGIC or version != VERSION:
            raise ValueError("unsupported RFU envelope")
        if not 1 <= session_len <= MAX_SESSION_BYTES or payload_len > MAX_PAYLOAD_BYTES:
            raise ValueError("invalid RFU envelope lengths")
        expected = HEADER.size + session_len + payload_len
        if len(data) != expected:
            raise ValueError("RFU envelope length mismatch")
        session_start = HEADER.size
        payload_start = session_start + session_len
        try:
            session = data[session_start:payload_start].decode("utf-8")
            parsed_kind = Kind(kind)
            parsed_direction = Direction(direction)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("invalid RFU envelope field") from error
        return cls(
            session_id=session,
            direction=parsed_direction,
            epoch=epoch,
            sequence=sequence,
            source_player=source,
            target_player=target,
            payload=data[payload_start:],
            kind=parsed_kind,
            timestamp_ns=timestamp,
            flags=flags,
        )


class SequenceGate:
    """Reject duplicate/out-of-order frames and already-retired epochs."""

    def __init__(self):
        self.epoch: int | None = None
        self.sequence = -1
        self.gaps = 0
        self._retired_epochs: set[int] = set()

    def accept(self, envelope: Envelope) -> bool:
        if self.epoch is None:
            self.epoch = envelope.epoch
            self.sequence = -1
        elif envelope.epoch != self.epoch:
            if envelope.epoch in self._retired_epochs:
                return False
            self._retired_epochs.add(self.epoch)
            self.epoch = envelope.epoch
            self.sequence = -1
        if envelope.sequence <= self.sequence:
            return False
        if self.sequence >= 0 and envelope.sequence != self.sequence + 1:
            self.gaps += envelope.sequence - self.sequence - 1
        self.sequence = envelope.sequence
        return True


def direction_for_role(role: str) -> Direction:
    """Return the only wire direction a group role may transmit."""
    try:
        return {
            "host": Direction.HOST_TO_GUEST,
            "guest": Direction.GUEST_TO_HOST,
        }[role]
    except KeyError as error:
        raise ValueError("role must be host or guest") from error


class BoundedOutbox:
    """A bounded queue that applies producer backpressure instead of dropping RFU state."""

    def __init__(self, capacity: int = 256):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._queue = queue.Queue(maxsize=capacity)

    def put(self, envelope: Envelope, timeout: float = 1.0) -> None:
        self._queue.put(envelope, timeout=timeout)

    def get(self, timeout: float = 1.0) -> Envelope:
        return self._queue.get(timeout=timeout)

    def __len__(self) -> int:
        return self._queue.qsize()


@dataclass(frozen=True)
class PlayerMap:
    """Map each endpoint's local player-zero view to stable host/guest wire IDs."""

    role: str

    def __post_init__(self):
        if self.role not in {"host", "guest"}:
            raise ValueError("role must be host or guest")

    def local_to_wire(self, player: int) -> int:
        if player not in {0, 1}:
            raise ValueError("two-player beta accepts only player 0 or 1")
        return player if self.role == "host" else 1 - player

    def wire_to_local(self, player: int) -> int:
        return self.local_to_wire(player)
