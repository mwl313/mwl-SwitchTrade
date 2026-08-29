import json
from pathlib import Path
import threading
import unittest

from switchtrade.connection.c_stage import CStage, CStageError, GATES
from switchtrade.rfu_tunnel_v2 import Envelope, Kind, SourceSeat, advertisement_hash


class FakeClient:
    def __init__(self, seat="member_a"):
        self.attempt_id = "attempt-1"
        self.source_seat = SourceSeat.parse(seat)
        self.authenticated = threading.Event()
        self.peer_ready = threading.Event()
        self.data_plane_proven = threading.Event()
        self.last_error_code = self.last_error = ""
        self.received_advertisement_hash = None
        self.frames = []
        self.started = self.stopped = False

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True

    def advertise(self, payload):
        if not self.data_plane_proven.is_set():
            raise ConnectionError("not proven")
        return advertisement_hash(payload)

    def poll(self):
        frames, self.frames = self.frames, []
        return frames


class CStageTests(unittest.TestCase):
    def test_reports_distinct_c0_gates_and_redacted_c1_hash(self):
        client = FakeClient()
        for event in (client.authenticated, client.peer_ready, client.data_plane_proven):
            event.set()
        passed = []
        stage = CStage(
            "run-1", "attempt-1", "member_a", "a_room_joiner", client,
            gate_sink=lambda value: passed.append(value["gate"]),
        )
        stage.connect(0.1)
        digest = stage.publish_advertisement(b"private-advertisement")
        report = stage.report()
        self.assertEqual(passed, list(GATES[:3]))
        self.assertEqual(report["last_passed_gate"], GATES[2])
        self.assertEqual(report["advertisement_sha256"], digest)
        self.assertNotIn("private-advertisement", json.dumps(report))

    def test_b_side_delivers_one_hash_and_timeout_is_factual(self):
        client = FakeClient("member_b")
        client.received_advertisement_hash = advertisement_hash(b"room")
        client.frames = [Envelope(
            "attempt-1", SourceSeat.MEMBER_A, 1, 3, Kind.ADVERTISEMENT, b"room")]
        stage = CStage("run-2", "attempt-1", "member_b", "b_ap_host", client)
        self.assertEqual(stage.receive_advertisement(0.1), advertisement_hash(b"room"))
        self.assertEqual(stage.report()["last_passed_gate"], GATES[3])

        empty = CStage(
            "run-3", "attempt-1", "member_b", "b_ap_host", FakeClient("member_b"))
        with self.assertRaises(CStageError) as raised:
            empty.receive_advertisement(0.01)
        self.assertEqual(raised.exception.code, "C_ADVERTISEMENT_TIMEOUT")

    def test_contract_schema_matches_report_projection(self):
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "c0-c1-stage.v1.schema.json").read_text(encoding="utf-8"))
        stage = CStage(
            "run-4", "attempt-1", "member_a", "a_room_joiner", FakeClient())
        self.assertEqual(set(stage.report()), set(schema["required"]))


if __name__ == "__main__":
    unittest.main()
