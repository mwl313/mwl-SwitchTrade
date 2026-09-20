"""Metadata only at native Reliable admission/scheduling, never game receipt.

No raw packets, game arguments, connection IDs or payload fingerprints escape.
Unknown formats stay opaque; this observer cannot acknowledge or reject data.
"""
from collections import Counter, deque
from copy import deepcopy
import time

from switchtrade.rfu_progress import RfuProgress
from switchtrade.rfu_trace import MetadataTrace, native_metadata


class NativeRfuProgress:
    def __init__(self, *, parent, clock=time.monotonic):
        self.parent = parent
        self._clock = clock
        self._started = clock()
        self.progress = RfuProgress(clock)
        self.trace = MetadataTrace(clock=clock)
        self._counts = Counter()
        self._kinds = {side: Counter() for side in ("rx_admitted", "tx_queued")}
        self._recent = {side: deque(maxlen=24) for side in self._kinds}
        self._first = {side: [] for side in self._kinds}
        self._receipt_attempts = 0
        self._receipt_first = []
        self._receipt_recent = deque(maxlen=24)
        self._window = None
        self._pending_count = self._pending_peak = 0
        self._pending_max_ms = 0.0
        self._pre_clear = None

    def pending(self, envelope, depth):
        """One host clock across Core admission and the bounded native FIFO."""
        now = self._clock()
        self._pending_count += 1
        self._pending_peak = max(self._pending_peak, depth)
        received = getattr(envelope, "core_received_at", None)
        enqueued = getattr(envelope, "core_enqueued_at", None)
        known = received is not None and enqueued is not None and received <= enqueued <= now
        self.trace.record("native_pending", pending_ordinal=self._pending_count, depth=depth,
                          core_wait_ms=round((enqueued - received) * 1000, 3) if known else None,
                          core_queue_ms=round((now - enqueued) * 1000, 3) if known else None,
                          **native_metadata(envelope.payload, parent=self.parent))
        return self._pending_count, now

    def backlog(self, pending, *, clear_reason=None):
        oldest_ms = round((self._clock() - pending[0][2]) * 1000, 3) if pending else 0.0
        result = {"count": len(pending), "oldest_ms": oldest_ms,
                  "peak": self._pending_peak, "max_residence_ms": self._pending_max_ms}
        if clear_reason is not None and self._pre_clear is None:
            self._pre_clear = {"reason": clear_reason, **result}
            self.trace.record("native_pending_clear", **self._pre_clear)
        return {**result, "pre_clear": deepcopy(self._pre_clear)}

    def ack(self, ackid, mask, before, after):
        # Only authenticated parsed ACK metadata, not packet bytes or RFU ACKs.
        self.trace.record("native_ack", ack_id=ackid,
                          selective_bits=int.from_bytes(mask or b"", "little").bit_count(),
                          before_low=before[0], after_low=after[0],
                          before_inflight=before[1], after_inflight=after[1],
                          released=before[1] - after[1])

    def window(self, send_low, next_out, inflight):
        current = (send_low, next_out, inflight)
        if current != self._window:
            self._window = current
            self.trace.record("native_window", send_low=send_low,
                              next_out=next_out, inflight=inflight)

    def observe(self, payload, seq, flags, *, received, pending=None):
        side = "rx_admitted" if received else "tx_queued"
        parent = not self.parent if received else self.parent
        self._counts[side] += 1
        metadata = native_metadata(payload, parent=parent)
        entry = {"ordinal": self._counts[side], "reliable_seq": seq,
                 "flags": flags, **metadata,
                 "elapsed_ms": round((self._clock() - self._started) * 1000)}
        # Recognize only a complete single native wrapper. Malformed/unknown
        # payloads remain forwarded by TunnelSim without exposing their bytes.
        if entry["kind"] == "WT":
            self.progress.observe(payload[12:12 + entry["slot_len"]], parent=parent,
                                  timestamp=entry["timestamp"], reliable_seq=seq)
        if entry["kind"] == "other":
            self.progress.observe(b"\xff", parent=parent)
        self._kinds[side][entry["kind"]] += 1
        timing = {}
        if pending is not None:
            ordinal, started = pending
            residence_ms = round((self._clock() - started) * 1000, 3)
            self._pending_max_ms = max(self._pending_max_ms, residence_ms)
            timing = {"pending_ordinal": ordinal, "pending_ms": residence_ms}
        self.trace.record("native_" + side, reliable_seq=seq, flags=flags,
                          **metadata, **timing)
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
                self.trace.record("native_tx_attempt", reliable_seq=seq, flags=flags,
                                  app_position=app_position,
                                  **native_metadata(payload, parent=self.parent))
                if len(payload) != 16 or payload[:4] != b"WK\x0c\0":
                    continue
                receipt_position += 1
                self._receipt_attempts += 1
                record = {"attempt": self._receipt_attempts, "reliable_seq": seq,
                          "elapsed_ms": round((self._clock() - self._started) * 1000),
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
