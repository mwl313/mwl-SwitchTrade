"""Fail-closed evidence checks; modeled reports are not qualification evidence."""
import copy
import json
from pathlib import Path

import pytest

from tools.gpsp_qualification.attest import attest, validate_report, MANIFEST, RA, CORE, FIXTURES
from tools.gpsp_qualification.prepare_stock import selected_members


def reports():
    sample = {"handles": 100, "private_bytes": 32 * 1024 * 1024}
    result = {}
    for kind in FIXTURES:
        count = 1 if kind == "full" else 2
        result[kind] = {**{key: True for key in ("passed", "source_clean", "source_unchanged", "stock_tree_unchanged",
            "started_before_netplay", "same_process_two_rounds", "process_handle_cleanup", "desktop_cleanup")},
            "source_sha": "1" * 40, "retroarch_sha256": RA, "gpsp_sha256": CORE,
            "fixture_sha256": FIXTURES[kind], "test_process_exit": 0, "stock_tree_delta": [],
            "socket_cleanup": [True] * count, "netplay_handshakes": count,
            "production_local": kind == "continuity", "native_doctor_exit": 0, "full_stack": kind == "full",
            "rounds": [{"in_ram_counter": number, "real_traffic_seconds": 1801,
                "game_wait_seconds": 181, "local_netplay_wait_seconds": 181,
                "same_pair": True, "local_netplay_retained": True, "radio_room_end": True,
                "bidirectional_exchanges": 3000, "encrypted_ldn_frames": 6000,
                "resource_samples": [{"seconds": n * 60, "native": dict(sample), "retroarch": dict(sample)}
                                     for n in range(31)]} for number in (1, 2)]}
    return result


def test_complete_evidence_requires_all_ids_and_exact_process_reports():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    original = copy.deepcopy(manifest)
    result = attest(manifest, reports(), "1" * 40, {"windows": "success", "ubuntu": "success"}, "test://modeled")
    assert result["state"] == "COMPLETE" and manifest == original
    root = Path(__file__).resolve().parents[1]
    assert all((root / path).is_file() for row in manifest["acceptance"] for path in row["evidence"])


@pytest.mark.parametrize("fault", ["skip", "source", "dirty", "changed", "binary", "fixture", "forced", "cleanup",
    "reset", "reconnect", "modeled", "short_wait", "short_game", "short_soak", "no_resources", "leak", "room"])
def test_incomplete_or_modeled_evidence_never_attests(fault):
    value = reports()["full"]
    first = value["rounds"][0]
    if fault == "skip": value["passed"] = False
    elif fault == "source": value["source_sha"] = "2" * 40
    elif fault == "dirty": value["source_clean"] = False
    elif fault == "changed": value["source_unchanged"] = False
    elif fault == "binary": value["gpsp_sha256"] = "other"
    elif fault == "fixture": value["fixture_sha256"] = FIXTURES["continuity"]
    elif fault == "forced": value["test_process_forced_exit"] = True
    elif fault == "cleanup": value["socket_cleanup"] = [False]
    elif fault == "reset": value["rounds"][1]["in_ram_counter"] = 1
    elif fault == "reconnect": value["netplay_handshakes"] = 2
    elif fault == "modeled": value["full_stack"] = False
    elif fault == "short_wait": first["local_netplay_wait_seconds"] = 180
    elif fault == "short_game": first["game_wait_seconds"] = 180
    elif fault == "short_soak": first["real_traffic_seconds"] = 1799
    elif fault == "no_resources": first["resource_samples"] = []
    elif fault == "leak": first["resource_samples"][-1]["native"]["handles"] = 999
    elif fault == "room": first["radio_room_end"] = False
    with pytest.raises(ValueError):
        validate_report(value, "full", "1" * 40)


def test_failed_ci_or_open_acceptance_cannot_close():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        attest(manifest, reports(), "1" * 40, {"windows": "success", "ubuntu": "failure"}, "test://modeled")
    manifest["acceptance"][0]["status"] = "PARTIAL"
    with pytest.raises(ValueError):
        attest(manifest, reports(), "1" * 40, {"windows": "success", "ubuntu": "success"}, "test://modeled")


def test_archive_selection_is_exact_and_path_safe():
    assert selected_members(["RetroArch-Win64/retroarch.exe", "RetroArch-Win64/SDL2.dll",
        "RetroArch-Win64/config/user.cfg", "RetroArch-Win64/cores/other.dll"]) == [
        "RetroArch-Win64/retroarch.exe", "RetroArch-Win64/SDL2.dll"]
    assert selected_members(["RetroArch-Win64/cores/gpsp_libretro.dll"], True) == ["RetroArch-Win64/cores/gpsp_libretro.dll"]
    for names in (["RetroArch-Win64/..\\escape.dll"], ["RetroArch-Win64/c:escape.dll"], [],
                  ["RetroArch-Win64/a.dll", "RetroArch-Win64/a.dll"]):
        with pytest.raises(ValueError):
            selected_members(names)
