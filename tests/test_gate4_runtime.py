from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from switchtrade.control import Group, create_app, endpoint_command
from switchtrade.relay_client import RelayClient, RelayError


class Gate4RuntimeContractTests(unittest.TestCase):
    def test_wsl_relay_client_uses_dual_stack_safe_dns_queries(self):
        with patch.dict(os.environ, {"RES_OPTIONS": "rotate"}):
            with patch("switchtrade.relay_client.os.name", "posix"):
                RelayClient("https://relay.example")
            self.assertEqual(os.environ["RES_OPTIONS"], "rotate single-request-reopen")

    def test_legacy_group_listing_never_exposes_room_code(self):
        listing = Group("Compatibility room", "ABC123", "public").public()
        self.assertNotIn("passcode", listing)

    def test_package_includes_live_decoder_runtime(self):
        package_script = (Path(__file__).resolve().parents[1] /
                          "installer" / "Build-Package.ps1").read_text(encoding="utf-8")
        for dependency in (
            "payload_decoder.py", "pk3-tool.py", "species_map.py",
            "stats.py", "basestats.py", "charmap_jp.py",
        ):
            self.assertIn(f"tools/{dependency}", package_script)

    def test_readiness_separates_component_axes_and_versions_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                response = client.get("/api/v1/app/readiness")
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["contract_version"], "app-readiness.v1")
                self.assertTrue(body["compatible"])
                self.assertEqual(set(body["states"]),
                                 {"control", "relay", "radio", "session", "decoder"})
                self.assertEqual(body["states"]["control"]["status"], "ready")
                self.assertNotIn("passcode", str(body).lower())

    def test_public_directory_capability_is_gated_by_relay_health(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("switchtrade.control.RelayClient.health", return_value={
                    "status": "ready", "room_contract": "room-control.v1",
                    "rfu_contract": "rfu-tunnel.v1",
                    "capabilities": ["public-directory.v1"]}):
                with TestClient(create_app(
                        runs_root=temporary, relay_url="https://relay.example")) as client:
                    body = client.get("/api/v1/app/readiness").json()
                    self.assertEqual(body["capabilities"], ["public-directory.v1"])

        with tempfile.TemporaryDirectory() as temporary:
            with patch("switchtrade.control.RelayClient.health", return_value={
                    "status": "ready", "room_contract": "room-control.v1",
                    "rfu_contract": "rfu-tunnel.v1", "capabilities": []}):
                with TestClient(create_app(
                        runs_root=temporary, relay_url="https://relay.example")) as client:
                    body = client.get("/api/v1/app/readiness").json()
                    self.assertEqual(body["capabilities"], [])

        with tempfile.TemporaryDirectory() as temporary:
            with patch("switchtrade.control.RelayClient.health",
                       side_effect=RelayError("relay unavailable: DNS lookup failed")):
                with TestClient(create_app(
                        runs_root=temporary, relay_url="https://relay.example")) as client:
                    body = client.get("/api/v1/app/readiness").json()
                    self.assertEqual(body["capabilities"], [])
                    self.assertEqual(body["states"]["relay"]["status"], "failed")
                    self.assertEqual(body["states"]["relay"]["technical_code"],
                                     "relay.unavailable")

    def test_local_control_rejects_cross_origin_browser_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                response = client.post(
                    "/api/v1/session/stop", headers={"Origin": "https://untrusted.example"})
                self.assertEqual(response.status_code, 403)

    def test_party_api_fails_neutral_when_session_is_inactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                body = client.get("/api/v1/trade-room/parties").json()
                self.assertEqual(body["contract_version"], "party-commit.v1")
                self.assertFalse(body["trading_room_confirmed"])
                self.assertTrue(all(value["status"] == "unavailable"
                                    for value in body["parties"].values()))

    def test_public_directory_is_proxied_without_room_credentials(self):
        listing = {
            "contract_version": "public-directory.v1", "listing_id": "listing-1",
            "room_name": "Kanto", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English", "offering": "Vulpix",
            "wanted": "Growlithe", "note": "", "availability": "open",
            "occupancy": 1, "capacity": 2, "created_at": "2026-08-26T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                with patch("switchtrade.control.RelayClient.health", return_value={
                        "status": "ready", "room_contract": "room-control.v1",
                        "rfu_contract": "rfu-tunnel.v1",
                        "capabilities": ["public-directory.v1"]}), patch.object(
                        runtime.relay, "public_trade_rooms", return_value={
                        "contract_version": "public-directory.v1", "rooms": [listing],
                        "next_cursor": None}) as public_rooms:
                    response = client.get(
                        "/api/v1/public-trade-rooms?query=Vulpix&game=LeafGreen")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["rooms"], [listing])
                self.assertNotIn("room_code", response.text)
                public_rooms.assert_called_once()

                room = {
                    "contract_version": "room-control.v1",
                    "room_id": "room-1", "room_code": "ABC123",
                    "members": [], "visibility": "public",
                }
                with patch.object(runtime.relay, "join_public_trade_room", return_value={
                        "room": room, "member_token": "secret", "reconnect_token": "reconnect"}):
                    joined = client.post(
                        "/api/v1/public-trade-rooms/listing-1/join",
                        json={"trainer_display_name": "Red"})
                self.assertEqual(joined.status_code, 200, joined.text)
                self.assertEqual(joined.json()["room"]["room_code"], "ABC123")
                self.assertNotIn("member_token", joined.text)

    def test_release_is_idempotent_after_remote_membership_already_ended(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                expired = {
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "expired-member", "reconnect_token": "expired-reconnect",
                }
                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401,
                        code="member_credential_invalid", stage="authentication",
                        primary_action="reconnect")), patch.object(
                        runtime.relay, "reconnect_trade_room", side_effect=RelayError(
                            "reconnect credential is invalid", status=401,
                            code="reconnect_credential_invalid", stage="authentication",
                            recoverable=False, primary_action="rejoin_room")):
                    for path in ("/api/v1/trade-room/members/me", "/api/v1/trade-room"):
                        runtime.save_authority(expired)
                        response = client.delete(path)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertFalse(runtime.authority_state.exists())

    def test_remote_room_close_clears_local_authority_and_returns_stable_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "expired-member", "reconnect_token": "expired-reconnect",
                })
                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401,
                        code="member_credential_invalid", stage="authentication",
                        primary_action="reconnect")), patch.object(
                        runtime.relay, "reconnect_trade_room", side_effect=RelayError(
                            "room is no longer active", status=410,
                            code="room_not_active", stage="room",
                            recoverable=False, primary_action="return_home",
                            correlation_id="relay-correlation")):
                    response = client.get("/api/v1/trade-room")
                self.assertEqual(response.status_code, 410, response.text)
                self.assertEqual(response.json()["code"], "room_not_active")
                self.assertEqual(response.json()["primary_action"], "return_home")
                self.assertEqual(response.json()["correlation_id"], "relay-correlation")
                self.assertEqual(response.headers["X-Correlation-ID"], "relay-correlation")
                self.assertFalse(runtime.authority_state.exists())

    def test_end_connection_succeeds_when_relay_teardown_sync_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                with patch.object(runtime, "authoritative_room", side_effect=RelayError(
                        "relay unavailable: temporary DNS failure")):
                    response = client.post("/api/v1/session/stop")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "stopped")

    def test_retry_without_retained_session_fails_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                response = client.post("/api/v1/app/retry")
                self.assertEqual(response.status_code, 409)

    def test_structured_relay_error_and_contract_gate_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                healthy = {
                    "status": "ready", "room_contract": "room-control.v1",
                    "rfu_contract": "rfu-tunnel.v1",
                    "capabilities": ["manual-switch-role.v1"],
                }
                with patch("switchtrade.control.RelayClient.health", return_value=healthy), \
                        patch.object(runtime.relay, "create_trade_room", side_effect=RelayError(
                            "trade room is full", status=409, code="room_full", stage="room",
                            recoverable=False, primary_action="choose_another_room")):
                    response = client.post("/api/v1/trade-room", json={
                        "name": "Room", "visibility": "private", "trainer_display_name": "Leaf",
                        "game": "LeafGreen", "language": "English",
                    })
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["code"], "room_full")
                self.assertEqual(response.json()["stage"], "room")
                self.assertFalse(response.json()["recoverable"])
                self.assertTrue(response.json()["correlation_id"])

                runtime.next_capability_probe = 0
                with patch("switchtrade.control.RelayClient.health", return_value={
                        **healthy, "room_contract": "room-control.v2"}), patch.object(
                        runtime.relay, "create_trade_room") as create:
                    incompatible = client.post("/api/v1/trade-room", json={
                        "name": "Room", "visibility": "private", "trainer_display_name": "Leaf",
                        "game": "LeafGreen", "language": "English",
                    })
                self.assertEqual(incompatible.status_code, 503, incompatible.text)
                self.assertEqual(incompatible.json()["code"], "relay_contract_incompatible")
                create.assert_not_called()

    def test_retry_reconciles_authoritative_attempt_without_type_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "m" * 43, "reconnect_token": "r" * 43,
                })
                runtime.endpoint_session = "ABC123"
                room = {
                    "room_id": "room-1", "room_code": "ABC123", "room_version": 4,
                    "members": [{"is_local": True, "seat": "member_a",
                                 "switch_room_role": "creator"}],
                    "attempt": {"attempt_id": "attempt-1", "phase": "connecting_switches",
                                "role_locked": True, "local_switch_role": "creator"},
                }
                process = MagicMock()
                process.pid = 1234
                process.poll.return_value = None
                with patch.object(runtime, "authoritative_room", return_value=room), patch(
                        "switchtrade.control.subprocess.Popen", return_value=process) as popen:
                    response = client.post("/api/v1/app/retry")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["session_id"], "ABC123")
                popen.assert_called_once()

    def test_repair_action_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                rejected = client.post("/api/v1/app/repair", json={"action": "run_shell"})
                self.assertEqual(rejected.status_code, 422)
                with patch("switchtrade.control.subprocess.run") as run:
                    run.return_value.returncode = 0
                    accepted = client.post(
                        "/api/v1/app/repair", json={"action": "recheck_adapter"})
                self.assertEqual(accepted.status_code, 200, accepted.text)
                command = run.call_args.args[0]
                self.assertNotIsInstance(command, str)
                self.assertIn("wsl-radio-prepare.sh", command[0])
                self.assertIn("--reset-on-rx-failure", command)

    def test_endpoint_command_keeps_seat_and_switch_role_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = endpoint_command(
                "member_a", "ABC123", "http://127.0.0.1:8788",
                state_file=Path(temporary) / "state.json",
                switch_room_role="finder",
                party_state_file=Path(temporary) / "parties.json",
                attempt_id="attempt-1",
            )
            self.assertIn("--tunnel-seat", command)
            self.assertIn("member_a", command)
            self.assertIn("--switch-room-role", command)
            self.assertIn("finder", command)

    def test_hardware_profiles_publish_engine_availability_and_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                body = client.get("/api/hardware/profiles").json()
                self.assertEqual(len(body["profiles"]), 9)
                self.assertEqual(
                    [engine["id"] for engine in body["host_engines"] if engine["selectable"]],
                    ["ldn"],
                )
                candidate = next(
                    profile for profile in body["profiles"] if profile["usb_id"] == "0e8d:7610")
                self.assertTrue(candidate["experimental"])
                self.assertTrue(candidate["selectable"])
                self.assertEqual(candidate["host_engine"], "ldn")

    def test_hardware_diagnostic_api_returns_machine_readable_report(self):
        fake_report = {
            "contract_version": "hardware-diagnostic.v1",
            "run_id": "20260826T000000Z-1234abcd",
            "overall_status": "partial",
            "stages": [],
            "incompatibilities": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = json.dumps(fake_report) + "\n"
                    run.return_value.stderr = ""
                    response = client.post(
                        "/api/v1/hardware/diagnostics",
                        json={"usb_id": "0e8d:7610", "mode": "quick"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["report"]["overall_status"], "partial")
                self.assertIn("switchtrade.hardware_diagnostics", run.call_args.args[0])

    def test_detected_experimental_adapter_can_be_selected_without_confirmation(self):
        usbipd_state = {
            "Devices": [
                {
                    "BusId": "4-20", "ClientIPAddress": None,
                    "Description": "ALFA AWUS036ACHM",
                    "InstanceId": r"USB\VID_0E8D&PID_7610\TEST",
                },
                {
                    "BusId": "4-21", "ClientIPAddress": None,
                    "Description": "Realtek RTL8188EU",
                    "InstanceId": r"USB\VID_0BDA&PID_8179\TEST",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = json.dumps(usbipd_state)
                    devices = client.get("/api/v1/hardware/devices")
                    self.assertEqual(devices.status_code, 200, devices.text)
                    by_id = {item["usb_id"]: item for item in devices.json()["devices"]}
                    self.assertTrue(by_id["0e8d:7610"]["selectable"])
                    self.assertTrue(by_id["0e8d:7610"]["experimental"])
                    self.assertFalse(by_id["0bda:8179"]["selectable"])
                    selected = client.post("/api/v1/hardware/selection", json={
                        "usb_id": "0e8d:7610", "bus_id": "4-20",
                    })
                    self.assertEqual(selected.status_code, 200, selected.text)


if __name__ == "__main__":
    unittest.main()
