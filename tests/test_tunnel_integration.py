"""Network integration for the feature-neutral RFU tunnel (no radio required)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from switchtrade.rfu_tunnel import Direction, Kind
from switchtrade.relay_client import RelayClient
from switchtrade.tunnel_client import TunnelClient
from switchtrade.control import create_app, endpoint_command
from relay.authority import uuid7
from fastapi.testclient import TestClient


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TunnelIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.relay_state = tempfile.TemporaryDirectory()
        cls.environment = dict(os.environ)
        cls.environment["SWITCHTRADE_AUTH_DB"] = str(
            Path(cls.relay_state.name) / "authority.sqlite3")
        cls.environment["SWITCHTRADE_ENABLE_LEGACY_RELAY"] = "1"
        cls._start_relay()

    @classmethod
    def _start_relay(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "relay.server:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=ROOT, env=cls.environment, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.proc.poll() is not None:
                raise RuntimeError(cls.proc.stderr.read())
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("relay did not start")

    @classmethod
    def _stop_relay(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(5)
        if cls.proc.stderr is not None:
            cls.proc.stderr.close()

    @classmethod
    def tearDownClass(cls):
        cls._stop_relay()
        cls.relay_state.cleanup()

    def _session(self) -> str:
        with urlopen(Request(f"{self.base}/session/create", method="POST"), timeout=5) as response:
            return json.load(response)["session_id"]

    def _authority_request(self, path: str, payload: dict, headers: dict) -> dict:
        request = Request(f"{self.base}{path}", method="POST",
                          data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", **headers})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def _close_authority_room(self, room_id: str, token: str) -> None:
        with urlopen(Request(f"{self.base}/v1/trade-rooms/{room_id}", headers={
            "Authorization": f"Bearer {token}",
        }), timeout=5) as response:
            version = json.load(response)["room_version"]
        request = Request(f"{self.base}/v1/trade-rooms/{room_id}", method="DELETE", headers={
            "Authorization": f"Bearer {token}", "Idempotency-Key": uuid7(),
            "If-Match": str(version),
        })
        with urlopen(request, timeout=5):
            pass

    def _prepare_authority_attempt(self, first: dict, second: dict) -> str:
        relay = RelayClient(self.base)
        room_id = first["room"]["room_id"]
        for credential in (first, second):
            room = relay.room(room_id, credential["member_token"])
            relay.room_command(
                room_id, credential["member_token"], "/ready", {"ready": True},
                expected_version=room["room_version"],
            )
        room = relay.room(room_id, first["member_token"])
        room = relay.room_command(
            room_id, first["member_token"], "/attempts",
            expected_version=room["room_version"],
        )
        attempt_id = room["attempt"]["attempt_id"]
        room = relay.room_command(
            room_id, first["member_token"],
            f"/attempts/{attempt_id}:claim-creator",
            expected_version=room["room_version"],
        )
        relay.room_command(
            room_id, first["member_token"], f"/attempts/{attempt_id}:lock-role",
            expected_version=room["room_version"],
        )
        return attempt_id

    @staticmethod
    def _wait(client: TunnelClient, kind: Kind, timeout: float = 5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for envelope in client.poll():
                if envelope.kind == kind:
                    return envelope
            time.sleep(0.02)
        raise AssertionError(f"timed out waiting for {kind.name}")

    def test_bidirectional_rfu_and_advertisement(self):
        sid = self._session()
        host = TunnelClient(self.base, sid, "host", heartbeat_interval=0.2).start()
        guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2).start()
        try:
            self.assertTrue(host.wait_connected(5))
            self.assertTrue(guest.wait_connected(5))
            time.sleep(0.1)
            host.poll()
            guest.poll()

            host.send(b"parent-rfu", flags=0x0F)
            inbound = self._wait(guest, Kind.RFU)
            self.assertEqual(inbound.payload, b"parent-rfu")
            self.assertEqual(inbound.flags, 0x0F)
            self.assertEqual(inbound.direction, Direction.HOST_TO_GUEST)

            guest.send(b"child-rfu", flags=0x07)
            inbound = self._wait(host, Kind.RFU)
            self.assertEqual(inbound.payload, b"child-rfu")
            self.assertEqual(inbound.direction, Direction.GUEST_TO_HOST)

            host.advertise(b"leader-application-data")
            self.assertEqual(self._wait(guest, Kind.ADVERTISEMENT).payload,
                             b"leader-application-data")
            self.assertEqual(host.stats["dropped"], 0)
            self.assertEqual(guest.stats["dropped"], 0)
        finally:
            host.stop()
            guest.stop()

    def test_tracked_trade_fixture_replays_byte_exactly_without_switch_hardware(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Recorded replay", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "replay-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "replay-b"})
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        fixture = (ROOT / "archive" / "pokemon" / "fixtures" /
                   "0373_SALAMENCE.pk3").read_bytes()
        host = TunnelClient(self.base, sid, "host", heartbeat_interval=0.2,
                            member_token=first["member_token"], attempt_id=attempt_id).start()
        guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2,
                             member_token=second["member_token"], attempt_id=attempt_id).start()
        try:
            self.assertTrue(host.wait_connected(5))
            self.assertTrue(guest.wait_connected(5))
            host.send(fixture)
            self.assertEqual(self._wait(guest, Kind.RFU).payload, fixture)
            guest.send(fixture[::-1])
            self.assertEqual(self._wait(host, Kind.RFU).payload, fixture[::-1])
        finally:
            host.stop()
            guest.stop()

    def test_authoritative_websocket_requires_seat_credential_and_stays_opaque(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Opaque Relay", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "opaque-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "opaque-b"})
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        rejected = TunnelClient(
            self.base, sid, "host", heartbeat_interval=0.2,
            attempt_id=attempt_id,
        ).start()
        unbound = TunnelClient(
            self.base, sid, "host", heartbeat_interval=0.2,
            member_token=first["member_token"],
        ).start()
        host = TunnelClient(self.base, sid, "host", heartbeat_interval=0.2,
                            member_token=first["member_token"], attempt_id=attempt_id).start()
        guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2,
                             member_token=second["member_token"], attempt_id=attempt_id).start()
        try:
            self.assertFalse(rejected.wait_connected(0.5))
            self.assertFalse(unbound.wait_connected(0.5))
            self.assertTrue(host.wait_connected(5))
            self.assertTrue(guest.wait_connected(5))
            arbitrary = bytes(range(256)) * 3
            host.send(arbitrary)
            self.assertEqual(self._wait(guest, Kind.RFU).payload, arbitrary)
            self._close_authority_room(first["room"]["room_id"], first["member_token"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (host.connected.is_set() or guest.connected.is_set()):
                time.sleep(0.02)
            self.assertFalse(host.connected.is_set())
            self.assertFalse(guest.connected.is_set())
        finally:
            rejected.stop()
            unbound.stop()
            host.stop()
            guest.stop()

    def test_authoritative_clients_reconnect_after_relay_restart_without_replaying_stale_frames(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Restart Relay", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "restart-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "restart-b"})
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        host = TunnelClient(self.base, sid, "host", heartbeat_interval=0.2,
                            member_token=first["member_token"], attempt_id=attempt_id).start()
        guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2,
                             member_token=second["member_token"], attempt_id=attempt_id).start()
        try:
            self.assertTrue(host.wait_connected(5))
            self.assertTrue(guest.wait_connected(5))
            host.send(b"before-restart")
            self.assertEqual(self._wait(guest, Kind.RFU).payload, b"before-restart")

            self._stop_relay()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (host.connected.is_set() or guest.connected.is_set()):
                time.sleep(0.02)
            self.assertFalse(host.connected.is_set())
            self.assertFalse(guest.connected.is_set())
            self._start_relay()
            self.assertTrue(host.wait_connected(8))
            self.assertTrue(guest.wait_connected(8))
            host.poll()
            guest.poll()
            guest.send(b"after-restart")
            self.assertEqual(self._wait(host, Kind.RFU).payload, b"after-restart")
            self.assertGreaterEqual(host.stats["reconnects"], 1)
            self.assertGreaterEqual(guest.stats["reconnects"], 1)
        finally:
            host.stop()
            guest.stop()

    def test_late_guest_receives_advertisement_and_can_restart(self):
        sid = self._session()
        host = TunnelClient(self.base, sid, "host", heartbeat_interval=0.2).start()
        first_guest = None
        second_guest = None
        try:
            self.assertTrue(host.wait_connected(5))
            host.advertise(b"retained-room-advertisement")
            time.sleep(0.1)

            first_guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2).start()
            self.assertTrue(first_guest.wait_connected(5))
            self.assertEqual(self._wait(first_guest, Kind.ADVERTISEMENT).payload,
                             b"retained-room-advertisement")
            first_guest.send(b"before-restart")
            self.assertEqual(self._wait(host, Kind.RFU).payload, b"before-restart")
            first_guest.stop()
            first_guest = None

            second_guest = TunnelClient(self.base, sid, "guest", heartbeat_interval=0.2).start()
            self.assertTrue(second_guest.wait_connected(5))
            second_guest.poll()
            second_guest.send(b"after-restart")
            self.assertEqual(self._wait(host, Kind.RFU).payload, b"after-restart")
        finally:
            host.stop()
            if first_guest is not None:
                first_guest.stop()
            if second_guest is not None:
                second_guest.stop()

    def test_send_fails_closed_before_connection(self):
        client = TunnelClient(self.base, "ABC123", "host")
        with self.assertRaises(ConnectionError):
            client.send(b"stale")

    def test_two_control_apis_share_private_relay_session(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with TestClient(create_app(runs_root=first, relay_url=self.base)) as host_api:
                response = host_api.post("/api/groups", json={
                    "name": "Kanto Trade", "visibility": "private",
                })
                self.assertEqual(response.status_code, 200, response.text)
                code = response.json()["group"]["passcode"]
            with TestClient(create_app(runs_root=second, relay_url=self.base)) as guest_api:
                response = guest_api.post("/api/groups/join", json={"passcode": code})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["group"]["passcode"], code)

    def test_authoritative_controls_assign_one_creator_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with TestClient(create_app(runs_root=first, relay_url=self.base)) as first_api, \
                    TestClient(create_app(runs_root=second, relay_url=self.base)) as second_api:
                created = first_api.post("/api/v1/trade-room", json={
                    "name": "Authority Test", "visibility": "private",
                    "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
                })
                self.assertEqual(created.status_code, 200, created.text)
                code = created.json()["room"]["room_code"]
                joined = second_api.post("/api/v1/trade-room/join", json={
                    "passcode": code, "trainer_display_name": "Red",
                })
                self.assertEqual(joined.status_code, 200, joined.text)
                self.assertNotIn("token", created.text.lower())
                self.assertNotIn("token", joined.text.lower())

                processes = []
                def process(*_args, **_kwargs):
                    value = MagicMock()
                    value.pid = 1000 + len(processes)
                    value.poll.return_value = None
                    processes.append(value)
                    return value

                with patch("switchtrade.control.subprocess.Popen", side_effect=process):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        responses = list(executor.map(
                            lambda client: client.post("/api/v1/trade-room/connect"),
                            (first_api, second_api),
                        ))
                self.assertTrue(all(response.status_code == 200 for response in responses),
                                [response.text for response in responses])
                roles = {response.json()["room"]["attempt"]["local_switch_role"]
                         for response in responses}
                self.assertEqual(roles, {"creator", "finder"})
                seats = {response.json()["hardware"]["tunnel_seat"] for response in responses}
                self.assertEqual(seats, {"member_a", "member_b"})

    def test_control_group_preserves_invitation_fields_and_releases_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            with TestClient(create_app(runs_root=temporary, relay_url=self.base)) as api:
                response = api.post("/api/groups", json={
                    "name": "Kanto Trade",
                    "visibility": "private",
                    "trainer_display_name": "Leaf",
                    "game": "LeafGreen",
                    "language": "English",
                    "offering": "Pinsir",
                    "wanted": "Scyther",
                    "note": "Version-exclusive swap",
                })
                self.assertEqual(response.status_code, 200, response.text)
                group = response.json()["group"]
                self.assertEqual(group["trainer_display_name"], "Leaf")
                self.assertEqual(group["game"], "LeafGreen")
                self.assertEqual(group["offering"], "Pinsir")
                code = group["passcode"]

                response = api.post("/api/groups/join", json={"passcode": code})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["group"]["participants"], 2)

                response = api.delete(f"/api/groups/{code}/members/me")
                self.assertEqual(response.status_code, 200, response.text)
                response = api.delete(f"/api/groups/{code}")
                self.assertEqual(response.status_code, 200, response.text)

    def test_endpoint_command_is_argument_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "endpoint state.json"
            command = endpoint_command("guest", "ABC123", self.base, "0BDA:818B", state)
            self.assertIn("--session-id", command)
            self.assertIn("ABC123", command)
            self.assertIn("0bda:818b", command)
            self.assertIn("--state-file", command)


if __name__ == "__main__":
    unittest.main()
