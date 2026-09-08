import json

import pytest

from frlgsim.beacon import build_application_data
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
