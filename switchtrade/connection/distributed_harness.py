"""GUI-independent two-PC/two-Switch ABC+D qualification runner."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from switchtrade.connection.coordinator import (
    AuthoritySeat,
    ConnectionCoordinator,
    FunctionalOutcome,
    RunMode,
    SwitchRole,
)
from switchtrade.connection.d_control import MeasuredD5Control
from switchtrade.connection.d_probes import WslDProbes
from switchtrade.connection.d_release import LocalDRelease
from switchtrade.connection.p0 import P0Error, PassiveValidator, atomic_json
from switchtrade.connection.p0_harness import P0Harness, _installed_release, _wsl_path
from switchtrade.diagnostics import default_runs_root
from switchtrade.relay_client import RelayClient, RelayError


INVITATION_CONTRACT = "distributed-invitation.v2"
SESSION_CONTRACT = "distributed-session.v1"
ROOM_CONTRACT = "room-control.v1"
ROLES = {"a_room_joiner", "b_ap_host"}
ACTIONS = {"end", "stop", "leave", "close"}
TERMINAL_ATTEMPTS = {"completed", "canceled", "failed"}
ROLE_CHECKPOINTS = {
    "a_room_joiner": "CREATE_SWITCH_ROOM",
    "b_ap_host": "JOIN_SWITCH_GROUP",
}
SOURCE_SHA = re.compile(r"[0-9a-f]{40}")
RELAY_POLL_INTERVAL = 1.0
RELAY_HEARTBEAT_INTERVAL = 10.0


def _status(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, sort_keys=True, separators=(",", ":")), flush=True)


def _source_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            text=True, encoding="utf-8", timeout=5, check=False,
        )
        value = result.stdout.strip().lower()
    except (OSError, subprocess.SubprocessError) as error:
        raise SystemExit("DISTRIBUTED_SOURCE_IDENTITY_UNAVAILABLE") from error
    if result.returncode != 0 or SOURCE_SHA.fullmatch(value) is None:
        raise SystemExit("DISTRIBUTED_SOURCE_IDENTITY_UNAVAILABLE")
    clean = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, encoding="utf-8", timeout=5, check=False,
    )
    if clean.returncode != 0 or clean.stdout.strip():
        raise SystemExit("DISTRIBUTED_SOURCE_WORKTREE_DIRTY")
    return value


def _invitation(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_invitation(encoded: str) -> dict:
    try:
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 2048:
            raise ValueError("invitation size")
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit("DISTRIBUTED_INVITATION_INVALID") from error
    fields = {
        "contract_version", "test_id", "source_sha", "release", "room_id", "room_code",
        "action", "owner_role", "peer_role",
    }
    try:
        uuid.UUID(str(value.get("test_id")))
        uuid.UUID(str(value.get("room_id")))
    except (AttributeError, TypeError, ValueError) as error:
        raise SystemExit("DISTRIBUTED_INVITATION_INVALID") from error
    if (
        not isinstance(value, dict) or set(value) != fields or
        value.get("contract_version") != INVITATION_CONTRACT or
        SOURCE_SHA.fullmatch(str(value.get("source_sha", ""))) is None or
        value.get("action") not in ACTIONS or value.get("owner_role") not in ROLES or
        value.get("peer_role") not in ROLES or value["owner_role"] == value["peer_role"] or
        {value["owner_role"], value["peer_role"]} != ROLES or
        not isinstance(value.get("release"), str) or not 1 <= len(value["release"]) <= 64 or
        not isinstance(value.get("room_id"), str) or not value["room_id"] or
        not isinstance(value.get("room_code"), str) or
        re.fullmatch(r"[A-Z0-9]{6}", value["room_code"]) is None
    ):
        raise SystemExit("DISTRIBUTED_INVITATION_INVALID")
    return value


def _validate_room_identity(
    room: dict, *, room_id: str, room_code: str, expected_seat: str,
) -> list[dict]:
    """Validate authoritative private-room identity, never optional directory metadata."""
    try:
        uuid.UUID(str(room_id))
        valid_room_id = True
    except (AttributeError, TypeError, ValueError):
        valid_room_id = False
    members = room.get("members") if isinstance(room, dict) else None
    local_id = room.get("local_member_id") if isinstance(room, dict) else None
    active = [
        item for item in members or []
        if isinstance(item, dict) and item.get("online_state") != "left"
    ]
    local = next((item for item in active if item.get("member_id") == local_id), None)
    member_ids = [item.get("member_id") for item in active]
    seats = [item.get("seat") for item in active]
    if (
        not valid_room_id or re.fullmatch(r"[A-Z0-9]{6}", str(room_code)) is None or
        expected_seat not in {"member_a", "member_b"} or
        not isinstance(room, dict) or room.get("contract_version") != ROOM_CONTRACT or
        room.get("room_id") != room_id or room.get("room_code") != room_code or
        room.get("visibility") != "private" or
        not isinstance(local, dict) or local.get("seat") != expected_seat or
        len(member_ids) != len(set(member_ids)) or len(seats) != len(set(seats)) or
        any(not isinstance(item, str) or not item for item in member_ids) or
        any(item not in {"member_a", "member_b"} for item in seats)
    ):
        raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    return active


def _validate_room_credential(value: dict) -> tuple[dict, str, str]:
    if not isinstance(value, dict):
        raise SystemExit("DISTRIBUTED_ROOM_CREDENTIAL_INVALID")
    room = value.get("room")
    member_token = value.get("member_token")
    reconnect_token = value.get("reconnect_token")
    if (
        not isinstance(room, dict) or
        not isinstance(member_token, str) or len(member_token) < 32 or
        not isinstance(reconnect_token, str) or len(reconnect_token) < 32
    ):
        raise SystemExit("DISTRIBUTED_ROOM_CREDENTIAL_INVALID")
    return room, member_token, reconnect_token


def _local_member(room: dict) -> dict:
    local_id = room.get("local_member_id")
    members = room.get("members")
    member = next(
        (item for item in members or [] if isinstance(item, dict) and item.get("member_id") == local_id),
        None,
    )
    if not isinstance(member, dict) or member.get("seat") not in {"member_a", "member_b"}:
        raise P0Error(
            "DISTRIBUTED_AUTHORITY_INVALID", "C0_authority",
            "relay membership does not contain one stable local seat",
        )
    return member


def _strict_session(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID") from error
    fields = {
        "contract_version", "schema", "test_id", "source_sha", "release", "action",
        "switch_role", "owner", "room_id", "room_code", "member_token", "reconnect_token",
    }
    try:
        uuid.UUID(str(value.get("test_id")))
        uuid.UUID(str(value.get("room_id")))
    except (AttributeError, TypeError, ValueError) as error:
        raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID") from error
    if (
        not isinstance(value, dict) or set(value) != fields or
        value.get("contract_version") != SESSION_CONTRACT or value.get("schema") != 1 or
        value.get("switch_role") not in ROLES or value.get("action") not in ACTIONS or
        not isinstance(value.get("owner"), bool) or
        SOURCE_SHA.fullmatch(str(value.get("source_sha", ""))) is None or
        re.fullmatch(r"[A-Z0-9]{6}", str(value.get("room_code", ""))) is None or
        any(not isinstance(value.get(name), str) or not value[name]
            for name in ("test_id", "source_sha", "release", "room_id", "room_code",
                         "member_token", "reconnect_token"))
    ):
        raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID")
    return value


class DistributedLifecycle:
    """Relay/C/D policy plugged into the canonical P0 hardware owner."""

    def __init__(self, *, coordinator: ConnectionCoordinator, relay: RelayClient,
                 session: dict, session_path: Path, distro: str, packaged_python: str,
                 timeout: float = 300):
        self.coordinator = coordinator
        self.relay = relay
        self.session = session
        self.session_path = session_path
        self.distro = distro
        self.packaged_python = packaged_python
        self.timeout = timeout
        self.room = relay.room(session["room_id"], session["member_token"])
        self.last_heartbeat = time.monotonic()
        self.config_path: Path | None = None
        self.d1_path: Path | None = None
        self.last_gate = "P0_SIDE_READY"
        self.intent: dict | None = None
        self.run_context: dict | None = None

    @property
    def relay_role(self) -> str:
        return "creator" if self.session["switch_role"] == "a_room_joiner" else "finder"

    def _versioned(self, operation) -> dict:
        """Retry only the relay's explicit optimistic-version conflict."""
        for attempt in range(8):
            current = self.relay.room(
                self.session["room_id"], self.session["member_token"])
            try:
                result = operation(current)
            except RelayError as error:
                if error.code != "room_version_conflict" or attempt == 7:
                    raise
                time.sleep(0.05)
                continue
            self.room = result
            return result
        raise AssertionError("unreachable version retry state")

    def _heartbeat(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self.last_heartbeat < RELAY_HEARTBEAT_INTERVAL:
            return False
        self._versioned(
            lambda current: self.relay.room_command(
                self.session["room_id"], self.session["member_token"], "/heartbeat",
                expected_version=current["room_version"],
            )
        )
        self.last_heartbeat = now
        return True

    def _refresh_room(self, *, force_heartbeat: bool = False) -> dict:
        if not self._heartbeat(force=force_heartbeat):
            self.room = self.relay.room(
                self.session["room_id"], self.session["member_token"])
        return self.room

    def _prompt(self, message: str) -> None:
        """Keep the member present while the operator is physically away from this PC."""
        stopped = threading.Event()
        errors: list[Exception] = []

        def keep_alive() -> None:
            while not stopped.wait(RELAY_HEARTBEAT_INTERVAL):
                try:
                    self._heartbeat(force=True)
                except Exception as error:
                    errors.append(error)
                    return

        worker = threading.Thread(target=keep_alive, name="distributed-heartbeat", daemon=True)
        worker.start()
        try:
            input(message)
        finally:
            stopped.set()
            worker.join(timeout=1)
        if errors:
            raise errors[0]
        self._heartbeat(force=True)

    def confirm_pairing(self) -> None:
        """Prove both relay members before allowing any P0 or USB ownership action."""
        expected_seat = "member_a" if self.session["owner"] else "member_b"
        deadline = time.monotonic() + self.timeout
        while True:
            room = self._refresh_room()
            active = _validate_room_identity(
                room, room_id=self.session["room_id"], room_code=self.session["room_code"],
                expected_seat=expected_seat,
            )
            if len(active) == 2 and {item["seat"] for item in active} == {"member_a", "member_b"}:
                break
            if len(active) > 2:
                raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
            if time.monotonic() >= deadline:
                raise SystemExit("DISTRIBUTED_PAIRING_TIMEOUT")
            time.sleep(RELAY_POLL_INTERVAL)
        _status(
            "coordination_paired", test_id=self.session["test_id"],
            role=self.session["switch_role"], usb_attached=False,
        )
        self._prompt(
            "Software pairing is verified and USB is still owned by Windows. "
            "Confirm the other PC also reports coordination_paired, then press Enter to start P0: "
        )
        active = _validate_room_identity(
            self.room, room_id=self.session["room_id"], room_code=self.session["room_code"],
            expected_seat=expected_seat,
        )
        if len(active) != 2 or {item["seat"] for item in active} != {"member_a", "member_b"}:
            raise SystemExit("DISTRIBUTED_PEER_LOST_BEFORE_P0")

    def bind(self, run_id: str, run: dict) -> dict:
        self._refresh_room(force_heartbeat=True)
        member = _local_member(self.room)
        return self.coordinator.bind_authority(
            run_id, room_id=self.session["room_id"], room_version=self.room["room_version"],
            seat=AuthoritySeat(member["seat"]), switch_role=SwitchRole(self.session["switch_role"]),
        )

    @staticmethod
    def _p0_proof(context: dict) -> dict:
        report_path = context["run_root"] / "p0-side-ready.json"
        return {
            "contract_version": "p0-attestation.v2",
            "run_id": context["run_id"],
            "release": context["run"]["identity"]["release"],
            "run_generation": context["run"]["identity"]["run_generation"],
            "stage_generation": context["run"]["identity"]["stage_generation"],
            "adapter_instance_sha256": context["adapter"].instance_sha256,
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        }

    def _validate_attempt(self, room: dict) -> dict:
        attempt = room.get("attempt")
        members = [item for item in room.get("members", []) if item.get("online_state") != "left"]
        local = _local_member(room)
        peer_role = "finder" if self.relay_role == "creator" else "creator"
        roles = {item.get("switch_room_role") for item in members}
        creator = next((item for item in members if item.get("switch_room_role") == "creator"), None)
        if (
            len(members) != 2 or roles != {"creator", "finder"} or
            local.get("switch_room_role") != self.relay_role or
            not isinstance(creator, dict) or not isinstance(attempt, dict) or
            not attempt.get("attempt_id") or attempt.get("role_locked") is not True or
            attempt.get("creator_member_id") != creator.get("member_id") or
            not isinstance(attempt.get("role_lock_version"), int) or
            not isinstance(attempt.get("activation_generation"), int) or
            peer_role not in roles
        ):
            raise P0Error(
                "DISTRIBUTED_ATTEMPT_INVALID", "C0_authority",
                "relay did not lock one complementary current-generation attempt",
            )
        return attempt

    def prepare(self, context: dict) -> dict:
        self.run_context = context
        command_id = self.relay.command_id()
        room = self._versioned(
            lambda current: self.relay.v2_ready(
                self.session["room_id"], self.session["member_token"], {
                    "ready": True, "switch_room_role": self.relay_role,
                    "p0": self._p0_proof(context),
                }, expected_version=current["room_version"], command_id=command_id,
            )
        )
        self.last_heartbeat = time.monotonic()
        deadline = time.monotonic() + self.timeout
        while not isinstance(room.get("attempt"), dict):
            if time.monotonic() >= deadline:
                raise P0Error(
                    "DISTRIBUTED_PEER_READY_TIMEOUT", "C0_authority",
                    "the second P0-qualified PC did not become ready",
                )
            time.sleep(RELAY_POLL_INTERVAL)
            room = self._refresh_room()
        attempt = self._validate_attempt(room)
        self.room = room
        self.coordinator.lock_attempt(
            context["run_id"], attempt_id=attempt["attempt_id"],
            role_lock_version=attempt["role_lock_version"],
        )
        self.config_path = context["run_root"] / "distributed-endpoint-config.json"
        self.d1_path = context["run_root"] / "d1-control-state.json"
        atomic_json(self.config_path, {
            "contract_version": "distributed-endpoint-config.v1",
            "relay_url": self.relay.base_url,
            "room_id": self.session["room_id"],
            "room_code": self.session["room_code"],
            "attempt_id": attempt["attempt_id"],
            "member_token": self.session["member_token"],
            "source_seat": _local_member(room)["seat"],
            "switch_role": self.session["switch_role"],
            "activation_generation": attempt["activation_generation"],
            "run_id": context["run_id"],
            "release": context["run"]["identity"]["release"],
            "stage_generation": context["run"]["identity"]["stage_generation"],
            "launch_nonce": context["launch_nonce"],
            "endpoint_pid": context["p0b"]["wrapper_pid"],
        }, private=True)
        _status(
            "attempt_locked", test_id=self.session["test_id"],
            run_id=context["run_id"], role=self.session["switch_role"],
        )
        return {
            "attempt_id": attempt["attempt_id"],
            "endpoint_config": _wsl_path(self.config_path) if os.name == "nt" else str(self.config_path),
        }

    def _authority_intent(self, room: dict) -> dict | None:
        attempt = room.get("attempt") if isinstance(room, dict) else None
        state = attempt.get("d") if isinstance(attempt, dict) else None
        if not isinstance(state, dict) or attempt.get("phase") not in {"closing", *TERMINAL_ATTEMPTS}:
            return None
        return {
            "contract_version": "d-closing-intent.v1",
            "attempt_id": attempt["attempt_id"],
            "activation_generation": state["activation_generation"],
            "outcome": state["outcome"],
            "primary_failure_code": state.get("primary_failure_code"),
            "last_passed_gate": state["last_passed_gate"],
        }

    def _begin_d(self, outcome: str, *, code: str | None = None) -> dict:
        if self.intent is not None:
            return self.intent
        command_id = self.relay.command_id()
        for retry in range(8):
            room = self._refresh_room(force_heartbeat=True)
            authority_intent = self._authority_intent(room)
            if authority_intent is not None:
                self.intent = authority_intent
                return authority_intent
            attempt = room["attempt"]
            intent = {
                "contract_version": "d-closing-intent.v1",
                "attempt_id": attempt["attempt_id"],
                "activation_generation": attempt["activation_generation"],
                "outcome": outcome,
                "primary_failure_code": code if outcome == "failed" else None,
                "last_passed_gate": self.last_gate,
            }
            state = {
                "contract_version": "distributed-d1-control.v1", "schema": 1,
                "run_id": self.run_context["run_id"], "command_id": command_id,
                "expected_room_version": room["room_version"], "intent": intent,
            }
            atomic_json(self.d1_path, state, private=True)
            try:
                self.room = self.relay.begin_distributed_d(
                    self.session["room_id"], attempt["attempt_id"],
                    self.session["member_token"], intent,
                    expected_version=state["expected_room_version"], command_id=command_id,
                )
            except RelayError as error:
                if error.code != "room_version_conflict" or retry == 7:
                    raise
                time.sleep(0.05)
                continue
            self.intent = intent
            _status("d1_recorded", test_id=self.session["test_id"], outcome=outcome)
            return intent
        raise AssertionError("unreachable D1 version retry state")

    def _poll_authority(self) -> dict | None:
        self._refresh_room()
        intent = self._authority_intent(self.room)
        if intent is not None:
            self.intent = intent
        return intent

    def _continue_checkpoint(self, events, event: dict) -> None:
        checkpoint = event.get("checkpoint")
        expected = ROLE_CHECKPOINTS[self.session["switch_role"]]
        if checkpoint != expected or event.get("run_id") != self.run_context["run_id"]:
            raise P0Error(
                "DISTRIBUTED_ENDPOINT_IDENTITY_MISMATCH", self.last_gate,
                "distributed user checkpoint changed run or role identity",
            )
        if checkpoint == "CREATE_SWITCH_ROOM":
            message = (
                "On Switch A, open the trade room as Group Leader and leave it open. "
                "Return to PC A and press Enter to start the bounded room scan: "
            )
        else:
            message = (
                "PC B has prepared the AP path. Press Enter to continue, then use Switch B "
                "to choose Join Group before the association deadline: "
            )
        self._prompt(message)
        events.send({
            "action": "continue_checkpoint", "checkpoint": checkpoint,
            "run_id": self.run_context["run_id"],
        })
        _status(
            "checkpoint_continued", test_id=self.session["test_id"],
            checkpoint=checkpoint,
        )

    def drive(self, context: dict) -> dict:
        self.run_context = context
        events = context["events"]
        action = self.session["action"]
        owner = self.session["owner"]
        threshold = "C_TRADE_COMPLETE" if action in {"end", "close"} else "C_RFU_ACTIVE"
        prompted = False
        deadline = time.monotonic() + self.timeout
        endpoint_report = None
        try:
            while endpoint_report is None:
                event = events.next_event(RELAY_POLL_INTERVAL)
                if event is not None:
                    if event.get("run_id") not in {None, context["run_id"]}:
                        raise P0Error(
                            "DISTRIBUTED_ENDPOINT_IDENTITY_MISMATCH", self.last_gate,
                            "distributed checkpoint changed run identity",
                        )
                    kind = event["event"]
                    if kind in {"a_gate_passed", "b_gate_passed", "c_gate_passed", "c2_gate_passed"}:
                        self.last_gate = str(event["gate"])
                    elif kind == "side_ready":
                        self.last_gate = str(event["gate"])
                        _status("stage", test_id=self.session["test_id"], gate=self.last_gate)
                    elif kind == "bridge_ready":
                        self.last_gate = "C_BRIDGE_READY"
                        _status("stage", test_id=self.session["test_id"], gate=self.last_gate)
                    elif kind == "rfu_active":
                        self.last_gate = "C_RFU_ACTIVE"
                        _status(
                            "stage", test_id=self.session["test_id"], gate=self.last_gate,
                            bidirectional=True,
                        )
                    elif kind == "trade_complete":
                        self.last_gate = "C_TRADE_COMPLETE"
                        _status("stage", test_id=self.session["test_id"], gate=self.last_gate)
                    elif kind == "user_checkpoint":
                        _status(
                            "user_checkpoint", test_id=self.session["test_id"],
                            checkpoint=event.get("checkpoint"),
                        )
                        self._continue_checkpoint(events, event)
                    elif kind == "functional_failed":
                        code = str(event.get("code") or "DISTRIBUTED_ENDPOINT_FAILED")
                        self.last_gate = str(event.get("gate") or self.last_gate)
                        self._begin_d("failed", code=code)
                    elif kind == "d_endpoint_completed":
                        endpoint_report = event.get("report")
                if self.intent is None:
                    peer_intent = self._poll_authority()
                    if peer_intent is not None:
                        self.intent = peer_intent
                    elif owner and self.last_gate == threshold and not prompted:
                        prompted = True
                        self._prompt(
                            f"[{action}] checkpoint reached. Complete the Switch-side action, "
                            "then press Enter to begin ordered D cleanup: "
                        )
                        self._begin_d("completed" if threshold == "C_TRADE_COMPLETE" else "canceled")
                if self.intent is not None and endpoint_report is None:
                    events.send({"action": "closing_intent", "value": self.intent})
                    # The endpoint accepts the intent exactly once; do not send it again.
                    intent_sent = self.intent
                    self.intent = intent_sent
                    while endpoint_report is None:
                        event = events.next_event(max(0.01, min(0.5, deadline - time.monotonic())))
                        self._heartbeat()
                        if event is not None and event.get("event") == "d_endpoint_completed":
                            endpoint_report = event.get("report")
                            break
                        if time.monotonic() >= deadline:
                            raise P0Error(
                                "DISTRIBUTED_D_ENDPOINT_TIMEOUT", "D4_LDN_TEARDOWN",
                                "endpoint D2-D4 did not finish before its deadline",
                            )
                if time.monotonic() >= deadline:
                    raise P0Error(
                        "DISTRIBUTED_RUN_TIMEOUT", self.last_gate,
                        "distributed qualification exceeded its bounded deadline",
                    )
        except Exception as error:
            code = str(getattr(error, "code", "DISTRIBUTED_ENDPOINT_FAILED"))
            if self.intent is None:
                self._begin_d("failed", code=code)
                try:
                    events.send({"action": "closing_intent", "value": self.intent})
                    event = events.wait_for({"d_endpoint_completed"}, 30)
                    endpoint_report = event.get("report")
                except Exception:
                    pass
            frozen = self.intent["outcome"]
            return {
                "outcome": {
                    "completed": FunctionalOutcome.PASSED.value,
                    "canceled": FunctionalOutcome.CANCELED.value,
                    "failed": FunctionalOutcome.FAILED.value,
                }[frozen],
                "code": self.intent["primary_failure_code"],
                "message": (
                    str(getattr(error, "message", error))[:500]
                    if frozen == "failed" else None),
                "last_passed_gate": self.last_gate,
                "endpoint_d_status": (
                    endpoint_report.get("status") if isinstance(endpoint_report, dict) else "missing"),
            }
        outcome = self.intent["outcome"]
        return {
            "outcome": {
                "completed": FunctionalOutcome.PASSED.value,
                "canceled": FunctionalOutcome.CANCELED.value,
                "failed": FunctionalOutcome.FAILED.value,
            }[outcome],
            "code": self.intent["primary_failure_code"],
            "message": (
                "distributed endpoint failed" if outcome == "failed" else None),
            "last_passed_gate": self.intent["last_passed_gate"],
            "endpoint_d_status": (
                endpoint_report.get("status") if isinstance(endpoint_report, dict) else "missing"),
        }

    def _wait_terminal(self, room: dict) -> dict:
        deadline = time.monotonic() + 45
        while (room.get("attempt") or {}).get("phase") not in TERMINAL_ATTEMPTS:
            if time.monotonic() >= deadline:
                raise P0Error(
                    "DISTRIBUTED_D6_TIMEOUT", "D6_TWO_SIDE_BARRIER",
                    "the two-side D6 barrier did not become terminal",
                )
            time.sleep(RELAY_POLL_INTERVAL)
            room = self._refresh_room()
        return room

    def _room_finalize(self) -> str:
        if self.session["owner"]:
            self._prompt(
                "Confirm the other PC reports D11_VERIFIED, then press Enter to close the "
                "one-time qualification room: "
            )
            self._versioned(
                lambda current: self.relay.room_command(
                    self.session["room_id"], self.session["member_token"], "",
                    method="DELETE", expected_version=current["room_version"],
                )
            )
            return "room_closed"
        if self.session["action"] == "leave":
            self._prompt(
                "Confirm PC A reports D11_VERIFIED, then press Enter to perform the Leave action: "
            )
            self._versioned(
                lambda current: self.relay.room_command(
                    self.session["room_id"], self.session["member_token"], "/members/me",
                    method="DELETE", expected_version=current["room_version"],
                )
            )
            return "member_left"
        _status("waiting_for_room_finalization", test_id=self.session["test_id"])
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                self._refresh_room()
            except RelayError as error:
                if error.status == 401:
                    try:
                        self.relay.reconnect_trade_room(
                            self.session["room_id"], self.session["reconnect_token"])
                    except RelayError as reconnect_error:
                        if reconnect_error.status == 410:
                            return "room_closed"
                elif error.status == 410:
                    return "room_closed"
                raise
            time.sleep(RELAY_POLL_INTERVAL)
        raise P0Error(
            "DISTRIBUTED_ROOM_FINALIZE_TIMEOUT", "D11_RELEASE",
            "the owner did not close the one-time qualification room",
        )

    def cleanup(self, context: dict) -> dict:
        run_root = context["run_root"]
        if self.config_path is not None:
            self.config_path.unlink(missing_ok=True)
        probes = WslDProbes(
            distro=self.distro, packaged_python=self.packaged_python,
            private_paths=(self.config_path,) if self.config_path is not None else (),
        )
        if self.intent is None:
            self._begin_d("failed", code="DISTRIBUTED_CONTROL_INTERRUPTED")
        room = self.room
        control = MeasuredD5Control(
            coordinator=self.coordinator, relay=self.relay, run_id=context["run_id"],
            member_token=self.session["member_token"],
            endpoint_report_path=run_root / "d-endpoint-stage.json",
            state_path=run_root / "d5-control-state.json",
            process_probe=probes.process_start_ticks,
            radio_probe=probes.temporary_interfaces,
        )
        acknowledged = control.acknowledge(room)["room"]
        _status("cleanup", test_id=self.session["test_id"], gate="D5_SIDE_QUIESCENT")
        terminal = self._wait_terminal(acknowledged)
        _status("cleanup", test_id=self.session["test_id"], gate="D6_TWO_SIDE_TERMINAL")
        released = LocalDRelease(
            coordinator=self.coordinator, run_id=context["run_id"],
            d5_state_path=run_root / "d5-control-state.json",
            release_state_path=run_root / "d-local-release.json",
            launch_probe=probes.launch, radio_probe=probes.radio,
            usb_lease=context["lease"],
        ).release(terminal)
        if released["status"] != "passed":
            raise P0Error(
                "DISTRIBUTED_LOCAL_RELEASE_FAILED", "D11_RELEASE",
                "local D7-D11 cleanup was not verified",
            )
        _status("cleanup", test_id=self.session["test_id"], gate="D11_VERIFIED")
        room_finalization = self._room_finalize()
        self.session_path.unlink(missing_ok=True)
        if self.d1_path is not None:
            self.d1_path.unlink(missing_ok=True)
        return {
            "d5_side_quiescent": True,
            "d6_two_side_terminal": True,
            "d11_verified": True,
            "shared_cleanup_verified": (
                terminal["attempt"]["d"].get("cleanup_status") == "verified"),
            "room_finalization": room_finalization,
        }

    def abort(self, *, cleanup_verified: bool) -> dict:
        if not cleanup_verified:
            return {"authority_released": False, "session_retained": True}
        try:
            if self.session["owner"]:
                self._versioned(
                    lambda current: self.relay.room_command(
                        self.session["room_id"], self.session["member_token"], "",
                        method="DELETE", expected_version=current["room_version"],
                    )
                )
            else:
                self._versioned(
                    lambda current: self.relay.room_command(
                        self.session["room_id"], self.session["member_token"], "/members/me",
                        method="DELETE", expected_version=current["room_version"],
                    )
                )
        except RelayError as error:
            if error.status != 410:
                return {"authority_released": False, "session_retained": True}
        return {"authority_released": True, "session_retained": True}

    def finalize_abort(self, evidence: dict) -> dict:
        if not isinstance(evidence, dict) or evidence.get("authority_released") is not True:
            return {"session_removed": False}
        self.session_path.unlink(missing_ok=True)
        return {"session_removed": not self.session_path.exists()}


def _room_session(args: argparse.Namespace, release: str, source_sha: str,
                  relay: RelayClient, session_path: Path) -> tuple[dict, str | None]:
    if session_path.exists():
        raise SystemExit("DISTRIBUTED_RECOVERY_REQUIRED")
    if args.command == "create":
        test_id = str(uuid.uuid4())
        peer_role = "b_ap_host" if args.role == "a_room_joiner" else "a_room_joiner"
        credential = relay.create_trade_room({
            "name": "M7 qualification", "visibility": "private",
            "trainer_display_name": "PC A", "game": "FireRed", "language": "English",
            "offering": "", "wanted": "", "note": "",
        }, f"m7-pc-a-{test_id}")
        room, member_token, reconnect_token = _validate_room_credential(credential)
        try:
            active = _validate_room_identity(
                room, room_id=room.get("room_id"), room_code=room.get("room_code"),
                expected_seat="member_a",
            )
            if len(active) != 1 or active[0].get("seat") != "member_a":
                raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
        except SystemExit:
            try:
                relay.room_command(
                    room.get("room_id"), member_token, "", method="DELETE",
                    expected_version=room.get("room_version"),
                )
            except (RelayError, TypeError, ValueError):
                pass
            raise
        invitation_value = {
            "contract_version": INVITATION_CONTRACT, "test_id": test_id,
            "source_sha": source_sha, "release": release,
            "room_id": room["room_id"],
            "room_code": room["room_code"], "action": args.action,
            "owner_role": args.role, "peer_role": peer_role,
        }
        session = {
            "contract_version": SESSION_CONTRACT, "schema": 1, "test_id": test_id,
            "source_sha": source_sha, "release": release, "action": args.action,
            "switch_role": args.role, "owner": True,
            "room_id": room["room_id"],
            "room_code": room["room_code"],
            "member_token": member_token,
            "reconnect_token": reconnect_token,
        }
        atomic_json(session_path, session, private=True)
        return session, _invitation(invitation_value)
    invitation = _decode_invitation(args.invitation)
    if invitation["source_sha"] != source_sha or invitation["release"] != release:
        raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    credential = relay.join_trade_room(
        invitation["room_code"], "PC B", f"m7-pc-b-{invitation['test_id']}")
    room, member_token, reconnect_token = _validate_room_credential(credential)
    try:
        active = _validate_room_identity(
            room, room_id=invitation["room_id"],
            room_code=invitation["room_code"], expected_seat="member_b",
        )
        if len(active) != 2 or {item["seat"] for item in active} != {"member_a", "member_b"}:
            raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    except SystemExit:
        try:
            relay.room_command(
                room["room_id"], member_token, "/members/me",
                method="DELETE", expected_version=room.get("room_version"),
            )
        except RelayError:
            pass
        raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    session = {
        "contract_version": SESSION_CONTRACT, "schema": 1,
        "test_id": invitation["test_id"], "source_sha": source_sha, "release": release,
        "action": invitation["action"], "switch_role": invitation["peer_role"],
        "owner": False, "room_id": room["room_id"],
        "room_code": room["room_code"],
        "member_token": member_token,
        "reconnect_token": reconnect_token,
    }
    atomic_json(session_path, session, private=True)
    return session, None


def _resume_session_room(
    relay: RelayClient, session: dict, session_path: Path,
) -> tuple[dict, dict | None, bool]:
    try:
        room = relay.room(session["room_id"], session["member_token"])
    except RelayError as error:
        if error.status == 410:
            return session, None, True
        if error.status != 401:
            raise
        try:
            credential = relay.reconnect_trade_room(
                session["room_id"], session["reconnect_token"])
        except RelayError as reconnect_error:
            if reconnect_error.status == 410:
                return session, None, True
            raise
        room, member_token, reconnect_token = _validate_room_credential(credential)
        session = {
            **session, "member_token": member_token, "reconnect_token": reconnect_token,
        }
        atomic_json(session_path, session, private=True)
    expected_seat = "member_a" if session["owner"] else "member_b"
    _validate_room_identity(
        room, room_id=session["room_id"], room_code=session["room_code"],
        expected_seat=expected_seat,
    )
    return session, room, False


def _recover_distributed(*, coordinator: ConnectionCoordinator, relay: RelayClient,
                         harness: P0Harness, session: dict, session_path: Path) -> dict:
    """Preserve D ordering while conservatively recovering an interrupted installed endpoint."""
    run = coordinator.snapshot()
    try:
        session, room, room_finalized = _resume_session_room(relay, session, session_path)
    except RelayError as error:
        recovery = None if run is None else harness.recover(run)
        return {
            "status": "failed", "code": error.code,
            "local_recovery": recovery, "room_finalized": False,
        }
    if run is None:
        if not room_finalized:
            assert room is not None
            path = "" if session["owner"] else "/members/me"
            relay.room_command(
                session["room_id"], session["member_token"], path, method="DELETE",
                expected_version=room["room_version"],
            )
        session_path.unlink(missing_ok=True)
        return {
            "status": "recovered", "local_recovery": {"status": "not_required"},
            "room_finalized": True,
        }
    if (
        session["release"] != run["identity"]["release"] or
        session["switch_role"] != run["identity"].get("switch_role") or
        session["room_id"] != run["identity"].get("room_id")
    ):
        raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID")
    if run["cleanup"]["verified"]:
        recovery = {
            "status": "already_recovered", "run_id": run["run_id"],
            "cleanup": run["cleanup"],
        }
    else:
        recovery = None
    if room_finalized:
        if recovery is None:
            recovery = harness.recover(run)
        if recovery["status"] in {"recovered", "already_recovered"}:
            session_path.unlink(missing_ok=True)
            return {"status": "recovered", "local_recovery": recovery, "room_finalized": True}
        return {"status": "failed", "local_recovery": recovery, "room_finalized": True}
    assert room is not None
    attempt = room.get("attempt") or {}
    attempt_id = attempt.get("attempt_id")
    if (
        attempt_id and attempt_id == run["identity"].get("attempt_id") and
        attempt.get("phase") not in TERMINAL_ATTEMPTS and attempt.get("d") is None
    ):
        intent = {
            "contract_version": "d-closing-intent.v1",
            "attempt_id": attempt_id,
            "activation_generation": attempt["activation_generation"],
            "outcome": "failed",
            "primary_failure_code": "DISTRIBUTED_CONTROL_INTERRUPTED",
            "last_passed_gate": run.get("last_passed_gate") or "P0_SIDE_READY",
        }
        room = relay.begin_distributed_d(
            session["room_id"], attempt_id, session["member_token"], intent,
            expected_version=room["room_version"],
        )
    if recovery is None:
        recovery = harness.recover(run)
        if recovery["status"] != "recovered":
            return {"status": "failed", "local_recovery": recovery, "room_finalized": False}

    if attempt_id:
        deadline = time.monotonic() + 45
        while (room.get("attempt") or {}).get("phase") not in TERMINAL_ATTEMPTS:
            if time.monotonic() >= deadline:
                return {
                    "status": "failed", "code": "DISTRIBUTED_D6_TIMEOUT",
                    "local_recovery": recovery, "room_finalized": False,
                }
            time.sleep(RELAY_POLL_INTERVAL)
            room = relay.room(session["room_id"], session["member_token"])
    if session["owner"]:
        if attempt_id:
            input(
                "Confirm the other PC has completed local recovery, then press Enter to close the "
                "interrupted qualification room: "
            )
        relay.room_command(
            session["room_id"], session["member_token"], "", method="DELETE",
            expected_version=room["room_version"],
        )
    else:
        relay.room_command(
            session["room_id"], session["member_token"], "/members/me", method="DELETE",
            expected_version=room["room_version"],
        )
    session_path.unlink(missing_ok=True)
    return {"status": "recovered", "local_recovery": recovery, "room_finalized": True}


def parser() -> argparse.ArgumentParser:
    runtime = default_runs_root().parent / "runtime"
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--state-root", type=Path,
                       default=default_runs_root().parent / "connection-v2-distributed")
    value.add_argument("--selection-file", type=Path,
                       default=runtime / "hardware-selection.json")
    value.add_argument("--runtime-root", default="/opt/switchtrade")
    value.add_argument("--distro", default=os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"))
    value.add_argument("--relay-url", default=os.environ.get(
        "SWITCHTRADE_RELAY_URL", "https://relay.pangyostonefist.org"))
    value.add_argument("--target-channel", type=int, default=6)
    value.add_argument("--timeout", type=float, default=300)
    commands = value.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="PC A creates the one-time private room")
    create.add_argument("--role", choices=sorted(ROLES), required=True)
    create.add_argument("--action", choices=sorted(ACTIONS), required=True)
    join = commands.add_parser("join", help="PC B consumes the one-time invitation")
    join.add_argument("--invitation", required=True)
    commands.add_parser("recover", help="resume exact cleanup after an interrupted run")
    return value


def main() -> None:
    args = parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("DISTRIBUTED_TIMEOUT_INVALID")
    root = Path(__file__).resolve().parents[2]
    source_sha = _source_sha(root)
    release = _installed_release(args.runtime_root, args.distro)
    if release != f"beta-{source_sha[:12]}":
        raise SystemExit("DISTRIBUTED_SOURCE_RUNTIME_MISMATCH")
    relay = RelayClient(args.relay_url)
    health = relay.health()
    if (
        health.get("status") != "ready" or
        health.get("room_contract") != "room-control.v1" or
        "rfu-tunnel.v2" not in health.get("rfu_contracts", [])
    ):
        raise SystemExit("DISTRIBUTED_RELAY_CONTRACT_UNAVAILABLE")
    args.state_root.mkdir(parents=True, exist_ok=True)
    with ConnectionCoordinator(args.state_root / "coordinator", release) as coordinator:
        session_path = args.state_root / "distributed-session.json"
        packaged_python = f"{args.runtime_root.rstrip('/')}/bridge/.venv/bin/python"
        current = coordinator.snapshot()
        if args.command == "recover":
            session = _strict_session(session_path)
            if session["source_sha"] != source_sha or session["release"] != release:
                raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID")
            probes = WslDProbes(distro=args.distro, packaged_python=packaged_python)
            harness = P0Harness(
                coordinator, None, args.state_root / "runs",
                distro=args.distro, runtime_root=args.runtime_root,
                packaged_python=packaged_python, target_channel=args.target_channel,
                release_probes=probes,
            )
            result = _recover_distributed(
                coordinator=coordinator, relay=relay, harness=harness,
                session=session, session_path=session_path,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            raise SystemExit(0 if result["status"] == "recovered" else 2)
        if current is not None and not current["cleanup"]["verified"]:
            raise SystemExit("DISTRIBUTED_RECOVERY_REQUIRED")
        session, invitation = _room_session(args, release, source_sha, relay, session_path)
        if invitation is not None:
            print("ONE_TIME_INVITATION=" + invitation, flush=True)
        lifecycle = DistributedLifecycle(
            coordinator=coordinator, relay=relay, session=session, session_path=session_path,
            distro=args.distro, packaged_python=packaged_python, timeout=args.timeout,
        )
        try:
            lifecycle.confirm_pairing()
        except BaseException:
            evidence = lifecycle.abort(cleanup_verified=True)
            lifecycle.finalize_abort(evidence)
            raise
        _status(
            "preflight_started", test_id=session["test_id"], role=session["switch_role"],
            action=session["action"], source_sha=source_sha, release=release,
        )
        validator = PassiveValidator(
            release=release, selection_file=args.selection_file,
            relay_health=relay.health, relay_websocket_health=relay.websocket_health,
            distro=args.distro, runtime_root=args.runtime_root,
            target_channel=args.target_channel,
            blocking_state_paths=(
                default_runs_root().parent / "runtime" / "production-diagnostic-recovery.json",
            ),
        )
        harness = P0Harness(
            coordinator, validator, args.state_root / "runs",
            distro=args.distro, runtime_root=args.runtime_root,
            packaged_python=packaged_python, target_channel=args.target_channel,
            release_probes=WslDProbes(distro=args.distro, packaged_python=packaged_python),
        )
        result = harness.run_distributed(lifecycle)
    print(json.dumps(result, indent=2, sort_keys=True))
    distributed_cleanup = result.get("cleanup", {}).get("distributed", {})
    passed = (
        result["cleanup_status"] == "verified" and
        result["functional_status"] in {"passed", "canceled"} and
        distributed_cleanup.get("d11_verified") is True and
        distributed_cleanup.get("shared_cleanup_verified") is True
    )
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
