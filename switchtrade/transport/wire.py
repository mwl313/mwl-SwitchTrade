"""Bounded pair-wire envelope and generation ordering state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import secrets
import struct

from switchtrade.core.contracts import MAX_PACKET_BYTES, PairSeat


MAGIC = b"STPW"
VERSION = 1
MAX_GENERATION_ID_BYTES = 128
PROBE_BYTES = 32
MAX_RETIRED_EPOCHS = 64
HEADER = struct.Struct("!4sBBBHQQHI")


class TransportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FrameKind(IntEnum):
    PEER_READY = 1
    PROBE_CHALLENGE = 2
    PROBE_RESPONSE = 3
    CAPABILITIES = 4
    GENERATION_OFFER = 5
    GENERATION_ACCEPT = 6
    GENERATION_CLOSE = 7
    DATA = 8
    HEARTBEAT = 9
    PEER_CLOSE = 10


_SEATS = {PairSeat.HOST: 1, PairSeat.GUEST: 2}
_SEATS_REVERSE = {value: key for key, value in _SEATS.items()}
_GENERATION_KINDS = {FrameKind.GENERATION_OFFER, FrameKind.GENERATION_ACCEPT, FrameKind.GENERATION_CLOSE, FrameKind.DATA}


def _peer(seat: PairSeat) -> PairSeat:
    return PairSeat.GUEST if seat is PairSeat.HOST else PairSeat.HOST


@dataclass(frozen=True)
class Envelope:
    kind: FrameKind
    source_seat: PairSeat
    source_epoch: int
    sequence: int
    generation_id: str = ""
    payload: bytes = b""
    flags: int = 0

    def encode(self) -> bytes:
        try:
            generation = self.generation_id.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TransportError("T_GENERATION_INVALID") from exc
        payload = bytes(self.payload)
        self._validate(generation, payload)
        return HEADER.pack(MAGIC, VERSION, int(self.kind), _SEATS[self.source_seat], self.flags, self.source_epoch, self.sequence, len(generation), len(payload)) + generation + payload

    @classmethod
    def decode(cls, raw: bytes) -> "Envelope":
        if not isinstance(raw, bytes) or len(raw) < HEADER.size:
            raise TransportError("T_ENVELOPE_INVALID")
        magic, version, kind, seat, flags, epoch, sequence, generation_length, payload_length = HEADER.unpack_from(raw)
        if magic != MAGIC:
            raise TransportError("T_MAGIC_INVALID")
        if version != VERSION:
            raise TransportError("T_VERSION_INVALID")
        if generation_length > MAX_GENERATION_ID_BYTES or payload_length > MAX_PACKET_BYTES or len(raw) != HEADER.size + generation_length + payload_length:
            raise TransportError("T_ENVELOPE_INVALID")
        boundary = HEADER.size + generation_length
        try:
            envelope = cls(FrameKind(kind), _SEATS_REVERSE[seat], epoch, sequence, raw[HEADER.size:boundary].decode("utf-8"), raw[boundary:], flags)
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise TransportError("T_ENVELOPE_INVALID") from exc
        envelope._validate(envelope.generation_id.encode("utf-8"), envelope.payload)
        return envelope

    def _validate(self, generation: bytes, payload: bytes) -> None:
        if not 0 <= self.flags <= 0xFFFF or not 0 <= self.source_epoch <= 0xFFFFFFFFFFFFFFFF or not 0 <= self.sequence <= 0xFFFFFFFFFFFFFFFF:
            raise TransportError("T_ENVELOPE_INVALID")
        if len(generation) > MAX_GENERATION_ID_BYTES or len(payload) > MAX_PACKET_BYTES:
            raise TransportError("T_FRAME_TOO_LARGE")
        if self.kind in _GENERATION_KINDS and not generation:
            raise TransportError("T_GENERATION_INVALID")
        if self.kind not in _GENERATION_KINDS and generation:
            raise TransportError("T_GENERATION_INVALID")
        if self.kind in {FrameKind.PEER_READY, FrameKind.HEARTBEAT} and payload:
            raise TransportError("T_PAYLOAD_INVALID")
        if self.kind in {FrameKind.PROBE_CHALLENGE, FrameKind.PROBE_RESPONSE} and len(payload) != PROBE_BYTES:
            raise TransportError("T_PROBE_INVALID")


class WireState:
    """Tracks one local epoch and the peer's contiguous epoch stream."""

    def __init__(self, seat: PairSeat) -> None:
        self.seat, self.peer_seat = PairSeat(seat), _peer(PairSeat(seat))
        self._epoch: int | None = None
        self._next_sequence = 0
        self._peer_epoch: int | None = None
        self._peer_next_sequence = 0
        self._retired_epochs: set[int] = set()
        self._expect_peer_resync = False
        self._challenge = b""
        self._challenge_confirmed = False
        self._responded_to_peer = False
        self._inbound_offer: str | None = None
        self._outbound_offer: str | None = None
        self.active_generation: str | None = None

    @property
    def ready(self) -> bool:
        return self._challenge_confirmed and self._responded_to_peer

    def start(self, epoch: int | None = None, *, expect_peer_resync: bool | None = None) -> tuple[Envelope, Envelope]:
        candidate = secrets.randbits(64) if epoch is None else epoch
        if not 1 <= candidate <= 0xFFFFFFFFFFFFFFFF:
            raise TransportError("T_EPOCH_INVALID")
        self._epoch, self._next_sequence = candidate, 0
        self._expect_peer_resync = self._peer_epoch is not None if expect_peer_resync is None else expect_peer_resync
        self._reset_generation_and_probe()
        ready = self.emit(FrameKind.PEER_READY)
        return ready, self._new_probe()

    def emit(self, kind: FrameKind, generation_id: str = "", payload: bytes = b"", flags: int = 0) -> Envelope:
        if self._epoch is None:
            raise TransportError("T_NOT_CONNECTED")
        kind = FrameKind(kind)
        envelope = Envelope(kind, self.seat, self._epoch, self._next_sequence, generation_id, payload, flags)
        envelope.encode()
        self._outbound_transition(kind, generation_id)
        self._next_sequence += 1
        return envelope

    def accept(self, envelope: Envelope) -> tuple[Envelope, ...] | None:
        if envelope.source_seat is not self.peer_seat:
            raise TransportError("T_SOURCE_SEAT_MISMATCH")
        if self._expect_peer_resync and envelope.source_epoch == self._peer_epoch:
            return None
        is_new_epoch = envelope.source_epoch != self._peer_epoch
        if envelope.source_epoch in self._retired_epochs:
            raise TransportError("T_EPOCH_STALE")
        if is_new_epoch:
            if envelope.kind is not FrameKind.PEER_READY or envelope.sequence != 0:
                raise TransportError("T_EPOCH_START_INVALID")
            previous = self._peer_epoch
            peer_reconnected = previous is not None
            peer_resync_expected = self._expect_peer_resync
            if peer_reconnected:
                if len(self._retired_epochs) >= MAX_RETIRED_EPOCHS:
                    raise TransportError("T_EPOCH_EXHAUSTED")
                self._retired_epochs.add(previous)
                self._reset_generation_and_probe(preserve_local_challenge=peer_resync_expected)
                self._expect_peer_resync = False
            self._peer_epoch, self._peer_next_sequence = envelope.source_epoch, 0
        if envelope.sequence < self._peer_next_sequence:
            raise TransportError("T_SEQUENCE_DUPLICATE")
        if envelope.sequence > self._peer_next_sequence:
            raise TransportError("T_SEQUENCE_GAP")
        if envelope.kind is FrameKind.PEER_READY and envelope.sequence != 0:
            raise TransportError("T_PEER_READY_INVALID")
        self._peer_next_sequence += 1
        replies: list[Envelope] = []
        if is_new_epoch and peer_reconnected and not peer_resync_expected:
            replies.extend(self.start(expect_peer_resync=False))
        if envelope.kind is FrameKind.PROBE_CHALLENGE:
            self._responded_to_peer = True
            replies.append(self.emit(FrameKind.PROBE_RESPONSE, payload=envelope.payload))
        elif envelope.kind is FrameKind.PROBE_RESPONSE:
            if envelope.payload != self._challenge:
                raise TransportError("T_PROBE_INVALID")
            self._challenge_confirmed = True
        else:
            self._inbound_transition(envelope)
        return tuple(replies)

    def _outbound_transition(self, kind: FrameKind, generation_id: str) -> None:
        if kind is FrameKind.GENERATION_OFFER:
            self._require_ready()
            if self.active_generation or self._outbound_offer or self._inbound_offer:
                raise TransportError("T_GENERATION_ACTIVE")
            self._outbound_offer = generation_id
        elif kind is FrameKind.GENERATION_ACCEPT:
            self._require_ready()
            if generation_id != self._inbound_offer:
                raise TransportError("T_GENERATION_STALE")
            self.active_generation, self._inbound_offer = generation_id, None
        elif kind is FrameKind.GENERATION_CLOSE:
            if generation_id != self.active_generation:
                raise TransportError("T_GENERATION_STALE")
            self.active_generation = None
        elif kind is FrameKind.DATA:
            if generation_id != self.active_generation:
                raise TransportError("T_GENERATION_INACTIVE")

    def _inbound_transition(self, envelope: Envelope) -> None:
        if envelope.kind is FrameKind.GENERATION_OFFER:
            self._require_ready()
            if self.active_generation or self._outbound_offer or self._inbound_offer:
                raise TransportError("T_GENERATION_ACTIVE")
            self._inbound_offer = envelope.generation_id
        elif envelope.kind is FrameKind.GENERATION_ACCEPT:
            if envelope.generation_id != self._outbound_offer:
                raise TransportError("T_GENERATION_STALE")
            self.active_generation, self._outbound_offer = envelope.generation_id, None
        elif envelope.kind is FrameKind.GENERATION_CLOSE:
            if envelope.generation_id != self.active_generation:
                raise TransportError("T_GENERATION_STALE")
            self.active_generation = None
        elif envelope.kind is FrameKind.DATA and envelope.generation_id != self.active_generation:
            raise TransportError("T_GENERATION_INACTIVE")

    def _require_ready(self) -> None:
        if not self.ready:
            raise TransportError("T_PROBE_REQUIRED")

    def _reset_generation_and_probe(self, *, preserve_local_challenge: bool = False) -> None:
        if not preserve_local_challenge:
            self._challenge = b""
            self._challenge_confirmed = False
        self._responded_to_peer = False
        self._inbound_offer = self._outbound_offer = self.active_generation = None

    def _new_probe(self) -> Envelope:
        self._challenge = secrets.token_bytes(PROBE_BYTES)
        return self.emit(FrameKind.PROBE_CHALLENGE, payload=self._challenge)
