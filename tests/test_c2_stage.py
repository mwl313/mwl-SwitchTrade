import json
from dataclasses import replace
from pathlib import Path
import threading
import unittest

from switchtrade.c2_protocol import CONTRACT, SideReady, launch_identity_hash
from switchtrade.connection.c2 import C2Bridge, C2StageError, MAX_PRE_BARRIER_FRAMES
from switchtrade.rfu_tunnel_v2 import (
    Envelope, Kind, SourceSeat, TunnelV2Error, advertisement_hash,
)


RUN_A = "018f3e10-1111-7000-8000-000000000001"
RUN_B = "018f3e10-2222-7000-8000-000000000002"
ATTEMPT = "attempt-c2"
ADVERTISEMENT_HASH = advertisement_hash(b"advertisement")


class FakeClient:
    def __init__(self, seat="member_a", run_id=RUN_A):
        self.attempt_id = ATTEMPT
        self.source_seat = SourceSeat.parse(seat)
        self.run_id = run_id
        self.stage_generation = 1
        self.launch_nonce = "n" * 64
        self.endpoint_pid = 6101
        self.data_plane_proven = threading.Event()
        self.data_plane_proven.set()
        self.proof_generation = 1
        self.last_error_code = self.last_error = ""
        self.frames = []
        self.side_ready = []
        self.rfu = []

    def send_side_ready(self, payload):
        self.side_ready.append(bytes(payload))

    def send_rfu(self, payload, *, flags):
        self.rfu.append((bytes(payload), flags))

    def poll(self):
        frames, self.frames = self.frames, []
        return frames


def peer_ready(epoch=11, proof=1, *, advertisement=ADVERTISEMENT_HASH,
               role="b_ap_host", seat="member_b", run_id=RUN_B):
    ready = SideReady(
        CONTRACT, ATTEMPT, 1, seat, role,
        "B_READY" if role == "b_ap_host" else "A_READY",
        run_id, 1, "a" * 64, advertisement, proof,
    )
    return Envelope(
        ATTEMPT, SourceSeat.parse(seat), epoch, 4, Kind.SIDE_READY, ready.encode()
    )


class C2BridgeTests(unittest.TestCase):
    def bridge(self):
        client = FakeClient()
        bridge = C2Bridge(
            RUN_A, ATTEMPT, "member_a", "a_room_joiner", client,
            activation_generation=1, advertisement_sha256=ADVERTISEMENT_HASH,
        )
        return bridge, client

    def activate(self):
        bridge, client = self.bridge()
        bridge.mark_local_ready("A_READY")
        client.frames.append(peer_ready())
        bridge.pump()
        self.assertTrue(bridge.connected.is_set())
        return bridge, client

    def test_delayed_peer_holds_and_flushes_byte_exact_rfu(self):
        bridge, client = self.bridge()
        payload = b"\x57\x00opaque-reliable"
        bridge.send_rfu(payload, flags=0x0F)
        bridge.mark_local_ready("A_READY")
        self.assertFalse(bridge.connected.is_set())
        self.assertEqual(client.rfu, [])
        self.assertEqual(len(client.side_ready), 1)

        client.frames.append(peer_ready())
        bridge.pump()
        self.assertTrue(bridge.connected.is_set())
        self.assertEqual(client.rfu, [(payload, 0x0F)])
        self.assertFalse(bridge.rfu_active.is_set())

        remote = b"\x57\x01remote-byte-exact"
        client.frames.append(Envelope(
            ATTEMPT, SourceSeat.MEMBER_B, 11, 5, Kind.RFU, remote, 0x07,
        ))
        received = bridge.poll()
        self.assertEqual([(frame.payload, frame.flags) for frame in received], [(remote, 0x07)])
        self.assertTrue(bridge.rfu_active.is_set())
        self.assertEqual(bridge.last_passed_gate, "C_RFU_ACTIVE")

    def test_one_sided_ready_never_becomes_bridge_active(self):
        bridge, client = self.bridge()
        bridge.mark_local_ready("A_READY")
        bridge.send_rfu(b"queued", flags=0x01)
        bridge.pump()
        self.assertFalse(bridge.connected.is_set())
        self.assertFalse(bridge.rfu_active.is_set())
        self.assertEqual(client.rfu, [])

    def test_delayed_a_and_reverse_role_mapping_activate(self):
        client = FakeClient("member_b", RUN_B)
        bridge = C2Bridge(
            RUN_B, ATTEMPT, "member_b", "b_ap_host", client,
            activation_generation=1, advertisement_sha256=ADVERTISEMENT_HASH,
        )
        bridge.send_rfu(b"b-before-a", flags=0x01)
        bridge.mark_local_ready("B_READY")
        self.assertFalse(bridge.connected.is_set())

        client.frames.append(peer_ready(
            role="a_room_joiner", seat="member_a", run_id=RUN_A,
        ))
        bridge.pump()
        self.assertTrue(bridge.connected.is_set())
        self.assertEqual(client.rfu, [(b"b-before-a", 0x01)])

    def test_pre_barrier_queue_overflow_and_cancel_fail_closed(self):
        bridge, _client = self.bridge()
        for index in range(MAX_PRE_BARRIER_FRAMES):
            bridge.send_rfu(index.to_bytes(2, "big"), flags=0x01)
        with self.assertRaises(C2StageError) as raised:
            bridge.send_rfu(b"overflow", flags=0x01)
        self.assertEqual(raised.exception.code, "C_PRE_BARRIER_OVERFLOW")

        canceled, client = self.bridge()
        canceled.send_rfu(b"discard", flags=0x01)
        canceled.cancel()
        canceled.cancel()
        self.assertEqual(canceled.report()["queued_local_frames"], 0)
        self.assertEqual(canceled.report()["failure"]["code"], "C_CANCELED")
        self.assertEqual(client.rfu, [])
        with self.assertRaises(C2StageError) as raised:
            canceled.send_rfu(b"must-not-queue", flags=0x01)
        self.assertEqual(raised.exception.code, "C_CANCELED")
        self.assertEqual(canceled.report()["queued_local_frames"], 0)

    def test_reconnect_invalidates_once_and_reproves_side_ready(self):
        bridge, client = self.activate()
        client.data_plane_proven.clear()
        bridge.pump()
        bridge.pump()
        self.assertFalse(bridge.connected.is_set())
        self.assertEqual(bridge.stats["invalidations"], 1)

        client.proof_generation = 2
        client.data_plane_proven.set()
        bridge.pump()
        self.assertEqual(len(client.side_ready), 2)
        client.frames.append(peer_ready(epoch=12, proof=2))
        bridge.pump()
        self.assertTrue(bridge.connected.is_set())
        self.assertEqual(bridge.stats["activation_count"], 2)

    def test_stale_changed_and_duplicate_readiness_are_rejected(self):
        bridge, client = self.bridge()
        bridge.mark_local_ready("A_READY")
        client.frames.append(peer_ready(advertisement="b" * 64))
        with self.assertRaises(C2StageError) as raised:
            bridge.pump()
        self.assertEqual(raised.exception.code, "C_SIDE_READY_ADVERTISEMENT")

        bridge, client = self.activate()
        client.frames.append(peer_ready())
        with self.assertRaises(C2StageError) as raised:
            bridge.pump()
        self.assertEqual(raised.exception.code, "C_SIDE_READY_DUPLICATE")

    def test_report_matches_schema_and_never_contains_payload(self):
        bridge, _client = self.bridge()
        bridge.send_rfu(b"private-rfu", flags=0x01)
        report = bridge.report()
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "c2-stage.v1.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(set(report), set(schema["required"]))
        self.assertNotIn("private-rfu", json.dumps(report))

    def test_side_ready_contract_is_canonical_and_strict(self):
        launch_hash = launch_identity_hash(RUN_A, 1, "x" * 64, 6101)
        ready = SideReady(
            CONTRACT, ATTEMPT, 1, "member_a", "a_room_joiner", "A_READY",
            RUN_A, 1, launch_hash, ADVERTISEMENT_HASH, 1,
        )
        self.assertEqual(SideReady.decode(ready.encode()), ready)
        changed = json.loads(ready.encode())
        changed["unexpected"] = True
        with self.assertRaisesRegex(TunnelV2Error, "payload is invalid"):
            SideReady.decode(json.dumps(changed).encode())
        with self.assertRaisesRegex(TunnelV2Error, "attempt is invalid"):
            replace(ready, attempt_id="\ud800").validate()


if __name__ == "__main__":
    unittest.main()
