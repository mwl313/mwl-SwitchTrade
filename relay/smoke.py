"""Credentialed end-to-end smoke test for a staged SwitchTrade relay."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from switchtrade.relay_client import RelayClient, USER_AGENT
from relay.authority import uuid7
from switchtrade.connection.b_fixture import FIXTURE, FIXTURE_SHA256
from switchtrade.connection.c2 import C2Bridge
from switchtrade.c2_protocol import launch_identity_hash
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


def _d_quiescent(client: TunnelClientV2, seat: str,
                 activation_generation: int) -> dict:
    return {
        "contract_version": "d-side-quiescent.v1",
        "attempt_id": client.attempt_id,
        "activation_generation": activation_generation,
        "source_seat": seat,
        "run_id": client.run_id,
        "stage_generation": client.stage_generation,
        "launch_identity_sha256": launch_identity_hash(
            client.run_id, client.stage_generation,
            client.launch_nonce, client.endpoint_pid,
        ),
        "evidence": {
            "endpoint_exited": True,
            "transport_exited": True,
            "threads_exited": True,
            "ldn_released": True,
            "interfaces_absent": True,
            "forced": False,
        },
    }


def smoke(base_url: str, allow_http: bool = False, reverse_roles: bool = False) -> None:
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
    first_role, second_role = (
        ("finder", "creator") if reverse_roles else ("creator", "finder")
    )
    for label, credential, role in (
            ("a", first, first_role), ("b", second, second_role)):
        proof = _p0_attestation(label)
        attestations[credential["member_token"]] = proof
        room = relay.room(room_id, credential["member_token"])
        room = relay.v2_ready(room_id, credential["member_token"], {
            "ready": True, "switch_room_role": role, "p0": proof,
        }, expected_version=room["room_version"])
    attempt_id = room["attempt"]["attempt_id"]
    activation_generation = room["attempt"].get("activation_generation")
    if (not room["attempt"]["role_locked"] or
            not room["v2_admission"]["attempt_admitted"] or
            isinstance(activation_generation, bool) or
            not isinstance(activation_generation, int) or activation_generation < 1 or
            activation_generation != room["v2_admission"].get("activation_generation")):
        raise RuntimeError("v2 P0 admission and roles were not locked atomically")

    def client(credential: dict, seat: str, pid: int, expected_hash=None) -> TunnelClientV2:
        proof = attestations[credential["member_token"]]
        return TunnelClientV2(
            base_url, code, attempt_id, seat, credential["member_token"],
            run_id=proof["run_id"], stage_generation=proof["stage_generation"],
            launch_nonce=hashlib.sha256(f"launch-{seat}-{attempt_id}".encode()).hexdigest(),
            endpoint_pid=pid, expected_advertisement_hash=expected_hash,
        )

    first_client = client(
        first, "member_a", 4101, FIXTURE_SHA256 if reverse_roles else None
    ).start()
    second_client = client(
        second, "member_b", 4102, None if reverse_roles else FIXTURE_SHA256
    ).start()
    try:
        if not first_client.wait_data_plane(10) or not second_client.wait_data_plane(10):
            raise RuntimeError("both v2 seats did not prove the bidirectional nonce path")
        advertiser = second_client if reverse_roles else first_client
        receiver = first_client if reverse_roles else second_client
        if advertiser.advertise(FIXTURE) != FIXTURE_SHA256:
            raise RuntimeError("A advertisement hash changed before relay delivery")
        _wait_advertisement(receiver)

        first_bridge = C2Bridge(
            attestations[first["member_token"]]["run_id"], attempt_id,
            "member_a", "b_ap_host" if reverse_roles else "a_room_joiner", first_client,
            activation_generation=activation_generation,
            advertisement_sha256=FIXTURE_SHA256,
        )
        second_bridge = C2Bridge(
            attestations[second["member_token"]]["run_id"], attempt_id,
            "member_b", "a_room_joiner" if reverse_roles else "b_ap_host", second_client,
            activation_generation=activation_generation,
            advertisement_sha256=FIXTURE_SHA256,
        )
        first_bridge.mark_local_ready("B_READY" if reverse_roles else "A_READY")
        for _ in range(10):
            first_bridge.pump()
            second_bridge.pump()
            time.sleep(0.01)
        if first_bridge.connected.is_set() or second_bridge.connected.is_set():
            raise RuntimeError("one-sided readiness incorrectly activated C2")
        second_bridge.mark_local_ready("A_READY" if reverse_roles else "B_READY")
        deadline = time.monotonic() + 10
        while (time.monotonic() < deadline and
               not (first_bridge.connected.is_set() and second_bridge.connected.is_set())):
            first_bridge.pump()
            second_bridge.pump()
            time.sleep(0.02)
        if not first_bridge.connected.is_set() or not second_bridge.connected.is_set():
            raise RuntimeError("C2 side-ready barrier did not activate both seats")

        to_first, to_second = secrets.token_bytes(32), secrets.token_bytes(32)
        first_bridge.send_rfu(to_second, flags=0x01)
        second_bridge.send_rfu(to_first, flags=0x03)
        received_first = received_second = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (
                received_first is None or received_second is None):
            received_first = next(iter(first_bridge.poll()), received_first)
            received_second = next(iter(second_bridge.poll()), received_second)
            time.sleep(0.02)
        if (received_first is None or received_second is None or
                (received_first.payload, received_first.flags) != (to_first, 0x03) or
                (received_second.payload, received_second.flags) != (to_second, 0x01) or
                not first_bridge.rfu_active.is_set() or not second_bridge.rfu_active.is_set()):
            raise RuntimeError("C2 byte-exact bidirectional RFU proof failed")

        room = relay.room(room_id, first["member_token"])
        closing_payload = {
            "contract_version": "d-closing-intent.v1",
            "attempt_id": attempt_id,
            "activation_generation": activation_generation,
            "outcome": "canceled",
            "primary_failure_code": None,
            "last_passed_gate": "C_RFU_ACTIVE",
        }
        room = relay.begin_distributed_d(
            room_id, attempt_id, first["member_token"], closing_payload,
            expected_version=room["room_version"],
        )
        if room["attempt"]["phase"] != "closing":
            raise RuntimeError("D1 did not preserve the closing intent")

        first_client.stop()
        first_quiescent = _d_quiescent(first_client, "member_a", activation_generation)
        first_ack = relay.acknowledge_distributed_d(
            room_id, attempt_id, first["member_token"], first_quiescent,
            expected_version=room["room_version"],
        )
        if first_ack["attempt"]["phase"] != "closing":
            raise RuntimeError("D6 terminalized before both sides were quiescent")

        second_client.stop()
        second_quiescent = _d_quiescent(second_client, "member_b", activation_generation)
        terminal = relay.acknowledge_distributed_d(
            room_id, attempt_id, second["member_token"], second_quiescent,
            expected_version=first_ack["room_version"],
        )
        if (terminal["attempt"]["phase"] != "canceled" or
                terminal["attempt"]["d"]["cleanup_status"] != "verified"):
            raise RuntimeError("D6 did not preserve the canceled two-side outcome")
        replay = relay.acknowledge_distributed_d(
            room_id, attempt_id, second["member_token"], second_quiescent,
            expected_version=first_ack["room_version"],
        )
        if replay["room_version"] != terminal["room_version"]:
            raise RuntimeError("D5 response-loss retry mutated the terminal room")
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
    parser.add_argument(
        "--reverse-roles", action="store_true",
        help="assign member A to finder/B and member B to creator/A",
    )
    args = parser.parse_args()
    smoke(args.base_url, args.allow_http, args.reverse_roles)
    print("SwitchTrade relay hosting smoke PASS")


if __name__ == "__main__":
    main()
