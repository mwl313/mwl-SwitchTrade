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
        self.client = TestClient(create_app())
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

    def test_relay_closes_malformed_binary_frame(self) -> None:
        with self.client.websocket_connect(self.path, headers={"authorization": f"Bearer {self.host['access_token']}"}) as host:
            self.assertEqual(host.receive_json(), {"seat": "host"})
            host.send_bytes(b"not-a-frame")
            with self.assertRaises(WebSocketDisconnect) as closed:
                host.receive_bytes()
            self.assertEqual(closed.exception.code, 4400)


if __name__ == "__main__":
    unittest.main()
