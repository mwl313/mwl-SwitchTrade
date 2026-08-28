from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from switchtrade.control import Group, Runtime, create_app, endpoint_command
from switchtrade.relay_client import RelayClient, RelayError


def acknowledge_initialized(runtime, command, pid: int) -> None:
    nonce = command[command.index("--launch-nonce") + 1]
    session_id = command[command.index("--session-id") + 1]
    attempt_id = command[command.index("--attempt-id") + 1]
    runtime.endpoint_launch_ack.write_text(json.dumps({
        "schema": 2, "stage": "radio_gate_passed",
        "launch_nonce": nonce, "launcher_pid": pid,
    }), encoding="utf-8")
    runtime.endpoint_state.write_text(json.dumps({
        "state": "initializing", "pid": pid + 10000,
        "process_kind": "rfu-endpoint", "session_id": session_id,
        "attempt_id": attempt_id, "launch_nonce": nonce,
        "process_start_ticks": 12345,
    }), encoding="utf-8")


class Gate4RuntimeContractTests(unittest.TestCase):
    @unittest.skipUnless(os.name != "nt" and shutil.which("bash"),
                         "requires a native POSIX bash with flock and timeout")
    def test_endpoint_shell_holds_launch_lock_until_child_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            source = Path(__file__).resolve().parents[1] / "scripts" / "run-beta-endpoint.sh"
            launcher = scripts / "run-beta-endpoint.sh"
            launcher.write_bytes(source.read_bytes())
            prep = scripts / "wsl-radio-prepare.sh"
            prep.write_text(
                "#!/usr/bin/env bash\n"
                "sleep 0.25\n"
                "while [[ $# -gt 0 && $1 != -- ]]; do shift; done\n"
                "shift\nexec \"$@\"\n",
                encoding="utf-8",
            )
            child = root / "endpoint-child.sh"
            child.write_text("#!/usr/bin/env bash\nsleep 30\n", encoding="utf-8")
            for executable in (launcher, prep, child):
                executable.chmod(0o755)
            runtime = root / "runtime"
            runtime.mkdir()
            environment = os.environ.copy()
            environment.update({
                "SWITCHTRADE_RUNTIME_DIR": runtime.as_posix(),
                "SWITCHTRADE_PYTHON": child.as_posix(),
                "SWITCHTRADE_ENDPOINT_TIMEOUT": "30",
            })

            def command(nonce: str, acknowledgement: Path) -> list[str]:
                return [
                    "bash", launcher.as_posix(), "--role", "host",
                    "--launch-nonce", nonce,
                    "--launch-ack-file", acknowledgement.as_posix(),
                ]

            first_ack = runtime / "first.json"
            first = subprocess.Popen(command("1" * 32, first_ack), env=environment)
            try:
                time.sleep(0.05)
                self.assertFalse(first_ack.exists(), "launch acknowledged before the radio gate")
                deadline = time.monotonic() + 3
                while not first_ack.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(first_ack.exists(), "first launch did not acknowledge")
                acknowledgement = json.loads(first_ack.read_text(encoding="utf-8"))
                self.assertEqual(acknowledgement["schema"], 2)
                self.assertEqual(acknowledgement["stage"], "radio_gate_passed")
                second_ack = runtime / "second.json"
                second = subprocess.run(
                    command("2" * 32, second_ack), env=environment,
                    capture_output=True, text=True, timeout=3,
                )
                self.assertNotEqual(second.returncode, 0)
                self.assertFalse(second_ack.exists())
                self.assertIn("already running", second.stderr)
            finally:
                first.terminate()
                first.wait(timeout=3)

            third_ack = runtime / "third.json"
            third = subprocess.Popen(command("3" * 32, third_ack), env=environment)
            try:
                deadline = time.monotonic() + 3
                while not third_ack.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(third_ack.exists(), "lock was not released after exit")
            finally:
                third.terminate()
                third.wait(timeout=3)

    def test_pidfd_is_pinned_before_endpoint_identity_check(self):
        endpoint = {"pid": 4321}
        events = []

        def open_pidfd(pid):
            events.append(("open", pid))
            return 99

        def verify(_endpoint):
            events.append(("verify", _endpoint))
            return 4321

        def send_pidfd(descriptor, selected_signal):
            events.append(("signal", descriptor, selected_signal))

        with patch("switchtrade.control.os.name", "posix"), patch.object(
                os, "pidfd_open", side_effect=open_pidfd, create=True), patch.object(
                signal, "pidfd_send_signal", side_effect=send_pidfd, create=True), patch.object(
                os, "close", side_effect=lambda descriptor: events.append(("close", descriptor))), patch.object(
                Runtime, "_verified_endpoint_pid", side_effect=verify), patch.object(
                os, "kill") as kill:
            Runtime._signal_endpoint_pid(4321, "TERM", endpoint)

        self.assertEqual([event[0] for event in events], ["open", "verify", "signal", "close"])
        self.assertEqual(events[2][1:], (99, signal.SIGTERM))
        kill.assert_not_called()

        events.clear()
        with patch("switchtrade.control.os.name", "posix"), patch.object(
                os, "pidfd_open", side_effect=open_pidfd, create=True), patch.object(
                signal, "pidfd_send_signal", side_effect=send_pidfd, create=True), patch.object(
                os, "close", side_effect=lambda descriptor: events.append(("close", descriptor))), patch.object(
                Runtime, "_verified_endpoint_pid", return_value=None), patch.object(
                os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                Runtime._signal_endpoint_pid(4321, "TERM", endpoint)
        self.assertEqual([event[0] for event in events], ["open", "signal", "close"])
        self.assertEqual(events[1][1:], (99, 0))
        kill.assert_not_called()

    def test_pidfd_disappearance_is_idempotent_and_stop_clears_session(self):
        endpoint = {"pid": 4321, "process_kind": "rfu-endpoint"}
        with patch("switchtrade.control.os.name", "posix"), patch.object(
                os, "pidfd_open", return_value=99, create=True), patch.object(
                signal, "pidfd_send_signal", side_effect=ProcessLookupError, create=True), patch.object(
                Runtime, "_verified_endpoint_pid", return_value=None), patch.object(os, "close") as close:
            self.assertFalse(Runtime._signal_endpoint_pid(4321, "TERM", endpoint))
        close.assert_called_once_with(99)

        runtime = Runtime.__new__(Runtime)
        runtime.lock = threading.RLock()
        runtime.launch_cancel_generation = 0
        runtime.endpoint = None
        runtime.endpoint_session = "ABC123"
        runtime.read_endpoint = lambda: endpoint
        with patch("switchtrade.control.os.name", "posix"), patch.object(
                Runtime, "_signal_endpoint_pid", return_value=False) as signal_endpoint:
            runtime.stop_endpoint()
        signal_endpoint.assert_called_once_with(4321, "TERM", endpoint)
        self.assertIsNone(runtime.endpoint_session)

    def test_windows_wsl_signal_uses_one_pinned_helper_and_rejects_reuse(self):
        endpoint = {
            "pid": 4321, "process_kind": "rfu-endpoint", "wsl_distro": "SwitchTrade",
            "session_id": "ABC123", "launch_nonce": "a" * 32,
            "process_start_ticks": 9876,
        }
        with patch("switchtrade.control.os.name", "nt"), patch.dict(
                os.environ, {"SWITCHTRADE_WSL_DISTRO": "SwitchTrade"}), patch(
                "switchtrade.control.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="", stderr="")) as run, patch.object(
                Runtime, "_verified_endpoint_pid") as verify:
            self.assertTrue(Runtime._signal_endpoint_pid(4321, "TERM", endpoint))
        verify.assert_not_called()
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["wsl.exe", "-d", "SwitchTrade", "-u", "root", "--"])
        self.assertNotIn("kill", command)
        helper = command[command.index("-c") + 1]
        compile(helper, "<wsl-pidfd-helper>", "exec")
        self.assertLess(helper.index("pidfd_open"), helper.index("/proc"))
        self.assertIn("pidfd_send_signal", helper)

        with patch("switchtrade.control.os.name", "nt"), patch.dict(
                os.environ, {"SWITCHTRADE_WSL_DISTRO": "SwitchTrade"}), patch(
                "switchtrade.control.subprocess.run",
                return_value=MagicMock(returncode=4, stdout="", stderr="")) as reused:
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                Runtime._signal_endpoint_pid(4321, "TERM", endpoint)
        self.assertEqual(reused.call_count, 1)
        self.assertNotIn("kill", reused.call_args.args[0])

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

    def test_stop_clears_terminal_snapshot_and_readiness_stays_idle_without_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.write_endpoint({
                    "state": "failed", "attempt_id": "attempt-1",
                    "error_code": "relay.peer_lost", "error": "peer lost",
                    "failure_stage": "relay", "recovery_action": "retry",
                })

                failed = client.get("/api/v1/app/readiness").json()
                self.assertEqual(failed["states"]["relay"]["user_message"], "peer lost")
                self.assertEqual(failed["states"]["session"]["user_message"], "peer lost")

                stopped = client.post("/api/v1/session/stop")
                self.assertEqual(stopped.status_code, 200, stopped.text)
                self.assertEqual(client.get("/api/status").json()["status"], "ready")
                for _ in range(3):
                    readiness = client.get("/api/v1/app/readiness").json()
                    self.assertIsNone(readiness["failure"])
                    self.assertEqual(readiness["states"]["session"]["status"], "unavailable")
                events = runtime.log._events.read_text(encoding="utf-8")
                self.assertNotIn("authority_phase_sync_failed", events)

    def test_authoritative_peer_loss_does_not_overwrite_local_radio_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Runtime(Path("config/wsl-radio-hardware.tsv"), Path(temporary),
                              "http://127.0.0.1:8788")
            runtime.write_endpoint({
                "state": "failed", "attempt_id": "attempt-1",
                "error_code": "radio.switch_room_not_found", "error": "no room",
                "failure_stage": "radio", "recovery_action": "recreate_switch_room",
            })
            runtime.record_authoritative_failure({
                "attempt_id": "attempt-1", "recoverable_error": "relay.peer_lost",
            })
            self.assertEqual(
                runtime.read_endpoint()["error_code"], "radio.switch_room_not_found")

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

    def test_support_bundle_records_selected_shared_and_attached_gates(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-A"
        usbipd_state = {"Devices": [{
            "BusId": "2-4", "ClientIPAddress": None, "PersistedGuid": None,
            "StubInstanceId": None, "Description": "Realtek RTL8192EU",
            "InstanceId": instance_id,
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run") as run, patch.object(
                        client.app.state.runtime.relay, "upload_diagnostic", return_value={
                            "status": "stored", "upload_id": "support-upload",
                            "correlation_id": "support-correlation",
                        }) as upload:
                    run.return_value = MagicMock(
                        returncode=0, stdout=json.dumps(usbipd_state), stderr="")
                    client.post("/api/v1/hardware/selection", json={
                        "usb_id": "0bda:818b", "bus_id": "2-4",
                        "instance_id": instance_id,
                    })
                    response = client.post("/api/v1/support-bundle").json()
                    bundle = response["path"]
                with zipfile.ZipFile(bundle) as archive:
                    summary = json.loads(archive.read("runtime-summary.json"))
                exported = base64.b64decode(response["content_base64"])
                with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                    self.assertIn("privacy-manifest.json", archive.namelist())
                upload.assert_called_once()
        self.assertEqual(summary["hardware"]["selected"]["usb_id"], "0bda:818b")
        self.assertFalse(summary["hardware"]["selected"]["shared"])
        self.assertFalse(summary["hardware"]["selected"]["attached"])
        self.assertNotIn("instance_id", summary["hardware"]["selected"])

    def test_support_bundle_remains_downloadable_when_relay_upload_is_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client, patch.object(
                    client.app.state.runtime.relay, "upload_diagnostic",
                    side_effect=RelayError("relay offline")):
                response = client.post("/api/v1/support-bundle")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["relay_upload"]["status"], "unavailable")
        self.assertTrue(body["filename"].startswith("SwitchTrade-support-"))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["content_base64"]))) as archive:
            self.assertIn("privacy-manifest.json", archive.namelist())

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

    def test_reconnect_deadline_preserves_exact_envelope_and_clears_terminal_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_state.write_text(json.dumps({
                    "state": "trading_room", "pid": 4321,
                    "process_kind": "rfu-endpoint", "session_id": "ABC123",
                }), encoding="utf-8")
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "expired-member", "reconnect_token": "expired-reconnect",
                })
                transitions = []
                clear_authority = runtime.clear_authority

                def stop_endpoint():
                    transitions.append(("stop", runtime.endpoint_session))
                    runtime.endpoint_state.unlink(missing_ok=True)
                    runtime.endpoint = None
                    runtime.endpoint_session = None

                def clear_terminal_authority():
                    transitions.append(("clear", runtime.endpoint_session))
                    clear_authority()

                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401,
                        code="member_credential_invalid", stage="authentication",
                        primary_action="reconnect")), patch.object(
                        runtime.relay, "reconnect_trade_room", side_effect=RelayError(
                            "reconnect deadline expired", status=410,
                            code="reconnect_deadline_expired", stage="authentication",
                            recoverable=False, primary_action="rejoin_room",
                            correlation_id="deadline-correlation")), patch.object(
                        runtime, "_verified_endpoint_pid", return_value=4321), patch.object(
                        runtime, "stop_endpoint", side_effect=stop_endpoint), patch.object(
                        runtime, "clear_authority", side_effect=clear_terminal_authority):
                    response = client.get("/api/v1/trade-room")
                self.assertEqual(response.status_code, 410, response.text)
                self.assertEqual(response.json(), {
                    "code": "reconnect_deadline_expired",
                    "message": "reconnect deadline expired",
                    "detail": "reconnect deadline expired",
                    "stage": "authentication", "recoverable": False,
                    "primary_action": "rejoin_room",
                    "correlation_id": "deadline-correlation",
                })
                self.assertEqual(transitions, [("stop", "ABC123"), ("clear", None)])
                self.assertFalse(runtime.authority_state.exists())
                self.assertFalse(runtime.endpoint_state.exists())

                process = MagicMock(pid=8765)
                process.poll.return_value = None

                def acknowledge_relaunch(command, **_kwargs):
                    acknowledge_initialized(runtime, command, 8765)
                    return process

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=acknowledge_relaunch):
                    relaunched = client.post("/api/session/start", json={
                        "role": "host", "passcode": "XYZ789", "usb_id": "0bda:818b",
                    })
                self.assertEqual(relaunched.status_code, 200, relaunched.text)
                self.assertEqual(runtime.endpoint_session, "XYZ789")

    def test_readiness_does_not_consume_terminal_reconnect_before_room_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_state.write_text(json.dumps({
                    "state": "completed", "pid": 4321,
                    "process_kind": "rfu-endpoint", "session_id": "ABC123",
                }), encoding="utf-8")
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "expired-member", "reconnect_token": "expired-reconnect",
                })
                transitions = []
                clear_authority = runtime.clear_authority

                def stop_endpoint():
                    transitions.append("stop")
                    runtime.endpoint_state.unlink(missing_ok=True)
                    runtime.endpoint = None
                    runtime.endpoint_session = None

                def clear_terminal_authority():
                    transitions.append("clear")
                    clear_authority()

                terminal = RelayError(
                    "reconnect deadline expired", status=410,
                    code="reconnect_deadline_expired", stage="authentication",
                    recoverable=False, primary_action="rejoin_room",
                    correlation_id="deadline-correlation")
                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401,
                        code="member_credential_invalid", stage="authentication",
                        primary_action="reconnect")), patch.object(
                        runtime.relay, "reconnect_trade_room", side_effect=terminal), patch.object(
                        runtime, "_verified_endpoint_pid", return_value=4321), patch.object(
                        runtime, "stop_endpoint", side_effect=stop_endpoint) as stop, patch.object(
                        runtime, "clear_authority", side_effect=clear_terminal_authority):
                    readiness = client.get("/api/v1/app/readiness")
                    self.assertEqual(readiness.status_code, 200, readiness.text)
                    self.assertTrue(runtime.authority_state.exists())
                    self.assertEqual(runtime.endpoint_session, "ABC123")
                    stop.assert_not_called()

                    room = client.get("/api/v1/trade-room")
                self.assertEqual(room.status_code, 410, room.text)
                self.assertEqual(room.json()["code"], "reconnect_deadline_expired")
                self.assertEqual(room.json()["stage"], "authentication")
                self.assertEqual(room.json()["primary_action"], "rejoin_room")
                self.assertEqual(room.json()["correlation_id"], "deadline-correlation")
                self.assertEqual(transitions, ["stop", "clear"])
                self.assertFalse(runtime.authority_state.exists())
                self.assertFalse(runtime.endpoint_state.exists())

    def test_terminal_credentials_do_not_stop_reconciled_endpoint_for_another_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_state.write_text(json.dumps({
                    "state": "trading_room", "pid": 4321,
                    "process_kind": "rfu-endpoint", "session_id": "XYZ789",
                }), encoding="utf-8")
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "expired-member", "reconnect_token": "expired-reconnect",
                })
                with patch.object(runtime.relay, "room", side_effect=RelayError(
                        "member credential is invalid", status=401)), patch.object(
                        runtime.relay, "reconnect_trade_room", side_effect=RelayError(
                            "reconnect deadline expired", status=410,
                            code="reconnect_deadline_expired", stage="authentication",
                            recoverable=False, primary_action="rejoin_room")), patch.object(
                        runtime, "_verified_endpoint_pid", return_value=4321), patch.object(
                        runtime, "stop_endpoint") as stop:
                    response = client.get("/api/v1/trade-room")
                    self.assertEqual(response.status_code, 410, response.text)
                    stop.assert_not_called()
                    self.assertEqual(runtime.endpoint_session, "XYZ789")
                    self.assertTrue(runtime.endpoint_state.exists())
                    self.assertFalse(runtime.authority_state.exists())
                    runtime.endpoint_state.unlink()
                    runtime.endpoint_session = None

    def test_explicit_local_authority_abandon_stops_endpoint_and_clears_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.save_authority({
                    "room": {"contract_version": "room-control.v1",
                             "room_id": "room-1", "room_code": "ABC123"},
                    "member_token": "unmatched-member", "reconnect_token": "unmatched-reconnect",
                })
                with patch.object(runtime, "stop_endpoint") as stop_endpoint:
                    response = client.delete("/api/v1/trade-room/local-authority")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "abandoned")
                stop_endpoint.assert_called_once_with()
                self.assertFalse(runtime.authority_state.exists())
                self.assertFalse(runtime.member_token_file.exists())

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

                def acknowledge_launch(command, **_kwargs):
                    acknowledge_initialized(runtime, command, 1234)
                    return process

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "_verified_endpoint_pid", side_effect=verify_after_launch), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=acknowledge_launch) as popen:
                    response = client.post("/api/v1/app/retry")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["session_id"], "ABC123")
                popen.assert_called_once()

    def test_repair_action_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                rejected = client.post("/api/v1/app/repair", json={"action": "run_shell"})
                self.assertEqual(rejected.status_code, 422)
                instance_id = r"USB\VID_0BDA&PID_818B\REPAIR"
                client.app.state.runtime.write_hardware_selection(
                    "0bda:818b", instance_id, "4-20")

                def repair_run(command, **_kwargs):
                    if command[:2] == ["usbipd.exe", "state"]:
                        return MagicMock(returncode=0, stdout=json.dumps({"Devices": [{
                            "BusId": "4-20", "ClientIPAddress": "172.20.0.1",
                            "PersistedGuid": "shared-radio", "Description": "RTL8192EU",
                            "InstanceId": instance_id,
                        }]}), stderr="")
                    return MagicMock(returncode=0, stdout="", stderr="")

                with patch("switchtrade.control.subprocess.run", side_effect=repair_run) as run:
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
                if command and command[0] == "wsl.exe" and "pidfd_open" in " ".join(command):
                    return MagicMock(returncode=0, stdout="", stderr="")
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
            self.assertTrue(any("pidfd_open" in " ".join(command) for command in commands))
            self.assertFalse(any("kill" in command for command in commands))

    def test_late_endpoint_state_is_adopted_for_terminal_cleanup_and_relaunch(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.last_authority_heartbeat = time.monotonic()
                runtime.endpoint_state.write_text(json.dumps({
                    "state": "initializing", "pid": 4321,
                    "process_kind": "rfu-endpoint", "session_id": "ABC123",
                }), encoding="utf-8")
                room = {
                    "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
                    "attempt": {"attempt_id": "attempt-1", "phase": "completed"},
                    "members": [],
                }
                adopted = []

                def stop_late_endpoint():
                    adopted.append(runtime.endpoint_session)
                    runtime.endpoint_state.unlink(missing_ok=True)
                    runtime.endpoint = None
                    runtime.endpoint_session = None

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "_verified_endpoint_pid", return_value=4321), patch.object(
                        runtime, "stop_endpoint", side_effect=stop_late_endpoint) as stop:
                    terminal = client.get("/api/v1/trade-room")
                self.assertEqual(terminal.status_code, 200, terminal.text)
                stop.assert_called_once()
                self.assertEqual(adopted, ["ABC123"])

                process = MagicMock(pid=8765)
                process.poll.return_value = None

                def acknowledge_relaunch(command, **_kwargs):
                    acknowledge_initialized(runtime, command, 8765)
                    return process

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=acknowledge_relaunch):
                    relaunched = client.post("/api/session/start", json={
                        "role": "host", "passcode": "XYZ789", "usb_id": "0bda:818b",
                    })
                self.assertEqual(relaunched.status_code, 200, relaunched.text)
                self.assertEqual(runtime.endpoint_session, "XYZ789")

    def test_terminal_room_does_not_stop_reconciled_endpoint_for_another_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_session = "ABC123"
                runtime.last_authority_heartbeat = time.monotonic()
                room = {
                    "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
                    "attempt": {"attempt_id": "attempt-1", "phase": "completed"},
                    "members": [],
                }

                def reconcile_live_endpoint():
                    runtime.endpoint_session = "XYZ789"
                    return True

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "endpoint_running", side_effect=reconcile_live_endpoint) as running, \
                        patch.object(runtime, "stop_endpoint") as stop:
                    response = client.get("/api/v1/trade-room")
                self.assertEqual(response.status_code, 200, response.text)
                running.assert_called_once_with()
                stop.assert_not_called()
                self.assertEqual(runtime.endpoint_session, "XYZ789")

    def test_nonterminal_room_rejects_other_live_session_before_hardware_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_session = "ABC123"
                runtime.last_authority_heartbeat = time.monotonic()
                room = {
                    "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
                    "attempt": {"attempt_id": "attempt-1", "phase": "connecting_switches",
                                "role_locked": True, "local_switch_role": "creator"},
                    "members": [{"is_local": True, "seat": "member_a"}],
                }

                def reconcile_live_endpoint():
                    runtime.endpoint_session = "XYZ789"
                    return True

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "endpoint_running", side_effect=reconcile_live_endpoint), patch.object(
                        runtime, "read_hardware_selection") as hardware_selection:
                    response = client.get("/api/v1/trade-room")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["code"], "session_active")
                self.assertEqual(response.json()["stage"], "session")
                self.assertEqual(response.json()["primary_action"], "end_session")
                hardware_selection.assert_not_called()
                self.assertEqual(runtime.endpoint_session, "XYZ789")

    def test_terminal_room_cleans_disappeared_cached_session_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.endpoint_session = "ABC123"
                runtime.last_authority_heartbeat = time.monotonic()
                room = {
                    "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
                    "attempt": {
                        "attempt_id": "attempt-1", "phase": "failed",
                        "recoverable_error": "radio.switch_room_not_found",
                    },
                    "members": [],
                }

                def clear_disappeared_endpoint():
                    runtime.endpoint = None
                    runtime.endpoint_session = None

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime, "endpoint_running", return_value=False) as running, patch.object(
                        runtime, "stop_endpoint", side_effect=clear_disappeared_endpoint) as stop:
                    response = client.get("/api/v1/trade-room")
                self.assertEqual(response.status_code, 200, response.text)
                running.assert_called_once_with()
                stop.assert_called_once_with()
                self.assertIsNone(runtime.endpoint_session)
                failure = runtime.read_endpoint()
                self.assertEqual(failure["state"], "failed")
                self.assertEqual(failure["error_code"], "radio.switch_room_not_found")
                self.assertEqual(failure["recovery_action"], "recreate_switch_room")
                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime.relay, "room_command") as publish:
                    runtime.sync_authoritative_phase(failure, {})
                publish.assert_not_called()

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

                def fail_before_python(_command, **kwargs):
                    kwargs["stderr"].write(b"ERROR: actual RX gate timed out\n")
                    kwargs["stderr"].flush()
                    return process

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=fail_before_python):
                    response = client.post("/api/session/start", json={
                        "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                    })
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["code"], "endpoint_start_failed")
            self.assertEqual(response.json()["stage"], "radio")
            self.assertIn("actual RX gate timed out", response.json()["message"])

    def test_failed_attempt_requires_explicit_retry_before_another_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                failed = MagicMock(pid=1234)
                failed.poll.return_value = 73
                running = MagicMock(pid=5678)
                running.poll.return_value = None
                launches = 0

                def launch(command, **_kwargs):
                    nonlocal launches
                    launches += 1
                    if launches == 1:
                        return failed
                    acknowledge_initialized(runtime, command, running.pid)
                    return running

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=launch) as popen:
                    first = client.post("/api/session/start", json={
                        "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                    })
                    duplicate = client.post("/api/session/start", json={
                        "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                    })
                    retried = client.post("/api/v1/app/retry")

                self.assertEqual(first.status_code, 503, first.text)
                self.assertEqual(duplicate.status_code, 409, duplicate.text)
                self.assertEqual(duplicate.json()["code"], "endpoint_start_failed")
                self.assertEqual(retried.status_code, 200, retried.text)
                self.assertEqual(popen.call_count, 2)

    def test_stop_cancels_initialization_without_relaunch(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                exited = False
                launched = threading.Event()
                process = MagicMock(pid=1234)
                process.poll.side_effect = lambda: 143 if exited else None

                def terminate():
                    nonlocal exited
                    exited = True

                process.terminate.side_effect = terminate
                process.wait.side_effect = lambda **_kwargs: 143

                def launch(_command, **_kwargs):
                    launched.set()
                    return process

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=launch) as popen:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        starting = executor.submit(client.post, "/api/session/start", json={
                            "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                        })
                        self.assertTrue(launched.wait(2), "endpoint launch did not begin")
                        stopped = client.post("/api/v1/session/stop")
                        result = starting.result(timeout=5)

                self.assertEqual(stopped.status_code, 200, stopped.text)
                self.assertEqual(result.status_code, 503, result.text)
                self.assertEqual(result.json()["code"], "endpoint_start_canceled")
                popen.assert_called_once()

    def test_windows_endpoint_requires_matching_launch_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                process = MagicMock(pid=1234)
                process.poll.side_effect = [None, None, 73, 73]

                def write_wrong_ack(command, **_kwargs):
                    runtime.endpoint_launch_ack.write_text(json.dumps({
                        "schema": 2, "stage": "radio_gate_passed",
                        "launch_nonce": "0" * 32,
                        "launcher_pid": 1234,
                    }), encoding="utf-8")
                    self.assertNotEqual(
                        command[command.index("--launch-nonce") + 1], "0" * 32)
                    return process

                with patch.object(runtime.relay, "status", return_value={"status": "waiting"}), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=write_wrong_ack):
                    response = client.post("/api/session/start", json={
                        "role": "host", "passcode": "ABC123", "usb_id": "0bda:818b",
                    })
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["code"], "endpoint_start_failed")
            self.assertEqual(response.json()["stage"], "radio")

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
                runtime = client.app.state.runtime
                instance_id = r"USB\VID_0E8D&PID_7610\DIAGNOSTIC"
                runtime.write_hardware_selection("0e8d:7610", instance_id, "4-20")

                def diagnostic_run(command, **_kwargs):
                    if command[:2] == ["usbipd.exe", "state"]:
                        return MagicMock(returncode=0, stdout=json.dumps({"Devices": [{
                            "BusId": "4-20", "ClientIPAddress": "172.20.0.1",
                            "PersistedGuid": "shared-radio", "Description": "ALFA AWUS036ACHM",
                            "InstanceId": instance_id,
                        }]}), stderr="")
                    return MagicMock(
                        returncode=0, stdout=json.dumps(fake_report) + "\n", stderr="")

                with patch("switchtrade.control.subprocess.run", side_effect=diagnostic_run) as run, patch.object(
                        client.app.state.runtime.relay, "upload_diagnostic", return_value={
                            "status": "stored", "upload_id": "diagnostic-upload",
                            "correlation_id": "diagnostic-correlation",
                        }) as upload:
                    response = client.post(
                        "/api/v1/hardware/diagnostics",
                        json={"usb_id": "0e8d:7610", "mode": "quick"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["report"]["overall_status"], "partial")
                self.assertEqual(response.json()["relay_upload"]["status"], "stored")
                self.assertIn("switchtrade.hardware_diagnostics", run.call_args.args[0])
                self.assertFalse(any(call.args[0][:2] == ["usbipd.exe", "detach"]
                                     for call in run.call_args_list))
                upload.assert_called_once()

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
        attached = [False]
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "attach"]:
                attached[0] = True
            if command[:2] == ["usbipd.exe", "detach"]:
                attached[0] = False
            if command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [
                    {
                        "BusId": "4-20", "ClientIPAddress": None,
                        "PersistedGuid": "shared-a",
                        "Description": "Realtek RTL8192EU", "InstanceId": other_instance,
                    },
                    {
                        "BusId": current_bus[0],
                        "ClientIPAddress": "172.20.0.1" if attached[0] else None,
                        "PersistedGuid": "shared-b",
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
                    self.assertTrue(any(command[:2] == ["usbipd.exe", "detach"]
                                        for command in commands))
                    self.assertIsNone(runtime.owned_hardware)
                    self.assertFalse(runtime.hardware_attachment_file.exists())

    def test_startup_recovers_only_the_exact_persisted_owned_attachment(self):
        owned_instance = r"USB\VID_0BDA&PID_818B\OWNED-RADIO"
        other_instance = r"USB\VID_0BDA&PID_818B\OTHER-RADIO"
        attached = {"2-4": True, "2-5": True}
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "detach"]:
                attached[command[-1]] = False
            elif command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [
                    {
                        "BusId": "2-4",
                        "ClientIPAddress": "172.20.0.1" if attached["2-4"] else None,
                        "PersistedGuid": "shared-owned", "Description": "Realtek RTL8192EU",
                        "InstanceId": owned_instance,
                    },
                    {
                        "BusId": "2-5",
                        "ClientIPAddress": "172.20.0.2" if attached["2-5"] else None,
                        "PersistedGuid": "shared-other", "Description": "Realtek RTL8192EU",
                        "InstanceId": other_instance,
                    },
                ]})
            return result

        with tempfile.TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / "runtime"
            runtime_root.mkdir()
            attachment_file = runtime_root / "hardware-attachment.json"
            attachment_file.write_text(json.dumps({
                "schema": 1, "usb_id": "0bda:818b", "bus_id": "2-4",
                "instance_id": owned_instance, "owner_run_id": "interrupted-run",
            }), encoding="utf-8")

            with patch("switchtrade.control.subprocess.run", side_effect=run):
                with TestClient(create_app(runs_root=temporary)) as client:
                    self.assertIsNone(client.app.state.runtime.owned_hardware)
                    self.assertFalse(attachment_file.exists())

        self.assertFalse(attached["2-4"])
        self.assertTrue(attached["2-5"])
        detach_commands = [command for command in commands
                           if command[:2] == ["usbipd.exe", "detach"]]
        self.assertEqual(detach_commands, [["usbipd.exe", "detach", "--busid", "2-4"]])

    def test_parallel_room_poll_and_connect_attach_and_launch_once(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-B"
        attached = [False]
        attach_calls = []

        def run(command, **_kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "attach"]:
                attach_calls.append(command)
                time.sleep(0.05)
                attached[0] = True
            elif command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [{
                    "BusId": "2-4",
                    "ClientIPAddress": "172.20.0.1" if attached[0] else None,
                    "PersistedGuid": "shared-radio",
                    "Description": "Realtek RTL8192EU",
                    "InstanceId": instance_id,
                }]})
            return result

        room = {
            "contract_version": "room-control.v1",
            "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
            "state": "connection_attempt",
            "attempt": {
                "attempt_id": "attempt-1", "phase": "connecting_switches",
                "role_locked": True, "local_switch_role": "finder",
            },
            "members": [{"is_local": True, "seat": "member_b"}],
        }

        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
                runtime.authority_state.write_text(json.dumps({
                    "room_id": "room-1", "room_code": "ABC123",
                    "member_token": "member-token", "reconnect_token": "reconnect-token",
                }), encoding="utf-8")
                runtime.member_token_file.write_text("member-token", encoding="utf-8")
                runtime.relay_capabilities = {"manual-switch-role.v1"}
                runtime.next_capability_probe = time.monotonic() + 60
                runtime.last_authority_heartbeat = time.monotonic()
                process = MagicMock(pid=8765)
                process.poll.return_value = None

                def acknowledge_launch(command, **_kwargs):
                    acknowledge_initialized(runtime, command, 8765)
                    return process

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime.relay, "room_command", return_value=room), patch(
                        "switchtrade.control.subprocess.run", side_effect=run), patch(
                        "switchtrade.control.subprocess.Popen",
                        side_effect=acknowledge_launch) as popen:
                    for _ in range(10):
                        polled = client.get("/api/v1/trade-room")
                        self.assertEqual(polled.status_code, 200, polled.text)
                    self.assertEqual(attach_calls, [])
                    popen.assert_not_called()
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        poll = executor.submit(client.get, "/api/v1/trade-room")
                        connect = executor.submit(
                            client.post, "/api/v1/trade-room/connect",
                            json={"switch_room_role": "finder"},
                        )
                        responses = [poll.result(timeout=5), connect.result(timeout=5)]

                self.assertEqual([response.status_code for response in responses], [200, 200])
                self.assertEqual(len(attach_calls), 1)
                popen.assert_called_once()
                self.assertEqual(runtime.endpoint_session, "ABC123")

    def test_connect_requires_local_adapter_before_publishing_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.relay_capabilities = {"manual-switch-role.v1"}
                runtime.next_capability_probe = time.monotonic() + 60
                with patch.object(runtime, "authoritative_room") as room, patch.object(
                        runtime.relay, "room_command") as command:
                    response = client.post(
                        "/api/v1/trade-room/connect", json={"switch_room_role": "creator"})

                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["code"], "adapter_selection_required")
                room.assert_not_called()
                command.assert_not_called()

    def test_launch_failure_becomes_authoritative_before_adapter_cleanup(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-FAIL"
        attached = False
        events = []

        def run(command, **_kwargs):
            nonlocal attached
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "attach"]:
                events.append("attach")
                attached = True
            elif command[:2] == ["usbipd.exe", "detach"]:
                events.append("detach")
                attached = False
            elif command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [{
                    "BusId": "2-4", "ClientIPAddress": "172.20.0.1" if attached else None,
                    "PersistedGuid": "shared-radio", "Description": "Realtek RTL8192EU",
                    "InstanceId": instance_id,
                }]})
            return result

        base_room = {
            "contract_version": "room-control.v1", "room_id": "room-1",
            "room_code": "ABC123", "room_version": 6, "state": "ready_check",
            "attempt": None, "members": [{"is_local": True, "seat": "member_a"}],
        }
        attempt_room = {
            **base_room, "room_version": 7, "state": "connection_attempt",
            "attempt": {
                "attempt_id": "attempt-1", "phase": "connecting_switches",
                "role_locked": True, "local_switch_role": "creator",
            },
        }
        relay_commands = []

        def room_command(_room_id, _token, path, payload, **_kwargs):
            relay_commands.append((path, payload))
            events.append(path)
            return attempt_room

        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
                runtime.authority_state.write_text(json.dumps({
                    "room_id": "room-1", "room_code": "ABC123",
                    "member_token": "member-token", "reconnect_token": "reconnect-token",
                }), encoding="utf-8")
                runtime.member_token_file.write_text("member-token", encoding="utf-8")
                runtime.relay_capabilities = {"manual-switch-role.v1"}
                runtime.next_capability_probe = time.monotonic() + 60

                with patch.object(
                        runtime, "authoritative_room",
                        side_effect=[base_room, attempt_room]), patch.object(
                        runtime.relay, "room_command", side_effect=room_command), patch(
                        "switchtrade.control.subprocess.run", side_effect=run), patch(
                        "switchtrade.control.subprocess.Popen",
                        side_effect=OSError("synthetic launch failure")):
                    response = client.post(
                        "/api/v1/trade-room/connect", json={"switch_room_role": "creator"})

                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["code"], "endpoint_start_failed")
                self.assertLess(events.index("attach"), events.index("/ready"))
                self.assertEqual(relay_commands[-1][0], "/attempts/attempt-1:phase")
                self.assertEqual(relay_commands[-1][1], {
                    "phase": "failed", "failure_code": "endpoint_start_failed",
                })
                self.assertFalse(attached)
                self.assertIsNone(runtime.owned_hardware)

    def test_stop_during_adapter_attach_prevents_endpoint_launch(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-C"
        attach_started = threading.Event()
        release_attach = threading.Event()
        attached = False

        def run(command, **_kwargs):
            nonlocal attached
            result = MagicMock(returncode=0, stdout="", stderr="")
            if command[:2] == ["usbipd.exe", "attach"]:
                attach_started.set()
                release_attach.wait(3)
                attached = True
            elif command[:2] == ["usbipd.exe", "detach"]:
                attached = False
            elif command[:2] == ["usbipd.exe", "state"]:
                result.stdout = json.dumps({"Devices": [{
                    "BusId": "2-4", "ClientIPAddress": "172.20.0.1" if attached else None,
                    "PersistedGuid": "shared-radio", "Description": "Realtek RTL8192EU",
                    "InstanceId": instance_id,
                }]})
            return result

        room = {
            "contract_version": "room-control.v1",
            "room_id": "room-1", "room_code": "ABC123", "room_version": 7,
            "state": "connection_attempt",
            "attempt": {
                "attempt_id": "attempt-1", "phase": "connecting_switches",
                "role_locked": True, "local_switch_role": "creator",
            },
            "members": [{"is_local": True, "seat": "member_a"}],
        }

        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                runtime = client.app.state.runtime
                runtime.write_hardware_selection("0bda:818b", instance_id, "2-4")
                runtime.authority_state.write_text(json.dumps({
                    "room_id": "room-1", "room_code": "ABC123",
                    "member_token": "member-token", "reconnect_token": "reconnect-token",
                }), encoding="utf-8")
                runtime.member_token_file.write_text("member-token", encoding="utf-8")
                runtime.relay_capabilities = {"manual-switch-role.v1"}
                runtime.next_capability_probe = time.monotonic() + 60

                with patch.object(runtime, "authoritative_room", return_value=room), patch.object(
                        runtime.relay, "room_command", return_value=room), patch(
                        "switchtrade.control.subprocess.run", side_effect=run), patch(
                        "switchtrade.control.subprocess.Popen") as popen:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        connecting = executor.submit(
                            client.post, "/api/v1/trade-room/connect",
                            json={"switch_room_role": "creator"},
                        )
                        self.assertTrue(attach_started.wait(2), "adapter attach did not begin")
                        stopped = client.post("/api/v1/session/stop")
                        release_attach.set()
                        result = connecting.result(timeout=5)

                self.assertEqual(stopped.status_code, 200, stopped.text)
                self.assertEqual(result.status_code, 409, result.text)
                self.assertEqual(result.json()["code"], "endpoint_start_canceled")
                popen.assert_not_called()
                self.assertFalse(attached)
                self.assertIsNone(runtime.owned_hardware)
                self.assertFalse(runtime.hardware_attachment_file.exists())

    def test_unshared_adapter_reports_authorization_gate_without_attach(self):
        instance_id = r"USB\VID_0BDA&PID_818B\RADIO-A"
        usbipd_state = {"Devices": [{
            "BusId": "2-4", "ClientIPAddress": None, "PersistedGuid": None,
            "StubInstanceId": None, "Description": "Realtek RTL8192EU",
            "InstanceId": instance_id,
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                with patch("switchtrade.control.subprocess.run") as run:
                    run.return_value = MagicMock(
                        returncode=0, stdout=json.dumps(usbipd_state), stderr="")
                    selected = client.post("/api/v1/hardware/selection", json={
                        "usb_id": "0bda:818b", "bus_id": "2-4",
                        "instance_id": instance_id,
                    })
                    self.assertEqual(selected.status_code, 200, selected.text)
                    repaired = client.post(
                        "/api/v1/app/repair", json={"action": "recheck_adapter"})
                self.assertEqual(repaired.status_code, 409, repaired.text)
                self.assertEqual(repaired.json()["code"], "adapter_not_shared")
                self.assertEqual(repaired.json()["stage"], "hardware_share")
                self.assertEqual(repaired.json()["primary_action"], "authorize_adapter")
                self.assertFalse(any(call.args[0][:2] == ["usbipd.exe", "attach"]
                                     for call in run.call_args_list))

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
