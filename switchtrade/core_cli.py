"""Automatic Core flow with explicitly selected local endpoint/runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from uuid import uuid4

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from switchtrade import __version__
from switchtrade.composition import create_switch_ldn_driver, create_retroarch_gpsp_driver
from switchtrade.core import CoreSupervisor, PairCredentials, PairSeat
from switchtrade.core.contracts import GenerationEnded
from switchtrade.transport import TransportError, WireClient

if TYPE_CHECKING:
    from switchtrade.endpoints.switch_ldn import SwitchLdnPolicy


DEFAULT_RELAY = "http://127.0.0.1:8788"
USER_AGENT = f"SwitchTrade-Core/{__version__}"


class CliError(RuntimeError):
    pass


class _WebSocketSocket:
    def __init__(self, connection: Any, *, close_timeout: float = 2.0) -> None:
        self._connection = connection
        self._close_timeout = close_timeout

    async def send(self, data: bytes) -> None:
        await self._connection.send(data)

    async def recv(self) -> bytes:
        data = await self._connection.recv()
        if not isinstance(data, bytes):
            raise CliError("relay sent non-binary Core data")
        return data

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._connection.close(), self._close_timeout)
        except TimeoutError:
            # WireClient's outer bound must not cancel a longer WebSocket close
            # handshake and forget its TCP owner. Abort only this connection,
            # then prove local socket termination before returning clean.
            logging.getLogger(__name__).warning("websocket_close_abort reason=handshake_timeout")
            self._connection.transport.abort()
            await asyncio.wait_for(self._connection.wait_closed(), 1.0)
        except asyncio.CancelledError:
            self._connection.transport.abort()
            raise


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--relay", default=os.environ.get("SWITCHTRADE_CORE_RELAY", DEFAULT_RELAY))
    value.add_argument("--usb-id", default=os.environ.get("SWITCHTRADE_USB_ID"))
    value.add_argument("--channel", type=int, choices=(1, 6, 11), default=6)
    value.add_argument("--verbose", action="store_true")
    value.add_argument("--log-dir", type=Path)
    value.add_argument("--emulator", choices=("gpsp",))
    value.add_argument("--emulator-port", type=int, default=55435)
    value.add_argument("--emulator-pid", type=int)
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("host")
    join = commands.add_parser("join")
    join.add_argument("code")
    doctor = commands.add_parser("doctor")
    for subcommand in (join, doctor):
        subcommand.add_argument("--emulator", choices=("gpsp",), default=argparse.SUPPRESS)
        subcommand.add_argument("--emulator-port", type=int, default=argparse.SUPPRESS)
        subcommand.add_argument("--emulator-pid", type=int, default=argparse.SUPPRESS)
    return value


def _configure_logging(args: argparse.Namespace) -> None:
    logger = logging.getLogger("switchtrade")
    for handler in logger.handlers:
        handler.close()
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
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    if not handlers:
        logger.addHandler(logging.NullHandler())


def _capabilities(role: str) -> dict[str, object]:
    return {
        "endpoint_kind": "switch_ldn",
        "runtime_kind": "managed_wsl",
        "protocols": ["switchtrade.gba-frame.v1"],
        "generation_roles": [role],
    }


def _relay_base(relay: str, *, websocket: bool = False) -> str:
    try:
        parts = urlsplit(relay)
        valid_port = parts.port
    except ValueError as error:
        raise CliError("RELAY_URL_INVALID") from error
    del valid_port
    if (parts.scheme not in {"http", "https", "ws", "wss"} or not parts.hostname
        or parts.username is not None or parts.password is not None or parts.query or parts.fragment):
        raise CliError("RELAY_URL_INVALID: use an http(s) or ws(s) base URL without credentials/query")
    secure = parts.scheme in {"https", "wss"}
    scheme = ("wss" if secure else "ws") if websocket else ("https" if secure else "http")
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


async def _request(relay: str, path: str, payload: dict[str, object] | None = None,
                   *, access_token: str | None = None) -> dict[str, object]:
    base = _relay_base(relay)

    def send() -> dict[str, object]:
        headers = {"content-type": "application/json", "User-Agent": USER_AGENT}
        if access_token is not None:
            headers["authorization"] = f"Bearer {access_token}"
        request = Request(f"{base}{path}",
                          json.dumps(payload).encode("utf-8") if payload is not None else None, headers)
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise CliError("relay returned an invalid Pair response")
        return data

    try:
        return await asyncio.to_thread(send)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(4096)).get("detail", "PAIR_REQUEST_FAILED")
        except (ValueError, AttributeError):
            detail = "PAIR_REQUEST_FAILED"
        finally:
            exc.close()
        if not isinstance(detail, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", detail):
            detail = "PAIR_REQUEST_FAILED"
        raise CliError(detail) from exc
    except (URLError, TimeoutError) as exc:
        raise CliError("RELAY_UNREACHABLE: verify the common relay URL and connectivity") from exc
    except Exception as exc:
        raise CliError(f"Pair request failed: {exc}") from exc


def _credentials(response: dict[str, object], seat: PairSeat) -> PairCredentials:
    try:
        for field in ("pair_id", "access_token", "reconnect_expires_at"):
            if not isinstance(response[field], str) or not response[field]:
                raise ValueError("missing identity")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", response["pair_id"]):
            raise ValueError("invalid Pair identity")
        if datetime.fromisoformat(response["reconnect_expires_at"]).tzinfo is None:
            raise ValueError("missing lease timezone")
        if seat is PairSeat.HOST and not re.fullmatch(r"[0-9]{6}", str(response.get("code", ""))):
            raise ValueError("invalid Pair code")
        return PairCredentials(
            str(response["pair_id"]), seat, str(response["access_token"]),
            str(response["reconnect_expires_at"]),
            str(response["code"]) if seat is PairSeat.HOST else None,
        )
    except (KeyError, ValueError) as exc:
        raise CliError("relay returned incomplete Pair credentials") from exc


def _websocket_url(relay: str, credentials: PairCredentials) -> str:
    return f"{_relay_base(relay, websocket=True)}/core/v1/pairs/{credentials.pair_id}/ws"


async def _socket(relay: str, credentials: PairCredentials) -> _WebSocketSocket:
    connection = None
    try:
        connection = await websockets.connect(
            _websocket_url(relay, credentials),
            additional_headers={"authorization": f"Bearer {credentials.access_token}"},
            user_agent_header=USER_AGENT,
            proxy=None,
        )
        raw = await asyncio.wait_for(connection.recv(), 5)
        if not isinstance(raw, str):
            raise TransportError("T_HANDSHAKE_INVALID")
        try:
            hello = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TransportError("T_HANDSHAKE_INVALID") from exc
        if hello != {"seat": credentials.seat.value}:
            raise CliError("relay authenticated an unexpected Pair seat")
    except BaseException as exc:
        if connection is not None:
            await connection.close()
        if isinstance(exc, InvalidStatus):
            code = "T_AUTH_INVALID" if exc.response.status_code in {401, 403} else "T_HANDSHAKE_INVALID"
            raise TransportError(code) from exc
        if isinstance(exc, ConnectionClosed):
            close_code = exc.rcvd.code if exc.rcvd else None
            code = "T_AUTH_INVALID" if close_code == 4401 else (
                "T_HANDSHAKE_INVALID" if close_code in {1002, 1003, 1008, 4400, 4403, 4408}
                else "T_TRANSPORT_FAILED")
            raise TransportError(code) from exc
        if isinstance(exc, (OSError, asyncio.TimeoutError)) and not isinstance(exc, ssl.SSLError):
            raise TransportError("T_TRANSPORT_FAILED") from exc
        raise
    return _WebSocketSocket(connection)


def _policy(args: argparse.Namespace) -> SwitchLdnPolicy:
    from switchtrade.endpoints.switch_ldn import SwitchLdnPolicy
    from switchtrade.hardware import HardwarePolicyError, require_hardware, select_profile
    proven_usb = os.environ.get("SWITCHTRADE_USB_ID", "")
    phy = os.environ.get("SWITCHTRADE_PHY", "")
    ifname = os.environ.get("SWITCHTRADE_IFACE", "")
    proven_channel = os.environ.get("SWITCHTRADE_P0_TARGET_CHANNEL", "")
    if not proven_usb or not args.usb_id or args.usb_id.lower() != proven_usb.lower():
        raise CliError("RADIO_IDENTITY_MISMATCH: CLI USB ID differs from radio gate evidence")
    if proven_channel != str(args.channel):
        raise CliError("RADIO_CHANNEL_MISMATCH: CLI channel differs from radio gate evidence")
    if os.environ.get("SWITCHTRADE_P0_RX_PASSED") != "1":
        raise CliError("RADIO_RX_UNPROVEN: radio health gate did not prove receive")
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
    run_id = str(uuid4())
    suffix = uuid4().hex[:7]
    policy = SwitchLdnPolicy(
        run_id=run_id,
        release=os.environ.get("SWITCHTRADE_CORE_RELEASE", "development"),
        usb_id=profile.usb_id,
        hardware_profile=profile.chipset,
        phy=phy,
        proven_radio_iface=ifname,
        ifname=f"st-{suffix}",
        ap_ifname=f"ap-{suffix}",
        monitor_ifname=f"mon-{suffix}",
        tap_ifname=f"tap-{suffix}",
        keys_path=os.environ.get("SWITCHTRADE_KEYS", "/opt/switchtrade/config/prod.keys"),
        channel=args.channel,
    )
    logging.getLogger(__name__).info(
        "radio_binding run=%s release=%s usb=%s phy=%s proven_iface=%s channel=%s owned=%s",
        policy.run_id, policy.release, policy.usb_id, policy.phy, policy.proven_radio_iface,
        policy.channel, (policy.ifname, policy.ap_ifname, policy.monitor_ifname, policy.tap_ifname))
    return policy


async def _bridge_until_canceled(supervisor: CoreSupervisor) -> None:
    await supervisor.wait_generation_end()


async def _stop_preserving_failure(supervisor, primary: BaseException | None) -> None:
    try:
        await supervisor.stop()
    except BaseException as cleanup:
        if primary is None or isinstance(primary, asyncio.CancelledError):
            raise
        primary.add_note("cleanup failed: " + str(getattr(cleanup, "code", type(cleanup).__name__)))
        logging.getLogger(__name__).error("Additional cleanup failure: %s", getattr(cleanup, "code", type(cleanup).__name__))
    finally:
        logging.getLogger(__name__).info("supervisor_exit state=%s primary=%s cleanup_failure_count=%s",
            getattr(supervisor, "state", None), getattr(primary, "code", type(primary).__name__ if primary else None),
            len(getattr(supervisor, "cleanup_failures", ())))


async def _run_host(args: argparse.Namespace) -> None:
    driver = create_switch_ldn_driver(_policy(args))
    print("Starting SwitchTrade...", flush=True)
    pair = await _request(args.relay, "/core/v1/pairs", {"capabilities": _capabilities("origin")})
    credentials = _credentials(pair, PairSeat.HOST)
    print(f"Pair code: {credentials.code}", flush=True)
    if expires_at := pair.get("code_expires_at"):
        print(f"Pair code expires at: {expires_at}", flush=True)
    transport = WireClient(PairSeat.HOST)
    async def peer_joined():
        status = await _request(args.relay, f"/core/v1/pairs/{credentials.pair_id}",
                                access_token=credentials.access_token)
        return status.get("guest_joined") is True

    supervisor = CoreSupervisor(credentials, driver, transport, connector=lambda: _socket(args.relay, credentials),
                                invite_expires_at=pair.get("code_expires_at"), confirm_peer_joined=peer_joined)
    primary = None
    try:
        await transport.connect(await _socket(args.relay, credentials))
        while True:
            try:
                print("Waiting for a Group Leader room...", flush=True)
                await supervisor.discover_local()
                print("Group Leader room detected.", flush=True)
                print("Waiting for peer...", flush=True)
                await supervisor.wait_for_peer()
                print("Peer connected.", flush=True)
                await supervisor.offer_generation()
                print("Remote mirror ready.", flush=True)
                print("Bridge active.", flush=True)
                await _bridge_until_canceled(supervisor)
            except GenerationEnded:
                pass
            print("Generation ended. Pair retained.", flush=True)
    except BaseException as error:
        primary = error
        raise
    finally:
        await _stop_preserving_failure(supervisor, primary)


async def _run_guest(args: argparse.Namespace) -> None:
    driver = create_switch_ldn_driver(_policy(args))
    print("Starting SwitchTrade...", flush=True)
    print(f"Connecting with code {args.code}...", flush=True)
    credentials = _credentials(await _request(args.relay, "/core/v1/pairs:join", {"code": args.code, "capabilities": _capabilities("mirror")}), PairSeat.GUEST)
    transport = WireClient(PairSeat.GUEST)
    supervisor = CoreSupervisor(credentials, driver, transport, connector=lambda: _socket(args.relay, credentials))
    primary = None
    try:
        await transport.connect(await _socket(args.relay, credentials))
        while True:
            try:
                print("Waiting for the host's Switch...", flush=True)
                await supervisor.wait_for_peer()
                print("Peer connected.", flush=True)
                print("Preparing the mirror access point...", flush=True)
                print("Choose Join Group on the Switch when it appears.", flush=True)
                await supervisor.accept_next_offer()
                print("Mirror access point and Switch ready.", flush=True)
                print("Bridge active.", flush=True)
                await _bridge_until_canceled(supervisor)
            except GenerationEnded:
                pass
            print("Generation ended. Pair retained.", flush=True)
    except BaseException as error:
        primary = error
        raise
    finally:
        await _stop_preserving_failure(supervisor, primary)


async def run(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "join" and not re.fullmatch(r"[0-9]{6}", args.code):
        raise CliError("Pair code must contain six digits.")
    if getattr(args, "emulator", None):
        if args.command not in ("join", "doctor"):
            raise CliError("gpSP currently supports Join Group only.")
        operation = _doctor_gpsp(args) if args.command == "doctor" else _run_gpsp_guest(args)
    elif args.command == "doctor":
        raise CliError("Use doctor --emulator gpsp for a native emulator check.")
    else:
        operation = _run_host(args) if args.command == "host" else _run_guest(args)
    if os.environ.get("SWITCHTRADE_PARENT_STDIN") == "1":
        from switchtrade.parent_lifetime import run_with_parent
        await run_with_parent(operation)
    else:
        await operation
    return 0


async def _doctor_gpsp(args):
    from switchtrade.endpoints.retroarch_gpsp.process import ProcessObserver
    from switchtrade.endpoints.retroarch_gpsp.errors import GpspError
    import socket

    observer = ProcessObserver.select(args.emulator_pid)
    if not 1 <= args.emulator_port <= 65535:
        raise GpspError("EMULATOR_PORT_INVALID", "올바른 --emulator-port를 지정하세요.")
    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", args.emulator_port))
        except OSError as error:
            raise GpspError("EMULATOR_PORT_UNAVAILABLE", "로컬 Netplay 포트가 사용 중입니다. 실행 중인 SwitchTrade도 확인하세요.") from error
    observer.check()
    print("RetroArch and supported gpSP core found.", flush=True)
    print(f"Local Netplay port available: 127.0.0.1:{args.emulator_port}", flush=True)
    print("RFU setting and game connection are not yet verified. Join a Pair and connect Netplay.", flush=True)


async def _wait_gpsp_bridge(supervisor, generation):
    ended = asyncio.create_task(supervisor.wait_generation_end())
    ready = asyncio.create_task(generation.wait_link_ready())
    try:
        done, _ = await asyncio.wait((ended, ready), return_when=asyncio.FIRST_COMPLETED)
        if ended in done:
            await ended
            return
        await ready
        print("Bridge active.", flush=True)
        await ended
    finally:
        for task in (ended, ready):
            if not task.done():
                task.cancel()
        await asyncio.gather(ended, ready, return_exceptions=True)


async def _run_gpsp_guest(args):
    driver = create_retroarch_gpsp_driver(pid=args.emulator_pid, port=args.emulator_port)
    supervisor = None
    primary = None
    try:
        # No Pair/code consumption until the selected process and local bind
        # have been checked. No WSL/radio preparation occurs on this path.
        await driver.prepare()
        print("RetroArch and supported gpSP core found.", flush=True)
        credentials = _credentials(await _request(args.relay, "/core/v1/pairs:join", {
            "code": args.code, "capabilities": {"endpoint_kind": "retroarch_gpsp", "runtime_kind": "native",
                "protocols": list(driver.capabilities.protocols), "generation_roles": ["mirror"]}}), PairSeat.GUEST)
        transport = WireClient(PairSeat.GUEST)
        supervisor = CoreSupervisor(credentials, driver, transport, connector=lambda: _socket(args.relay, credentials))
        await transport.connect(await _socket(args.relay, credentials))
        print(f"Connect RetroArch Netplay to 127.0.0.1:{args.emulator_port}.", flush=True)
        while True:
            try:
                print("Waiting for the host's room and local Netplay connection...", flush=True)
                await supervisor.accept_next_offer()
                print("Local Netplay connected. GBA Wireless Adapter verified.", flush=True)
                print("Choose Join Group in the emulator.", flush=True)
                await _wait_gpsp_bridge(supervisor, driver.generation)
            except GenerationEnded:
                pass
            print("Generation ended. Pair and local Netplay retained.", flush=True)
    except BaseException as error:
        primary = error
        raise
    finally:
        if supervisor is not None:
            await _stop_preserving_failure(supervisor, primary)
        else:
            report = await driver.close()
            if not (report.endpoint_stopped and report.local_resources_released and report.transport_drained):
                if primary is None or isinstance(primary, asyncio.CancelledError):
                    raise CliError("EMULATOR_CLEANUP_UNPROVEN")
                primary.add_note("EMULATOR_CLEANUP_UNPROVEN")
        print("SwitchTrade stopped. RetroArch was not closed.", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    except CliError as exc:
        if args.emulator:
            logging.getLogger(__name__).exception("Native Core CLI failed")
            print("Pair 연결에 실패했습니다. 참가 코드와 공통 relay 설정을 확인하세요.")
        else:
            print(f"CORE_CLI_FAILED: {exc}")
    except Exception as exc:
        if args.verbose or args.log_dir is not None:
            logging.getLogger(__name__).exception("Core CLI failed code=%s", getattr(exc, "code", type(exc).__name__))
        if args.emulator:
            from switchtrade.endpoints.retroarch_gpsp.errors import GpspError
            cause = exc
            seen = set()
            while cause is not None and id(cause) not in seen:
                if isinstance(cause, GpspError):
                    print(cause.message)
                    break
                seen.add(id(cause))
                cause = cause.__cause__
            else:
                print("중계가 종료됐습니다. 상대 연결과 로컬 Netplay를 확인하세요.")
        else:
            code = getattr(exc, "code", None)
            label = f"{code}: {exc}" if code and str(exc) != code else str(exc)
            print(f"CORE_CLI_FAILED: {label}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
