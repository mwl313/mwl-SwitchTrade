import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from switchtrade.diagnostics import RunLogger
from switchtrade.hardware import load_profiles
from switchtrade.rfu_tunnel import Direction, Envelope, PlayerMap, SequenceGate


class HardwarePolicyTests(unittest.TestCase):
    def test_only_8192_is_auto_selected(self):
        profiles = load_profiles()
        automatic = [profile.usb_id for profile in profiles if profile.auto_select]
        self.assertEqual(automatic, ["0bda:818b"])
        rtl8188 = next(profile for profile in profiles if profile.usb_id == "0bda:8179")
        self.assertEqual(rtl8188.status, "quarantined")
        self.assertEqual(rtl8188.roles, ("observe",))


class DiagnosticsTests(unittest.TestCase):
    def test_redaction_and_support_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = RunLogger("test", temporary)
            logger.event("credentials", passcode="ABC123", packets=4)
            event = json.loads(logger._events.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["passcode"], "<redacted>")
            self.assertEqual(event["packets"], 4)
            bundle = logger.support_bundle()
            with zipfile.ZipFile(bundle) as archive:
                self.assertIn("privacy-manifest.json", archive.namelist())


class RfuTunnelTests(unittest.TestCase):
    def test_envelope_ordering_and_player_mapping(self):
        first = Envelope("ABC123", Direction.HOST_TO_GUEST, 2, 5, 0, 1, b"rfu")
        decoded = Envelope.decode(first.encode())
        self.assertEqual(decoded.payload, b"rfu")
        gate = SequenceGate()
        self.assertTrue(gate.accept(decoded))
        self.assertFalse(gate.accept(decoded))
        self.assertFalse(gate.accept(Envelope("ABC123", Direction.HOST_TO_GUEST, 1, 99, 0, 1, b"old")))
        guest = PlayerMap("guest")
        self.assertEqual(guest.local_to_wire(0), 1)
        self.assertEqual(guest.wire_to_local(0), 1)


if __name__ == "__main__":
    unittest.main()
