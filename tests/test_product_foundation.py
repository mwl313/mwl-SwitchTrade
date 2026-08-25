import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from switchtrade.diagnostics import RunLogger
from switchtrade.endpoint import runtime_plan
from switchtrade.hardware import load_profiles
from switchtrade.rfu_tunnel import (Direction, Envelope, PlayerMap, SequenceGate,
                                    direction_for_role)
from switchtrade.tunnel_client import relay_websocket_url


class HardwarePolicyTests(unittest.TestCase):
    def test_only_8192_is_auto_selected(self):
        profiles = load_profiles()
        automatic = [profile.usb_id for profile in profiles if profile.auto_select]
        self.assertEqual(automatic, ["0bda:818b"])
        rtl8188 = next(profile for profile in profiles if profile.usb_id == "0bda:8179")
        self.assertEqual(rtl8188.status, "quarantined")
        self.assertEqual(rtl8188.roles, ("observe",))

    def test_endpoint_roles_are_resolved_through_profiles(self):
        self.assertEqual(runtime_plan("host")["radio_role"], "guest")
        self.assertEqual(runtime_plan("guest")["radio_role"], "host")
        with self.assertRaises(ValueError):
            runtime_plan("host", "0bda:8179")


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
    def test_role_direction_and_relay_url_are_stable(self):
        self.assertEqual(direction_for_role("host"), Direction.HOST_TO_GUEST)
        self.assertEqual(direction_for_role("guest"), Direction.GUEST_TO_HOST)
        self.assertEqual(
            relay_websocket_url("https://relay.example/base", "ABC123", "guest"),
            "wss://relay.example/base/session/ABC123/ws?role=guest&protocol=rfu",
        )
        with self.assertRaises(ValueError):
            direction_for_role("observer")

    def test_envelope_ordering_and_player_mapping(self):
        first = Envelope("ABC123", Direction.HOST_TO_GUEST, 2, 5, 0, 1, b"rfu")
        decoded = Envelope.decode(first.encode())
        self.assertEqual(decoded.payload, b"rfu")
        gate = SequenceGate()
        self.assertTrue(gate.accept(decoded))
        self.assertFalse(gate.accept(decoded))
        restarted = Envelope("ABC123", Direction.HOST_TO_GUEST, 1, 0, 0, 1, b"restart")
        self.assertTrue(gate.accept(restarted))
        self.assertFalse(gate.accept(decoded))
        skipped = Envelope("ABC123", Direction.HOST_TO_GUEST, 1, 2, 0, 1, b"gap")
        self.assertTrue(gate.accept(skipped))
        self.assertEqual(gate.gaps, 1)
        guest = PlayerMap("guest")
        self.assertEqual(guest.local_to_wire(0), 1)
        self.assertEqual(guest.wire_to_local(0), 1)


if __name__ == "__main__":
    unittest.main()
