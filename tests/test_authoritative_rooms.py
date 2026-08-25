from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

import relay.server as relay_server
from relay.authority import AuthorityStore, uuid7


def _command() -> str:
    return uuid7()


class AuthoritativeRoomTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "authority.sqlite3"
        self.previous = relay_server.authority
        relay_server.authority = AuthorityStore(self.database)
        relay_server.sessions.clear()
        self.client = TestClient(relay_server.app)

    def tearDown(self):
        self.client.close()
        relay_server.authority.close()
        relay_server.authority = self.previous
        relay_server.sessions.clear()
        self.temporary.cleanup()

    def _create(self, client_id="client-a") -> dict:
        response = self.client.post("/v1/trade-rooms", json={
            "name": "Kanto Trade", "visibility": "private",
            "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
        }, headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": client_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _join(self, code: str, client_id="client-b") -> dict:
        response = self.client.post("/v1/trade-rooms:join", json={
            "room_code": code, "trainer_display_name": "Red",
        }, headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": client_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _mutate(self, room_id: str, token: str, path: str, payload=None):
        return self.client.post(f"/v1/trade-rooms/{room_id}{path}", json=payload or {}, headers={
            "Authorization": f"Bearer {token}", "Idempotency-Key": _command(),
        })

    def test_code_is_locator_not_authority_and_room_has_exactly_two_seats(self):
        first = self._create()
        room = first["room"]
        unauthenticated = self.client.get(f"/v1/trade-rooms/{room['room_id']}")
        self.assertEqual(unauthenticated.status_code, 401)
        second = self._join(room["room_code"])
        self.assertEqual([member["seat"] for member in second["room"]["members"]],
                         ["member_a", "member_b"])
        third = self.client.post("/v1/trade-rooms:join", json={
            "room_code": room["room_code"], "trainer_display_name": "Blue",
        }, headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": "client-c"})
        self.assertEqual(third.status_code, 409)

    def test_idempotency_and_atomic_creator_claim(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential in (first, second):
            response = self._mutate(room_id, credential["member_token"], "/ready", {"ready": True})
            self.assertEqual(response.status_code, 200, response.text)
        attempt = self._mutate(room_id, first["member_token"], "/attempts")
        self.assertEqual(attempt.status_code, 200, attempt.text)
        attempt_id = attempt.json()["attempt"]["attempt_id"]

        def claim(credential):
            return relay_server.authority.mutate(
                room_id, credential["member_token"], _command(), "claim_creator",
                {"attempt_id": attempt_id})

        with ThreadPoolExecutor(max_workers=2) as executor:
            snapshots = list(executor.map(claim, (first, second)))
        creators = {snapshot["attempt"]["creator_member_id"] for snapshot in snapshots}
        self.assertEqual(len(creators), 1)
        self.assertIn(next(iter(creators)), {
            first["room"]["local_member_id"], second["room"]["local_member_id"]})

        key = _command()
        before = relay_server.authority.snapshot(room_id, first["member_token"])["room_version"]
        one = relay_server.authority.mutate(room_id, first["member_token"], key, "heartbeat")
        two = relay_server.authority.mutate(room_id, first["member_token"], key, "heartbeat")
        self.assertEqual(one, two)
        self.assertEqual(one["room_version"], before + 1)

    def test_hashed_credentials_and_room_state_survive_service_restart(self):
        first = self._create()
        room_id = first["room"]["room_id"]
        database_text = self.database.read_bytes()
        self.assertNotIn(first["member_token"].encode(), database_text)
        relay_server.authority.close()
        relay_server.authority = AuthorityStore(self.database)
        snapshot = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(snapshot["room_id"], room_id)
        self.assertEqual(snapshot["local_member_id"], first["room"]["local_member_id"])


if __name__ == "__main__":
    unittest.main()
