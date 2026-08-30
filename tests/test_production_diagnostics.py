"""Regression coverage for persisted production-diagnostic lifecycle and API purity."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from switchtrade.control import create_app
from switchtrade.diagnostics import RunLogger
from switchtrade.relay_client import RelayError
from switchtrade.production_diagnostics import (
    AP_FIXTURE, DIAGNOSTIC_CONTRACT, DiagnosticD7Resources, DiagnosticFailure,
    ProductionDiagnostics, diagnostic_member_pair, fixture_metadata,
)


class ProductionDiagnosticsTests(unittest.TestCase):
    def test_d7_owner_releases_each_resource_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            updates = []
            credential = Path(temporary) / "member-token"
            credential.write_text("private", encoding="utf-8")

            class Peer:
                def stop(self):
                    events.append("peer")

            owner = DiagnosticD7Resources(
                close_room=lambda room: events.append(("room", room["room_id"])),
                update_recovery=lambda **value: updates.append(value),
            )
            owner.register_room({"room_id": "room-1", "owner_token": "private"})
            owner.register_peer(Peer())
            owner.register_credential(credential)

            first = owner.cleanup()
            second = owner.cleanup()

            self.assertEqual(first, {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": True,
                "credential_file_absent": True,
            })
            self.assertEqual(second, first)
            self.assertEqual(events, ["peer", ("room", "room-1")])
            self.assertFalse(credential.exists())
            self.assertEqual(updates[-2:], [{"room": None}, {"token_file": None}])

    def test_d7_owner_retries_only_the_resource_that_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            credential = Path(temporary) / "member-token"
            credential.write_text("private", encoding="utf-8")

            class Peer:
                def stop(self):
                    events.append("peer")

            room_attempts = 0

            def close_room(_room):
                nonlocal room_attempts
                room_attempts += 1
                events.append("room")
                if room_attempts == 1:
                    raise RelayError("temporary failure", status=503)

            owner = DiagnosticD7Resources(
                close_room=close_room,
                update_recovery=lambda **_value: None,
            )
            owner.register_room({"room_id": "room-1", "owner_token": "private"})
            owner.register_peer(Peer())
            owner.register_credential(credential)

            self.assertEqual(owner.cleanup(), {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": False,
                "credential_file_absent": True,
            })
            self.assertEqual(owner.cleanup(), {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": True,
                "credential_file_absent": True,
            })
            self.assertEqual(events, ["peer", "room", "room"])
            self.assertFalse(credential.exists())

    def test_d7_peer_failure_does_not_skip_room_or_credential_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            credential = Path(temporary) / "member-token"
            credential.write_text("private", encoding="utf-8")

            class Peer:
                def __init__(self):
                    self.calls = 0

                def stop(self):
                    self.calls += 1
                    events.append("peer")
                    if self.calls == 1:
                        raise RuntimeError("peer stop timed out")

            owner = DiagnosticD7Resources(
                close_room=lambda _room: events.append("room"),
                update_recovery=lambda **_value: None,
            )
            owner.register_room({"room_id": "room-1", "owner_token": "private"})
            owner.register_peer(Peer())
            owner.register_credential(credential)

            self.assertEqual(owner.cleanup(), {
                "synthetic_peer_stopped": False,
                "temporary_room_closed": True,
                "credential_file_absent": True,
            })
            self.assertFalse(credential.exists())
            self.assertEqual(owner.cleanup(), {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": True,
                "credential_file_absent": True,
            })
            self.assertEqual(events, ["peer", "room", "peer"])

    def test_d7_credential_delete_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            credential = Path(temporary) / "member-token"
            credential.write_text("private", encoding="utf-8")
            owner = DiagnosticD7Resources(
                close_room=lambda _room: None,
                update_recovery=lambda **_value: None,
            )
            owner.register_credential(credential)
            original_unlink = Path.unlink
            attempts = 0

            def flaky_unlink(path, *args, **kwargs):
                nonlocal attempts
                if path == credential:
                    attempts += 1
                    if attempts == 1:
                        raise PermissionError("credential is temporarily busy")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", new=flaky_unlink):
                self.assertFalse(owner.cleanup()["credential_file_absent"])
                self.assertTrue(owner.cleanup()["credential_file_absent"])
            self.assertFalse(credential.exists())
            self.assertEqual(attempts, 2)

    def _wait(self, diagnostics: ProductionDiagnostics, run_id: str, status: str) -> dict:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            value = diagnostics.get(run_id)
            if value and value["status"] == status:
                return value
            time.sleep(0.01)
        self.fail(f"diagnostic {run_id} did not reach {status}")

    def test_checkpoint_is_persisted_idempotent_and_terminal_after_worker_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = ProductionDiagnostics(temporary)

            def worker(run):
                run.stage("preflight", "passed", "DIAG_PREFLIGHT_PASSED", "Ready")
                run.await_continue("open_switch_room", "Open one Switch room.", timeout=2)
                run.stage("cleanup", "passed", "DIAG_CLEANUP_PASSED", "Released")
                run.finish("passed", result_level="switch_room_joined")

            started = diagnostics.start("room_detection", "0bda:818b", worker)
            waiting = self._wait(diagnostics, started["run_id"], "awaiting_user")
            self.assertEqual(waiting["contract_version"], DIAGNOSTIC_CONTRACT)
            self.assertEqual(waiting["checkpoint"]["id"], "open_switch_room")
            self.assertFalse(diagnostics.continue_run(started["run_id"], "wrong"))
            self.assertTrue(diagnostics.continue_run(started["run_id"], "open_switch_room"))
            finished = self._wait(diagnostics, started["run_id"], "passed")
            self.assertEqual(finished["cleanup"]["status"], "passed")
            self.assertEqual(finished["result_level"], "switch_room_joined")

    def test_restart_marks_guarded_incomplete_record_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "20260829T000000Z-deadbeef"
            run.mkdir()
            report = run / "production-diagnostic-report.json"
            report.write_text(json.dumps({
                "contract_version": DIAGNOSTIC_CONTRACT, "run_id": run.name,
                "status": "running", "cleanup": {"status": "pending"},
            }), encoding="utf-8")
            (root / "active-recovery.json").write_text(json.dumps({
                "schema": 1, "run_id": run.name, "report_path": str(report.resolve()),
                "status": "active", "adapter": {"usb_id": "0bda:818b"},
            }), encoding="utf-8")
            recovered = ProductionDiagnostics(root).get(run.name)
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["failure"]["code"], "DIAG_RUN_INTERRUPTED")

    def test_successful_restart_recovery_clears_only_the_current_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "20260829T000000Z-deadbeef"
            run.mkdir()
            report = run / "production-diagnostic-report.json"
            report.write_text(json.dumps({
                "contract_version": DIAGNOSTIC_CONTRACT, "run_id": run.name,
                "status": "failed", "cleanup": {"status": "interrupted"},
            }), encoding="utf-8")
            guard = root / "active-recovery.json"
            guard.write_text(json.dumps({
                "schema": 1, "run_id": run.name, "report_path": str(report.resolve()),
                "status": "unresolved", "adapter": {"usb_id": "0bda:818b"},
            }), encoding="utf-8")
            diagnostics = ProductionDiagnostics(root)
            diagnostics.complete_recovery({"radio_quiescent": True})
            self.assertFalse(guard.exists())
            self.assertEqual(diagnostics.get(run.name)["cleanup"]["status"], "passed")
            created = diagnostics.start(
                "automated", "0bda:818b", lambda current: current.finish("passed"))
            self._wait(diagnostics, created["run_id"], "passed")

    def test_incomplete_cleanup_blocks_another_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = ProductionDiagnostics(temporary)
            started = diagnostics.start(
                "automated", "0bda:818b",
                lambda run: run.finish("failed", cleanup_ok=False),
            )
            self._wait(diagnostics, started["run_id"], "failed")
            with self.assertRaisesRegex(DiagnosticFailure, "did not prove cleanup"):
                diagnostics.start("automated", "0bda:818b", lambda run: None)

    def test_fixture_is_immutable_and_redacted_metadata_only(self):
        self.assertEqual(len(AP_FIXTURE), 122)
        metadata = fixture_metadata()
        self.assertEqual(metadata["id"], "frlg-search-v2")
        self.assertEqual(len(metadata["sha256"]), 64)

    def test_diagnostic_member_pair_uses_distinct_complementary_members_for_both_roles(self):
        owner = {"member_token": "owner-token"}
        joined = {"member_token": "joined-token"}
        creator = diagnostic_member_pair(owner, joined, "creator")
        finder = diagnostic_member_pair(owner, joined, "finder")
        self.assertIs(creator["local"], owner)
        self.assertIs(creator["peer"], joined)
        self.assertEqual((creator["local_role"], creator["peer_role"]), ("creator", "finder"))
        self.assertIs(finder["local"], joined)
        self.assertIs(finder["peer"], owner)
        self.assertEqual((finder["local_role"], finder["peer_role"]), ("finder", "creator"))

    def test_diagnostic_member_pair_rejects_duplicate_credentials(self):
        with self.assertRaisesRegex(DiagnosticFailure, "distinct member credentials"):
            diagnostic_member_pair(
                {"member_token": "duplicate"}, {"member_token": "duplicate"}, "creator")

    def test_support_bundle_includes_production_diagnostic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = RunLogger("control", temporary)
            diagnostic = ProductionDiagnostics(logger.run_dir / "production-diagnostics")
            created = diagnostic.start(
                "automated", "0bda:818b",
                lambda run: run.finish("passed", result_level="relay_exchange_passed"),
            )
            self._wait(diagnostic, created["run_id"], "passed")
            with zipfile.ZipFile(logger.support_bundle()) as archive:
                self.assertIn(
                    f"production-diagnostics/{created['run_id']}/production-diagnostic-report.json",
                    archive.namelist(),
                )
                self.assertFalse(any("recovery" in name for name in archive.namelist()))

    def test_start_rejects_missing_adapter_before_any_endpoint_launch(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(runs_root=temporary)) as client:
            with patch("switchtrade.control.subprocess.Popen") as popen:
                started = client.post("/api/v1/production-diagnostics", json={
                    "test": "automated", "usb_id": "0bda:818b",
                })
                self.assertEqual(started.status_code, 409, started.text)
                self.assertEqual(started.json()["code"], "diag_adapter_not_selected")
                popen.assert_not_called()

    def test_known_attach_failure_is_radio_gate_failure_with_verified_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(
                create_app(runs_root=temporary, relay_url="https://relay.test")) as client:
            runtime = client.app.state.runtime
            instance_id = r"USB\VID_0BDA&PID_818B\ATTACH-FAILURE"
            runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
            runtime.relay_capabilities = {"manual-switch-role.v1"}
            runtime.next_capability_probe = time.monotonic() + 60

            def run(command, **_kwargs):
                if command[:2] == ["usbipd.exe", "state"]:
                    return MagicMock(returncode=0, stdout=json.dumps({"Devices": [{
                        "BusId": "2-4", "ClientIPAddress": None,
                        "PersistedGuid": "shared-radio", "Description": "Realtek RTL8192EU",
                        "InstanceId": instance_id,
                    }]}), stderr="")
                if command[:2] == ["usbipd.exe", "attach"]:
                    return MagicMock(returncode=1, stdout="", stderr="inactive port")
                if "python3" in command and any(
                        "/sys/bus/usb/devices" in str(part) for part in command):
                    return MagicMock(returncode=0, stdout=json.dumps({
                        "status": "absent", "interface_present": False, "phy_present": False,
                    }), stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("switchtrade.control.subprocess.run", side_effect=run):
                started = client.post("/api/v1/production-diagnostics", json={
                    "test": "automated", "usb_id": "0bda:818b",
                })
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["run_id"]
                deadline = time.monotonic() + 3
                report = None
                while time.monotonic() < deadline:
                    report = client.get(f"/api/v1/production-diagnostics/{run_id}").json()
                    if report["status"] == "failed":
                        break
                    time.sleep(0.02)

            self.assertEqual(report["failure"]["code"], "DIAG_RADIO_GATE_FAILED", report)
            self.assertEqual(report["cleanup"]["status"], "passed")
            self.assertIsNone(runtime.owned_hardware)
            self.assertFalse(runtime.diagnostics.cleanup_incomplete)

    def test_relay_pair_construction_failure_has_private_room_code_and_cleans_radio(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(
                create_app(runs_root=temporary, relay_url="https://relay.test")) as client:
            runtime = client.app.state.runtime
            instance_id = r"USB\VID_0BDA&PID_818B\ROOM-FAILURE"
            runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
            runtime.relay_capabilities = {"manual-switch-role.v1"}
            runtime.next_capability_probe = time.monotonic() + 60
            attached = False

            def run(command, **_kwargs):
                nonlocal attached
                if command[:2] == ["usbipd.exe", "attach"]:
                    attached = True
                elif command[:2] == ["usbipd.exe", "detach"]:
                    attached = False
                if command[:2] == ["usbipd.exe", "state"]:
                    return MagicMock(returncode=0, stdout=json.dumps({"Devices": [{
                        "BusId": "2-4", "ClientIPAddress": "172.20.0.1" if attached else None,
                        "PersistedGuid": "shared-radio", "Description": "Realtek RTL8192EU",
                        "InstanceId": instance_id,
                    }]}), stderr="")
                if "python3" in command and any(
                        "/sys/bus/usb/devices" in str(part) for part in command):
                    return MagicMock(returncode=0, stdout=json.dumps({
                        "status": "present" if attached else "absent",
                        "interface_present": attached, "phy_present": attached,
                    }), stderr="")
                if "switchtrade.hardware_diagnostics" in command:
                    return MagicMock(returncode=0, stdout=json.dumps({
                        "contract_version": "hardware-diagnostic.v1",
                        "run_id": "hardware-run", "overall_status": "partial",
                    }) + "\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("switchtrade.control.subprocess.run", side_effect=run), patch.object(
                    runtime.relay, "create_trade_room", side_effect=RelayError(
                        "relay unavailable", status=503, code="relay_unavailable", stage="relay")):
                started = client.post("/api/v1/production-diagnostics", json={
                    "test": "automated", "usb_id": "0bda:818b",
                })
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["run_id"]
                deadline = time.monotonic() + 3
                report = None
                while time.monotonic() < deadline:
                    report = client.get(f"/api/v1/production-diagnostics/{run_id}").json()
                    if report["status"] == "failed":
                        break
                    time.sleep(0.02)

            self.assertEqual(report["failure"]["code"], "DIAG_PRIVATE_ROOM_FAILED", report)
            self.assertEqual(report["cleanup"]["status"], "passed")
            self.assertFalse(attached)

    def test_get_projection_never_launches_or_mutates_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(runs_root=temporary)) as client:
            runtime = client.app.state.runtime
            release = threading.Event()

            def worker(run):
                run.transition("running", "fixture")
                release.wait(2)
                run.finish("passed", result_level="relay_exchange_passed")

            run_id = runtime.diagnostics.start("automated", "0bda:818b", worker)["run_id"]
            with patch("switchtrade.control.subprocess.Popen") as popen:
                snapshots = [client.get(f"/api/v1/production-diagnostics/{run_id}") for _ in range(20)]
                self.assertTrue(all(response.status_code == 200 for response in snapshots))
                popen.assert_not_called()
            release.set()

    def test_cancel_route_signals_worker_without_racing_endpoint_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(runs_root=temporary)) as client:
            runtime = client.app.state.runtime

            def worker(run):
                run.transition("running", "fixture")
                while not run.canceled():
                    time.sleep(0.01)
                run.begin_cleanup()
                run.finish("canceled", code="DIAG_CANCELED", cleanup={
                    "status": "passed", "evidence": {"endpoint_stopped": True},
                })

            started = runtime.diagnostics.start("automated", "0bda:818b", worker)
            with patch.object(runtime, "stop_endpoint") as stop:
                canceled = client.delete(
                    f"/api/v1/production-diagnostics/{started['run_id']}")
                self.assertEqual(canceled.status_code, 200, canceled.text)
                stop.assert_not_called()
            finished = self._wait(runtime.diagnostics, started["run_id"], "canceled")
            self.assertEqual(finished["cleanup"]["status"], "passed")

    def test_automated_run_uses_distinct_roles_and_one_hardware_lease(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(
                create_app(runs_root=temporary, relay_url="https://relay.test")) as client:
            runtime = client.app.state.runtime
            instance_id = r"USB\VID_0BDA&PID_818B\DIAGNOSTIC"
            runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
            runtime.relay_capabilities = {"manual-switch-role.v1"}
            runtime.next_capability_probe = time.monotonic() + 60
            attached = False
            commands = []
            room_number = 0
            current = {}
            ready_calls = []

            def run(command, **_kwargs):
                nonlocal attached
                commands.append(command)
                result = MagicMock(returncode=0, stdout="", stderr="")
                if command[:2] == ["usbipd.exe", "attach"]:
                    attached = True
                elif command[:2] == ["usbipd.exe", "detach"]:
                    attached = False
                elif command[:2] == ["usbipd.exe", "state"]:
                    result.stdout = json.dumps({"Devices": [{
                        "BusId": "2-4", "ClientIPAddress": "172.20.0.1" if attached else None,
                        "PersistedGuid": "shared-radio", "Description": "Realtek RTL8192EU",
                        "InstanceId": instance_id,
                    }]})
                elif "python3" in command and any(
                        "/sys/bus/usb/devices" in str(part) for part in command):
                    result.stdout = json.dumps({
                        "status": "present" if attached else "absent",
                        "interface_present": attached, "phy_present": attached,
                    })
                elif "switchtrade.hardware_diagnostics" in command:
                    result.stdout = json.dumps({
                        "contract_version": "hardware-diagnostic.v1",
                        "run_id": "hardware-run", "overall_status": "partial",
                    }) + "\n"
                return result

            def create_room(_payload, _client_id):
                nonlocal room_number, current
                room_number += 1
                current = {
                    "number": room_number, "version": 1, "roles": {},
                    "owner": f"owner-{room_number}", "joined": f"joined-{room_number}",
                }
                return {"member_token": current["owner"], "room": {
                    "room_id": f"room-{room_number}", "room_code": f"ROOM{room_number}",
                    "room_version": 1,
                }}

            def join_room(_code, _name, _client_id):
                return {"member_token": current["joined"]}

            def room_view(_room_id, token):
                roles = current["roles"]
                members = [
                    {"seat": "member_a", "switch_room_role": roles.get(current["owner"]),
                     "is_local": token == current["owner"]},
                    {"seat": "member_b", "switch_room_role": roles.get(current["joined"]),
                     "is_local": token == current["joined"]},
                ]
                return {
                    "room_version": current["version"], "members": members,
                    "attempt": {
                        "attempt_id": f"attempt-{current['number']}", "role_locked": True,
                        "local_switch_role": roles.get(token),
                    } if len(roles) == 2 else None,
                }

            def room_command(_room_id, token, path, payload=None, **kwargs):
                if kwargs.get("method") == "DELETE":
                    return {"state": "closed"}
                self.assertEqual(path, "/ready")
                current["roles"][token] = payload["switch_room_role"]
                current["version"] += 1
                ready_calls.append((token, payload["switch_room_role"]))
                return room_view(_room_id, token)

            pid = 2000

            def windows_path(value):
                return (f"{value[5].upper()}:\\" + value[7:].replace("/", "\\")
                        if value.startswith("/mnt/") else value)

            def popen(command, **_kwargs):
                nonlocal pid
                pid += 1
                process = MagicMock()
                process.pid = pid
                process.poll.return_value = None
                launch_nonce = command[command.index("--launch-nonce") + 1]
                state_path = Path(windows_path(command[command.index("--state-file") + 1]))
                ack_path = Path(windows_path(command[command.index("--launch-ack-file") + 1]))
                diagnostic_nonce = (command[command.index("--diagnostic-nonce") + 1]
                                    if "--diagnostic-nonce" in command else None)
                ack_path.write_text(json.dumps({
                    "schema": 2, "stage": "radio_gate_passed",
                    "launch_nonce": launch_nonce, "launcher_pid": pid,
                }), encoding="utf-8")
                state_path.write_text(json.dumps({
                    "state": "diagnostic_checkpoint_passed", "pid": pid + 10000,
                    "process_kind": "rfu-endpoint", "wsl_distro": "SwitchTrade",
                    "session_id": command[command.index("--session-id") + 1],
                    "attempt_id": command[command.index("--attempt-id") + 1],
                    "launch_nonce": launch_nonce, "process_start_ticks": 12345,
                    "diagnostic_run_id": command[command.index("--diagnostic-run-id") + 1],
                    "diagnostic_checkpoint": command[command.index("--diagnostic-checkpoint") + 1],
                    "diagnostic_nonce_hash": hashlib.sha256(
                        diagnostic_nonce.encode("ascii")).hexdigest(),
                }), encoding="utf-8")
                return process

            with patch.object(runtime.relay, "create_trade_room", side_effect=create_room), \
                    patch.object(runtime.relay, "join_trade_room", side_effect=join_room), \
                    patch.object(runtime.relay, "room_command", side_effect=room_command), \
                    patch.object(runtime.relay, "room", side_effect=room_view), \
                    patch("switchtrade.control.subprocess.run", side_effect=run), \
                    patch("switchtrade.control.subprocess.Popen", side_effect=popen), \
                    patch("switchtrade.control.SyntheticDiagnosticPeer") as peer, \
                    patch.object(type(runtime), "_signal_endpoint_pid", return_value=False):
                started = client.post("/api/v1/production-diagnostics", json={
                    "test": "automated", "usb_id": "0bda:818b",
                })
                self.assertEqual(started.status_code, 202, started.text)
                run_id = started.json()["run_id"]
                deadline = time.monotonic() + 5
                report = None
                while time.monotonic() < deadline:
                    report = client.get(f"/api/v1/production-diagnostics/{run_id}").json()
                    if report["status"] in {"passed", "failed"}:
                        break
                    time.sleep(0.02)

            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["cleanup"]["status"], "passed")
            self.assertEqual(ready_calls, [
                ("owner-1", "creator"), ("joined-1", "finder"),
                ("joined-2", "finder"), ("owner-2", "creator"),
            ])
            self.assertEqual(sum(command[:2] == ["usbipd.exe", "attach"] for command in commands), 1)
            self.assertEqual(sum(command[:2] == ["usbipd.exe", "detach"] for command in commands), 1)
            quiesce = [index for index, command in enumerate(commands)
                       if "switchtrade-radio-quiesce" in command]
            detach = [index for index, command in enumerate(commands)
                      if command[:2] == ["usbipd.exe", "detach"]]
            self.assertEqual(len(quiesce), 1)
            self.assertLess(quiesce[0], detach[0])
            self.assertEqual(peer.call_count, 2)


if __name__ == "__main__":
    unittest.main()
