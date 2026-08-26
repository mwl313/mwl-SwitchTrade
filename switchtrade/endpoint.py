"""SwitchTrade RFU endpoint: local LDN/Pia/Reliable, opaque RFU over WebSocket."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import time

from switchtrade.diagnostics import RunLogger
from switchtrade.hardware import require_role, select_profile
from switchtrade.party_observer import PassivePartyObserver
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock
from switchtrade.rfu_tunnel import Kind
from switchtrade.tunnel_client import TunnelClient


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))

from frlgsim import crypto as cryptomod  # noqa: E402
from frlgsim import pia_connect  # noqa: E402
from frlgsim import transport as transportmod  # noqa: E402
from frlgsim.sim import MS_PER_VBLANK  # noqa: E402
from frlgsim.tunnel import TunnelSim  # noqa: E402


SEAT_TO_TUNNEL_ROLE = {"member_a": "host", "member_b": "guest"}
SWITCH_TO_RADIO_ROLE = {"creator": "guest", "finder": "host"}
LEGACY_ROLE_AXES = {
    "host": ("member_a", "creator"),
    "guest": ("member_b", "finder"),
}


def runtime_phy(explicit: str | None = None) -> str:
    """Return the PHY proven by the radio gate; never guess ``phy0``."""
    phy = explicit or os.environ.get("SWITCHTRADE_PHY", "")
    if not phy.startswith("phy") or not phy[3:].isdigit():
        raise RuntimeError(
            "PHY_UNRESOLVED: launch through run-beta-endpoint.sh so the selected adapter can be verified"
        )
    return phy


def cleanup_resources(observer, sim, transport, tunnel, logger) -> list[str]:
    """Run every teardown step and return stable subsystem-labelled failures."""
    errors = []
    for name, cleanup in (
        ("observer", (lambda: observer.stop(clear=True)) if observer is not None else None),
        ("simulation", sim.close if sim is not None else None),
        ("transport", transport.stop if transport is not None else None),
        ("tunnel", tunnel.stop),
    ):
        if cleanup is None:
            continue
        try:
            cleanup()
        except Exception as error:
            errors.append(f"{name}: {error}")
            logger.event("cleanup_failed", level="error", subsystem=name, error=str(error))
    return errors


class StateReporter:
    def __init__(self, path: str | None, defaults: dict | None = None):
        self.path = Path(path).expanduser() if path else None
        self.defaults = defaults or {}

    def write(self, state: str, **fields) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({
            "state": state,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "process_kind": "rfu-endpoint",
            **self.defaults,
            **fields,
        }, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def process_start_ticks() -> int | None:
    """Return Linux's stable process incarnation field when /proc is available."""
    try:
        raw = Path("/proc/self/stat").read_text(encoding="ascii")
        return int(raw[raw.rfind(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class EndpointLog:
    def __init__(self, logger: RunLogger):
        self.logger = logger

    def __call__(self, *parts) -> None:
        message = " ".join(str(part) for part in parts)
        print(message, flush=True)
        self.logger.event("runtime", message=message)

    def info(self, *parts) -> None:
        message = " ".join(str(part) for part in parts)
        print(message, flush=True)
        self.logger.event("milestone", message=message)


def runtime_plan(identity: str, usb_id: str | None = None,
                 *, switch_room_role: str | None = None,
                 allow_experimental_hardware: bool = False) -> dict:
    """Resolve stable tunnel identity separately from temporary radio behavior."""
    if identity in LEGACY_ROLE_AXES:
        tunnel_seat, legacy_switch_role = LEGACY_ROLE_AXES[identity]
        switch_room_role = switch_room_role or legacy_switch_role
    else:
        tunnel_seat = identity
    if tunnel_seat not in SEAT_TO_TUNNEL_ROLE:
        raise ValueError("tunnel seat must be member_a or member_b")
    if switch_room_role not in SWITCH_TO_RADIO_ROLE:
        raise ValueError("Switch room role must be creator or finder")
    radio_role = SWITCH_TO_RADIO_ROLE[switch_room_role]
    profile = require_role(
        select_profile(usb_id), radio_role,
        allow_experimental=allow_experimental_hardware,
    )
    return {
        "tunnel_seat": tunnel_seat,
        "tunnel_role": SEAT_TO_TUNNEL_ROLE[tunnel_seat],
        "switch_room_role": switch_room_role,
        "radio_role": radio_role,
        "usb_id": profile.usb_id,
        "driver_strategy": profile.strategy,
        "allowed_drivers": list(profile.allowed_drivers),
        "profile_status": profile.status,
        "experimental_hardware": profile.status in {"upstream-candidate", "driver-candidate"},
        "hardware_model": profile.model,
        "host_engine": profile.host_engine,
        "allow_experimental_hardware": allow_experimental_hardware,
    }


def _wait_advertisement(tunnel: TunnelClient, timeout: float, log: EndpointLog) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for envelope in tunnel.poll():
            if envelope.kind == Kind.ADVERTISEMENT:
                if not envelope.payload:
                    raise RuntimeError("leader sent an empty room advertisement")
                log.info("Received the leader room advertisement.")
                return envelope.payload
            if envelope.kind == Kind.PEER_CLOSE:
                raise RuntimeError("leader closed the group before advertising a room")
        time.sleep(0.05)
    raise TimeoutError("timed out waiting for the leader room advertisement")


def _connection(transport, role: str, name: str, log: EndpointLog):
    our_var = max(2, int.from_bytes(os.urandom(2), "big"))
    if role == "guest":
        connection = pia_connect.HostConnectionManager(
            our_mac=transport.our_mac or b"\x00" * 6,
            our_ip=transport.our_ip,
            network_id=cryptomod.PiaCrypto(transport.ssid).net_id,
            our_var=our_var,
            peer_provider=lambda: (transport.host_mac, transport.host_ip),
            player_name=name,
            log=log,
        )
    else:
        connection = pia_connect.ConnectionManager(
            our_mac=transport.our_mac or b"\x00" * 6,
            host_mac=transport.host_mac or b"\x00" * 6,
            our_ip=transport.our_ip,
            host_ip=transport.host_ip,
            our_var=our_var,
            player_name=name,
            random4=os.urandom(4),
            log=log,
        )
    return connection, our_var


def run_endpoint(args) -> int:
    identity = args.tunnel_seat or args.role
    if identity is None:
        raise ValueError("--tunnel-seat is required")
    plan = runtime_plan(
        identity, args.usb_id, switch_room_role=args.switch_room_role,
        allow_experimental_hardware=args.allow_experimental_hardware,
    )
    if args.dry_run:
        print(plan)
        return 0

    args.phy = runtime_phy(args.phy)

    state = StateReporter(args.state_file, {
        "session_id": args.session_id,
        "attempt_id": args.attempt_id or args.session_id,
        "wsl_distro": os.environ.get("WSL_DISTRO_NAME"),
        "launch_nonce": args.launch_nonce,
        "process_start_ticks": process_start_ticks(),
    })
    state.write("initializing", radio_checked=False, tunnel_connected=False,
                failure_stage=None, recovery_action=None, **plan)
    logger = RunLogger("rfu-endpoint", args.runs_root, {
        **plan, "session_id": args.session_id, "relay_url": args.relay_url,
        "phy": args.phy, "channel": args.channel,
    })
    log = EndpointLog(logger)
    member_token = None
    if args.member_token_file:
        member_token = Path(args.member_token_file).read_text(encoding="utf-8").strip()
        if len(member_token) < 32:
            raise ValueError("member credential file is invalid")
    tunnel = TunnelClient(
        args.relay_url, args.session_id, plan["tunnel_role"], log=log,
        member_token=member_token, attempt_id=args.attempt_id,
    ).start()
    transport = sim = observer = None
    outcome = "failed"
    failure_stage = "relay"
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        if sim is None:
            raise InterruptedError("endpoint shutdown requested")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        if not tunnel.wait_connected(args.connect_timeout):
            raise TimeoutError(f"relay connection failed: {tunnel.last_error or 'timeout'}")
        state.write("relay_connected", radio_checked=False, tunnel_connected=True,
                    failure_stage=None, recovery_action=None, **plan)
        peer_deadline = time.monotonic() + args.connect_timeout
        while time.monotonic() < peer_deadline and not stopping:
            if any(frame.kind == Kind.PEER_READY for frame in tunnel.poll()):
                break
            time.sleep(0.02)
        else:
            raise TimeoutError("the authenticated RFU peer did not become ready")

        failure_stage = "radio"
        if plan["switch_room_role"] == "creator":
            log.info("Create a Direct Connection room on the leader Switch.")
            transport = transportmod.LiveTransport(
                nickname=args.name, keys_path=args.keys, phyname=args.phy,
                target_bssid=args.target_bssid, log=log,
            )
            transport.start(timeout=args.radio_timeout)
            if not transport.app_data:
                raise RuntimeError("leader room did not expose application_data")
            tunnel.advertise(transport.app_data)
            log.info("Leader room mirrored to the remote endpoint.")
        else:
            advertisement = _wait_advertisement(tunnel, args.room_timeout, log)
            log.info("Opening the mirrored room for the joining Switch.")
            transport = transportmod.HostTransport(
                nickname=args.name, keys_path=args.keys, phyname=args.phy,
                channel=args.channel, application_data=advertisement, log=log,
                host_engine=plan["host_engine"],
            )
            transport.start(timeout=args.radio_timeout)

        state.write("radio_ready", radio_checked=True, tunnel_connected=True,
                    failure_stage=None, recovery_action=None, **plan)

        legacy_radio_role = "host" if plan["switch_room_role"] == "creator" else "guest"
        connection, our_var = _connection(transport, legacy_radio_role, args.name, log)
        crypto = cryptomod.PiaCrypto(transport.ssid)
        party_state = Path(args.party_state_file) if args.party_state_file else (
            Path(args.state_file).with_name("party-state.json") if args.state_file else
            logger.run_dir / "party-state.json"
        )
        observer = PassivePartyObserver(
            party_state, args.attempt_id or args.session_id, plan["tunnel_seat"], log=log,
        ).start()
        sim = TunnelSim(
            transport, crypto, transport.our_ip, transport.host_ip, tunnel,
            conn=connection, our_var=our_var, parent=plan["switch_room_role"] == "finder",
            observer=observer, local_seat=plan["tunnel_seat"],
            capture_path=str(logger.run_dir / "pia.jsonl"), log=log,
        )
        failure_stage = "session"
        log.info("RFU endpoint ready; opaque feature-neutral forwarding active.")
        state.write("session_ready", radio_checked=True, tunnel_connected=True,
                    decoder_status="ready", party_state_file=str(party_state),
                    failure_stage=None, recovery_action=None, **plan)

        period = MS_PER_VBLANK / 1000.0
        deadline = time.monotonic()
        next_report = deadline + 1.0
        while not stopping and not sim.host_disconnected:
            if not tunnel.connected.is_set():
                raise ConnectionError("the authenticated RFU peer disconnected")
            sim.tick()
            deadline += period
            if time.monotonic() >= next_report:
                state.write(
                    "session_ready", radio_checked=True,
                    tunnel_connected=tunnel.connected.is_set(), decoder_status="ready",
                    party_state_file=str(party_state), tunnel_counters=dict(tunnel.stats),
                    rfu_counters={"rx_datagrams": sim.rx_count, "tx_datagrams": sim.tx_count},
                    decoder_counters=dict(observer.stats), failure_stage=None,
                    recovery_action=None, **plan,
                )
                next_report += 1.0
            time.sleep(max(0, deadline - time.monotonic()))
        outcome = "completed"
        state.write("completed", radio_checked=True, tunnel_connected=False,
                    decoder_status="stopped", failure_stage=None,
                    recovery_action=None, **plan)
        return 0
    except InterruptedError:
        outcome = "completed"
        state.write("completed", radio_checked=transport is not None,
                    tunnel_connected=False, decoder_status="stopped",
                    failure_stage=None, recovery_action=None, **plan)
        return 0
    except Exception as error:
        log(f"[endpoint] fatal: {error}")
        logger.event("endpoint_failed", level="error", error=str(error))
        state.write("failed", radio_checked=transport is not None,
                    tunnel_connected=tunnel.connected.is_set(), error=str(error),
                    failure_stage=failure_stage, recovery_action=(
                        "retry" if failure_stage in {"relay", "session"} else "recheck_adapter"
                    ), **plan)
        return 1
    finally:
        cleanup_errors = cleanup_resources(observer, sim, transport, tunnel, logger)
        if cleanup_errors:
            message = "; ".join(cleanup_errors)
            state.write(
                "failed", radio_checked=transport is not None, tunnel_connected=False,
                error_code="ENDPOINT_CLEANUP_FAILED", error=message,
                failure_stage="cleanup", recovery_action="restart_backend", **plan,
            )
            logger.close("failed")
            return 1
        logger.close(outcome)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tunnel-seat", choices=("member_a", "member_b"),
                        help="stable server-assigned tunnel identity")
    parser.add_argument("--switch-room-role", choices=("creator", "finder"),
                        help="per-attempt radio behavior")
    parser.add_argument("--role", choices=("host", "guest"),
                        help="temporary compatibility input; prefer the two independent role axes")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--usb-id", help="profiled VID:PID; defaults to the registry auto candidate")
    parser.add_argument(
        "--allow-experimental-hardware", action="store_true",
        help="allow one explicit upstream/driver candidate for this attempt",
    )
    parser.add_argument("--phy", help="verified radio PHY; normally supplied by the health gate")
    parser.add_argument("--channel", type=int, choices=range(1, 14), default=6)
    parser.add_argument("--name", default="CODEX")
    parser.add_argument("--keys", default="./config/prod.keys")
    parser.add_argument("--target-bssid")
    parser.add_argument("--runs-root")
    parser.add_argument("--state-file")
    parser.add_argument("--party-state-file")
    parser.add_argument("--attempt-id")
    parser.add_argument("--member-token-file")
    parser.add_argument("--launch-nonce", required=True)
    parser.add_argument("--launch-ack-file", required=True)
    parser.add_argument("--connect-timeout", type=float, default=20)
    parser.add_argument("--radio-timeout", type=float, default=60)
    parser.add_argument("--room-timeout", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        if os.environ.get("SWITCHTRADE_ENDPOINT_LOCK_HELD") == "1":
            raise SystemExit(run_endpoint(args))
        with SingleInstanceLock("endpoint"):
            raise SystemExit(run_endpoint(args))
    except AlreadyRunningError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
