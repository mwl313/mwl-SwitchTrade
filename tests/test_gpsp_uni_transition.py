"""Native-shaped UNI admission/receipt regressions; not physical trade proof."""
from collections import deque
import json

import pytest

from bridge.frlgsim import rfu as native
from switchtrade.endpoints.retroarch_gpsp import rfu as r
from switchtrade.endpoints.retroarch_gpsp.cadence import RfuCadence
from tests.test_gpsp_rfu import TranslatorFixture, GPSP_DEVICE, parent_t, rfu1


class Link:
    def __init__(self):
        self.translator = TranslatorFixture.connected()
        self.cadence = RfuCadence(lambda: 0)
        self.local = deque()
        self.remote = []
        self.cs, self.rs = 1, 2

    def admit(self, actions):
        for a in self.cadence.admit(actions):
            (self.local if a.destination == "core" else self.remote).append(a)

    def parent(self, timestamp, slot):
        self.rs += 1
        self.admit(self.translator.from_switch(parent_t(timestamp, slot), flags=7, generation=1, sequence=self.rs))

    def core(self, kind, slot=b""):
        self.cs += 1
        self.admit(self.translator.from_core(rfu1(kind, GPSP_DEVICE | len(slot) << 24, slot,
            size=104 if kind == r.RFU1_CLIENT_SEND else 16), peer_id=1, sequence=self.cs))


def test_uni_transition_preserves_each_receipt_on_both_sides_of_boundary():
    link = Link()
    for i in range(1, 4):
        link.parent(i, None)  # real translator owns receipt numbering
    link.parent(4, native.parent_uni_slot([bytes(14)]))
    link.core(r.RFU1_CLIENT_ACK)
    for i in range(5, 15):
        link.parent(i, None)
    receipts = [int.from_bytes(a.payload[12:16], "little") for a in link.remote]
    assert receipts == list(range(1, 15))
    assert [int.from_bytes(a.payload[4:8], "little") for a in link.remote] == list(range(1, len(receipts) + 1))
    assert link.cadence.snapshot()["ordered_receipts"]
    assert not link.cadence.snapshot()["receipt_pending"]


def test_ack_before_admission_cannot_overrun_stock_buffer_during_uni_burst():
    link = Link()
    slots = [native.parent_uni_slot([i.to_bytes(2, "little") + bytes(12)]) for i in range(12)]
    for i, slot in enumerate(slots, 1):
        link.parent(i, slot)
    assert len(link.local) == 1
    # A network callback ACK is NOT permission to send the next buffered UNI.
    # Model gpSP's actual four-slot admission; game reads are deliberately late.
    for i, slot in enumerate(slots, 1):
        packet = link.local.popleft()
        assert packet.payload[12:12 + len(slot)] == slot
        link.core(r.RFU1_CLIENT_ACK)
        assert not link.local
        assert link.translator.snapshot()["uni_inflight"] == i
        # The supported child MSC callback reads parent data before emitting
        # this UNI. No clock advance / synthetic response is injected by Core.
        link.core(r.RFU1_CLIENT_SEND, native.uni_slot(bytes(14)))
        assert len(link.local) == (i < len(slots))
    assert [int.from_bytes(a.payload[12:16], "little") for a in link.remote if a.classification == "parent_ack"] == list(range(1, 13))
    assert link.translator.snapshot()["uni_inflight"] is None
    assert link.translator.snapshot()["uni_waiting"] == 0


def test_queued_duplicate_not_falsely_receipted_or_redelivered():
    link = Link()
    slot = native.parent_uni_slot([bytes(14)])
    link.parent(1, slot)
    link.parent(2, slot)
    link.parent(2, slot)
    assert len(link.local) == 1 and not link.remote
    link.core(r.RFU1_CLIENT_ACK)
    link.parent(1, slot)
    assert len(link.local) == 1  # no repeat delivery to the game buffer
    assert all(int.from_bytes(a.payload[12:16], "little") == 1 for a in link.remote)


def test_unrelated_or_early_child_input_does_not_grant_uni_credit():
    link = Link()
    slot = native.parent_uni_slot([bytes(14)])
    link.parent(1, slot)
    link.parent(2, slot)
    link.core(r.RFU1_CLIENT_SEND, native.uni_slot(bytes(14)))  # no correlated local receipt yet
    assert len(link.local) == 1
    link.core(r.RFU1_CLIENT_ACK)
    link.core(r.RFU1_CLIENT_SEND, b"\0\0")
    assert len(link.local) == 1
    link.core(r.RFU1_CLIENT_SEND, native.uni_slot(bytes(14)))
    assert len(link.local) == 2


def test_waiting_is_bounded_and_first_failure_is_sticky():
    link = Link()
    slot = native.parent_uni_slot([bytes(14)])
    for i in range(1, r.MAX_PENDING + 1):
        link.parent(i, slot)
    assert len(link.local) == 1
    with pytest.raises(r.TranslatorError) as first:
        link.parent(r.MAX_PENDING + 1, slot)
    assert first.value.code == "TRANSLATOR_QUEUE_FULL"
    with pytest.raises(r.TranslatorError) as again:
        link.core(r.RFU1_CLIENT_ACK)
    assert first.value is again.value
    link.translator.retire()
    assert link.translator.snapshot()["uni_waiting"] == 0
    with pytest.raises(r.TranslatorError) as retired:
        link.core(r.RFU1_CLIENT_ACK)
    assert retired.value is first.value


def test_timestamp_wrap_preserves_each_uni_receipt_and_retire_erases_waiting():
    link = Link()
    slot = native.parent_uni_slot([bytes(14)])
    for timestamp in (0xFFFFFFFE, 0xFFFFFFFF, 1):
        link.parent(timestamp, slot)
        link.local.popleft()
        link.core(r.RFU1_CLIENT_ACK)
        link.core(r.RFU1_CLIENT_SEND, native.uni_slot(bytes(14)))
    assert [int.from_bytes(a.payload[12:16], "little") for a in link.remote
            if a.classification == "parent_ack"] == [0xFFFFFFFE, 0xFFFFFFFF, 1]
    link.parent(2, slot)
    link.parent(3, slot)
    link.translator.retire()
    assert link.translator.state == "closed"
    assert link.translator.snapshot()["uni_waiting"] == 0
    assert link.translator.snapshot()["pending_core_acks"] == 0
    assert link.translator.snapshot()["uni_inflight"] is None


@pytest.mark.parametrize("bit", [9, 11, 13, 18, 19, 22])
def test_unqualified_parent_layout_is_not_subject_to_uni_credit(bit):
    link = Link()
    raw = native.parent_uni_slot([bytes(14)])
    slot = (int.from_bytes(raw[:3], "little") ^ (1 << bit)).to_bytes(3, "little") + raw[3:]
    for i in (1, 2):
        link.parent(i, slot)
    assert len(link.local) == 2
    assert link.translator.snapshot()["uni_inflight"] is None
    assert not link.cadence.snapshot()["ordered_receipts"]


def test_uni_metadata_bounded_does_not_include_game_data_and_fresh_generation_resets():
    link = Link()
    for i in range(40):
        payload = b"\xe1\x89" + b"PRIVATE-DATA"
        link.parent(i + 1, native.parent_uni_slot([payload]))
        link.local.popleft()
        link.core(r.RFU1_CLIENT_ACK)
        link.core(r.RFU1_CLIENT_SEND, native.uni_slot(payload))
    snapshot = link.translator.snapshot()
    assert len(snapshot["recent_transfers"]) == 24
    assert len(snapshot["uni"]["child"]["first"]) == 12
    assert snapshot["uni"]["child"]["last"] == {"commands": [0x8900], "fragments": [1], "tag": 7}
    assert "PRIVATE" not in json.dumps(snapshot)
    fresh = Link()
    assert fresh.translator.snapshot()["uni_waiting"] == 0
    assert fresh.translator.snapshot()["recent_transfers"] == []
    assert not fresh.cadence.snapshot()["ordered_receipts"]
