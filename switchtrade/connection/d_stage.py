"""Endpoint-owned D2-D4 shutdown for the ABC+D production path."""

from __future__ import annotations

from copy import deepcopy
import re
import time
import uuid
from typing import Callable

from switchtrade.c2_protocol import launch_identity_hash


CONTRACT_VERSION = "d-endpoint-stage.v1"
GATES = ("D2_GAME_CLOSE_TAIL", "D3_BRIDGE_DRAIN", "D4_LDN_TEARDOWN")
_INTENT_FIELDS = {
    "contract_version", "attempt_id", "activation_generation", "outcome",
    "primary_failure_code", "last_passed_gate",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}")
_GATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")


class EndpointDStage:
    """Run the local endpoint's ordered shutdown exactly once."""

    def __init__(self, *, run_id: str, source_seat: str, stage_generation: int,
                 launch_identity_sha256: str, closing_intent: dict,
                 bridge=None, simulation=None, observer=None, transport=None,
                 close_tail_seconds: float = 10.0, tick_seconds: float = 1 / 60,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 gate_sink: Callable[[dict], None] = lambda _value: None):
        try:
            self.run_id = str(uuid.UUID(str(run_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("D run identity is invalid") from error
        if source_seat not in {"member_a", "member_b"}:
            raise ValueError("D source seat is invalid")
        if not isinstance(stage_generation, int) or isinstance(stage_generation, bool) or stage_generation < 1:
            raise ValueError("D stage generation is invalid")
        if not isinstance(launch_identity_sha256, str) or not _SHA256.fullmatch(
                launch_identity_sha256):
            raise ValueError("D launch identity is invalid")
        if (not isinstance(closing_intent, dict) or set(closing_intent) != _INTENT_FIELDS or
                closing_intent.get("contract_version") != "d-closing-intent.v1" or
                closing_intent.get("outcome") not in {"completed", "canceled", "failed"} or
                not isinstance(closing_intent.get("attempt_id"), str) or
                not closing_intent["attempt_id"] or len(closing_intent["attempt_id"]) > 128 or
                not isinstance(closing_intent.get("activation_generation"), int) or
                isinstance(closing_intent.get("activation_generation"), bool) or
                closing_intent["activation_generation"] < 1):
            raise ValueError("D closing intent is invalid")
        outcome = closing_intent["outcome"]
        primary = closing_intent.get("primary_failure_code")
        last_gate = closing_intent.get("last_passed_gate")
        if ((outcome == "failed") != isinstance(primary, str) or
                outcome != "failed" and primary is not None or
                isinstance(primary, str) and not _CODE.fullmatch(primary) or
                not isinstance(last_gate, str) or not _GATE.fullmatch(last_gate) or
                outcome == "completed" and last_gate != "C_TRADE_COMPLETE"):
            raise ValueError("D closing outcome is invalid")
        if close_tail_seconds <= 0 or tick_seconds <= 0:
            raise ValueError("D close-tail policy is invalid")

        self.source_seat = source_seat
        self.stage_generation = stage_generation
        self.launch_identity_sha256 = launch_identity_sha256
        self.intent = dict(closing_intent)
        if bridge is not None:
            client = getattr(bridge, "client", None)
            seat = getattr(getattr(bridge, "source_seat", None), "label", None)
            try:
                bridge_launch_hash = launch_identity_hash(
                    client.run_id, client.stage_generation,
                    client.launch_nonce, client.endpoint_pid,
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError("D bridge launch identity is unavailable") from error
            if (getattr(bridge, "run_id", None) != self.run_id or
                    getattr(bridge, "attempt_id", None) != closing_intent["attempt_id"] or
                    seat != source_seat or
                    getattr(bridge, "activation_generation", None) !=
                    closing_intent["activation_generation"] or
                    client.stage_generation != stage_generation or
                    bridge_launch_hash != launch_identity_sha256):
                raise ValueError("D bridge identity does not match the closing intent")
        self.bridge = bridge
        self.simulation = simulation
        self.observer = observer
        self.transport = transport
        self.close_tail_seconds = close_tail_seconds
        self.tick_seconds = tick_seconds
        self.monotonic = monotonic
        self.sleep = sleep
        self.gate_sink = gate_sink
        self._report: dict | None = None

    def _pass(self, gate: str, started: float) -> None:
        self.gate_sink({
            "gate": gate,
            "elapsed_ms": round((self.monotonic() - started) * 1000),
        })

    @staticmethod
    def _failure(code: str, gate: str, error: BaseException | str) -> dict:
        return {"code": code, "gate": gate, "message": str(error)[:500]}

    def run(self) -> dict:
        if self._report is not None:
            return deepcopy(self._report)
        started = self.monotonic()
        failures = []
        evidence = {
            "close_tail_required": self.simulation is not None,
            "close_tail_observed": self.simulation is None,
            "bridge_admission_stopped": self.bridge is None,
            "bridge_transport_exited": self.bridge is None,
            "observer_stopped": self.observer is None,
            "simulation_closed": self.simulation is None,
            "ldn_released": self.transport is None,
            "radio_thread_exited": self.transport is None,
        }
        drain = {
            "pending_local_frames": 0, "flushed_local_frames": 0,
            "discarded_local_frames": 0, "discarded_remote_frames": 0,
        }

        # D2: keep the existing Pia/Reliable path alive only for the bounded native close tail.
        if self.simulation is not None:
            deadline = started + self.close_tail_seconds
            try:
                while not getattr(self.simulation, "host_disconnected", False):
                    remaining = deadline - self.monotonic()
                    if remaining <= 0:
                        break
                    self.simulation.tick()
                    if getattr(self.simulation, "host_disconnected", False):
                        break
                    self.sleep(min(self.tick_seconds, remaining))
                evidence["close_tail_observed"] = bool(
                    getattr(self.simulation, "host_disconnected", False))
            except Exception as error:
                failures.append(self._failure("D_CLOSE_TAIL_FAILED", GATES[0], error))
            if not evidence["close_tail_observed"] and not failures:
                failures.append(self._failure(
                    "D_CLOSE_TAIL_TIMEOUT", GATES[0],
                    "native Switch close-link tail exceeded its deadline",
                ))
        if evidence["close_tail_observed"]:
            self._pass(GATES[0], started)

        # D3: seal RFU admission, account for bounded queues, finalize evidence, then stop C transport.
        d3_ok = True
        if self.bridge is not None:
            try:
                result = self.bridge.finish_drain(self.intent["outcome"])
                evidence["bridge_admission_stopped"] = result.get("admission_stopped") is True
                drain.update({key: int(result.get(key, 0)) for key in drain})
                if not evidence["bridge_admission_stopped"]:
                    failures.append(self._failure(
                        "D_BRIDGE_ADMISSION_ACTIVE", GATES[1],
                        "C2 bridge still accepts RFU after drain",
                    ))
                    d3_ok = False
                if result.get("error_code"):
                    failures.append(self._failure(
                        str(result["error_code"]), GATES[1], "C2 bridge could not drain cleanly"))
                    d3_ok = False
            except Exception as error:
                failures.append(self._failure("D_BRIDGE_DRAIN_FAILED", GATES[1], error))
                d3_ok = False
        if self.observer is not None:
            try:
                self.observer.stop(clear=False)
                evidence["observer_stopped"] = True
            except Exception as error:
                failures.append(self._failure("D_OBSERVER_STOP_FAILED", GATES[1], error))
                d3_ok = False
        if self.simulation is not None:
            try:
                self.simulation.close()
                evidence["simulation_closed"] = True
            except Exception as error:
                failures.append(self._failure("D_SIMULATION_CLOSE_FAILED", GATES[1], error))
                d3_ok = False
        if self.bridge is not None:
            try:
                self.bridge.stop_transport()
                evidence["bridge_transport_exited"] = True
            except Exception as error:
                failures.append(self._failure("D_BRIDGE_TRANSPORT_STOP_FAILED", GATES[1], error))
                d3_ok = False
        if d3_ok and evidence["bridge_admission_stopped"] and evidence["bridge_transport_exited"]:
            self._pass(GATES[1], started)

        # D4: the admitted transport stop owns LDN context exit, socket close, thread join, and vif sweep.
        if self.transport is not None:
            try:
                self.transport.stop()
                evidence["ldn_released"] = True
                evidence["radio_thread_exited"] = True
            except Exception as error:
                failures.append(self._failure("D_LDN_TEARDOWN_FAILED", GATES[2], error))
        if evidence["ldn_released"] and evidence["radio_thread_exited"]:
            self._pass(GATES[2], started)

        self._report = {
            "contract_version": CONTRACT_VERSION,
            "run_id": self.run_id,
            "attempt_id": self.intent["attempt_id"],
            "activation_generation": self.intent["activation_generation"],
            "source_seat": self.source_seat,
            "stage_generation": self.stage_generation,
            "launch_identity_sha256": self.launch_identity_sha256,
            "outcome": self.intent["outcome"],
            "primary_failure_code": self.intent["primary_failure_code"],
            "last_passed_gate": next(
                (gate for gate in reversed(GATES) if not any(
                    failure["gate"] == gate for failure in failures)), None),
            "status": "passed" if not failures else "failed",
            "forced": bool(failures),
            "evidence": evidence,
            "drain": drain,
            "failures": failures[:16],
            "elapsed_ms": round((self.monotonic() - started) * 1000),
        }
        return deepcopy(self._report)


__all__ = ["CONTRACT_VERSION", "EndpointDStage", "GATES"]
