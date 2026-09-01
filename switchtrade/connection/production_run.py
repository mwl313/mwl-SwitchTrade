"""Production adapters for the neutral ABC+D connection executor."""

from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from switchtrade.connection.coordinator import ConnectionCoordinator
from switchtrade.connection.d_probes import WslDProbes
from switchtrade.connection.distributed_harness import (
    DistributedCanceled,
    DistributedLifecycle,
    RELAY_HEARTBEAT_INTERVAL,
    _local_member,
    _validate_room_credential,
    _validate_room_identity,
)
from switchtrade.connection.p0 import P0Error, PassiveValidator, atomic_json
from switchtrade.connection.p0_harness import ConnectionRunExecutor
from switchtrade.connection.service import (
    ConnectionRunServiceError,
    RunControl,
)
from switchtrade.diagnostics import default_runs_root
from switchtrade.relay_client import RelayClient, RelayError


def _safe_room(room: dict, *, owner: bool) -> dict:
    members = [item for item in room.get("members", []) if item.get("online_state") != "left"]
    return {
        "room_id": room.get("room_id"),
        "room_code": room.get("room_code"),
        "name": room.get("name") or "Trade Room",
        "visibility": room.get("visibility") or "private",
        "participants": len(members),
        "membership_role": "owner" if owner else "member",
        "room_version": room.get("room_version"),
    }


class ProductionControlAdapter:
    """Translate lifecycle checkpoints to the service-owned command channel."""

    def __init__(self, control: RunControl, set_action):
        self.control = control
        self.set_action = set_action

    def publish(self, phase: str, *, run_id: str | None = None,
                checkpoint: str | None = None, can_continue: bool = False, **_fields) -> dict:
        if checkpoint is not None and can_continue:
            return {"phase": "awaiting_user", "checkpoint": checkpoint, "run_id": run_id}
        self.control.phase(phase, gate=checkpoint)
        return {"phase": phase, "checkpoint": checkpoint, "run_id": run_id}

    def cancel_requested(self) -> bool:
        action = self.control.termination
        if action is not None:
            self.set_action(action)
        return action is not None

    def raise_if_canceled(self, gate: str) -> None:
        if self.cancel_requested():
            raise DistributedCanceled(gate)

    def await_continue(self, checkpoint: str, *, run_id: str | None,
                       timeout: float, heartbeat=None) -> None:
        if checkpoint == "PAIRING_CONFIRMED":
            return
        if checkpoint == "D_ACTION_CONFIRMED":
            self.set_action(self.control.wait_for_termination(timeout, heartbeat))
            return
        if checkpoint in {"ROOM_FINALIZATION_CONFIRMED", "RECOVERY_FINALIZATION_CONFIRMED"}:
            return
        instructions = {
            "CREATE_SWITCH_ROOM": (
                "On this PC's Switch, open the Wireless Club and create the room as Group Leader."),
            "JOIN_SWITCH_GROUP": (
                "On this PC's Switch, open the Wireless Club and choose Join Group."),
        }.get(checkpoint, "Complete the physical Switch step, then continue.")
        try:
            self.control.await_user(checkpoint, instructions, timeout)
        except ConnectionRunServiceError as error:
            if error.code == "CONNECTION_CANCELED":
                raise DistributedCanceled(checkpoint) from error
            raise

    def begin_cleanup(self, _run_id: str | None) -> None:
        self.control.begin_cleanup()

    def heartbeat(self, gate: str) -> None:
        self.control.heartbeat(gate)

    def gate_passed(self, gate: str) -> None:
        self.control.phase(
            "running", gate=gate, last_passed_gate=gate, peer_state="paired")


class ProductionLifecycle(DistributedLifecycle):
    """Relay authority policy for a normal app run, established only after P0a."""

    def __init__(self, *, coordinator: ConnectionCoordinator, relay: RelayClient,
                 request: dict, run_control: RunControl, root: Path,
                 distro: str, packaged_python: str, runtime_root: str,
                 timeout: float = 300):
        self._coordinator = coordinator
        self._relay = relay
        self.request = request
        self.run_control = run_control
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.authority_path = self.root / "room-authority.private.json"
        self.run_session_path: Path | None = None
        self._distro = distro
        self._packaged_python = packaged_python
        self._runtime_root = runtime_root
        self._timeout = timeout
        self._established = False
        self._production_control = ProductionControlAdapter(run_control, self._set_action)

    def _set_action(self, action: str) -> None:
        if hasattr(self, "session"):
            self.session["action"] = action

    def establish(self, context: dict) -> None:
        """C0.1: create/join authority after P0a and before any USB acquisition."""
        run_id = context["run_id"]
        self.run_session_path = context["run_root"] / "production-room-session.private.json"
        kind = self.request["kind"]
        command_id = self.request.get("authority_command_id") or str(uuid.uuid4())
        client_id = str(self.request.get("client_id") or f"product-{run_id}")[:128]
        if kind == "resume":
            credential = self._read_authority()
            room = self._relay.room(credential["room_id"], credential["member_token"])
            member_token = credential["member_token"]
            reconnect_token = credential["reconnect_token"]
            owner = credential["owner"]
        else:
            if self.authority_path.exists():
                raise P0Error(
                    "PRODUCTION_AUTHORITY_ACTIVE", "C0.1_AUTHORITY",
                    "leave or close the existing room before creating another")
            if kind == "create":
                payload = {
                    "name": str(self.request.get("name") or "Trade Room")[:22],
                    "visibility": str(self.request.get("visibility") or "private"),
                    "trainer_display_name": str(self.request.get("trainer_display_name") or "Trainer")[:20],
                    "game": str(self.request.get("game") or "None"),
                    "language": str(self.request.get("language") or "None"),
                    "offering": str(self.request.get("offering") or "")[:80],
                    "wanted": str(self.request.get("wanted") or "")[:80],
                    "note": str(self.request.get("note") or "")[:120],
                }
                credential = self._relay.create_trade_room(
                    payload, client_id, command_id=command_id)
                owner = True
            elif kind == "join":
                room_code = str(self.request.get("room_code") or "").upper()
                if len(room_code) != 6 or not room_code.isalnum():
                    raise P0Error(
                        "PRODUCTION_ROOM_CODE_INVALID", "C0.1_AUTHORITY",
                        "room code must be six letters or numbers")
                credential = self._relay.join_trade_room(
                    room_code,
                    str(self.request.get("trainer_display_name") or "Trainer")[:20],
                    client_id, command_id=command_id)
                owner = False
            else:
                listing_id = str(self.request.get("listing_id") or "")
                if not listing_id or len(listing_id) > 128:
                    raise P0Error(
                        "PRODUCTION_LISTING_ID_INVALID", "C0.1_AUTHORITY",
                        "public room identity is invalid")
                credential = self._relay.join_public_trade_room(
                    listing_id,
                    str(self.request.get("trainer_display_name") or "Trainer")[:20],
                    client_id, command_id=command_id)
                owner = False
            try:
                room, member_token, reconnect_token = _validate_room_credential(credential)
            except SystemExit as error:
                raise P0Error(
                    "PRODUCTION_AUTHORITY_INVALID", "C0.1_AUTHORITY",
                    "relay returned an invalid room credential") from error

        session = {
            "contract_version": "production-room-session.v1", "schema": 1,
            "test_id": run_id, "release": context["run"]["identity"]["release"],
            "action": "end", "switch_role": None, "owner": owner,
            "room_id": room["room_id"], "room_code": room["room_code"],
            "member_token": member_token, "reconnect_token": reconnect_token,
        }
        atomic_json(self.authority_path, session, private=True)
        atomic_json(self.run_session_path, session, private=True)
        self.run_control.authority(_safe_room(room, owner=owner))

        role = self.request.get("switch_role")
        if role is not None:
            self.run_control.choose_role(role)
        try:
            session["switch_role"] = self.run_control.wait_for_role(self._timeout)
        except ConnectionRunServiceError as error:
            if error.code == "CONNECTION_CANCELED":
                raise DistributedCanceled("C0.1_AUTHORITY") from error
            raise
        atomic_json(self.authority_path, session, private=True)
        atomic_json(self.run_session_path, session, private=True)

        super().__init__(
            coordinator=self._coordinator, relay=self._relay, session=session,
            session_path=self.run_session_path, distro=self._distro,
            packaged_python=self._packaged_python, runtime_root=self._runtime_root,
            control=self._production_control, timeout=self._timeout,
        )
        expected_seat = "member_a" if owner else "member_b"
        deadline = time.monotonic() + self._timeout
        while True:
            self._production_control.raise_if_canceled("C0.1_PAIRING")
            room = self._refresh_room(force_heartbeat=(
                time.monotonic() - self.last_heartbeat >= RELAY_HEARTBEAT_INTERVAL))
            try:
                active = _validate_room_identity(
                    room, room_id=session["room_id"], room_code=session["room_code"],
                    expected_seat=expected_seat)
            except SystemExit as error:
                raise P0Error(
                    "PRODUCTION_PAIRING_IDENTITY_MISMATCH", "C0.1_PAIRING",
                    "relay room identity changed unexpectedly") from error
            self.run_control.authority(_safe_room(room, owner=owner))
            if len(active) == 2 and {item["seat"] for item in active} == {"member_a", "member_b"}:
                break
            if len(active) > 2:
                raise P0Error(
                    "PRODUCTION_PAIRING_IDENTITY_MISMATCH", "C0.1_PAIRING",
                    "relay room membership changed unexpectedly")
            if time.monotonic() >= deadline:
                raise P0Error(
                    "PRODUCTION_PAIRING_TIMEOUT", "C0.1_PAIRING",
                    "the complementary PC did not join before the deadline")
            time.sleep(0.5)
        self._established = True
        self.run_control.phase(
            "running", gate="C0.1_AUTHORITY_BOUND",
            last_passed_gate="C0.1_AUTHORITY_BOUND", peer_state="paired")

    def _room_finalize(self) -> str:
        action = self.run_control.termination or self.session.get("action") or "end"
        self.session["action"] = action
        if action == "close" and self.session["owner"]:
            self._versioned(lambda current: self.relay.room_command(
                self.session["room_id"], self.session["member_token"], "",
                method="DELETE", expected_version=current["room_version"]))
            self.authority_path.unlink(missing_ok=True)
            return "room_closed"
        if action == "leave" and not self.session["owner"]:
            self._versioned(lambda current: self.relay.room_command(
                self.session["room_id"], self.session["member_token"], "/members/me",
                method="DELETE", expected_version=current["room_version"]))
            self.authority_path.unlink(missing_ok=True)
            return "member_left"
        self._versioned(lambda current: self.relay.v2_ready(
            self.session["room_id"], self.session["member_token"], {"ready": False},
            expected_version=current["room_version"]))
        return "room_retained"

    def endpoint_started(self, event: dict) -> None:
        self.run_control.mark_endpoint_started({
            "pid": event["endpoint_pid"],
            "start_ticks": event["process_start_ticks"],
            "launch_nonce": event["launch_nonce"],
            "attempt_id": self.room["attempt"]["attempt_id"],
        })

    def abort(self, *, cleanup_verified: bool) -> dict:
        if not cleanup_verified:
            return {"authority_released": False, "session_retained": True}
        if not self._established:
            return {"authority_released": True, "session_retained": self.authority_path.exists()}
        self._set_action(self.run_control.termination or "stop")
        try:
            self._room_finalize()
            return {"authority_released": True, "session_retained": self.authority_path.exists()}
        except RelayError:
            return {"authority_released": False, "session_retained": True}

    def finalize_abort(self, evidence: dict) -> dict:
        if evidence.get("authority_released") is not True:
            return {"session_removed": False}
        if self.run_session_path is not None:
            self.run_session_path.unlink(missing_ok=True)
        return {"session_removed": self.run_session_path is None or not self.run_session_path.exists()}

    def _read_authority(self) -> dict:
        try:
            value = json.loads(self.authority_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise P0Error(
                "PRODUCTION_AUTHORITY_INVALID", "C0.1_AUTHORITY",
                "saved room authority is missing or invalid") from error
        required = {"room_id", "room_code", "member_token", "reconnect_token", "owner"}
        if not isinstance(value, dict) or any(value.get(name) is None for name in required):
            raise P0Error(
                "PRODUCTION_AUTHORITY_INVALID", "C0.1_AUTHORITY",
                "saved room authority is missing or invalid")
        return value


class ProductionRunner:
    """Build the proven P0/ABC+D executor for a headless production request."""

    def __init__(self, *, root: str | Path, release: str, relay: RelayClient,
                 selection_file: str | Path, distro: str = "SwitchTrade",
                 runtime_root: str = "/opt/switchtrade", target_channel: int = 6,
                 timeout: float = 300, evidence_root: str | Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.release = release
        self.relay = relay
        self.selection_file = Path(selection_file)
        self.distro = distro
        self.runtime_root = runtime_root
        self.packaged_python = f"{runtime_root.rstrip('/')}/bridge/.venv/bin/python"
        self.target_channel = target_channel
        self.timeout = timeout
        self.evidence_root = Path(evidence_root) if evidence_root else self.root / "evidence"
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.coordinator = ConnectionCoordinator(self.root / "coordinator", release)

    def __call__(self, run_id: str, request: dict, control: RunControl) -> dict:
        def relay_health() -> dict:
            health = self.relay.health()
            if "rfu-tunnel.v2" not in health.get("rfu_contracts", []):
                raise P0Error(
                    "P0_RELAY_CONTRACT_MISMATCH", "P0a_relay",
                    "relay does not advertise the production RFU v2 contract")
            return health

        validator = PassiveValidator(
            release=self.release, selection_file=self.selection_file,
            relay_health=relay_health,
            relay_websocket_health=self.relay.websocket_health,
            distro=self.distro, runtime_root=self.runtime_root,
            packaged_python=self.packaged_python, target_channel=self.target_channel,
            blocking_state_paths=(
                default_runs_root().parent / "runtime" / "production-diagnostic-recovery.json",
            ),
        )
        lifecycle = ProductionLifecycle(
            coordinator=self.coordinator, relay=self.relay, request=request,
            run_control=control, root=self.root, distro=self.distro,
            packaged_python=self.packaged_python, runtime_root=self.runtime_root,
            timeout=self.timeout,
        )
        executor = ConnectionRunExecutor(
            self.coordinator, validator, self.evidence_root / "connection-runs",
            distro=self.distro, runtime_root=self.runtime_root,
            packaged_python=self.packaged_python, target_channel=self.target_channel,
            release_probes=WslDProbes(
                distro=self.distro, packaged_python=self.packaged_python,
                runtime_root=self.runtime_root),
            cancel_probe=lambda: control.termination is not None,
        )
        return executor.run_distributed(lifecycle, run_id=run_id)

    def recover(self, _service_record: dict) -> dict:
        try:
            current = self.coordinator.snapshot()
            if current is None:
                result = {"status": "not_required"}
            else:
                executor = ConnectionRunExecutor(
                    self.coordinator, None, self.evidence_root / "connection-runs",
                    distro=self.distro, runtime_root=self.runtime_root,
                    packaged_python=self.packaged_python, target_channel=self.target_channel,
                    release_probes=WslDProbes(
                        distro=self.distro, packaged_python=self.packaged_python,
                        runtime_root=self.runtime_root),
                )
                result = executor.recover(current)
            if result.get("status") not in {
                    "not_required", "recovered", "already_recovered"}:
                return {**result, "cleanup_verified": False}
            authority = self.root / "room-authority.private.json"
            if authority.exists():
                credential = json.loads(authority.read_text(encoding="utf-8"))
                self.release_authority("close" if credential.get("owner") is True else "leave")
            return {
                **result, "authority_released": not authority.exists(),
                "cleanup_verified": not authority.exists(),
            }
        except (ConnectionRunServiceError, OSError, ValueError) as error:
            return {
                "status": "failed", "cleanup_verified": False,
                "code": getattr(error, "code", "STARTUP_RECOVERY_FAILED"),
            }

    def recover_failed_run(self, _service_record: dict) -> dict:
        """Verify a synchronous runner failure without releasing a retained normal room."""
        try:
            current = self.coordinator.snapshot()
            if current is None:
                return {"status": "not_required", "cleanup_verified": True}
            executor = ConnectionRunExecutor(
                self.coordinator, None, self.evidence_root / "connection-runs",
                distro=self.distro, runtime_root=self.runtime_root,
                packaged_python=self.packaged_python, target_channel=self.target_channel,
                release_probes=WslDProbes(
                    distro=self.distro, packaged_python=self.packaged_python,
                    runtime_root=self.runtime_root),
            )
            result = executor.recover(current)
            return {**result, "cleanup_verified": result.get("status") in {
                "not_required", "recovered", "already_recovered"}}
        except (ConnectionRunServiceError, OSError, ValueError) as error:
            return {
                "status": "failed", "cleanup_verified": False,
                "code": getattr(error, "code", "RUN_RECOVERY_FAILED"),
            }

    def release_authority(self, action: str) -> None:
        """Release a retained room only after the prior run proved D cleanup."""
        lifecycle = ProductionLifecycle(
            coordinator=self.coordinator, relay=self.relay,
            request={"kind": "resume", "switch_role": None},
            run_control=RunControl("authority-release", lambda *_args: None),
            root=self.root, distro=self.distro,
            packaged_python=self.packaged_python, runtime_root=self.runtime_root,
            timeout=self.timeout,
        )
        credential = lifecycle._read_authority()
        owner = credential["owner"] is True
        if (action == "close" and not owner) or (action == "leave" and owner):
            raise ConnectionRunServiceError(
                "AUTHORITY_ACTION_INVALID", "room authority does not permit this action")
        try:
            room = self.relay.room(credential["room_id"], credential["member_token"])
            self.relay.room_command(
                credential["room_id"], credential["member_token"],
                "" if owner else "/members/me", method="DELETE",
                expected_version=room["room_version"],
            )
        except RelayError as error:
            if error.status != 410:
                raise ConnectionRunServiceError(
                    "AUTHORITY_RELEASE_FAILED", "relay room authority was not released") from error
        lifecycle.authority_path.unlink(missing_ok=True)

    def close(self) -> None:
        self.coordinator.close()
