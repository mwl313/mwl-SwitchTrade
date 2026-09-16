"""Bounded, read-only LLSF diagnostics at the gpSP conversion boundary.

Observations retain only numeric header/command metadata, never game contents
or success claims. uni_slot also identifies the qualified pacing boundary.
RFU1 CLIENT_ACK can precede gpSP receive-buffer admission. Native
NI ACK (inside an LLSF) and RFU1 CLIENT_ACK must therefore stay distinct.
Layout: pinned pret/pokefirered librfu_rfu.c llsf_struct / constructLLSF.
"""
from collections import Counter, deque
from copy import deepcopy
import time


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


def uni_command_metadata(slot: bytes, *, parent: bool):
    """Public command headers only; never include command arguments/game data."""
    if not uni_slot(slot, parent=parent):
        return None
    start = 3 if parent else 2
    words = [int.from_bytes(slot[i:i + 2], "little") for i in range(start, len(slot), 14)]
    result = {"commands": [word & 0xFF00 for word in words],
              "fragments": [word & 31 for word in words]}
    if not parent:
        result["tag"] = words[0] >> 5 & 7
    return result


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
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._sides = {side: {"slots": 0, "unknown_slots": 0, "idle_slots": 0,
            "repeated_slots": 0, "kinds": Counter(), "first_changes": [], "last": None}
            for side in ("child", "parent")}
        self._previous = {"child": None, "parent": None}
        self._uni = {side: {"count": 0, "first": [], "last": None} for side in self._sides}
        self._recent = {side: deque(maxlen=24) for side in self._sides}
        self._commands = {side: Counter() for side in self._sides}
        self._last_uni_at = {side: None for side in self._sides}
        self._max_gap_ms = {side: 0 for side in self._sides}
        self._child_tag = None
        self._tag_checks = self._tag_gaps = self._tag_coverage_breaks = 0
        self._first_tag_gap = None

    @property
    def milestone(self):
        # Finite kinds/opcodes plus the first tag discontinuity force a log;
        # repeated commands/retries cannot create per-VBlank log events.
        return (sum(len(side["kinds"]) for side in self._sides.values())
                + sum(len(commands) for commands in self._commands.values())
                + int(self._first_tag_gap is not None))

    def observe(self, slot: bytes, *, parent: bool, timestamp=None):
        side = "parent" if parent else "child"
        record = self._sides[side]
        record["slots"] += 1
        metadata = uni_command_metadata(slot, parent=parent)
        if not parent and metadata is None and self._child_tag is not None:
            # An unrecognized/mixed or non-UNI interval is a coverage break,
            # not evidence of a missing game command across that interval.
            self._child_tag = None
            self._tag_coverage_breaks += 1
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
        if metadata is not None:
            record_uni = self._uni[side]
            record_uni["count"] += 1
            if len(record_uni["first"]) < _TRACE_LIMIT:
                record_uni["first"].append(metadata)
            record_uni["last"] = metadata
            now = self._clock()
            previous = self._last_uni_at[side]
            if previous is not None:
                self._max_gap_ms[side] = max(self._max_gap_ms[side], round((now - previous) * 1000))
            self._last_uni_at[side] = now
            entry = {"ordinal": record_uni["count"], "timestamp": timestamp,
                     "elapsed_ms": round((now - self._started) * 1000), **metadata}
            self._recent[side].append(entry)
            self._commands[side].update(metadata["commands"])
            # Pinned FRLG ChildBuildSendCmd: only non-idle commands advance
            # the three-bit tag. This observes gpSP OUTPUT, not Switch receipt
            # or its error state. Eight missing commands can alias the tag.
            if not parent and metadata["commands"][0]:
                tag = metadata["tag"]
                if self._child_tag is not None:
                    self._tag_checks += 1
                    expected = (self._child_tag + 1) & 7
                    if tag != expected:
                        self._tag_gaps += 1
                        if self._first_tag_gap is None:
                            self._first_tag_gap = {**entry, "expected_tag": expected}
                self._child_tag = tag
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
        now = self._clock()
        result = deepcopy(self._uni)
        for side, record in result.items():
            previous = self._last_uni_at[side]
            record.update(recent=deepcopy(list(self._recent[side])),
                          command_counts=dict(self._commands[side]),
                          last_age_ms=None if previous is None else round((now - previous) * 1000),
                          max_gap_ms=self._max_gap_ms[side])
        result["child"].update(tag_checks=self._tag_checks, tag_discontinuities=self._tag_gaps,
                               tag_coverage_breaks=self._tag_coverage_breaks,
                               first_tag_discontinuity=deepcopy(self._first_tag_gap))
        return result
