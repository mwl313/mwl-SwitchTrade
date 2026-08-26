from concurrent.futures import ThreadPoolExecutor
import asyncio
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
import os

from fastapi.testclient import TestClient
import httpx

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

    def _create_public(self, client_id="public-owner") -> dict:
        response = self.client.post("/v1/trade-rooms", json={
            "name": "Version exclusives", "visibility": "public",
            "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
            "offering": "Vulpix", "wanted": "Growlithe", "note": "One quick trade",
        }, headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": client_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _mutate(self, room_id: str, token: str, path: str, payload=None):
        snapshot = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {token}"})
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        return self.client.post(f"/v1/trade-rooms/{room_id}{path}", json=payload or {}, headers={
            "Authorization": f"Bearer {token}", "Idempotency-Key": _command(),
            "If-Match": str(snapshot.json()["room_version"]),
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

    def test_public_directory_is_authoritative_sanitized_and_atomically_joinable(self):
        private = self._create()
        public = self._create_public()
        health = self.client.get("/health")
        self.assertIn("public-directory.v1", health.json()["capabilities"])

        listed = self.client.get(
            "/v1/public-trade-rooms?query=vulpix&game=LeafGreen&language=English")
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertEqual(body["contract_version"], "public-directory.v1")
        self.assertEqual(len(body["rooms"]), 1)
        listing = body["rooms"][0]
        self.assertEqual(listing["room_name"], "Version exclusives")
        self.assertEqual(listing["offering"], "Vulpix")
        self.assertEqual(listing["availability"], "open")
        serialized = str(body).lower()
        self.assertNotIn("room_code", serialized)
        self.assertNotIn(public["room"]["room_code"].lower(), serialized)
        self.assertNotIn(private["room"]["room_code"].lower(), serialized)
        self.assertNotIn("member_token", serialized)
        self.assertNotIn("reconnect_token", serialized)

        listing_id = listing["listing_id"]
        joined = self.client.post(
            f"/v1/public-trade-rooms/{listing_id}:join",
            json={"trainer_display_name": "Red"},
            headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": "public-guest"},
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertEqual(joined.json()["room"]["room_code"], public["room"]["room_code"])
        self.assertEqual(len(joined.json()["room"]["members"]), 2)

        open_rooms = self.client.get("/v1/public-trade-rooms?availability=open").json()["rooms"]
        self.assertFalse(any(room["listing_id"] == listing_id for room in open_rooms))
        all_rooms = self.client.get("/v1/public-trade-rooms?availability=all").json()["rooms"]
        full = next(room for room in all_rooms if room["listing_id"] == listing_id)
        self.assertEqual(full["availability"], "full")

        losing_join = self.client.post(
            f"/v1/public-trade-rooms/{listing_id}:join",
            json={"trainer_display_name": "Blue"},
            headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": "public-third"},
        )
        self.assertEqual(losing_join.status_code, 409)

    def test_production_mode_rejects_legacy_sessions_and_invalid_room_fields(self):
        with patch.dict(os.environ, {"SWITCHTRADE_ENABLE_LEGACY_RELAY": "0"}):
            legacy = self.client.post("/session/create")
        self.assertEqual(legacy.status_code, 404)
        invalid = self.client.post("/v1/trade-rooms", json={
            "name": "Kanto", "trainer_display_name": "Leaf",
            "game": "Emerald", "language": "English",
        }, headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": "invalid"})
        self.assertEqual(invalid.status_code, 422)
        oversized = self.client.post("/v1/trade-rooms", content=b"x" * 65537, headers={
            "Content-Length": "65537", "Idempotency-Key": _command(),
        })
        self.assertEqual(oversized.status_code, 413)
        async def chunked_request():
            async def chunks():
                for chunk in (b'{"name":"', b"x" * 70000, b'"}'):
                    yield chunk

            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=relay_server.app),
                    base_url="http://testserver") as client:
                return await client.post(
                    "/v1/trade-rooms", content=chunks(),
                    headers={"Idempotency-Key": _command(),
                             "X-SwitchTrade-Client": "oversized-chunked"},
                )

        chunked = asyncio.run(chunked_request())
        self.assertEqual(chunked.status_code, 413)

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

    def test_mutations_require_version_and_parallel_attempt_creation_is_singleton(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        missing = self.client.post(f"/v1/trade-rooms/{room_id}/ready", json={"ready": True}, headers={
            "Authorization": f"Bearer {first['member_token']}", "Idempotency-Key": _command(),
        })
        self.assertEqual(missing.status_code, 428)
        for credential in (first, second):
            self.assertEqual(self._mutate(
                room_id, credential["member_token"], "/ready", {"ready": True}).status_code, 200)

        version = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {first['member_token']}"}).json()["room_version"]

        def create_attempt(credential):
            return self.client.post(f"/v1/trade-rooms/{room_id}/attempts", json={}, headers={
                "Authorization": f"Bearer {credential['member_token']}",
                "Idempotency-Key": _command(), "If-Match": str(version),
            })

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create_attempt, (first, second)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        room = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(room["last_attempt_number"], 1)

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

    def test_public_listing_survives_service_restart_without_exposing_credentials(self):
        created = self._create_public()
        listing_id = created["room"]["directory"]["listing_id"]
        relay_server.authority.close()
        relay_server.authority = AuthorityStore(self.database)
        directory = relay_server.authority.list_public(query="Vulpix")
        self.assertEqual([room["listing_id"] for room in directory["rooms"]], [listing_id])
        serialized = str(directory).lower()
        self.assertNotIn("room_code", serialized)
        self.assertNotIn("member_token", serialized)

    def test_reconnect_rotates_both_credentials(self):
        first = self._create()
        room_id = first["room"]["room_id"]
        command = _command()
        response = self.client.post(f"/v1/trade-rooms/{room_id}:reconnect", json={
            "reconnect_token": first["reconnect_token"],
        }, headers={"Idempotency-Key": command})
        self.assertEqual(response.status_code, 200, response.text)
        rotated = response.json()
        self.assertNotEqual(rotated["member_token"], first["member_token"])
        self.assertNotEqual(rotated["reconnect_token"], first["reconnect_token"])
        old = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {first['member_token']}"})
        self.assertEqual(old.status_code, 401)
        current = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {rotated['member_token']}"})
        self.assertEqual(current.status_code, 200)
        repeated = self.client.post(f"/v1/trade-rooms/{room_id}:reconnect", json={
            "reconnect_token": first["reconnect_token"],
        }, headers={"Idempotency-Key": command})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["member_token"], rotated["member_token"])
        relay_server.authority.close()
        relay_server.authority = AuthorityStore(self.database)
        recovered = self.client.post(f"/v1/trade-rooms/{room_id}:reconnect", json={
            "reconnect_token": first["reconnect_token"],
        }, headers={"Idempotency-Key": _command()})
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertNotEqual(recovered.json()["member_token"], rotated["member_token"])

    def test_presence_moves_through_bounded_reconnect_window(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        baseline = time.time()
        with patch("relay.authority.time.time", return_value=baseline + 46):
            relay_server.authority.mutate(
                room_id, second["member_token"], _command(), "heartbeat")
            relay_server.authority.sweep_presence()
        room = relay_server.authority.snapshot(room_id, second["member_token"])
        self.assertEqual(room["members"][0]["online_state"], "reconnecting")
        with patch("relay.authority.time.time", return_value=baseline + 137):
            relay_server.authority.mutate(
                room_id, second["member_token"], _command(), "heartbeat")
            relay_server.authority.sweep_presence()
        room = relay_server.authority.snapshot(room_id, second["member_token"])
        self.assertEqual(room["members"][0]["online_state"], "offline")
        expired = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {first['member_token']}"})
        self.assertEqual(expired.status_code, 401)

    def test_owner_can_release_partner_only_after_reconnect_grace(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        target = second["room"]["local_member_id"]
        for credential in (first, second):
            ready = self._mutate(
                room_id, credential["member_token"], "/ready", {"ready": True})
            self.assertEqual(ready.status_code, 200, ready.text)
        attempt = self._mutate(room_id, first["member_token"], "/attempts").json()["attempt"]
        claimed = self._mutate(
            room_id, first["member_token"],
            f"/attempts/{attempt['attempt_id']}:claim-creator")
        self.assertEqual(claimed.status_code, 200, claimed.text)
        locked = self._mutate(
            room_id, first["member_token"],
            f"/attempts/{attempt['attempt_id']}:lock-role")
        self.assertEqual(locked.status_code, 200, locked.text)
        early = self._mutate(room_id, first["member_token"], "/members:remove-offline", {
            "target_member_id": target,
        })
        self.assertEqual(early.status_code, 409)
        baseline = time.time()
        with patch("relay.authority.time.time", return_value=baseline + 46):
            relay_server.authority.sweep_presence()
        with patch("relay.authority.time.time", return_value=baseline + 137):
            relay_server.authority.mutate(
                room_id, first["member_token"], _command(), "heartbeat")
            relay_server.authority.sweep_presence()
            removed = self._mutate(room_id, first["member_token"], "/members:remove-offline", {
                "target_member_id": target,
            })
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["state"], "waiting_for_partner")
        self.assertEqual([member["online_state"] for member in removed.json()["members"]],
                         ["online", "left"])


if __name__ == "__main__":
    unittest.main()
