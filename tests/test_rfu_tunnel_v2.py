import unittest

from switchtrade.rfu_tunnel_v2 import (
    HEADER,
    MAX_PAYLOAD_BYTES,
    Envelope,
    Kind,
    SequenceGate,
    SourceSeat,
    TunnelV2Error,
    advertisement_hash,
    new_probe,
    verify_advertisement,
    verify_probe,
)


class EnvelopeV2Tests(unittest.TestCase):
    def test_all_control_kinds_round_trip_with_utf8_attempt_identity(self):
        payloads = {
            Kind.PEER_READY: b"",
            Kind.PROBE_CHALLENGE: b"c" * 32,
            Kind.PROBE_RESPONSE: b"r" * 32,
            Kind.ADVERTISEMENT: b"advertisement",
            Kind.SIDE_READY: b'{"stage":"A_READY"}',
            Kind.PEER_CLOSE: b"normal",
        }
        for sequence, (kind, payload) in enumerate(payloads.items()):
            expected = Envelope("시도-1", SourceSeat.MEMBER_A, 7, sequence, kind, payload)
            self.assertEqual(Envelope.decode(expected.encode()), expected)

    def test_decode_rejects_bad_header_length_and_payload_semantics(self):
        valid = Envelope("attempt-1", SourceSeat.MEMBER_A, 1, 0, Kind.PEER_READY).encode()
        for raw in (b"", valid[:-1], b"BAD!" + valid[4:]):
            with self.assertRaises(TunnelV2Error):
                Envelope.decode(raw)
        with self.assertRaisesRegex(TunnelV2Error, "32 bytes"):
            Envelope("attempt-1", SourceSeat.MEMBER_A, 1, 0,
                     Kind.PROBE_CHALLENGE, b"short").encode()
        with self.assertRaisesRegex(TunnelV2Error, "exceeds"):
            Envelope("attempt-1", SourceSeat.MEMBER_A, 1, 0,
                     Kind.ADVERTISEMENT, b"x" * (MAX_PAYLOAD_BYTES + 1)).encode()
        self.assertLess(HEADER.size, len(valid))


class SequenceGateV2Tests(unittest.TestCase):
    def setUp(self):
        self.gate = SequenceGate("attempt-1", "member_b")

    def frame(self, epoch, sequence, kind=Kind.PEER_READY, attempt="attempt-1",
              seat=SourceSeat.MEMBER_B, payload=b""):
        return Envelope(attempt, seat, epoch, sequence, kind, payload)

    def test_accepts_only_contiguous_stream_and_clean_reconnect(self):
        self.gate.accept(self.frame(11, 0))
        self.gate.accept(self.frame(11, 1, Kind.ADVERTISEMENT, payload=b"room"))
        self.gate.accept(self.frame(12, 0))
        self.gate.accept(self.frame(12, 1, Kind.PROBE_CHALLENGE, payload=b"n" * 32))
        self.assertEqual(self.gate.epoch, 12)
        self.assertEqual(self.gate.next_sequence, 2)

    def test_rejects_wrong_identity_gap_duplicate_stale_epoch_and_bad_epoch_start(self):
        self.gate.accept(self.frame(11, 0))
        cases = (
            (self.frame(11, 0), "C_SEQUENCE_DUPLICATE"),
            (self.frame(11, 1), "C_PEER_READY_DUPLICATE"),
            (self.frame(11, 2, Kind.ADVERTISEMENT, payload=b"room"), "C_SEQUENCE_GAP"),
            (self.frame(11, 1, attempt="attempt-2"), "C_ATTEMPT_MISMATCH"),
            (self.frame(11, 1, seat=SourceSeat.MEMBER_A), "C_SOURCE_SEAT_MISMATCH"),
            (self.frame(12, 1, Kind.ADVERTISEMENT, payload=b"room"), "C_EPOCH_START_INVALID"),
        )
        for frame, code in cases:
            with self.subTest(code=code), self.assertRaises(TunnelV2Error) as raised:
                self.gate.accept(frame)
            self.assertEqual(raised.exception.code, code)
        self.gate.accept(self.frame(12, 0))
        with self.assertRaises(TunnelV2Error) as raised:
            self.gate.accept(self.frame(11, 1, Kind.ADVERTISEMENT, payload=b"room"))
        self.assertEqual(raised.exception.code, "C_EPOCH_STALE")


class EvidenceV2Tests(unittest.TestCase):
    def test_probe_and_advertisement_evidence_fail_closed(self):
        first, second = new_probe(), new_probe()
        self.assertEqual(len(first), 32)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_probe(first, first))
        self.assertFalse(verify_probe(first, second))
        digest = advertisement_hash(b"room")
        self.assertTrue(verify_advertisement(b"room", digest))
        self.assertFalse(verify_advertisement(b"other", digest))
        self.assertFalse(verify_advertisement(b"room", "invalid"))


if __name__ == "__main__":
    unittest.main()
