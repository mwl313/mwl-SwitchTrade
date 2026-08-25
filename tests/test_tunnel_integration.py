"""Network integration for the feature-neutral RFU tunnel (no radio required)."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from switchtrade.rfu_tunnel import Direction, Kind
from switchtrade.tunnel_client import TunnelClient
from switchtrade.control import create_app, endpoint_command
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
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "relay.server:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
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
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def _session(self) -> str:
        with urlopen(Request(f"{self.base}/session/create", method="POST"), timeout=5) as response:
            return json.load(response)["session_id"]

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
