from concurrent.futures import ThreadPoolExecutor
import asyncio
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import time
import unittest
import uuid
import zipfile
from unittest.mock import patch
import os

from fastapi.testclient import TestClient
import httpx

import relay.server as relay_server
from relay.authority import AuthorityError, AuthorityStore, copy_database, uuid7
from switchtrade.process_guard import AlreadyRunningError


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
        problem = third.json()
        self.assertEqual(problem["code"], "room_full")
        self.assertEqual(problem["stage"], "room")
        self.assertFalse(problem["recoverable"])
        self.assertTrue(problem["correlation_id"])

    def test_public_directory_is_authoritative_sanitized_and_atomically_joinable(self):
        private = self._create()
        public = self._create_public()
        health = self.client.get("/health")
        self.assertIn("public-directory.v1", health.json()["capabilities"])
        self.assertEqual(health.json()["room_contract"], "room-control.v1")
        self.assertEqual(health.json()["rfu_contract"], "rfu-tunnel.v1")

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

    def test_redacted_diagnostic_uploads_are_validated_and_stored(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
                os.environ, {"SWITCHTRADE_DIAGNOSTICS_ROOT": temporary}):
            report = json.dumps({
                "contract_version": "hardware-diagnostic.v1",
                "run_id": "20260828T000000Z-test",
                "overall_status": "partial",
            }).encode()
            diagnostic = self.client.post(
                "/v1/diagnostics/hardware-diagnostic", content=report,
                headers={
                    "Content-Type": "application/json",
                    "X-SwitchTrade-Client": "installation-a",
                    "X-SwitchTrade-Release": "beta-test",
                })
            self.assertEqual(diagnostic.status_code, 200, diagnostic.text)
            self.assertEqual(diagnostic.json()["contract_version"], "diagnostic-upload.v1")

            support_bytes = io.BytesIO()
            with zipfile.ZipFile(support_bytes, "w") as archive:
                archive.writestr("privacy-manifest.json", "{}")
                archive.writestr("events.jsonl", "{}\n")
            support = self.client.post(
                "/v1/diagnostics/support-bundle", content=support_bytes.getvalue(),
                headers={
                    "Content-Type": "application/zip",
                    "X-SwitchTrade-Client": "installation-b",
                    "X-SwitchTrade-Release": "beta-test",
                })
            self.assertEqual(support.status_code, 200, support.text)

            root = Path(temporary)
            self.assertEqual(len(list((root / "hardware-diagnostic").glob("*.json"))), 2)
            self.assertEqual(len(list((root / "support-bundle").glob("*.zip"))), 1)
            metadata = next((root / "support-bundle").glob("*.metadata.json")).read_text()
            self.assertNotIn("installation-b", metadata)
            self.assertIn('"release_id":"beta-test"', metadata)

            invalid = self.client.post(
                "/v1/diagnostics/hardware-diagnostic", content=b"not-json")
            self.assertEqual(invalid.status_code, 422)
            unknown = self.client.post("/v1/diagnostics/unknown", content=b"data")
            self.assertEqual(unknown.status_code, 404)

    def test_offline_owner_room_is_hidden_and_cannot_be_joined_publicly(self):
        created = self._create_public()
        listing_id = created["room"]["directory"]["listing_id"]
        baseline = time.time()
        with patch("relay.authority.time.time", return_value=baseline + 46):
            relay_server.authority.sweep_presence()
        self.assertEqual(
            self.client.get("/v1/public-trade-rooms").json()["rooms"][0]["listing_id"],
            listing_id,
        )
        with patch("relay.authority.time.time", return_value=baseline + 137):
            relay_server.authority.sweep_presence()
        self.assertEqual(self.client.get("/v1/public-trade-rooms").json()["rooms"], [])
        details = self.client.get(f"/v1/public-trade-rooms/{listing_id}")
        self.assertEqual(details.status_code, 410, details.text)
        joined = self.client.post(
            f"/v1/public-trade-rooms/{listing_id}:join",
            json={"trainer_display_name": "Red"},
            headers={"Idempotency-Key": _command(), "X-SwitchTrade-Client": "offline-owner"},
        )
        self.assertEqual(joined.status_code, 410, joined.text)

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

    def test_manual_roles_are_validated_and_locked_atomically(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            response = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            })
            self.assertEqual(response.status_code, 200, response.text)
        attempt = self._mutate(room_id, first["member_token"], "/attempts")
        self.assertEqual(attempt.status_code, 200, attempt.text)
        self.assertTrue(attempt.json()["attempt"]["role_locked"])
        self.assertEqual(attempt.json()["attempt"]["local_switch_role"], "creator")
        second_view = relay_server.authority.snapshot(room_id, second["member_token"])
        self.assertEqual(second_view["attempt"]["local_switch_role"], "finder")

        first_same = self._create("same-a")
        second_same = self._join(first_same["room"]["room_code"], "same-b")
        same_room_id = first_same["room"]["room_id"]
        for credential in (first_same, second_same):
            self.assertEqual(self._mutate(
                same_room_id, credential["member_token"], "/ready", {
                    "ready": True, "switch_room_role": "creator",
                }).status_code, 200)
        rejected = self._mutate(same_room_id, first_same["member_token"], "/attempts")
        self.assertEqual(rejected.status_code, 409)
        self.assertIn("one trainer must choose Group Leader", rejected.text)

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
        for credential, role in ((first, "creator"), (second, "finder")):
            self.assertEqual(self._mutate(
                room_id, credential["member_token"], "/ready", {
                    "ready": True, "switch_room_role": role,
                }).status_code, 200)

        version = self.client.get(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {first['member_token']}"}).json()["room_version"]

        def create_attempt(credential):
            return self.client.post(f"/v1/trade-rooms/{room_id}/attempts", json={}, headers={
                "Authorization": f"Bearer {credential['member_token']}",
                "Idempotency-Key": _command(), "If-Match": str(version),
            })

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create_attempt, (first, second)))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        attempt_id = relay_server.authority.snapshot(
            room_id, first["member_token"])["attempt"]["attempt_id"]
        self.assertEqual(
            {response.json()["attempt"]["attempt_id"] for response in responses},
            {attempt_id},
        )
        room = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(room["last_attempt_number"], 1)

    def test_second_complementary_ready_choice_starts_one_attempt_without_waiting(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        first_ready = self._mutate(room_id, first["member_token"], "/ready", {
            "ready": True, "switch_room_role": "creator",
        })
        self.assertEqual(first_ready.status_code, 200, first_ready.text)
        self.assertIsNone(first_ready.json()["attempt"])
        self.assertEqual(first_ready.json()["state"], "waiting_for_complementary_role")
        second_ready = self._mutate(room_id, second["member_token"], "/ready", {
            "ready": True, "switch_room_role": "finder",
        })
        self.assertEqual(second_ready.status_code, 200, second_ready.text)
        self.assertTrue(second_ready.json()["attempt"]["role_locked"])
        self.assertEqual(second_ready.json()["last_attempt_number"], 1)

    def test_transport_loss_and_restart_fail_active_attempt_recoverably(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]
        self.assertTrue(relay_server.authority.fail_transport_attempt(
            room_id, attempt_id, "relay.peer_lost"))
        failed = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(failed["attempt"]["phase"], "failed")
        self.assertEqual(failed["attempt"]["recoverable_error"], "relay.peer_lost")
        self.assertTrue(all(member["ready_state"] == "not_ready" for member in failed["members"]))
        self.assertFalse(relay_server.authority.fail_transport_attempt(
            room_id, attempt_id, "relay.peer_lost"))

        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        replacement_id = room["attempt"]["attempt_id"]
        self.assertNotEqual(replacement_id, attempt_id)
        self.assertEqual(relay_server.authority.fail_active_attempts("relay.restart"), 1)
        restarted = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(restarted["attempt"]["phase"], "failed")
        self.assertEqual(restarted["attempt"]["recoverable_error"], "relay.restart")

    def test_attempt_phases_only_move_forward_and_terminal_failure_is_immutable(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]

        trading = self._mutate(
            room_id, first["member_token"], f"/attempts/{attempt_id}:phase",
            {"phase": "trading_room"})
        self.assertEqual(trading.status_code, 200, trading.text)
        backward = self._mutate(
            room_id, first["member_token"], f"/attempts/{attempt_id}:phase",
            {"phase": "connecting_switches"})
        self.assertEqual(backward.status_code, 409, backward.text)
        self.assertEqual(backward.json()["code"], "attempt_phase_conflict")

        self.assertTrue(relay_server.authority.fail_transport_attempt(
            room_id, attempt_id, "relay.peer_lost"))
        stale_phase = self._mutate(
            room_id, first["member_token"], f"/attempts/{attempt_id}:phase",
            {"phase": "trading_room"})
        self.assertEqual(stale_phase.status_code, 409, stale_phase.text)
        self.assertEqual(stale_phase.json()["code"], "attempt_phase_conflict")
        failed = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(failed["attempt"]["phase"], "failed")
        self.assertEqual(failed["attempt"]["recoverable_error"], "relay.peer_lost")

    def test_endpoint_failure_code_is_preserved_for_the_partner(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]

        failed = self._mutate(
            room_id, first["member_token"], f"/attempts/{attempt_id}:phase", {
                "phase": "failed", "failure_code": "radio.switch_room_not_found",
            })
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(
            failed.json()["attempt"]["recoverable_error"],
            "radio.switch_room_not_found",
        )
        partner = relay_server.authority.snapshot(room_id, second["member_token"])
        self.assertEqual(
            partner["attempt"]["recoverable_error"],
            "radio.switch_room_not_found",
        )

    def test_endpoint_failure_code_rejects_unstructured_input(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]

        rejected = self._mutate(
            room_id, first["member_token"], f"/attempts/{attempt_id}:phase", {
                "phase": "failed", "failure_code": "invalid failure code!",
            })
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(
            relay_server.authority.snapshot(room_id, first["member_token"])
            ["attempt"]["phase"],
            "connecting_switches",
        )

    def test_concurrent_peer_loss_and_stale_phase_cannot_reactivate_attempt(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        for credential, role in ((first, "creator"), (second, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]
        failure_committed = Event()

        def lose_peer():
            try:
                return relay_server.authority.fail_transport_attempt(
                    room_id, attempt_id, "relay.peer_lost")
            finally:
                failure_committed.set()

        def publish_stale_phase():
            self.assertTrue(failure_committed.wait(timeout=2))
            return relay_server.authority.mutate(
                room_id, first["member_token"], _command(), "phase", {
                    "attempt_id": attempt_id, "phase": "trading_room",
                })

        with ThreadPoolExecutor(max_workers=2) as executor:
            lost = executor.submit(lose_peer)
            stale = executor.submit(publish_stale_phase)
            self.assertTrue(lost.result(timeout=2))
            with self.assertRaises(AuthorityError) as raised:
                stale.result(timeout=2)
        self.assertEqual(raised.exception.status, 409)
        final = relay_server.authority.snapshot(room_id, first["member_token"])
        self.assertEqual(final["attempt"]["phase"], "failed")

    def test_owner_close_cancels_attempt_and_peer_cleanup_cannot_reopen_room(self):
        owner = self._create()
        member = self._join(owner["room"]["room_code"])
        room_id = owner["room"]["room_id"]
        for credential, role in ((owner, "creator"), (member, "finder")):
            room = self._mutate(room_id, credential["member_token"], "/ready", {
                "ready": True, "switch_room_role": role,
            }).json()
        attempt_id = room["attempt"]["attempt_id"]
        closed = self.client.delete(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {owner['member_token']}",
            "Idempotency-Key": _command(), "If-Match": str(room["room_version"]),
        })
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["state"], "closed")
        self.assertEqual(closed.json()["attempt"]["phase"], "canceled")
        self.assertFalse(relay_server.authority.fail_transport_attempt(
            room_id, attempt_id, "relay.peer_lost"))

    def test_member_leave_and_owner_close_ignore_stale_presence_version(self):
        owner = self._create()
        member = self._join(owner["room"]["room_code"])
        room_id = owner["room"]["room_id"]
        stale_version = member["room"]["room_version"]

        self._mutate(room_id, owner["member_token"], "/heartbeat")
        left = self.client.delete(f"/v1/trade-rooms/{room_id}/members/me", headers={
            "Authorization": f"Bearer {member['member_token']}",
            "Idempotency-Key": _command(), "If-Match": str(stale_version),
        })
        self.assertEqual(left.status_code, 200, left.text)

        closed = self.client.delete(f"/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {owner['member_token']}",
            "Idempotency-Key": _command(), "If-Match": str(stale_version),
        })
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["state"], "closed")

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

    def test_database_writer_is_single_instance_and_releases_on_close(self):
        database = Path(self.temporary.name) / "single-writer.sqlite3"
        first = AuthorityStore(database)
        try:
            with self.assertRaises(AlreadyRunningError):
                AuthorityStore(database)
        finally:
            first.close()
        AuthorityStore(database).close()

    def test_wal_backup_restore_drill_is_atomic_and_offline_only(self):
        database = Path(self.temporary.name) / "restore-source.sqlite3"
        backup = Path(self.temporary.name) / "backups" / "authority.sqlite3"
        store = AuthorityStore(database)
        created = store.create({
            "name": "Backup drill", "visibility": "private",
            "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
        }, _command(), "backup-client")
        room_id = created["room"]["room_id"]
        copy_database(database, backup)
        with self.assertRaises(AlreadyRunningError):
            copy_database(backup, database)
        store.close()
        corrupt = Path(self.temporary.name) / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a sqlite database")
        before = database.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            copy_database(corrupt, database)
        self.assertEqual(database.read_bytes(), before)
        copy_database(backup, database)
        restored = AuthorityStore(database)
        try:
            room = restored.snapshot(room_id, created["member_token"])
            self.assertEqual(room["state"], "waiting_for_partner")
            restored.ping()
        finally:
            restored.close()
        self.assertFalse(Path(str(database) + "-wal").exists())

    def test_read_triggered_expiry_commits_as_one_transaction(self):
        created = self._create()
        room_id = created["room"]["room_id"]
        statements = []
        relay_server.authority._db.set_trace_callback(statements.append)
        baseline = time.time()
        with patch("relay.authority.time.time", return_value=baseline + 31 * 60):
            room = relay_server.authority.snapshot(room_id, created["member_token"])
        relay_server.authority._db.set_trace_callback(None)
        self.assertEqual(room["state"], "expired")
        self.assertIn("BEGIN IMMEDIATE", statements)
        self.assertIn("COMMIT", statements)
        self.assertFalse(relay_server.authority._db.in_transaction)
        events = relay_server.authority._db.execute(
            "SELECT COUNT(*) FROM events WHERE room_id=? AND event_type='room.expired'",
            (room_id,),
        ).fetchone()[0]
        self.assertEqual(events, 1)

    def test_authoritative_session_registry_prunes_and_enforces_capacity(self):
        stale = relay_server.Session("STALE1")
        stale.last_activity = 0
        live = relay_server.Session("LIVE01")
        live.host = object()
        relay_server.sessions.update({"STALE1": stale, "LIVE01": live})
        with patch("relay.server.time.monotonic", return_value=relay_server.SESSION_TTL + 1):
            relay_server._prune_sessions()
        self.assertNotIn("STALE1", relay_server.sessions)
        self.assertIn("LIVE01", relay_server.sessions)
        with patch.object(relay_server, "MAX_SESSIONS", 1):
            with self.assertRaises(relay_server.HTTPException) as raised:
                relay_server._session("NEW001")
        self.assertEqual(raised.exception.status_code, 503)

    def test_rate_limit_identity_ignores_untrusted_spoof_headers(self):
        limiter = relay_server.RateLimiter(limit=1, window=60)
        payload = {
            "name": "Rate identity", "visibility": "private",
            "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
        }
        with patch.object(relay_server, "rate_limiter", limiter):
            first = self.client.post("/v1/trade-rooms", json=payload, headers={
                "Idempotency-Key": _command(), "X-SwitchTrade-Client": "spoof-a",
                "X-Forwarded-For": "198.51.100.1",
            })
            second = self.client.post("/v1/trade-rooms", json=payload, headers={
                "Idempotency-Key": _command(), "X-SwitchTrade-Client": "spoof-b",
                "X-Forwarded-For": "198.51.100.2",
            })
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 429, second.text)
        request = relay_server.Request({
            "type": "http", "method": "GET", "path": "/", "headers": [
                (b"x-forwarded-for", b"198.51.100.99, 203.0.113.7")],
            "client": ("10.0.0.5", 1234), "server": ("relay", 8788),
            "scheme": "http", "query_string": b"",
        })
        with patch.dict(os.environ, {"SWITCHTRADE_TRUSTED_PROXIES": "10.0.0.0/8"}):
            self.assertEqual(relay_server._rate_identity(request), "203.0.113.7")

    def test_health_performs_writable_storage_probe(self):
        before = relay_server.authority._db.execute(
            "SELECT value FROM service_state WHERE key='readiness'").fetchone()[0]
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["storage_status"], "writable")
        self.assertEqual(response.json()["worker_model"], "single-writer")
        after = relay_server.authority._db.execute(
            "SELECT value FROM service_state WHERE key='readiness'").fetchone()[0]
        self.assertNotEqual(after, before)

    def test_unhandled_relay_failure_returns_generic_structured_envelope(self):
        with patch.object(
                relay_server.authority, "operational_stats",
                side_effect=ExceptionGroup("do-not-leak", [RuntimeError("credential-secret")])):
            response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 500, response.text)
        body = response.json()
        self.assertEqual(set(body), {
            "code", "message", "detail", "stage", "recoverable",
            "primary_action", "correlation_id",
        })
        self.assertEqual(body["code"], "relay_internal_error")
        self.assertEqual(body["message"], "internal relay error")
        self.assertTrue(body["recoverable"])
        self.assertEqual(body["primary_action"], "retry")
        self.assertEqual(response.headers["X-Correlation-ID"], body["correlation_id"])
        self.assertNotIn("credential-secret", response.text)

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

    def test_matched_inactive_reconnect_credentials_report_terminal_lifecycle(self):
        first = self._create()
        second = self._join(first["room"]["room_code"])
        room_id = first["room"]["room_id"]
        invalid = self.client.post(f"/v1/trade-rooms/{room_id}:reconnect", json={
            "reconnect_token": "not-a-valid-secret-that-matches-nothing",
        }, headers={"Idempotency-Key": _command()})
        self.assertEqual(invalid.status_code, 401, invalid.text)
        self.assertEqual(invalid.json()["code"], "reconnect_credential_invalid")

        relay_server.authority.mutate(room_id, first["member_token"], _command(), "close")
        closed = self.client.post(f"/v1/trade-rooms/{room_id}:reconnect", json={
            "reconnect_token": second["reconnect_token"],
        }, headers={"Idempotency-Key": _command()})
        self.assertEqual(closed.status_code, 410, closed.text)
        self.assertEqual(closed.json()["code"], "room_not_active")

        owner = self._create("left-owner")
        member = self._join(owner["room"]["room_code"], "left-member")
        relay_server.authority.mutate(
            owner["room"]["room_id"], member["member_token"], _command(), "leave")
        left = self.client.post(
            f"/v1/trade-rooms/{owner['room']['room_id']}:reconnect",
            json={"reconnect_token": member["reconnect_token"]},
            headers={"Idempotency-Key": _command()})
        self.assertEqual(left.status_code, 410, left.text)
        self.assertEqual(left.json()["code"], "room_not_active")

        expiring = self._create("expired-owner")
        with patch("relay.authority.time.time", return_value=time.time() + 7 * 60 * 60):
            expired = self.client.post(
                f"/v1/trade-rooms/{expiring['room']['room_id']}:reconnect",
                json={"reconnect_token": expiring["reconnect_token"]},
                headers={"Idempotency-Key": _command()})
        self.assertEqual(expired.status_code, 410, expired.text)
        self.assertEqual(expired.json()["code"], "room_not_active")

        reconnecting = self._create("deadline-owner")
        partner = self._join(reconnecting["room"]["room_code"], "deadline-member")
        baseline = time.time()
        with patch("relay.authority.time.time", return_value=baseline + 46):
            relay_server.authority.sweep_presence()
        with patch("relay.authority.time.time", return_value=baseline + 137):
            relay_server.authority.sweep_presence()
            deadline = self.client.post(
                f"/v1/trade-rooms/{reconnecting['room']['room_id']}:reconnect",
                json={"reconnect_token": partner["reconnect_token"]},
                headers={"Idempotency-Key": _command()})
        self.assertEqual(deadline.status_code, 410, deadline.text)
        self.assertEqual(deadline.json()["code"], "reconnect_deadline_expired")

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
        for credential, role in ((first, "creator"), (second, "finder")):
            ready = self._mutate(
                room_id, credential["member_token"], "/ready", {
                    "ready": True, "switch_room_role": role,
                })
            self.assertEqual(ready.status_code, 200, ready.text)
        attempt = self._mutate(room_id, first["member_token"], "/attempts").json()["attempt"]
        self.assertTrue(attempt["role_locked"])
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
