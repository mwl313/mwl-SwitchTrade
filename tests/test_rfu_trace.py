"""Evidence coverage, privacy, boundary mismatch and pre-cleanup regressions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from bridge.frlgsim import gbaframe, rfu
from bridge.frlgsim.tunnel_progress import NativeRfuProgress
from switchtrade.core.contracts import LinkPacket
from switchtrade.endpoints.switch_ldn.tunnel_adapter import CoreTunnelAdapter
from switchtrade.rfu_trace import MetadataTrace, native_metadata
from tools.audit_rfu_trace import audit, read_trace, native_envelope_observations, receipt_accounting


def save(path, batches, side, generation="test"):
    path.write_text("".join(f"INFO rfu_trace id={generation} side={side} {json.dumps(x)}\n"
                            for x in batches), encoding="utf-8")


def test_middle_records_not_lost_after_ring_rollover_and_arbitrary_wait(tmp_path):
    clock = [1.0]
    trace = MetadataTrace(clock=lambda: clock[0])
    batches = []
    for index in range(337):
        trace.record("core_enqueued", timestamp=index, kind="WT")
        clock[0] += .017
        if index % 100 == 0:
            batches.append(trace.drain())
    clock[0] += 240
    batches.append(trace.drain(final=True))
    path = tmp_path / "guest.log"
    save(path, batches, "gpsp")
    result = read_trace(path, "gpsp")
    assert result["issues"] == []
    assert [e["timestamp"] for e in result["entries"]] == list(range(337))
    assert batches[-1]["elapsed_ms"] > 240000


@pytest.mark.parametrize("damage", ["overflow", "middle_batch", "final", "duplicate",
                                     "bad_json", "bad_event", "nan_time", "no_source"])
def test_incomplete_evidence_never_passes(damage, tmp_path):
    trace = MetadataTrace(capacity=2 if damage == "overflow" else 10)
    batches = []
    for _ in range(3):
        for index in range(3):
            trace.record("core_received", timestamp=index)
        batches.append(trace.drain())
    batches.append(trace.drain(final=True))
    if damage == "middle_batch":
        del batches[1]
    elif damage == "final":
        batches.pop()
    elif damage == "duplicate":
        batches.insert(1, deepcopy(batches[0]))
    elif damage == "bad_event":
        batches[1]["entries"][0] = {"seq": 5}
    elif damage == "nan_time":
        batches[-1]["elapsed_ms"] = float("nan")
    elif damage == "no_source":
        batches[0].pop("source")
    path = tmp_path / "guest.log"
    save(path, batches, "gpsp")
    if damage == "bad_json":
        with path.open("a", encoding="utf-8") as target:
            target.write("INFO rfu_trace id=test side=gpsp {oops}\n")
    result = read_trace(path, "gpsp")
    assert result["issues"]
    if damage == "overflow":
        assert result["dropped"] == 3
        assert batches[-1]["first_dropped"] == 1


def test_cross_boundary_mismatch_is_not_a_game_verdict_or_clock_subtraction(tmp_path):
    h, g = MetadataTrace(clock=lambda: 1), MetadataTrace(clock=lambda: 99999)
    for stamp in (1, 2, 3):
        h.record("native_rx_admitted", kind="WT", timestamp=stamp)
        g.record("core_received", kind="WT", timestamp=stamp)
        g.record("core_enqueued", kind="WT", timestamp=stamp)
        g.record("core_dequeued", kind="WT", timestamp=stamp)
        h.record("native_tx_queued", kind="WT", timestamp=stamp if stamp != 2 else 9)
    host, guest = tmp_path / "host", tmp_path / "guest"
    hb, gb = [h.drain(final=True)], [g.drain(final=True)]
    save(host, hb, "switch")
    save(guest, gb, "gpsp")
    result = audit(host, guest)
    assert result["coverage"] == "TRACE_COMPLETE"
    assert result["functional_verdict"] == "NOT_ASSESSED"
    assert result["comparisons"][0]["identical"]
    assert result["comparisons"][2]["matched_prefix"] == 1
    gb[0]["source"]["files"]["switchtrade/rfu_trace.py"] = "0" * 64
    save(guest, gb, "gpsp")
    assert "source_mismatch" in audit(host, guest)["issues"]
    save(guest, gb, "gpsp", "another")
    assert "generation_mismatch" in audit(host, guest)["issues"]


def test_no_traffic_is_not_boundary_success_and_generation_selection_is_required(tmp_path):
    host, guest = tmp_path / "host", tmp_path / "guest"
    for path, side in ((host, "switch"), (guest, "gpsp")):
        save(path, [MetadataTrace().drain(final=True)], side)
    assert audit(host, guest)["boundary_verdict"] == "INSUFFICIENT_RFU_EVIDENCE"
    with guest.open("a", encoding="utf-8") as target:
        target.write(f"INFO rfu_trace id=second side=gpsp {json.dumps(MetadataTrace().drain(final=True))}\n")
    assert audit(host, guest)["coverage"] == "TRACE_INCOMPLETE"
    assert audit(host, guest, "test")["coverage"] == "TRACE_COMPLETE"


def test_complete_forwarding_and_drained_window_do_not_attest_native_progress(tmp_path):
    clock = [100.0]
    h, g = MetadataTrace(clock=lambda: clock[0]), MetadataTrace(clock=lambda: 999999)
    parent = native_metadata(gbaframe.wrap_parent_t(rfu.parent_uni_slot([bytes(14)]), 100), parent=True)
    receipt = native_metadata(gbaframe.build_k(1, 1, 100), parent=False)
    child = native_metadata(gbaframe.wrap_t(rfu.uni_slot(bytes(14)), 200), parent=False)

    def host_event(ms, event, **fields):
        clock[0] = 100 + ms / 1000
        h.record(event, **fields)

    host_event(0, "native_rx_admitted", reliable_seq=188, flags=7, **parent)
    g.record("core_received", **parent)
    host_event(160, "native_tx_queued", reliable_seq=56, flags=7, **receipt)
    host_event(167, "native_tx_attempt", reliable_seq=56, flags=7, app_position=1, **receipt)
    host_event(200, "native_tx_queued", reliable_seq=57, flags=7, **child)
    host_event(201, "native_tx_attempt", reliable_seq=57, flags=7, app_position=1, **child)
    host_event(300, "native_tx_attempt", reliable_seq=57, flags=7, app_position=1, **child)
    host_event(500, "native_window", send_low=58, next_out=58, inflight=0)
    for fields in (receipt, child):
        g.record("core_enqueued", **fields)
        g.record("core_dequeued", **fields)
    g.record("child_transfer", **child)
    clock[0] += 165
    host, guest = tmp_path / "host", tmp_path / "guest"
    hb = h.drain(final=True)
    save(host, [hb], "switch")
    save(guest, [g.drain(final=True)], "gpsp")
    before = host.read_bytes(), guest.read_bytes()
    result = audit(host, guest)
    assert result["coverage"] == "TRACE_COMPLETE"
    assert result["boundary_verdict"] == "MATCHED_CAPTURED_BOUNDARIES"
    assert result["functional_verdict"] == "NOT_ASSESSED"
    observed = result["native_envelope"]
    assert observed["status"] == "OBSERVED_NOT_NATIVE_VALIDATED"
    assert observed["wk_attempts"] == observed["wk_position_compared"] == 1
    assert observed["parent_timestamps_without_queued_receipt"] == 0
    assert observed["first_uni"] == {
        "parent_count": 1, "child_queued_count": 1,
        "parent_to_wk_attempt_ms": 167, "parent_to_child_attempt_ms": 201,
        "wk_to_child_attempt_ms": 34, "same_scheduled_datagram": False,
        "child_queue_to_window_release_ms": 300, "next_parent_after_ms": None,
        "observed_until_ms": 165500, "native_completion": "NOT_OBSERVED",
    }
    assert before == (host.read_bytes(), guest.read_bytes())
    missing_identity = read_trace(host, "switch")
    for entry in missing_identity["entries"]:
        if entry["event"] == "native_tx_queued" and entry.get("kind") == "WK":
            entry.pop("reliable_seq")
    unknown = native_envelope_observations(missing_identity)["first_uni"]
    assert unknown["parent_to_wk_attempt_ms"] is None
    assert unknown["same_scheduled_datagram"] is None
    hb["final"] = False
    save(host, [hb], "switch")
    assert audit(host, guest)["native_envelope"] == {"status": "INCONCLUSIVE"}
    assert audit(host, guest)["receipt_accounting"] == {"status": "INCONCLUSIVE"}


def test_receipt_accounting_distinguishes_policy_omissions_from_missing_callbacks_and_repeats():
    trace = MetadataTrace()
    def parent(stamp, slot_len=1, **fields):
        trace.record("core_received", kind="WT", timestamp=stamp, slot_len=slot_len, **fields)
    def queued(stamp, number):
        trace.record("core_enqueued", kind="WK", timestamp=stamp, receipt_seq=number)
    parent(1)
    queued(1, 1)
    parent(2, 3)
    trace.record("local_receipt", timestamp=2)  # eligible but not admitted by cadence
    parent(3, 3)  # no callback: NOT an eligible WK and not labelled a lost receipt
    parent(4)
    parent(4)
    trace.record("parent_repeat", timestamp=4, waiting=False)
    queued(4, 2)
    queued(4, 3)
    parent(5, 73, commands=[0] * 5)
    trace.record("local_receipt", timestamp=5)
    queued(5, 4)
    parent(3, 3)
    trace.record("parent_repeat", timestamp=3, waiting=True)
    entries = trace.drain(final=True)["entries"]
    before = deepcopy(entries)
    result = receipt_accounting(entries)
    assert entries == before
    assert result == {
        "status": "OBSERVED_RECEIPTS_NOT_ENQUEUED", "eligible": 5,
        "eligible_by_source": {"idle": 2, "callback": 2, "repeat": 1},
        "queued": 4, "matched": 4, "matched_by_source": {"idle": 2, "repeat": 1, "callback": 1},
        "eligible_without_enqueue": 1, "pre_uni_without_enqueue_at_end": 1,
        "queued_without_observed_eligibility": 0, "unknown_records": 0,
        "receipt_sequence_discontinuities": 0, "native_completion": "NOT_OBSERVED"}


@pytest.mark.parametrize("damage", ["timestamp", "slot_len", "receipt_seq", "eligibility"])
def test_receipt_accounting_unknown_or_unpaired_is_not_success(damage):
    entries = [dict(event="core_received", kind="WT", seq=1, timestamp=1, slot_len=1),
               dict(event="core_enqueued", kind="WK", seq=2, timestamp=1, receipt_seq=1)]
    assert receipt_accounting(entries)["status"] == "ALL_OBSERVED_RECEIPTS_ENQUEUED"
    if damage == "eligibility":
        entries.pop(0)
    else:
        entries[1 if damage == "receipt_seq" else 0][damage] = True
    entries[0]["payload"] = "PRIVATE"
    result = receipt_accounting(entries)
    assert result["status"] == "INCONCLUSIVE"
    assert "PRIVATE" not in json.dumps(result)
    assert receipt_accounting([])["status"] == "NO_RECEIPT_EVIDENCE"


def test_receipt_number_gap_does_not_hide_a_timestamp_hole():
    entries = [dict(event="core_received", kind="WT", seq=1, timestamp=1, slot_len=1),
               dict(event="core_received", kind="WT", seq=2, timestamp=2, slot_len=1),
               dict(event="core_enqueued", kind="WK", seq=3, timestamp=2, receipt_seq=2)]
    result = receipt_accounting(entries)
    assert result["eligible_without_enqueue"] == result["receipt_sequence_discontinuities"] == 1


def test_missing_receipt_position_is_unknown_and_sample_output_is_bounded():
    entries = [{"event": "native_rx_admitted", "kind": "WT", "timestamp": 1}]
    entries += [{"event": "native_tx_attempt", "kind": "WK", "message_index": 1,
                 "app_position": 2, "payload": "PRIVATE", "receipt_seq": i} for i in range(30)]
    entries += [{"event": "native_tx_attempt", "kind": "WK"},
                {"event": "native_tx_attempt", "kind": "WK", "message_index": True, "app_position": 1}]
    entries[1]["timestamp"] = "PRIVATE"
    result = native_envelope_observations({"entries": entries})
    assert result["wk_position_compared"] == result["wk_position_differences"] == 30
    assert result["wk_position_unknown"] == 2
    assert len(result["first_position_differences"]) == 8
    assert result["parent_timestamps_without_queued_receipt"] == 1
    assert "PRIVATE" not in json.dumps(result)
    assert result["first_uni"] is None
    assert native_envelope_observations({"entries": []}) == {"status": "NO_NATIVE_ATTEMPT_EVIDENCE"}


def test_read_only_cli_rejects_legacy_logs_without_trace(tmp_path):
    host, guest = tmp_path / "host.log", tmp_path / "guest.log"
    host.write_text("legacy snapshot only\n", encoding="utf-8")
    guest.write_text("legacy snapshot only\n", encoding="utf-8")
    before = (host.read_bytes(), guest.read_bytes())
    result = subprocess.run([sys.executable, "tools/audit_rfu_trace.py", str(host), str(guest)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["coverage"] == "TRACE_INCOMPLETE"
    assert report["boundary_verdict"] == "INCONCLUSIVE"
    assert all(x["identical"] is None for x in report["comparisons"])
    assert (host.read_bytes(), guest.read_bytes()) == before


def test_eight_lost_commands_cannot_hide_behind_three_bit_tag_alias(tmp_path):
    host, guest = tmp_path / "host", tmp_path / "guest"
    h, g = MetadataTrace(), MetadataTrace()
    for stamp in range(20):
        fields = {"kind": "WT", "timestamp": stamp, "commands": [0xBE00], "tag": stamp & 7}
        g.record("core_enqueued", **fields)
        g.record("core_dequeued", **fields)
        if not 5 <= stamp < 13:
            h.record("native_tx_queued", **fields)
    save(host, [h.drain(final=True)], "switch")
    save(guest, [g.drain(final=True)], "gpsp")
    comparison = audit(host, guest)["comparisons"][2]
    assert comparison["matched_prefix"] == 5
    assert comparison["counts"] == [20, 12]
    assert comparison["first_difference"]["from"]["tag"] == comparison["first_difference"]["to"]["tag"]


def test_qualified_uni_missing_before_core_enqueue_is_visible(tmp_path):
    host, guest = tmp_path / "host", tmp_path / "guest"
    h, g = MetadataTrace(), MetadataTrace()
    for stamp in (1, 2):
        g.record("child_transfer", timestamp=stamp, commands=[0], fragments=[0], tag=0)
    g.record("core_enqueued", kind="WT", timestamp=1, commands=[0], fragments=[0], tag=0)
    save(host, [h.drain(final=True)], "switch")
    save(guest, [g.drain(final=True)], "gpsp")
    result = audit(host, guest)
    assert result["coverage"] == "TRACE_COMPLETE"
    assert result["boundary_verdict"] == "DIVERGED"
    assert result["comparisons"][3]["counts"] == [2, 1]
    assert result["comparisons"][3]["first_difference"]["from"]["timestamp"] == 2


def test_native_metadata_never_includes_private_contents_and_preserves_retries():
    secret = b"PRIVATE-DATA"
    slot = rfu.uni_slot(b"\x20\xbe" + secret)
    payload = gbaframe.wrap_t(slot, 9)
    observer = NativeRfuProgress(parent=False)
    observer.window(2, 2, 0)
    observer.window(2, 2, 0)
    observer.observe(payload, 2, 7, received=False)
    for _ in range(3):
        observer.scheduled([(2, 7, payload)], 3)
    batch = observer.trace.drain(final=True)
    assert [e["event"] for e in batch["entries"]] == ["native_window", "native_tx_queued"] + ["native_tx_attempt"] * 3
    assert all(e["commands"] == [0xBE00] and e["tag"] == 1 for e in batch["entries"][1:])
    output = json.dumps(batch)
    assert "PRIVATE" not in output and secret.hex() not in output
    assert native_metadata(secret, parent=False) == {"kind": "other", "bytes": len(secret)}
    assert native_metadata(payload[:-1], parent=False)["kind"] == "other"


@pytest.mark.parametrize("first", ["seal", "fail", "close"])
def test_cleanup_does_not_replace_pre_clear_evidence(first):
    async def exercise():
        adapter = CoreTunnelAdapter("test", "switchtrade.gba-frame.v1")
        await adapter.deliver_from_core(LinkPacket("test", "switchtrade.gba-frame.v1", b"PRIVATE", 7))
        adapter.send_rfu(b"PRIVATE", flags=7)
        if first == "fail":
            adapter.fail(RuntimeError("first"))
        else:
            getattr(adapter, first)()
        adapter.seal()
        adapter.close()
        assert adapter.poll() == []
        status = adapter.flow_status()
        assert status["core_to_local_queue"] == status["local_to_core_queue"] == 0
        assert status["pre_clear"] == {"reason": first, "core_to_local_queue": 1, "local_to_core_queue": 1}
        status["pre_clear"]["reason"] = "changed"
        assert adapter.flow_status()["pre_clear"]["reason"] == first
    asyncio.run(exercise())
