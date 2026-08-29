"""CLI entry point for installed-runtime direct Switch AP admission (B2-B10)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from switchtrade.connection.coordinator import ConnectionCoordinator
from switchtrade.connection.p0 import PassiveValidator
from switchtrade.connection.p0_harness import P0Harness, _installed_release
from switchtrade.diagnostics import default_runs_root


def parser() -> argparse.ArgumentParser:
    runtime = default_runs_root().parent / "runtime"
    value = argparse.ArgumentParser(description="SwitchTrade direct B2-B10 qualification harness")
    value.add_argument("--state-root", type=Path, default=default_runs_root().parent / "connection-v2")
    value.add_argument("--selection-file", type=Path, default=runtime / "hardware-selection.json")
    value.add_argument("--runtime-root", default="/opt/switchtrade")
    value.add_argument("--distro", default=os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"))
    value.add_argument("--target-channel", type=int, default=6)
    return value


def main() -> None:
    args = parser().parse_args()
    release = _installed_release(args.runtime_root, args.distro)
    validator = PassiveValidator(
        release=release,
        selection_file=args.selection_file,
        distro=args.distro,
        runtime_root=args.runtime_root,
        target_channel=args.target_channel,
        blocking_state_paths=(
            default_runs_root().parent / "runtime" / "production-diagnostic-recovery.json",
        ),
        require_relay=False,
    )
    with ConnectionCoordinator(args.state_root / "coordinator", release) as coordinator:
        harness = P0Harness(
            coordinator,
            validator,
            args.state_root / "runs",
            distro=args.distro,
            runtime_root=args.runtime_root,
            target_channel=args.target_channel,
        )
        current = coordinator.snapshot()
        if current is not None and not current["cleanup"]["verified"]:
            recovery = harness.recover(current)
            if recovery["status"] == "failed":
                print(json.dumps(recovery, indent=2, sort_keys=True))
                raise SystemExit(2)
        result = harness.run_direct_b()
    print(json.dumps(result, indent=2, sort_keys=True))
    passed = result["functional_status"] == "passed" and result["cleanup_status"] == "verified"
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()

