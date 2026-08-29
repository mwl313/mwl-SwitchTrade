"""Credentialed end-to-end smoke test for a staged SwitchTrade relay."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from switchtrade.relay_client import RelayClient, USER_AGENT
from relay.authority import uuid7
from switchtrade.connection.b_fixture import FIXTURE, FIXTURE_SHA256
from switchtrade.rfu_tunnel_v2 import Kind
from switchtrade.tunnel_client_v2 import TunnelClientV2


def _wait_advertisement(client: TunnelClientV2, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(frame.kind == Kind.ADVERTISEMENT and frame.payload == FIXTURE
               for frame in client.poll()):
            return
        time.sleep(0.02)
    raise RuntimeError("timed out waiting for the verified v2 advertisement")


def _p0_attestation(label: str) -> dict:
    return {
        "contract_version": "p0-attestation.v2",
        "run_id": uuid7(),
        "release": "0.3.0-validation.1",
        "run_generation": 1,
        "stage_generation": 1,
        "adapter_instance_sha256": hashlib.sha256(
            f"hosting-smoke-adapter-{label}".encode()).hexdigest(),
        "report_sha256": hashlib.sha256(
            f"hosting-smoke-report-{label}".encode()).hexdigest(),
    }


def smoke(base_url: str, allow_http: bool = False) -> None:
    base_url = base_url.rstrip("/")
    if not allow_http and not base_url.startswith("https://"):
        raise ValueError("public smoke tests require HTTPS; use --allow-http only for local staging")
    headers = {"User-Agent": USER_AGENT}
    with urlopen(Request(f"{base_url}/health", headers=headers), timeout=5) as response:
        health = json.load(response)
    if (health.get("status") != "ready" or health.get("payload_mode") != "opaque" or
            health.get("room_contract") != "room-control.v1" or
            "rfu-tunnel.v2" not in health.get("rfu_contracts", [])):
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
    attestations = {}
    for label, credential, role in (
            ("a", first, "creator"), ("b", second, "finder")):
        proof = _p0_attestation(label)
        attestations[credential["member_token"]] = proof
        room = relay.room(room_id, credential["member_token"])
        room = relay.v2_ready(room_id, credential["member_token"], {
            "ready": True, "switch_room_role": role, "p0": proof,
        }, expected_version=room["room_version"])
    attempt_id = room["attempt"]["attempt_id"]
    if (not room["attempt"]["role_locked"] or
            not room["v2_admission"]["attempt_admitted"]):
        raise RuntimeError("v2 P0 admission and roles were not locked atomically")

    def client(credential: dict, seat: str, pid: int, expected_hash=None) -> TunnelClientV2:
        proof = attestations[credential["member_token"]]
        return TunnelClientV2(
            base_url, code, attempt_id, seat, credential["member_token"],
            run_id=proof["run_id"], stage_generation=proof["stage_generation"],
            launch_nonce=hashlib.sha256(f"launch-{seat}-{attempt_id}".encode()).hexdigest(),
            endpoint_pid=pid, expected_advertisement_hash=expected_hash,
        )

    first_client = client(first, "member_a", 4101).start()
    second_client = client(second, "member_b", 4102, FIXTURE_SHA256).start()
    try:
        if not first_client.wait_data_plane(10) or not second_client.wait_data_plane(10):
            raise RuntimeError("both v2 seats did not prove the bidirectional nonce path")
        if first_client.advertise(FIXTURE) != FIXTURE_SHA256:
            raise RuntimeError("A advertisement hash changed before relay delivery")
        _wait_advertisement(second_client)
    finally:
        first_client.stop()
        second_client.stop()
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
