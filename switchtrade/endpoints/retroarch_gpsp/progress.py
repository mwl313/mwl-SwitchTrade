"""Bounded, read-only LLSF diagnostics at the gpSP conversion boundary.

Observations retain only numeric header/command metadata, never game contents
or success claims. uni_slot also identifies the qualified pacing boundary.
RFU1 CLIENT_ACK can precede gpSP receive-buffer admission. Native
NI ACK (inside an LLSF) and RFU1 CLIENT_ACK must therefore stay distinct.
Layout: pinned pret/pokefirered librfu_rfu.c llsf_struct / constructLLSF.
"""
from collections import Counter
from copy import deepcopy


_STATES = ("null", "ni_start", "ni", "ni_end", "uni")
_TRACE_LIMIT = 12


def uni_slot(slot: bytes, *, parent: bool) -> bool:
    """The supported single FRLG UNI layout, not arbitrary RFU payloads."""
    size, width = (70, 3) if parent else (14, 2)
    if len(slot) != size + width:
        return False
    header = _headers(slot, parent=parent)
    return (header is not None and len(header) == 1 and header[0]["state"] == "uni"
            and not header[0]["ack"] and header[0]["size"] == size
            and header[0]["n"] == 0 and header[0]["phase"] == 0
            and (not parent or header[0]["slot_mask"] == 1))


def _headers(slot: bytes, *, parent: bool):
    """Recognize a complete LLSF sequence, or return unknown (never reject it)."""
    width, shift = (3, 14) if parent else (2, 10)
    result = []
    offset = 0
    while offset < len(slot):
        if not any(slot[offset:]):  # RFU word padding / idle, not NI completion.
            break
        if len(slot) - offset < width:
            return None
        word = int.from_bytes(slot[offset:offset + width], "little")
        state = (word >> shift) & 15
        size = word & (0x1FF if parent else 0x1F)
        if (state >= len(_STATES) or word >> (22 if parent else 14)
                or offset + width + size > len(slot)):
            return None
        header = {"state": _STATES[state], "ack": (word >> (shift - 1)) & 1,
                  "n": (word >> (shift - 3)) & 3,
                  "phase": (word >> (shift - 5)) & 3, "size": size}
        if parent:
            header["slot_mask"] = (word >> 18) & 15
        result.append(header)
        offset += width + size
    return result


class RfuProgress:
    def __init__(self):
        self._sides = {side: {"slots": 0, "unknown_slots": 0, "idle_slots": 0,
            "repeated_slots": 0, "kinds": Counter(), "first_changes": [], "last": None}
            for side in ("child", "parent")}
        self._previous = {"child": None, "parent": None}
        self._uni = {side: {"count": 0, "first": [], "last": None} for side in self._sides}

    @property
    def milestone(self):
        # At most ten kinds per direction. Only first-kind observations force
        # a log; per-VBlank retransmissions cannot create unbounded log events.
        return sum(len(side["kinds"]) for side in self._sides.values())

    def observe(self, slot: bytes, *, parent: bool):
        side = "parent" if parent else "child"
        record = self._sides[side]
        record["slots"] += 1
        headers = _headers(slot, parent=parent)
        if headers is None:
            record["unknown_slots"] += 1
            self._previous[side] = None
            return
        if not headers:
            record["idle_slots"] += 1
        if self._previous[side] == slot:
            record["repeated_slots"] += 1
        self._previous[side] = bytes(slot)  # Bounded to one RFU slot; never logged.
        if uni_slot(slot, parent=parent):
            start = 3 if parent else 2
            words = [int.from_bytes(slot[i:i + 2], "little") for i in range(start, len(slot), 14)]
            metadata = {"commands": [word & 0xFF00 for word in words],
                        "fragments": [word & 31 for word in words]}
            if not parent:
                metadata["tag"] = words[0] >> 5 & 7
            record_uni = self._uni[side]
            record_uni["count"] += 1
            if len(record_uni["first"]) < _TRACE_LIMIT:
                record_uni["first"].append(metadata)
            record_uni["last"] = metadata
        for header in headers:
            kind = header["state"] + ("_ack" if header["ack"] else "")
            record["kinds"][kind] += 1
            if header != record["last"] and len(record["first_changes"]) < _TRACE_LIMIT:
                record["first_changes"].append(header)
            record["last"] = header

    def snapshot(self):
        # Numeric protocol headers only: no slot bytes, trainer IDs, names,
        # status-byte guesses, game/save contents, or success verdicts.
        return deepcopy(self._sides)

    def uni_snapshot(self):
        return deepcopy(self._uni)
