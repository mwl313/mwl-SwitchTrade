"""One installed-runtime physical A/B endpoint for the distributed qualification CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import re
import signal
import sys
import threading
import time
import uuid

from .a_stage import DirectAStage
from .b_stage import DirectBStage
from .c2 import C2Bridge
from .c_stage import CStage
from .d_stage import EndpointDStage
from .p0 import atomic_json
from .radio_worker import process_start_ticks
from .stage_session import StageSession
from switchtrade.c2_protocol import launch_identity_hash
from switchtrade.party_observer import PassivePartyObserver
from switchtrade.tunnel_client_v2 import TunnelClientV2


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "bridge"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))

from frlgsim import crypto as cryptomod  # noqa: E402
from frlgsim import pia_connect  # noqa: E402
from frlgsim.sim import MS_PER_VBLANK  # noqa: E402
from frlgsim.tunnel import TunnelSim  # noqa: E402


CONFIG_CONTRACT = "distributed-endpoint-config.v1"
ROLES = {"a_room_joiner", "b_ap_host"}
SEATS = {"member_a", "member_b"}
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}")
_GATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")
CHECKPOINTS = {"CREATE_SWITCH_ROOM", "JOIN_SWITCH_GROUP"}
_EMIT_LOCK = threading.Lock()


class _ClosingRequested(Exception):
    """Carry a validated D intent out of a physical user checkpoint."""

    def __init__(self, intent: dict):
        super().__init__("distributed endpoint closing requested")
        self.intent = intent


def _emit(event: str, **value: object) -> None:
    with _EMIT_LOCK:
        print(json.dumps({"event": event, **value}, sort_keys=True, separators=(",", ":")), flush=True)


def _config(path: Path, args: argparse.Namespace) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("distributed endpoint configuration is unreadable") from error
    required = {
        "contract_version", "relay_url", "room_id", "room_code", "attempt_id",
        "member_token", "source_seat", "switch_role", "activation_generation",
        "run_id", "release", "stage_generation", "launch_nonce", "endpoint_pid",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("distributed endpoint configuration contract is invalid")
    if (
        value["contract_version"] != CONFIG_CONTRACT
        or value["run_id"] != args.run_id
        or value["release"] != args.release
        or value["launch_nonce"] != args.launch_nonce
        or value["endpoint_pid"] != os.getpid()
        or value["source_seat"] not in SEATS
        or value["switch_role"] not in ROLES
        or not isinstance(value["stage_generation"], int)
        or isinstance(value["stage_generation"], bool)
        or value["stage_generation"] < 1
        or not isinstance(value["activation_generation"], int)
        or isinstance(value["activation_generation"], bool)
        or value["activation_generation"] < 1
        or not isinstance(value["member_token"], str)
        or not 32 <= len(value["member_token"]) <= 128
    ):
        raise ValueError("distributed endpoint identity does not match its launch")
    try:
        uuid.UUID(str(value["run_id"]))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("distributed endpoint run identity is invalid") from error
    for name in ("relay_url", "room_id", "room_code", "attempt_id"):
        if not isinstance(value[name], str) or not value[name] or len(value[name]) > 512:
            raise ValueError(f"distributed endpoint {name} is invalid")
    if re.fullmatch(r"[A-Za-z0-9]{6}", value["room_code"]) is None:
        raise ValueError("distributed endpoint room code is invalid")
    return value


class _Commands:
    def __init__(self):
        self.values: queue.Queue[dict | BaseException] = queue.Queue(maxsize=4)
        self.thread = threading.Thread(target=self._read, name="distributed-commands", daemon=True)
        self.thread.start()

    def _read(self) -> None:
        try:
            for line in sys.stdin:
                if len(line) > 16_384:
                    raise ValueError("distributed endpoint command exceeds its bound")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("distributed endpoint command is invalid")
                self.values.put(value, timeout=1)
        except BaseException as error:
            try:
                self.values.put(error, timeout=1)
            except queue.Full:
                pass

    def poll(self) -> dict | None:
        try:
            value = self.values.get_nowait()
        except queue.Empty:
            return None
        if isinstance(value, BaseException):
            raise value
        return value

    def wait_checkpoint(self, config: dict, checkpoint: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = TimeoutError("distributed operator checkpoint expired")
                error.code = "DISTRIBUTED_CHECKPOINT_TIMEOUT"
                error.gate = checkpoint
                raise error
            try:
                value = self.values.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if isinstance(value, BaseException):
                raise value
            if value.get("action") == "closing_intent":
                raise _ClosingRequested(_closing_command(value, config))
            _checkpoint_command(value, config, checkpoint)
            return


def _connection(transport: object, role: str):
    our_var = max(2, int.from_bytes(os.urandom(2), "big"))
    if role == "b_ap_host":
        connection = pia_connect.HostConnectionManager(
            our_mac=transport.our_mac,
            our_ip=transport.our_ip,
            network_id=cryptomod.PiaCrypto(transport.ssid).net_id,
            our_var=our_var,
            peer_provider=lambda: (transport.host_mac, transport.host_ip),
            player_name="SwitchTrade",
            log=lambda *_parts: None,
        )
    else:
        connection = pia_connect.ConnectionManager(
            our_mac=transport.our_mac,
            host_mac=transport.host_mac,
            our_ip=transport.our_ip,
            host_ip=transport.host_ip,
            our_var=our_var,
            player_name="SwitchTrade",
            random4=os.urandom(4),
            log=lambda *_parts: None,
        )
    return connection, our_var


def _closing_command(command: dict, config: dict) -> dict:
    if command.get("action") != "closing_intent":
        raise ValueError("distributed endpoint accepts only a closing intent")
    value = command.get("value")
    fields = {
        "contract_version", "attempt_id", "activation_generation", "outcome",
        "primary_failure_code", "last_passed_gate",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("contract_version") != "d-closing-intent.v1"
        or value.get("attempt_id") != config["attempt_id"]
        or value.get("activation_generation") != config["activation_generation"]
        or value.get("outcome") not in {"completed", "canceled", "failed"}
        or not isinstance(value.get("last_passed_gate"), str)
        or _GATE.fullmatch(value["last_passed_gate"]) is None
    ):
        raise ValueError("distributed endpoint closing intent is stale")
    primary = value.get("primary_failure_code")
    if (
        (value["outcome"] == "failed") != isinstance(primary, str)
        or isinstance(primary, str) and _CODE.fullmatch(primary) is None
        or value["outcome"] == "completed" and value["last_passed_gate"] != "C_TRADE_COMPLETE"
    ):
        raise ValueError("distributed endpoint closing outcome is invalid")
    return value


def _checkpoint_command(command: dict, config: dict, checkpoint: str) -> None:
    if (
        checkpoint not in CHECKPOINTS
        or not isinstance(command, dict)
        or set(command) != {"action", "checkpoint", "run_id"}
        or command.get("action") != "continue_checkpoint"
        or command.get("checkpoint") != checkpoint
        or command.get("run_id") != config["run_id"]
    ):
        raise ValueError("distributed endpoint checkpoint command is stale or invalid")


def run(args: argparse.Namespace) -> int:
    if process_start_ticks() != args.process_start_ticks:
        _emit("endpoint_failed", code="DISTRIBUTED_ENDPOINT_IDENTITY_MISMATCH", gate="C0")
        return 2
    config = _config(args.config, args)
    _emit(
        "endpoint_started", run_id=args.run_id, release=args.release,
        launch_nonce=args.launch_nonce, endpoint_pid=os.getpid(),
        process_start_ticks=args.process_start_ticks, endpoint="distributed",
        source_seat=config["source_seat"], switch_role=config["switch_role"],
    )

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    commands = _Commands()
    client = TunnelClientV2(
        config["relay_url"], config["room_code"], config["attempt_id"],
        config["source_seat"], config["member_token"], run_id=args.run_id,
        stage_generation=config["stage_generation"], launch_nonce=args.launch_nonce,
        endpoint_pid=os.getpid(),
    )
    c_stage = CStage(
        args.run_id, config["attempt_id"], config["source_seat"],
        config["switch_role"], client,
        gate_sink=lambda item: _emit("c_gate_passed", run_id=args.run_id, **item),
    )
    session = bridge = simulation = observer = None
    closing_intent = None
    last_gate = "C0_DATA_PLANE_PROVEN"
    d_report = None
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(2):
            _emit(
                "endpoint_heartbeat", run_id=args.run_id,
                attempt_id=config["attempt_id"], launch_nonce=args.launch_nonce,
                endpoint_pid=os.getpid(), process_start_ticks=args.process_start_ticks,
                gate=last_gate,
            )

    heartbeat_thread = threading.Thread(
        target=heartbeat, name="distributed-heartbeat", daemon=True)
    heartbeat_thread.start()
    try:
        c_stage.connect(args.relay_timeout)
        if config["switch_role"] == "a_room_joiner":
            _emit("user_checkpoint", checkpoint="CREATE_SWITCH_ROOM", run_id=args.run_id)
            commands.wait_checkpoint(config, "CREATE_SWITCH_ROOM", args.room_timeout)
            _emit("checkpoint_continued", checkpoint="CREATE_SWITCH_ROOM", run_id=args.run_id)
            stage = DirectAStage(
                run_id=args.run_id, release=args.release, phy=args.phy,
                ifname=args.station_ifname, keys_path=args.keys,
                gate_sink=lambda item: _emit("a_gate_passed", run_id=args.run_id, **item),
                scan_timeout=args.scan_timeout, join_timeout=args.join_timeout,
                hold_seconds=args.hold_seconds,
            )
            session = StageSession(stage, timeout=args.room_timeout).start()
            resources = session.wait_ready()
            advertisement_hash = c_stage.publish_advertisement(resources.advertisement)
            last_gate = "A_READY"
        else:
            _emit("waiting_for_advertisement", run_id=args.run_id)
            advertisement, advertisement_hash = c_stage.receive_advertisement_payload(
                args.room_timeout)

            def b_gate(item: dict) -> None:
                _emit("b_gate_passed", run_id=args.run_id, **item)
                if item["gate"] == "B5_AP_MONITOR_TAP_CREATION":
                    _emit("user_checkpoint", checkpoint="JOIN_SWITCH_GROUP", run_id=args.run_id)
                    commands.wait_checkpoint(config, "JOIN_SWITCH_GROUP", args.room_timeout)
                    _emit(
                        "checkpoint_continued", checkpoint="JOIN_SWITCH_GROUP",
                        run_id=args.run_id,
                    )

            stage = DirectBStage(
                run_id=args.run_id, release=args.release, phy=args.phy,
                keys_path=args.keys, ap_ifname=args.ap_ifname,
                monitor_ifname=args.monitor_ifname, tap_ifname=args.tap_ifname,
                gate_sink=b_gate, channel=args.channel, ap_timeout=args.ap_timeout,
                association_timeout=args.association_timeout,
                control_timeout=args.control_timeout, hold_seconds=args.hold_seconds,
                teardown_timeout=args.teardown_timeout, application_data=advertisement,
            )
            session = StageSession(stage, timeout=args.room_timeout).start()
            resources = session.wait_ready()
            last_gate = "B_READY"

        connection, our_var = _connection(resources.transport, config["switch_role"])
        observer = PassivePartyObserver(
            args.party_state, config["attempt_id"], config["source_seat"],
            log=lambda *_parts: None,
        ).start()
        bridge = C2Bridge(
            args.run_id, config["attempt_id"], config["source_seat"],
            config["switch_role"], client,
            activation_generation=config["activation_generation"],
            advertisement_sha256=advertisement_hash,
            gate_sink=lambda item: _emit("c2_gate_passed", run_id=args.run_id, **item),
        )
        simulation = TunnelSim(
            resources.transport, cryptomod.PiaCrypto(resources.transport.ssid),
            resources.transport.our_ip, resources.transport.host_ip, bridge,
            conn=connection, our_var=our_var,
            parent=config["switch_role"] == "b_ap_host", observer=observer,
            local_seat=config["source_seat"], log=lambda *_parts: None,
        )
        bridge.mark_local_ready(last_gate)
        _emit("side_ready", run_id=args.run_id, gate=last_gate)

        bridge_reported = rfu_reported = trade_reported = False
        period = MS_PER_VBLANK / 1000.0
        deadline = time.monotonic()
        next_observer = deadline
        while closing_intent is None:
            command = commands.poll()
            if command is not None:
                closing_intent = _closing_command(command, config)
                break
            if stopping.is_set():
                raise InterruptedError("distributed endpoint shutdown requested")
            if client.last_error_code:
                raise ConnectionError(client.last_error_code)
            simulation.tick()
            bridge.pump()
            if bridge.connected.is_set() and not bridge_reported:
                bridge_reported = True
                last_gate = "C_BRIDGE_READY"
                _emit("bridge_ready", run_id=args.run_id)
            if bridge.rfu_active.is_set() and not rfu_reported:
                rfu_reported = True
                last_gate = "C_RFU_ACTIVE"
                _emit("rfu_active", run_id=args.run_id, bidirectional=True)
            now = time.monotonic()
            if now >= next_observer:
                snapshot = observer.snapshot()
                if snapshot["commits"] and not trade_reported:
                    trade_reported = True
                    last_gate = "C_TRADE_COMPLETE"
                    _emit("trade_complete", run_id=args.run_id)
                next_observer = now + 0.5
            deadline += period
            time.sleep(max(0, deadline - time.monotonic()))
    except _ClosingRequested as requested:
        closing_intent = requested.intent
    except Exception as error:
        code = getattr(error, "code", "DISTRIBUTED_ENDPOINT_FAILED")
        gate = getattr(error, "last_passed_gate", None) or last_gate
        failure_gate = getattr(error, "gate", None)
        failure = {"failure_gate": str(failure_gate)} if failure_gate is not None else {}
        _emit(
            "functional_failed", run_id=args.run_id, code=str(code), gate=str(gate),
            **failure,
        )
        deadline = time.monotonic() + args.closing_timeout
        while closing_intent is None and time.monotonic() < deadline:
            command = commands.poll()
            if command is not None:
                closing_intent = _closing_command(command, config)
                break
            time.sleep(0.05)
    finally:
        if closing_intent is not None:
            d_report = EndpointDStage(
                run_id=args.run_id, source_seat=config["source_seat"],
                stage_generation=config["stage_generation"],
                launch_identity_sha256=launch_identity_hash(
                    args.run_id, config["stage_generation"], args.launch_nonce, os.getpid()),
                closing_intent=closing_intent, bridge=bridge, simulation=simulation,
                observer=observer, transport=session,
                close_tail_seconds=args.close_tail_timeout,
            ).run()
            atomic_json(args.report, d_report, private=True)
            _emit("d_endpoint_completed", run_id=args.run_id, report=d_report)
        else:
            for resource in (observer, simulation, session, c_stage):
                try:
                    if resource is not None:
                        resource.stop() if hasattr(resource, "stop") else resource.close()
                except Exception:
                    pass
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=3)
    return 0 if d_report is not None and d_report["status"] == "passed" else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--run-id", required=True)
    value.add_argument("--release", required=True)
    value.add_argument("--launch-nonce", required=True)
    value.add_argument("--process-start-ticks", type=int, required=True)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--report", type=Path, required=True)
    value.add_argument("--party-state", type=Path, required=True)
    value.add_argument("--phy", required=True)
    value.add_argument("--station-ifname", required=True)
    value.add_argument("--ap-ifname", required=True)
    value.add_argument("--monitor-ifname", required=True)
    value.add_argument("--tap-ifname", required=True)
    value.add_argument("--keys", type=Path, required=True)
    value.add_argument("--channel", type=int, choices=(1, 6, 11), default=6)
    value.add_argument("--relay-timeout", type=float, default=30)
    value.add_argument("--room-timeout", type=float, default=300)
    value.add_argument("--scan-timeout", type=float, default=8)
    value.add_argument("--join-timeout", type=float, default=15)
    value.add_argument("--ap-timeout", type=float, default=45)
    value.add_argument("--association-timeout", type=float, default=120)
    value.add_argument("--control-timeout", type=float, default=10)
    value.add_argument("--hold-seconds", type=float, default=5)
    value.add_argument("--teardown-timeout", type=float, default=10)
    value.add_argument("--closing-timeout", type=float, default=30)
    value.add_argument("--close-tail-timeout", type=float, default=10)
    return value


def main() -> None:
    raise SystemExit(run(parser().parse_args()))


if __name__ == "__main__":
    main()
