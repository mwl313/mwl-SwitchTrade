import json
from pathlib import Path
import tempfile
import unittest

from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.connection import (
    AuthoritySeat,
    ConnectionCoordinator,
    DControlError,
    FunctionalOutcome,
    LocalDRelease,
    Phase,
    RunMode,
    SwitchRole,
)
from switchtrade.connection.p0 import atomic_json
from switchtrade.relay_client import RelayClient


ADAPTER = r"USB\VID_0BDA&PID_818B\RADIO-A"
NONCE = "a" * 32


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeLease:
    def __init__(self, events, result=None):
        self.events = events
        self.result = result or {
            "prior_state_restored": True,
            "windows_state_verified": True,
            "linux_state_verified": True,
            "detached_by_run": True,
        }

    def release(self):
        self.events.append("D10")
        return dict(self.result)


class LocalDReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.coordinator = ConnectionCoordinator(self.root / "coordinator", "0.3.0-dev")

    def tearDown(self):
        self.coordinator.close()
        self.temporary.cleanup()

    def prepare(self, mode=RunMode.NORMAL):
        software = mode == RunMode.C_HARNESS
        run = self.coordinator.start(
            mode,
            adapter_instance_id="software" if software else ADAPTER,
            usb_id="software" if software else "0bda:818b",
        )
        run_id = run["run_id"]
        self.coordinator.transition(run_id, Phase.PREFLIGHT, "P0a_release")
        self.coordinator.transition(run_id, Phase.RUNNING, "C0.1_authority")
        self.coordinator.bind_authority(
            run_id, room_id="room-1", room_version=7,
            seat=AuthoritySeat.MEMBER_A, switch_role=SwitchRole.A_ROOM_JOINER,
        )
        self.coordinator.acquire_wrapper(
            run_id, wrapper_pid=4001, process_start_ticks=101,
            adapter_instance_id="software" if software else ADAPTER,
            usb_id="software" if software else "0bda:818b",
            bus_id="software" if software else "4-18",
        )
        self.coordinator.mark_p0_ready(
            run_id, wrapper_pid=4001, process_start_ticks=101, phy="phy0", netdev="wlan0")
        self.coordinator.lock_attempt(run_id, attempt_id="attempt-1", role_lock_version=9)
        self.coordinator.reserve_endpoint_launch(run_id, launch_nonce=NONCE)
        self.coordinator.acknowledge_endpoint(
            run_id, launch_nonce=NONCE, endpoint_pid=5001, process_start_ticks=202)
        run = self.coordinator.close_run(run_id, FunctionalOutcome.CANCELED)
        identity = run["identity"]
        payload = {
            "contract_version": "d-side-quiescent.v1",
            "attempt_id": "attempt-1",
            "activation_generation": 3,
            "source_seat": "member_a",
            "run_id": run_id,
            "stage_generation": identity["stage_generation"],
            "launch_identity_sha256": launch_identity_hash(
                run_id, identity["stage_generation"], NONCE, identity["endpoint_pid"]),
            "evidence": {
                "endpoint_exited": True, "transport_exited": True, "threads_exited": True,
                "ldn_released": True, "interfaces_absent": True, "forced": False,
            },
        }
        d5_path = self.root / run_id / "d5-control-state.json"
        atomic_json(d5_path, {
            "contract_version": "d5-control-state.v1", "schema": 1,
            "run_id": run_id, "room_id": "room-1", "attempt_id": "attempt-1",
            "expected_room_version": 12,
            "command_id": RelayClient.command_id(),
            "endpoint_report_sha256": "a" * 64,
            "measurement": {
                "process_state_known": True, "temporary_interface_state_known": True},
            "payload": payload,
        }, private=True)
        side = {
            "run_id": payload["run_id"],
            "stage_generation": payload["stage_generation"],
            "launch_identity_sha256": payload["launch_identity_sha256"],
            "evidence": payload["evidence"],
            "acknowledged_at": "2026-08-30T00:00:00Z",
        }
        room = {
            "room_id": "room-1", "room_version": 14,
            "attempt": {
                "attempt_id": "attempt-1", "phase": "canceled",
                "d": {
                    "activation_generation": 3, "outcome": "canceled",
                    "primary_failure_code": None,
                    "sides": {"member_a": side, "member_b": {**side, "run_id": "other-run"}},
                    "barrier_status": "two_side_terminal", "cleanup_status": "verified",
                    "terminalized_at": "2026-08-30T00:00:01Z",
                },
            },
        }
        return run, room, d5_path

    @staticmethod
    def launch_absent(events):
        def probe(_identity):
            events.append("D8")
            return {
                "status": "absent", "endpoint_exited": True, "wrapper_exited": True,
                "children_absent": True, "token_absent": True, "session_absent": True,
            }
        return probe

    @staticmethod
    def radio_quiescent(events):
        def probe(_identity):
            events.append("D9")
            return {
                "status": "quiescent", "owned_interfaces": 0,
                "driver_threads": 0, "phy_active": False,
            }
        return probe

    def release(self, run, room, d5_path, *, events, launch_probe=None, radio_probe=None,
                lease=None, diagnostic_cleanup=None):
        clock = FakeClock()
        worker = LocalDRelease(
            coordinator=self.coordinator,
            run_id=run["run_id"],
            d5_state_path=d5_path,
            release_state_path=self.root / run["run_id"] / "d-local-release.json",
            launch_probe=launch_probe or self.launch_absent(events),
            radio_probe=radio_probe or self.radio_quiescent(events),
            usb_lease=lease,
            diagnostic_cleanup=diagnostic_cleanup,
            stable_samples=3,
            sample_interval=0.1,
            radio_timeout=0.3,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        return worker, worker.release(room)

    def test_orders_d7_through_d11_and_retains_only_redacted_final_report(self):
        run, room, d5_path = self.prepare()
        events = []

        def diagnostic_not_required_guard():
            self.fail("normal runs must not invoke diagnostic cleanup")

        worker, result = self.release(
            run, room, d5_path, events=events, lease=FakeLease(events),
            diagnostic_cleanup=diagnostic_not_required_guard)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(events, ["D8", "D9", "D9", "D9", "D10"])
        self.assertTrue(result["run"]["cleanup"]["verified"])
        self.assertFalse(d5_path.exists())
        self.assertTrue(worker.release_state_path.exists())
        persisted = json.loads(worker.release_state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["last_passed_gate"], "D11_RELEASE")
        self.assertNotIn("secret-member-token", worker.release_state_path.read_text(encoding="utf-8"))

    def test_active_endpoint_blocks_usb_return_and_preserves_cleanup_guard(self):
        run, room, d5_path = self.prepare()
        events = []

        def active(_identity):
            events.append("D8")
            return {
                "status": "present", "endpoint_exited": False, "wrapper_exited": False,
                "children_absent": False, "token_absent": False, "session_absent": False,
            }

        _worker, result = self.release(
            run, room, d5_path, events=events, launch_probe=active, lease=FakeLease(events))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("D10", events)
        self.assertEqual(result["run"]["functional"]["status"], "canceled")
        self.assertEqual(result["run"]["cleanup"]["code"], "D_LOCAL_CLEANUP_FAILED")
        with self.assertRaises(Exception):
            self.coordinator.start(RunMode.C_HARNESS)

    def test_unknown_radio_state_never_detaches_usb(self):
        run, room, d5_path = self.prepare()
        events = []

        def unknown(_identity):
            events.append("D9")
            return {
                "status": "unknown", "owned_interfaces": None,
                "driver_threads": None, "phy_active": None,
            }

        _worker, result = self.release(
            run, room, d5_path, events=events,
            radio_probe=unknown, lease=FakeLease(events))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("D10", events)
        self.assertEqual(result["report"]["failures"][0]["code"], "D_RADIO_NOT_QUIESCENT")

    def test_c_harness_has_no_radio_or_usb_ownership_to_release(self):
        run, room, d5_path = self.prepare(RunMode.C_HARNESS)
        events = []
        _worker, result = self.release(run, room, d5_path, events=events)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(events, ["D8"])
        self.assertFalse(result["report"]["evidence"]["usb"]["detached_by_run"])

    def test_diagnostic_resources_are_required_and_failure_does_not_skip_safe_local_checks(self):
        run, room, d5_path = self.prepare(RunMode.DIAGNOSTIC_A)
        events = []

        def diagnostic_cleanup():
            events.append("D7")
            return {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": False,
                "credential_file_absent": True,
            }

        _worker, result = self.release(
            run, room, d5_path, events=events, lease=FakeLease(events),
            diagnostic_cleanup=diagnostic_cleanup)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(events, ["D7", "D8", "D9", "D9", "D9", "D10"])
        self.assertEqual(result["report"]["failures"][0]["code"], "D_DIAGNOSTIC_CLEANUP_FAILED")

    def test_d6_must_contain_the_exact_persisted_local_d5(self):
        run, room, d5_path = self.prepare()
        room["attempt"]["d"]["sides"]["member_a"]["launch_identity_sha256"] = "0" * 64
        events = []
        worker = LocalDRelease(
            coordinator=self.coordinator, run_id=run["run_id"], d5_state_path=d5_path,
            release_state_path=self.root / "release.json",
            launch_probe=self.launch_absent(events), radio_probe=self.radio_quiescent(events),
            usb_lease=FakeLease(events),
        )
        with self.assertRaises(DControlError) as caught:
            worker.release(room)
        self.assertEqual(caught.exception.code, "D_BARRIER_UNVERIFIED")
        self.assertEqual(events, [])
        self.assertEqual(self.coordinator.snapshot(run["run_id"])["phase"], "closing")

    def test_missing_d5_state_is_rejected_during_an_ordinary_live_run(self):
        run, room, d5_path = self.prepare()
        d5_path.unlink()
        worker = LocalDRelease(
            coordinator=self.coordinator, run_id=run["run_id"], d5_state_path=d5_path,
            release_state_path=self.root / "release.json",
            launch_probe=self.launch_absent([]), radio_probe=self.radio_quiescent([]),
            usb_lease=FakeLease([]),
        )
        with self.assertRaises(DControlError) as caught:
            worker.release(room)
        self.assertEqual(caught.exception.code, "D_CONTROL_STATE_INVALID")

    def test_startup_recovery_can_release_after_forced_d6_without_a_local_d5_record(self):
        run, room, d5_path = self.prepare(RunMode.C_HARNESS)
        d5_path.unlink()
        room["attempt"]["d"].update(
            barrier_status="forced_timeout", cleanup_status="failed",
            secondary_failure_code="D_BARRIER_TIMEOUT")
        room["attempt"]["d"]["sides"]["member_a"] = None
        self.coordinator.close()
        self.coordinator = ConnectionCoordinator(
            self.root / "coordinator", "0.3.0-dev")
        recovered = self.coordinator.snapshot(run["run_id"])
        self.assertEqual(recovered["phase"], "cleaning")
        self.assertTrue(recovered["recovery_required"])
        events = []
        worker = LocalDRelease(
            coordinator=self.coordinator, run_id=run["run_id"], d5_state_path=d5_path,
            release_state_path=self.root / "recovered-release.json",
            launch_probe=self.launch_absent(events),
        )
        result = worker.release(room)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["run"]["cleanup"]["verified"])
        self.assertFalse(result["report"]["shared_cleanup_verified"])

    def test_failed_local_cleanup_can_be_retried_to_verified_release(self):
        run, room, d5_path = self.prepare()
        events = []
        state = {"active": True}

        def launch(_identity):
            events.append("D8")
            if state["active"]:
                return {
                    "status": "present", "endpoint_exited": False, "wrapper_exited": False,
                    "children_absent": False, "token_absent": False, "session_absent": False,
                }
            return {
                "status": "absent", "endpoint_exited": True, "wrapper_exited": True,
                "children_absent": True, "token_absent": True, "session_absent": True,
            }

        worker, first = self.release(
            run, room, d5_path, events=events, launch_probe=launch, lease=FakeLease(events))
        self.assertEqual(first["status"], "failed")
        state["active"] = False
        second = worker.release(room)
        self.assertEqual(second["status"], "passed")
        self.assertTrue(second["run"]["cleanup"]["verified"])
        self.assertEqual(second["run"]["cleanup"]["failures"][0]["code"], "D_LOCAL_CLEANUP_FAILED")

    def test_d10_failure_is_secondary_and_keeps_the_cleanup_guard(self):
        run, room, d5_path = self.prepare()
        events = []

        class FailingLease:
            def release(self):
                events.append("D10")
                raise RuntimeError("usbipd response unavailable")

        _worker, result = self.release(
            run, room, d5_path, events=events, lease=FailingLease())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["report"]["failures"][0]["code"], "D_USB_RETURN_FAILED")
        self.assertEqual(result["run"]["functional"]["status"], "canceled")
        self.assertTrue(result["run"]["recovery_required"])

    def test_lost_d11_response_repairs_report_without_repeating_release(self):
        run, room, d5_path = self.prepare()
        events = []

        class LostResponseCoordinator:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def complete_cleanup(self, *args, **kwargs):
                self.inner.complete_cleanup(*args, **kwargs)
                raise RuntimeError("D11 response lost")

        worker = LocalDRelease(
            coordinator=LostResponseCoordinator(self.coordinator), run_id=run["run_id"],
            d5_state_path=d5_path,
            release_state_path=self.root / run["run_id"] / "d-local-release.json",
            launch_probe=self.launch_absent(events), radio_probe=self.radio_quiescent(events),
            usb_lease=FakeLease(events), stable_samples=3,
            sample_interval=0.1, radio_timeout=0.3,
            monotonic=FakeClock().monotonic, sleep=lambda _seconds: None,
        )
        with self.assertRaisesRegex(RuntimeError, "response lost"):
            worker.release(room)
        self.assertTrue(self.coordinator.snapshot(run["run_id"])["cleanup"]["verified"])
        self.assertEqual(
            json.loads(worker.release_state_path.read_text(encoding="utf-8"))["status"],
            "running",
        )

        worker.coordinator = self.coordinator
        recovered = worker.release(room)
        self.assertEqual(recovered["status"], "passed")
        self.assertEqual(recovered["report"]["last_passed_gate"], "D11_RELEASE")
        self.assertFalse(d5_path.exists())
        self.assertEqual(events, ["D8", "D9", "D9", "D9", "D10"])

    def test_final_report_projection_matches_strict_contract(self):
        run, room, d5_path = self.prepare()
        events = []
        _worker, result = self.release(
            run, room, d5_path, events=events, lease=FakeLease(events))
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "d-local-release.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(result["report"]), set(schema["required"]))
        self.assertEqual(
            result["report"]["contract_version"],
            schema["properties"]["contract_version"]["const"],
        )


if __name__ == "__main__":
    unittest.main()
