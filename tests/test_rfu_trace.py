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
from tools.audit_rfu_trace import audit, read_trace


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
