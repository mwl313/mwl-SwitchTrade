from io import BytesIO
import unittest
from unittest.mock import patch

from switchtrade.relay_client import RelayClient, USER_AGENT


class RelayClientTests(unittest.TestCase):
    def test_every_http_request_identifies_switchtrade(self):
        with patch("switchtrade.relay_client.urlopen", return_value=BytesIO(b"{}")) as request:
            RelayClient("https://relay.example")._request("GET", "/health")

        self.assertEqual(request.call_args.args[0].get_header("User-agent"), USER_AGENT)

    def test_callers_cannot_restore_cloudflare_blocked_default_user_agent(self):
        with patch("switchtrade.relay_client.urlopen", return_value=BytesIO(b"{}")) as request:
            RelayClient("https://relay.example")._request(
                "GET", "/health", headers={"User-Agent": "Python-urllib/3.10"}
            )

        self.assertEqual(request.call_args.args[0].get_header("User-agent"), USER_AGENT)


if __name__ == "__main__":
    unittest.main()
