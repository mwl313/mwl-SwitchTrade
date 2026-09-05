from __future__ import annotations

import argparse
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from switchtrade.core import PairCredentials, PairSeat
from switchtrade.core_cli import _credentials, _policy, _websocket_url, parser, run


class SwitchCoreCliTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(_policy(args).channel, 11)

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
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor), \
             patch("switchtrade.core_cli._bridge_until_canceled", AsyncMock()):
            self.assertEqual(await run(args), 0)
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
             patch("switchtrade.core_cli.create_switch_ldn_driver", return_value=object()), \
             patch("switchtrade.core_cli.CoreSupervisor", return_value=supervisor), \
             patch("switchtrade.core_cli._bridge_until_canceled", AsyncMock()):
            self.assertEqual(await run(args), 0)
        supervisor.wait_for_peer.assert_awaited_once()
        supervisor.accept_next_offer.assert_awaited_once()
        supervisor.stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
