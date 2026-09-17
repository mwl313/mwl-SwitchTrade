"""Metadata only at native Reliable admission/scheduling, never game receipt.

No raw packets, game arguments, connection IDs or payload fingerprints escape.
Unknown formats stay opaque; this observer cannot acknowledge or reject data.
"""
from collections import Counter, deque
from copy import deepcopy
import time

from switchtrade.rfu_progress import RfuProgress


class NativeRfuProgress:
    def __init__(self, *, parent, clock=time.monotonic):
        self.parent = parent
        self._clock = clock
        self._started = clock()
        self.progress = RfuProgress(clock)
        self._counts = Counter()
        self._kinds = {side: Counter() for side in ("rx_admitted", "tx_queued")}
        self._recent = {side: deque(maxlen=24) for side in self._kinds}
        self._first = {side: [] for side in self._kinds}
        self._receipt_attempts = 0
        self._receipt_first = []
        self._receipt_recent = deque(maxlen=24)

    def observe(self, payload, seq, flags, *, received):
        side = "rx_admitted" if received else "tx_queued"
        parent = not self.parent if received else self.parent
        self._counts[side] += 1
        entry = {"ordinal": self._counts[side], "reliable_seq": seq,
                 "flags": flags, "bytes": len(payload), "kind": "other",
                 "elapsed_ms": round((self._clock() - self._started) * 1000)}
        # Recognize only a complete single native wrapper. Malformed/unknown
        # payloads remain forwarded by TunnelSim without exposing their bytes.
        if (len(payload) >= 4 and payload[0] == 0x57
                and int.from_bytes(payload[2:4], "little") == len(payload) - 4):
            if payload[1] == 0x54 and len(payload) >= 12:
                timestamp = int.from_bytes(payload[4:8], "little")
                size = payload[8 if parent else 9]
                slot = payload[12:12 + size]
                # Native parent idle encodes size=1 without any slot bytes.
                if len(slot) == size or (parent and size == 1 and len(payload) == 12):
                    entry.update(kind="WT", timestamp=timestamp, slot_len=size)
                    self.progress.observe(slot, parent=parent, timestamp=timestamp, reliable_seq=seq)
            elif payload[1] == 0x4B and len(payload) == 16:
                entry.update(kind="WK", receipt_seq=int.from_bytes(payload[4:8], "little"),
                             message_index=int.from_bytes(payload[8:12], "little"),
                             timestamp=int.from_bytes(payload[12:16], "little"))
            elif payload[1] == 0x47 and len(payload) == 8:
                entry.update(kind="WG", state=int.from_bytes(payload[4:8], "little"))
        if entry["kind"] == "other":
            self.progress.observe(b"\xff", parent=parent)
        self._kinds[side][entry["kind"]] += 1
        self._recent[side].append(entry)
        if len(self._first[side]) < 12:
            self._first[side].append(entry)

    def scheduled(self, batch, batch_size):
        """WK grouping at transmit attempt, including retries (not delivery).

        Native gold's WK message_index correlates with its datagram position.
        Record both without assuming the receiver's rule or rewriting bytes.
        """
        for start in range(0, len(batch), batch_size):
            app_position = receipt_position = 0
            for seq, flags, payload in batch[start:start + batch_size]:
                if not flags & 1:
                    continue
                app_position += 1
                if len(payload) != 16 or payload[:4] != b"WK\x0c\0":
                    continue
                receipt_position += 1
                self._receipt_attempts += 1
                record = {"attempt": self._receipt_attempts, "reliable_seq": seq,
                          "app_position": app_position, "receipt_position": receipt_position,
                          "message_index": int.from_bytes(payload[8:12], "little"),
                          "timestamp": int.from_bytes(payload[12:16], "little")}
                self._receipt_recent.append(record)
                if len(self._receipt_first) < 12:
                    self._receipt_first.append(record)

    def snapshot(self):
        result = {side: {"count": self._counts[side], "kinds": dict(self._kinds[side]),
                        "first": deepcopy(self._first[side]),
                        "recent": deepcopy(list(self._recent[side]))}
                  for side in self._kinds}
        result["uni"] = self.progress.uni_snapshot()
        result["wk_scheduled"] = {"attempts": self._receipt_attempts,
                                  "first": deepcopy(self._receipt_first),
                                  "recent": deepcopy(list(self._receipt_recent))}
        return result
