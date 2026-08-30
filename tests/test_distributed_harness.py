import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest

from switchtrade.connection.distributed_endpoint import _closing_command, _config
from switchtrade.connection.distributed_harness import (
    DistributedLifecycle,
    INVITATION_CONTRACT,
    _decode_invitation,
    _invitation,
)
from switchtrade.connection.stage_session import StageSession


RUN_ID = "00000000-0000-0000-0000-000000000123"


class DistributedContractTests(unittest.TestCase):
    def invitation(self):
        return {
            "contract_version": INVITATION_CONTRACT,
            "test_id": "00000000-0000-0000-0000-000000000456",
            "source_sha": "a" * 40,
            "release": "abcd-m7",
            "room_code": "ABC123",
            "action": "end",
            "owner_role": "a_room_joiner",
            "peer_role": "b_ap_host",
        }

    def test_one_time_invitation_is_strict_and_round_trips_utf8_safely(self):
        invitation = self.invitation()
        encoded = _invitation(invitation)
        self.assertTrue(encoded.isascii())
        self.assertEqual(_decode_invitation(encoded), invitation)
        for changed in (
            {**invitation, "token": "secret"},
            {**invitation, "peer_role": "a_room_joiner"},
            {**invitation, "source_sha": "not-a-commit"},
        ):
            with self.assertRaises(SystemExit):
                _decode_invitation(_invitation(changed))

    def test_endpoint_config_and_closing_intent_are_launch_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "설정.json"
            value = {
                "contract_version": "distributed-endpoint-config.v1",
                "relay_url": "https://relay.example",
                "room_id": "room-1",
                "room_code": "ABC123",
                "attempt_id": "attempt-1",
                "member_token": "x" * 43,
                "source_seat": "member_a",
                "switch_role": "a_room_joiner",
                "activation_generation": 1,
                "run_id": RUN_ID,
                "release": "release-a",
                "stage_generation": 1,
                "launch_nonce": "n" * 64,
                "endpoint_pid": os.getpid(),
            }
            path.write_text(json.dumps(value), encoding="utf-8")
            args = argparse.Namespace(
                run_id=RUN_ID, release="release-a", launch_nonce="n" * 64)
            self.assertEqual(_config(path, args)["attempt_id"], "attempt-1")
            changed = {**value, "endpoint_pid": os.getpid() + 1}
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                _config(path, args)

            intent = {
                "contract_version": "d-closing-intent.v1",
                "attempt_id": "attempt-1",
                "activation_generation": 1,
                "outcome": "canceled",
                "primary_failure_code": None,
                "last_passed_gate": "C_RFU_ACTIVE",
            }
            config = {"attempt_id": "attempt-1", "activation_generation": 1}
            self.assertEqual(
                _closing_command({"action": "closing_intent", "value": intent}, config), intent)
            with self.assertRaises(ValueError):
                _closing_command({
                    "action": "closing_intent",
                    "value": {**intent, "activation_generation": 2},
                }, config)

    def test_authority_attempt_requires_complementary_roles_and_locked_generation(self):
        lifecycle = object.__new__(DistributedLifecycle)
        lifecycle.session = {"switch_role": "a_room_joiner"}
        room = {
            "local_member_id": "a",
            "members": [
                {"member_id": "a", "seat": "member_a", "online_state": "online",
                 "switch_room_role": "creator"},
                {"member_id": "b", "seat": "member_b", "online_state": "online",
                 "switch_room_role": "finder"},
            ],
            "attempt": {
                "attempt_id": "attempt-1", "role_locked": True,
                "creator_member_id": "a", "role_lock_version": 8,
                "activation_generation": 2,
            },
        }
        self.assertEqual(lifecycle._validate_attempt(room)["attempt_id"], "attempt-1")
        with self.assertRaises(Exception):
            lifecycle._validate_attempt({
                **room,
                "members": [room["members"][0], {**room["members"][1],
                                                   "switch_room_role": "creator"}],
            })


class StageSessionTests(unittest.TestCase):
    def test_stage_resources_remain_owned_until_single_stop(self):
        class Stage:
            session_handler = None

            async def run(self):
                await self.session_handler("network", "transport", b"advertisement")
                return {"status": "passed"}

        session = StageSession(Stage(), timeout=1, stop_timeout=1).start()
        resources = session.wait_ready()
        self.assertEqual(resources.transport, "transport")
        self.assertEqual(resources.advertisement, b"advertisement")
        session.stop()
        session.stop()


if __name__ == "__main__":
    unittest.main()
