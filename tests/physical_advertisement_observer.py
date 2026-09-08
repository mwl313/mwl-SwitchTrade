"""Opt-in, scan-only physical diagnosis. Never joins a room or starts a Pair.

Private output contains only the selected trainer's decoded 24-byte RFU record,
not keys, MACs, IPs, complete advertisements, game traffic, ROMs or saves.
Run behind the existing source-verified radio gate, with the user's permission.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import trio

from switchtrade.connection.a_stage import AStageError, DirectAStage, GATES, room_mismatches
from switchtrade.connection.resource_scope import cancelled
from switchtrade.connection.stage_session import StageSession
from switchtrade.endpoints.retroarch_gpsp.rfu import _advertisement_record


def selected_record(networks, trainer_name, diagnostics=None):
    from frlgsim.beacon import encode_frlg_name

    # EOS terminates the name; bytes after it can be zero-filled, not only FF.
    expected = encode_frlg_name(trainer_name).split(b"\xff", 1)[0] + b"\xff"
    matches = []
    counts = {"networks": 0, "compatible_rooms": 0, "selected_matches": 0,
              "other_trainers": 0, "rejected_conditions": {}}
    if diagnostics is not None:
        diagnostics.update(counts)
        counts = diagnostics
    for network in networks:
        counts["networks"] += 1
        mismatches = room_mismatches(network)
        for reason in mismatches:
            rejected = counts["rejected_conditions"]
            rejected[reason] = rejected.get(reason, 0) + 1
        if mismatches:
            continue
        counts["compatible_rooms"] += 1
        record = _advertisement_record(network.application_data)
        if record[2:10].startswith(expected):
            matches.append(record)
            counts["selected_matches"] += 1
        else:
            counts["other_trainers"] += 1
    if len(matches) > 1:
        raise AStageError("A_ROOM_AMBIGUOUS", GATES[2], "multiple matching trainers")
    return matches[0] if matches else None


class ScanOnlyStage(DirectAStage):
    """Reuse production preflight, scanner and ownership; no station admission."""

    trainer_name = ""

    async def _run_stage(self):
        import ldn
        self.ldn, self.trio = ldn, trio
        self.scan_diagnostics = {"completed": False}
        try:
            keys = self._preflight()
            with trio.fail_after(self.scan_timeout):
                networks = await self._scan(keys)
            self.scan_diagnostics["completed"] = True
            record = selected_record(networks, self.trainer_name, self.scan_diagnostics)
            return {"status": "observed" if record else "not_observed", "failure": None}, record
        except BaseException as error:
            code = getattr(error, "code", None) or (
                "A_CANCELLED" if cancelled(error) or isinstance(error, KeyboardInterrupt)
                else "A_SCAN_TIMEOUT" if isinstance(error, trio.TooSlowError) else "A_STAGE_INTERNAL")
            return self._failure(AStageError(code, GATES[1], "scan-only diagnosis stopped")), None


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-private", action="store_true", required=True)
    parser.add_argument("--trainer-name", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--usb-id", required=True)
    parser.add_argument("--channel", type=int, choices=(1, 6, 11), default=6)
    parser.add_argument("--cancel-check", action="store_true")
    parser.add_argument("--samples", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    if (not args.output.is_absolute() or not args.output.parent.is_dir()
            or not args.trainer_name.isascii() or not args.trainer_name.isalnum()
            or not 1 <= len(args.trainer_name) <= 7):
        parser.error("require a new absolute private output directory and exact 1-7 character trainer name")
    from switchtrade.core_cli import _policy
    args.command = "host"
    policy = _policy(args)  # USB/channel/RX/PHY/profile binding; never guess an interface.
    if policy.release == "development":
        parser.error("source-verified release identity required")
    args.output.mkdir(mode=0o700, exist_ok=False)
    print("scan_only: no Pair, station join, AP, game traffic or VM", flush=True)
    for index in range(args.samples):
        stage = ScanOnlyStage(run_id=policy.run_id, release=policy.release, phy=policy.phy,
                     ifname=policy.ifname, keys_path=policy.keys_path,
                     dwell_time=5 if args.cancel_check else 1)
        stage.trainer_name = args.trainer_name
        record = None
        stop_error = None
        if args.cancel_check:
            session = StageSession(stage).start()
            try:
                deadline = time.monotonic() + 6
                while stage.resources.states.get("scan.vif.6") != "acquired":
                    if session.ended or time.monotonic() >= deadline:
                        raise RuntimeError("SCAN_MONITOR_NOT_READY")
                    time.sleep(.01)
                print("scan_monitor_acquired: requesting owned StageSession.stop", flush=True)
            finally:
                try:
                    session.stop()
                except BaseException as error:
                    stop_error = type(error).__name__
            report = session.report or {"failure": {"code": "SCAN_REPORT_MISSING"}, "cleanup": {}}
        else:
            report, record = trio.run(stage.run)
        clean = report.get("cleanup", {}).get("ldn_context_released") is True and not stop_error
        summary = {"label": args.label, "sample": index, "cleanup": report.get("cleanup"),
                   "failure": (report.get("failure") or {}).get("code"),
                   "cleanup_error": stop_error, "observed": record is not None,
                   "source": policy.release, "utc": datetime.now(timezone.utc).isoformat(),
                   "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        summary["scan"] = getattr(stage, "scan_diagnostics", {"completed": False})
        write_private(args.output / f"sample-{index}.json",
                      {**summary, "record_hex": record.hex() if record is not None else None})
        print(json.dumps(summary, sort_keys=True), flush=True)
        if not clean or summary["failure"] and not (
                args.cancel_check and summary["failure"] == "A_CANCELLED"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
