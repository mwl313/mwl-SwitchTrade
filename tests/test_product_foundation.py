import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from switchtrade.diagnostics import RunLogger
from switchtrade.endpoint import runtime_plan
from switchtrade.hardware import load_profiles
from switchtrade.party_observer import (
    CONFIRM_FINISH_TRADE, READY_FINISH_TRADE, READY_TO_TRADE,
    SET_MONS_TO_TRADE, START_TRADE, PassivePartyObserver,
)
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
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
        independent = runtime_plan("member_a", switch_room_role="finder")
        self.assertEqual(independent["tunnel_role"], "host")
        self.assertEqual(independent["radio_role"], "host")
        with self.assertRaises(ValueError):
            runtime_plan("host", "0bda:8179")


class DiagnosticsTests(unittest.TestCase):
    def test_redaction_and_support_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            logger = RunLogger("test", temporary)
            logger.event("credentials", passcode="ABC123", session_id="ABC123",
                         member_token="MEMBER-SECRET", reconnect_token="RECONNECT-SECRET", packets=4)
            event = json.loads(logger._events.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["passcode"], "<redacted>")
            self.assertEqual(event["session_id"], "<redacted>")
            self.assertEqual(event["member_token"], "<redacted>")
            self.assertEqual(event["reconnect_token"], "<redacted>")
            self.assertEqual(event["packets"], 4)
            bundle = logger.support_bundle(summary={"session_id": "ABC123", "packets": 4})
            with zipfile.ZipFile(bundle) as archive:
                self.assertIn("privacy-manifest.json", archive.namelist())
                summary = json.loads(archive.read("runtime-summary.json"))
                self.assertEqual(summary["session_id"], "<redacted>")

    def test_process_lock_rejects_a_duplicate_and_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = SingleInstanceLock("test", temporary).acquire()
            try:
                with self.assertRaises(AlreadyRunningError):
                    SingleInstanceLock("test", temporary).acquire()
            finally:
                first.close()
            SingleInstanceLock("test", temporary).acquire().close()


class PassiveObserverTests(unittest.TestCase):
    @staticmethod
    def _publish(observer, seat, records):
        for ordinal in range(3):
            observer._consume_party_block(
                seat, SimpleNamespace(
                    payload=records[ordinal * 2] + records[ordinal * 2 + 1],
                    ordinal=ordinal,
                ))

    def test_bounded_queue_drops_without_blocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            observer = PassivePartyObserver(
                Path(temporary) / "party.json", "attempt", "member_a", capacity=1)
            observer.submit("member_a", "parent", b"first")
            observer.submit("member_a", "parent", b"second")
            self.assertEqual(observer.stats["dropped"], 1)

    def test_three_complete_party_blocks_publish_only_safe_projection(self):
        fixtures = Path(__file__).resolve().parents[1] / "archive" / "pokemon" / "fixtures"
        pair = ((fixtures / "0001_BULBASAUR_user_20260824.pk3").read_bytes() +
                (fixtures / "0019_RATTATA_user_20260824.pk3").read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            observer = PassivePartyObserver(
                Path(temporary) / "party.json", "attempt", "member_a")
            for ordinal in range(3):
                observer._consume_party_block(
                    "member_a", SimpleNamespace(payload=pair, ordinal=ordinal))
            snapshot = observer.snapshot()["parties"]["member_a"]["snapshot"]
            self.assertEqual(len(snapshot["slots"]), 6)
            self.assertTrue(all(slot["record_hash"].startswith("sha256:")
                                for slot in snapshot["slots"]))
            serialized = json.dumps(snapshot)
            self.assertNotIn("raw_hex", serialized)
            self.assertNotIn("canonical_hex", serialized)

    def test_trade_commit_requires_finish_save_and_swapped_post_parties(self):
        fixtures = Path(__file__).resolve().parents[1] / "archive" / "pokemon" / "fixtures"
        bulbasaur = (fixtures / "0001_BULBASAUR_user_20260824.pk3").read_bytes()
        rattata = (fixtures / "0019_RATTATA_user_20260824.pk3").read_bytes()
        salamence = (fixtures / "0373_SALAMENCE.pk3").read_bytes()
        before_a = [bulbasaur, rattata, rattata, rattata, rattata, rattata]
        before_b = [salamence] * 6
        with tempfile.TemporaryDirectory() as temporary:
            observer = PassivePartyObserver(
                Path(temporary) / "party.json", "attempt", "member_a")
            self._publish(observer, "member_a", before_a)
            self._publish(observer, "member_b", before_b)
            observer._observe_link_command("member_b", READY_TO_TRADE, 0)
            observer._observe_link_command("member_a", SET_MONS_TO_TRADE, 0)
            observer._observe_link_command("member_a", START_TRADE)
            observer._observe_link_command("member_b", READY_FINISH_TRADE)
            observer._observe_link_command("member_a", CONFIRM_FINISH_TRADE)
            for count in range(5, 11):
                observer._observe_save_count("member_a", count)
                observer._observe_save_count("member_b", count)
            self.assertEqual(observer.snapshot()["commits"], [])
            self._publish(observer, "member_a", [salamence, *before_a[1:]])
            self._publish(observer, "member_b", [bulbasaur, *before_b[1:]])
            commits = observer.snapshot()["commits"]
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0]["event"], "trade.committed")
            self.assertTrue(all(commits[0]["evidence"].values()))
            self._publish(observer, "member_a", [salamence, *before_a[1:]])
            self._publish(observer, "member_b", [bulbasaur, *before_b[1:]])
            self.assertEqual(len(observer.snapshot()["commits"]), 1)

    def test_trade_commit_fails_closed_on_rollback(self):
        fixtures = Path(__file__).resolve().parents[1] / "archive" / "pokemon" / "fixtures"
        a = [(fixtures / "0001_BULBASAUR_user_20260824.pk3").read_bytes()] * 6
        b = [(fixtures / "0373_SALAMENCE.pk3").read_bytes()] * 6
        with tempfile.TemporaryDirectory() as temporary:
            observer = PassivePartyObserver(
                Path(temporary) / "party.json", "attempt", "member_a")
            self._publish(observer, "member_a", a)
            self._publish(observer, "member_b", b)
            observer._observe_link_command("member_b", READY_TO_TRADE, 0)
            observer._observe_link_command("member_a", SET_MONS_TO_TRADE, 0)
            observer._observe_link_command("member_a", START_TRADE)
            observer._observe_link_command("member_b", READY_FINISH_TRADE)
            observer._observe_link_command("member_a", CONFIRM_FINISH_TRADE)
            for count in range(5, 11):
                observer._observe_save_count("member_a", count)
                observer._observe_save_count("member_b", count)
            self._publish(observer, "member_a", a)
            self._publish(observer, "member_b", b)
            self.assertEqual(observer.snapshot()["commits"], [])


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
