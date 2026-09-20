"""Bounded diagnostic metadata, not packet capture or protocol control.

Each instance has one owner (endpoint loop or simulation thread). Flushes carry
contiguous observation ordinals and sticky loss counts. A missing final flush
or missing batch is incomplete evidence, never an implicit successful run.
"""
from collections import deque
from copy import deepcopy
import hashlib
from pathlib import Path
import platform
import time
from uuid import uuid4

from switchtrade.rfu_progress import uni_command_metadata


def source_identity():
    # Same normalized source hashes on native Windows and the WSL overlay.
    # This is disk-source identity, not a claim about ROM or game execution.
    root = Path(__file__).resolve().parents[1]
    paths = ("switchtrade/rfu_trace.py", "switchtrade/rfu_progress.py",
             "switchtrade/endpoints/retroarch_gpsp/driver.py",
             "switchtrade/endpoints/retroarch_gpsp/rfu.py",
             "switchtrade/endpoints/retroarch_gpsp/cadence.py",
             "switchtrade/endpoints/switch_ldn/generation.py",
             "switchtrade/endpoints/switch_ldn/tunnel_adapter.py",
             "bridge/frlgsim/tunnel.py", "bridge/frlgsim/tunnel_progress.py",
             "bridge/frlgsim/sim.py", "bridge/frlgsim/reliable.py")
    hashes = {}
    for name in paths:
        try:
            hashes[name] = hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            hashes[name] = None  # Unavailable is not a matching/verified source.
    return {"python": platform.python_version(), "platform": platform.system(), "files": hashes}


def native_metadata(payload, *, parent):
    """Whitelist public WT/WK/WG fields; never serialize unknown bytes/IDs."""
    result = {"kind": "other", "bytes": len(payload)}
    if (len(payload) < 4 or payload[0] != 0x57
            or int.from_bytes(payload[2:4], "little") != len(payload) - 4):
        return result
    if payload[1] == 0x54 and len(payload) >= 12:
        size = payload[8 if parent else 9]
        slot = payload[12:12 + size]
        if len(slot) == size or (parent and size == 1 and len(payload) == 12):
            result.update(kind="WT", timestamp=int.from_bytes(payload[4:8], "little"), slot_len=size)
            metadata = uni_command_metadata(slot, parent=parent)
            if metadata is not None:
                result.update(metadata)
    elif payload[1] == 0x4B and len(payload) == 16:
        result.update(kind="WK", receipt_seq=int.from_bytes(payload[4:8], "little"),
                      message_index=int.from_bytes(payload[8:12], "little"),
                      timestamp=int.from_bytes(payload[12:16], "little"))
    elif payload[1] == 0x47 and len(payload) == 8:
        result.update(kind="WG", state=int.from_bytes(payload[4:8], "little"))
    return result


class MetadataTrace:
    """Only callers' explicitly sanitized metadata may be passed to record()."""
    def __init__(self, *, capacity=4096, clock=time.monotonic):
        if capacity < 1:
            raise ValueError("trace capacity must be positive")
        self._clock = clock
        self._started = clock()
        self._entries = deque(maxlen=capacity)
        self._stream = uuid4().hex
        self._observed = self._dropped = self._batch = 0
        self._first_dropped = None
        self._source = source_identity()

    def record(self, event, **metadata):
        self._observed += 1
        if len(self._entries) == self._entries.maxlen:
            self._dropped += 1
            if self._first_dropped is None:
                self._first_dropped = self._entries[0]["seq"]
        self._entries.append({**deepcopy(metadata), "event": event,
                              "seq": self._observed,
                              "elapsed_ms": round((self._clock() - self._started) * 1000, 3)})

    def drain(self, *, final=False):
        self._batch += 1
        result = {"schema": 1, "stream": self._stream, "batch": self._batch,
                  "observed": self._observed, "dropped": self._dropped,
                  "first_dropped": self._first_dropped, "final": final,
                  "elapsed_ms": round((self._clock() - self._started) * 1000, 3),
                  "entries": list(self._entries)}
        self._entries.clear()
        if self._batch == 1:
            result["source"] = self._source
        return result
