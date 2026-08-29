"""PID-preserving installed-runtime endpoint for the direct B2-B10 harness."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .b_stage import BStageError, DirectBStage, quiesce_selected_phy
from .p0 import atomic_json
from .radio_worker import process_start_ticks


def _emit(event: str, **value: object) -> None:
    print(json.dumps({"event": event, **value}, sort_keys=True, separators=(",", ":")), flush=True)


def run(args: argparse.Namespace) -> int:
    actual_ticks = process_start_ticks()
    if actual_ticks != args.process_start_ticks:
        _emit(
            "b_stage_failed", code="B_ENDPOINT_IDENTITY_MISMATCH",
            gate="B2_ADVERTISEMENT_VALIDATION", message="endpoint process identity changed",
        )
        return 2
    _emit(
        "endpoint_started",
        run_id=args.run_id,
        release=args.release,
        launch_nonce=args.launch_nonce,
        endpoint_pid=os.getpid(),
        process_start_ticks=actual_ticks,
        endpoint="direct_b",
    )

    import trio

    def gate_sink(value: dict) -> None:
        _emit(
            "b_gate_passed", run_id=args.run_id, launch_nonce=args.launch_nonce,
            gate=value["gate"], elapsed_ms=value["elapsed_ms"],
        )

    stage = DirectBStage(
        run_id=args.run_id,
        release=args.release,
        phy=args.phy,
        keys_path=args.keys,
        ap_ifname=args.ap_ifname,
        monitor_ifname=args.monitor_ifname,
        tap_ifname=args.tap_ifname,
        gate_sink=gate_sink,
        channel=args.channel,
        ap_timeout=args.ap_timeout,
        association_timeout=args.association_timeout,
        control_timeout=args.control_timeout,
        hold_seconds=args.hold_seconds,
        teardown_timeout=args.teardown_timeout,
    )
    report = trio.run(stage.run)
    try:
        quiesce_selected_phy(args.phy, args.tap_ifname)
        report["cleanup"]["radio_quiescent"] = True
    except BStageError:
        report["cleanup"]["radio_quiescent"] = False
    atomic_json(args.report, report)

    if report["status"] != "passed":
        failure = report["failure"]
        _emit(
            "b_stage_failed", run_id=args.run_id, launch_nonce=args.launch_nonce,
            report=report, code=failure["code"], gate=failure["gate"],
            message=failure["message"],
        )
        return 2
    _emit(
        "b_stage_ready", run_id=args.run_id, launch_nonce=args.launch_nonce,
        report=report,
    )
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="SwitchTrade direct B2-B10 endpoint")
    value.add_argument("--run-id", required=True)
    value.add_argument("--release", required=True)
    value.add_argument("--launch-nonce", required=True)
    value.add_argument("--process-start-ticks", type=int, required=True)
    value.add_argument("--phy", required=True)
    value.add_argument("--ap-ifname", required=True)
    value.add_argument("--monitor-ifname", required=True)
    value.add_argument("--tap-ifname", required=True)
    value.add_argument("--keys", type=Path, required=True)
    value.add_argument("--report", type=Path, required=True)
    value.add_argument("--channel", type=int, default=6)
    value.add_argument("--ap-timeout", type=float, default=45)
    value.add_argument("--association-timeout", type=float, default=120)
    value.add_argument("--control-timeout", type=float, default=10)
    value.add_argument("--hold-seconds", type=float, default=5)
    value.add_argument("--teardown-timeout", type=float, default=10)
    return value


def main() -> None:
    raise SystemExit(run(parser().parse_args()))


if __name__ == "__main__":
    main()
