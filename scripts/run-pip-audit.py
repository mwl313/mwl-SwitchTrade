#!/usr/bin/env python3
"""Run pip-audit with version-bound, expiring reachability exceptions."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "test-requirements.txt"
RUNTIME_LOCK = ROOT / "bridge" / "requirements.txt"
POLICY = ROOT / "security" / "pip-audit-exceptions.json"


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("schema") != 1:
        raise SystemExit("unsupported pip-audit exception policy schema")
    pins = {
        name.strip().lower(): version.strip()
        for path in (RUNTIME_LOCK, REQUIREMENTS)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.lstrip().startswith("#")
        for name, version in [line.split("==", 1)]
    }
    command = [sys.executable, "-m", "pip_audit", "-r", str(REQUIREMENTS)]
    seen: set[str] = set()
    for exception in policy.get("exceptions", []):
        missing = {"id", "package", "version", "expires", "reason"} - exception.keys()
        if missing:
            raise SystemExit(f"incomplete pip-audit exception: {sorted(missing)}")
        if exception["id"] in seen:
            raise SystemExit(f"duplicate pip-audit exception: {exception['id']}")
        seen.add(exception["id"])
        if date.fromisoformat(exception["expires"]) < date.today():
            raise SystemExit(f"expired pip-audit exception: {exception['id']}")
        package = exception["package"].lower()
        if pins.get(package) != exception["version"]:
            raise SystemExit(
                f"stale pip-audit exception {exception['id']}: expected "
                f"{package}=={exception['version']}"
            )
        command.extend(("--ignore-vuln", exception["id"]))
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
