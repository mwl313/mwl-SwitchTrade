"""Attempt-scoped C0/C1 control envelope for the ABC+D relay path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib
import hmac
import secrets
import struct

from switchtrade.rfu_tunnel import MAX_PAYLOAD_BYTES as MAX_RFU_PAYLOAD_BYTES


MAGIC = b"STR2"
VERSION = 2
MAX_ATTEMPT_BYTES = 128
MAX_PAYLOAD_BYTES = 64 * 1024
HEADER = struct.Struct("!4sBBBBQQHI")
MAX_ENVELOPE_BYTES = HEADER.size + MAX_ATTEMPT_BYTES + MAX_PAYLOAD_BYTES
PROBE_BYTES = 32


class TunnelV2Error(ValueError):
    """One factual rfu-tunnel.v2 contract or ordering failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SourceSeat(IntEnum):
    MEMBER_A = 1
    MEMBER_B = 2

    @classmethod
    def parse(cls, value: "SourceSeat | str") -> "SourceSeat":
        if isinstance(value, cls):
            return value
        try:
            return {"member_a": cls.MEMBER_A, "member_b": cls.MEMBER_B}[value]
        except (KeyError, TypeError) as error:
            raise TunnelV2Error("C_SOURCE_SEAT_INVALID", "source seat is invalid") from error

    @property
    def label(self) -> str:
        return "member_a" if self is self.MEMBER_A else "member_b"

    @property
    def peer(self) -> "SourceSeat":
        return self.MEMBER_B if self is self.MEMBER_A else self.MEMBER_A


class Kind(IntEnum):
    PEER_READY = 1
    PROBE_CHALLENGE = 2
    PROBE_RESPONSE = 3
    ADVERTISEMENT = 4
    SIDE_READY = 5
    PEER_CLOSE = 6
    RFU = 7


def _attempt_bytes(attempt_id: str) -> bytes:
    if not isinstance(attempt_id, str):
        raise TunnelV2Error("C_ATTEMPT_INVALID", "attempt ID must be text")
    try:
        encoded = attempt_id.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TunnelV2Error("C_ATTEMPT_INVALID", "attempt ID is not valid UTF-8") from error
    if not 1 <= len(encoded) <= MAX_ATTEMPT_BYTES:
        raise TunnelV2Error("C_ATTEMPT_INVALID", "attempt ID length is invalid")
    return encoded


def _validate_payload(kind: Kind, payload: bytes, flags: int = 0) -> None:
    if not 0 <= flags <= 0xFF:
        raise TunnelV2Error("C_FLAGS_INVALID", "Reliable flags are outside uint8")
    if kind is not Kind.RFU and flags:
        raise TunnelV2Error("C_FLAGS_INVALID", "control frames cannot carry Reliable flags")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise TunnelV2Error("C_PAYLOAD_TOO_LARGE", "payload exceeds the v2 bound")
    if kind is Kind.PEER_READY and payload:
        raise TunnelV2Error("C_PAYLOAD_INVALID", "PEER_READY payload must be empty")
    if kind in {Kind.PROBE_CHALLENGE, Kind.PROBE_RESPONSE} and len(payload) != PROBE_BYTES:
        raise TunnelV2Error("C_PAYLOAD_INVALID", "probe payload must be 32 bytes")
    if kind in {Kind.ADVERTISEMENT, Kind.SIDE_READY} and not payload:
        raise TunnelV2Error("C_PAYLOAD_INVALID", f"{kind.name} payload must not be empty")
    if kind is Kind.RFU and (not payload or len(payload) > MAX_RFU_PAYLOAD_BYTES):
        raise TunnelV2Error(
            "C_RFU_PAYLOAD_INVALID", "RFU payload is outside the Pia Reliable wire bound"
        )


@dataclass(frozen=True)
class Envelope:
    attempt_id: str
    source_seat: SourceSeat
    source_epoch: int
    sequence: int
    kind: Kind
    payload: bytes = b""
    flags: int = 0

    def encode(self) -> bytes:
        attempt = _attempt_bytes(self.attempt_id)
        try:
            seat = SourceSeat(self.source_seat)
            kind = Kind(self.kind)
        except ValueError as error:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope enum is invalid") from error
        if not 0 <= self.source_epoch <= 0xFFFFFFFFFFFFFFFF:
            raise TunnelV2Error("C_EPOCH_INVALID", "source epoch is outside uint64")
        if not 0 <= self.sequence <= 0xFFFFFFFFFFFFFFFF:
            raise TunnelV2Error("C_SEQUENCE_INVALID", "sequence is outside uint64")
        payload = bytes(self.payload)
        _validate_payload(kind, payload, self.flags)
        return HEADER.pack(
            MAGIC, VERSION, int(kind), int(seat), self.flags,
            self.source_epoch, self.sequence, len(attempt), len(payload),
        ) + attempt + payload

    @classmethod
    def decode(cls, raw: bytes) -> "Envelope":
        if not isinstance(raw, bytes) or len(raw) < HEADER.size:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope header is truncated")
        magic, version, kind, seat, flags, epoch, sequence, attempt_len, payload_len = (
            HEADER.unpack_from(raw)
        )
        if magic != MAGIC or version != VERSION:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope header is unsupported")
        if not 1 <= attempt_len <= MAX_ATTEMPT_BYTES or payload_len > MAX_PAYLOAD_BYTES:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope lengths are invalid")
        if len(raw) != HEADER.size + attempt_len + payload_len:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope length does not match header")
        boundary = HEADER.size + attempt_len
        try:
            attempt_id = raw[HEADER.size:boundary].decode("utf-8")
            source_seat = SourceSeat(seat)
            parsed_kind = Kind(kind)
        except (UnicodeDecodeError, ValueError) as error:
            raise TunnelV2Error("C_ENVELOPE_INVALID", "envelope field is invalid") from error
        envelope = cls(
            attempt_id, source_seat, epoch, sequence, parsed_kind, raw[boundary:], flags
        )
        _attempt_bytes(envelope.attempt_id)
        _validate_payload(envelope.kind, envelope.payload, envelope.flags)
        return envelope


class SequenceGate:
    """Accept exactly one contiguous stream from the bound peer and attempt."""

    def __init__(self, attempt_id: str, source_seat: SourceSeat | str):
        _attempt_bytes(attempt_id)
        self.attempt_id = attempt_id
        self.source_seat = SourceSeat.parse(source_seat)
        self.epoch: int | None = None
        self.next_sequence = 0
        self._retired_epochs: set[int] = set()

    def accept(self, envelope: Envelope) -> None:
        if envelope.attempt_id != self.attempt_id:
            raise TunnelV2Error("C_ATTEMPT_MISMATCH", "frame belongs to another attempt")
        if envelope.source_seat is not self.source_seat:
            raise TunnelV2Error("C_SOURCE_SEAT_MISMATCH", "frame came from the wrong seat")
        if envelope.source_epoch in self._retired_epochs:
            raise TunnelV2Error("C_EPOCH_STALE", "source epoch is retired")
        if envelope.source_epoch != self.epoch:
            if envelope.sequence != 0 or envelope.kind is not Kind.PEER_READY:
                raise TunnelV2Error(
                    "C_EPOCH_START_INVALID", "a source epoch must begin with PEER_READY sequence 0"
                )
            if self.epoch is not None:
                self._retired_epochs.add(self.epoch)
            self.epoch = envelope.source_epoch
            self.next_sequence = 0
        if envelope.sequence < self.next_sequence:
            raise TunnelV2Error("C_SEQUENCE_DUPLICATE", "frame sequence is duplicate or stale")
        if envelope.sequence > self.next_sequence:
            raise TunnelV2Error("C_SEQUENCE_GAP", "frame sequence is not contiguous")
        if envelope.kind is Kind.PEER_READY and envelope.sequence != 0:
            raise TunnelV2Error("C_PEER_READY_DUPLICATE", "PEER_READY may appear only at sequence 0")
        self.next_sequence += 1


def new_probe() -> bytes:
    return secrets.token_bytes(PROBE_BYTES)


def verify_probe(challenge: bytes, response: bytes) -> bool:
    return len(challenge) == PROBE_BYTES and hmac.compare_digest(challenge, response)


def advertisement_hash(payload: bytes) -> str:
    return hashlib.sha256(bytes(payload)).hexdigest()


def verify_advertisement(payload: bytes, expected_hash: str) -> bool:
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        return False
    return hmac.compare_digest(advertisement_hash(payload), expected_hash.lower())
