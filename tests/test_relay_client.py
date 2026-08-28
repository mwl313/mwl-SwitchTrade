from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from switchtrade.relay_client import RelayClient, RelayError, USER_AGENT


class RelayClientTests(unittest.TestCase):
    def test_every_http_request_identifies_switchtrade(self):
        with patch("switchtrade.relay_client.urlopen", return_value=BytesIO(b"{}")) as request:
            RelayClient("https://relay.example")._request("GET", "/health")

        self.assertEqual(request.call_args.args[0].get_header("User-agent"), USER_AGENT)

    def test_structured_relay_failure_is_preserved(self):
        body = {
            "code": "room_full", "message": "trade room is full", "stage": "room",
            "recoverable": False, "primary_action": "choose_another_room",
            "correlation_id": "correlation-1",
        }
        error = HTTPError(
            "https://relay.example/v1/trade-rooms:join", 409, "Conflict", {},
            BytesIO(json.dumps(body).encode()))
        with patch("switchtrade.relay_client.urlopen", side_effect=error):
            with self.assertRaises(RelayError) as raised:
                RelayClient("https://relay.example")._request("POST", "/v1/trade-rooms:join")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "room_full")
        self.assertEqual(raised.exception.stage, "room")
        self.assertFalse(raised.exception.recoverable)
        self.assertEqual(raised.exception.correlation_id, "correlation-1")

    def test_callers_cannot_restore_cloudflare_blocked_default_user_agent(self):
        with patch("switchtrade.relay_client.urlopen", return_value=BytesIO(b"{}")) as request:
            RelayClient("https://relay.example")._request(
                "GET", "/health", headers={"User-Agent": "Python-urllib/3.10"}
            )

        self.assertEqual(request.call_args.args[0].get_header("User-agent"), USER_AGENT)

    def test_diagnostic_upload_sends_exact_artifact_with_release_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "diagnostic.json"
            expected = b'{"contract_version":"hardware-diagnostic.v1"}'
            artifact.write_bytes(expected)
            response = BytesIO(b'{"status":"stored","upload_id":"upload-1"}')
            with patch("switchtrade.relay_client.urlopen", return_value=response) as send:
                result = RelayClient("https://relay.example").upload_diagnostic(
                    "hardware-diagnostic", artifact, "client-a", "beta-test")
        request = send.call_args.args[0]
        self.assertEqual(result["upload_id"], "upload-1")
        self.assertEqual(request.full_url,
                         "https://relay.example/v1/diagnostics/hardware-diagnostic")
        self.assertEqual(request.data, expected)
        self.assertEqual(request.get_header("X-switchtrade-client"), "client-a")
        self.assertEqual(request.get_header("X-switchtrade-release"), "beta-test")


if __name__ == "__main__":
    unittest.main()
