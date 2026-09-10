"""Require real-process evidence; unit tests or a skipped/short soak cannot pass."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/core-simplification/GPSP_ACCEPTANCE.json"
RA = "81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a"
CORE = "c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516"
FIXTURES = {"continuity": "cfb0a21e1504931d7589a30b125ff3bbdf9211116a7bea690cfecadf031a2720",
    "full": "8dc38db4b62b1fd66ce2ee390db66b22e040b5da7f4138470f7c318e9fe1c9ea"}


def validate_report(report, kind, sha, python_version="3.12"):
    runtime = report.get("native_python", {})
    if (python_version not in ("3.12", "3.14")
            or runtime.get("version", [])[:2] != list(map(int, python_version.split(".")))
            or runtime.get("bits") != 64 or runtime.get("implementation") != "cpython"
            or runtime.get("free_threaded") is not False):
        raise ValueError("native Python identity mismatch")
    for key in ("passed", "source_clean", "source_unchanged", "stock_tree_unchanged", "started_before_netplay",
                "same_process_two_rounds", "process_handle_cleanup", "desktop_cleanup"):
        if report.get(key) is not True:
            raise ValueError("required real-process proof missing: " + key)
    if (report.get("source_sha") != sha or report.get("retroarch_sha256") != RA
            or report.get("gpsp_sha256") != CORE or report.get("fixture_sha256") != FIXTURES[kind]):
        raise ValueError("source/runtime/fixture identity mismatch")
    if report.get("test_process_forced_exit") or report.get("test_process_exit") != 0 or report.get("stock_tree_delta") != []:
        raise ValueError("cleanup or isolation not proven")
    expected = 1 if kind == "full" else 2
    if report.get("socket_cleanup") != [True] * expected or report.get("netplay_handshakes") != expected:
        raise ValueError("connection lifetime/cleanup not proven")
    rows = report.get("rounds", [])
    if len(rows) != 2 or [r.get("in_ram_counter") for r in rows] != [1, 2]:
        raise ValueError("same-game continuity not proven")
    if kind == "continuity":
        if not report.get("production_local") or report.get("native_doctor_exit") != 0:
            raise ValueError("actual process observation/native doctor not proven")
        return
    if not report.get("full_stack"):
        raise ValueError("modeled P2 is not full qualification")
    first = rows[0]
    if (first.get("real_traffic_seconds", 0) < 1800 or first.get("game_wait_seconds", 0) <= 180
            or first.get("local_netplay_wait_seconds", 0) <= 180):
        raise ValueError("real human waiting/30-minute traffic not proven")
    for row in rows:
        if (not all(row.get(k) is True for k in ("same_pair", "local_netplay_retained", "radio_room_end", "native_discovery_gate"))
                or row.get("bidirectional_exchanges", 0) < 2 or row.get("encrypted_ldn_frames", 0) < 5):
            raise ValueError("full data/lifecycle path not proven")
        if (row.get("receipt_verified_exchanges") != row["bidirectional_exchanges"]
                or type(row.get("data_before_receipt")) is not int
                or not 0 <= row["data_before_receipt"] <= row["receipt_verified_exchanges"]):
            raise ValueError("correlated receipts not proven")
    samples = first.get("resource_samples", [])
    if len(samples) < 30 or samples[-1]["seconds"] < 1800:
        raise ValueError("resource soak missing")
    warm = next(sample for sample in samples if sample["seconds"] >= 60)
    for sample in samples[2:]:
        for process in ("retroarch", "native"):
            if (sample[process]["handles"] > warm[process]["handles"] + 8
                    or sample[process]["private_bytes"] > warm[process]["private_bytes"] + 16 * 1024 * 1024):
                raise ValueError("bounded resource soak failed")


def attest(manifest, reports, sha, results, run_url, python_version="3.12"):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("exact source SHA required")
    if results != {"windows": "success", "ubuntu": "success"}:
        raise ValueError("both exact-SHA platform jobs required")
    if manifest.get("software_gaps") != [] or manifest.get("state") != "AWAITING_FINAL_CI":
        raise ValueError("unfinished software acceptance")
    rows = manifest["acceptance"]
    if len(rows) != 24 or {r["id"] for r in rows} != {f"G{i:02}" for i in range(1, 25)}:
        raise ValueError("incomplete gpSP acceptance IDs")
    if any(r.get("status") != "READY_FOR_FINAL_CI" or not r.get("evidence") for r in rows):
        raise ValueError("unresolved acceptance item")
    for kind in FIXTURES:
        validate_report(reports[kind], kind, sha, python_version)
    result = copy.deepcopy(manifest)
    result.update(state="COMPLETE", final_sha=sha, ci={**results, "run_url": run_url},
        verdict="Switch↔gpSP 소프트웨어 검증 완료, 실물 시험 준비 완료", real_process_evidence=reports,
        native_python_version=python_version)
    for row in result["acceptance"]:
        row["status"] = "PASS"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-version", choices=("3.12", "3.14"), required=True)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_SHA") != sha
            or os.environ.get("GITHUB_REPOSITORY") != "mwl313/mwl-SwitchTrade"):
        raise RuntimeError("exact repository/CI identity required")
    reports = {name: json.loads((args.reports / name / "report.json").read_text(encoding="utf-8")) for name in FIXTURES}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = attest(manifest, reports, sha, {"windows": os.environ.get("WINDOWS_RESULT"),
        "ubuntu": os.environ.get("UBUNTU_RESULT")},
        f"https://github.com/mwl313/mwl-SwitchTrade/actions/runs/{os.environ['GITHUB_RUN_ID']}", args.python_version)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
