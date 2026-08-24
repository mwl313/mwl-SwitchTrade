#!/usr/bin/env python3
"""Payload-side helpers for MWL-SwitchTrade.

This module intentionally starts *after* LDN/Pia decryption.  It provides the
stable hand-off schema, GBA/RFU carrier parsing, block reassembly, and Gen-III
Pokémon candidate validation.  It does not attempt to decrypt 802.11 or guess
Pia fields from ciphertext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")
_DIRECTIONS = {"host_to_peer", "peer_to_host"}


class PayloadSchemaError(ValueError):
    """Raised when a protocol-agent payload-stream record is malformed."""


@dataclass(frozen=True)
class PayloadRecord:
    """One decrypted/reassembled datagram from the protocol-agent hand-off."""

    capture_id: str
    room_id: str
    timestamp_ns: int
    direction: str
    payload: bytes
    source_frames: tuple[int, ...]
    complete: bool
    src_mac: str | None = None
    dst_mac: str | None = None
    src_ip: str | None = None
    dst_ip: str | None = None
    pia_packet_id: int | None = None
    reliable_seq: int | None = None
    flags: int = 0
    retransmit: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "PayloadRecord":
        if not isinstance(obj, dict):
            raise PayloadSchemaError("record must be a JSON object")

        def required_text(name: str) -> str:
            value = obj.get(name)
            if not isinstance(value, str) or not value:
                raise PayloadSchemaError(f"{name} must be a non-empty string")
            return value

        capture_id = required_text("capture_id")
        room_id = required_text("room_id")
        direction = required_text("direction")
        if direction not in _DIRECTIONS:
            raise PayloadSchemaError(f"direction must be one of {_DIRECTIONS}")

        timestamp_ns = obj.get("timestamp_ns")
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int):
            raise PayloadSchemaError("timestamp_ns must be an integer")

        payload_hex = obj.get("payload_hex")
        if not isinstance(payload_hex, str) or len(payload_hex) % 2:
            raise PayloadSchemaError("payload_hex must be an even-length string")
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise PayloadSchemaError("payload_hex is not hexadecimal") from exc

        source_frames = obj.get("source_frames")
        if not isinstance(source_frames, list) or any(
            isinstance(x, bool) or not isinstance(x, int) for x in source_frames
        ):
            raise PayloadSchemaError("source_frames must be a list of integers")

        complete = obj.get("complete")
        if not isinstance(complete, bool):
            raise PayloadSchemaError("complete must be boolean")

        def optional_mac(name: str) -> str | None:
            value = obj.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not _MAC_RE.fullmatch(value):
                raise PayloadSchemaError(f"{name} must be a MAC address")
            return value.lower()

        def optional_int(name: str) -> int | None:
            value = obj.get(name)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int):
                raise PayloadSchemaError(f"{name} must be an integer")
            return value

        flags = obj.get("flags", 0)
        if isinstance(flags, bool) or not isinstance(flags, int):
            raise PayloadSchemaError("flags must be an integer")
        retransmit = obj.get("retransmit", False)
        if not isinstance(retransmit, bool):
            raise PayloadSchemaError("retransmit must be boolean")

        known = {
            "capture_id", "room_id", "timestamp_ns", "direction", "payload_hex",
            "source_frames", "complete", "src_mac", "dst_mac", "src_ip", "dst_ip",
            "pia_packet_id", "reliable_seq", "flags", "retransmit",
        }
        return cls(
            capture_id=capture_id,
            room_id=room_id,
            timestamp_ns=timestamp_ns,
            direction=direction,
            payload=payload,
            source_frames=tuple(source_frames),
            complete=complete,
            src_mac=optional_mac("src_mac"),
            dst_mac=optional_mac("dst_mac"),
            src_ip=obj.get("src_ip"),
            dst_ip=obj.get("dst_ip"),
            pia_packet_id=optional_int("pia_packet_id"),
            reliable_seq=optional_int("reliable_seq"),
            flags=flags,
            retransmit=retransmit,
            extra={k: v for k, v in obj.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "capture_id": self.capture_id,
            "room_id": self.room_id,
            "timestamp_ns": self.timestamp_ns,
            "direction": self.direction,
            "payload_hex": self.payload.hex(),
            "source_frames": list(self.source_frames),
            "complete": self.complete,
            "flags": self.flags,
            "retransmit": self.retransmit,
        }
        for name in ("src_mac", "dst_mac", "src_ip", "dst_ip", "pia_packet_id", "reliable_seq"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        result.update(self.extra)
        return result


def load_payload_stream(path: str | Path) -> list[PayloadRecord]:
    """Load and validate a JSONL payload-stream.v1 file."""

    records: list[PayloadRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                records.append(PayloadRecord.from_dict(obj))
            except (json.JSONDecodeError, PayloadSchemaError) as exc:
                raise PayloadSchemaError(f"{path}:{line_no}: {exc}") from exc
    return records


@dataclass(frozen=True)
class ParseIssue:
    offset: int
    code: str
    detail: str


@dataclass(frozen=True)
class GbaFrame:
    offset: int
    frame_type: int
    body: bytes
    raw: bytes

    @property
    def type_name(self) -> str:
        return {
            0x41: "A",  # accept
            0x43: "C",  # connect
            0x4B: "K",  # acknowledgement
            0x54: "T",  # RFU command-slot carrier
        }.get(self.frame_type, f"0x{self.frame_type:02x}")


@dataclass(frozen=True)
class GbaParseResult:
    frames: tuple[GbaFrame, ...]
    issues: tuple[ParseIssue, ...]


def parse_gba_frames(data: bytes, *, strict: bool = False) -> GbaParseResult:
    """Parse concatenated ``0x57 type length:u16-le body`` carriers.

    Unexpected bytes are reported and skipped in tolerant mode.  No bytes are
    silently treated as a valid carrier, which is important when a capture has
    a missing fragment or contains the separate Reliable initialization record.
    """

    frames: list[GbaFrame] = []
    issues: list[ParseIssue] = []
    offset = 0
    while offset < len(data):
        if data[offset] != 0x57:
            issue = ParseIssue(offset, "unexpected_prefix", f"0x{data[offset]:02x}")
            if strict:
                raise ValueError(issue)
            issues.append(issue)
            next_marker = data.find(b"\x57", offset + 1)
            if next_marker < 0:
                break
            offset = next_marker
            continue
        if len(data) - offset < 4:
            issue = ParseIssue(offset, "truncated_header", "fewer than 4 bytes")
            if strict:
                raise ValueError(issue)
            issues.append(issue)
            break
        frame_type = data[offset + 1]
        body_len = int.from_bytes(data[offset + 2:offset + 4], "little")
        end = offset + 4 + body_len
        if end > len(data):
            issue = ParseIssue(
                offset, "truncated_body", f"need {body_len} bytes, have {len(data) - offset - 4}"
            )
            if strict:
                raise ValueError(issue)
            issues.append(issue)
            break
        frames.append(GbaFrame(offset, frame_type, data[offset + 4:end], data[offset:end]))
        offset = end
    return GbaParseResult(tuple(frames), tuple(issues))


RFU_UNI = 4
RFU_COMMANDS = {
    0x0000: "IDLE",
    0x2F00: "SEND_PACKET",
    0x5F00: "READY_CLOSE_LINK",
    0x6600: "READY_EXIT_STANDBY",
    0x7700: "SEND_PLAYER_IDS",
    0x7800: "SEND_PLAYER_IDS_NEW",
    0x8800: "SEND_BLOCK_INIT",
    0x8900: "SEND_BLOCK",
    0xA100: "SEND_BLOCK_REQ",
    0xBE00: "SEND_HELD_KEYS",
    0xED00: "DISCONNECT",
    0xEE00: "DISCONNECT_PARENT",
}


@dataclass(frozen=True)
class RfuCommand:
    raw: bytes
    word0: int
    opcode: int
    name: str
    words: tuple[int, ...]
    multiplayer_id: int | None = None
    block_index: int | None = None
    block_count: int | None = None
    block_owner: int | None = None
    fragment: bytes | None = None
    request_type: int | None = None


@dataclass(frozen=True)
class RfuSlot:
    role: str
    raw: bytes
    state: int
    ack: int
    n: int
    phase: int
    size: int
    payload: bytes
    commands: tuple[RfuCommand, ...]
    idle: bool = False


@dataclass(frozen=True)
class RfuCarrier:
    frame: GbaFrame
    role: str
    timestamp_ns: int | None
    slot_length: int
    slot: RfuSlot | None
    issues: tuple[ParseIssue, ...] = ()


def _parse_command(raw: bytes, multiplayer_id: int | None = None) -> RfuCommand:
    padded = raw[:14].ljust(14, b"\x00")
    words = tuple(int.from_bytes(padded[i:i + 2], "little") for i in range(0, 14, 2))
    word0 = words[0]
    opcode = word0 & 0xFF00
    kwargs: dict[str, Any] = {"multiplayer_id": multiplayer_id}
    if opcode == 0x8800:
        kwargs["block_count"] = words[1]
        kwargs["block_owner"] = padded[4] & 0x7F
    elif opcode == 0x8900:
        kwargs["block_index"] = word0 & 0x1F
        kwargs["fragment"] = padded[2:14]
    elif opcode == 0xA100:
        kwargs["request_type"] = words[1]
    return RfuCommand(
        raw=padded,
        word0=word0,
        opcode=opcode,
        name=RFU_COMMANDS.get(opcode, f"0x{opcode:04x}"),
        words=words,
        **kwargs,
    )


def _parse_llsf(slot: bytes, role: str) -> tuple[int, int, int, int, int, bytes]:
    if role == "parent":
        if len(slot) < 3:
            raise ValueError("parent LLSF header requires 3 bytes")
        word = int.from_bytes(slot[:3], "little")
        return (
            (word >> 14) & 0xF, (word >> 13) & 1, (word >> 11) & 0x3,
            (word >> 9) & 0x3, word & 0x7F, slot[3:],
        )
    if role == "child":
        if len(slot) < 2:
            raise ValueError("child LLSF header requires 2 bytes")
        word = int.from_bytes(slot[:2], "little")
        return (
            (word >> 10) & 0xF, (word >> 9) & 1, (word >> 7) & 0x3,
            (word >> 5) & 0x3, word & 0x1F, slot[2:],
        )
    raise ValueError("role must be 'parent' or 'child'")


def parse_t_carrier(
    frame: GbaFrame,
    *,
    role: str,
    timestamp_ns: int | None = None,
) -> RfuCarrier:
    """Decode one GBA ``T`` carrier into LLSF and RFU commands."""

    issues: list[ParseIssue] = []
    if frame.frame_type != 0x54:
        return RfuCarrier(frame, role, timestamp_ns, 0, None, (
            ParseIssue(frame.offset, "not_t_carrier", frame.type_name),
        ))
    body = frame.body
    if len(body) < 8:
        return RfuCarrier(frame, role, timestamp_ns, 0, None, (
            ParseIssue(frame.offset, "truncated_t_body", str(len(body))),
        ))
    slot_length = body[4] if role == "parent" else body[5]
    if slot_length <= 1:
        slot = RfuSlot(role, b"", 0, 0, 0, 0, 0, b"", (), idle=True)
        return RfuCarrier(frame, role, timestamp_ns, slot_length, slot, ())
    if len(body) < 8 + slot_length:
        issues.append(ParseIssue(
            frame.offset, "truncated_t_slot", f"need {slot_length}, have {len(body) - 8}"
        ))
        slot_bytes = body[8:]
    else:
        slot_bytes = body[8:8 + slot_length]
    try:
        state, ack, n, phase, size, payload = _parse_llsf(slot_bytes, role)
    except ValueError as exc:
        issues.append(ParseIssue(frame.offset, "invalid_llsf", str(exc)))
        return RfuCarrier(frame, role, timestamp_ns, slot_length, None, tuple(issues))

    commands: list[RfuCommand] = []
    if state == RFU_UNI:
        if role == "parent":
            for mpid, start in enumerate(range(0, len(payload) - 13, 14)):
                commands.append(_parse_command(payload[start:start + 14], mpid))
        elif len(payload) >= 14:
            commands.append(_parse_command(payload[:14]))
    slot = RfuSlot(role, slot_bytes, state, ack, n, phase, size, payload, tuple(commands))
    return RfuCarrier(frame, role, timestamp_ns, slot_length, slot, tuple(issues))


@dataclass
class RfuBlock:
    direction: str
    ordinal: int
    expected_fragments: int
    owner: int | None
    multiplayer_id: int | None = None
    fragments: dict[int, bytes] = field(default_factory=dict)
    source_offsets: list[int] = field(default_factory=list)
    request_type: int | None = None
    complete: bool = False

    def add_fragment(self, index: int, fragment: bytes, source_offset: int | None = None) -> None:
        self.fragments.setdefault(index, bytes(fragment))
        if source_offset is not None:
            self.source_offsets.append(source_offset)
        self.complete = (
            self.expected_fragments > 0
            and all(i in self.fragments for i in range(self.expected_fragments))
        )

    @property
    def missing_indices(self) -> list[int]:
        return [i for i in range(self.expected_fragments) if i not in self.fragments]

    @property
    def payload(self) -> bytes | None:
        if not self.complete:
            return None
        return b"".join(self.fragments[i] for i in range(self.expected_fragments))

    @property
    def partial_payload(self) -> bytes:
        return b"".join(self.fragments[i] for i in sorted(self.fragments))


class RfuBlockAssembler:
    """Reassemble RFU SEND_BLOCK_INIT/SEND_BLOCK pairs per direction."""

    def __init__(self) -> None:
        self._active: dict[tuple[str, int | None], RfuBlock] = {}
        self._ordinals: dict[tuple[str, int | None], int] = {}
        self.completed: list[RfuBlock] = []
        self.issues: list[ParseIssue] = []

    def feed(
        self,
        command: RfuCommand,
        *,
        direction: str,
        source_offset: int | None = None,
    ) -> RfuBlock | None:
        stream = (direction, command.multiplayer_id)
        if command.opcode == 0x8800:
            active = self._active.get(stream)
            # RFU retransmits INIT until the peer arms its receive block.  A
            # same-size/same-owner INIT during an incomplete epoch is a
            # retransmission, not a new block; resetting here would discard
            # already received fragments and manufacture false gaps.
            if (
                active is not None
                and not active.complete
                and active.expected_fragments == (command.block_count or 0)
                and active.owner == command.block_owner
            ):
                if source_offset is not None:
                    active.source_offsets.append(source_offset)
                return active
            ordinal = self._ordinals.get(stream, 0)
            self._ordinals[stream] = ordinal + 1
            previous = active
            if previous is not None and not previous.complete:
                self.issues.append(ParseIssue(
                    source_offset or 0, "block_replaced_incomplete",
                    f"{direction} block {previous.ordinal} missing {previous.missing_indices}",
                ))
            block = RfuBlock(
                direction=direction,
                ordinal=ordinal,
                expected_fragments=command.block_count or 0,
                owner=command.block_owner,
                multiplayer_id=command.multiplayer_id,
            )
            if source_offset is not None:
                block.source_offsets.append(source_offset)
            self._active[stream] = block
            return block
        if command.opcode == 0x8900:
            block = self._active.get(stream)
            if block is None:
                self.issues.append(ParseIssue(
                    source_offset or 0, "fragment_without_init", direction,
                ))
                return None
            index = command.block_index
            if index is None or not 0 <= index < block.expected_fragments:
                self.issues.append(ParseIssue(
                    source_offset or 0, "invalid_fragment_index",
                    f"{direction}:{index} not in 0..{block.expected_fragments - 1}",
                ))
                return block
            block.add_fragment(command.block_index or 0, command.fragment or b"", source_offset)
            if block.complete and block not in self.completed:
                self.completed.append(block)
            return block
        if command.opcode == 0xA100:
            block = self._active.get(stream)
            if block is not None:
                block.request_type = command.request_type
            return block
        return None

    def finalize(self) -> None:
        for block in self._active.values():
            if block.complete or block in self.completed:
                continue
            self.issues.append(ParseIssue(
                block.source_offsets[-1] if block.source_offsets else 0,
                "incomplete_block",
                f"{block.direction}:{block.ordinal} missing {block.missing_indices}",
            ))


@dataclass(frozen=True)
class PokemonCandidate:
    source_id: str
    offset: int
    size: int
    raw: bytes
    canonical: bytes
    form: str
    decoded: dict[str, Any]
    complete: bool
    validation: dict[str, bool]

    @property
    def valid(self) -> bool:
        return self.complete and all(self.validation.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "offset": self.offset,
            "size": self.size,
            "raw_hex": self.raw.hex(),
            "canonical_hex": self.canonical.hex(),
            "form": self.form,
            "decoded": self.decoded,
            "complete": self.complete,
            "validation": self.validation,
            "valid": self.valid,
        }


_PK3_TOOL: Any | None = None


def _pk3_tool() -> Any:
    global _PK3_TOOL
    if _PK3_TOOL is not None:
        return _PK3_TOOL
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    path = tools_dir / "pk3-tool.py"
    spec = importlib.util.spec_from_file_location("_mwl_pk3_tool", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PK3_TOOL = module
    return module


def scan_pokemon_candidates(
    data: bytes,
    *,
    source_id: str = "",
    complete: bool = True,
    max_bytes: int = 1_048_576,
) -> list[PokemonCandidate]:
    """Find checksum-valid, species-plausible Gen-III records in a payload buffer.

    The scanner tries party records before box records at each offset so a
    100-byte party record is not reported twice as an 80-byte prefix.  It does
    not claim a candidate from a partial block as valid.
    """

    if len(data) > max_bytes:
        raise ValueError(
            f"candidate input is {len(data)} bytes; pass reassembled payload blocks, "
            f"not a raw capture (limit {max_bytes})"
        )

    pk3 = _pk3_tool()
    species = pk3.SPECIES
    # Header/name bytes are plaintext in both .pk3 and .ek3.  This cheap
    # filter avoids running the PID-dependent secure-region transform at every
    # byte of a megabyte-scale unrelated buffer (for example, a raw pcap).
    text_bytes = set(pk3._CHARS) | set(pk3.G3_JP)

    def header_plausible(raw: bytes) -> bool:
        if int.from_bytes(raw[28:30], "little") == 0:
            return False
        if raw[18] > 7:
            return False
        return all(byte in text_bytes for byte in raw[8:18] + raw[20:27])

    candidates: list[PokemonCandidate] = []
    seen: set[tuple[int, int, int, int]] = set()
    for offset in range(len(data)):
        for size in (100, 80):
            if offset + size > len(data):
                continue
            raw = bytes(data[offset:offset + size])
            if not header_plausible(raw):
                continue
            decoded = pk3.decode(raw)
            if not decoded or not decoded.get("checksum_ok"):
                continue
            species_id = int(decoded.get("species", 0))
            species_ok = species_id in species and species_id != 0
            if not species_ok:
                continue
            key = (offset, size, int(decoded.get("pid", 0)), int(decoded.get("stored", 0)))
            if key in seen:
                continue
            seen.add(key)
            canonical, form = pk3.canonical_view(raw)
            validation = {"checksum": True, "species_plausible": True}
            candidates.append(PokemonCandidate(
                source_id=source_id,
                offset=offset,
                size=size,
                raw=raw,
                canonical=bytes(canonical),
                form=form,
                decoded=decoded,
                complete=complete,
                validation=validation,
            ))
            break
    return candidates


def classify_command(command: RfuCommand) -> dict[str, Any]:
    """Return a stable, JSON-friendly event record for one RFU command."""

    result: dict[str, Any] = {
        "event": command.name.lower(),
        "opcode": f"0x{command.opcode:04x}",
        "word0": command.word0,
        "words": list(command.words),
    }
    if command.multiplayer_id is not None:
        result["multiplayer_id"] = command.multiplayer_id
    for name in ("block_index", "block_count", "block_owner", "request_type"):
        value = getattr(command, name)
        if value is not None:
            result[name] = value
    if command.fragment is not None:
        result["fragment_hex"] = command.fragment.hex()
    return result


__all__ = [
    "GbaFrame", "GbaParseResult", "ParseIssue", "PayloadRecord", "PayloadSchemaError",
    "PokemonCandidate", "RfuBlock", "RfuBlockAssembler", "RfuCarrier", "RfuCommand",
    "RfuSlot", "classify_command", "load_payload_stream", "parse_gba_frames",
    "parse_t_carrier", "scan_pokemon_candidates",
]
