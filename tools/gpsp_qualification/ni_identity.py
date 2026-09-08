"""Offline native NI identity evidence; NOT a Switch advertisement converter.

Callers must select ONE child source and ONE RFU connection before passing
decoded slots. Do not compare the child's identity with its parent's advert.
Completeness here proves captured bytes, not peer acceptance or game success.
"""
from collections.abc import Iterable

from tools.payload_decoder import RfuSlot


def reassemble_child_game_ni(slots: Iterable[RfuSlot]) -> bytes:
    """Recover the observed 26-byte/12-byte-window initial NI transfer.

    Reject missing, conflicting, oversized or differently shaped evidence.
    Byte-identical retransmissions and receive-side ACKs are not new data.
    Other NI sizes/window schemes require separate analysis, not a guess.
    """
    started = ended = False
    fragments: dict[int, bytes] = {}
    for slot in slots:
        if slot.role != "child":
            raise ValueError("NI_SOURCE_ROLE")
        if slot.size > len(slot.payload):
            raise ValueError("NI_TRUNCATED")
        if slot.ack or slot.state not in (1, 2, 3):
            continue
        payload = slot.payload[:slot.size]
        if slot.state == 1:
            if (slot.n, slot.phase, payload) != (1, 0, b"\x01\x0c\x00\x1a\x00\x00\x00"):
                raise ValueError("NI_UNSUPPORTED_HEADER")
            if ended:
                raise ValueError("NI_MULTIPLE_TRANSFERS")
            started = True
        elif slot.state == 2:
            if not started or ended:
                raise ValueError("NI_TRANSFER_ORDER")
            if slot.n != 1 or slot.phase not in (0, 1, 2):
                raise ValueError("NI_UNSUPPORTED_WINDOW")
            if slot.size != (2 if slot.phase == 2 else 12):
                raise ValueError("NI_FRAGMENT_SIZE")
            if slot.phase in fragments and fragments[slot.phase] != payload:
                raise ValueError("NI_CONFLICTING_RETRANSMISSION")
            fragments[slot.phase] = payload
        else:
            if not started or set(fragments) != {0, 1, 2}:
                raise ValueError("NI_INCOMPLETE")
            if (slot.n, slot.phase, slot.size) != (0, 0, 0):
                raise ValueError("NI_INVALID_END")
            ended = True
    if not ended:
        raise ValueError("NI_INCOMPLETE")
    return b"".join(fragments[phase] for phase in range(3))


def inspect_native_game_ni(data: bytes) -> dict:
    """Non-identifying game fields from serial2 + gname15 + uname9.

    Never emit trainer ID/name, source addresses or raw payloads. The layout
    is native RfuGameData (pret/pokefirered include/link_rfu.h), not Sloop's
    opaque 24-byte advertisement layout. Do not infer one from the other.
    """
    if len(data) != 26 or data[:2] != b"\x02\x00":
        raise ValueError("NI_GAME_RECORD")
    gname = data[2:15]
    compatibility = int.from_bytes(gname[:2], "little")
    trade = int.from_bytes(gname[8:10], "little")
    return {
        "serial": 2,
        "language": compatibility & 15,
        "version": (compatibility >> 10) & 15,
        "has_news": bool(compatibility & 0x10),
        "has_card": bool(compatibility & 0x20),
        "compatibility_unknown": bool(compatibility & 0x40),
        "can_link_nationally": bool(compatibility & 0x80),
        "has_national_dex": bool(compatibility & 0x100),
        "game_clear": bool(compatibility & 0x200),
        "compatibility_reserved": compatibility >> 14,
        "activity": gname[10] & 127,
        "started_activity": bool(gname[10] & 128),
        "gender": gname[11] & 1,
        "trade_level": gname[11] >> 1,
        "trade_species": trade & 1023,
        "trade_type": trade >> 10,
    }
