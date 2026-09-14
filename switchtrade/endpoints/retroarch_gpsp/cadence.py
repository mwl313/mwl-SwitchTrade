"""Bound NI retries and NI-phase receipts; keep UNI-phase receipts lossless.

This is endpoint conversion policy, not Core packet loss or game ACK synthesis.
Only a single, recognized NI subframe may be paced; distinct data, UNI, mixed
slots and unknown layouts remain byte-for-byte FIFO. The game still originates
every retry. A paced copy never allocates a Core sequence or a Reliable slot.
"""
from dataclasses import replace
import time
from .progress import uni_slot


# Radio retry cadence, NOT a human-wait or game timeout. Trial10 accumulated
# 189 END copies behind a ~15 application-frame/s local path. Four retries/s
# per NI lane leave space for transitions and receipts without enlarging Pia.
NI_RETRY_SECONDS = .25
RECEIPT_SECONDS = .25


class RfuCadence:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self._lanes = {}
        self._states = {}
        self._receipt = None
        self._receipt_due = 0.0
        self._receipt_sequence = 0
        self._closed = False
        self.ni_paced = self.receipts_coalesced = 0
        self._ordered_receipts = False
        self._last_receipt_timestamp = None

    def admit(self, actions):
        output = []
        for action in actions:
            if self._closed:
                break
            if action.classification == "parent_transfer":
                size = int.from_bytes(action.payload[8:12], "big")
                if uni_slot(action.payload[12:12 + size], parent=True):
                    # Clock-driven UNI is not the free-running NI retry phase.
                    # Retire its predecessor's deferred receipt before entering
                    # lossless receipt mode; every later callback keeps its WK.
                    self._ordered_receipts = True
                    output.extend(self.poll(force=True))
            if action.classification == "parent_ack":
                # During NI keep one unsent receipt, not a growing history.
                # After the first UNI, emit each receipt without replacement.
                # This does NOT
                # acknowledge a game NI transaction or earlier timestamps.
                # The translator can reissue a WK when the Switch repeats a
                # known WT whose local receipt has already completed.
                if self._receipt is not None:
                    self.receipts_coalesced += 1
                self._receipt = action
                output.extend(self.poll(force=self._ordered_receipts))
                continue
            if action.classification == "child_transfer":
                payload = action.payload
                slot = payload[12:12 + payload[9]]
                if not self._admit_slot(slot):
                    continue
            if action.classification == "disconnect":
                self.close()
            output.append(action)
        return tuple(output)

    def _admit_slot(self, slot):
        if len(slot) < 2:
            self._lanes.clear()
            self._states.clear()
            return True
        word = int.from_bytes(slot[:2], "little")
        state, size = (word >> 10) & 15, word & 31
        ack, phase = (word >> 9) & 1, (word >> 5) & 3
        # Mixed slots, padding ambiguities, UNI and unknown data are opaque.
        if word >> 14 or len(slot) != size + 2 or state not in (1, 2, 3):
            self._lanes.clear()
            self._states.clear()
            return True
        if (ack and size) or (state == 3 and size):
            self._lanes.clear()
            self._states.clear()
            return True
        if self._states.get(ack) != state:
            # A new native stage/transaction must not inherit another phase's
            # old retry identity, even if the next transfer has identical data.
            self._lanes = {key: value for key, value in self._lanes.items() if key[0] != ack}
            self._states[ack] = state
        lane = (ack, phase)  # at most eight entries; n/state/bytes remain identity
        now = self.clock()
        previous = self._lanes.get(lane)
        if previous is not None and previous[0] == slot and now < previous[1]:
            self.ni_paced += 1
            return False
        self._lanes[lane] = (bytes(slot), now + NI_RETRY_SECONDS)
        return True

    def poll(self, *, force=False):
        if self._closed or self._receipt is None or (not force and self.clock() < self._receipt_due):
            return ()
        action, self._receipt = self._receipt, None
        self._receipt_due = self.clock() + RECEIPT_SECONDS
        # Number receipts when actually admitted, not when replaced while local.
        self._receipt_sequence = self._receipt_sequence % 0xFFFFFFFF + 1
        self._last_receipt_timestamp = int.from_bytes(action.payload[12:16], "little")
        return (replace(action, payload=action.payload[:4] +
                        self._receipt_sequence.to_bytes(4, "little") + action.payload[8:]),)

    def close(self):
        self._closed = True
        self._receipt = None
        self._lanes.clear()
        self._states.clear()

    def snapshot(self):
        return {"ni_paced": self.ni_paced, "receipts_coalesced": self.receipts_coalesced,
                "receipt_pending": int(self._receipt is not None), "ni_lanes": len(self._lanes),
                "ordered_receipts": self._ordered_receipts,
                "receipt_sequence": self._receipt_sequence,
                "last_receipt_timestamp": self._last_receipt_timestamp}
