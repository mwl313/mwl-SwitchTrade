"""Synthetic independent NI evidence tests; no capture/trainer bytes."""
from dataclasses import replace

import pytest

from tools.gpsp_qualification.ni_identity import (
    inspect_native_game_ni, reassemble_child_game_ni,
)
from tools.payload_decoder import parse_gba_frames, parse_t_carrier


def slot(state, n, phase, payload=b"", *, ack=0):
    header = state << 10 | ack << 9 | n << 7 | phase << 5 | len(payload)
    raw = header.to_bytes(2, "little") + payload
    body = bytes(4) + bytes((0, len(raw), 0, 0)) + raw
    frame, = parse_gba_frames(b"WT" + len(body).to_bytes(2, "little") + body, strict=True).frames
    carrier = parse_t_carrier(frame, role="child")
    assert not carrier.issues
    return carrier.slot


def record(version=4, gender=0):
    # English, no progression flags, synthetic TID/name, already-started Trade.
    gname = (2 | version << 10).to_bytes(2, "little")
    gname += b"\x11\x22" + bytes(6) + bytes((0x84, gender, 0))
    return b"\x02\x00" + gname + bytes(2) + b"\xbb\xff" + bytes(7)


def transfer(data):
    return [slot(1, 1, 0, b"\x01\x0c\x00\x1a\x00\x00\x00"),
            slot(2, 1, 0, data[:12]), slot(2, 1, 1, data[12:24]),
            slot(2, 1, 2, data[24:]), slot(3, 0, 0)]


@pytest.mark.parametrize("version,gender", [(4, 0), (5, 1)])
def test_actual_carrier_decoder_to_complete_identity(version, gender):
    data = record(version, gender)
    assert reassemble_child_game_ni(transfer(data)) == data
    fields = inspect_native_game_ni(data)
    assert (fields["language"], fields["version"], fields["gender"]) == (2, version, gender)
    assert fields["activity"] == 4 and fields["started_activity"]
    assert not fields["can_link_nationally"] and not fields["has_national_dex"]
    assert not fields["game_clear"]


def test_retransmissions_and_receive_acks_do_not_duplicate_data():
    a, b, c, d, e = transfer(record())
    assert reassemble_child_game_ni([a, a, b, slot(1, 1, 0, ack=1), b, c, d, e, e]) == record()


@pytest.mark.parametrize("missing", range(5))
def test_missing_fragment_or_boundary_never_completes(missing):
    slots = transfer(record())
    del slots[missing]
    with pytest.raises(ValueError, match="NI_(INCOMPLETE|TRANSFER_ORDER)"):
        reassemble_child_game_ni(slots)


def test_conflicting_retransmission_rejected():
    a, b, c, d, e = transfer(record())
    with pytest.raises(ValueError, match="NI_CONFLICTING_RETRANSMISSION"):
        reassemble_child_game_ni([a, b, replace(b, payload=bytes(12)), c, d, e])


def test_parent_evidence_must_not_be_treated_as_child():
    a, *rest = transfer(record())
    with pytest.raises(ValueError, match="NI_SOURCE_ROLE"):
        reassemble_child_game_ni([replace(a, role="parent"), *rest])


def test_multiple_connections_must_not_be_merged():
    with pytest.raises(ValueError, match="NI_MULTIPLE_TRANSFERS"):
        reassemble_child_game_ni(transfer(record()) + transfer(record(5, 1)))


@pytest.mark.parametrize("change,code", [
    ({"n": 2}, "NI_UNSUPPORTED_WINDOW"),
    ({"phase": 3}, "NI_UNSUPPORTED_WINDOW"),
    ({"size": 11}, "NI_FRAGMENT_SIZE"),
])
def test_different_window_not_silently_reassembled(change, code):
    a, b, *rest = transfer(record())
    with pytest.raises(ValueError, match=code):
        reassemble_child_game_ni([a, replace(b, **change), *rest])


def test_nonempty_end_is_not_completion():
    *start, end = transfer(record())
    with pytest.raises(ValueError, match="NI_INVALID_END"):
        reassemble_child_game_ni([*start, replace(end, size=1, payload=b"\x00")])


@pytest.mark.parametrize("change,code", [
    ({"payload": b"\x01\x0c\x00\xff\xff\xff\xff"}, "NI_UNSUPPORTED_HEADER"),
    ({"size": 31}, "NI_TRUNCATED"),
])
def test_header_rejects_unbounded_or_truncated_input(change, code):
    a, *rest = transfer(record())
    with pytest.raises(ValueError, match=code):
        reassemble_child_game_ni([replace(a, **change), *rest])


def test_summary_never_emits_identity_bytes():
    data = record()
    modified = bytearray(data)
    modified[4:6] = b"\x33\x44"
    modified[17:26] = b"\xbc" * 9
    assert inspect_native_game_ni(data) == inspect_native_game_ni(bytes(modified))


@pytest.mark.parametrize("data", [b"", bytes(25), bytes(26), record()+b"\x00"])
def test_record_requires_exact_native_game_shape(data):
    with pytest.raises(ValueError, match="NI_GAME_RECORD"):
        inspect_native_game_ni(data)


def test_native_bitfields_preserved_independently():
    data = bytearray(record())
    data[2:4] = (0x3F0 | 7 | 5 << 10 | 3 << 14).to_bytes(2, "little")
    data[10:12] = (511 | 17 << 10).to_bytes(2, "little")
    data[12:14] = bytes((0x43, 50 << 1 | 1))
    fields = inspect_native_game_ni(bytes(data))
    assert fields["version"] == 5 and fields["language"] == 7
    assert fields["has_news"] and fields["has_card"] and fields["game_clear"]
    assert fields["can_link_nationally"] and fields["has_national_dex"]
    assert fields["compatibility_reserved"] == 3
    assert fields["activity"] == 0x43 and not fields["started_activity"]
    assert fields["trade_species"] == 511 and fields["trade_type"] == 17
    assert fields["gender"] == 1 and fields["trade_level"] == 50
