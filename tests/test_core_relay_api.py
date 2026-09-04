from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
