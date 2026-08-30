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


INVITATION_CONTRACT = "distributed-invitation.v1"
SESSION_CONTRACT = "distributed-session.v1"
ROLES = {"a_room_joiner", "b_ap_host"}
ACTIONS = {"end", "stop", "leave", "close"}
TERMINAL_ATTEMPTS = {"completed", "canceled", "failed"}
SOURCE_SHA = re.compile(r"[0-9a-f]{40}")
RELAY_POLL_INTERVAL = 1.0


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
        "contract_version", "test_id", "source_sha", "release", "room_code",
        "action", "owner_role", "peer_role",
    }
    try:
        uuid.UUID(str(value.get("test_id")))
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
        not isinstance(value.get("room_code"), str) or
        re.fullmatch(r"[A-Za-z0-9]{6}", value["room_code"]) is None
    ):
        raise SystemExit("DISTRIBUTED_INVITATION_INVALID")
    return value


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
    if (
        not isinstance(value, dict) or set(value) != fields or
        value.get("contract_version") != SESSION_CONTRACT or value.get("schema") != 1 or
        value.get("switch_role") not in ROLES or value.get("action") not in ACTIONS or
        not isinstance(value.get("owner"), bool) or
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
        self.config_path: Path | None = None
        self.d1_path: Path | None = None
        self.last_gate = "P0_SIDE_READY"
        self.intent: dict | None = None
        self.run_context: dict | None = None

    @property
    def relay_role(self) -> str:
        return "creator" if self.session["switch_role"] == "a_room_joiner" else "finder"

    def bind(self, run_id: str, run: dict) -> dict:
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
        room = self.relay.room(self.session["room_id"], self.session["member_token"])
        room = self.relay.v2_ready(
            self.session["room_id"], self.session["member_token"], {
                "ready": True, "switch_room_role": self.relay_role,
                "p0": self._p0_proof(context),
            }, expected_version=room["room_version"], command_id=command_id,
        )
        deadline = time.monotonic() + self.timeout
        while not isinstance(room.get("attempt"), dict):
            if time.monotonic() >= deadline:
                raise P0Error(
                    "DISTRIBUTED_PEER_READY_TIMEOUT", "C0_authority",
                    "the second P0-qualified PC did not become ready",
                )
            time.sleep(RELAY_POLL_INTERVAL)
            room = self.relay.room(self.session["room_id"], self.session["member_token"])
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
        attempt = self.room["attempt"]
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
            "run_id": self.run_context["run_id"], "command_id": self.relay.command_id(),
            "expected_room_version": self.room["room_version"], "intent": intent,
        }
        atomic_json(self.d1_path, state, private=True)
        self.room = self.relay.begin_distributed_d(
            self.session["room_id"], attempt["attempt_id"], self.session["member_token"],
            intent, expected_version=state["expected_room_version"],
            command_id=state["command_id"],
        )
        self.intent = intent
        _status("d1_recorded", test_id=self.session["test_id"], outcome=outcome)
        return intent

    def _poll_authority(self) -> dict | None:
        self.room = self.relay.room(self.session["room_id"], self.session["member_token"])
        intent = self._authority_intent(self.room)
        if intent is not None:
            self.intent = intent
        return intent

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
                        input(
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
            room = self.relay.room(self.session["room_id"], self.session["member_token"])
        return room

    def _room_finalize(self) -> str:
        if self.session["owner"]:
            input(
                "Confirm the other PC reports D11_VERIFIED, then press Enter to close the "
                "one-time qualification room: "
            )
            room = self.relay.room(self.session["room_id"], self.session["member_token"])
            self.relay.room_command(
                self.session["room_id"], self.session["member_token"], "",
                method="DELETE", expected_version=room["room_version"],
            )
            return "room_closed"
        if self.session["action"] == "leave":
            input(
                "Confirm PC A reports D11_VERIFIED, then press Enter to perform the Leave action: "
            )
            room = self.relay.room(self.session["room_id"], self.session["member_token"])
            self.relay.room_command(
                self.session["room_id"], self.session["member_token"], "/members/me",
                method="DELETE", expected_version=room["room_version"],
            )
            return "member_left"
        _status("waiting_for_room_finalization", test_id=self.session["test_id"])
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                self.relay.room(self.session["room_id"], self.session["member_token"])
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

    def abort(self) -> None:
        try:
            room = self.relay.room(self.session["room_id"], self.session["member_token"])
            if self.session["owner"]:
                self.relay.room_command(
                    self.session["room_id"], self.session["member_token"], "",
                    method="DELETE", expected_version=room["room_version"],
                )
            else:
                self.relay.room_command(
                    self.session["room_id"], self.session["member_token"], "/members/me",
                    method="DELETE", expected_version=room["room_version"],
                )
        except RelayError as error:
            # An admitted peer may have to wait for the owner to terminalize the shared room.
            if error.status not in {401, 409, 410}:
                raise
            return
        self.session_path.unlink(missing_ok=True)


def _room_session(args: argparse.Namespace, release: str, source_sha: str,
                  relay: RelayClient, session_path: Path) -> tuple[dict, str | None]:
    if session_path.exists():
        raise SystemExit("DISTRIBUTED_RECOVERY_REQUIRED")
    if args.command == "create":
        test_id = str(uuid.uuid4())
        peer_role = "b_ap_host" if args.role == "a_room_joiner" else "a_room_joiner"
        note = f"M7|{source_sha}|{args.action}|{test_id}"
        credential = relay.create_trade_room({
            "name": "M7 qualification", "visibility": "private",
            "trainer_display_name": "PC A", "game": "FireRed", "language": "English",
            "offering": "", "wanted": "", "note": note,
        }, f"m7-pc-a-{test_id}")
        invitation_value = {
            "contract_version": INVITATION_CONTRACT, "test_id": test_id,
            "source_sha": source_sha, "release": release,
            "room_code": credential["room"]["room_code"], "action": args.action,
            "owner_role": args.role, "peer_role": peer_role,
        }
        session = {
            "contract_version": SESSION_CONTRACT, "schema": 1, "test_id": test_id,
            "source_sha": source_sha, "release": release, "action": args.action,
            "switch_role": args.role, "owner": True,
            "room_id": credential["room"]["room_id"],
            "room_code": credential["room"]["room_code"],
            "member_token": credential["member_token"],
            "reconnect_token": credential["reconnect_token"],
        }
        atomic_json(session_path, session, private=True)
        return session, _invitation(invitation_value)
    invitation = _decode_invitation(args.invitation)
    if invitation["source_sha"] != source_sha or invitation["release"] != release:
        raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    credential = relay.join_trade_room(
        invitation["room_code"], "PC B", f"m7-pc-b-{invitation['test_id']}")
    note = credential["room"].get("note")
    expected_note = (
        f"M7|{invitation['source_sha']}|{invitation['action']}|{invitation['test_id']}")
    if note != expected_note:
        try:
            relay.room_command(
                credential["room"]["room_id"], credential["member_token"], "/members/me",
                method="DELETE", expected_version=credential["room"]["room_version"],
            )
        except RelayError:
            pass
        raise SystemExit("DISTRIBUTED_INVITATION_IDENTITY_MISMATCH")
    session = {
        "contract_version": SESSION_CONTRACT, "schema": 1,
        "test_id": invitation["test_id"], "source_sha": source_sha, "release": release,
        "action": invitation["action"], "switch_role": invitation["peer_role"],
        "owner": False, "room_id": credential["room"]["room_id"],
        "room_code": credential["room"]["room_code"],
        "member_token": credential["member_token"],
        "reconnect_token": credential["reconnect_token"],
    }
    atomic_json(session_path, session, private=True)
    return session, None


def _recover_distributed(*, coordinator: ConnectionCoordinator, relay: RelayClient,
                         harness: P0Harness, session: dict, session_path: Path) -> dict:
    """Preserve D ordering while conservatively recovering an interrupted installed endpoint."""
    run = coordinator.snapshot()
    if run is None:
        raise SystemExit("DISTRIBUTED_RECOVERY_NOT_REQUIRED")
    if (
        session["release"] != run["identity"]["release"] or
        session["switch_role"] != run["identity"].get("switch_role") or
        session["room_id"] != run["identity"].get("room_id")
    ):
        raise SystemExit("DISTRIBUTED_RECOVERY_STATE_INVALID")
    room = relay.room(session["room_id"], session["member_token"])
    if run["cleanup"]["verified"]:
        recovery = {
            "status": "already_recovered", "run_id": run["run_id"],
            "cleanup": run["cleanup"],
        }
    else:
        recovery = None
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
        lifecycle = DistributedLifecycle(
            coordinator=coordinator, relay=relay, session=session, session_path=session_path,
            distro=args.distro, packaged_python=packaged_python, timeout=args.timeout,
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
