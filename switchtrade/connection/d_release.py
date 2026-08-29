"""Control-owned D6 verification and ordered D7-D11 local resource release."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import time
from typing import Callable

from switchtrade.connection.coordinator import (
    ConnectionCoordinator,
    FunctionalOutcome,
    Phase,
    RunMode,
)
from switchtrade.connection.d_control import DControlError, load_d5_state
from switchtrade.connection.d_probes import (
    verify_launch_absence,
    verify_stable_radio_quiescence,
)
from switchtrade.connection.p0 import atomic_json
from switchtrade.c2_protocol import launch_identity_hash


CONTRACT_VERSION = "d-local-release.v1"
GATES = (
    "D6_TWO_SIDE_BARRIER", "D7_DIAGNOSTIC_RESOURCES", "D8_ENDPOINT_VERIFICATION",
    "D9_RADIO_QUIESCENCE", "D10_USB_RETURN", "D11_RELEASE",
)
_TERMINAL_ATTEMPTS = {"completed", "canceled", "failed"}
_SOFTWARE_ONLY_MODES = {RunMode.C_HARNESS.value}
_DIAGNOSTIC_MODES = {
    RunMode.DIAGNOSTIC_AUTOMATED.value, RunMode.DIAGNOSTIC_A.value,
    RunMode.DIAGNOSTIC_B.value, RunMode.DIAGNOSTIC_SUITE.value,
}
_CODE = re.compile(r"[A-Z][A-Z0-9_.-]{0,95}")
_REPORT_FIELDS = {
    "contract_version", "schema", "run_id", "attempt_id", "status", "last_passed_gate",
    "shared_barrier_status", "shared_cleanup_verified", "evidence", "failures",
}


class LocalDRelease:
    """Verify the relay barrier, then release resources in D7-D11 order.

    Probes return small, typed projections. They perform no teardown; the endpoint supervisor and
    USB lease remain the sole action owners. Any active or unknown observation fails closed.
    """

    def __init__(
        self,
        *,
        coordinator: ConnectionCoordinator,
        run_id: str,
        d5_state_path: str | Path,
        release_state_path: str | Path,
        launch_probe: Callable[[dict], dict],
        radio_probe: Callable[[dict], dict] | None = None,
        usb_lease=None,
        diagnostic_cleanup: Callable[[], dict] | None = None,
        stable_samples: int = 3,
        sample_interval: float = 0.1,
        radio_timeout: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if stable_samples < 2 or sample_interval <= 0 or radio_timeout <= 0:
            raise ValueError("D local release policy is invalid")
        self.coordinator = coordinator
        self.run_id = run_id
        self.d5_state_path = Path(d5_state_path)
        self.release_state_path = Path(release_state_path)
        self.launch_probe = launch_probe
        self.radio_probe = radio_probe
        self.usb_lease = usb_lease
        self.diagnostic_cleanup = diagnostic_cleanup
        self.stable_samples = stable_samples
        self.sample_interval = sample_interval
        self.radio_timeout = radio_timeout
        self.monotonic = monotonic
        self.sleep = sleep

    @staticmethod
    def _d6(room: dict, run: dict, d5: dict | None) -> dict:
        identity = run["identity"]
        attempt = room.get("attempt") if isinstance(room, dict) else None
        state = attempt.get("d") if isinstance(attempt, dict) else None
        side = state.get("sides", {}).get(identity.get("authority_seat")) if isinstance(state, dict) else None
        payload = d5["payload"] if d5 is not None else None
        comparable = None if payload is None else {
            "run_id": payload["run_id"], "stage_generation": payload["stage_generation"],
            "launch_identity_sha256": payload["launch_identity_sha256"],
            "evidence": payload["evidence"],
        }
        side_fields = {
            "run_id", "stage_generation", "launch_identity_sha256", "evidence", "acknowledged_at"}
        invalid = (
            not isinstance(attempt, dict) or not isinstance(state, dict) or
            room.get("room_id") != identity.get("room_id") or
            attempt.get("attempt_id") != identity.get("attempt_id") or
            attempt.get("phase") not in _TERMINAL_ATTEMPTS or
            state.get("barrier_status") not in {
                "two_side_terminal", "forced_timeout", "forced_failure"} or
            state.get("cleanup_status") not in {"verified", "failed"} or
            state.get("terminalized_at") is None or
            not isinstance(state.get("activation_generation"), int) or
            isinstance(state.get("activation_generation"), bool) or
            state.get("activation_generation") < 1 or
            (state.get("barrier_status") in {"forced_timeout", "forced_failure"} and
             state.get("cleanup_status") != "failed")
        )
        side_valid = (
            isinstance(side, dict) and set(side) == side_fields and
            (comparable is None or all(side.get(key) == value for key, value in comparable.items()))
        )
        if comparable is None and side_valid:
            expected_hash = launch_identity_hash(
                run["run_id"], identity["stage_generation"],
                identity["launch_nonce"], identity["endpoint_pid"],
            )
            side_valid = all((
                side["run_id"] == run["run_id"],
                side["stage_generation"] == identity["stage_generation"],
                side["launch_identity_sha256"] == expected_hash,
            ))
        recovery_without_side = (
            comparable is None and run.get("recovery_required") is True and side is None and
            isinstance(state, dict) and state.get("barrier_status") in {
                "forced_timeout", "forced_failure"}
        )
        activation_valid = (
            isinstance(state, dict) and
            (payload is None or state.get("activation_generation") == payload["activation_generation"])
        )
        if invalid or not activation_valid or not (side_valid or recovery_without_side):
            raise DControlError(
                "D_BARRIER_UNVERIFIED", GATES[0],
                "the relay D6 terminal barrier does not contain this run's measured D5 evidence",
            )
        expected_outcome = {
            FunctionalOutcome.PASSED.value: "completed",
            FunctionalOutcome.CANCELED.value: "canceled",
            FunctionalOutcome.FAILED.value: "failed",
            FunctionalOutcome.INTERRUPTED.value: "failed",
        }.get(run["functional"]["status"])
        if attempt["phase"] != expected_outcome or state.get("outcome") != expected_outcome:
            raise DControlError(
                "D_OUTCOME_MISMATCH", GATES[0],
                "the relay terminal outcome does not match the coordinator result",
            )
        expected_primary = run["functional"].get("code") if expected_outcome == "failed" else None
        if state.get("primary_failure_code") != expected_primary:
            raise DControlError(
                "D_OUTCOME_MISMATCH", GATES[0],
                "the relay primary result does not match the coordinator result",
            )
        return state

    def _radio_evidence(self, identity: dict) -> tuple[dict, bool]:
        if identity["mode"] in _SOFTWARE_ONLY_MODES:
            return {
                "status": "quiescent", "owned_interfaces": 0,
                "driver_threads": 0, "phy_active": False,
            }, True
        if self.radio_probe is None:
            return {
                "status": "unknown", "owned_interfaces": None,
                "driver_threads": None, "phy_active": None,
            }, False
        return verify_stable_radio_quiescence(
            self.radio_probe, {**identity, "run_id": self.run_id},
            stable_samples=self.stable_samples,
            sample_interval=self.sample_interval,
            timeout=self.radio_timeout,
            monotonic=self.monotonic,
            sleep=self.sleep,
        )

    @staticmethod
    def _diagnostic_evidence(callback, required: bool) -> tuple[dict, bool]:
        if not required:
            return {
                "synthetic_peer_stopped": True,
                "temporary_room_closed": True,
                "credential_file_absent": True,
            }, True
        if callback is None:
            return {
                "synthetic_peer_stopped": False,
                "temporary_room_closed": False,
                "credential_file_absent": False,
            }, False
        try:
            value = callback()
        except Exception:
            value = None
        fields = {"synthetic_peer_stopped", "temporary_room_closed", "credential_file_absent"}
        if not isinstance(value, dict) or set(value) != fields or any(
                not isinstance(value.get(key), bool) for key in fields):
            value = {key: False for key in fields}
        return value, all(value.values())

    def _persist(self, report: dict) -> None:
        atomic_json(self.release_state_path, report, private=True)

    def _finish_terminal_report(self, run: dict) -> dict:
        """Finish the local evidence file after a lost D11 response without repeating teardown."""
        try:
            report = json.loads(self.release_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise DControlError(
                "D_RELEASE_REPORT_INVALID", GATES[5],
                "the verified terminal run has no recoverable local release report",
            ) from error
        valid = (
            isinstance(report, dict) and set(report) == _REPORT_FIELDS and
            report.get("contract_version") == CONTRACT_VERSION and report.get("schema") == 1 and
            report.get("run_id") == self.run_id and
            report.get("attempt_id") == run["identity"].get("attempt_id") and
            report.get("status") in {"running", "passed"} and
            report.get("last_passed_gate") in {GATES[4], GATES[5]} and
            isinstance(report.get("evidence"), dict) and report.get("failures") == []
        )
        if not valid:
            raise DControlError(
                "D_RELEASE_REPORT_INVALID", GATES[5],
                "the verified terminal run's local release report is inconsistent",
            )
        self.d5_state_path.unlink(missing_ok=True)
        if report["status"] != "passed" or report["last_passed_gate"] != GATES[5]:
            report["status"] = "passed"
            report["last_passed_gate"] = GATES[5]
            self._persist(report)
        return report

    def release(self, room: dict) -> dict:
        """Run D7-D11 once D6 is terminal; return factual local cleanup state."""
        run = self.coordinator.snapshot(self.run_id)
        if not isinstance(run, dict):
            raise DControlError("D_RUN_STATE_INVALID", GATES[0], "the coordinator run is unavailable")
        if run["phase"] == Phase.TERMINAL.value and run["cleanup"]["verified"]:
            report = self._finish_terminal_report(run)
            return {"status": "passed", "run": run, "report": report}
        if run["phase"] == Phase.TERMINAL.value:
            run = self.coordinator.retry_cleanup(self.run_id)
        elif run["phase"] not in {Phase.CLOSING.value, Phase.CLEANING.value}:
            raise DControlError(
                "D_RUN_STATE_INVALID", GATES[0], "the coordinator run is not in D cleanup")
        d5 = load_d5_state(self.d5_state_path) if self.d5_state_path.exists() else None
        if d5 is None and not run.get("recovery_required"):
            raise DControlError(
                "D_CONTROL_STATE_INVALID", GATES[0],
                "the measured D5 state is missing outside startup recovery",
            )
        d6 = self._d6(room, run, d5)
        if run["phase"] == Phase.CLOSING.value:
            run = self.coordinator.begin_cleanup(self.run_id)

        report = {
            "contract_version": CONTRACT_VERSION,
            "schema": 1,
            "run_id": self.run_id,
            "attempt_id": run["identity"]["attempt_id"],
            "status": "running",
            "last_passed_gate": GATES[0],
            "shared_barrier_status": d6["barrier_status"],
            "shared_cleanup_verified": d6["cleanup_status"] == "verified",
            "evidence": {},
            "failures": [],
        }
        self._persist(report)

        diagnostic, d7_ok = self._diagnostic_evidence(
            self.diagnostic_cleanup, run["identity"]["mode"] in _DIAGNOSTIC_MODES)
        report["evidence"]["diagnostic"] = diagnostic
        if d7_ok:
            report["last_passed_gate"] = GATES[1]
        else:
            report["failures"].append({
                "code": "D_DIAGNOSTIC_CLEANUP_FAILED", "gate": GATES[1],
                "message": "diagnostic-owned resources were not fully released",
            })
        self._persist(report)

        launch, d8_ok = verify_launch_absence(
            self.launch_probe, {**deepcopy(run["identity"]), "run_id": self.run_id})
        report["evidence"]["launch"] = launch
        if d8_ok:
            report["last_passed_gate"] = GATES[2]
        else:
            report["failures"].append({
                "code": "D_ENDPOINT_UNVERIFIED", "gate": GATES[2],
                "message": "the exact endpoint launch is active or its state is unknown",
            })
        self._persist(report)

        radio, d9_ok = self._radio_evidence(run["identity"])
        report["evidence"]["radio"] = radio
        if d8_ok and d9_ok:
            report["last_passed_gate"] = GATES[3]
        elif not d9_ok:
            report["failures"].append({
                "code": "D_RADIO_NOT_QUIESCENT", "gate": GATES[3],
                "message": "Linux radio quiescence was not stable or was unknown",
            })
        self._persist(report)

        usb = {
            "prior_state_restored": False, "windows_state_verified": False,
            "linux_state_verified": False, "detached_by_run": False,
        }
        d10_ok = False
        if d8_ok and d9_ok:
            if run["identity"]["mode"] in _SOFTWARE_ONLY_MODES:
                usb.update(
                    prior_state_restored=True, windows_state_verified=True,
                    linux_state_verified=True)
                d10_ok = True
            elif self.usb_lease is None:
                report["failures"].append({
                    "code": "D_USB_OWNERSHIP_MISSING", "gate": GATES[4],
                    "message": "the run-owned USB lease is unavailable",
                })
            else:
                try:
                    value = self.usb_lease.release()
                    if isinstance(value, dict):
                        usb.update({key: value.get(key) for key in usb})
                    d10_ok = (
                        usb["prior_state_restored"] is True and
                        usb["windows_state_verified"] is True and
                        usb["linux_state_verified"] is True and
                        isinstance(usb["detached_by_run"], bool)
                    )
                except Exception as error:
                    code = getattr(error, "code", "D_USB_RETURN_FAILED")
                    if not isinstance(code, str) or _CODE.fullmatch(code) is None:
                        code = "D_USB_RETURN_FAILED"
                    message = str(error)[:500] or type(error).__name__
                    report["failures"].append({
                        "code": code, "gate": GATES[4], "message": message,
                    })
            if not d10_ok and not any(item["gate"] == GATES[4] for item in report["failures"]):
                report["failures"].append({
                    "code": "D_USB_RETURN_UNVERIFIED", "gate": GATES[4],
                    "message": "the exact prior USB ownership state was not verified",
                })
        report["evidence"]["usb"] = usb
        if d10_ok:
            report["last_passed_gate"] = GATES[4]

        verified = d7_ok and d8_ok and d9_ok and d10_ok
        report["status"] = "running" if verified else "failed"
        report["failures"] = report["failures"][:16]
        self._persist(report)

        cleanup_evidence = {
            "d6_terminal": True,
            "d6_shared_cleanup_verified": report["shared_cleanup_verified"],
            "diagnostic_resources_released": d7_ok,
            "endpoint_identity_absent": d8_ok,
            "radio_stably_quiescent": d9_ok,
            "usb_prior_state_restored": d10_ok,
        }
        if verified:
            terminal = self.coordinator.complete_cleanup(
                self.run_id, verified=True, evidence=cleanup_evidence)
            self.d5_state_path.unlink(missing_ok=True)
            report["status"] = "passed"
            report["last_passed_gate"] = GATES[5]
            self._persist(report)
        else:
            first = report["failures"][0]
            terminal = self.coordinator.complete_cleanup(
                self.run_id, verified=False, evidence=cleanup_evidence,
                code="D_LOCAL_CLEANUP_FAILED", message=first["message"],
            )
        return {"status": report["status"], "run": terminal, "report": report}


__all__ = ["CONTRACT_VERSION", "GATES", "LocalDRelease"]
