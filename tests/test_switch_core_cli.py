from __future__ import annotations

import asyncio
import ssl
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close

from switchtrade.core import PairCredentials, PairSeat
from switchtrade.core.supervisor import SupervisorError
from switchtrade.core_cli import CliError, _credentials, _policy, _websocket_url, _relay_base, _stop_preserving_failure, main, parser, run
from switchtrade.core_cli import _socket
from switchtrade.transport import TransportError


class SwitchCoreCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_classifies_transient_loss_without_retrying_identity_failures(self):
        credentials = PairCredentials("pair", PairSeat.HOST, "token", "2099-01-01T00:00:00+00:00")
        cases = [
            (OSError("dial lost"), "T_TRANSPORT_FAILED", False),
            (TimeoutError("dial timed out"), "T_TRANSPORT_FAILED", False),
            (InvalidStatus(SimpleNamespace(status_code=403)), "T_AUTH_INVALID", False),
            (InvalidStatus(SimpleNamespace(status_code=400)), "T_HANDSHAKE_INVALID", False),
            (ssl.SSLCertVerificationError("untrusted certificate"), None, False),
            (TimeoutError("hello timed out"), "T_TRANSPORT_FAILED", True),
            (ConnectionClosedError(Close(1012, "restart"), None), "T_TRANSPORT_FAILED", True),
            (ConnectionClosedError(Close(4401, "auth"), None), "T_AUTH_INVALID", True),
            (ConnectionClosedError(Close(4403, "seat"), None), "T_HANDSHAKE_INVALID", True),
        ]
        for failure, code, opened in cases:
            with self.subTest(failure=type(failure).__name__, code=code, opened=opened):
                connection = AsyncMock()
                connection.recv.side_effect = failure
                connect = AsyncMock(return_value=connection) if opened else AsyncMock(side_effect=failure)
                with patch("switchtrade.core_cli.websockets.connect", connect):
                    with self.assertRaises(TransportError if code else ssl.SSLError) as caught:
                        await _socket("http://relay.example", credentials)
                if code:
                    self.assertEqual(caught.exception.code, code)
                    self.assertIs(caught.exception.__cause__, failure)
                else:
                    self.assertIs(caught.exception, failure)
                self.assertEqual(connection.close.await_count, int(opened))

    async def test_socket_rejects_non_text_or_malformed_hello_and_closes_it(self):
        credentials = PairCredentials("pair", PairSeat.HOST, "token", "2099-01-01T00:00:00+00:00")
        for raw in (b"STPW\xff", "not-json"):
            with self.subTest(raw=raw):
                connection = AsyncMock()
                connection.recv.return_value = raw
                with patch("switchtrade.core_cli.websockets.connect", AsyncMock(return_value=connection)):
                    with self.assertRaises(TransportError) as caught:
                        await _socket("http://relay.example", credentials)
                self.assertEqual(caught.exception.code, "T_HANDSHAKE_INVALID")
                connection.close.assert_awaited_once()

    def test_common_relay_http_and_websocket_urls_are_consistent(self):
        for scheme, http, ws in (("http", "http", "ws"), ("ws", "http", "ws"),
                                 ("https", "https", "wss"), ("wss", "https", "wss")):
            self.assertEqual(_relay_base(f"{scheme}://relay.example/base/"), f"{http}://relay.example/base")
            self.assertEqual(_relay_base(f"{scheme}://relay.example/base/", websocket=True), f"{ws}://relay.example/base")
        for invalid in ("ftp://relay.example", "https://token@relay.example", "https://relay.example/?token=x",
                        "http://relay.example:invalid", "http://", "https://relay.example/#fragment"):
            with self.assertRaises(CliError):
                _relay_base(invalid)

    async def test_first_failure_survives_cleanup_but_cancel_cleanup_failure_is_nonzero(self):
        cleanup = SupervisorError("S_CLEANUP_FAILED")
        supervisor = type("Owner", (), {"stop": AsyncMock(side_effect=cleanup)})()
        first = CliError("PAIR_AUTH_INVALID")
        await _stop_preserving_failure(supervisor, first)
        self.assertEqual(str(first), "PAIR_AUTH_INVALID")
        self.assertIn("S_CLEANUP_FAILED", first.__notes__[0])
        with self.assertRaises(SupervisorError) as caught:
            await _stop_preserving_failure(supervisor, asyncio.CancelledError())
        self.assertIs(caught.exception, cleanup)

    def test_credentials_reject_missing_or_unbound_identities(self):
        response = {"pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00", "code": "000042"}
        self.assertEqual(_credentials(response, PairSeat.HOST).code, "000042")
        for field, value in (("pair_id", "../other"), ("access_token", None),
                             ("reconnect_expires_at", "2099-01-01"), ("code", 42)):
            with self.assertRaises(CliError):
                _credentials({**response, field: value}, PairSeat.HOST)

    def test_dev_core_route_runs_through_the_proven_radio_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn("Invoke-DevRun -Arguments $runArguments -CoreCli", (root / "dev.ps1").read_text(encoding="utf-8"))
        overlay = (root / "scripts" / "dev" / "DevOverlay.psm1").read_text(encoding="utf-8")
        self.assertIn("./scripts/wsl-radio-prepare.sh", overlay)
        self.assertIn("'--usb-id', $usbId", overlay)
        self.assertIn("'--target-channel', $channel", overlay)

    def test_parser_accepts_automatic_host_and_join_commands(self) -> None:
        host = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        guest = parser().parse_args(["--usb-id", "0bda:818b", "join", "381742"])
        self.assertEqual((host.command, host.channel), ("host", 6))
        self.assertEqual((guest.command, guest.code), ("join", "381742"))

    def test_pair_credentials_and_websocket_path_are_seat_bound(self) -> None:
        response = {
            "pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00", "code": "381742"
        }
        host = _credentials(response, PairSeat.HOST)
        guest = _credentials(response, PairSeat.GUEST)
        self.assertEqual(host.code, "381742")
        self.assertIsNone(guest.code)
        self.assertEqual(_websocket_url("https://relay.example/base", host), "wss://relay.example/base/core/v1/pairs/pair-1/ws")

    def test_policy_uses_only_proven_channel_values(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "--channel", "11", "host"])
        with patch.dict("switchtrade.core_cli.os.environ", {
            "SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_PHY": "phy7", "SWITCHTRADE_IFACE": "wlan7",
            "SWITCHTRADE_P0_TARGET_CHANNEL": "11", "SWITCHTRADE_P0_RX_PASSED": "1",
        }, clear=True):
            policy = _policy(args)
        self.assertEqual((policy.channel, policy.usb_id, policy.phy, policy.proven_radio_iface), (11, "0bda:818b", "phy7", "wlan7"))
        self.assertNotEqual(policy.ifname, policy.proven_radio_iface)

    def test_policy_rejects_identity_channel_or_receive_proof_mismatch(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        proven = {
            "SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_PHY": "phy7", "SWITCHTRADE_IFACE": "wlan7",
            "SWITCHTRADE_P0_TARGET_CHANNEL": "6", "SWITCHTRADE_P0_RX_PASSED": "1",
        }
        for key, value, code in (
            ("SWITCHTRADE_USB_ID", "0e8d:7610", "RADIO_IDENTITY_MISMATCH"),
            ("SWITCHTRADE_P0_TARGET_CHANNEL", "11", "RADIO_CHANNEL_MISMATCH"),
            ("SWITCHTRADE_P0_RX_PASSED", "0", "RADIO_RX_UNPROVEN"),
        ):
            with self.subTest(code=code), patch.dict("switchtrade.core_cli.os.environ", {**proven, key: value}, clear=True):
                with self.assertRaisesRegex(CliError, code):
                    _policy(args)

    def test_policy_rejects_missing_proven_phy_or_unsupported_usb(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        with patch.dict("switchtrade.core_cli.os.environ", {"SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_IFACE": "wlan7", "SWITCHTRADE_P0_TARGET_CHANNEL": "6", "SWITCHTRADE_P0_RX_PASSED": "1"}, clear=True):
            with self.assertRaisesRegex(CliError, "PHY_UNRESOLVED"):
                _policy(args)
        unsupported = parser().parse_args(["--usb-id", "ffff:ffff", "host"])
        with patch.dict("switchtrade.core_cli.os.environ", {"SWITCHTRADE_USB_ID": "ffff:ffff", "SWITCHTRADE_PHY": "phy7", "SWITCHTRADE_IFACE": "wlan7", "SWITCHTRADE_P0_TARGET_CHANNEL": "6", "SWITCHTRADE_P0_RX_PASSED": "1"}, clear=True):
            with self.assertRaisesRegex(CliError, "HARDWARE_UNSUPPORTED"):
                _policy(unsupported)

    async def test_host_uses_discovery_before_waiting_for_peer_and_stops(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        response = {
            "pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00", "code": "381742"
        }
        supervisor = type("Supervisor", (), {
            "discover_local": AsyncMock(), "wait_for_peer": AsyncMock(), "offer_generation": AsyncMock(), "stop": AsyncMock(),
        })()
        with patch("switchtrade.core_cli._request", AsyncMock(return_value=response)), \
             patch("switchtrade.core_cli._socket", AsyncMock(return_value=object())), \
             patch("switchtrade.core_cli.WireClient.connect", AsyncMock()), \
             patch("switchtrade.core_cli._policy", return_value=object()), \
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor), \
             patch("switchtrade.core_cli._bridge_until_canceled", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await run(args)
        supervisor.discover_local.assert_awaited_once()
        supervisor.wait_for_peer.assert_awaited_once()
        supervisor.offer_generation.assert_awaited_once()
        supervisor.stop.assert_awaited_once()

    async def test_guest_waits_for_peer_accepts_offer_and_stops(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "join", "381742"])
        response = {
            "pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00"
        }
        supervisor = type("Supervisor", (), {
            "wait_for_peer": AsyncMock(), "accept_next_offer": AsyncMock(), "stop": AsyncMock(),
        })()
        with patch("switchtrade.core_cli._request", AsyncMock(return_value=response)), \
             patch("switchtrade.core_cli._socket", AsyncMock(return_value=object())), \
             patch("switchtrade.core_cli.WireClient.connect", AsyncMock()), \
             patch("switchtrade.core_cli._policy", return_value=object()), \
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor), \
             patch("switchtrade.core_cli._bridge_until_canceled", AsyncMock(side_effect=asyncio.CancelledError)), \
             patch("builtins.print") as printed:
            with self.assertRaises(asyncio.CancelledError):
                await run(args)
        supervisor.wait_for_peer.assert_awaited_once()
        supervisor.accept_next_offer.assert_awaited_once()
        supervisor.stop.assert_awaited_once()
        events = [call.args[0] for call in printed.call_args_list]
        self.assertLess(events.index("Choose Join Group on the Switch when it appears."), events.index("Mirror access point and Switch ready."))

    async def test_active_failure_exits_run_and_stops_once(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        response = {"pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00", "code": "381742"}
        supervisor = type("Supervisor", (), {
            "discover_local": AsyncMock(), "wait_for_peer": AsyncMock(), "offer_generation": AsyncMock(),
            "wait_generation_end": AsyncMock(side_effect=SupervisorError("S_PUMP_FAILED")), "stop": AsyncMock(),
        })()
        with patch("switchtrade.core_cli._request", AsyncMock(return_value=response)), \
             patch("switchtrade.core_cli._socket", AsyncMock(return_value=object())), \
             patch("switchtrade.core_cli.WireClient.connect", AsyncMock()), \
             patch("switchtrade.core_cli._policy", return_value=object()), \
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor):
            with self.assertRaisesRegex(SupervisorError, "S_PUMP_FAILED"):
                await run(args)
        supervisor.stop.assert_awaited_once()

    async def test_cancellation_stops_once_without_turning_into_a_failure(self) -> None:
        args = parser().parse_args(["--usb-id", "0bda:818b", "host"])
        response = {"pair_id": "pair-1", "access_token": "token", "reconnect_expires_at": "2099-01-01T00:00:00+00:00", "code": "381742"}
        supervisor = type("Supervisor", (), {
            "discover_local": AsyncMock(), "wait_for_peer": AsyncMock(), "offer_generation": AsyncMock(), "stop": AsyncMock(),
        })()
        with patch("switchtrade.core_cli._request", AsyncMock(return_value=response)), \
             patch("switchtrade.core_cli._socket", AsyncMock(return_value=object())), \
             patch("switchtrade.core_cli.WireClient.connect", AsyncMock()), \
             patch("switchtrade.core_cli._policy", return_value=object()), \
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor), \
             patch("switchtrade.core_cli._bridge_until_canceled", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await run(args)
        supervisor.stop.assert_awaited_once()

    def test_main_maps_unexpected_failure_to_a_clean_nonzero_exit(self) -> None:
        with patch("switchtrade.core_cli.run", AsyncMock(side_effect=SupervisorError("S_PUMP_FAILED"))), \
             patch("builtins.print") as printed:
            self.assertEqual(main(["--usb-id", "0bda:818b", "host"]), 1)
        self.assertEqual(printed.call_args.args[0], "CORE_CLI_FAILED: S_PUMP_FAILED")


if __name__ == "__main__":
    unittest.main()
