import json
from pathlib import Path
import tempfile
import unittest
import uuid

from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.connection import (
    AuthoritySeat,
    ConnectionCoordinator,
    DControlError,
    FunctionalOutcome,
    MeasuredD5Control,
    Phase,
    RunMode,
    SwitchRole,
)


ADAPTER = r"USB\VID_0BDA&PID_818B\RADIO-A"
NONCE = "a" * 32


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeRelay:
    def __init__(self):
        self.calls = []

    def acknowledge_distributed_d(self, room_id, attempt_id, token, payload, **options):
        self.calls.append((room_id, attempt_id, token, payload, options))
        return {"room_id": room_id, "room_version": 13, "attempt": {"phase": "closing"}}


class MeasuredD5ControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.coordinator = ConnectionCoordinator(self.root / "coordinator", "0.3.0-dev")

    def tearDown(self):
        self.coordinator.close()
        self.temporary.cleanup()

    def prepare_run(self, mode=RunMode.NORMAL):
        run = self.coordinator.start(
            mode, adapter_instance_id="software" if mode == RunMode.C_HARNESS else ADAPTER,
            usb_id="software" if mode == RunMode.C_HARNESS else "0bda:818b",
        )
        self.coordinator.transition(run["run_id"], Phase.PREFLIGHT, "P0a_release")
        self.coordinator.transition(run["run_id"], Phase.RUNNING, "C0.1_authority")
        self.coordinator.bind_authority(
            run["run_id"], room_id="room-1", room_version=7,
            seat=AuthoritySeat.MEMBER_A, switch_role=SwitchRole.A_ROOM_JOINER,
        )
        if mode == RunMode.C_HARNESS:
            # The software harness still binds a synthetic P0 identity before its admitted launch.
            self.coordinator.acquire_wrapper(
                run["run_id"], wrapper_pid=4001, process_start_ticks=101,
                adapter_instance_id="software", usb_id="software", bus_id="software",
            )
        else:
            self.coordinator.acquire_wrapper(
                run["run_id"], wrapper_pid=4001, process_start_ticks=101,
                adapter_instance_id=ADAPTER, usb_id="0bda:818b", bus_id="4-18",
            )
        self.coordinator.mark_p0_ready(
            run["run_id"], wrapper_pid=4001, process_start_ticks=101,
            phy="phy0", netdev="wlan0",
        )
        self.coordinator.lock_attempt(
            run["run_id"], attempt_id="attempt-1", role_lock_version=9)
        self.coordinator.reserve_endpoint_launch(run["run_id"], launch_nonce=NONCE)
        self.coordinator.acknowledge_endpoint(
            run["run_id"], launch_nonce=NONCE,
            endpoint_pid=5001, process_start_ticks=202,
        )
        return self.coordinator.close_run(run["run_id"], FunctionalOutcome.CANCELED)

    @staticmethod
    def authority_room(run):
        return {
            "room_id": "room-1",
            "room_version": 12,
            "attempt": {
                "attempt_id": "attempt-1",
                "phase": "closing",
                "d": {
                    "activation_generation": 3,
                    "outcome": "canceled",
                    "primary_failure_code": None,
                },
            },
        }

    def write_endpoint_report(self, run, **updates):
        identity = run["identity"]
        report = {
            "contract_version": "d-endpoint-stage.v1",
            "run_id": run["run_id"],
            "attempt_id": identity["attempt_id"],
            "activation_generation": 3,
            "source_seat": identity["authority_seat"],
            "stage_generation": identity["stage_generation"],
            "launch_identity_sha256": launch_identity_hash(
                run["run_id"], identity["stage_generation"],
                identity["launch_nonce"], identity["endpoint_pid"],
            ),
            "outcome": "canceled",
            "primary_failure_code": None,
            "last_passed_gate": "D4_LDN_TEARDOWN",
            "status": "passed",
            "forced": False,
            "evidence": {
                "close_tail_required": True,
                "close_tail_observed": True,
                "bridge_admission_stopped": True,
                "bridge_transport_exited": True,
                "observer_stopped": True,
                "simulation_closed": True,
                "ldn_released": True,
                "radio_thread_exited": True,
            },
            "drain": {
                "pending_local_frames": 0,
                "flushed_local_frames": 0,
                "discarded_local_frames": 0,
                "discarded_remote_frames": 0,
            },
            "failures": [],
            "elapsed_ms": 15,
        }
        report.update(updates)
        path = self.root / run["run_id"] / "d-endpoint-stage.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def control(self, run, relay, report_path, *, process_probe, radio_probe=None, clock=None):
        clock = clock or FakeClock()
        return MeasuredD5Control(
            coordinator=self.coordinator,
            relay=relay,
            run_id=run["run_id"],
            member_token="secret-member-token",
            endpoint_report_path=report_path,
            state_path=self.root / run["run_id"] / "d5-control-state.json",
            process_probe=process_probe,
            radio_probe=radio_probe,
            exit_timeout=0.3,
            stable_samples=3,
            sample_interval=0.1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    def test_constructs_d5_from_persisted_report_and_independent_stable_measurements(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        process_calls = []
        radio_calls = []

        def process_probe(pid):
            process_calls.append(pid)
            return None

        def radio_probe(identity):
            radio_calls.append(identity)
            return {"status": "quiescent", "owned_interfaces": 0}

        control = self.control(
            run, relay, report_path, process_probe=process_probe, radio_probe=radio_probe)
        result = control.acknowledge(self.authority_room(run))
        payload = relay.calls[0][3]
        self.assertEqual(payload["evidence"], {
            "endpoint_exited": True,
            "transport_exited": True,
            "threads_exited": True,
            "ldn_released": True,
            "interfaces_absent": True,
            "forced": False,
        })
        self.assertEqual(process_calls, [5001])
        self.assertEqual(len(radio_calls), 3)
        self.assertEqual(uuid.UUID(result["control"]["command_id"]).version, 7)
        self.assertNotIn("secret-member-token", result["control"].__repr__())
        self.assertNotIn("secret-member-token", control.state_path.read_text(encoding="utf-8"))

        replay = control.acknowledge(self.authority_room(run))
        self.assertEqual(len(relay.calls), 2)
        self.assertEqual(relay.calls[0][4], relay.calls[1][4])
        self.assertEqual(replay["control"], result["control"])
        self.assertEqual(process_calls, [5001])
        self.assertEqual(len(radio_calls), 3)

    def test_live_endpoint_and_unknown_radio_are_acknowledged_as_forced_failure(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path,
            process_probe=lambda _pid: 202,
            radio_probe=lambda _identity: {"status": "unknown", "owned_interfaces": None},
        )
        control.acknowledge(self.authority_room(run))
        evidence = relay.calls[0][3]["evidence"]
        self.assertFalse(evidence["endpoint_exited"])
        self.assertFalse(evidence["interfaces_absent"])
        self.assertTrue(evidence["forced"])

    def test_stale_endpoint_report_cannot_acknowledge_the_current_launch(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run, launch_identity_sha256="0" * 64)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path,
            process_probe=lambda _pid: None,
            radio_probe=lambda _identity: {"status": "quiescent", "owned_interfaces": 0},
        )
        with self.assertRaises(DControlError) as caught:
            control.acknowledge(self.authority_room(run))
        self.assertEqual(caught.exception.code, "D_ENDPOINT_IDENTITY_MISMATCH")
        self.assertEqual(relay.calls, [])

    def test_c_harness_has_no_radio_claim_and_does_not_require_a_probe(self):
        run = self.prepare_run(RunMode.C_HARNESS)
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path, process_probe=lambda _pid: None)
        control.acknowledge(self.authority_room(run))
        evidence = relay.calls[0][3]["evidence"]
        self.assertTrue(evidence["interfaces_absent"])
        self.assertFalse(evidence["forced"])

    def test_corrupt_persisted_control_state_fails_closed_without_remeasurement(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path,
            process_probe=lambda _pid: None,
            radio_probe=lambda _identity: {"status": "quiescent", "owned_interfaces": 0},
        )
        control.acknowledge(self.authority_room(run))
        state = json.loads(control.state_path.read_text(encoding="utf-8"))
        state["run_id"] = "00000000-0000-0000-0000-000000000001"
        control.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DControlError) as caught:
            control.acknowledge(self.authority_room(run))
        self.assertEqual(caught.exception.code, "D_CONTROL_STATE_INVALID")
        self.assertEqual(len(relay.calls), 1)

    def test_changed_endpoint_report_cannot_change_an_idempotent_acknowledgement(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path,
            process_probe=lambda _pid: None,
            radio_probe=lambda _identity: {"status": "quiescent", "owned_interfaces": 0},
        )
        control.acknowledge(self.authority_room(run))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["elapsed_ms"] += 1
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(DControlError) as caught:
            control.acknowledge(self.authority_room(run))
        self.assertEqual(caught.exception.code, "D_CONTROL_STATE_INVALID")
        self.assertEqual(len(relay.calls), 1)

    def test_private_state_projection_matches_its_strict_schema(self):
        run = self.prepare_run()
        report_path = self.write_endpoint_report(run)
        relay = FakeRelay()
        control = self.control(
            run, relay, report_path,
            process_probe=lambda _pid: None,
            radio_probe=lambda _identity: {"status": "quiescent", "owned_interfaces": 0},
        )
        result = control.acknowledge(self.authority_room(run))
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "d5-control-state.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(result["control"]), set(schema["required"]))
        self.assertEqual(
            result["control"]["contract_version"],
            schema["properties"]["contract_version"]["const"],
        )


if __name__ == "__main__":
    unittest.main()
