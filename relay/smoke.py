"""Credentialed end-to-end smoke test for a staged SwitchTrade relay."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from switchtrade.relay_client import RelayClient, USER_AGENT
from switchtrade.rfu_tunnel import Kind
from switchtrade.tunnel_client import TunnelClient


def _wait(client: TunnelClient, payload: bytes, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(frame.kind == Kind.RFU and frame.payload == payload for frame in client.poll()):
            return
        time.sleep(0.02)
    raise RuntimeError("timed out waiting for relayed RFU payload")


def smoke(base_url: str, allow_http: bool = False) -> None:
    base_url = base_url.rstrip("/")
    if not allow_http and not base_url.startswith("https://"):
        raise ValueError("public smoke tests require HTTPS; use --allow-http only for local staging")
    headers = {"User-Agent": USER_AGENT}
    with urlopen(Request(f"{base_url}/health", headers=headers), timeout=5) as response:
        health = json.load(response)
    if health.get("status") != "ready" or health.get("payload_mode") != "opaque":
        raise RuntimeError("relay health contract is not ready")
    try:
        urlopen(Request(f"{base_url}/session/create", method="POST", headers=headers), timeout=5)
    except HTTPError as error:
        if error.code != 404:
            raise RuntimeError(f"legacy relay endpoint returned {error.code}, expected 404") from error
    else:
        raise RuntimeError("legacy unauthenticated relay endpoint is enabled")

    relay = RelayClient(base_url)
    first = relay.create_trade_room({
        "name": "Hosting smoke test", "visibility": "private",
        "trainer_display_name": "Smoke A", "game": "FireRed", "language": "English",
    }, "hosting-smoke-a")
    second = relay.join_trade_room(
        first["room"]["room_code"], "Smoke B", "hosting-smoke-b")
    room_id = first["room"]["room_id"]
    code = first["room"]["room_code"]
    for credential, role in ((first, "creator"), (second, "finder")):
        room = relay.room(room_id, credential["member_token"])
        relay.room_command(
            room_id, credential["member_token"], "/ready",
            {"ready": True, "switch_room_role": role},
            expected_version=room["room_version"],
        )
    room = relay.room(room_id, first["member_token"])
    room = relay.room_command(
        room_id, first["member_token"], "/attempts",
        expected_version=room["room_version"],
    )
    attempt_id = room["attempt"]["attempt_id"]
    if not room["attempt"]["role_locked"]:
        raise RuntimeError("manual Switch roles were not locked atomically")
    host = TunnelClient(base_url, code, "host", heartbeat_interval=1,
                        member_token=first["member_token"], attempt_id=attempt_id).start()
    guest = TunnelClient(base_url, code, "guest", heartbeat_interval=1,
                         member_token=second["member_token"], attempt_id=attempt_id).start()
    try:
        if not host.wait_connected(10) or not guest.wait_connected(10):
            raise RuntimeError("both credentialed RFU seats did not connect")
        host.send(b"switchtrade-hosting-smoke-a")
        _wait(guest, b"switchtrade-hosting-smoke-a")
        guest.send(b"switchtrade-hosting-smoke-b")
        _wait(host, b"switchtrade-hosting-smoke-b")
    finally:
        host.stop()
        guest.stop()
        room = relay.room(room_id, first["member_token"])
        relay.room_command(room_id, first["member_token"], "", method="DELETE",
                           expected_version=room["room_version"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="public HTTPS relay base URL")
    parser.add_argument("--allow-http", action="store_true", help="allow HTTP for local staging only")
    args = parser.parse_args()
    smoke(args.base_url, args.allow_http)
    print("SwitchTrade relay hosting smoke PASS")


if __name__ == "__main__":
    main()
