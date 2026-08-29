"""Network integration for the feature-neutral RFU tunnel (no radio required)."""

from __future__ import annotations

import asyncio
import inspect
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

from switchtrade.rfu_tunnel import (Direction, HEADER, Kind, MAGIC, MAX_PAYLOAD_BYTES,
                                    VERSION)
from switchtrade.relay_client import RelayClient
from switchtrade.tunnel_client import TunnelClient
from switchtrade.control import create_app, endpoint_command
from switchtrade.production_diagnostics import SyntheticDiagnosticPeer
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
        cls.environment["SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN"] = "1"
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
        if cls.proc.poll() is None:
            try:
                urlopen(Request(f"{cls.base}/shutdown", method="POST"), timeout=2).close()
            except OSError:
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
        for credential, role in ((first, "creator"), (second, "finder")):
            room = relay.room(room_id, credential["member_token"])
            relay.room_command(
                room_id, credential["member_token"], "/ready",
                {"ready": True, "switch_room_role": role},
                expected_version=room["room_version"],
            )
        room = relay.room(room_id, first["member_token"])
        room = relay.room_command(
            room_id, first["member_token"], "/attempts",
            expected_version=room["room_version"],
        )
        attempt_id = room["attempt"]["attempt_id"]
        self.assertTrue(room["attempt"]["role_locked"])
        return attempt_id

    def test_synthetic_diagnostic_peer_returns_nonce_over_authoritative_tunnel(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "Diagnostic", "visibility": "private", "trainer_display_name": "Peer",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "diagnostic-peer")
        second = relay.join_trade_room(first["room"]["room_code"], "Local", "diagnostic-local")
        attempt_id = self._prepare_authority_attempt(first, second)
        peer = SyntheticDiagnosticPeer(
            self.base, first["room"]["room_code"], "host", first["member_token"], attempt_id)
        local = TunnelClient(
            self.base, first["room"]["room_code"], "guest", member_token=second["member_token"],
            attempt_id=attempt_id, heartbeat_interval=0.2).start()
        try:
            peer.start()
            self.assertTrue(local.wait_connected(5))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    local.send(b"STDIAG1:nonce", kind=Kind.RFU)
                    break
                except ConnectionError:
                    time.sleep(0.02)
            else:
                self.fail("diagnostic tunnel never became ready")
            response = self._wait(local, Kind.RFU)
            self.assertEqual(response.payload, b"STDIAG2:nonce")
        finally:
            local.stop()
            peer.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

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

    def test_tracked_pokemon_payload_replays_byte_exactly_without_switch_hardware(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Recorded replay", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "replay-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "replay-b"})
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        fixture = (ROOT / "tests" / "fixtures" / "pokemon" /
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
            self.assertEqual(self._wait(host, Kind.PEER_READY).kind, Kind.PEER_READY)
            self.assertEqual(self._wait(guest, Kind.PEER_READY).kind, Kind.PEER_READY)
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
        replacement_host = replacement_guest = None
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
            self.assertFalse(host.wait_connected(2))
            self.assertFalse(guest.wait_connected(2))
            relay = RelayClient(self.base)
            room = relay.room(first["room"]["room_id"], first["member_token"])
            self.assertEqual(room["attempt"]["phase"], "failed")
            self.assertEqual(room["attempt"]["recoverable_error"], "relay.restart")
            host.stop()
            guest.stop()
            for credential, role in ((first, "creator"), (second, "finder")):
                room = relay.room(first["room"]["room_id"], credential["member_token"])
                room = relay.room_command(
                    room["room_id"], credential["member_token"], "/ready",
                    {"ready": True, "switch_room_role": role},
                    expected_version=room["room_version"],
                )
            replacement_attempt = room["attempt"]["attempt_id"]
            self.assertNotEqual(replacement_attempt, attempt_id)
            replacement_host = TunnelClient(
                self.base, sid, "host", heartbeat_interval=0.2,
                member_token=first["member_token"], attempt_id=replacement_attempt).start()
            replacement_guest = TunnelClient(
                self.base, sid, "guest", heartbeat_interval=0.2,
                member_token=second["member_token"], attempt_id=replacement_attempt).start()
            self.assertTrue(replacement_host.wait_connected(5))
            self.assertTrue(replacement_guest.wait_connected(5))
            replacement_guest.send(b"after-clean-restart")
            self.assertEqual(
                self._wait(replacement_host, Kind.RFU).payload, b"after-clean-restart")
        finally:
            host.stop()
            guest.stop()
            if replacement_host is not None:
                replacement_host.stop()
            if replacement_guest is not None:
                replacement_guest.stop()

    def test_oversized_authenticated_frame_is_rejected_and_attempt_fails_recoverably(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Oversized RFU", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "oversize-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "oversize-b"})
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        payload = b"x" * (MAX_PAYLOAD_BYTES + 1)
        raw = HEADER.pack(
            MAGIC, VERSION, int(Kind.RFU), int(Direction.HOST_TO_GUEST), 1,
            1, 0, 0, 0, 1, len(sid), len(payload),
        ) + sid.encode() + payload

        async def send_invalid() -> int | None:
            import websockets

            options = {}
            header_name = ("additional_headers" if "additional_headers" in
                           inspect.signature(websockets.connect).parameters else "extra_headers")
            options[header_name] = {"Authorization": f"Bearer {first['member_token']}"}
            url = (self.base.replace("http://", "ws://", 1) +
                   f"/session/{sid}/ws?role=host&protocol=rfu&attempt_id={attempt_id}")
            async with websockets.connect(url, **options) as websocket:
                await websocket.send(raw)
                try:
                    await websocket.recv()
                except Exception as error:
                    received = getattr(error, "rcvd", None)
                    return getattr(received, "code", None)
            return None

        self.assertEqual(asyncio.run(send_invalid()), 4400)
        relay = RelayClient(self.base)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            room = relay.room(first["room"]["room_id"], second["member_token"])
            if room["attempt"]["phase"] == "failed":
                break
            time.sleep(0.02)
        self.assertEqual(room["attempt"]["phase"], "failed")
        self.assertEqual(room["attempt"]["recoverable_error"], "relay.peer_lost")

    def test_authenticated_peer_loss_fails_attempt_and_disconnects_partner(self):
        first = self._authority_request("/v1/trade-rooms", {
            "name": "Peer loss", "trainer_display_name": "Leaf",
            "game": "LeafGreen", "language": "English",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "peer-loss-a"})
        second = self._authority_request("/v1/trade-rooms:join", {
            "room_code": first["room"]["room_code"], "trainer_display_name": "Red",
        }, {"Idempotency-Key": uuid7(), "X-SwitchTrade-Client": "peer-loss-b"})
        room_id = first["room"]["room_id"]
        sid = first["room"]["room_code"]
        attempt_id = self._prepare_authority_attempt(first, second)
        host = TunnelClient(
            self.base, sid, "host", heartbeat_interval=0.2,
            member_token=first["member_token"], attempt_id=attempt_id).start()
        guest = TunnelClient(
            self.base, sid, "guest", heartbeat_interval=0.2,
            member_token=second["member_token"], attempt_id=attempt_id).start()
        try:
            self.assertTrue(host.wait_connected(5))
            self.assertTrue(guest.wait_connected(5))
            host.stop()
            relay = RelayClient(self.base)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                room = relay.room(room_id, second["member_token"])
                if room["attempt"]["phase"] == "failed":
                    break
                time.sleep(0.02)
            self.assertEqual(room["attempt"]["phase"], "failed")
            self.assertEqual(room["attempt"]["recoverable_error"], "relay.peer_lost")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and guest.connected.is_set():
                time.sleep(0.02)
            self.assertFalse(guest.connected.is_set())
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

    def test_authoritative_controls_use_explicit_complementary_switch_roles(self):
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

                instance_id = r"USB\VID_0BDA&PID_818B\ROLE-TEST"
                first_api.app.state.runtime.write_hardware_selection(
                    "0bda:818b", instance_id, "2-4")
                second_api.app.state.runtime.write_hardware_selection(
                    "0bda:818b", instance_id, "2-4")

                def hardware(command, **_kwargs):
                    result = MagicMock(returncode=0, stdout="", stderr="")
                    if command[:2] == ["usbipd.exe", "state"]:
                        result.stdout = json.dumps({"Devices": [{
                            "BusId": "2-4", "ClientIPAddress": "172.20.0.1",
                            "PersistedGuid": "shared-radio",
                            "Description": "Realtek RTL8192EU",
                            "InstanceId": instance_id,
                        }]})
                    elif "python3" in command and any(
                            "/sys/bus/usb/devices" in str(part) for part in command):
                        result.stdout = json.dumps({
                            "status": "present", "interface_present": True,
                            "phy_present": True,
                        })
                    return result

                processes = []
                def process(command, **_kwargs):
                    value = MagicMock()
                    value.pid = 1000 + len(processes)
                    value.poll.return_value = None
                    nonce = command[command.index("--launch-nonce") + 1]
                    ack_value = command[command.index("--launch-ack-file") + 1]
                    if ack_value.startswith("/mnt/"):
                        ack_value = f"{ack_value[5].upper()}:\\" + ack_value[7:].replace("/", "\\")
                    ack_path = Path(ack_value)
                    ack_path.parent.mkdir(parents=True, exist_ok=True)
                    ack_path.write_text(json.dumps({
                        "schema": 2, "stage": "radio_gate_passed",
                        "launch_nonce": nonce, "launcher_pid": value.pid,
                    }), encoding="utf-8")
                    state_value = command[command.index("--state-file") + 1]
                    if state_value.startswith("/mnt/"):
                        state_value = f"{state_value[5].upper()}:\\" + state_value[7:].replace("/", "\\")
                    Path(state_value).write_text(json.dumps({
                        "state": "initializing", "pid": value.pid + 10000,
                        "process_kind": "rfu-endpoint",
                        "session_id": command[command.index("--session-id") + 1],
                        "attempt_id": command[command.index("--attempt-id") + 1],
                        "launch_nonce": nonce, "process_start_ticks": 12345,
                    }), encoding="utf-8")
                    processes.append(value)
                    return value

                with patch("switchtrade.control.subprocess.run", side_effect=hardware), patch(
                        "switchtrade.control.subprocess.Popen", side_effect=process):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        responses = list(executor.map(
                            lambda pair: pair[0].post(
                                "/api/v1/trade-room/connect",
                                json={"switch_room_role": pair[1]}),
                            ((first_api, "creator"), (second_api, "finder")),
                        ))
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        reconciled = list(executor.map(
                            lambda pair: pair[0].post(
                                "/api/v1/trade-room/connect",
                                json={"switch_room_role": pair[1]}),
                            ((first_api, "creator"), (second_api, "finder")),
                        ))
                    snapshots = [
                        first_api.get("/api/v1/trade-room"),
                        second_api.get("/api/v1/trade-room"),
                    ]
                self.assertTrue(all(response.status_code == 200 for response in responses),
                                [response.text for response in responses])
                self.assertTrue(all(response.status_code == 200 for response in reconciled),
                                [response.text for response in reconciled])
                self.assertTrue(all(response.status_code == 200 for response in snapshots),
                                [response.text for response in snapshots])
                roles = {response.json()["attempt"]["local_switch_role"]
                         for response in snapshots}
                self.assertEqual(roles, {"creator", "finder"})
                self.assertEqual(len(processes), 2)

    def test_rotated_credentials_leave_and_remote_close_cleanup_across_two_controls(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with TestClient(create_app(runs_root=first, relay_url=self.base)) as owner_api, \
                    TestClient(create_app(runs_root=second, relay_url=self.base)) as member_api:
                created = owner_api.post("/api/v1/trade-room", json={
                    "name": "Rotated leave", "visibility": "private",
                    "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
                })
                self.assertEqual(created.status_code, 200, created.text)
                joined = member_api.post("/api/v1/trade-room/join", json={
                    "passcode": created.json()["room"]["room_code"],
                    "trainer_display_name": "Red",
                })
                self.assertEqual(joined.status_code, 200, joined.text)

                member_runtime = member_api.app.state.runtime
                stale = member_runtime.read_authority()
                member_runtime.relay.reconnect_trade_room(
                    stale["room_id"], stale["reconnect_token"])
                left = member_api.delete("/api/v1/trade-room/members/me")
                self.assertEqual(left.status_code, 200, left.text)
                self.assertFalse(member_runtime.authority_state.exists())
                closed = owner_api.delete("/api/v1/trade-room")
                self.assertEqual(closed.status_code, 200, closed.text)

                created = owner_api.post("/api/v1/trade-room", json={
                    "name": "Rotated close", "visibility": "private",
                    "trainer_display_name": "Leaf", "game": "LeafGreen", "language": "English",
                })
                self.assertEqual(created.status_code, 200, created.text)
                joined = member_api.post("/api/v1/trade-room/join", json={
                    "passcode": created.json()["room"]["room_code"],
                    "trainer_display_name": "Red",
                })
                self.assertEqual(joined.status_code, 200, joined.text)

                owner_runtime = owner_api.app.state.runtime
                stale = owner_runtime.read_authority()
                owner_runtime.relay.reconnect_trade_room(
                    stale["room_id"], stale["reconnect_token"])
                closed = owner_api.delete("/api/v1/trade-room")
                self.assertEqual(closed.status_code, 200, closed.text)
                self.assertFalse(owner_runtime.authority_state.exists())

                left = member_api.delete("/api/v1/trade-room/members/me")
                self.assertEqual(left.status_code, 200, left.text)
                self.assertEqual(left.json()["status"], "left")
                self.assertFalse(member_runtime.authority_state.exists())

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
