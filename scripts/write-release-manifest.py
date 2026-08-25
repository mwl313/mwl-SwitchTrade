#!/usr/bin/env python3
"""Write reproducible application and radio metadata for a packaged build."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    try:
        return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kernel-build", default="unverified")
    parser.add_argument("--driver", default="unverified")
    parser.add_argument("--firmware", default="unverified")
    parser.add_argument("--usb-id", default="unverified")
    args = parser.parse_args()
    tracked = [
        ROOT / "requirements.txt",
        ROOT / "bridge" / "requirements.txt",
        ROOT / "test-requirements.txt",
        ROOT / "config" / "wsl-radio-hardware.tsv",
        ROOT / "apps" / "web" / "package.json",
        ROOT / "apps" / "web" / "pnpm-lock.yaml",
    ]
    manifest = {
        "schema": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "application_commit": command("git", "rev-parse", "HEAD"),
        "branch": command("git", "branch", "--show-current"),
        "kernel_build": args.kernel_build,
        "driver": args.driver,
        "firmware": args.firmware,
        "usb_id": args.usb_id.lower(),
        "inputs": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in tracked},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
