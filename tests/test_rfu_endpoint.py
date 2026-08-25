"""Internal RFU-boundary tests; no LDN, keys, radio, or Switch required."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))

from frlgsim.transport import HostTransport
from frlgsim.tunnel import TunnelSim
from switchtrade.rfu_tunnel import Direction, Envelope, Kind


class FakeTunnel:
    def __init__(self):
        self.sent = []
        self.inbound = []

    def send(self, payload, **fields):
        self.sent.append((bytes(payload), fields))

    def poll(self):
        inbound, self.inbound = self.inbound, []
        return inbound


class FakeObserver:
    def __init__(self):
        self.frames = []

    def submit(self, seat, role, payload):
        self.frames.append((seat, role, bytes(payload)))


class RfuEndpointTest(unittest.TestCase):
    def _sim(self, parent=False):
        tunnel = FakeTunnel()
        sim = TunnelSim(object(), object(), "169.254.1.2", "169.254.1.1", tunnel,
                        conn=None, our_var=0xC493, parent=parent)
        batches = []
        sim._tx_reliable_batch = lambda batch: batches.extend(batch)
        return sim, tunnel, batches

    def test_local_reliable_payload_is_forwarded_opaque(self):
        sim, tunnel, _ = self._sim()
        payload = b"\x57future-feature-opcodes-are-not-decoded"
        sim._on_reliable_app(0x0F, payload)
        self.assertEqual(tunnel.sent, [(payload, {"kind": Kind.RFU, "flags": 0x0F})])

    def test_remote_payload_is_rewrapped_with_original_flags(self):
        sim, tunnel, batches = self._sim(parent=True)
        tunnel.inbound.append(Envelope(
            "ABC123", Direction.HOST_TO_GUEST, 0, 7, 0, 1,
            b"\x57raw-rfu", kind=Kind.RFU, flags=0x07,
        ))
        sim._drive_tunnel_reliable()
        self.assertEqual(len(batches), 1)
        sequence, flags, payload = batches[0]
        self.assertIsInstance(sequence, int)
        self.assertEqual(flags, 0x07)
        self.assertEqual(payload, b"\x57raw-rfu")

    def test_passive_observer_receives_both_streams_without_changing_forwarding(self):
        observer = FakeObserver()
        tunnel = FakeTunnel()
        sim = TunnelSim(
            object(), object(), "169.254.1.2", "169.254.1.1", tunnel,
            conn=None, our_var=0xC493, parent=False, observer=observer,
            local_seat="member_a",
        )
        batches = []
        sim._tx_reliable_batch = lambda batch: batches.extend(batch)
        sim._on_reliable_app(0x01, b"local")
        tunnel.inbound.append(Envelope(
            "ABC123", Direction.GUEST_TO_HOST, 0, 1, 1, 0,
            b"remote", kind=Kind.RFU, flags=0x01,
        ))
        sim._drive_tunnel_reliable()
        self.assertEqual(tunnel.sent[0][0], b"local")
        self.assertEqual(batches[0][2], b"remote")
        self.assertEqual(observer.frames, [
            ("member_a", "parent", b"local"),
            ("member_b", "child", b"remote"),
        ])

    def test_non_appdata_and_control_frames_are_not_injected(self):
        sim, tunnel, batches = self._sim()
        tunnel.inbound.extend((
            Envelope("ABC123", Direction.HOST_TO_GUEST, 0, 1, 0, 1,
                     b"not-app", kind=Kind.RFU, flags=0),
            Envelope("ABC123", Direction.HOST_TO_GUEST, 0, 2, 0, 1,
                     b"ad", kind=Kind.ADVERTISEMENT),
        ))
        sim._drive_tunnel_reliable()
        self.assertEqual(batches, [])

    def test_host_transport_keeps_mirrored_advertisement_override(self):
        transport = HostTransport(application_data=b"leader-advertisement")
        self.assertEqual(transport._application_data_override, b"leader-advertisement")


if __name__ == "__main__":
    unittest.main()
