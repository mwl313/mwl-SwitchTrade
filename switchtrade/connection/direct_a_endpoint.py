"""PID-preserving installed-runtime endpoint for the direct A0-A9 harness."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from .a_stage import DirectAStage
from .p0 import atomic_json
from .radio_worker import (
    RadioWorkerError, process_start_ticks, quiesce_selected_radio,
)


def _emit(event: str, **value: object) -> None:
    print(json.dumps({"event": event, **value}, sort_keys=True, separators=(",", ":")), flush=True)


def run(args: argparse.Namespace) -> int:
    actual_ticks = process_start_ticks()
    if actual_ticks != args.process_start_ticks:
        _emit(
            "a_stage_failed", code="A_ENDPOINT_IDENTITY_MISMATCH",
            gate="A0_SCAN_PREPARATION", message="endpoint process identity changed",
        )
        return 2
    _emit(
        "endpoint_started",
        run_id=args.run_id,
        release=args.release,
        launch_nonce=args.launch_nonce,
        endpoint_pid=os.getpid(),
        process_start_ticks=actual_ticks,
        endpoint="direct_a",
    )

    import trio

    def gate_sink(value: dict) -> None:
        _emit(
            "a_gate_passed", run_id=args.run_id, launch_nonce=args.launch_nonce,
            gate=value["gate"], elapsed_ms=value["elapsed_ms"],
        )

    stage = DirectAStage(
        run_id=args.run_id,
        release=args.release,
        phy=args.phy,
        ifname=args.ifname,
        keys_path=args.keys,
        gate_sink=gate_sink,
        scan_timeout=args.scan_timeout,
        join_timeout=args.join_timeout,
        hold_seconds=args.hold_seconds,
        dwell_time=args.dwell_time,
    )
    report, advertisement = trio.run(stage.run)
    try:
        quiesce_selected_radio()
        report["cleanup"] = {"ldn_context_released": True, "radio_quiescent": True}
    except RadioWorkerError as error:
        report["status"] = "failed"
        report["failure"] = {
            "code": "A_RADIO_QUIESCE_FAILED",
            "gate": "A9_DATA_PLANE",
            "message": "selected radio did not become quiescent",
        }
        report["cleanup"] = {"ldn_context_released": True, "radio_quiescent": False}
        advertisement = None
    atomic_json(args.report, report)

    if report["status"] != "passed" or advertisement is None:
        failure = report["failure"]
        _emit(
            "a_stage_failed",
            run_id=args.run_id,
            launch_nonce=args.launch_nonce,
            report=report,
            code=failure["code"],
            gate=failure["gate"],
            message=failure["message"],
        )
        return 2
    _emit(
        "a_stage_ready",
        run_id=args.run_id,
        launch_nonce=args.launch_nonce,
        report=report,
        advertisement_b64=base64.b64encode(advertisement).decode("ascii"),
    )
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="SwitchTrade direct A0-A9 endpoint")
    value.add_argument("--run-id", required=True)
    value.add_argument("--release", required=True)
    value.add_argument("--launch-nonce", required=True)
    value.add_argument("--process-start-ticks", type=int, required=True)
    value.add_argument("--phy", required=True)
    value.add_argument("--ifname", required=True)
    value.add_argument("--keys", type=Path, required=True)
    value.add_argument("--report", type=Path, required=True)
    value.add_argument("--scan-timeout", type=float, default=8)
    value.add_argument("--join-timeout", type=float, default=15)
    value.add_argument("--hold-seconds", type=float, default=5)
    value.add_argument("--dwell-time", type=float, default=1)
    return value


def main() -> None:
    raise SystemExit(run(parser().parse_args()))


if __name__ == "__main__":
    main()
