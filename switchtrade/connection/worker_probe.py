"""PID-preserving endpoint canary for Milestone 2 worker qualification only."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .radio_worker import RadioWorkerError, quiesce_selected_radio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--launch-nonce", required=True)
    parser.add_argument("--process-start-ticks", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps({
        "event": "endpoint_started",
        "run_id": args.run_id,
        "release": args.release,
        "launch_nonce": args.launch_nonce,
        "endpoint_pid": os.getpid(),
        "process_start_ticks": args.process_start_ticks,
        "endpoint": "probe",
    }, sort_keys=True, separators=(",", ":")), flush=True)
    # The control-owned stdin pipe is the lifetime boundary for this canary, just as it will be
    # for the direct A/B endpoints. No timer or second cleanup owner is introduced here.
    sys.stdin.readline()
    try:
        quiesce_selected_radio()
    except RadioWorkerError as error:
        print(json.dumps({
            "event": "endpoint_cleanup_failed", "code": error.code,
            "message": error.message,
        }, sort_keys=True, separators=(",", ":")), flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
