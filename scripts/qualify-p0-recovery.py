#!/usr/bin/env python3
"""Installed-runtime endpoint-hang and restart qualification using the production P0 path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from switchtrade.connection.coordinator import ConnectionCoordinator  # noqa: E402
from switchtrade.connection.d_probes import WslDProbes  # noqa: E402
from switchtrade.connection.p0 import PassiveValidator, atomic_json, run_command  # noqa: E402
from switchtrade.connection.p0_harness import P0Harness, _installed_release  # noqa: E402
from switchtrade.diagnostics import default_runs_root  # noqa: E402
from switchtrade.relay_client import RelayClient  # noqa: E402


PACKAGED_PYTHON = "/opt/switchtrade/bridge/.venv/bin/python"


def _harness(args, coordinator, *, checkpoint=None) -> P0Harness:
    release = _installed_release(args.runtime_root, args.distro)
    relay = RelayClient(args.relay_url)
    validator = PassiveValidator(
        release=release,
        selection_file=args.selection_file,
        relay_health=relay.health,
        relay_websocket_health=relay.websocket_health,
        distro=args.distro,
        runtime_root=args.runtime_root,
        target_channel=args.target_channel,
        blocking_state_paths=(
            default_runs_root().parent / "runtime" / "production-diagnostic-recovery.json",
        ),
    )
    probes = WslDProbes(distro=args.distro, packaged_python=PACKAGED_PYTHON)
    return P0Harness(
        coordinator,
        validator,
        args.state_root / "runs",
        distro=args.distro,
        runtime_root=args.runtime_root,
        packaged_python=PACKAGED_PYTHON,
        target_channel=args.target_channel,
        release_probes=probes,
        after_endpoint_started=checkpoint,
    )


def _signal_exact(
    probes: WslDProbes, distro: str, pid: int, expected_ticks: int, name: str,
) -> bool:
    if probes.process_start_ticks(pid) != expected_ticks:
        return False
    result = run_command([
        "wsl.exe", "-d", distro, "-u", "root", "--", "kill", f"-{name}", str(pid),
    ], 5)
    return result.returncode == 0


def _spawn_hung_child(distro: str, run_id: str, probes: WslDProbes) -> tuple[int, int]:
    child = (
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(600)"
    )
    parent = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "start_new_session=True,close_fds=True); print(p.pid,flush=True)"
    )
    result = run_command([
        "wsl.exe", "-d", distro, "-u", "root", "--", PACKAGED_PYTHON,
        "-c", parent, child, run_id,
    ], 5)
    if result.returncode != 0:
        raise RuntimeError("the installed hang fixture could not be launched")
    try:
        pid = int(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError("the installed hang fixture returned an invalid PID") from error
    ticks = probes.process_start_ticks(pid)
    if ticks is None:
        raise RuntimeError("the installed hang fixture exited before measurement")
    return pid, ticks


def endpoint_hang(args) -> dict:
    held: dict = {}
    probes = WslDProbes(distro=args.distro, packaged_python=PACKAGED_PYTHON)

    def checkpoint(run: dict) -> None:
        pid, ticks = _spawn_hung_child(args.distro, run["run_id"], probes)
        held.update(pid=pid, ticks=ticks)

    with ConnectionCoordinator(args.state_root / "coordinator", _installed_release(
            args.runtime_root, args.distro)) as coordinator:
        harness = _harness(args, coordinator, checkpoint=checkpoint)
        initial = None
        try:
            initial = harness.run()
        finally:
            if held:
                _signal_exact(
                    probes, args.distro, held["pid"], held["ticks"], "KILL")
        snapshot = coordinator.snapshot()
        recovered = harness.recover(snapshot)

    initial_report = initial or {}
    d_release = initial_report.get("cleanup", {}).get("d_release", {})
    passed = all((
        initial is not None,
        initial_report.get("cleanup_status") == "failed",
        d_release.get("endpoint_identity_absent") is False,
        "usb" not in initial_report.get("cleanup", {}),
        recovered.get("status") == "recovered",
        recovered.get("cleanup", {}).get("verified") is True,
    ))
    report = {
        "contract_version": "p0-recovery-qualification.v1",
        "mode": "endpoint_hang",
        "status": "passed" if passed else "failed",
        "run_id": initial_report.get("run_id"),
        "endpoint_hang_blocked_usb_return": d_release.get("endpoint_identity_absent") is False and
        "usb" not in initial_report.get("cleanup", {}),
        "recovery_verified": recovered.get("cleanup", {}).get("verified") is True,
    }
    atomic_json(args.state_root / "endpoint-hang-qualification.json", report)
    return report


def prepare_reboot(args) -> None:
    marker = args.state_root / "reboot-checkpoint.json"

    def checkpoint(run: dict) -> None:
        identity = run["identity"]
        atomic_json(marker, {
            "contract_version": "p0-reboot-checkpoint.v1",
            "status": "awaiting_reboot",
            "run_id": run["run_id"],
            "endpoint_pid": identity["endpoint_pid"],
            "endpoint_start_ticks": identity["endpoint_start_ticks"],
            "control_pid": os.getpid(),
        }, private=True)
        print(json.dumps({"status": "awaiting_reboot", "run_id": run["run_id"]}), flush=True)
        threading.Event().wait()

    with ConnectionCoordinator(args.state_root / "coordinator", _installed_release(
            args.runtime_root, args.distro)) as coordinator:
        _harness(args, coordinator, checkpoint=checkpoint).run()


def recover_reboot(args) -> dict:
    marker_path = args.state_root / "reboot-checkpoint.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    with ConnectionCoordinator(args.state_root / "coordinator", _installed_release(
            args.runtime_root, args.distro)) as coordinator:
        snapshot = coordinator.snapshot()
        recovered = _harness(args, coordinator).recover(snapshot)
    passed = all((
        marker.get("contract_version") == "p0-reboot-checkpoint.v1",
        marker.get("run_id") == recovered.get("run_id"),
        recovered.get("status") == "recovered",
        recovered.get("cleanup", {}).get("verified") is True,
    ))
    report = {
        "contract_version": "p0-recovery-qualification.v1",
        "mode": "startup_recovery",
        "status": "passed" if passed else "failed",
        "run_id": recovered.get("run_id"),
        "cleanup_verified": recovered.get("cleanup", {}).get("verified") is True,
    }
    atomic_json(args.state_root / "reboot-recovery-qualification.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("mode", choices=("endpoint-hang", "prepare-reboot", "recover-reboot"))
    value.add_argument("--state-root", type=Path, required=True)
    value.add_argument("--selection-file", type=Path, required=True)
    value.add_argument("--distro", required=True)
    value.add_argument("--runtime-root", default="/opt/switchtrade")
    value.add_argument("--relay-url", default="https://relay.pangyostonefist.org")
    value.add_argument("--target-channel", type=int, default=6)
    return value


def main() -> None:
    args = parser().parse_args()
    args.state_root = args.state_root.resolve()
    args.selection_file = args.selection_file.resolve()
    if args.mode == "prepare-reboot":
        prepare_reboot(args)
        return
    report = endpoint_hang(args) if args.mode == "endpoint-hang" else recover_reboot(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
