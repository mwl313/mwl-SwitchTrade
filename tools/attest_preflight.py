"""Resolve the tracked acceptance manifest after both exact-SHA CI jobs succeed.

The artifact contains its generating commit's literal SHA; it is not committed
back into that commit (which would change the SHA and invalidate the statement).
"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/core-simplification/ABC_SOFTWARE_PREFLIGHT_CLOSURE.json"


def attest(manifest, sha, results, run_url):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("exact source SHA is required")
    if results != {"windows": "success", "ubuntu": "success"}:
        raise ValueError("both mandatory platform jobs must succeed")
    if manifest.get("software_gaps") != []:
        raise ValueError("software gaps remain")
    if manifest.get("task_state") != "AWAITING_FINAL_CI":
        raise ValueError("manifest is not ready for final qualification")
    for collection, prefix, count, status in (
        ("issues", "I", 18, "IMPLEMENTED_PENDING_FINAL_CI"),
        ("tests", "T", 44, "READY_FOR_FINAL_CI"),
    ):
        rows = manifest[collection]
        expected = {f"{prefix}{i:02}" for i in range(1, count + 1)}
        if len(rows) != count or {row["id"] for row in rows} != expected:
            raise ValueError("acceptance IDs are incomplete or duplicated")
        if any(row["status"] != status for row in rows):
            raise ValueError("an acceptance item remains unresolved")
    for issue in manifest["issues"]:
        if not issue["resolution"] or not issue["source_locations"] or not issue["required_tests"]:
            raise ValueError("issue lacks source/test evidence")
    for test in manifest["tests"]:
        if not test["test_nodes"] or not test["observed_result"]:
            raise ValueError("test lacks an actual observation mapping")
    result = copy.deepcopy(manifest)
    result.update(final_sha=sha, task_state="COMPLETE", verdict="ABC SOFTWARE PREFLIGHT: PASS")
    for issue in result["issues"]:
        issue["status"] = "CLOSED"
    for test in result["tests"]:
        test.update(status="PASS", source_revision=sha, exit_code=0)
        test["evidence_refs"].append(run_url)
    result["ci"] = {"head_sha": sha, "run_url": run_url, **{
        name: {"status": "completed", "conclusion": "success", "required_steps_passed": True}
        for name in results}}
    result["notes"] = "Exact-SHA software attestation after both required CI jobs; physical testing has NOT been performed. See the REAL/STUB evidence and runbook."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_SHA") != sha
            or os.environ.get("GITHUB_REF") not in {"refs/heads/Simple-Architecture", "refs/heads/codex/gpsp-endpoint"}
            or os.environ.get("GITHUB_REPOSITORY") != "mwl313/mwl-SwitchTrade"):
        raise RuntimeError("attestation requires the exact repository/branch/CI checkout identity")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for issue in manifest["issues"]:
        if any(not (ROOT / path).is_file() for path in issue["source_locations"]):
            raise RuntimeError("source evidence path does not exist")
    for test in manifest["tests"]:
        if any(not (ROOT / node.split("::", 1)[0]).exists() for node in test["test_nodes"]):
            raise RuntimeError("test evidence path does not exist")
    url = f"https://github.com/mwl313/mwl-SwitchTrade/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    result = attest(manifest, sha, {
        "windows": os.environ.get("WINDOWS_RESULT"), "ubuntu": os.environ.get("UBUNTU_RESULT")}, url)
    result["branch"] = os.environ["GITHUB_REF"].removeprefix("refs/heads/")
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["verdict"], sha)


if __name__ == "__main__":
    main()
