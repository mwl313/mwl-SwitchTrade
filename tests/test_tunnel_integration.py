"""Network integration for the feature-neutral RFU tunnel (no radio required)."""

from __future__ import annotations

import asyncio
import hashlib
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
from switchtrade.rfu_tunnel_v2 import (
    Envelope as EnvelopeV2,
    Kind as KindV2,
    SourceSeat,
    advertisement_hash,
)
from switchtrade.relay_client import RelayClient, RelayError
from switchtrade.tunnel_client import TunnelClient
from switchtrade.tunnel_client_v2 import TunnelClientV2
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

    def _prepare_authority_attempt(self, first: dict, second: dict,
                                   first_role: str = "creator") -> str:
        relay = RelayClient(self.base)
        room_id = first["room"]["room_id"]
        second_role = "finder" if first_role == "creator" else "creator"
        for credential, role in ((first, first_role), (second, second_role)):
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

    @staticmethod
    def _p0_proof(label: str) -> dict:
        return {
            "contract_version": "p0-attestation.v2",
            "run_id": uuid7(),
            "release": "0.3.0-validation",
            "run_generation": 1,
            "stage_generation": 1,
            "adapter_instance_sha256": hashlib.sha256(
                f"adapter-{label}".encode()).hexdigest(),
            "report_sha256": hashlib.sha256(f"report-{label}".encode()).hexdigest(),
        }

    def _prepare_v2_attempt(self, first: dict, second: dict,
                            first_role: str = "creator") -> str:
        relay = RelayClient(self.base)
        room_id = first["room"]["room_id"]
        second_role = "finder" if first_role == "creator" else "creator"
        for label, credential, role in (
                ("a", first, first_role), ("b", second, second_role)):
            proof = self._p0_proof(label)
            credential["_v2_p0"] = proof
            credential["_v2_launch"] = {
                "run_id": proof["run_id"],
                "stage_generation": proof["stage_generation"],
                "launch_nonce": hashlib.sha256(
                    f"launch-{label}-{proof['run_id']}".encode()).hexdigest(),
                "endpoint_pid": 4101 if label == "a" else 4102,
            }
            room = relay.room(room_id, credential["member_token"])
            room = relay.v2_ready(
                room_id, credential["member_token"], {
                    "ready": True,
                    "switch_room_role": role,
                    "p0": proof,
                }, expected_version=room["room_version"])
        self.assertTrue(room["v2_admission"]["attempt_admitted"])
        self.assertEqual(room["v2_admission"]["p0_ready_members"], 2)
        return room["attempt"]["attempt_id"]

    @staticmethod
    def _v2_headers(credential: dict) -> dict:
        launch = credential["_v2_launch"]
        return {
            "Authorization": f"Bearer {credential['member_token']}",
            "X-SwitchTrade-Run-ID": launch["run_id"],
            "X-SwitchTrade-Stage-Generation": str(launch["stage_generation"]),
            "X-SwitchTrade-Launch-Nonce": launch["launch_nonce"],
            "X-SwitchTrade-Endpoint-PID": str(launch["endpoint_pid"]),
        }

    def _v2_client(self, credential: dict, attempt_id: str, seat: str, **options):
        launch = {**credential["_v2_launch"]}
        for key in tuple(launch):
            if key in options:
                launch[key] = options.pop(key)
        return TunnelClientV2(
            self.base, credential["room"]["room_code"], attempt_id, seat,
            credential["member_token"], **launch, **options)

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

    def test_v2_requires_two_distinct_matching_p0_proofs_before_transport(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 P0", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-p0-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-p0-b")
        first_proof = self._p0_proof("first")
        room = relay.room(first["room"]["room_id"], first["member_token"])
        admitted = relay.v2_ready(
            room["room_id"], first["member_token"], {
                "ready": True, "switch_room_role": "creator", "p0": first_proof,
            }, expected_version=room["room_version"])
        self.assertEqual(admitted["v2_admission"], {
            "contract_version": "app-readiness.v2",
            "p0_ready_members": 1,
            "attempt_admitted": False,
        })
        self.assertIsNone(admitted.get("attempt"))

        mismatch = self._p0_proof("second")
        mismatch["release"] = "another-release"
        room = relay.room(first["room"]["room_id"], second["member_token"])
        with self.assertRaises(RelayError) as raised:
            relay.v2_ready(
                room["room_id"], second["member_token"], {
                    "ready": True, "switch_room_role": "finder", "p0": mismatch,
                }, expected_version=room["room_version"])
        self.assertEqual(raised.exception.status, 409)

        duplicate_run = self._p0_proof("second")
        duplicate_run["run_id"] = first_proof["run_id"]
        with self.assertRaises(RelayError) as raised:
            relay.v2_ready(
                room["room_id"], second["member_token"], {
                    "ready": True, "switch_room_role": "finder", "p0": duplicate_run,
                }, expected_version=room["room_version"])
        self.assertEqual(raised.exception.status, 409)
        self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_rejects_legacy_attempt_and_changed_launch_identity(self):
        relay = RelayClient(self.base)
        legacy_first = relay.create_trade_room({
            "name": "V2 legacy", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-legacy-a")
        legacy_second = relay.join_trade_room(
            legacy_first["room"]["room_code"], "B", "v2-legacy-b")
        legacy_attempt = self._prepare_authority_attempt(legacy_first, legacy_second)
        legacy_room = relay.room(
            legacy_first["room"]["room_id"], legacy_first["member_token"])
        with self.assertRaises(RelayError) as raised:
            relay.v2_ready(
                legacy_room["room_id"], legacy_first["member_token"], {
                    "ready": True, "switch_room_role": "creator",
                    "p0": self._p0_proof("too-late"),
                }, expected_version=legacy_room["room_version"])
        self.assertEqual(raised.exception.status, 409)
        rejected = TunnelClientV2(
            self.base, legacy_first["room"]["room_code"], legacy_attempt, "member_a",
            legacy_first["member_token"], run_id=uuid7(), stage_generation=1,
            launch_nonce="x" * 32, endpoint_pid=4101).start()
        try:
            self.assertFalse(rejected.wait_authenticated(0.5))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not rejected.last_error_code:
                time.sleep(0.02)
            self.assertEqual(rejected.last_error_code, "C_AUTHENTICATION_FAILED", (
                rejected.last_error_type, rejected.last_error))
        finally:
            rejected.stop()
            self._close_authority_room(
                legacy_first["room"]["room_id"], legacy_first["member_token"])

        first = relay.create_trade_room({
            "name": "V2 launch", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-launch-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-launch-b")
        attempt_id = self._prepare_v2_attempt(first, second)
        first_client = self._v2_client(first, attempt_id, "member_a").start()
        second_client = self._v2_client(second, attempt_id, "member_b").start()
        changed = None
        try:
            self.assertTrue(first_client.wait_data_plane(5))
            self.assertTrue(second_client.wait_data_plane(5))
            first_client.stop()
            changed = self._v2_client(
                first, attempt_id, "member_a", launch_nonce="z" * 64).start()
            self.assertFalse(changed.wait_authenticated(0.5))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not changed.last_error_code:
                time.sleep(0.02)
            self.assertEqual(changed.last_error_code, "C_AUTHENTICATION_FAILED")
        finally:
            first_client.stop()
            if changed is not None:
                changed.stop()
            second_client.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_late_peer_replays_ready_before_advertisement_exactly_once(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 late peer", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-late-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-late-b")
        attempt_id = self._prepare_v2_attempt(first, second)

        async def exercise() -> list[EnvelopeV2]:
            import websockets

            header_name = ("additional_headers" if "additional_headers" in
                           inspect.signature(websockets.connect).parameters else "extra_headers")
            root = self.base.replace("http://", "ws://", 1)
            path = (f"/v2/trade-rooms/{first['room']['room_code']}"
                    f"/attempts/{attempt_id}/ws")
            async with websockets.connect(
                    root + path, **{header_name: self._v2_headers(first)}) as source:
                await source.send(EnvelopeV2(
                    attempt_id, SourceSeat.MEMBER_A, 101, 0, KindV2.PEER_READY).encode())
                await source.send(EnvelopeV2(
                    attempt_id, SourceSeat.MEMBER_A, 101, 1,
                    KindV2.ADVERTISEMENT, b"retained-room").encode())
                async with websockets.connect(
                        root + path, **{header_name: self._v2_headers(second)}) as peer:
                    frames = [
                        EnvelopeV2.decode(await asyncio.wait_for(peer.recv(), 2)),
                        EnvelopeV2.decode(await asyncio.wait_for(peer.recv(), 2)),
                    ]
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(peer.recv(), 0.1)
                    return frames

        try:
            frames = asyncio.run(exercise())
            self.assertEqual([frame.sequence for frame in frames], [0, 1])
            self.assertEqual([frame.kind for frame in frames],
                             [KindV2.PEER_READY, KindV2.ADVERTISEMENT])
        finally:
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_clients_prove_both_directions_before_verified_advertisement(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 probe", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-probe-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-probe-b")
        attempt_id = self._prepare_v2_attempt(first, second)
        payload = b"validated-A-advertisement"
        first_client = self._v2_client(first, attempt_id, "member_a")
        second_client = self._v2_client(
            second, attempt_id, "member_b",
            expected_advertisement_hash=advertisement_hash(payload))
        try:
            with self.assertRaises(ConnectionError):
                first_client.advertise(payload)
            first_client.start()
            second_client.start()
            self.assertTrue(first_client.wait_authenticated(5))
            self.assertTrue(second_client.wait_authenticated(5))
            self.assertTrue(first_client.wait_peer_ready(5))
            self.assertTrue(second_client.wait_peer_ready(5))
            self.assertTrue(first_client.wait_data_plane(5))
            self.assertTrue(second_client.wait_data_plane(5))
            self.assertEqual(first_client.advertise(payload), advertisement_hash(payload))
            deadline = time.monotonic() + 5
            received = None
            while time.monotonic() < deadline:
                received = next((frame for frame in second_client.poll()
                                 if frame.kind is KindV2.ADVERTISEMENT), None)
                if received:
                    break
                time.sleep(0.02)
            self.assertIsNotNone(received)
            self.assertEqual(received.payload, payload)
            self.assertEqual(second_client.received_advertisement_hash,
                             advertisement_hash(payload))
        finally:
            first_client.stop()
            second_client.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_creator_can_be_member_b_without_changing_relay_seat(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 reversed", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-reversed-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-reversed-b")
        attempt_id = self._prepare_v2_attempt(first, second, first_role="finder")
        payload = b"member-b-created-advertisement"
        first_client = self._v2_client(
            first, attempt_id, "member_a",
            expected_advertisement_hash=advertisement_hash(payload))
        second_client = self._v2_client(second, attempt_id, "member_b")
        try:
            first_client.start()
            second_client.start()
            self.assertTrue(first_client.wait_data_plane(5))
            self.assertTrue(second_client.wait_data_plane(5))
            second_client.advertise(payload)
            deadline = time.monotonic() + 5
            received = None
            while time.monotonic() < deadline:
                received = next((frame for frame in first_client.poll()
                                 if frame.kind is KindV2.ADVERTISEMENT), None)
                if received:
                    break
                time.sleep(0.02)
            self.assertIsNotNone(received)
            self.assertEqual(received.payload, payload)
        finally:
            first_client.stop()
            second_client.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_gap_fails_attempt_factually_and_erases_retention(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 gap", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-gap-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-gap-b")
        attempt_id = self._prepare_v2_attempt(first, second)

        async def send_gap() -> int | None:
            import websockets

            header_name = ("additional_headers" if "additional_headers" in
                           inspect.signature(websockets.connect).parameters else "extra_headers")
            url = (self.base.replace("http://", "ws://", 1) +
                   f"/v2/trade-rooms/{first['room']['room_code']}/attempts/{attempt_id}/ws")
            async with websockets.connect(
                    url, **{header_name: self._v2_headers(first)}) as websocket:
                await websocket.send(EnvelopeV2(
                    attempt_id, SourceSeat.MEMBER_A, 5, 0, KindV2.PEER_READY).encode())
                await websocket.send(EnvelopeV2(
                    attempt_id, SourceSeat.MEMBER_A, 5, 2,
                    KindV2.ADVERTISEMENT, b"gap").encode())
                try:
                    await websocket.recv()
                except Exception as error:
                    received = getattr(error, "rcvd", None)
                    return getattr(received, "code", None)
            return None

        try:
            self.assertEqual(asyncio.run(send_gap()), 4400)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                room = relay.room(first["room"]["room_id"], second["member_token"])
                if room["attempt"]["phase"] == "failed":
                    break
                time.sleep(0.02)
            self.assertEqual(room["attempt"]["recoverable_error"], "relay.c_sequence_gap")
            with urlopen(f"{self.base}/metrics", timeout=5) as response:
                metrics = json.load(response)
            self.assertEqual(metrics["live_rfu_v2_attempts"], 0)
            self.assertEqual(metrics["admitted_rfu_v2_attempts"], 0)
        finally:
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_reconnect_reproves_nonce_with_fresh_epochs(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 reconnect", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-reconnect-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-reconnect-b")
        attempt_id = self._prepare_v2_attempt(first, second)
        payload = b"reconnect-stable-advertisement"
        first_log, second_log, replacement_log = [], [], []
        first_client = self._v2_client(
            first, attempt_id, "member_a", log=first_log.append).start()
        second_client = self._v2_client(
            second, attempt_id, "member_b",
            expected_advertisement_hash=advertisement_hash(payload),
            log=second_log.append).start()
        replacement = None
        try:
            self.assertTrue(first_client.wait_data_plane(5))
            self.assertTrue(second_client.wait_data_plane(5))
            first_client.advertise(payload)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not second_client.poll():
                time.sleep(0.02)
            self.assertEqual(second_client.received_advertisement_hash,
                             advertisement_hash(payload))
            first_client.stop()
            replacement = self._v2_client(
                first, attempt_id, "member_a", log=replacement_log.append).start()
            self.assertTrue(replacement.wait_data_plane(8), (
                replacement.last_error_code, replacement.last_error, replacement_log,
                replacement.connection_generation, replacement.peer_ready.is_set(), replacement.stats,
                second_client.last_error_code, second_client.last_error, second_log,
                second_client.connection_generation, second_client.peer_ready.is_set(), second_client.stats))
            self.assertTrue(second_client.wait_data_plane(8), (
                replacement.last_error_code, replacement.last_error, replacement_log,
                second_client.last_error_code, second_client.last_error, second_log))
            self.assertEqual(second_client.connection_generation, 1)
            self.assertGreaterEqual(second_client.proof_generation, 2)
            replacement.advertise(payload)
            deadline = time.monotonic() + 5
            while (time.monotonic() < deadline and
                   second_client.stats["advertisement_replays"] < 1):
                time.sleep(0.02)
            self.assertEqual(second_client.poll(), [])
            self.assertEqual(second_client.stats["advertisement_replays"], 1)
        finally:
            first_client.stop()
            if replacement is not None:
                replacement.stop()
            second_client.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

    def test_v2_duplicate_stale_epoch_and_wrong_attempt_fail_through_relay(self):
        cases = (
            ("duplicate", lambda attempt: [
                EnvelopeV2(attempt, SourceSeat.MEMBER_A, 1, 0, KindV2.PEER_READY),
                EnvelopeV2(attempt, SourceSeat.MEMBER_A, 1, 0, KindV2.PEER_READY),
            ], "relay.c_sequence_duplicate"),
            ("stale", lambda attempt: [
                EnvelopeV2(attempt, SourceSeat.MEMBER_A, 1, 0, KindV2.PEER_READY),
                EnvelopeV2(attempt, SourceSeat.MEMBER_A, 2, 0, KindV2.PEER_READY),
                EnvelopeV2(attempt, SourceSeat.MEMBER_A, 1, 1,
                           KindV2.ADVERTISEMENT, b"stale"),
            ], "relay.c_epoch_stale"),
            ("wrong-attempt", lambda attempt: [
                EnvelopeV2(attempt + "-wrong", SourceSeat.MEMBER_A, 1, 0, KindV2.PEER_READY),
            ], "relay.c_identity_mismatch"),
        )
        for name, frame_factory, expected_code in cases:
            with self.subTest(name=name):
                relay = RelayClient(self.base)
                first = relay.create_trade_room({
                    "name": f"V2 {name}", "visibility": "private", "trainer_display_name": "A",
                    "game": "FireRed", "language": "English",
                    "offering": "", "wanted": "", "note": "",
                }, f"v2-{name}-a")
                second = relay.join_trade_room(
                    first["room"]["room_code"], "B", f"v2-{name}-b")
                attempt_id = self._prepare_v2_attempt(first, second)

                async def send_invalid() -> int | None:
                    import websockets

                    header_name = ("additional_headers" if "additional_headers" in
                                   inspect.signature(websockets.connect).parameters
                                   else "extra_headers")
                    url = (self.base.replace("http://", "ws://", 1) +
                           f"/v2/trade-rooms/{first['room']['room_code']}"
                           f"/attempts/{attempt_id}/ws")
                    async with websockets.connect(
                            url, **{header_name: self._v2_headers(first)}) as websocket:
                        for frame in frame_factory(attempt_id):
                            await websocket.send(frame.encode())
                        try:
                            await websocket.recv()
                        except Exception as error:
                            received = getattr(error, "rcvd", None)
                            return getattr(received, "code", None)
                    return None

                try:
                    self.assertEqual(asyncio.run(send_invalid()), 4400)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        room = relay.room(first["room"]["room_id"], second["member_token"])
                        if room["attempt"]["phase"] == "failed":
                            break
                        time.sleep(0.02)
                    self.assertEqual(room["attempt"]["recoverable_error"], expected_code)
                finally:
                    self._close_authority_room(
                        first["room"]["room_id"], first["member_token"])

    def test_v2_relay_restart_fails_attempt_and_leaves_no_transport_namespace(self):
        relay = RelayClient(self.base)
        first = relay.create_trade_room({
            "name": "V2 restart", "visibility": "private", "trainer_display_name": "A",
            "game": "FireRed", "language": "English", "offering": "", "wanted": "", "note": "",
        }, "v2-restart-a")
        second = relay.join_trade_room(first["room"]["room_code"], "B", "v2-restart-b")
        attempt_id = self._prepare_v2_attempt(first, second)
        first_client = self._v2_client(first, attempt_id, "member_a").start()
        second_client = self._v2_client(second, attempt_id, "member_b").start()
        try:
            self.assertTrue(first_client.wait_data_plane(5))
            self.assertTrue(second_client.wait_data_plane(5))
            self._stop_relay()
            self._start_relay()
            relay = RelayClient(self.base)
            room = relay.room(first["room"]["room_id"], first["member_token"])
            self.assertEqual(room["attempt"]["phase"], "failed")
            self.assertEqual(room["attempt"]["recoverable_error"], "relay.restart")
            with urlopen(f"{self.base}/metrics", timeout=5) as response:
                self.assertEqual(json.load(response)["live_rfu_v2_attempts"], 0)
        finally:
            first_client.stop()
            second_client.stop()
            self._close_authority_room(first["room"]["room_id"], first["member_token"])

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
