from io import BytesIO
import json
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


if __name__ == "__main__":
    unittest.main()
