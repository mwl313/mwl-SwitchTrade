"""Automatic Switch LDN Core flow for the development runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import websockets

from switchtrade.composition import create_switch_ldn_driver
from switchtrade.core import CoreSupervisor, PairCredentials, PairSeat
from switchtrade.endpoints.switch_ldn import SwitchLdnPolicy
from switchtrade.hardware import HardwarePolicyError, require_hardware, select_profile
from switchtrade.transport import WireClient


DEFAULT_RELAY = "http://127.0.0.1:8788"


class CliError(RuntimeError):
    pass


class _WebSocketSocket:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def send(self, data: bytes) -> None:
        await self._connection.send(data)

    async def recv(self) -> bytes:
        data = await self._connection.recv()
        if not isinstance(data, bytes):
            raise CliError("relay sent non-binary Core data")
        return data

    async def close(self) -> None:
        await self._connection.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--relay", default=os.environ.get("SWITCHTRADE_CORE_RELAY", DEFAULT_RELAY))
    value.add_argument("--usb-id", default=os.environ.get("SWITCHTRADE_USB_ID"), required="SWITCHTRADE_USB_ID" not in os.environ)
    value.add_argument("--channel", type=int, choices=(1, 6, 11), default=6)
    value.add_argument("--verbose", action="store_true")
    value.add_argument("--log-dir", type=Path)
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("host")
    join = commands.add_parser("join")
    join.add_argument("code")
    return value


def _configure_logging(args: argparse.Namespace) -> None:
    logger = logging.getLogger(__name__)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handlers: list[logging.Handler] = []
    if args.verbose:
        handlers.append(logging.StreamHandler())
    if args.log_dir is not None:
        args.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_dir / "switchtrade-core.log", encoding="utf-8"))
    for handler in handlers:
        logger.addHandler(handler)


def _capabilities(role: str) -> dict[str, object]:
    return {
        "endpoint_kind": "switch_ldn",
        "runtime_kind": "managed_wsl",
        "protocols": ["switchtrade.gba-frame.v1"],
        "generation_roles": [role],
    }


async def _request(relay: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    base = relay.rstrip("/")

    def send() -> dict[str, object]:
        request = Request(
            f"{base}{path}", json.dumps(payload).encode("utf-8"), {"content-type": "application/json"}
        )
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise CliError("relay returned an invalid Pair response")
        return data

    try:
        return await asyncio.to_thread(send)
    except Exception as exc:
        raise CliError(f"Pair request failed: {exc}") from exc


def _credentials(response: dict[str, object], seat: PairSeat) -> PairCredentials:
    try:
        return PairCredentials(
            str(response["pair_id"]), seat, str(response["access_token"]),
            str(response["reconnect_expires_at"]),
            str(response["code"]) if seat is PairSeat.HOST else None,
        )
    except (KeyError, ValueError) as exc:
        raise CliError("relay returned incomplete Pair credentials") from exc


def _websocket_url(relay: str, credentials: PairCredentials) -> str:
    parts = urlsplit(relay)
    if parts.scheme not in {"http", "https", "ws", "wss"} or not parts.netloc:
        raise CliError("relay URL must use http(s) or ws(s)")
    scheme = "wss" if parts.scheme in {"https", "wss"} else "ws"
    return urlunsplit((scheme, parts.netloc, f"{parts.path.rstrip('/')}/core/v1/pairs/{credentials.pair_id}/ws", "", ""))


async def _socket(relay: str, credentials: PairCredentials) -> _WebSocketSocket:
    connection = await websockets.connect(
        _websocket_url(relay, credentials),
        additional_headers={"authorization": f"Bearer {credentials.access_token}"},
        proxy=None,
    )
    try:
        hello = json.loads(await connection.recv())
    except Exception:
        await connection.close()
        raise
    if hello != {"seat": credentials.seat.value}:
        await connection.close()
        raise CliError("relay authenticated an unexpected Pair seat")
    return _WebSocketSocket(connection)


def _policy(args: argparse.Namespace) -> SwitchLdnPolicy:
    phy = os.environ.get("SWITCHTRADE_PHY", "")
    ifname = os.environ.get("SWITCHTRADE_IFACE", "")
    if not phy:
        raise CliError("PHY_UNRESOLVED: run through the radio health gate")
    if not ifname:
        raise CliError("IFACE_UNRESOLVED: run through the radio health gate")
    try:
        profile = require_hardware(
            select_profile(args.usb_id), "guest" if args.command == "host" else "host"
        )
    except HardwarePolicyError as exc:
        raise CliError(str(exc)) from exc
    return SwitchLdnPolicy(
        run_id=f"core-{uuid4().hex}",
        release=os.environ.get("SWITCHTRADE_CORE_RELEASE", "development"),
        usb_id=profile.usb_id,
        hardware_profile=profile.chipset,
        phy=phy,
        ifname=ifname,
        keys_path=os.environ.get("SWITCHTRADE_KEYS", "/opt/switchtrade/config/prod.keys"),
        channel=args.channel,
    )


async def _bridge_until_canceled(supervisor: CoreSupervisor) -> None:
    await supervisor.wait_generation_end()


async def _run_host(args: argparse.Namespace) -> None:
    driver = create_switch_ldn_driver(_policy(args))
    print("Starting SwitchTrade...")
    credentials = _credentials(await _request(args.relay, "/core/v1/pairs", {"capabilities": _capabilities("origin")}), PairSeat.HOST)
    print(f"Pair code: {credentials.code}")
    transport = WireClient(PairSeat.HOST)
    await transport.connect(await _socket(args.relay, credentials))
    supervisor = CoreSupervisor(credentials, driver, transport, connector=lambda: _socket(args.relay, credentials))
    try:
        print("Waiting for a Group Leader room...")
        await supervisor.discover_local()
        print("Group Leader room detected.")
        print("Waiting for peer...")
        await supervisor.wait_for_peer()
        print("Peer connected.")
        await supervisor.offer_generation()
        print("Remote mirror ready.")
        print("Bridge active.")
        await _bridge_until_canceled(supervisor)
    finally:
        await supervisor.stop()


async def _run_guest(args: argparse.Namespace) -> None:
    driver = create_switch_ldn_driver(_policy(args))
    print("Starting SwitchTrade...")
    print(f"Connecting with code {args.code}...")
    credentials = _credentials(await _request(args.relay, "/core/v1/pairs:join", {"code": args.code, "capabilities": _capabilities("mirror")}), PairSeat.GUEST)
    transport = WireClient(PairSeat.GUEST)
    await transport.connect(await _socket(args.relay, credentials))
    supervisor = CoreSupervisor(credentials, driver, transport, connector=lambda: _socket(args.relay, credentials))
    try:
        print("Waiting for the host's Switch...")
        await supervisor.wait_for_peer()
        print("Peer connected.")
        print("Preparing the mirror access point...")
        print("Choose Join Group on the Switch when it appears.")
        await supervisor.accept_next_offer()
        print("Mirror access point and Switch ready.")
        print("Bridge active.")
        await _bridge_until_canceled(supervisor)
    finally:
        await supervisor.stop()


async def run(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "host":
        await _run_host(args)
    else:
        await _run_guest(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    except CliError as exc:
        print(f"CORE_CLI_FAILED: {exc}")
    except Exception as exc:
        if args.verbose or args.log_dir is not None:
            logging.getLogger(__name__).exception("Core CLI failed")
        print(f"CORE_CLI_FAILED: {exc}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
