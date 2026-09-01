"""GUI-independent single-PC Switchless C+D qualification harness."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
from typing import Callable

from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.connection.b_fixture import FIXTURE, FIXTURE_SHA256
from switchtrade.connection.c2 import C2Bridge, C2StageError
from switchtrade.connection.c_stage import CStage, CStageError
from switchtrade.connection.p0 import atomic_json
from switchtrade.connection.p0 import P0Error, UsbLease
from switchtrade.connection.p0_harness import (
    P0Harness, WorkerEvents, _default_worker_factory, _worker_command, _wsl_path,
)
from switchtrade.connection.dual_adapter_radio import (
    DualRadioOwner, WslExactUsb, requested_adapter_pair, usbipd_inventory,
)
from switchtrade.relay_client import RelayClient, RelayError
from switchtrade.tunnel_client_v2 import TunnelClientV2


WORKER_CONTRACT = "single-pc-switchless-cd-worker.v1"
COMMAND_CONTRACT = "single-pc-switchless-cd-command.v1"
REPORT_CONTRACT = "single-pc-switchless-cd-q2.v1"
RADIO_REPORT_CONTRACT = "single-pc-switchless-cd-q3.v1"
INTEGRATED_REPORT_CONTRACT = "single-pc-switchless-cd-q4.v1"
MODULE_NAME = "switchtrade.connection.dual_adapter_cd_harness"
AUTHORITY_SUCCESS_OUTCOME = "canceled"
POLL_INTERVAL = 0.05
WORKER_TIMEOUT = 20.0


class SwitchlessHarnessError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


def _hash(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SwitchlessHarnessError(
            "CD_STATE_UNAVAILABLE", "Q2_CONTROL", "state is unavailable",
        ) from error
    if not isinstance(value, dict):
        raise SwitchlessHarnessError(
            "CD_STATE_INVALID", "Q2_CONTROL", "state is invalid",
        )
    return value


def _failure(error: BaseException, fallback_gate: str) -> dict:
    return {
        "code": str(getattr(error, "code", "CD_WORKER_FAILED"))[:96],
        "gate": str(getattr(error, "gate", fallback_gate))[:96],
        "message": type(error).__name__,
        "detail_sha256": _hash(str(error)),
    }


def _worker_config(path: Path) -> dict:
    value = _read_json(path)
    required = {
        "contract_version", "relay_url", "room_code", "attempt_id", "source_seat",
        "switch_role", "member_token", "run_id", "stage_generation", "launch_nonce",
        "activation_generation", "local_payload", "peer_payload_sha256", "status_file",
        "command_file",
    }
    if set(value) != required or value.get("contract_version") != WORKER_CONTRACT:
        raise SwitchlessHarnessError(
            "CD_WORKER_CONFIG_INVALID", "Q2_WORKER_START", "worker config is incompatible",
        )
    try:
        uuid.UUID(str(value["run_id"]))
        payload = base64.b64decode(value["local_payload"], validate=True)
    except (TypeError, ValueError) as error:
        raise SwitchlessHarnessError(
            "CD_WORKER_CONFIG_INVALID", "Q2_WORKER_START", "worker identity is invalid",
        ) from error
    if (
        value["source_seat"] not in {"member_a", "member_b"} or
        value["switch_role"] not in {"a_room_joiner", "b_ap_host"} or
        not isinstance(value["member_token"], str) or not value["member_token"] or
        not isinstance(value["stage_generation"], int) or value["stage_generation"] < 1 or
        not isinstance(value["activation_generation"], int) or
        value["activation_generation"] < 1 or
        not 32 <= len(str(value["launch_nonce"])) <= 128 or
        len(payload) != 32 or
        not isinstance(value["peer_payload_sha256"], str) or
        len(value["peer_payload_sha256"]) != 64
    ):
        raise SwitchlessHarnessError(
            "CD_WORKER_CONFIG_INVALID", "Q2_WORKER_START", "worker config is invalid",
        )
    value["local_payload_bytes"] = payload
    return value


class _WorkerStatus:
    def __init__(self, path: Path, config: dict):
        self.path = path
        self.config = config
        self.revision = 0

    def write(self, phase: str, gate: str | None = None, *, evidence: dict | None = None,
              failure: dict | None = None) -> None:
        self.revision += 1
        atomic_json(self.path, {
            "contract_version": WORKER_CONTRACT,
            "run_id": self.config["run_id"],
            "attempt_id": self.config["attempt_id"],
            "source_seat": self.config["source_seat"],
            "switch_role": self.config["switch_role"],
            "pid": os.getpid(),
            "revision": self.revision,
            "phase": phase,
            "last_passed_gate": gate,
            "evidence": evidence or {},
            "failure": failure,
        })


def _command(config: dict) -> str:
    path = Path(config["command_file"])
    if not path.exists():
        return "wait"
    value = _read_json(path)
    if (
        value.get("contract_version") != COMMAND_CONTRACT or
        value.get("run_id") != config["run_id"] or
        value.get("attempt_id") != config["attempt_id"] or
        value.get("action") not in {"wait", "activate", "close", "cancel"}
    ):
        raise SwitchlessHarnessError(
            "CD_COMMAND_INVALID", "Q2_CONTROL", "worker command identity is invalid",
        )
    return value["action"]


def _worker(config_path: Path) -> int:
    try:
        config = _worker_config(config_path)
    except BaseException:
        return 2
    status = _WorkerStatus(Path(config["status_file"]), config)
    status.write("starting")
    client = TunnelClientV2(
        config["relay_url"], config["room_code"], config["attempt_id"],
        config["source_seat"], config["member_token"],
        run_id=config["run_id"], stage_generation=config["stage_generation"],
        launch_nonce=config["launch_nonce"], endpoint_pid=os.getpid(),
        expected_advertisement_hash=(
            FIXTURE_SHA256 if config["switch_role"] == "b_ap_host" else None
        ),
    )
    try:
        stage = CStage(
            config["run_id"], config["attempt_id"], config["source_seat"],
            config["switch_role"], client,
        )
        stage.connect(WORKER_TIMEOUT)
        status.write("c0_ready", "C0_DATA_PLANE_PROVEN")
        if config["switch_role"] == "a_room_joiner":
            if stage.publish_advertisement(FIXTURE) != FIXTURE_SHA256:
                raise SwitchlessHarnessError(
                    "CD_FIXTURE_CHANGED", "C1_ADVERTISEMENT_DELIVERED",
                    "fixture hash changed",
                )
            status.write("c1_sent", "C1_ADVERTISEMENT_DELIVERED", evidence={
                "advertisement_sha256": FIXTURE_SHA256,
            })
        else:
            payload, digest = stage.receive_advertisement_payload(WORKER_TIMEOUT)
            if payload != FIXTURE or digest != FIXTURE_SHA256:
                raise SwitchlessHarnessError(
                    "CD_FIXTURE_CHANGED", "C1_ADVERTISEMENT_DELIVERED",
                    "received fixture is invalid",
                )
            status.write("c1_received", "C1_ADVERTISEMENT_DELIVERED", evidence={
                "advertisement_sha256": digest,
            })

        bridge = C2Bridge(
            config["run_id"], config["attempt_id"], config["source_seat"],
            config["switch_role"], client,
            activation_generation=config["activation_generation"],
            advertisement_sha256=FIXTURE_SHA256,
        )
        bridge.send_rfu(config["local_payload_bytes"], flags=0x01)
        status.write("awaiting_activation", "C1_ADVERTISEMENT_DELIVERED", evidence={
            "queued_local_frames": 1,
        })
        deadline = time.monotonic() + WORKER_TIMEOUT
        while _command(config) == "wait":
            bridge.pump()
            if bridge.connected.is_set():
                raise SwitchlessHarnessError(
                    "CD_BARRIER_EARLY", "C_BRIDGE_READY",
                    "bridge activated before local command",
                )
            if time.monotonic() >= deadline:
                raise SwitchlessHarnessError(
                    "CD_ACTIVATION_TIMEOUT", "C_LOCAL_SIDE_READY",
                    "activation command timed out",
                )
            time.sleep(POLL_INTERVAL)
        action = _command(config)
        if action in {"close", "cancel"}:
            raise SwitchlessHarnessError(
                "CD_WORKER_CANCELED", "C_LOCAL_SIDE_READY", "worker was canceled",
            )
        bridge.mark_local_ready("A_READY" if config["switch_role"] == "a_room_joiner" else "B_READY")
        status.write("local_ready", "C_LOCAL_SIDE_READY")
        if not bridge.wait_bridge(WORKER_TIMEOUT):
            raise SwitchlessHarnessError(
                "CD_BRIDGE_TIMEOUT", "C_BRIDGE_READY", "C2 barrier timed out",
            )
        status.write("bridge_ready", "C_BRIDGE_READY")

        received_hash = None
        deadline = time.monotonic() + WORKER_TIMEOUT
        while time.monotonic() < deadline and received_hash is None:
            for frame in bridge.poll():
                received_hash = _hash(frame.payload)
                if received_hash != config["peer_payload_sha256"]:
                    raise SwitchlessHarnessError(
                        "CD_SYNTHETIC_PAYLOAD_MISMATCH", "C_SYNTHETIC_RFU_PROVEN",
                        "peer payload hash mismatched",
                    )
            time.sleep(POLL_INTERVAL)
        if received_hash is None or not bridge.wait_rfu_active(WORKER_TIMEOUT):
            raise SwitchlessHarnessError(
                "CD_SYNTHETIC_RFU_TIMEOUT", "C_SYNTHETIC_RFU_PROVEN",
                "synthetic RFU proof timed out",
            )
        status.write("rfu_proven", "C_SYNTHETIC_RFU_PROVEN", evidence={
            "sent_sha256": _hash(config["local_payload_bytes"]),
            "received_sha256": received_hash,
            "queued_local_peak": bridge.stats["queued_local_peak"],
            "activation_count": bridge.stats["activation_count"],
        })

        deadline = time.monotonic() + WORKER_TIMEOUT
        while _command(config) not in {"close", "cancel"}:
            bridge.pump()
            if time.monotonic() >= deadline:
                raise SwitchlessHarnessError(
                    "CD_CLOSE_TIMEOUT", "D1_CLOSING_INTENT", "close command timed out",
                )
            time.sleep(POLL_INTERVAL)
        drain = bridge.finish_drain("completed")
        bridge.stop_transport()
        status.write("quiescent", "D5_SIDE_QUIESCENT", evidence={
            "transport_exited": True,
            "threads_exited": True,
            "synthetic_boundary_released": True,
            "drain": drain,
            "launch_identity_sha256": launch_identity_hash(
                config["run_id"], config["stage_generation"],
                config["launch_nonce"], os.getpid(),
            ),
        })
        return 0
    except (CStageError, C2StageError, SwitchlessHarnessError, OSError, ValueError) as error:
        client.stop()
        status.write("failed", failure=_failure(error, "Q2_WORKER"))
        return 1


def _p0(run_id: str, label: str, release: str) -> dict:
    return {
        "contract_version": "p0-attestation.v2",
        "run_id": run_id,
        "release": release[:64],
        "run_generation": 1,
        "stage_generation": 1,
        "adapter_instance_sha256": _hash(f"q2-software-{label}"),
        "report_sha256": _hash(f"q2-software-report-{label}"),
    }


def _write_command(side: dict, action: str) -> None:
    atomic_json(Path(side["command_file"]), {
        "contract_version": COMMAND_CONTRACT,
        "run_id": side["run_id"],
        "attempt_id": side["attempt_id"],
        "action": action,
    }, private=True)


def _worker_argv(config_file: Path) -> list[str]:
    return [
        sys.executable, "-B", "-m", MODULE_NAME,
        "worker", "--config", str(config_file),
    ]


def _wait_status(side: dict, process: subprocess.Popen, phases: set[str],
                 timeout: float = WORKER_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    status_file = Path(side["status_file"])
    while time.monotonic() < deadline:
        if status_file.exists():
            status = _read_json(status_file)
            if status.get("run_id") != side["run_id"] or status.get("attempt_id") != side["attempt_id"]:
                raise SwitchlessHarnessError(
                    "CD_STATUS_IDENTITY_MISMATCH", "Q2_CONTROL",
                    "worker status identity mismatched",
                )
            if status.get("phase") == "failed":
                failure = status.get("failure") or {}
                raise SwitchlessHarnessError(
                    str(failure.get("code") or "CD_WORKER_FAILED"),
                    str(failure.get("gate") or "Q2_WORKER"),
                    "worker reported failure",
                )
            if status.get("phase") in phases:
                return status
        if process.poll() is not None:
            raise SwitchlessHarnessError(
                "CD_WORKER_EXITED", "Q2_WORKER", "worker exited before its checkpoint",
            )
        time.sleep(POLL_INTERVAL)
    raise SwitchlessHarnessError(
        "CD_WORKER_TIMEOUT", "Q2_WORKER", "worker checkpoint timed out",
    )


def _side_config(root: Path, label: str, *, relay_url: str, room_code: str,
                 attempt_id: str, token: str, seat: str, role: str,
                 run_id: str, activation_generation: int, local_payload: bytes,
                 peer_payload: bytes) -> dict:
    side_root = root / label
    side_root.mkdir(parents=True, exist_ok=False)
    return {
        "contract_version": WORKER_CONTRACT,
        "relay_url": relay_url,
        "room_code": room_code,
        "attempt_id": attempt_id,
        "source_seat": seat,
        "switch_role": role,
        "member_token": token,
        "run_id": run_id,
        "stage_generation": 1,
        "launch_nonce": secrets.token_hex(32),
        "activation_generation": activation_generation,
        "local_payload": base64.b64encode(local_payload).decode("ascii"),
        "peer_payload_sha256": _hash(peer_payload),
        "status_file": str(side_root / "status.json"),
        "command_file": str(side_root / "command.json"),
    }


def run_software(
    relay_url: str, state_root: Path, *, worker_death: bool = False,
    p0_proofs: tuple[dict, dict] | None = None,
) -> dict:
    """Run Q2 against the real relay; no WSL, USB, radio, or Switch path is imported."""
    state_root = Path(state_root).resolve()
    state_root.mkdir(parents=True, exist_ok=False)
    if p0_proofs is not None:
        if (
            not isinstance(p0_proofs, tuple) or len(p0_proofs) != 2 or
            any(
                not isinstance(item, dict) or
                item.get("contract_version") != "p0-attestation.v2" or
                not isinstance(item.get("run_id"), str) or
                not isinstance(item.get("adapter_instance_sha256"), str) or
                not isinstance(item.get("report_sha256"), str)
                for item in p0_proofs
            ) or
            p0_proofs[0]["run_id"] == p0_proofs[1]["run_id"] or
            p0_proofs[0]["adapter_instance_sha256"] == p0_proofs[1]["adapter_instance_sha256"]
        ):
            raise SwitchlessHarnessError(
                "CD_P0_ATTESTATION_INVALID", "Q4_P0_BINDING",
                "integrated P0 attestations are invalid or duplicated",
            )
    relay = RelayClient(relay_url)
    health = relay.health()
    if (
        health.get("status") != "ready" or
        "rfu-tunnel.v2" not in health.get("rfu_contracts", [])
    ):
        raise SwitchlessHarnessError(
            "CD_RELAY_CONTRACT_INVALID", "Q2_PREFLIGHT", "relay contract is not ready",
        )
    recovery_file = state_root / "private-recovery.json"
    report_file = state_root / "q2-software-report.json"
    processes: list[subprocess.Popen] = []
    sides: list[dict] = []
    primary_failure = None
    room_id = owner_token = attempt_id = None
    room_closed = False
    d_started = False
    release = "q2-source-development"
    result = {
        "contract_version": REPORT_CONTRACT,
        "case": "worker_death" if worker_death else "normal",
        "status": "running",
        "functional_status": "pending",
        "cleanup_status": "pending",
        "last_passed_gate": "Q2_PREFLIGHT",
        "fixture_sha256": FIXTURE_SHA256,
        "status_reads_mutation_free": False,
        "one_sided_activation_blocked": False,
        "sides": {},
        "primary_failure": None,
        "cleanup_failure": None,
        "room_closed": False,
        "credentials_removed": False,
    }
    try:
        first = relay.create_trade_room({
            "name": "Switchless C+D Q2", "visibility": "private",
            "trainer_display_name": "Q2 A", "game": "FireRed", "language": "English",
        }, f"q2-{uuid.uuid4()}")
        room_id = first["room"]["room_id"]
        owner_token = first["member_token"]
        atomic_json(recovery_file, {
            "schema": 1, "room_id": room_id, "room_code": first["room"]["room_code"],
            "owner_token": owner_token, "member_tokens": [owner_token],
        }, private=True)
        second = relay.join_trade_room(
            first["room"]["room_code"], "Q2 B", f"q2-{uuid.uuid4()}",
        )
        atomic_json(recovery_file, {
            "schema": 1, "room_id": room_id, "room_code": first["room"]["room_code"],
            "owner_token": owner_token,
            "member_tokens": [owner_token, second["member_token"]],
        }, private=True)
        proofs = p0_proofs or (
            _p0(str(uuid.uuid4()), "a", release),
            _p0(str(uuid.uuid4()), "b", release),
        )
        room = relay.room(room_id, owner_token)
        room = relay.v2_ready(room_id, owner_token, {
            "ready": True, "switch_room_role": "creator", "p0": proofs[0],
        }, expected_version=room["room_version"])
        room = relay.room(room_id, second["member_token"])
        room = relay.v2_ready(room_id, second["member_token"], {
            "ready": True, "switch_room_role": "finder", "p0": proofs[1],
        }, expected_version=room["room_version"])
        attempt = room.get("attempt") or {}
        attempt_id = attempt.get("attempt_id")
        activation_generation = attempt.get("activation_generation")
        if (
            not attempt_id or not attempt.get("role_locked") or
            not room.get("v2_admission", {}).get("attempt_admitted") or
            not isinstance(activation_generation, int) or activation_generation < 1
        ):
            raise SwitchlessHarnessError(
                "CD_ATTEMPT_NOT_ADMITTED", "C0_AUTHENTICATED",
                "relay did not lock one v2 attempt",
            )
        payload_a, payload_b = secrets.token_bytes(32), secrets.token_bytes(32)
        sides = [
            _side_config(
                state_root, "room-side", relay_url=relay.base_url,
                room_code=first["room"]["room_code"], attempt_id=attempt_id,
                token=owner_token, seat="member_a", role="a_room_joiner",
                run_id=proofs[0]["run_id"],
                activation_generation=activation_generation, local_payload=payload_a,
                peer_payload=payload_b,
            ),
            _side_config(
                state_root, "ap-side", relay_url=relay.base_url,
                room_code=first["room"]["room_code"], attempt_id=attempt_id,
                token=second["member_token"], seat="member_b", role="b_ap_host",
                run_id=proofs[1]["run_id"],
                activation_generation=activation_generation, local_payload=payload_b,
                peer_payload=payload_a,
            ),
        ]
        for side in sides:
            config_file = Path(side["status_file"]).parent / "private-config.json"
            atomic_json(config_file, side, private=True)
            output = (config_file.parent / "worker.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                _worker_argv(config_file),
                cwd=Path(__file__).resolve().parents[2], stdout=output,
                stderr=subprocess.STDOUT, text=True,
            )
            output.close()
            processes.append(process)
        stable = [
            _wait_status(side, process, {"awaiting_activation"})
            for side, process in zip(sides, processes)
        ]
        snapshots = [Path(side["status_file"]).read_bytes() for side in sides]
        for _ in range(20):
            if snapshots != [Path(side["status_file"]).read_bytes() for side in sides]:
                raise SwitchlessHarnessError(
                    "CD_STATUS_MUTATED", "Q2_STATUS", "read-only status changed worker state",
                )
        result["status_reads_mutation_free"] = True
        result["last_passed_gate"] = "C1_ADVERTISEMENT_DELIVERED"

        if worker_death:
            processes[1].terminate()
            processes[1].wait(5)
            raise SwitchlessHarnessError(
                "CD_WORKER_EXITED", "Q2_PROCESS_DEATH", "injected worker death was observed",
            )

        _write_command(sides[0], "activate")
        _wait_status(sides[0], processes[0], {"local_ready"})
        time.sleep(0.25)
        other = _read_json(Path(sides[1]["status_file"]))
        first_now = _read_json(Path(sides[0]["status_file"]))
        if other.get("phase") != "awaiting_activation" or first_now.get("phase") != "local_ready":
            raise SwitchlessHarnessError(
                "CD_BARRIER_EARLY", "C_BRIDGE_READY", "one-sided activation was not blocked",
            )
        result["one_sided_activation_blocked"] = True
        _write_command(sides[1], "activate")
        final_statuses = [
            _wait_status(side, process, {"rfu_proven"})
            for side, process in zip(sides, processes)
        ]
        result["last_passed_gate"] = "C_SYNTHETIC_RFU_PROVEN"

        room = relay.room(room_id, owner_token)
        room = relay.begin_distributed_d(
            room_id, attempt_id, owner_token, {
                "contract_version": "d-closing-intent.v1",
                "attempt_id": attempt_id,
                "activation_generation": activation_generation,
                "outcome": AUTHORITY_SUCCESS_OUTCOME,
                "primary_failure_code": None,
                "last_passed_gate": "C_SYNTHETIC_RFU_PROVEN",
            }, expected_version=room["room_version"],
        )
        d_started = True
        for side in sides:
            _write_command(side, "close")
        for process in processes:
            process.wait(WORKER_TIMEOUT)
            if process.returncode != 0:
                raise SwitchlessHarnessError(
                    "CD_WORKER_EXITED", "D5_SIDE_QUIESCENT",
                    "worker did not exit cleanly",
                )
        quiescent = [
            _wait_status(side, process, {"quiescent"})
            for side, process in zip(sides, processes)
        ]
        for index, (side, status) in enumerate(zip(sides, quiescent)):
            payload = {
                "contract_version": "d-side-quiescent.v1",
                "attempt_id": attempt_id,
                "activation_generation": activation_generation,
                "source_seat": side["source_seat"],
                "run_id": side["run_id"],
                "stage_generation": side["stage_generation"],
                "launch_identity_sha256": status["evidence"]["launch_identity_sha256"],
                "evidence": {
                    "endpoint_exited": True, "transport_exited": True,
                    "threads_exited": True, "ldn_released": True,
                    "interfaces_absent": True, "forced": False,
                },
            }
            room = relay.acknowledge_distributed_d(
                room_id, attempt_id,
                owner_token if index == 0 else second["member_token"], payload,
                expected_version=room["room_version"],
            )
        if (
            room.get("attempt", {}).get("phase") != AUTHORITY_SUCCESS_OUTCOME or
            room.get("attempt", {}).get("d", {}).get("cleanup_status") != "verified"
        ):
            raise SwitchlessHarnessError(
                "CD_D_BARRIER_FAILED", "D6_TWO_SIDE_TERMINAL",
                "relay D barrier did not verify both workers",
            )
        result["functional_status"] = "passed"
        result["cleanup_status"] = "verified"
        result["status"] = "passed"
        result["sides"] = {
            side["source_seat"]: {
                "run_id": side["run_id"],
                "switch_role": side["switch_role"],
                "pid": status["pid"],
                "last_passed_gate": status["last_passed_gate"],
                "evidence": status["evidence"],
            }
            for side, status in zip(sides, quiescent)
        }
    except (RelayError, SwitchlessHarnessError, OSError, ValueError) as error:
        primary_failure = _failure(error, "Q2_COORDINATOR")
        result["primary_failure"] = primary_failure
        result["functional_status"] = (
            "expected_failure" if worker_death and primary_failure["code"] == "CD_WORKER_EXITED"
            else "failed"
        )
        result["status"] = "failed"
    finally:
        for side in sides:
            try:
                _write_command(side, "close")
            except (OSError, SwitchlessHarnessError):
                pass
        forced = []
        for process in processes:
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(3)
                forced.append(process.pid)
        if room_id and owner_token:
            try:
                room = relay.room(room_id, owner_token)
                if attempt_id and not d_started and room.get("attempt"):
                    activation = room["attempt"].get("activation_generation", 1)
                    room = relay.begin_distributed_d(
                        room_id, attempt_id, owner_token, {
                            "contract_version": "d-closing-intent.v1",
                            "attempt_id": attempt_id,
                            "activation_generation": activation,
                            "outcome": "failed",
                            "primary_failure_code": (
                                primary_failure or {"code": "CD_COORDINATOR_INTERRUPTED"}
                            )["code"],
                            "last_passed_gate": result["last_passed_gate"],
                        }, expected_version=room["room_version"],
                    )
                room = relay.room(room_id, owner_token)
                relay.room_command(
                    room_id, owner_token, "", method="DELETE",
                    expected_version=room["room_version"],
                )
                room_closed = True
            except (RelayError, KeyError, TypeError, ValueError):
                room_closed = False
        room_released = room_id is None or room_closed
        result["room_closed"] = room_released
        processes_absent = not any(process.poll() is None for process in processes)
        credentials_removed = room_id is None and not recovery_file.exists()
        if room_closed and processes_absent:
            try:
                for side in sides:
                    Path(side["command_file"]).unlink(missing_ok=True)
                    (Path(side["status_file"]).parent / "private-config.json").unlink(
                        missing_ok=True,
                    )
                recovery_file.unlink(missing_ok=True)
                credentials_removed = not recovery_file.exists()
            except OSError:
                credentials_removed = False
        result["credentials_removed"] = credentials_removed
        cleanup_verified = (
            room_released and processes_absent and credentials_removed and
            (not forced or worker_death)
        )
        if cleanup_verified:
            result["cleanup_status"] = "verified"
            if worker_death and result["functional_status"] == "expected_failure":
                result["status"] = "passed"
        elif not cleanup_verified:
            result["cleanup_status"] = "failed"
            result["status"] = "failed"
            result["cleanup_failure"] = {
                "code": "CD_Q2_CLEANUP_FAILED",
                "gate": "D7_DIAGNOSTIC_RESOURCES",
                "message": "Q2 resources were not all proven released",
            }
        result["forced_worker_pids"] = forced
        atomic_json(report_file, result)
    return result


def run_radios(
    state_root: Path, *, release: str, distro: str,
    runtime_root: str = "/opt/switchtrade",
    packaged_python: str = "/opt/switchtrade/bridge/.venv/bin/python",
    source_root: Path | None = None,
    while_ready: Callable[[list[dict]], dict] | None = None,
) -> dict:
    """Run bounded Q3 acquisition/P0/reverse-cleanup with no C or Switch path."""
    state_root = Path(state_root).resolve()
    state_root.mkdir(parents=True, exist_ok=False)
    source_root = Path(source_root or Path(__file__).resolve().parents[2]).resolve()
    source_root_wsl = _wsl_path(source_root)
    exact = WslExactUsb(
        distro=distro, runtime_root=runtime_root, packaged_python=packaged_python,
        source_root=source_root_wsl,
    )
    result = {
        "contract_version": (
            INTEGRATED_REPORT_CONTRACT if while_ready is not None
            else RADIO_REPORT_CONTRACT
        ),
        "case": "integrated_cd_normal" if while_ready is not None else "dual_radio_ownership",
        "release": release,
        "status": "running",
        "functional_status": "pending",
        "cleanup_status": "pending",
        "last_passed_gate": "Q3_CREATED",
        "source": {
            "prepare_sha256": _hash((source_root / "scripts" / "wsl-radio-prepare.sh").read_bytes()),
            "owner_sha256": _hash((source_root / "switchtrade" / "connection" / "dual_adapter_radio.py").read_bytes()),
        },
        "ownership": None,
        "sides": [],
        "primary_failure": None,
        "cleanup": None,
        "workload": None,
    }
    owner = None
    workers: list[tuple[WorkerEvents, dict, dict]] = []
    try:
        adapters = requested_adapter_pair(usbipd_inventory())

        def lease_factory(adapter, recovery, resolver):
            return UsbLease(
                adapter, recovery, distro=distro, runtime_root=runtime_root,
                probe=exact.probe, identity_resolver=resolver, deadline=20,
            )

        owner = DualRadioOwner(
            adapters, state_root / "private-radio-state",
            inventory=exact.inventory, probe=exact.probe,
            lease_factory=lease_factory, lock_root=state_root.parent / "locks",
        )
        result["last_passed_gate"] = "Q3_PREFLIGHT"
        result["ownership"] = owner.acquire()
        result["last_passed_gate"] = "Q3_EXACT_LEASES"
        prepare_script = _wsl_path(source_root / "scripts" / "wsl-radio-prepare.sh")
        for index, (adapter, identity) in enumerate(zip(adapters, owner.identities)):
            run = {
                "run_id": str(uuid.uuid4()),
                "identity": {
                    "release": release[:64], "mode": "p0_harness",
                    "run_generation": 1, "stage_generation": 1,
                },
            }
            side_root = state_root / ("room-side" if index == 0 else "ap-side")
            side_root.mkdir()
            report_path = side_root / "p0-side-ready.json"
            command = _worker_command(
                run=run, adapter=adapter, report_path=report_path,
                runtime_root=runtime_root, packaged_python=packaged_python,
                distro=distro, target_channel=6, linux_identity=identity,
                prepare_script=prepare_script,
            )
            process = _default_worker_factory(
                command, side_root / "worker-events.ndjson",
                side_root / "worker.stderr.log",
            )
            events = WorkerEvents(process, side_root / "worker-events.ndjson")
            workers.append((events, run, {"adapter": adapter, "identity": identity}))
            event = events.wait_for({"p0_side_ready"}, 60)
            ready = P0Harness._validate_ready(
                event.get("report"), run, adapter, report_path,
            )
            descendants = exact.descendants(identity)
            if (
                descendants.get("status") != "present" or
                ready["radio"]["netdev"] not in descendants["netdevs"] or
                ready["radio"]["phy"] not in descendants["phys"]
            ):
                raise P0Error(
                    "CD_P0_CROSS_BOUND", "Q3_P0_IDENTITY",
                    "P0 readiness belongs to a different exact USB radio",
                )
            result["sides"].append({
                "side": "room_side" if index == 0 else "ap_side",
                "run_id": run["run_id"],
                "adapter_identity_sha256": adapter.instance_sha256,
                "linux_identity_sha256": _hash(identity),
                "phy": ready["radio"]["phy"],
                "netdev": ready["radio"]["netdev"],
                "driver": ready["radio"]["driver"],
                "rx_passed": ready["radio"]["rx_passed"],
                "runtime": ready["runtime"],
                "p0_attestation": {
                    "contract_version": "p0-attestation.v2",
                    "run_id": run["run_id"],
                    "release": run["identity"]["release"],
                    "run_generation": 1,
                    "stage_generation": 1,
                    "adapter_instance_sha256": adapter.instance_sha256,
                    "report_sha256": _hash(report_path.read_bytes()),
                },
            })
        phys = {side["phy"] for side in result["sides"]}
        netdevs = {side["netdev"] for side in result["sides"]}
        if len(phys) != 2 or len(netdevs) != 2:
            raise P0Error(
                "CD_P0_IDENTITY_DUPLICATE", "Q3_P0_IDENTITY",
                "the two exact radios did not produce distinct PHY and netdev identities",
            )
        result["last_passed_gate"] = "P0_SIDE_READY"
        if while_ready is not None:
            workload = while_ready(result["sides"])
            result["workload"] = workload
            if not isinstance(workload, dict) or workload.get("status") != "passed":
                failure = workload.get("primary_failure") if isinstance(workload, dict) else None
                raise SwitchlessHarnessError(
                    str((failure or {}).get("code") or "CD_INTEGRATED_WORKLOAD_FAILED"),
                    str((failure or {}).get("gate") or "Q4_C_D"),
                    "the integrated C+D workload failed",
                )
            result["last_passed_gate"] = "D6_TWO_SIDE_TERMINAL"
        result["functional_status"] = "passed"
    except (P0Error, SwitchlessHarnessError, OSError, ValueError) as error:
        result["primary_failure"] = _failure(error, "Q3_COORDINATOR")
        result["functional_status"] = "failed"
    finally:
        worker_cleanup = []
        for events, _run, _binding in reversed(workers):
            try:
                worker_cleanup.append(events.stop(endpoint_started=False))
            except BaseException as error:
                worker_cleanup.append({
                    "worker_exited": False,
                    "code": str(getattr(error, "code", "CD_WORKER_CLEANUP_FAILED")),
                })
        radio_cleanup = owner.release() if owner is not None else {"verified": True}
        cleanup_verified = (
            radio_cleanup.get("verified") is True and
            all(item.get("worker_exited") is True and item.get("worker_forced") is False
                for item in worker_cleanup)
        )
        result["cleanup"] = {
            "workers": worker_cleanup,
            "radios": radio_cleanup,
        }
        result["cleanup_status"] = "verified" if cleanup_verified else "failed"
        result["status"] = (
            "passed" if result["functional_status"] == "passed" and cleanup_verified
            else "failed"
        )
        atomic_json(
            state_root / (
                "q4-integrated-report.json" if while_ready is not None
                else "q3-radio-report.json"
            ), result,
        )
    return result


def run_integrated(
    relay_url: str, state_root: Path, *, release: str, distro: str,
    runtime_root: str = "/opt/switchtrade",
    packaged_python: str = "/opt/switchtrade/bridge/.venv/bin/python",
    source_root: Path | None = None,
) -> dict:
    state_root = Path(state_root).resolve()

    def workload(sides: list[dict]) -> dict:
        proofs = tuple(side["p0_attestation"] for side in sides)
        return run_software(
            relay_url, state_root / "software", p0_proofs=proofs,
        )

    return run_radios(
        state_root, release=release, distro=distro, runtime_root=runtime_root,
        packaged_python=packaged_python, source_root=source_root,
        while_ready=workload,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--config", type=Path, required=True)
    software = commands.add_parser("software")
    software.add_argument("--relay-url", default="https://relay.pangyostonefist.org")
    software.add_argument("--state-root", type=Path, required=True)
    software.add_argument("--worker-death", action="store_true")
    radios = commands.add_parser("radios")
    radios.add_argument("--state-root", type=Path, required=True)
    radios.add_argument("--release", required=True)
    radios.add_argument("--distro", required=True)
    radios.add_argument("--runtime-root", default="/opt/switchtrade")
    radios.add_argument(
        "--packaged-python", default="/opt/switchtrade/bridge/.venv/bin/python")
    radios.add_argument("--source-root", type=Path)
    integrated = commands.add_parser("integrated")
    integrated.add_argument("--relay-url", default="https://relay.pangyostonefist.org")
    integrated.add_argument("--state-root", type=Path, required=True)
    integrated.add_argument("--release", required=True)
    integrated.add_argument("--distro", required=True)
    integrated.add_argument("--runtime-root", default="/opt/switchtrade")
    integrated.add_argument(
        "--packaged-python", default="/opt/switchtrade/bridge/.venv/bin/python")
    integrated.add_argument("--source-root", type=Path)
    return value


def main() -> None:
    args = parser().parse_args()
    if args.command == "worker":
        raise SystemExit(_worker(args.config))
    if args.command == "software":
        result = run_software(args.relay_url, args.state_root, worker_death=args.worker_death)
    elif args.command == "radios":
        result = run_radios(
            args.state_root, release=args.release, distro=args.distro,
            runtime_root=args.runtime_root, packaged_python=args.packaged_python,
            source_root=args.source_root,
        )
    else:
        result = run_integrated(
            args.relay_url, args.state_root, release=args.release,
            distro=args.distro, runtime_root=args.runtime_root,
            packaged_python=args.packaged_python, source_root=args.source_root,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
