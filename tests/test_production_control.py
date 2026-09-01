import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from switchtrade.control import RelayReadinessMonitor, create_app


class FakeProductionRunner:
    def __init__(self):
        self.starts = 0
        self.closed = False
        self.released = []
        self.requests = []

    def __call__(self, _run_id, _request, control):
        self.starts += 1
        self.requests.append(_request)
        control.authority({
            "room_id": "room-1", "room_code": "ABC123", "name": "Room",
            "visibility": "private", "participants": 1,
            "membership_role": "owner", "room_version": 1,
        })
        deadline = time.monotonic() + 3
        while control.termination is None and time.monotonic() < deadline:
            time.sleep(0.01)
        return {"functional_status": "canceled", "cleanup_status": "verified"}

    def recover(self, _record):
        return {"cleanup_verified": True}

    def release_authority(self, action):
        self.released.append(action)

    def close(self):
        self.closed = True


def headers(revision, *, run_id=None):
    value = {
        "X-SwitchTrade-Command-ID": str(uuid.uuid4()),
        "X-SwitchTrade-Expected-Revision": str(revision),
    }
    if run_id is not None:
        value["X-SwitchTrade-Run-ID"] = run_id
    return value


class ProductionControlTests(unittest.TestCase):
    def test_desktop_contract_names_do_not_alias_existing_relay_or_coordinator_shapes(self):
        root = Path(__file__).resolve().parents[1] / "contracts" / "abcd"
        local = json.loads((root / "local-app-readiness.v2.schema.json").read_text(
            encoding="utf-8"))
        product = json.loads((root / "production-connection-run.v1.schema.json").read_text(
            encoding="utf-8"))
        relay = json.loads((root / "app-readiness.v2.schema.json").read_text(encoding="utf-8"))
        coordinator = json.loads((root / "connection-run.v1.schema.json").read_text(
            encoding="utf-8"))
        self.assertEqual(
            local["properties"]["contract_version"]["const"], "local-app-readiness.v2")
        self.assertEqual(
            product["properties"]["contract_version"]["const"],
            "production-connection-run.v1")
        self.assertNotEqual(local["$id"], relay["$id"])
        self.assertNotEqual(product["$id"], coordinator["$id"])
        self.assertTrue({"functional", "cleanup", "allowed_actions"}.issubset(
            product["required"]))

    def test_relay_monitor_is_lifespan_owned_and_snapshot_is_read_only(self):
        calls = []
        probed = time.monotonic()

        def probe():
            calls.append(time.monotonic())
            return {
                "status": "ready", "room_contract": "room-control.v1",
                "rfu_contracts": ["rfu-tunnel.v2"],
                "capabilities": ["public-directory.v1"],
            }

        monitor = RelayReadinessMonitor(
            probe, success_interval=60, failure_interval=60)
        try:
            deadline = time.monotonic() + 1
            while monitor.snapshot() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(monitor.snapshot())
            self.assertEqual(
                monitor.state_snapshot(), (True, frozenset({"public-directory.v1"})))
            before = len(calls)
            for _ in range(20):
                self.assertTrue(monitor.snapshot())
            self.assertEqual(len(calls), before)
            self.assertLess(calls[0] - probed, 1)
        finally:
            monitor.close()

        malformed = RelayReadinessMonitor(
            lambda: [], success_interval=60, failure_interval=60)
        try:
            deadline = time.monotonic() + 1
            while malformed.snapshot() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(malformed.state_snapshot(), (False, frozenset()))
        finally:
            malformed.close()

    def test_public_directory_uses_background_capability_and_read_only_routes(self):
        runner = FakeProductionRunner()
        health = {
            "status": "ready", "room_contract": "room-control.v1",
            "rfu_contracts": ["rfu-tunnel.v2"],
            "capabilities": ["public-directory.v1"],
        }
        directory = {
            "contract_version": "public-directory.v1", "rooms": [{
                "listing_id": "listing-1", "name": "Public Room",
                "trainer_display_name": "Leaf", "game": "LeafGreen",
                "language": "English", "offering": "", "wanted": "",
                "note": "", "participants": 1, "availability": "open",
            }], "next_cursor": None,
        }
        details = {"contract_version": "public-directory.v1", **directory["rooms"][0]}
        with patch("switchtrade.control.RelayClient.health", return_value=health) as probe:
            with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(
                    runs_root=temporary, relay_url="https://relay.invalid",
                    production_contract=True, connection_runner=runner)) as client:
                deadline = time.monotonic() + 1
                readiness = client.get("/api/v1/app/readiness").json()
                while ("public-directory.v1" not in readiness["capabilities"] and
                       time.monotonic() < deadline):
                    time.sleep(0.01)
                    readiness = client.get("/api/v1/app/readiness").json()
                self.assertIn("public-directory.v1", readiness["capabilities"])
                runtime = client.app.state.runtime
                with (patch.object(runtime.relay, "public_trade_rooms",
                                   return_value=directory) as list_rooms,
                      patch.object(runtime.relay, "public_trade_room",
                                   return_value=details) as room_details):
                    for _ in range(10):
                        response = client.get("/api/v1/public-trade-rooms")
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json(), directory)
                    response = client.get("/api/v1/public-trade-rooms/listing-1")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), details)
                self.assertEqual(list_rooms.call_count, 10)
                room_details.assert_called_once_with("listing-1")
                self.assertEqual(probe.call_count, 1)
                self.assertEqual(runner.starts, 0)
                self.assertIsNone(client.app.state.connection_service.snapshot())

                joined = client.post(
                    "/api/v1/public-trade-rooms/listing-1/join", headers=headers(0),
                    json={"trainer_display_name": "Red"})
                self.assertEqual(joined.status_code, 200, joined.text)
                run = joined.json()
                self.assertEqual(runner.requests[0]["kind"], "public_join")
                self.assertEqual(runner.requests[0]["listing_id"], "listing-1")
                stopped = client.post(
                    "/api/v1/session/stop",
                    headers=headers(run["revision"], run_id=run["run_id"]), json={})
                self.assertEqual(stopped.status_code, 200, stopped.text)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    final = client.get(
                        f"/api/v1/connection-runs/{run['run_id']}").json()
                    if final["phase"] == "terminal":
                        break
                    time.sleep(0.01)
                self.assertEqual(final["phase"], "terminal")
                self.assertTrue(final["cleanup"]["verified"])

    def test_production_routes_are_identity_bound_and_get_is_pure(self):
        runner = FakeProductionRunner()
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(
                runs_root=temporary, relay_url="http://127.0.0.1:9",
                production_contract=True, connection_runner=runner)) as client:
            readiness = client.get("/api/v1/app/readiness").json()
            self.assertEqual(readiness["contract_version"], "local-app-readiness.v2")
            self.assertEqual(readiness["revision"], 0)
            self.assertNotIn("public-directory.v1", readiness["capabilities"])
            self.assertEqual(client.get("/api/v1/public-trade-rooms").status_code, 503)
            unavailable_join = client.post(
                "/api/v1/public-trade-rooms/listing-1/join", headers=headers(0),
                json={"trainer_display_name": "Red"})
            self.assertEqual(unavailable_join.status_code, 503)
            unavailable_create = client.post(
                "/api/v1/trade-room", headers=headers(0),
                json={"name": "Room", "visibility": "public"})
            self.assertEqual(unavailable_create.status_code, 503)
            self.assertEqual(runner.starts, 0)
            missing = client.post("/api/v1/trade-room", json={
                "name": "Room", "visibility": "private",
            })
            self.assertEqual(missing.status_code, 422)

            created = client.post("/api/v1/trade-room", headers=headers(0), json={
                "name": "Room", "visibility": "private",
            })
            self.assertEqual(created.status_code, 200, created.text)
            run = created.json()
            self.assertEqual(run["contract_version"], "production-connection-run.v1")
            self.assertEqual(run["room"]["room_code"], "ABC123")
            before = client.get("/api/v1/trade-room").json()
            for _ in range(10):
                self.assertEqual(client.get("/api/v1/trade-room").json(), before)
            self.assertEqual(runner.starts, 1)

            connected = client.post(
                "/api/v1/trade-room/connect",
                headers=headers(before["revision"], run_id=before["run_id"]),
                json={"switch_room_role": "creator"})
            self.assertEqual(connected.status_code, 200, connected.text)
            self.assertEqual(connected.json()["local_role"], "a_room_joiner")

            checkpoint = client.post("/api/v1/support-bundle")
            self.assertEqual(checkpoint.status_code, 200)
            self.assertEqual(
                checkpoint.json()["contract_version"], "support-checkpoint.v1")
            self.assertEqual(client.post(
                "/api/v1/production-diagnostics", json={}).status_code, 404)
            self.assertEqual(client.post(
                "/api/session/start", json={}).status_code, 404)
            self.assertEqual(client.post(
                "/api/groups", json={}).status_code, 404)
            self.assertEqual(client.get("/api/groups/public").status_code, 404)
            self.assertEqual(client.post(
                "/api/hardware/diagnostics", json={}).status_code, 404)

            current = client.get("/api/v1/trade-room").json()
            stopped = client.post(
                "/api/v1/session/stop",
                headers=headers(current["revision"], run_id=current["run_id"]), json={})
            self.assertEqual(stopped.status_code, 200, stopped.text)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                final = client.get(
                    f"/api/v1/connection-runs/{current['run_id']}").json()
                if final["phase"] == "terminal":
                    break
                time.sleep(0.01)
            self.assertEqual(final["phase"], "terminal")
            self.assertTrue(final["cleanup"]["verified"])
            shutdown = client.post(
                "/api/v1/app/shutdown",
                headers=headers(final["revision"], run_id=final["run_id"]), json={})
            self.assertEqual(shutdown.status_code, 200, shutdown.text)
            self.assertIsNone(shutdown.json()["cleanup_code"])
            self.assertTrue(runner.closed)


if __name__ == "__main__":
    unittest.main()
