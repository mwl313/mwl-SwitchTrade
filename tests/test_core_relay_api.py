from __future__ import annotations

import unittest
from fastapi.websockets import WebSocketDisconnect

from fastapi.testclient import TestClient

from relay.core_server import create_app


CAPABILITIES = {"endpoint_kind": "fake", "runtime_kind": "in_process", "protocols": ["switchtrade.fake.v1"], "generation_roles": ["origin"]}
MIRROR = {**CAPABILITIES, "generation_roles": ["mirror"]}


class CoreRelayApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_create_join_status_and_one_time_code(self) -> None:
        created = self.client.post("/core/v1/pairs", json={"capabilities": CAPABILITIES}).json()
        self.assertRegex(created["code"], r"^\d{6}$")
        self.assertIn("code_expires_at", created)
        guest = self.client.post("/core/v1/pairs:join", json={"code": created["code"], "capabilities": MIRROR})
        self.assertEqual(guest.status_code, 200)
        self.assertEqual(self.client.post("/core/v1/pairs:join", json={"code": created["code"], "capabilities": MIRROR}).status_code, 400)
        status = self.client.get(f"/core/v1/pairs/{created['pair_id']}", headers={"authorization": f"Bearer {created['access_token']}"})
        self.assertEqual(status.status_code, 200)
        self.assertNotIn("access_token", status.json())

    def test_websocket_seat_is_credential_bound(self) -> None:
        created = self.client.post("/core/v1/pairs", json={"capabilities": CAPABILITIES}).json()
        with self.client.websocket_connect(f"/core/v1/pairs/{created['pair_id']}/ws", headers={"authorization": f"Bearer {created['access_token']}"}) as socket:
            self.assertEqual(socket.receive_json(), {"seat": "host"})

    def test_websocket_replaces_the_same_seat_and_rejects_wrong_token(self) -> None:
        created = self.client.post("/core/v1/pairs", json={"capabilities": CAPABILITIES}).json()
        path = f"/core/v1/pairs/{created['pair_id']}/ws"
        first = self.client.websocket_connect(path, headers={"authorization": f"Bearer {created['access_token']}"})
        with first as socket:
            self.assertEqual(socket.receive_json(), {"seat": "host"})
            with self.client.websocket_connect(path, headers={"authorization": f"Bearer {created['access_token']}"}) as replacement:
                self.assertEqual(replacement.receive_json(), {"seat": "host"})
            with self.assertRaises(WebSocketDisconnect) as closed:
                socket.receive_text()
            self.assertEqual(closed.exception.code, 4000)
        with self.assertRaises(WebSocketDisconnect) as rejected:
            with self.client.websocket_connect(path, headers={"authorization": "Bearer wrong-token"}):
                pass
        self.assertEqual(rejected.exception.code, 4401)

    def test_invalid_code_guesses_are_rate_limited(self) -> None:
        request = {"code": "000000", "capabilities": MIRROR}
        for _ in range(5):
            self.assertEqual(self.client.post("/core/v1/pairs:join", json=request).status_code, 400)
        limited = self.client.post("/core/v1/pairs:join", json=request)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["detail"], "PAIR_RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
