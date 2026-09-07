"""CI #104/#112: a failed state READ, not merely a failed os.replace."""

from pathlib import Path
import threading
import uuid
from unittest.mock import patch

import pytest

from switchtrade.connection import distributed_harness as harness


def control(root):
    return harness.DistributedControl(root, test_id=str(uuid.uuid4()), source_sha="a" * 40,
                                      release="test", role="a_room_joiner")


def test_atomic_state_reader_survives_only_the_bounded_windows_access_window(tmp_path):
    owner = control(tmp_path)
    original = Path.read_text
    attempts = []

    def read(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError(13, "destination being replaced")
        return original(path, *args, **kwargs)

    with patch.object(harness, "_WINDOWS_CONTROL_READ", True), patch.object(Path, "read_text", read):
        state = owner.read_state(owner.state_path)
    assert state["test_id"] == owner.state["test_id"]
    assert attempts == [owner.state_path] * 3


@pytest.mark.parametrize("windows", [False, True])
def test_permanent_read_denial_preserves_first_cause_and_never_runs_control(tmp_path, windows):
    owner = control(tmp_path)
    first = PermissionError(13, "permanent denial")
    with patch.object(harness, "_WINDOWS_CONTROL_READ", windows), \
         patch.object(harness, "_CONTROL_READ_WINDOW", .02), \
         patch.object(Path, "read_text", side_effect=first):
        with pytest.raises(SystemExit, match="DISTRIBUTED_CONTROL_STATE_INVALID") as caught:
            owner.read_state(owner.state_path)
    assert caught.value.__cause__ is first
    assert not owner.command_path.exists()


def test_bad_json_and_missing_state_are_not_retried(tmp_path):
    owner = control(tmp_path)
    for fault in ("{", FileNotFoundError("missing")):
        with patch.object(harness, "_WINDOWS_CONTROL_READ", True):
            with patch.object(Path, "read_text", **({"side_effect": fault} if isinstance(fault, Exception)
                                                   else {"return_value": fault})) as read:
                with pytest.raises(SystemExit, match="DISTRIBUTED_CONTROL_STATE_INVALID"):
                    owner.read_state(owner.state_path)
                assert read.call_count == 1


def test_actual_atomic_publisher_and_reader_keep_identity_and_whole_states(tmp_path):
    owner = control(tmp_path)
    failures = []

    def publish():
        try:
            for _ in range(100):
                owner.publish("pairing")
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=publish)
    worker.start()
    try:
        previous = 0
        while worker.is_alive():
            state = owner.read_state(owner.state_path)
            assert state["test_id"] == owner.state["test_id"]
            assert state["sequence"] >= previous
            previous = state["sequence"]
    finally:
        worker.join(2)
    assert not worker.is_alive() and not failures
    assert owner.read_state(owner.state_path)["sequence"] == 101
    assert not list(tmp_path.glob("*.tmp"))
