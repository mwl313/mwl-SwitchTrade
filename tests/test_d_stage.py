import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.connection.d_stage import EndpointDStage, GATES


RUN_ID = "018f3e10-1111-7000-8000-000000000001"
LAUNCH_NONCE = "n" * 64
LAUNCH_HASH = launch_identity_hash(RUN_ID, 2, LAUNCH_NONCE, 6101)


def intent(outcome="canceled"):
    return {
        "contract_version": "d-closing-intent.v1",
        "attempt_id": "attempt-d",
        "activation_generation": 3,
        "outcome": outcome,
        "primary_failure_code": "C_RFU_LOST" if outcome == "failed" else None,
        "last_passed_gate": "C_TRADE_COMPLETE" if outcome == "completed" else "C_RFU_ACTIVE",
    }


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Simulation:
    def __init__(self, disconnect_after=None, log=None, tick_error=None, close_error=None):
        self.disconnect_after = disconnect_after
        self.log = log
        self.tick_error = tick_error
        self.close_error = close_error
        self.host_disconnected = False
        self.ticks = 0
        self.closes = 0

    def tick(self):
        if self.log is not None:
            self.log.append("simulation.tick")
        self.ticks += 1
        if self.tick_error:
            raise RuntimeError(self.tick_error)
        if self.disconnect_after is not None and self.ticks >= self.disconnect_after:
            self.host_disconnected = True

    def close(self):
        if self.log is not None:
            self.log.append("simulation.close")
        self.closes += 1
        if self.close_error:
            raise RuntimeError(self.close_error)


class Bridge:
    def __init__(self, result=None, drain_error=None, stop_error=None, log=None):
        self.result = result or {
            "admission_stopped": True,
            "pending_local_frames": 0,
            "flushed_local_frames": 0,
            "discarded_local_frames": 0,
            "discarded_remote_frames": 0,
            "error_code": None,
        }
        self.stop_error = stop_error
        self.drain_error = drain_error
        self.log = log
        self.run_id = RUN_ID
        self.attempt_id = "attempt-d"
        self.source_seat = SimpleNamespace(label="member_a")
        self.activation_generation = 3
        self.client = SimpleNamespace(
            run_id=RUN_ID, stage_generation=2,
            launch_nonce=LAUNCH_NONCE, endpoint_pid=6101,
        )
        self.drains = 0
        self.stops = 0

    def finish_drain(self, _outcome):
        if self.log is not None:
            self.log.append("bridge.drain")
        self.drains += 1
        if self.drain_error:
            raise RuntimeError(self.drain_error)
        return dict(self.result)

    def stop_transport(self):
        if self.log is not None:
            self.log.append("bridge.stop")
        self.stops += 1
        if self.stop_error:
            raise RuntimeError(self.stop_error)


class Observer:
    def __init__(self, log=None, error=None):
        self.calls = []
        self.log = log
        self.error = error

    def stop(self, *, clear):
        if self.log is not None:
            self.log.append("observer.stop")
        self.calls.append(clear)
        if self.error:
            raise RuntimeError(self.error)


class Transport:
    def __init__(self, error=None, log=None):
        self.error = error
        self.log = log
        self.stops = 0

    def stop(self):
        if self.log is not None:
            self.log.append("transport.stop")
        self.stops += 1
        if self.error:
            raise RuntimeError(self.error)


class EndpointDStageTests(unittest.TestCase):
    def stage(self, *, simulation, bridge=None, observer=None, transport=None,
              clock=None, gates=None, closing_intent=None):
        clock = clock or Clock()
        return EndpointDStage(
            run_id=RUN_ID, source_seat="member_a", stage_generation=2,
            launch_identity_sha256=LAUNCH_HASH,
            closing_intent=closing_intent or intent(),
            bridge=bridge, simulation=simulation, observer=observer, transport=transport,
            close_tail_seconds=0.05, tick_seconds=0.01,
            monotonic=clock.monotonic, sleep=clock.sleep,
            gate_sink=gates.append if gates is not None else (lambda _value: None),
        )

    def test_clean_close_runs_d2_d3_d4_once_and_matches_schema(self):
        clock, gates, calls = Clock(), [], []
        simulation = Simulation(disconnect_after=2, log=calls)
        bridge, observer, transport = Bridge(log=calls), Observer(calls), Transport(log=calls)
        stage = self.stage(
            simulation=simulation, bridge=bridge, observer=observer,
            transport=transport, clock=clock, gates=gates,
        )
        report = stage.run()
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["forced"])
        self.assertEqual([item["gate"] for item in gates], list(GATES))
        self.assertEqual(observer.calls, [False])
        self.assertEqual(calls, [
            "simulation.tick", "simulation.tick", "bridge.drain", "observer.stop",
            "simulation.close", "bridge.stop", "transport.stop",
        ])
        self.assertEqual((simulation.closes, bridge.drains, bridge.stops, transport.stops),
                         (1, 1, 1, 1))

        replay = stage.run()
        self.assertEqual(replay, report)
        self.assertEqual((simulation.closes, bridge.drains, bridge.stops, transport.stops),
                         (1, 1, 1, 1))
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "d-endpoint-stage.v1.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(set(report), set(schema["required"]))

    def test_timeout_preserves_order_and_continues_through_ldn_failure(self):
        clock, gates = Clock(), []
        simulation, bridge = Simulation(), Bridge()
        observer, transport = Observer(), Transport("thread remained alive")
        report = self.stage(
            simulation=simulation, bridge=bridge, observer=observer,
            transport=transport, clock=clock, gates=gates,
            closing_intent=intent("failed"),
        ).run()
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["forced"])
        self.assertEqual(report["primary_failure_code"], "C_RFU_LOST")
        self.assertEqual(
            [item["code"] for item in report["failures"]],
            ["D_CLOSE_TAIL_TIMEOUT", "D_LDN_TEARDOWN_FAILED"],
        )
        self.assertEqual([item["gate"] for item in gates], [GATES[1]])
        self.assertEqual((simulation.closes, bridge.stops, transport.stops), (1, 1, 1))
        self.assertTrue(report["evidence"]["bridge_transport_exited"])
        self.assertFalse(report["evidence"]["ldn_released"])

    def test_d2_exception_is_bounded_and_d3_d4_still_release(self):
        gates = []
        simulation = Simulation(tick_error="native tick failed")
        bridge, observer, transport = Bridge(), Observer(), Transport()
        report = self.stage(
            simulation=simulation, bridge=bridge, observer=observer, transport=transport,
            clock=Clock(), gates=gates,
        ).run()
        self.assertEqual(report["failures"][0]["code"], "D_CLOSE_TAIL_FAILED")
        self.assertEqual([item["gate"] for item in gates], [GATES[1], GATES[2]])
        self.assertEqual((bridge.drains, bridge.stops, transport.stops), (1, 1, 1))

    def test_all_d3_faults_are_bounded_and_d4_still_releases(self):
        gates = []
        simulation = Simulation(disconnect_after=1, close_error="simulation close failed")
        bridge = Bridge(drain_error="drain failed", stop_error="bridge stop failed")
        observer = Observer(error="observer stop failed")
        transport = Transport()
        report = self.stage(
            simulation=simulation, bridge=bridge, observer=observer, transport=transport,
            clock=Clock(), gates=gates,
        ).run()
        self.assertEqual([item["code"] for item in report["failures"]], [
            "D_BRIDGE_DRAIN_FAILED", "D_OBSERVER_STOP_FAILED",
            "D_SIMULATION_CLOSE_FAILED", "D_BRIDGE_TRANSPORT_STOP_FAILED",
        ])
        self.assertEqual([item["gate"] for item in gates], [GATES[0], GATES[2]])
        self.assertEqual((bridge.drains, bridge.stops, transport.stops), (1, 1, 1))

    def test_completed_intent_requires_trade_complete(self):
        invalid = intent("completed")
        invalid["last_passed_gate"] = "C_RFU_ACTIVE"
        with self.assertRaisesRegex(ValueError, "outcome"):
            self.stage(simulation=None, closing_intent=invalid)

    def test_bridge_identity_must_match_closing_intent(self):
        bridge = Bridge()
        bridge.attempt_id = "another-attempt"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.stage(simulation=None, bridge=bridge)


if __name__ == "__main__":
    unittest.main()
