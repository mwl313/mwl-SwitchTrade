"""Offline audit of *complete* opt-in Host/VM logs. No device/network access.

Checks evidence coverage before comparing boundary identities. A matched trace
is NOT proof of radio delivery, gpSP buffer admission, game consumption or trade.
Never compare wall clocks between machines; elapsed times are local to a stream.
"""
import argparse
from collections import Counter, defaultdict, deque
import json
import math
from pathlib import Path
import re


LINE = re.compile(r"rfu_trace id=([a-zA-Z0-9_-]+) side=(switch|gpsp) (\{.*\})$")


def valid_time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def read_trace(path, side, generation=None):
    issues, streams, generations = [], {}, set()
    with Path(path).open(encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if "rfu_trace id=" not in line:
                continue
            match = LINE.search(line.rstrip())
            if match is None:
                issues.append("malformed_trace_line")
                continue
            gid, observed_side, raw = match.groups()
            if observed_side != side or (generation is not None and gid != generation):
                continue
            generations.add(gid)
            try:
                batch = json.loads(raw)
                if not isinstance(batch, dict) or not isinstance(batch.get("stream"), str):
                    raise ValueError("invalid stream")
                stream = streams.setdefault((gid, batch["stream"]), [])
                stream.append(batch)
            except (ValueError, KeyError, TypeError):
                issues.append("invalid_trace_json")
    if len(generations) != 1 or len(streams) != 1:
        issues.append("select_exactly_one_generation_and_stream")
    entries, source, final = [], None, False
    observed = dropped = 0
    for batches in streams.values():
        previous_seq, previous_ms = 0, -1
        for number, batch in enumerate(batches, 1):
            try:
                if (any(type(batch[key]) is not int or batch[key] < 0
                        for key in ("schema", "batch", "observed", "dropped"))
                        or type(batch["final"]) is not bool or not valid_time(batch["elapsed_ms"])
                        or not isinstance(batch["entries"], list)):
                    raise ValueError("invalid batch")
                if batch["schema"] != 1 or batch["batch"] != number or final:
                    issues.append("batch_gap_duplicate_or_after_final")
                if number == 1:
                    source = batch.get("source")
                if batch["dropped"]:
                    issues.append("observer_overflow")
                dropped = max(dropped, batch["dropped"])
                for entry in batch["entries"]:
                    if (not isinstance(entry, dict) or not isinstance(entry.get("event"), str)
                            or type(entry.get("seq")) is not int or entry["seq"] < 1
                            or not valid_time(entry.get("elapsed_ms"))):
                        raise ValueError("invalid event")
                    if entry["seq"] != previous_seq + 1 or entry["elapsed_ms"] < previous_ms:
                        issues.append("event_gap_or_time_reversal")
                    previous_seq, previous_ms = entry["seq"], entry["elapsed_ms"]
                    entries.append(entry)
                observed = batch["observed"]
                if observed != previous_seq or batch["elapsed_ms"] < previous_ms:
                    issues.append("observation_count_or_time_mismatch")
                previous_ms = batch["elapsed_ms"]
                final = batch["final"] is True
            except (KeyError, TypeError, ValueError):
                issues.append("invalid_batch_fields")
    if not final:
        issues.append("missing_final_flush")
    if not isinstance(source, dict) or not isinstance(source.get("files"), dict):
        source = None
    files = (source or {}).get("files", {})
    if len(files) != 9 or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in files.values()):
        issues.append("source_identity_unavailable")
    return {"issues": sorted(set(issues)), "generations": sorted(generations),
            "entries": entries, "source": source, "observed": observed, "dropped": dropped}


def signature(entry, *, uni=False):
    keys = (("timestamp", "commands", "fragments", "tag") if uni else
            ("kind", "bytes", "timestamp", "slot_len", "commands", "fragments", "tag", "receipt_seq", "message_index"))
    return {key: entry[key] for key in keys if key in entry}


def compare(left, left_event, right, right_event, *, uni=False):
    def selected(x, event):
        return x["event"] == event and ("commands" in x if uni else x.get("kind") in ("WT", "WK"))
    a = [x for x in left if selected(x, left_event)]
    b = [x for x in right if selected(x, right_event)]
    prefix = 0
    for x, y in zip(a, b):
        if signature(x, uni=uni) != signature(y, uni=uni):
            break
        prefix += 1
    return {"from": left_event, "to": right_event, "qualified_uni_only": uni, "counts": [len(a), len(b)],
            "matched_prefix": prefix, "identical": prefix == len(a) == len(b) if a or b else None,
            "first_difference": None if prefix == len(a) == len(b) else {
                "from": signature(a[prefix], uni=uni) if prefix < len(a) else None,
                "to": signature(b[prefix], uni=uni) if prefix < len(b) else None}}


def local_delays(entries):
    # Retried timestamps can reappear. FIFO pairing of observations avoids
    # interpreting a retry as a new original packet or subtracting PC clocks.
    result = {}
    for first, last, key in (("parent_transfer", "local_delivery", "timestamp"),
                             ("local_delivery", "local_receipt", "timestamp"),
                             ("core_enqueued", "core_dequeued", "ordinal"),
                             ("local_write_begin", "local_write_returned", "ordinal")):
        pending, delays = defaultdict(deque), []
        for item in entries:
            stamp = item.get(key)
            if item["event"] == first:
                pending[stamp].append(item["elapsed_ms"])
            elif item["event"] == last and pending[stamp]:
                delays.append(item["elapsed_ms"] - pending[stamp].popleft())
        result[first + "_to_" + last] = {"pairs": len(delays), "unmatched": sum(map(len, pending.values())),
                                         "max_ms": round(max(delays), 3) if delays else None}
    return result


def audit(host, guest, generation=None):
    h, g = read_trace(host, "switch", generation), read_trace(guest, "gpsp", generation)
    issues = [f"{side}:{issue}" for side, data in (("switch", h), ("gpsp", g)) for issue in data["issues"]]
    if h["generations"] != g["generations"]:
        issues.append("generation_mismatch")
    if (h["source"] or {}).get("files") != (g["source"] or {}).get("files"):
        issues.append("source_mismatch")
    comparisons = [compare(h["entries"], "native_rx_admitted", g["entries"], "core_received"),
                   compare(g["entries"], "core_enqueued", g["entries"], "core_dequeued"),
                   compare(g["entries"], "core_dequeued", h["entries"], "native_tx_queued"),
                   compare(g["entries"], "child_transfer", g["entries"], "core_enqueued", uni=True)]
    boundary = ("DIVERGED" if any(x["identical"] is False for x in comparisons)
                else "INSUFFICIENT_RFU_EVIDENCE" if any(not all(x["counts"]) for x in comparisons)
                else "MATCHED_CAPTURED_BOUNDARIES")
    return {"coverage": "TRACE_INCOMPLETE" if issues else "TRACE_COMPLETE",
            "boundary_verdict": boundary if not issues else "INCONCLUSIVE",
            "issues": issues, "functional_verdict": "NOT_ASSESSED",
            "comparisons": comparisons, "gpsp_local_delays": local_delays(g["entries"]),
            "event_counts": {side: dict(Counter(x.get("event") for x in data["entries"]))
                             for side, data in (("switch", h), ("gpsp", g))},
            "limits": ["Metadata identities only; payload integrity and game consumption are not proven.",
                       "A missing boundary event may be cancellation/cleanup, not the initiating fault.",
                       "Do not subtract elapsed or wall times across machines.",
                       "Git SHA/overlay identity and user action timeline must be checked separately."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", type=Path)
    parser.add_argument("guest", type=Path)
    parser.add_argument("--generation")
    args = parser.parse_args()
    try:
        result = audit(args.host, args.guest, args.generation)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"coverage": "TRACE_INCOMPLETE", "error": type(error).__name__}))
        return 2
    print(json.dumps(result, indent=2))
    if result["coverage"] != "TRACE_COMPLETE" or result["boundary_verdict"] == "INSUFFICIENT_RFU_EVIDENCE":
        return 2
    return 0 if result["boundary_verdict"] == "MATCHED_CAPTURED_BOUNDARIES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
