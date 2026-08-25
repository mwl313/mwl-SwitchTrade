from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from switchtrade.control import create_app, endpoint_command


class Gate4RuntimeContractTests(unittest.TestCase):
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

    def test_party_api_fails_neutral_when_session_is_inactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                body = client.get("/api/v1/trade-room/parties").json()
                self.assertEqual(body["contract_version"], "party-commit.v1")
                self.assertFalse(body["trading_room_confirmed"])
                self.assertTrue(all(value["status"] == "unavailable"
                                    for value in body["parties"].values()))

    def test_retry_without_retained_session_fails_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary)) as client:
                response = client.post("/api/v1/app/retry")
                self.assertEqual(response.status_code, 409)

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


if __name__ == "__main__":
    unittest.main()
