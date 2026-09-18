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
    elapsed_ms = None
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
                elapsed_ms = previous_ms
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
            "entries": entries, "source": source, "observed": observed, "dropped": dropped,
            "elapsed_ms": elapsed_ms}


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


def native_envelope_observations(trace):
    """Host-clock metadata only; gold correlations are not receiver rules.

    App position resets at each scheduled datagram, including retransmits.
    Nothing here manufactures a next parent frame or infers game consumption
    from a released Reliable window. Unknown metadata is not a matching layout.
    """
    entries = trace["entries"]
    attempts = [e for e in entries if e["event"] == "native_tx_attempt"]
    if not attempts:
        return {"status": "NO_NATIVE_ATTEMPT_EVIDENCE"}
    wk = [e for e in attempts if e.get("kind") == "WK"]
    positioned = [e for e in wk if all(type(e.get(k)) is int and e[k] > 0
                                      for k in ("message_index", "app_position"))]
    differences = [e for e in positioned if e["message_index"] != e["app_position"]]
    fields = ("seq", "elapsed_ms", "reliable_seq", "receipt_seq", "timestamp",
              "message_index", "app_position")
    parent = [e for e in entries if e["event"] == "native_rx_admitted" and e.get("kind") == "WT"]
    receipts = [e for e in entries if e["event"] == "native_tx_queued" and e.get("kind") == "WK"]
    stamps = lambda items: {e["timestamp"] for e in items if type(e.get("timestamp")) is int}
    result = {
        "status": "OBSERVED_NOT_NATIVE_VALIDATED",
        "wk_attempts": len(wk), "wk_position_compared": len(positioned),
        "wk_position_unknown": len(wk) - len(positioned),
        "wk_position_differences": len(differences),
        "first_position_differences": [
            {k: e[k] for k in fields if type(e.get(k)) in (int, float) and valid_time(e[k])}
            for e in differences[:8]],
        "parent_timestamps_observed": len(stamps(parent)),
        "receipt_timestamps_queued": len(stamps(receipts)),
        "parent_timestamps_without_queued_receipt": len(stamps(parent) - stamps(receipts)),
        "first_uni": None,
    }
    is_uni = lambda e: e.get("kind") == "WT" and isinstance(e.get("commands"), list) and bool(e["commands"])
    parents = [e for e in parent if is_uni(e)]
    if not parents:
        return result
    first = parents[0]
    after = [e for e in entries if e["seq"] > first["seq"]]
    receipt = next((e for e in after if e["event"] == "native_tx_queued" and
                    e.get("kind") == "WK" and e.get("timestamp") == first.get("timestamp")), None)
    child = next((e for e in after if e["event"] == "native_tx_queued" and is_uni(e)), None)

    def first_attempt(queued):
        if queued is None or type(queued.get("reliable_seq")) is not int:
            return None
        return next((e for e in attempts if e["seq"] > queued["seq"] and
                     e.get("reliable_seq") == queued.get("reliable_seq") and
                     signature(e) == signature(queued)), None)

    wk_attempt, wt_attempt = first_attempt(receipt), first_attempt(child)
    groups, group = {}, 0
    for e in attempts:
        if e.get("app_position") == 1:
            group += 1
        if group and type(e.get("app_position")) is int and e["app_position"] > 0:
            groups[e["seq"]] = group
    same_group = None
    if wk_attempt and wt_attempt and all(e["seq"] in groups for e in (wk_attempt, wt_attempt)):
        same_group = groups[wk_attempt["seq"]] == groups[wt_attempt["seq"]]
    release = None
    if wt_attempt and type(wt_attempt.get("reliable_seq")) is int:
        release = next((e for e in after if e["event"] == "native_window" and
                        e["seq"] > wt_attempt["seq"] and type(e.get("send_low")) is int and
                        0 < (e["send_low"] - wt_attempt["reliable_seq"]) % 65536 < 32768), None)
    delta = lambda a, b: round(b["elapsed_ms"] - a["elapsed_ms"], 3) if a and b else None
    result["first_uni"] = {
        "parent_count": len(parents),
        "child_queued_count": sum(e["event"] == "native_tx_queued" and is_uni(e) for e in after),
        "parent_to_wk_attempt_ms": delta(first, wk_attempt),
        "parent_to_child_attempt_ms": delta(first, wt_attempt),
        "wk_to_child_attempt_ms": delta(wk_attempt, wt_attempt),
        "same_scheduled_datagram": same_group,
        "child_queue_to_window_release_ms": delta(child, release),
        "next_parent_after_ms": delta(first, parents[1]) if len(parents) > 1 else None,
        "observed_until_ms": (round(trace["elapsed_ms"] - first["elapsed_ms"], 3)
                              if valid_time(trace.get("elapsed_ms")) else None),
        "native_completion": "NOT_OBSERVED",
    }
    return result


def receipt_accounting(entries):
    """Guest-clock receipts BEFORE cadence versus WK admitted AFTER cadence.

    Idle WT needs no frontend callback. Non-idle WT becomes eligible only on
    local_receipt; a known repeated WT can reissue a receipt when not waiting.
    This deliberately does not infer eligibility from mere transport delivery,
    a drained queue, or an absent callback. Call only after coverage validation.
    """
    seen, pending = set(), defaultdict(deque)
    sources, matched = Counter(), Counter()
    unknown = unpaired = queued = 0
    first_uni = None
    number = 0
    sequence_gaps = 0
    uint32 = lambda v: type(v) is int and 0 < v <= 0xFFFFFFFF
    for e in entries:
        event, stamp = e["event"], e.get("timestamp")
        reason = None
        if event == "core_received" and e.get("kind") == "WT":
            if not uint32(stamp) or type(e.get("slot_len")) is not int or not 0 <= e["slot_len"] <= 92:
                unknown += 1
                continue
            if first_uni is None and isinstance(e.get("commands"), list) and e["commands"]:
                first_uni = e["seq"]
            if stamp not in seen and e["slot_len"] <= 1:
                reason = "idle"
            seen.add(stamp)
        elif event == "local_receipt":
            reason = "callback"
        elif event == "parent_repeat":
            if type(e.get("waiting")) is not bool:
                unknown += 1
            elif not e["waiting"]:
                reason = "repeat"
        if reason:
            if not uint32(stamp) or stamp not in seen:
                unknown += 1
                continue
            sources[reason] += 1
            pending[stamp].append((e["seq"], reason))
        if event == "core_enqueued" and e.get("kind") == "WK":
            queued += 1
            if not uint32(stamp) or not uint32(e.get("receipt_seq")):
                unknown += 1
                continue
            sequence_gaps += e["receipt_seq"] != number % 0xFFFFFFFF + 1
            number = e["receipt_seq"]
            if pending[stamp]:
                _, reason = pending[stamp].popleft()
                matched[reason] += 1
            else:
                unpaired += 1
    missing = sum(map(len, pending.values()))
    status = ("INCONCLUSIVE" if unknown or unpaired else
              "NO_RECEIPT_EVIDENCE" if not sources else
              "OBSERVED_RECEIPTS_NOT_ENQUEUED" if missing else "ALL_OBSERVED_RECEIPTS_ENQUEUED")
    return {"status": status, "eligible": sum(sources.values()), "eligible_by_source": dict(sources),
            "queued": queued, "matched": sum(matched.values()), "matched_by_source": dict(matched),
            "eligible_without_enqueue": missing,
            "pre_uni_without_enqueue_at_end": (None if first_uni is None else
                sum(seq < first_uni for queue in pending.values() for seq, _ in queue)),
            "queued_without_observed_eligibility": unpaired, "unknown_records": unknown,
            "receipt_sequence_discontinuities": sequence_gaps,
            "native_completion": "NOT_OBSERVED"}


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
            "native_envelope": ({"status": "INCONCLUSIVE"} if issues else native_envelope_observations(h)),
            "receipt_accounting": ({"status": "INCONCLUSIVE"} if issues else receipt_accounting(g["entries"])),
            "event_counts": {side: dict(Counter(x.get("event") for x in data["entries"]))
                             for side, data in (("switch", h), ("gpsp", g))},
            "limits": ["Metadata identities only; payload integrity and game consumption are not proven.",
                       "A missing boundary event may be cancellation/cleanup, not the initiating fault.",
                       "WK position and missing receipts are observations, not proven native receiver violations.",
                       "Receipt accounting includes pre-cadence eligibility; missing enqueue is not RF loss or proof of the initiating fault.",
                       "Reliable window release does not establish RFU completion or next-parent progress.",
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
