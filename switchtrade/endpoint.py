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


GROUP_TO_RADIO_ROLE = {"host": "guest", "guest": "host"}


class StateReporter:
    def __init__(self, path: str | None):
        self.path = Path(path).expanduser() if path else None

    def write(self, state: str, **fields) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({
            "state": state,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            **fields,
        }, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(self.path)


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


def runtime_plan(group_role: str, usb_id: str | None = None) -> dict:
    radio_role = GROUP_TO_RADIO_ROLE[group_role]
    profile = require_role(select_profile(usb_id), radio_role)
    return {
        "group_role": group_role,
        "radio_role": radio_role,
        "usb_id": profile.usb_id,
        "driver_strategy": profile.strategy,
        "allowed_drivers": list(profile.allowed_drivers),
        "profile_status": profile.status,
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
    plan = runtime_plan(args.role, args.usb_id)
    if args.dry_run:
        print(plan)
        return 0

    state = StateReporter(args.state_file)
    state.write("initializing", radio_checked=False, tunnel_connected=False)
    logger = RunLogger("rfu-endpoint", args.runs_root, {
        **plan, "session_id": args.session_id, "relay_url": args.relay_url,
        "phy": args.phy, "channel": args.channel,
    })
    log = EndpointLog(logger)
    tunnel = TunnelClient(args.relay_url, args.session_id, args.role, log=log).start()
    transport = sim = None
    outcome = "failed"
    try:
        if not tunnel.wait_connected(args.connect_timeout):
            raise TimeoutError(f"relay connection failed: {tunnel.last_error or 'timeout'}")
        state.write("relay_connected", radio_checked=False, tunnel_connected=True)

        if args.role == "host":
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
            )
            transport.start(timeout=args.radio_timeout)

        state.write("radio_ready", radio_checked=True, tunnel_connected=True,
                    usb_id=plan["usb_id"], radio_role=plan["radio_role"])

        connection, our_var = _connection(transport, args.role, args.name, log)
        crypto = cryptomod.PiaCrypto(transport.ssid)
        sim = TunnelSim(
            transport, crypto, transport.our_ip, transport.host_ip, tunnel,
            conn=connection, our_var=our_var, parent=args.role == "guest",
            capture_path=str(logger.run_dir / "pia.jsonl"), log=log,
        )
        log.info("RFU endpoint ready; opaque feature-neutral forwarding active.")
        state.write("session_ready", radio_checked=True, tunnel_connected=True,
                    usb_id=plan["usb_id"], radio_role=plan["radio_role"])

        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        period = MS_PER_VBLANK / 1000.0
        deadline = time.monotonic()
        while not stopping and not sim.host_disconnected:
            sim.tick()
            deadline += period
            time.sleep(max(0, deadline - time.monotonic()))
        outcome = "completed"
        state.write("completed", radio_checked=True, tunnel_connected=False)
        return 0
    except Exception as error:
        log(f"[endpoint] fatal: {error}")
        logger.event("endpoint_failed", level="error", error=str(error))
        state.write("failed", radio_checked=transport is not None,
                    tunnel_connected=tunnel.connected.is_set(), error=str(error))
        return 1
    finally:
        if sim is not None:
            sim.close()
        if transport is not None:
            transport.stop()
        tunnel.stop()
        logger.close(outcome)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("host", "guest"), required=True,
                        help="online group role; host joins the leader Switch room, guest mirrors it")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--usb-id", help="profiled VID:PID; defaults to the registry auto candidate")
    parser.add_argument("--phy", default="phy0")
    parser.add_argument("--channel", type=int, choices=range(1, 14), default=6)
    parser.add_argument("--name", default="CODEX")
    parser.add_argument("--keys", default="~/.switch/prod.keys")
    parser.add_argument("--target-bssid")
    parser.add_argument("--runs-root")
    parser.add_argument("--state-file")
    parser.add_argument("--connect-timeout", type=float, default=20)
    parser.add_argument("--radio-timeout", type=float, default=60)
    parser.add_argument("--room-timeout", type=float, default=300)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    raise SystemExit(run_endpoint(build_parser().parse_args()))


if __name__ == "__main__":
    main()
