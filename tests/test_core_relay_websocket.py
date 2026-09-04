from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from relay.core_server import create_app
from switchtrade.core.contracts import PairSeat
from switchtrade.transport import Envelope, FrameKind


CAPABILITIES = {"endpoint_kind": "fake", "runtime_kind": "in_process", "protocols": ["switchtrade.fake.v1"], "generation_roles": ["origin"]}
MIRROR = {**CAPABILITIES, "generation_roles": ["mirror"]}


class CoreRelayWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.client = TestClient(self.app)
        self.host = self.client.post("/core/v1/pairs", json={"capabilities": CAPABILITIES}).json()
        self.guest = self.client.post("/core/v1/pairs:join", json={"code": self.host["code"], "capabilities": MIRROR}).json()
        self.path = f"/core/v1/pairs/{self.host['pair_id']}/ws"

    def test_relay_forwards_opaque_binary_frame_to_peer(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host, self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.guest['access_token']}"}) as guest:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            self.assertEqual(guest.receive_json(), {"seat": "guest"})
            raw = Envelope(FrameKind.PEER_READY, PairSeat.HOST, 1, 0).encode()
            host.send_bytes(raw)
            self.assertEqual(guest.receive_bytes(), raw)

    def test_relay_rejects_frame_claiming_another_seat(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            host.send_bytes(Envelope(FrameKind.PEER_READY, PairSeat.GUEST, 1, 0).encode())
            with self.assertRaises(WebSocketDisconnect) as closed:
                host.receive_bytes()
            self.assertEqual(closed.exception.code, 4403)
        self.assertFalse(self.app.state.core_sockets)

    def test_relay_closes_malformed_binary_frame(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            host.send_bytes(b"not-a-frame")
            with self.assertRaises(WebSocketDisconnect) as closed:
                host.receive_bytes()
            self.assertEqual(closed.exception.code, 4400)
        self.assertFalse(self.app.state.core_sockets)

    def test_reconnect_discards_stale_pending_frames(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.guest['access_token']}"}) as guest:
                self.assertEqual(guest.receive_json(), {"seat": "guest"})
            host.send_bytes(Envelope(FrameKind.DATA, PairSeat.HOST, 1, 1, "old-generation", b"stale").encode())
            with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.guest['access_token']}"}) as guest:
                self.assertEqual(guest.receive_json(), {"seat": "guest"})
                fresh = Envelope(FrameKind.HEARTBEAT, PairSeat.HOST, 1, 2).encode()
                host.send_bytes(fresh)
                self.assertEqual(guest.receive_bytes(), fresh)

    def test_relay_queue_overflow_closes_and_cleans_socket(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            for sequence in range(9):
                host.send_bytes(Envelope(FrameKind.HEARTBEAT, PairSeat.HOST, 1, sequence).encode())
            with self.assertRaises(WebSocketDisconnect) as closed:
                host.receive_bytes()
            self.assertEqual(closed.exception.code, 4408)
        self.assertFalse(self.app.state.core_sockets)


if __name__ == "__main__":
    unittest.main()
