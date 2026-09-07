"""Generation-scoped RFU1 conversion, selectively ported from fbd2776.

No frontend lifecycle, Room authority, or Core orchestration belongs here.
RFU1 is a gpSP format, not a universal emulator protocol.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import struct
from typing import Final


RFU1_MAGIC: Final = 0x52465531
RFU1_BROADCAST: Final = 0x00
RFU1_CONNECT_REQ: Final = 0x01
RFU1_CONNECT_ACK: Final = 0x02
RFU1_CONNECT_NACK: Final = 0x03
RFU1_DISCONNECT: Final = 0x04
RFU1_HOST_SEND: Final = 0x05
RFU1_CLIENT_SEND: Final = 0x06
RFU1_CLIENT_ACK: Final = 0x07
RFU1_SIZES: Final = {
    RFU1_BROADCAST: 36,
    RFU1_CONNECT_REQ: 16,
    RFU1_CONNECT_ACK: 16,
    RFU1_CONNECT_NACK: 16,
    RFU1_DISCONNECT: 16,
    RFU1_HOST_SEND: 104,
    RFU1_CLIENT_SEND: 104,
    RFU1_CLIENT_ACK: 16,
}

GBA_MARKER: Final = 0x57
GBA_ACCEPT: Final = 0x41
GBA_CONNECT: Final = 0x43
GBA_DISCONNECT: Final = 0x44
GBA_GROUP: Final = 0x47
GBA_ACK: Final = 0x4B
GBA_TRANSFER: Final = 0x54
FLAGS_GBA: Final = 0x07
FLAGS_METADATA: Final = 0x0F
METADATA_FRAME: Final = bytes.fromhex(
    "4a002a005801004c656166477265656e5f65" + "00" * 28)
MAX_PENDING: Final = 256
CHILD_TIMESTAMP_SEED: Final = 0x0000362E


class TranslatorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = "E4_TRANSLATOR"
        self.message = message


@dataclass(frozen=True)
class TranslatorAction:
    destination: str
    payload: bytes
    classification: str
    flags: int = 0
    peer_id: int | None = None


def _gba(frame_type: int, body: bytes) -> bytes:
    return bytes((GBA_MARKER, frame_type)) + len(body).to_bytes(2, "little") + body


def _rfu1(packet_type: int, header: int, payload: bytes = b"") -> bytes:
    size = RFU1_SIZES.get(packet_type)
    if size is None:
        raise ValueError("unknown RFU1 packet type")
    value = struct.pack("!III", RFU1_MAGIC, packet_type, header) + bytes(payload)
    if len(value) > size:
        raise ValueError("RFU1 packet overflow")
    return value + b"\0" * (size - len(value))


def _parse_rfu1(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 12:
        raise TranslatorError("TRANSLATOR_RFU1_LENGTH", "RFU1 packet length is invalid")
    magic, packet_type, header = struct.unpack("!III", payload[:12])
    if magic != RFU1_MAGIC or packet_type not in RFU1_SIZES:
        raise TranslatorError("TRANSLATOR_RFU1_TYPE", "RFU1 packet type is invalid")
    if len(payload) != RFU1_SIZES[packet_type]:
        raise TranslatorError("TRANSLATOR_RFU1_LENGTH", "RFU1 packet length is invalid")
    body = payload[12:]
    if packet_type not in (RFU1_BROADCAST, RFU1_HOST_SEND, RFU1_CLIENT_SEND) and any(body):
        raise TranslatorError("TRANSLATOR_RFU1_PADDING", "RFU1 command padding is invalid")
    return packet_type, header, body


def _parse_gba(payload: bytes) -> tuple[int, bytes]:
    if len(payload) < 4 or payload[0] != GBA_MARKER:
        raise TranslatorError("TRANSLATOR_FRAME_PREFIX", "Switch application frame is invalid")
    size = int.from_bytes(payload[2:4], "little")
    if size != len(payload) - 4:
        raise TranslatorError("TRANSLATOR_FRAME_LENGTH", "Switch application frame length is invalid")
    return payload[1], payload[4:]


def _decode_base85(value: bytes) -> bytes:
    if len(value) % 5:
        raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
    output = bytearray()
    for offset in range(0, len(value), 5):
        number = 0
        for character in reversed(value[offset:offset + 5]):
            if not 0x23 <= character <= 0x78 or character == 0x5C:
                raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
            number = number * 85 + (
                character - 0x23 if character < 0x5C else character - 0x24)
        if number > 0xFFFFFFFF:
            raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
        output.extend(number.to_bytes(4, "little"))
    return bytes(output)


def _advertisement_record(application_data: bytes) -> bytes:
    value = bytes(application_data)
    if len(value) != 122 or value[:5] != bytes.fromhex("005c160058"):
        raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
    name_length = int.from_bytes(value[0x17:0x1B], "big")
    if name_length > 64 or 0x1C + name_length > 0x5C:
        raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
    record = _decode_base85(value[0x5C:])
    if len(record) != 24:
        raise TranslatorError("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
    return record


def _metadata_valid(payload: bytes) -> bool:
    if len(payload) != len(METADATA_FRAME) or payload[:7] != bytes.fromhex("4a002a00580100"):
        return False
    title = payload[7:18].rstrip(b"\0")
    return title in (b"LeafGreen_e", b"FireRed_e") and not any(payload[18:])


class RfuTranslator:
    """One attempt-bound Nintendo Switch Creator to stock gpSP Finder translator."""

    def __init__(self, *, attempt_id: str, tunnel_epoch: int,
                 child_connection_id: bytes, gpsp_device_id: int, gpsp_slot: int = 0):
        if not attempt_id or not 0 < tunnel_epoch <= 0x7FFFFFFF:
            raise ValueError("attempt and tunnel epoch are required")
        if len(child_connection_id) != 2 or child_connection_id == b"\0\0":
            raise ValueError("child connection ID must be two non-zero bytes")
        if not 0 < gpsp_device_id <= 0xFFFF or not 0 <= gpsp_slot <= 3:
            raise ValueError("gpSP device mapping is invalid")
        self.attempt_id = attempt_id
        self.tunnel_epoch = tunnel_epoch
        self.child_connection_id = bytes(child_connection_id)
        self.gpsp_device_id = gpsp_device_id
        self.gpsp_slot = gpsp_slot
        self.state = "waiting_advertisement"
        self._failure: TranslatorError | None = None
        self._started = False
        self._advertisement_hash: bytes | None = None
        self._advertisement_generation: int | None = None
        self._host_session_id: int | None = None
        self._remote_metadata: bytes | None = None
        self._group_state: int | None = None
        self._child_timestamp = CHILD_TIMESTAMP_SEED
        self._k_sequence = 0
        self._pending_parent_timestamps: deque[int] = deque()
        self._parent_timestamps: OrderedDict[int, bytes] = OrderedDict()
        self._sequence_last = {"core": 0, "remote": 0}
        self._sequence_cache: dict[str, OrderedDict[int, tuple[bytes, tuple[TranslatorAction, ...]]]] = {
            "core": OrderedDict(), "remote": OrderedDict(),
        }

    @property
    def assignment(self) -> int:
        return self.gpsp_device_id | (self.gpsp_slot << 16)

    def snapshot(self) -> dict:
        return {
            "contract_version": "endpoint-rfu.v1",
            "profile": "frlg-wireless-adapter.v1",
            "role_capabilities": ["finder"],
            "state": self.state,
            "tunnel_epoch": self.tunnel_epoch,
            "group_state": self._group_state,
            "pending_core_acks": len(self._pending_parent_timestamps),
        }

    def _fail(self, code: str, message: str):
        self.state = "failed"
        if self._failure is None:
            self._failure = TranslatorError(code, message)
        raise self._failure

    def _active(self) -> None:
        if self.state in ("failed", "closed"):
            self._fail("TRANSLATOR_NOT_ACTIVE", "Translator attempt is not active")

    def _sequence(self, channel: str, sequence: int, signature: bytes,
                  build) -> tuple[TranslatorAction, ...]:
        self._active()
        if not 0 < sequence <= 0x7FFFFFFFFFFFFFFF:
            self._fail("TRANSLATOR_SEQUENCE_INVALID", "Translator sequence is invalid")
        cache = self._sequence_cache[channel]
        cached = cache.get(sequence)
        if cached is not None:
            if cached[0] != signature:
                self._fail("TRANSLATOR_DUPLICATE_CHANGED", "Duplicate translator input changed")
            return cached[1]
        expected = self._sequence_last[channel] + 1
        if sequence != expected:
            self._fail(
                "TRANSLATOR_SEQUENCE_GAP" if sequence > expected else "TRANSLATOR_SEQUENCE_REORDERED",
                "Translator input sequence is not contiguous")
        try:
            actions = tuple(build())
        except TranslatorError as error:
            self._fail(error.code, error.message)
        self._sequence_last[channel] = sequence
        cache[sequence] = (signature, actions)
        while len(cache) > MAX_PENDING:
            cache.popitem(last=False)
        return actions

    def start(self) -> tuple[TranslatorAction, ...]:
        self._active()
        if self._started:
            return ()
        self._started = True
        return (TranslatorAction(
            "tunnel", METADATA_FRAME, "metadata", flags=FLAGS_METADATA),)

    def accept_advertisement(self, application_data: bytes, *, generation: int) -> tuple[TranslatorAction, ...]:
        self._active()
        if generation != self.tunnel_epoch:
            self._fail("TRANSLATOR_GENERATION_STALE", "Advertisement generation is stale")
        record = _advertisement_record(application_data)
        digest = hashlib.sha256(application_data).digest()
        if self._advertisement_hash is not None and digest != self._advertisement_hash:
            self._fail("TRANSLATOR_ADVERTISEMENT_CHANGED", "Switch advertisement changed")
        host_session_id = int.from_bytes(record[10:12], "little")
        if host_session_id == 0:
            self._fail("TRANSLATOR_ADVERTISEMENT", "Switch advertisement is invalid")
        self._advertisement_hash = digest
        self._advertisement_generation = generation
        self._host_session_id = host_session_id
        if self.state == "waiting_advertisement":
            self.state = "searching"
        network_words = b"".join(
            struct.pack("!I", int.from_bytes(record[offset:offset + 4], "little"))
            for offset in range(0, 24, 4))
        return (TranslatorAction(
            "core", _rfu1(RFU1_BROADCAST, host_session_id, network_words),
            "broadcast", peer_id=0),)

    def from_core(self, payload: bytes, *, peer_id: int, sequence: int) -> tuple[TranslatorAction, ...]:
        if type(peer_id) is not int or peer_id != 1:
            self._fail("TRANSLATOR_CORE_PEER", "gpSP peer identity is invalid")
        signature = struct.pack("!I", peer_id) + bytes(payload)
        return self._sequence(
            "core", sequence, signature,
            lambda: self._from_core(bytes(payload), peer_id))

    def _from_core(self, payload: bytes, peer_id: int) -> tuple[TranslatorAction, ...]:
        if peer_id != 1:
            self._fail("TRANSLATOR_CORE_PEER", "gpSP peer identity is invalid")
        packet_type, header, body = _parse_rfu1(payload)
        if packet_type == RFU1_CONNECT_REQ:
            if self.state not in ("searching", "connecting") or header != self._host_session_id:
                self._fail("TRANSLATOR_CONNECT_STATE", "gpSP connect request is invalid")
            self.state = "connecting"
            return (TranslatorAction(
                "tunnel", _gba(GBA_CONNECT, self.child_connection_id),
                "connect_request", flags=FLAGS_GBA),)
        if packet_type == RFU1_CLIENT_SEND:
            if self.state != "connected":
                self._fail("TRANSLATOR_DATA_STATE", "gpSP data arrived outside a connection")
            size = header >> 24
            if (not 1 <= size <= 16 or (header & 0xFFFF) != self.gpsp_device_id
                    or ((header >> 16) & 3) != self.gpsp_slot
                    or header & 0x00FC0000 or any(body[size:])):
                self._fail("TRANSLATOR_CLIENT_DATA", "gpSP child data is invalid")
            slot = body[:size]
            timestamp = self._child_timestamp
            self._child_timestamp = (timestamp + 1) & 0xFFFFFFFF
            if self._child_timestamp == 0:
                self._child_timestamp = 1
            padded = slot + b"\0" * ((-len(slot)) & 3)
            frame_body = timestamp.to_bytes(4, "little") + bytes((0, len(slot), 0, 0)) + padded
            return (TranslatorAction(
                "tunnel", _gba(GBA_TRANSFER, frame_body),
                "child_transfer", flags=FLAGS_GBA),)
        if packet_type == RFU1_CLIENT_ACK:
            if self.state != "connected" or header != self.assignment:
                self._fail("TRANSLATOR_CLIENT_ACK", "gpSP acknowledgement is invalid")
            if not self._pending_parent_timestamps:
                self._fail("TRANSLATOR_ACK_UNCORRELATED", "gpSP acknowledgement is uncorrelated")
            timestamp = self._pending_parent_timestamps.popleft()
            return (self._switch_ack(timestamp),)
        if packet_type == RFU1_DISCONNECT:
            if self.state not in ("connecting", "connected") or header not in (
                    self.assignment, self.gpsp_device_id):
                self._fail("TRANSLATOR_DISCONNECT", "gpSP disconnect is invalid")
            self.state = "closed"
            return (TranslatorAction(
                "tunnel", _gba(GBA_DISCONNECT, self.child_connection_id),
                "disconnect", flags=FLAGS_GBA),)
        self._fail("TRANSLATOR_CORE_DIRECTION", "gpSP emitted a Finder-incompatible RFU1 packet")

    def from_switch(self, payload: bytes, *, flags: int, generation: int,
                    sequence: int) -> tuple[TranslatorAction, ...]:
        if generation != self.tunnel_epoch:
            self._fail("TRANSLATOR_GENERATION_STALE", "Switch frame generation is stale")
        # Validate before duplicate lookup: 0x0107 must not alias cached 0x0007.
        if type(flags) is not int or flags not in (FLAGS_GBA, FLAGS_METADATA):
            self._fail("TRANSLATOR_RELIABLE_FLAGS", "Switch Reliable flags are invalid")
        signature = struct.pack("!H", flags) + bytes(payload)
        return self._sequence(
            "remote", sequence, signature,
            lambda: self._from_switch(bytes(payload), flags))

    def _from_switch(self, payload: bytes, flags: int) -> tuple[TranslatorAction, ...]:
        if flags == FLAGS_METADATA:
            if not _metadata_valid(payload):
                self._fail("TRANSLATOR_METADATA", "Switch metadata is invalid")
            if self._remote_metadata is not None and payload != self._remote_metadata:
                self._fail("TRANSLATOR_METADATA_CHANGED", "Switch metadata changed")
            self._remote_metadata = payload
            return ()
        if flags != FLAGS_GBA:
            self._fail("TRANSLATOR_RELIABLE_FLAGS", "Switch Reliable flags are invalid")
        frame_type, body = _parse_gba(payload)
        if frame_type == GBA_ACCEPT:
            if len(body) != 6 or self._host_session_id is None:
                self._fail("TRANSLATOR_ACCEPT", "Switch accept is invalid")
            if (int.from_bytes(body[:2], "little") != self._host_session_id
                    or body[2:4] != self.child_connection_id or body[4:] != b"\0\0"):
                self._fail("TRANSLATOR_ACCEPT", "Switch accept identity is invalid")
            if self.state == "connected":
                return ()
            if self.state != "connecting":
                self._fail("TRANSLATOR_ACCEPT_STATE", "Switch accept arrived out of order")
            self.state = "connected"
            return (TranslatorAction(
                "core", _rfu1(RFU1_CONNECT_ACK, self.assignment),
                "connect_accept", peer_id=0),)
        if frame_type == GBA_GROUP:
            if self.state != "connected" or len(body) != 4:
                self._fail("TRANSLATOR_GROUP_STATE", "Switch group state is invalid")
            group_state = int.from_bytes(body, "little")
            if group_state not in (0, 1) or (
                    self._group_state is not None and group_state < self._group_state):
                self._fail("TRANSLATOR_GROUP_STATE", "Switch group state is invalid")
            self._group_state = group_state
            return ()
        if frame_type == GBA_TRANSFER:
            if self.state != "connected":
                self._fail("TRANSLATOR_DATA_STATE", "Switch data arrived outside a connection")
            return self._parent_transfer(payload, body)
        if frame_type == GBA_DISCONNECT:
            if self.state not in ("connecting", "connected") or body != self.child_connection_id:
                self._fail("TRANSLATOR_DISCONNECT", "Switch disconnect is invalid")
            self.state = "closed"
            return (TranslatorAction(
                "core", _rfu1(RFU1_DISCONNECT, self.assignment),
                "disconnect", peer_id=0),)
        self._fail("TRANSLATOR_SWITCH_DIRECTION", "Switch emitted a Finder-incompatible frame")

    def _parent_transfer(self, raw: bytes, body: bytes) -> tuple[TranslatorAction, ...]:
        if len(body) < 8 or body[5:8] != b"\0\0\0":
            self._fail("TRANSLATOR_PARENT_DATA", "Switch parent transfer is invalid")
        timestamp = int.from_bytes(body[:4], "little")
        slot_length = body[4]
        expected = 8 if slot_length <= 1 else 8 + ((slot_length + 3) & ~3)
        if timestamp == 0 or len(body) != expected or slot_length > 92:
            self._fail("TRANSLATOR_PARENT_DATA", "Switch parent transfer is invalid")
        previous = self._parent_timestamps.get(timestamp)
        if previous is not None:
            if previous != raw:
                self._fail("TRANSLATOR_TIMESTAMP_CHANGED", "Switch timestamp payload changed")
            return ()
        if self._parent_timestamps:
            last = next(reversed(self._parent_timestamps))
            delta = (timestamp - last) & 0xFFFFFFFF
            if delta == 0 or delta >= 0x80000000:
                self._fail("TRANSLATOR_TIMESTAMP_REORDERED", "Switch timestamp is not monotonic")
        self._parent_timestamps[timestamp] = raw
        while len(self._parent_timestamps) > MAX_PENDING:
            self._parent_timestamps.popitem(last=False)
        if slot_length <= 1:
            return (self._switch_ack(timestamp),)
        if len(self._pending_parent_timestamps) >= MAX_PENDING:
            self._fail("TRANSLATOR_QUEUE_FULL", "Translator acknowledgement queue is saturated")
        slot = body[8:8 + slot_length]
        if any(body[8 + slot_length:]):
            self._fail("TRANSLATOR_PARENT_PADDING", "Switch parent transfer padding is invalid")
        self._pending_parent_timestamps.append(timestamp)
        return (TranslatorAction(
            "core", _rfu1(RFU1_HOST_SEND, slot_length, slot),
            "parent_transfer", peer_id=0),)

    def _switch_ack(self, timestamp: int) -> TranslatorAction:
        self._k_sequence = (self._k_sequence + 1) & 0xFFFFFFFF
        if self._k_sequence == 0:
            self._k_sequence = 1
        body = (self._k_sequence.to_bytes(4, "little") + (1).to_bytes(4, "little")
                + timestamp.to_bytes(4, "little"))
        return TranslatorAction(
            "tunnel", _gba(GBA_ACK, body), "parent_ack", flags=FLAGS_GBA)
