"""Read-only native-boundary correlation; synthetic data and no radio."""
import json

import pytest

from bridge.frlgsim import gbaframe, rfu
from bridge.frlgsim.tunnel_progress import NativeRfuProgress


@pytest.mark.parametrize("parent", [False, True])
def test_native_boundary_roles_sequences_receipts_and_long_wait(parent):
    clock = [1.0]
    observer = NativeRfuProgress(parent=parent, clock=lambda: clock[0])
    builder = rfu.SlotBuilder()
    for index in range(337):
        command = builder.build(rfu.held_keys_words())
        if index == 150:  # A missing non-idle command at this boundary, not a game verdict.
            continue
        observer.observe(gbaframe.wrap_t(rfu.uni_slot(command), index),
                         index & 0xffff, 7, received=parent)
        observer.observe(gbaframe.wrap_parent_t(rfu.parent_uni_slot([bytes(14)]), index + 1000),
                         (0xfff0 + index) & 0xffff, 7, received=not parent)
    observer.observe(gbaframe.build_k(7, 2, 1336), 500, 7, received=parent)
    snapshot = observer.snapshot()
    child = snapshot["uni"]["child"]
    assert child["count"] == 336 and child["tag_checks"] == 335
    assert child["tag_discontinuities"] == 1
    assert child["first_tag_discontinuity"]["reliable_seq"] == 151
    assert child["last"]["commands"] == [0xBE00]
    assert child["recent"][-1]["timestamp"] == 336
    assert snapshot["uni"]["parent"]["count"] == 336
    child_boundary = snapshot["rx_admitted" if parent else "tx_queued"]
    assert child_boundary["kinds"] == {"WT": 336, "WK": 1}
    receipt = child_boundary["recent"][-1]
    assert (receipt["message_index"], receipt["timestamp"], receipt["receipt_seq"]) == (2, 1336, 7)
    assert len(child_boundary["first"]) == 12 and len(child_boundary["recent"]) == 24
    clock[0] += 240
    assert observer.snapshot()["uni"]["child"]["last_age_ms"] == 240000
    assert observer.snapshot()["uni"]["child"]["count"] == 336


def test_unknown_private_input_and_detached_snapshots_cannot_leak_or_invent_tags():
    observer = NativeRfuProgress(parent=False)
    secret = b"PRIVATE-DATA"
    slot = rfu.uni_slot(b"\xe1\x89" + secret)
    observer.observe(gbaframe.wrap_t(slot, 1), 1, 7, received=False)
    unknown = [b"", b"WT", gbaframe.wrap_t(slot, 2)[:-1], b"WZ\x0c\0" + bytes(12), secret]
    for seq, payload in enumerate(unknown, 2):
        observer.observe(payload, seq, 7, received=False)
    observer.observe(gbaframe.wrap_t(slot, 9), 9, 7, received=False)
    observer.observe(gbaframe.wrap_parent_t(None, 10), 10, 7, received=True)
    observer.observe(gbaframe.build_group_state(1), 11, 7, received=True)
    snapshot = observer.snapshot()
    assert snapshot["uni"]["child"]["tag_coverage_breaks"] == 1
    assert snapshot["uni"]["child"]["tag_checks"] == 0
    assert snapshot["tx_queued"]["kinds"] == {"WT": 2, "other": len(unknown)}
    assert snapshot["rx_admitted"]["kinds"] == {"WT": 1, "WG": 1}
    assert snapshot["rx_admitted"]["recent"][-1]["state"] == 1
    text = json.dumps(snapshot)
    assert "PRIVATE" not in text and secret.hex() not in text
    assert "keycode" not in text and "payload" not in text
    snapshot["tx_queued"]["recent"][0]["timestamp"] = -1
    snapshot["uni"]["child"]["recent"][0]["commands"][0] = -1
    assert observer.snapshot()["tx_queued"]["recent"][0]["timestamp"] == 1
    assert observer.snapshot()["uni"]["child"]["recent"][0]["commands"] == [0x8900]
    assert NativeRfuProgress(parent=False).snapshot()["tx_queued"]["count"] == 0


def test_receipt_grouping_is_bounded_attempt_evidence_not_rewrite_or_delivery():
    observer = NativeRfuProgress(parent=False)
    batch = [(4, 7, gbaframe.build_k(1, 1, 10)),
             (5, 7, gbaframe.wrap_t(rfu.uni_slot(bytes(14)), 20)),
             (6, 7, gbaframe.build_k(2, 1, 11)),
             (7, 7, gbaframe.build_k(3, 2, 12)),
             (None, 0, bytes(20))]
    original = list(batch)
    for _ in range(1000):  # Retransmits count as attempts, not new UNI/receipt data.
        observer.scheduled(batch, 3)
    snapshot = observer.snapshot()
    attempts = snapshot["wk_scheduled"]
    assert attempts["attempts"] == 3000
    assert len(attempts["first"]) == 12 and len(attempts["recent"]) == 24
    assert [(x["reliable_seq"], x["app_position"], x["receipt_position"], x["message_index"])
            for x in attempts["first"][:3]] == [(4, 1, 1, 1), (6, 3, 2, 1), (7, 1, 1, 2)]
    assert snapshot["tx_queued"]["count"] == 0 and snapshot["uni"]["child"]["count"] == 0
    assert batch == original
    attempts["recent"][0]["message_index"] = -1
    assert observer.snapshot()["wk_scheduled"]["recent"][0]["message_index"] == 1
