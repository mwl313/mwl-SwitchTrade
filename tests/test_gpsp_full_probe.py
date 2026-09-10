"""Qualification oracle regression, NOT stock-process or physical evidence."""
import asyncio
from collections import deque
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools/gpsp_qualification"))
    from tools.gpsp_qualification.full_probe import FullStackProbe
    # Only exercise the oracle: no thread, process, socket or radio is started.
    value = FullStackProbe.__new__(FullStackProbe)
    value.game = SimpleNamespace(output=deque())
    value.launch = SimpleNamespace(output=tmp_path)
    value.observed_sims = []
    value.receipt_verified = value.data_before_receipt = 0
    async def until(predicate, timeout):
        if not predicate():
            raise TimeoutError("modeled missing packet")
    value.until = until
    return value


def receipt(count=1):
    return b"WK\x0c\0" + struct.pack("<III", count, 1, count)


def data(number=1, count=2):
    return (b"WT\x14\0" + count.to_bytes(4, "little") + b"\0\x0c\0\0"
            + struct.pack("<III", 0x53544632, number, count))


@pytest.mark.parametrize("data_first", [False, True])
def test_reply_preserves_both_orders_and_exact_next_data(probe, data_first):
    for number in (1, 2):
        for count in range(1, 4):
            frames = [(receipt(count), 7), (data(number, count + 1), 7)]
            probe.game.output.extend(reversed(frames) if data_first else frames)
            result = asyncio.run(probe.expect_reply(count))
            probe.check_data(result, number, count + 1)
            assert not probe.game.output
    assert probe.receipt_verified == 6
    assert probe.data_before_receipt == (6 if data_first else 0)


@pytest.mark.parametrize("fault", ["no_receipt", "no_data", "duplicate_data", "duplicate_receipt",
    "wrong_timestamp", "wrong_sequence", "wrong_mask", "short_receipt", "extra_receipt",
    "wrong_flags", "disconnect", "wrong_round", "wrong_counter", "extra_data", "short_data",
    "wrong_size", "wrong_slots", "zero_timestamp"])
def test_reply_never_hides_missing_duplicate_stale_or_invalid_packets(probe, fault):
    ack, packet, flags = receipt(), data(), 7
    if fault == "wrong_timestamp": ack = ack[:12] + (2).to_bytes(4, "little")
    elif fault == "wrong_sequence": ack = ack[:4] + (2).to_bytes(4, "little") + ack[8:]
    elif fault == "wrong_mask": ack = ack[:8] + (2).to_bytes(4, "little") + ack[12:]
    elif fault == "short_receipt": ack = ack[:-1]
    elif fault == "extra_receipt": ack += b"\0"
    elif fault == "wrong_flags": flags = 0x0107
    elif fault == "disconnect": ack = b"WD\x02\0\0\0"
    elif fault == "wrong_round": packet = data(2)
    elif fault == "wrong_counter": packet = data(count=1)
    elif fault == "extra_data": packet += b"\0"
    elif fault == "short_data": packet = packet[:-1]
    elif fault == "wrong_size": packet = packet[:2] + b"\x13\0" + packet[4:]
    elif fault == "wrong_slots": packet = packet[:8] + b"\x0c\0\0\0" + packet[12:]
    elif fault == "zero_timestamp": packet = packet[:4] + b"\0" * 4 + packet[8:]
    frames = [(packet, 7), (ack, flags)]
    if fault == "no_receipt": frames = frames[:1]
    elif fault == "no_data": frames = frames[1:]
    elif fault == "duplicate_data": frames = [frames[0], frames[0], frames[1]]
    elif fault == "duplicate_receipt": frames = [frames[1], frames[1], frames[0]]
    probe.game.output.extend(frames)
    with pytest.raises((AssertionError, TimeoutError)):
        result = asyncio.run(probe.expect_reply(1))
        probe.check_data(result, 1, 2)
