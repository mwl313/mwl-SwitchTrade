"""Persisted, production-path diagnostics for one-PC SwitchTrade prequalification.

This module owns lifecycle, persistence, checkpoints, and cancellation only.  The
control service supplies the hardware/relay/endpoint work so diagnostics reuse the
same production paths rather than growing a second test stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Callable
import uuid

from switchtrade.rfu_tunnel import Kind
from switchtrade.tunnel_client import TunnelClient
from switchtrade.connection.b_fixture import (
    FIXTURE as AP_FIXTURE,
    FIXTURE_ID as AP_FIXTURE_ID,
    metadata as fixture_metadata,
)


DIAGNOSTIC_CONTRACT = "production-diagnostic.v1"
TERMINAL = {"passed", "partial", "failed", "canceled"}


@dataclass(frozen=True)
class DiagnosticDefinition:
    identifier: str
    label: str
    requires_switch: bool
    result_limit: str


DEFINITIONS = {
    "automated": DiagnosticDefinition(
        "automated", "Run automated system check", False, "relay_exchange_passed"),
    "room_detection": DiagnosticDefinition(
        "room_detection", "Detect a Switch room", True, "switch_room_joined"),
    "ap_association": DiagnosticDefinition(
        "ap_association", "Test Switch AP association", True, "switch_associated"),
    "recommended": DiagnosticDefinition(
        "recommended", "Run recommended local suite", True, "local_prequalification_passed"),
}

# Kept in one place so desktop countdowns and control enforcement never drift.
TIMEOUTS = {
    "preflight": 60,
    "relay": 20,
    "endpoint": 45,
    "room_detection": 90,
    "ap_association": 120,
    "checkpoint": 300,
    "cleanup": 30,
    "whole_run": 600,
}

class DiagnosticFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, result_level: str | None = None,
                 preceding: "DiagnosticFailure | None" = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.result_level = result_level
        self.preceding = preceding


def diagnostic_member_pair(owner: dict, joined: dict, local_switch_role: str) -> dict:
    """Bind distinct authoritative members to complementary diagnostic roles."""
    if local_switch_role not in {"creator", "finder"}:
        raise DiagnosticFailure("DIAG_PRIVATE_ROOM_FAILED", "The diagnostic Switch role is invalid.")
    owner_token = owner.get("member_token")
    joined_token = joined.get("member_token")
    if (not isinstance(owner_token, str) or not isinstance(joined_token, str) or
            not owner_token or not joined_token or owner_token == joined_token):
        raise DiagnosticFailure(
            "DIAG_PRIVATE_ROOM_FAILED",
            "The private diagnostic room did not issue two distinct member credentials.",
        )
    local_is_owner = local_switch_role == "creator"
    peer_switch_role = "finder" if local_switch_role == "creator" else "creator"
    return {
        "local": owner if local_is_owner else joined,
        "peer": joined if local_is_owner else owner,
        "local_role": local_switch_role,
        "peer_role": peer_switch_role,
        "local_seat": "member_a" if local_is_owner else "member_b",
    }


class SyntheticDiagnosticPeer:
    """The remote app seat for diagnostics; it never emulates a Switch or radio."""

    def __init__(self, relay_url: str, room_code: str, role: str, member_token: str,
                 attempt_id: str, *, fixture: bytes | None = None):
        self.tunnel = TunnelClient(
            relay_url, room_code, role, member_token=member_token, attempt_id=attempt_id,
        )
        self.fixture = fixture
        self.stop_requested = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.tunnel.start()
        if not self.tunnel.wait_connected(TIMEOUTS["relay"]):
            raise DiagnosticFailure("DIAG_SYNTHETIC_PEER_FAILED",
                                    "The diagnostic peer could not connect to the relay.")
        if self.fixture is not None:
            self.tunnel.advertise(self.fixture)
        self.thread = threading.Thread(target=self._serve, name="switchtrade-diagnostic-peer", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stop_requested.is_set():
            for envelope in self.tunnel.poll():
                if envelope.kind == Kind.RFU and envelope.payload.startswith(b"STDIAG1:"):
                    try:
                        self.tunnel.send(b"STDIAG2:" + envelope.payload[len(b"STDIAG1:"):])
                    except (ConnectionError, ValueError):
                        return
            time.sleep(0.02)

    def stop(self) -> None:
        self.stop_requested.set()
        self.tunnel.stop()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError("diagnostic peer did not stop")


class DiagnosticD7Resources:
    """Own diagnostic-only peer, room, and credential cleanup for LocalDRelease D7."""

    def __init__(self, *, close_room: Callable[[dict], None],
                 update_recovery: Callable[..., None]):
        self.close_room = close_room
        self.update_recovery = update_recovery
        self.peer: SyntheticDiagnosticPeer | None = None
        self.room: dict | None = None
        self.credential_file: Path | None = None

    def register_room(self, room: dict) -> None:
        self.room = room
        recovery_room = {
            "room_id": room["room_id"], "owner_token": room["owner_token"],
        }
        reconnect_token = room.get("owner_reconnect_token")
        if isinstance(reconnect_token, str) and reconnect_token:
            recovery_room["owner_reconnect_token"] = reconnect_token
        self.update_recovery(room=recovery_room)

    def register_peer(self, peer: SyntheticDiagnosticPeer) -> None:
        self.peer = peer

    def register_credential(self, credential_file: Path) -> None:
        self.credential_file = Path(credential_file)
        self.update_recovery(token_file=str(self.credential_file.resolve()))

    def cleanup(self) -> dict:
        """Return the exact Boolean-only D7 projection; failed resources remain retryable."""
        peer_stopped = self.peer is None
        if self.peer is not None:
            try:
                self.peer.stop()
                self.peer = None
                peer_stopped = True
            except Exception:
                peer_stopped = False

        room_closed = self.room is None
        if self.room is not None:
            try:
                self.close_room(self.room)
                self.update_recovery(room=None)
                self.room = None
                room_closed = True
            except Exception:
                room_closed = False

        credential_absent = self.credential_file is None
        if self.credential_file is not None:
            try:
                self.credential_file.unlink(missing_ok=True)
                if self.credential_file.exists():
                    raise OSError("diagnostic credential file still exists")
                self.update_recovery(token_file=None)
                self.credential_file = None
                credential_absent = True
            except Exception:
                credential_absent = False

        return {
            "synthetic_peer_stopped": peer_stopped,
            "temporary_room_closed": room_closed,
            "credential_file_absent": credential_absent,
        }


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]


class DiagnosticRun:
    """One persisted run.  All values written here are safe diagnostic metadata."""

    def __init__(self, root: Path, test: str, usb_id: str):
        self.root = root / _run_id()
        self.root.mkdir(parents=True, exist_ok=False)
        self.run_id = self.root.name
        self.test = test
        self.usb_id = usb_id.lower()
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.cancel_requested = False
        self.continued_checkpoint: str | None = None
        self.record = {
            "contract_version": DIAGNOSTIC_CONTRACT,
            "run_id": self.run_id,
            "test": test,
            "status": "created",
            "current_stage": "created",
            "checkpoint": None,
            "created_utc": _utc(),
            "updated_utc": _utc(),
            "adapter": {"usb_id": self.usb_id},
            "stages": [],
            "result_level": None,
            "limitations": [
                "A passed diagnostic does not certify a complete physical trade.",
                "No raw packets, room credentials, hardware addresses, or game data are retained.",
            ],
            "cleanup": {"status": "pending", "evidence": {}},
        }
        self._write_locked()

    @property
    def report_path(self) -> Path:
        return self.root / "production-diagnostic-report.json"

    def _write_locked(self) -> None:
        self.record["updated_utc"] = _utc()
        temporary = self.report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.report_path)

    def projection(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.record))

    def transition(self, status: str, stage: str, *, checkpoint: dict | None = None) -> None:
        with self.lock:
            if self.record["status"] in TERMINAL:
                return
            self.record.update(status=status, current_stage=stage, checkpoint=checkpoint)
            self._write_locked()
            self.changed.notify_all()

    def stage(self, name: str, status: str, code: str, message: str,
              *, details: dict | None = None) -> None:
        safe_details = details or {}
        with self.lock:
            existing = next((item for item in self.record["stages"] if item["name"] == name), None)
            value = {
                "name": name, "status": status, "code": code, "message": message,
                "updated_utc": _utc(), "details": safe_details,
            }
            if existing is None:
                self.record["stages"].append(value)
            else:
                existing.update(value)
            self.record["current_stage"] = name
            self._write_locked()
            self.changed.notify_all()

    def set_result(self, level: str) -> None:
        with self.lock:
            self.record["result_level"] = level
            self._write_locked()

    def await_continue(self, checkpoint_id: str, instructions: str,
                       timeout: int = TIMEOUTS["checkpoint"]) -> None:
        deadline = time.monotonic() + timeout
        checkpoint = {
            "id": checkpoint_id, "instructions": instructions,
            "deadline_utc": (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat().replace("+00:00", "Z"),
        }
        self.transition("awaiting_user", checkpoint_id, checkpoint=checkpoint)
        with self.changed:
            while self.continued_checkpoint != checkpoint_id:
                if self.cancel_requested:
                    raise DiagnosticFailure("DIAG_CANCELED", "The diagnostic was canceled.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DiagnosticFailure("DIAG_CHECKPOINT_TIMEOUT", "The diagnostic checkpoint timed out.")
                self.changed.wait(min(remaining, 0.5))
            self.continued_checkpoint = None
        self.transition("running", checkpoint_id)

    def continue_run(self, checkpoint_id: str) -> bool:
        with self.changed:
            checkpoint = self.record.get("checkpoint") or {}
            if self.record["status"] != "awaiting_user" or checkpoint.get("id") != checkpoint_id:
                return False
            self.continued_checkpoint = checkpoint_id
            self.changed.notify_all()
            return True

    def cancel(self) -> bool:
        with self.changed:
            if self.record["status"] in TERMINAL:
                return False
            self.cancel_requested = True
            self.record["status"] = "cleaning"
            self.record["current_stage"] = "cleanup"
            self.record["checkpoint"] = None
            self._write_locked()
            self.changed.notify_all()
            return True

    def canceled(self) -> bool:
        with self.lock:
            return self.cancel_requested

    def begin_cleanup(self) -> None:
        self.transition("cleaning", "cleanup")

    def finish(self, status: str, *, code: str | None = None, message: str | None = None,
               result_level: str | None = None, cleanup_ok: bool = True,
               cleanup: dict | None = None,
               preceding_failure: DiagnosticFailure | None = None) -> None:
        with self.lock:
            if status not in TERMINAL:
                raise ValueError("diagnostic status must be terminal")
            if not cleanup_ok:
                status, code, message = "failed", "DIAG_CLEANUP_FAILED", "Diagnostic cleanup did not complete."
            self.record["status"] = status
            self.record["current_stage"] = "completed" if status == "passed" else "failed"
            self.record["checkpoint"] = None
            self.record["cleanup"] = cleanup or {
                "status": "passed" if cleanup_ok else "failed", "evidence": {},
            }
            if result_level is not None:
                self.record["result_level"] = result_level
            if code:
                self.record["failure"] = {"code": code, "message": message or "Diagnostic failed."}
            if preceding_failure is not None:
                self.record["preceding_failure"] = {
                    "code": preceding_failure.code, "message": preceding_failure.message,
                }
            self._write_locked()
            self.changed.notify_all()


class ProductionDiagnostics:
    """Serializes runs and recovers interrupted records on the next control start."""

    def __init__(self, root: str | Path, recovery_file: str | Path | None = None,
                 report_root: str | Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.recovery_file = Path(recovery_file) if recovery_file else self.root / "active-recovery.json"
        self.report_root = Path(report_root).resolve() if report_root else self.root.resolve()
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.active: DiagnosticRun | None = None
        self.cleanup_incomplete = False
        self._recover_incomplete()

    def _read_recovery_locked(self) -> dict:
        try:
            value = json.loads(self.recovery_file.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) and value.get("schema") == 1 else {}
        except (OSError, ValueError):
            return {}

    def _write_recovery_locked(self, value: dict) -> None:
        self.recovery_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.recovery_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.recovery_file)

    def _report_from_recovery(self, recovery: dict) -> Path | None:
        try:
            report = Path(str(recovery["report_path"])).resolve()
            report.relative_to(self.report_root)
            return report
        except (KeyError, OSError, ValueError):
            return None

    def _recover_incomplete(self) -> None:
        recovery = self._read_recovery_locked()
        if not recovery:
            return
        self.cleanup_incomplete = True
        report = self._report_from_recovery(recovery)
        if report is None:
            return
        try:
            value = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if value.get("status") not in TERMINAL:
            value.update(
                status="failed", current_stage="failed", checkpoint=None, updated_utc=_utc(),
                cleanup={"status": "interrupted", "evidence": {}},
                failure={"code": "DIAG_RUN_INTERRUPTED",
                         "message": "The diagnostic was interrupted; startup cleanup is required."},
            )
            temporary = report.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(report)

    def recovery_state(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._read_recovery_locked()))

    def update_recovery(self, run_id: str, **updates) -> None:
        with self.lock:
            value = self._read_recovery_locked()
            if value.get("run_id") != run_id:
                return
            value.update(updates)
            self._write_recovery_locked(value)

    def complete_recovery(self, evidence: dict) -> None:
        with self.lock:
            recovery = self._read_recovery_locked()
            report = self._report_from_recovery(recovery)
            if report is not None:
                try:
                    value = json.loads(report.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    value = None
                if isinstance(value, dict):
                    value["cleanup"] = {"status": "passed", "recovered": True, "evidence": evidence}
                    value["updated_utc"] = _utc()
                    temporary = report.with_suffix(".json.tmp")
                    temporary.write_text(
                        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    temporary.replace(report)
            self.recovery_file.unlink(missing_ok=True)
            self.cleanup_incomplete = False

    def fail_recovery(self, message: str) -> None:
        with self.lock:
            value = self._read_recovery_locked()
            if value:
                value.update(status="unresolved", recovery_error=message[:500])
                self._write_recovery_locked(value)
            self.cleanup_incomplete = True

    def start(self, test: str, usb_id: str, worker) -> dict:
        if test not in DEFINITIONS:
            raise ValueError("unknown production diagnostic")
        with self.lock:
            if self.cleanup_incomplete:
                raise DiagnosticFailure(
                    "DIAG_CLEANUP_INCOMPLETE",
                    "A previous diagnostic did not prove cleanup. Restart or repair the local runtime before trying again.",
                )
            if self.active is not None:
                raise DiagnosticFailure("DIAG_RUN_ACTIVE", "Another production diagnostic is already running.")
            run = DiagnosticRun(self.root, test, usb_id)
            self.active = run
            self._write_recovery_locked({
                "schema": 1, "run_id": run.run_id, "report_path": str(run.report_path.resolve()),
                "status": "active", "adapter": {"usb_id": run.usb_id},
            })

        def execute() -> None:
            try:
                worker(run)
            except DiagnosticFailure as error:
                run.finish("canceled" if error.code == "DIAG_CANCELED" else "failed",
                           code=error.code, message=error.message,
                           result_level=error.result_level,
                           cleanup_ok=error.code != "DIAG_CLEANUP_FAILED",
                           preceding_failure=error.preceding)
            except Exception as error:  # final containment; details stay in the control run log
                run.finish("failed", code="DIAG_INTERNAL_ERROR",
                           message=f"The diagnostic stopped unexpectedly ({type(error).__name__}).",
                           cleanup_ok=False)
            finally:
                with self.lock:
                    if run.projection().get("cleanup", {}).get("status") == "passed":
                        recovery = self._read_recovery_locked()
                        if recovery.get("run_id") == run.run_id:
                            self.recovery_file.unlink(missing_ok=True)
                        self.cleanup_incomplete = False
                    else:
                        self.cleanup_incomplete = True
                        recovery = self._read_recovery_locked()
                        if recovery.get("run_id") == run.run_id:
                            recovery["status"] = "unresolved"
                            self._write_recovery_locked(recovery)
                    if self.active is run:
                        self.active = None
                    self.changed.notify_all()

        threading.Thread(target=execute, name=f"switchtrade-diagnostic-{run.run_id}", daemon=True).start()
        return run.projection()

    def get(self, run_id: str) -> dict | None:
        with self.lock:
            if self.active is not None and self.active.run_id == run_id:
                return self.active.projection()
        report = self.root / run_id / "production-diagnostic-report.json"
        try:
            return json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def continue_run(self, run_id: str, checkpoint_id: str) -> bool:
        with self.lock:
            return bool(self.active and self.active.run_id == run_id and
                        self.active.continue_run(checkpoint_id))

    def cancel(self, run_id: str) -> bool:
        with self.lock:
            return bool(self.active and self.active.run_id == run_id and self.active.cancel())

    def cancel_active(self) -> bool:
        with self.lock:
            return bool(self.active and self.active.cancel())

    def wait_for_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self.changed:
            while self.active is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.changed.wait(remaining)
            return True

    def running(self) -> bool:
        with self.lock:
            return self.active is not None
