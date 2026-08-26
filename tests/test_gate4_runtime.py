from pathlib import Path
import base64
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
                self.assertEqual(body["release_id"], "development")
                self.assertTrue(body["compatible"])
                self.assertEqual(set(body["states"]),
                                 {"control", "relay", "radio", "session", "decoder"})
                self.assertEqual(body["states"]["control"]["status"], "ready")
                self.assertNotIn("passcode", str(body).lower())

    def test_packaged_readiness_advertises_exact_immutable_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".switchtrade-release.json").write_text(
                json.dumps({"schema": 1, "release_id": "release-b"}), encoding="utf-8")
            with patch.dict(os.environ, {"SWITCHTRADE_RELEASE_ROOT": temporary}):
                with TestClient(create_app(runs_root=root / "runs")) as client:
                    body = client.get("/api/v1/app/readiness").json()
                    self.assertEqual(body["release_id"], "release-b")

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
                for origin in (
                        "https://untrusted.example", "http://127.0.0.1:3000",
                        "http://localhost:49152", "null"):
                    response = client.post(
                        "/api/v1/session/stop", headers={"Origin": origin})
                    self.assertEqual(response.status_code, 403, origin)
                    self.assertEqual(response.json()["code"], "cross_origin_blocked")
                self.assertEqual(client.post("/api/v1/session/stop").status_code, 200)

    def test_unhandled_control_error_is_a_redacted_structured_envelope(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary), raise_server_exceptions=False) as client:
                with patch("switchtrade.control.subprocess.run",
                           side_effect=RuntimeError("CANARY_INTERNAL_DETAIL")):
                    response = client.get(
                        "/api/v1/hardware/devices",
                        headers={"X-Correlation-ID": "cca-generic-handler"})
                self.assertEqual(response.status_code, 500, response.text)
                body = response.json()
                self.assertEqual(body["code"], "control_internal_error")
                self.assertEqual(body["stage"], "control")
                self.assertTrue(body["recoverable"])
                self.assertEqual(body["primary_action"], "export_support_bundle")
                self.assertEqual(body["correlation_id"], "cca-generic-handler")
                self.assertEqual(response.headers["X-Correlation-ID"], "cca-generic-handler")
                self.assertNotIn("CANARY_INTERNAL_DETAIL", response.text)
                events = client.app.state.runtime.log._events.read_text(encoding="utf-8")
                self.assertIn('"error_type":"RuntimeError"', events)
                self.assertNotIn("CANARY_INTERNAL_DETAIL", events)

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

    def test_invalid_credentials_do_not_clear_unconfirmed_remote_authority(self):
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
                        self.assertEqual(response.status_code, 401, response.text)
                        self.assertEqual(response.json()["code"], "reconnect_credential_invalid")
                        self.assertTrue(runtime.authority_state.exists())

    def test_release_reloads_rotated_member_credential_before_remote_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "stale-member", "reconnect_token": "stale-reconnect",
                })
                authoritative_room = {
                    "contract_version": "room-control.v1", "room_id": "room-1",
                    "room_code": "ABC123", "room_version": 7, "members": [],
                }
                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401,
                        code="member_credential_invalid", stage="authentication",
                        primary_action="reconnect")), patch.object(
                        runtime.relay, "reconnect_trade_room", return_value={
                            "room": authoritative_room, "member_token": "rotated-member",
                            "reconnect_token": "rotated-reconnect",
                        }), patch.object(runtime.relay, "room_command", return_value={
                            **authoritative_room, "room_version": 8, "state": "closed",
                        }) as room_command:
                    response = client.delete("/api/v1/trade-room")
                self.assertEqual(response.status_code, 200, response.text)
                room_command.assert_called_once_with(
                    "room-1", "rotated-member", "", None, method="DELETE",
                    expected_version=7)
                self.assertFalse(runtime.authority_state.exists())

    def test_active_authority_cannot_be_overwritten_by_another_room(self):
        room = {
            "contract_version": "room-control.v1", "room_id": "room-1",
            "room_code": "ABC123", "room_version": 7, "state": "ready_check",
            "members": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.save_authority({
                    "room": room, "member_token": "member-secret",
                    "reconnect_token": "reconnect-secret",
                })
                retained = runtime.authority_state.read_text(encoding="utf-8")
                with patch.object(runtime, "authoritative_room", return_value=room), \
                        patch.object(runtime.relay, "create_trade_room") as create, \
                        patch.object(runtime.relay, "join_trade_room") as join, \
                        patch.object(runtime.relay, "join_public_trade_room") as public_join:
                    responses = [
                        client.post("/api/v1/trade-room", json={
                            "name": "Replacement", "visibility": "private",
                            "trainer_display_name": "Leaf", "game": "LeafGreen",
                            "language": "English",
                        }),
                        client.post("/api/v1/trade-room/join", json={
                            "passcode": "DEF456", "trainer_display_name": "Red",
                        }),
                        client.post("/api/v1/public-trade-rooms/listing-2/join", json={
                            "trainer_display_name": "Red",
                        }),
                    ]
                for response in responses:
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()["code"], "room_already_active")
                    self.assertEqual(response.json()["primary_action"], "resume_room")
                create.assert_not_called()
                join.assert_not_called()
                public_join.assert_not_called()
                self.assertEqual(runtime.authority_state.read_text(encoding="utf-8"), retained)

    def test_attempt_failures_are_exposed_as_stable_recovery_contracts(self):
        room = {
            "contract_version": "room-control.v1", "room_id": "room-1",
            "room_code": "ABC123", "room_version": 8, "state": "ready_check",
            "members": [{"member_id": "member-1", "is_local": True,
                         "seat": "member_a", "online_state": "online",
                         "ready_state": "not_ready", "switch_room_role": None}],
            "attempt": {"attempt_id": "attempt-1", "phase": "failed",
                        "role_locked": True},
        }
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                for code in ("relay.restart", "relay.peer_lost"):
                    with self.subTest(code=code):
                        failed_room = {**room, "attempt": {
                            **room["attempt"], "recoverable_error": code,
                        }}
                        runtime.save_authority({
                            "room": failed_room, "member_token": "member-secret",
                            "reconnect_token": "reconnect-secret",
                        })
                        with patch.object(runtime.relay, "room", return_value=failed_room), \
                                patch.object(runtime.relay, "room_command",
                                             return_value=failed_room):
                            response = client.get("/api/v1/trade-room")
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["attempt"]["failure"], {
                            "code": code, "stage": "relay", "recoverable": True,
                            "primary_action": "retry",
                        })

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
                verification_calls = 0

                def verify_after_launch(_endpoint):
                    nonlocal verification_calls
                    verification_calls += 1
                    return 1234 if verification_calls >= 4 else None

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "_verified_endpoint_pid", side_effect=verify_after_launch), patch(
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

    def test_windows_control_adopts_and_stops_verified_wsl_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "runtime" / "endpoint-state.json"
            state_path.parent.mkdir(parents=True)
            nonce = "a" * 32
            state_path.write_text(json.dumps({
                "state": "trading_room", "pid": 4321, "process_kind": "rfu-endpoint",
                "wsl_distro": "SwitchTrade", "session_id": "ABC123",
                "launch_nonce": nonce, "process_start_ticks": 9876,
            }), encoding="utf-8")
            probe_calls = 0
            real_run = __import__("subprocess").run
            stat_value = "4321 (python) " + " ".join(["S", *(["0"] * 18), "9876"])
            command_line = b"python\0-m\0switchtrade.endpoint\0--session-id\0ABC123\0--launch-nonce\0" + nonce.encode() + b"\0"

            def wsl_process(command, **kwargs):
                nonlocal probe_calls
                if command and command[0] == "wsl.exe" and "python3" in command:
                    probe_calls += 1
                    if probe_calls <= 4:
                        return MagicMock(returncode=0, stdout=json.dumps({
                            "stat": stat_value,
                            "cmdline": base64.b64encode(command_line).decode("ascii"),
                        }))
                    return MagicMock(returncode=1, stdout="")
                if command and command[0] == "wsl.exe" and "kill" in command:
                    return MagicMock(returncode=0, stdout=b"")
                return real_run(command, **kwargs)

            with patch.dict(os.environ, {"SWITCHTRADE_WSL_DISTRO": "SwitchTrade"}), patch(
                    "switchtrade.control.subprocess.run", side_effect=wsl_process) as run:
                with TestClient(create_app(runs_root=temporary)) as client:
                    runtime = client.app.state.runtime
                    self.assertEqual(runtime.endpoint_session, "ABC123")
                    self.assertTrue(runtime.endpoint_running())
                    runtime.stop_endpoint()
                    self.assertFalse(runtime.endpoint_running())
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any("kill" in command and "-TERM" in command for command in commands))

    def test_windows_control_rejects_endpoint_from_another_wsl_distro(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "runtime" / "endpoint-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({
                "state": "trading_room", "pid": 4321, "process_kind": "rfu-endpoint",
                "wsl_distro": "ForeignDistro", "session_id": "ABC123",
                "launch_nonce": "b" * 32, "process_start_ticks": 9876,
            }), encoding="utf-8")
            real_run = __import__("subprocess").run

            def passthrough(command, **kwargs):
                if command and command[0] == "wsl.exe":
                    self.fail(f"foreign endpoint triggered a WSL command: {command}")
                return real_run(command, **kwargs)

            with patch.dict(os.environ, {"SWITCHTRADE_WSL_DISTRO": "SwitchTrade"}), patch(
                    "switchtrade.control.subprocess.run", side_effect=passthrough) as run:
                with TestClient(create_app(runs_root=temporary)) as client:
                    self.assertFalse(client.app.state.runtime.endpoint_running())
            self.assertFalse(any(call.args[0][0] == "wsl.exe" for call in run.call_args_list))

    def test_windows_control_rejects_cmdline_substring_impostor(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "runtime" / "endpoint-state.json"
            state_path.parent.mkdir(parents=True)
            nonce = "c" * 32
            state_path.write_text(json.dumps({
                "state": "trading_room", "pid": 4321, "process_kind": "rfu-endpoint",
                "wsl_distro": "SwitchTrade", "session_id": "ABC123",
                "launch_nonce": nonce, "process_start_ticks": 9876,
            }), encoding="utf-8")
            stat_value = "4321 (python) " + " ".join(["S", *(["0"] * 18), "9876"])
            impostor = base64.b64encode(b"python\0-c\0print('switchtrade.endpoint')\0").decode("ascii")
            result = MagicMock(returncode=0, stdout=json.dumps({
                "stat": stat_value, "cmdline": impostor,
            }))
            with patch.dict(os.environ, {"SWITCHTRADE_WSL_DISTRO": "SwitchTrade"}), patch(
                    "switchtrade.control.subprocess.run", return_value=result) as run:
                with TestClient(create_app(runs_root=temporary)) as client:
                    runtime = client.app.state.runtime
                    self.assertFalse(runtime.endpoint_running())
                    runtime.stop_endpoint()
            self.assertFalse(any("kill" in call.args[0] for call in run.call_args_list))

    def test_windows_endpoint_early_exit_is_reported_before_starting(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                process = MagicMock(pid=1234)
                process.poll.return_value = 73
                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", return_value=process):
                    response = client.post("/api/session/start", json={
                        "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                    })
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["code"], "endpoint_start_failed")
            self.assertEqual(response.json()["stage"], "endpoint")

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
                        "instance_id": r"USB\VID_0E8D&PID_7610\TEST",
                    })
                    self.assertEqual(selected.status_code, 200, selected.text)
                    persisted = client.app.state.runtime.read_hardware_selection()
                    self.assertEqual(persisted["instance_id"],
                                     r"USB\VID_0E8D&PID_7610\TEST")

    def test_selected_instance_resolves_a_changed_bus_id_before_attach(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-B"
        other_instance = r"USB\VID_0BDA&PID_818B\RADIO-A"
        current_bus = ["9-7"]
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [
                    {
                        "BusId": "4-20", "ClientIPAddress": None,
                        "Description": "Realtek RTL8192EU", "InstanceId": other_instance,
                    },
                    {
                        "BusId": current_bus[0], "ClientIPAddress": None,
                        "Description": "Realtek RTL8192EU", "InstanceId": instance_id,
                    },
                ]})
            return result

        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run", side_effect=run):
                    runtime = client.app.state.runtime
                    runtime.hardware_selection_file.write_bytes(
                        b"\xef\xbb\xbf" + json.dumps({
                            "schema": 1, "usb_id": "0bda:818b", "bus_id": "4-21",
                            "instance_id": instance_id,
                        }).encode("utf-8"))
                    devices = client.get("/api/v1/hardware/devices").json()["devices"]
                    selected = [device for device in devices if device["selected"]]
                    self.assertEqual([device["instance_id"] for device in selected], [instance_id])
                    repaired = client.post(
                        "/api/v1/app/repair", json={"action": "recheck_adapter"})
                    self.assertEqual(repaired.status_code, 200, repaired.text)
                    self.assertTrue(any(command[:2] == ["usbipd.exe", "attach"] and
                                        command[-1] == "9-7" for command in commands))
                    persisted = client.app.state.runtime.read_hardware_selection()
                    self.assertEqual(persisted["instance_id"], instance_id)
                    self.assertEqual(persisted["bus_id"], "9-7")

    def test_inventory_does_not_present_unpersisted_fallback_as_selected(self):
        usbipd_state = {"Devices": [{
            "BusId": "4-20", "ClientIPAddress": None,
            "Description": "Realtek RTL8192EU",
            "InstanceId": r"USB\VID_0BDA&PID_818B\RADIO-A",
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = json.dumps(usbipd_state)
                    devices = client.get("/api/v1/hardware/devices").json()["devices"]
                    self.assertFalse(devices[0]["selected"])

    def test_control_reads_powershell_51_bom_hardware_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.hardware_selection_file.write_bytes(
                    b"\xef\xbb\xbf" + json.dumps({
                        "schema": 1, "usb_id": "0bda:818b", "bus_id": "9-7",
                        "instance_id": r"USB\VID_0BDA&PID_818B\RADIO-A",
                    }).encode("utf-8"))
                self.assertEqual(runtime.read_hardware_selection()["bus_id"], "9-7")


if __name__ == "__main__":
    unittest.main()
