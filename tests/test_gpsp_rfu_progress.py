"""Synthetic native NI boundaries; no commercial game, save, or capture data."""
import json

import pytest

from bridge.frlgsim import ni, rfu as native
from switchtrade.endpoints.retroarch_gpsp.progress import RfuProgress
from switchtrade.endpoints.retroarch_gpsp import rfu as r
from tests.test_gpsp_rfu import TranslatorFixture, GPSP_DEVICE, CHILD_CONNECTION, parent_t


def test_ni_and_rfu1_acks_are_distinct_and_retries_are_not_filtered():
    translator = TranslatorFixture.connected()
    sender = ni.NISender(bytes(range(26)))
    slot = sender.next_slot()
    for sequence in range(2, 302):
        actions = translator.from_core(r._rfu1(r.RFU1_CLIENT_SEND,
            len(slot) << 24 | GPSP_DEVICE, slot), peer_id=1, sequence=sequence)
        # Equal NI retry bytes are still forwarded, with distinct WT stamps.
        assert len(actions) == 1
        assert actions[0].payload[12:12 + len(slot)] == slot
        assert int.from_bytes(actions[0].payload[4:8], "little") == r.CHILD_TIMESTAMP_SEED + sequence - 2
    child = translator.progress.snapshot()["child"]
    assert child["kinds"] == {"ni_start": 300}
    assert child["repeated_slots"] == 299
    assert len(child["first_changes"]) == 1

    # gpSP's socket-level ACK of a parent NI frame does not create an NI ACK.
    parent_slot = ni.parent_join_status_slots()[0]
    action, = translator.from_switch(parent_t(1, parent_slot), flags=7, generation=1, sequence=3)
    assert action.payload[12:12 + len(parent_slot)] == parent_slot
    before = translator.progress.snapshot()
    ack, = translator.from_core(r._rfu1(r.RFU1_CLIENT_ACK, GPSP_DEVICE), peer_id=1, sequence=302)
    assert ack.payload.startswith(b"WK")
    assert translator.progress.snapshot() == before
    native_ack = ni.recv_ack_slot(native.LCOM_NI_START, 1, 0)
    translator.from_core(r._rfu1(r.RFU1_CLIENT_SEND,
        len(native_ack) << 24 | GPSP_DEVICE, native_ack), peer_id=1, sequence=303)
    assert translator.progress.snapshot()["child"]["kinds"]["ni_start_ack"] == 1


@pytest.mark.parametrize("source", ["gpsp", "switch"])
def test_disconnect_source_is_explicit_without_guessing_game_reason(source):
    translator = TranslatorFixture.connected()
    assert translator.disconnected_by is None
    if source == "gpsp":
        translator.from_core(r._rfu1(r.RFU1_DISCONNECT, GPSP_DEVICE), peer_id=1, sequence=2)
    else:
        translator.from_switch(r._gba(r.GBA_DISCONNECT, CHILD_CONNECTION), flags=7, generation=1, sequence=3)
    snapshot = translator.snapshot()
    assert snapshot["disconnected_by"] == source
    assert snapshot["state"] == "closed"
    assert "success" not in json.dumps(snapshot)


def test_multi_llsf_parse_is_all_or_unknown_and_preserves_opaque_data():
    progress = RfuProgress()
    first = ni.parent_recv_ack_slot(native.LCOM_NI_START, 1, 0)
    second = ni.parent_recv_ack_slot(native.LCOM_NI, 2, 3)
    progress.observe(first + second + bytes(2), parent=True)
    snapshot = progress.snapshot()["parent"]
    assert snapshot["kinds"] == {"ni_start_ack": 1, "ni_ack": 1}
    assert snapshot["last"] == {"state": "ni", "ack": 1, "n": 2, "phase": 3, "size": 0, "slot_mask": 1}
    progress.observe(first + b"\xff", parent=True)
    assert progress.snapshot()["parent"]["unknown_slots"] == 1
    assert progress.snapshot()["parent"]["kinds"] == snapshot["kinds"]
    progress.observe(bytes(16), parent=False)
    assert progress.snapshot()["child"]["idle_slots"] == 1
    assert progress.snapshot()["child"]["kinds"] == {}  # Idle is not a NI terminator.


def test_diagnostics_are_bounded_detached_private_and_generation_local():
    progress = RfuProgress()
    secret = b"PRIVATE-DATA"
    for index in range(1000):
        slot = native.child_ni_llsf(native.LCOM_NI, index % 4, (index // 4) % 4, 0, len(secret)) + secret
        progress.observe(slot, parent=False)
    snapshot = progress.snapshot()
    assert len(snapshot["child"]["first_changes"]) == 12
    assert len(json.dumps(snapshot)) < 2500
    assert progress.milestone == 1
    assert "PRIVATE-DATA" not in json.dumps(snapshot)
    assert secret.hex() not in json.dumps(snapshot)
    snapshot["child"]["last"]["state"] = "changed"
    assert progress.snapshot()["child"]["last"]["state"] == "ni"
    assert RfuProgress().snapshot()["child"]["slots"] == 0


def test_invalid_translator_input_cannot_publish_ni_progress():
    translator = TranslatorFixture.connected()
    slot = ni.NISender(bytes(26)).next_slot()
    with pytest.raises(r.TranslatorError):
        translator.from_core(r._rfu1(r.RFU1_CLIENT_SEND,
            len(slot) << 24 | GPSP_DEVICE, slot + b"\x01"), peer_id=1, sequence=2)
    assert translator.progress.snapshot()["child"]["slots"] == 0
