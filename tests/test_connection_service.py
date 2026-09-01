import tempfile
import threading
import time
import unittest
import uuid

from switchtrade.connection.service import (
    ConnectionRunService, ConnectionRunServiceError,
)


class ConnectionRunServiceTests(unittest.TestCase):
    def request(self):
        return {"kind": "create", "switch_role": "a_room_joiner"}

    def test_one_start_idempotent_commands_pure_get_and_verified_terminal(self):
        release = threading.Event()
        running = threading.Event()
        starts = []

        def runner(run_id, _request, control):
            starts.append(run_id)
            control.phase("running", gate="C2_BRIDGE", last_passed_gate="C1_READY")
            running.set()
            release.wait(2)
            return {"functional_status": "passed", "cleanup_status": "verified"}

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(temporary, runner) as service:
                command_id = str(uuid.uuid4())
                first = service.start(command_id=command_id, expected_revision=0,
                                      request=self.request())
                again = service.start(command_id=command_id, expected_revision=0,
                                      request=self.request())
                self.assertEqual(first, again)
                self.assertTrue(running.wait(1), "runner did not reach its stable checkpoint")
                before = service.snapshot(first["run_id"])
                for _ in range(20):
                    service.snapshot(first["run_id"])
                after = service.snapshot(first["run_id"])
                self.assertEqual(before, after)
                deadline = time.monotonic() + 1
                while not starts and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(len(starts), 1)
                release.set()
                deadline = time.monotonic() + 2
                while service.snapshot()["phase"] != "terminal" and time.monotonic() < deadline:
                    time.sleep(0.01)
                final = service.snapshot()
                self.assertEqual(final["functional"]["status"], "passed")
                self.assertTrue(final["cleanup"]["verified"])
                self.assertIn("retry", final["allowed_actions"])

    def test_rejects_stale_revision_and_command_payload_reuse(self):
        waiting = threading.Event()

        def runner(_run_id, _request, _control):
            waiting.wait(2)
            return {"functional_status": "canceled", "cleanup_status": "verified"}

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(temporary, runner) as service:
                command_id = str(uuid.uuid4())
                started = service.start(command_id=command_id, expected_revision=0,
                                        request=self.request())
                with self.assertRaises(ConnectionRunServiceError) as conflict:
                    service.start(command_id=command_id, expected_revision=0, request={
                        "kind": "join", "switch_role": "b_ap_host"})
                self.assertEqual(conflict.exception.code, "COMMAND_ID_CONFLICT")
                with self.assertRaises(ConnectionRunServiceError) as stale:
                    service.command(
                        command_id=str(uuid.uuid4()), run_id=started["run_id"],
                        expected_revision=999, action="stop")
                self.assertEqual(stale.exception.code, "REVISION_STALE")
                deadline = time.monotonic() + 1
                while (service.snapshot()["phase"] == "created" and
                       time.monotonic() < deadline):
                    time.sleep(0.01)
                current = service.snapshot()
                service.command(
                    command_id=str(uuid.uuid4()), run_id=current["run_id"],
                    expected_revision=current["revision"], action="stop")
                waiting.set()

    def test_restart_blocks_when_cleanup_cannot_be_proved(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = ConnectionRunService(
                temporary, lambda *_args: time.sleep(1), command_timeout=2)
            started = service.start(
                command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
            # Simulate process loss without giving the worker a chance to publish terminal cleanup.
            service._closed = True
            service._queue.put(None)
            service._thread.join(2)
            recovered = ConnectionRunService(
                temporary, lambda *_args: {},
                recovery=lambda _record: {"cleanup_verified": False}, command_timeout=0.1)
            try:
                snapshot = recovered.snapshot(started["run_id"])
                self.assertEqual(snapshot["phase"], "cleaning")
                self.assertFalse(snapshot["cleanup"]["verified"])
                with self.assertRaises(ConnectionRunServiceError) as blocked:
                    recovered.start(
                        command_id=str(uuid.uuid4()), expected_revision=snapshot["revision"],
                        request=self.request())
                self.assertEqual(blocked.exception.code, "CONNECTION_RUN_ACTIVE")
            finally:
                with self.assertRaises(ConnectionRunServiceError) as closing:
                    recovered.close()
                self.assertEqual(closing.exception.code, "SERVICE_CLEANUP_TIMEOUT")

    def test_restart_recovery_exception_is_contained_and_blocks_new_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = ConnectionRunService(
                temporary, lambda *_args: time.sleep(1), command_timeout=2)
            service.start(
                command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
            service._closed = True
            service._queue.put(None)
            service._thread.join(2)

            def fail_recovery(_record):
                raise RuntimeError("probe failed")

            recovered = ConnectionRunService(
                temporary, lambda *_args: {}, recovery=fail_recovery, command_timeout=0.1)
            try:
                snapshot = recovered.snapshot()
                self.assertEqual(snapshot["phase"], "cleaning")
                self.assertFalse(snapshot["cleanup"]["verified"])
            finally:
                with self.assertRaises(ConnectionRunServiceError):
                    recovered.close()

    def test_identity_bound_endpoint_heartbeat_timeout_preserves_first_failure(self):
        def runner(_run_id, _request, control):
            control.mark_endpoint_started({
                "pid": 42, "start_ticks": 7, "launch_nonce": "n" * 32,
                "attempt_id": "attempt-1",
            })
            deadline = time.monotonic() + 2
            while control.termination is None and time.monotonic() < deadline:
                time.sleep(0.01)
            return {"functional_status": "canceled", "cleanup_status": "verified"}

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(
                    temporary, runner, heartbeat_timeout=0.05, command_timeout=2) as service:
                service.start(
                    command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
                deadline = time.monotonic() + 2
                while service.snapshot()["phase"] != "terminal" and time.monotonic() < deadline:
                    time.sleep(0.01)
                final = service.snapshot()
                self.assertEqual(final["functional"]["status"], "failed")
                self.assertEqual(
                    final["functional"]["failure"]["code"], "ENDPOINT_HEARTBEAT_TIMEOUT")
                self.assertTrue(final["cleanup"]["verified"])

    def test_endpoint_heartbeat_does_not_churn_the_public_revision(self):
        stable = threading.Event()
        release = threading.Event()
        controls = []

        def runner(_run_id, _request, control):
            controls.append(control)
            control.phase("running", gate="C2_BRIDGE", last_passed_gate="C1_READY")
            stable.set()
            release.wait(2)
            return {"functional_status": "canceled", "cleanup_status": "verified"}

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(temporary, runner) as service:
                started = service.start(
                    command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
                self.assertTrue(stable.wait(1))
                deadline = time.monotonic() + 1
                while (service.snapshot(started["run_id"])["phase"] != "running" and
                       time.monotonic() < deadline):
                    time.sleep(0.01)
                before = service.snapshot(started["run_id"])
                self.assertEqual(before["phase"], "running")
                for _ in range(10):
                    controls[0].heartbeat("C2_BRIDGE")
                after = service.snapshot(started["run_id"])
                self.assertEqual(before, after)
                release.set()

    def test_retry_resumes_retained_authority_and_terminal_owner_can_close(self):
        releases = []
        requests = []
        first_done = threading.Event()
        second_done = threading.Event()

        class Runner:
            def __call__(self, _run_id, request, control):
                requests.append(request)
                control.authority({
                    "room_id": "room-1", "room_code": "ABC123",
                    "membership_role": "owner",
                })
                (first_done if len(requests) == 1 else second_done).wait(2)
                return {"functional_status": "canceled", "cleanup_status": "verified"}

            def release_authority(self, action):
                releases.append(action)

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(temporary, Runner()) as service:
                service.start(
                    command_id=str(uuid.uuid4()), expected_revision=0,
                    request=self.request())
                first_done.set()
                deadline = time.monotonic() + 2
                while service.snapshot()["phase"] != "terminal" and time.monotonic() < deadline:
                    time.sleep(0.01)
                terminal = service.snapshot()
                retried = service.retry(
                    command_id=str(uuid.uuid4()), run_id=terminal["run_id"],
                    expected_revision=terminal["revision"])
                self.assertNotEqual(retried["run_id"], terminal["run_id"])
                deadline = time.monotonic() + 1
                while len(requests) < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(requests[1]["kind"], "resume")
                second_done.set()
                deadline = time.monotonic() + 2
                while service.snapshot()["phase"] != "terminal" and time.monotonic() < deadline:
                    time.sleep(0.01)
                current = service.snapshot()
                closed = service.command(
                    command_id=str(uuid.uuid4()), run_id=current["run_id"],
                    expected_revision=current["revision"], action="close")
                self.assertEqual(releases, ["close"])
                self.assertIsNone(closed["room"])
                self.assertNotIn("close", closed["allowed_actions"])

    def test_shutdown_is_identity_bound_and_uses_the_active_cleanup_owner(self):
        stopped = threading.Event()
        running = threading.Event()

        def runner(_run_id, _request, control):
            running.set()
            while control.termination is None:
                time.sleep(0.01)
            stopped.set()
            return {"functional_status": "canceled", "cleanup_status": "verified"}

        with tempfile.TemporaryDirectory() as temporary:
            service = ConnectionRunService(temporary, runner, command_timeout=2)
            started = service.start(
                command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
            with self.assertRaises(ConnectionRunServiceError) as stale:
                service.shutdown(
                    command_id=str(uuid.uuid4()), run_id=started["run_id"],
                    expected_revision=999)
            self.assertEqual(stale.exception.code, "REVISION_STALE")
            self.assertTrue(running.wait(1))
            deadline = time.monotonic() + 1
            while (service.snapshot()["phase"] == "created" and
                   time.monotonic() < deadline):
                time.sleep(0.01)
            current = service.snapshot()
            accepted = service.shutdown(
                command_id=str(uuid.uuid4()), run_id=current["run_id"],
                expected_revision=current["revision"])
            self.assertEqual(accepted["run_id"], current["run_id"])
            self.assertTrue(stopped.wait(1))
            service.close()

    def test_active_close_clears_room_only_after_verified_distributed_finalization(self):
        def runner(_run_id, _request, control):
            control.authority({
                "room_id": "room-1", "room_code": "ABC123",
                "membership_role": "owner",
            })
            control.phase("running", gate="C_RFU_ACTIVE", last_passed_gate="C_RFU_ACTIVE")
            while control.termination is None:
                time.sleep(0.01)
            return {
                "functional_status": "canceled", "cleanup_status": "verified",
                "cleanup": {"distributed": {"room_finalization": "room_closed"}},
            }

        with tempfile.TemporaryDirectory() as temporary:
            with ConnectionRunService(temporary, runner) as service:
                started = service.start(
                    command_id=str(uuid.uuid4()), expected_revision=0, request=self.request())
                deadline = time.monotonic() + 1
                while service.snapshot()["room"] is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                current = service.snapshot()
                service.command(
                    command_id=str(uuid.uuid4()), run_id=current["run_id"],
                    expected_revision=current["revision"], action="close")
                deadline = time.monotonic() + 2
                while service.snapshot()["phase"] != "terminal" and time.monotonic() < deadline:
                    time.sleep(0.01)
                final = service.snapshot()
                self.assertTrue(final["cleanup"]["verified"])
                self.assertIsNone(final["room"])


if __name__ == "__main__":
    unittest.main()
