from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from switchtrade.connection import (
    AuthoritySeat,
    ConnectionCoordinator,
    ConnectionCoordinatorError,
    FunctionalOutcome,
    Phase,
    RunMode,
    SwitchRole,
)


ADAPTER = r"USB\VID_0BDA&PID_818B\RADIO-A"
USB_ID = "0bda:818b"
NONCE = "a" * 32


class ConnectionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def start_direct(self, coordinator: ConnectionCoordinator) -> dict:
        run = coordinator.start(
            RunMode.DIRECT_A, adapter_instance_id=ADAPTER, usb_id=USB_ID)
        run = coordinator.transition(run["run_id"], Phase.PREFLIGHT, "P0a_release")
        return coordinator.transition(run["run_id"], Phase.RUNNING, "P0b_radio")

    def prepare_direct(self, coordinator: ConnectionCoordinator) -> dict:
        run = self.start_direct(coordinator)
        run = coordinator.acquire_wrapper(
            run["run_id"], wrapper_pid=4001, process_start_ticks=101,
            adapter_instance_id=ADAPTER, usb_id=USB_ID, bus_id="4-18")
        return coordinator.mark_p0_ready(
            run["run_id"], wrapper_pid=4001, process_start_ticks=101,
            phy="phy0", netdev="wlan0")

    def verify_cleanup(self, coordinator: ConnectionCoordinator, run_id: str,
                       outcome: FunctionalOutcome = FunctionalOutcome.PASSED) -> dict:
        coordinator.close_run(run_id, outcome)
        coordinator.begin_cleanup(run_id)
        return coordinator.complete_cleanup(
            run_id, verified=True,
            evidence={"endpoint_exited": True, "radio_quiescent": True})

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(ConnectionCoordinatorError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_snapshots_are_read_only_and_one_launch_identity_is_idempotent(self):
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = self.prepare_direct(coordinator)
            record_path = self.root / run["run_id"] / "connection-run.json"
            before_revision = run["revision"]
            before_bytes = record_path.read_bytes()
            for _ in range(20):
                snapshot = coordinator.snapshot(run["run_id"])
                snapshot["identity"]["wrapper_pid"] = 9999
            self.assertEqual(coordinator.snapshot(run["run_id"])["revision"], before_revision)
            self.assertEqual(record_path.read_bytes(), before_bytes)

            reserved = coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=NONCE)
            duplicate = coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=NONCE)
            self.assertEqual(duplicate["revision"], reserved["revision"])
            self.assertEqual(duplicate["ownership"]["launch_count"], 1)
            self.assert_code(
                "CONNECTION_IDENTITY_MISMATCH",
                lambda: coordinator.reserve_endpoint_launch(
                    run["run_id"], launch_nonce="b" * 32),
            )

            started = coordinator.acknowledge_endpoint(
                run["run_id"], launch_nonce=NONCE,
                endpoint_pid=5001, process_start_ticks=202)
            duplicate = coordinator.acknowledge_endpoint(
                run["run_id"], launch_nonce=NONCE,
                endpoint_pid=5001, process_start_ticks=202)
            self.assertEqual(duplicate["revision"], started["revision"])
            self.assertEqual(duplicate["ownership"], {
                "wrapper_acquired": True,
                "p0_side_ready": True,
                "launch_reserved": True,
                "endpoint_started": True,
                "wrapper_count": 1,
                "launch_count": 1,
            })
            terminal = self.verify_cleanup(coordinator, run["run_id"])
            self.assertTrue(terminal["cleanup"]["verified"])

    def test_authority_and_role_axes_bind_once_before_attempt_launch(self):
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = coordinator.start(
                RunMode.NORMAL, adapter_instance_id=ADAPTER, usb_id=USB_ID)
            coordinator.transition(run["run_id"], Phase.PREFLIGHT, "P0a_release")
            coordinator.transition(run["run_id"], Phase.RUNNING, "C0.1_authority")
            bound = coordinator.bind_authority(
                run["run_id"], room_id="room-1", room_version=7,
                seat=AuthoritySeat.MEMBER_B, switch_role=SwitchRole.B_AP_HOST)
            self.assertEqual(bound["identity"]["authority_seat"], "member_b")
            self.assertEqual(bound["identity"]["switch_role"], "b_ap_host")
            self.assertEqual(bound["identity"]["ldn_role"], "ap")
            self.assertEqual(bound["identity"]["tunnel_direction"], "b_to_a")
            self.assert_code(
                "CONNECTION_IDENTITY_MISMATCH",
                lambda: coordinator.bind_authority(
                    run["run_id"], room_id="room-1", room_version=8,
                    seat=AuthoritySeat.MEMBER_B, switch_role=SwitchRole.B_AP_HOST),
            )
            coordinator.acquire_wrapper(
                run["run_id"], wrapper_pid=4002, process_start_ticks=102,
                adapter_instance_id=ADAPTER, usb_id=USB_ID, bus_id="4-18")
            coordinator.mark_p0_ready(
                run["run_id"], wrapper_pid=4002, process_start_ticks=102,
                phy="phy0", netdev="wlan0")
            locked = coordinator.lock_attempt(
                run["run_id"], attempt_id="attempt-1", role_lock_version=9)
            self.assertEqual(locked["identity"]["attempt_id"], "attempt-1")
            coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=NONCE)
            self.verify_cleanup(coordinator, run["run_id"], FunctionalOutcome.CANCELED)

    def test_unverified_cleanup_blocks_new_run_until_explicit_recovery(self):
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = coordinator.start(
                RunMode.P0_HARNESS, adapter_instance_id=ADAPTER, usb_id=USB_ID)
            self.assert_code(
                "CONNECTION_RUN_ACTIVE",
                lambda: coordinator.start(
                    RunMode.C_HARNESS, run_id="00000000-0000-0000-0000-000000000010"),
            )
            coordinator.close_run(
                run["run_id"], FunctionalOutcome.FAILED,
                code="P0_DRIVER_FAILED", message="Driver probe failed.")
            coordinator.begin_cleanup(run["run_id"])
            failed = coordinator.complete_cleanup(
                run["run_id"], verified=False,
                code="CLEANUP_FAILED", message="Radio state is unknown.",
                evidence={"radio_absent": None})
            self.assertEqual(failed["functional"]["code"], "P0_DRIVER_FAILED")
            self.assertEqual(failed["cleanup"]["code"], "CLEANUP_FAILED")
            self.assertTrue(failed["recovery_required"])
            self.assert_code(
                "CONNECTION_RUN_ACTIVE",
                lambda: coordinator.start(RunMode.C_HARNESS),
            )
            coordinator.retry_cleanup(run["run_id"])
            terminal = coordinator.complete_cleanup(
                run["run_id"], verified=True,
                evidence={"radio_absent": True})
            self.assertFalse(terminal["recovery_required"])
            self.assertEqual(terminal["cleanup"]["failures"][0]["code"], "CLEANUP_FAILED")
            next_run = coordinator.start(RunMode.C_HARNESS)
            self.verify_cleanup(coordinator, next_run["run_id"], FunctionalOutcome.CANCELED)

    def test_restart_marks_pending_run_interrupted_and_preserves_existing_primary_failure(self):
        first = ConnectionCoordinator(self.root, "0.3.0-dev")
        pending = self.start_direct(first)
        first.close()

        second = ConnectionCoordinator(self.root, "0.3.0-dev")
        recovered = second.snapshot(pending["run_id"])
        self.assertEqual(recovered["phase"], "cleaning")
        self.assertEqual(recovered["functional"]["status"], "interrupted")
        self.assertEqual(recovered["functional"]["code"], "CONNECTION_RUN_INTERRUPTED")
        self.assertTrue(recovered["recovery_required"])
        self.assert_code(
            "CONNECTION_RUN_ACTIVE", lambda: second.start(RunMode.C_HARNESS))
        second.complete_cleanup(
            pending["run_id"], verified=True,
            evidence={"endpoint_exited": True, "radio_quiescent": True})
        failed = second.start(
            RunMode.P0_HARNESS, adapter_instance_id=ADAPTER, usb_id=USB_ID)
        second.close_run(
            failed["run_id"], FunctionalOutcome.FAILED,
            code="P0_RX_FAILED", message="No physical RX evidence.")
        second.close()

        third = ConnectionCoordinator(self.root, "0.3.0-dev")
        recovered_failure = third.snapshot(failed["run_id"])
        self.assertEqual(recovered_failure["phase"], "cleaning")
        self.assertEqual(recovered_failure["functional"]["code"], "P0_RX_FAILED")
        third.complete_cleanup(
            failed["run_id"], verified=True,
            evidence={"radio_quiescent": True})
        third.close()

    def test_concurrent_commands_cannot_create_duplicate_launches(self):
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = self.prepare_direct(coordinator)
            coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=NONCE)

            def reserve(index: int):
                nonce = NONCE if index % 2 == 0 else "b" * 32
                try:
                    return coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=nonce)
                except ConnectionCoordinatorError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(reserve, range(40)))
            self.assertEqual(sum(isinstance(result, dict) for result in results), 20)
            self.assertEqual(results.count("CONNECTION_IDENTITY_MISMATCH"), 20)
            snapshot = coordinator.snapshot(run["run_id"])
            self.assertEqual(snapshot["ownership"]["launch_count"], 1)
            self.assertEqual(snapshot["identity"]["launch_nonce"], NONCE)
            self.verify_cleanup(coordinator, run["run_id"], FunctionalOutcome.CANCELED)

    def test_cancel_and_cleanup_are_idempotent_and_keep_separate_outcomes(self):
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = coordinator.start(
                RunMode.P0_HARNESS, adapter_instance_id=ADAPTER, usb_id=USB_ID)
            canceled = coordinator.request_cancel(run["run_id"])
            duplicate = coordinator.request_cancel(run["run_id"])
            self.assertEqual(duplicate["revision"], canceled["revision"])
            coordinator.begin_cleanup(run["run_id"])
            failed = coordinator.complete_cleanup(
                run["run_id"], verified=False,
                code="CLEANUP_FAILED", message="Linux state is unknown.",
                evidence={"linux_absent": None})
            duplicate_failure = coordinator.complete_cleanup(
                run["run_id"], verified=False,
                code="CLEANUP_FAILED", message="Linux state is unknown.",
                evidence={"linux_absent": None})
            self.assertEqual(duplicate_failure["revision"], failed["revision"])
            self.assertEqual(failed["functional"]["status"], "canceled")
            self.assertEqual(failed["cleanup"]["status"], "failed")

    def test_contract_schema_matches_projection_and_rejects_unbounded_evidence(self):
        schema = json.loads((
            Path(__file__).resolve().parents[1] /
            "contracts" / "abcd" / "connection-run.v1.schema.json").read_text(encoding="utf-8"))
        with ConnectionCoordinator(self.root, "0.3.0-dev") as coordinator:
            run = coordinator.start(RunMode.C_HARNESS)
            self.assertEqual(set(run), set(schema["required"]))
            self.assertEqual(run["contract_version"], schema["properties"]["contract_version"]["const"])
            self.assertIn(run["phase"], schema["properties"]["phase"]["enum"])
            coordinator.close_run(run["run_id"], FunctionalOutcome.CANCELED)
            coordinator.begin_cleanup(run["run_id"])
            self.assert_code(
                "CONNECTION_INPUT_INVALID",
                lambda: coordinator.complete_cleanup(
                    run["run_id"], verified=False, code="CLEANUP_FAILED",
                    evidence={"credential": "must-not-enter-state"}),
            )
            coordinator.complete_cleanup(
                run["run_id"], verified=True, evidence={"software_clean": True})

    def test_closed_coordinator_rejects_mutations(self):
        coordinator = ConnectionCoordinator(self.root, "0.3.0-dev")
        run = coordinator.start(RunMode.C_HARNESS)
        self.assert_code(
            "CONNECTION_COORDINATOR_ACTIVE",
            lambda: ConnectionCoordinator(self.root, "0.3.0-dev"),
        )
        coordinator.close()
        self.assert_code(
            "CONNECTION_COORDINATOR_STOPPED",
            lambda: coordinator.request_cancel(run["run_id"]),
        )


if __name__ == "__main__":
    unittest.main()
