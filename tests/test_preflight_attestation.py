import copy
import json

import pytest

from tools.attest_preflight import MANIFEST, ROOT, attest


def test_complete_manifest_resolves_to_exact_ci_sha_without_self_reference():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    original = copy.deepcopy(manifest)
    result = attest(manifest, "1" * 40, {"windows": "success", "ubuntu": "success"}, "https://example.invalid/ci")
    assert manifest == original
    assert result["final_sha"] == result["ci"]["head_sha"] == "1" * 40
    assert result["verdict"] == "ABC SOFTWARE PREFLIGHT: PASS"
    assert all(row["status"] == "CLOSED" for row in result["issues"])
    assert all(row["status"] == "PASS" and row["source_revision"] == "1" * 40 for row in result["tests"])
    for issue in manifest["issues"]:
        assert all((ROOT / path).is_file() for path in issue["source_locations"])
    for test in manifest["tests"]:
        assert all((ROOT / node.split("::", 1)[0]).exists() for node in test["test_nodes"])


@pytest.mark.parametrize("fault", ["missing", "duplicate", "open_issue", "open_test", "gap", "ci", "sha"])
def test_attestation_refuses_partial_or_failed_acceptance(fault):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = {"windows": "success", "ubuntu": "success"}
    sha = "1" * 40
    if fault == "missing":
        manifest["tests"].pop()
    elif fault == "duplicate":
        manifest["issues"][-1] = manifest["issues"][0]
    elif fault == "open_issue":
        manifest["issues"][0]["status"] = "PARTIAL"
    elif fault == "open_test":
        manifest["tests"][0]["status"] = "NOT_RUN"
    elif fault == "gap":
        manifest["software_gaps"] = ["known unresolved integration gap"]
    elif fault == "ci":
        results["windows"] = "failure"
    else:
        sha = "old-head"
    with pytest.raises(ValueError):
        attest(manifest, sha, results, "https://example.invalid/ci")
