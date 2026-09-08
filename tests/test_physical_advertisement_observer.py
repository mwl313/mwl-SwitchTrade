import json

import pytest

from frlgsim.beacon import _b85_encode, build_application_data, build_rfu_record
from tests.physical_advertisement_observer import selected_record, write_private
from tests.test_direct_a_stage import network


def test_selection_keeps_only_exact_trainer_and_rejects_ambiguity():
    selected = network(application_data=build_application_data(123, "TEST", 456))
    other = network(application_data=build_application_data(124, "OTHER", 457))
    assert len(selected_record([other, selected], "TEST")) == 24
    assert selected_record([other], "TEST") is None
    assert selected_record([network(app_version=99)], "TEST") is None
    with pytest.raises(Exception) as caught:
        selected_record([selected, selected], "TEST")
    assert caught.value.code == "A_ROOM_AMBIGUOUS"


def test_private_record_never_overwrites_existing_evidence(tmp_path):
    path = tmp_path / "sample.json"
    write_private(path, {"record_hex": "00" * 24})
    with pytest.raises(FileExistsError):
        write_private(path, {"replacement": True})
    assert json.loads(path.read_text()) == {"record_hex": "00" * 24}


def test_scan_diagnostics_distinguish_absence_filter_and_trainer_without_identity():
    counts = {}
    assert selected_record([], "TEST", counts) is None
    assert counts == {"networks": 0, "compatible_rooms": 0, "selected_matches": 0,
                      "other_trainers": 0, "rejected_conditions": {}}
    candidates = [network(app_version=99, channel=36),
                  network(application_data=build_application_data(124, "OTHER", 457)),
                  network(application_data=build_application_data(123, "TEST", 456))]
    assert len(selected_record(candidates, "TEST", counts)) == 24
    assert counts == {"networks": 3, "compatible_rooms": 2, "selected_matches": 1,
                      "other_trainers": 1,
                      "rejected_conditions": {"app_version": 1, "channel": 1}}
    assert "TEST" not in json.dumps(counts) and "OTHER" not in json.dumps(counts)
    with pytest.raises(Exception) as caught:
        selected_record([candidates[-1], candidates[-1]], "TEST", counts)
    assert caught.value.code == "A_ROOM_AMBIGUOUS"
    assert counts["selected_matches"] == 2


@pytest.mark.parametrize("padding", [b"\xff\xff\xff", b"\0\0\0", b"\x12\x34\x56"])
def test_selected_name_ends_at_eos_but_keeps_original_record(padding):
    record = bytearray(build_rfu_record(123, "TEST", 456))
    record[7:10] = padding  # Four letters + EOS; remaining bytes are not name.
    header = build_application_data(123, "TEST", 456)[:0x5C]
    candidate = network(application_data=header + _b85_encode(record))
    assert selected_record([candidate], "TEST") == bytes(record)
    assert selected_record([candidate], "TES") is None
    assert selected_record([candidate], "TESTS") is None
    record[6] = 0  # Same letters without their required EOS must not match.
    candidate.application_data = header + _b85_encode(record)
    assert selected_record([candidate], "TEST") is None
