"""Test the independent checker, NOT claim that production discovery works."""
import struct

import pytest

from tools.gpsp_qualification.check_advertisement import inspect_broadcast


def broadcast(data):
    return struct.pack("!9I", 0x52465531, 0, 0x1234, *struct.unpack("<6I", data))


def valid_record():
    # Synthetic English FireRed, public TID 0x2211, empty trade group, name A.
    # RfuGameData: compatibility, TID, partner[4], species/type, activity,
    # gender/level, padding. No inferred Switch -> gname mapping here.
    gname = bytes.fromhex("02101122000000000000040000")
    uname = b"\xbb" + b"\xff" * 7
    checksum = (~sum(gname[:8] + uname)) & 255
    return b"\x02\x00" + gname + bytes([checksum]) + uname


def test_native_game_config_satisfies_discovery_checks():
    assert all(inspect_broadcast(broadcast(valid_record())).values())


@pytest.mark.parametrize("offset,field", [(0, "game_serial"), (2, "game_checksum"),
                                          (15, "game_checksum"), (23, "game_checksum")])
def test_native_game_discovery_rejects_corruption(offset, field):
    data = bytearray(valid_record())
    data[offset] ^= 1
    assert not inspect_broadcast(broadcast(data))[field]


def test_legacy_synthetic_golden_is_not_a_valid_game_advertisement():
    # Frozen pre-fix bytes, independent of the golden file that a real fix must
    # update. Old tests checked only equality with these same wrong bytes.
    packet = bytes.fromhex("524655310000000000001234c9c22211ffffcecd1234ffff000000010000000000000000")
    assert inspect_broadcast(packet) == dict(frame=True, game_serial=False, game_checksum=False)


@pytest.mark.parametrize("packet", [b"", bytes(35), bytes(36), bytes(37)])
def test_bad_rfu_envelope_fails(packet):
    assert not inspect_broadcast(packet)["frame"]
