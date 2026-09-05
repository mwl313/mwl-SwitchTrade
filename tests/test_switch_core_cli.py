from __future__ import annotations

import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from switchtrade.core import PairCredentials, PairSeat
from switchtrade.core.supervisor import SupervisorError
from switchtrade.core_cli import CliError, _credentials, _policy, _websocket_url, main, parser, run


class SwitchCoreCliTests(unittest.IsolatedAsyncioTestCase):
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
