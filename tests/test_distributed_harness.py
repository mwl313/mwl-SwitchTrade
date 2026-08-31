import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from switchtrade.connection.distributed_endpoint import (
    _Commands,
    _checkpoint_command,
    _closing_command,
    _config,
)
from switchtrade.connection.distributed_harness import (
    CONTROL_STATE_CONTRACT,
    DistributedControl,
    DistributedLifecycle,
    INVITATION_CONTRACT,
    RELAY_POLL_INTERVAL,
    _decode_invitation,
    _invitation,
    _room_session,
    _recover_distributed,
    _source_sha,
)
from switchtrade.connection.p0_harness import _stable_error_code
from switchtrade.connection.stage_session import StageSession, StageSessionError
from switchtrade.relay_client import RelayError


RUN_ID = "00000000-0000-0000-0000-000000000123"
ROOM_ID = "00000000-0000-0000-0000-000000000789"


class FakeControl:
    def __init__(self):
        self.calls = []
        self.state = {"run_id": None, "terminal_status": None}

    def publish(self, phase, **values):
        self.calls.append(("publish", phase, values))
        if values.get("run_id") is not None:
            self.state["run_id"] = values["run_id"]

    def await_continue(self, checkpoint, **values):
        self.calls.append(("continue", checkpoint, values))

    def raise_if_canceled(self, _gate):
        return None

    def cancel_requested(self):
        return False

    def begin_cleanup(self, run_id):
        self.calls.append(("cleaning", run_id))


class DistributedContractTests(unittest.TestCase):
    def invitation(self):
        return {
            "contract_version": INVITATION_CONTRACT,
            "test_id": "00000000-0000-0000-0000-000000000456",
            "source_sha": "a" * 40,
            "release": "abcd-m7",
            "room_id": ROOM_ID,
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

    def test_private_room_join_binds_to_authoritative_room_id_without_note(self):
        invitation = self.invitation()

        class Relay:
            commands = []

            @staticmethod
            def join_trade_room(room_code, _display_name, _client_id):
                return {
                    "room": {
                        "contract_version": "room-control.v1",
                        "room_id": ROOM_ID,
                        "room_code": room_code, "visibility": "private",
                        "local_member_id": "member-b",
                        "members": [
                            {"member_id": "member-a", "seat": "member_a", "online_state": "online"},
                            {"member_id": "member-b", "seat": "member_b", "online_state": "online"},
                        ],
                    },
                    "member_token": "m" * 32, "reconnect_token": "r" * 32,
                }

            def room_command(self, *args, **kwargs):
                self.commands.append((args, kwargs))

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "분산-세션.json"
            relay = Relay()
            session, encoded = _room_session(
                argparse.Namespace(command="join", invitation=_invitation(invitation)),
                invitation["release"], invitation["source_sha"], relay, path,
            )
            self.assertIsNone(encoded)
            self.assertEqual(session["room_id"], invitation["room_id"])
            self.assertTrue(path.exists())
            self.assertEqual(relay.commands, [])

    def test_reused_control_root_is_rejected_before_any_relay_mutation(self):
        class Relay:
            calls = 0

            def create_trade_room(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("relay mutation must not run")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distributed-control-state.json").write_text("{}", encoding="utf-8")
            relay = Relay()
            args = argparse.Namespace(
                command="create", role="a_room_joiner", action="end")
            with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_STATE_ROOT_REUSE_FORBIDDEN"):
                _room_session(
                    args, "release-a", "a" * 40, relay,
                    root / "distributed-session.json",
                )
            self.assertEqual(relay.calls, 0)

    def test_session_persistence_failure_rolls_back_joined_authority_member(self):
        invitation = self.invitation()

        class Relay:
            left = False

            @staticmethod
            def join_trade_room(room_code, _display_name, _client_id):
                return {
                    "room": {
                        "contract_version": "room-control.v1", "room_id": ROOM_ID,
                        "room_code": room_code, "visibility": "private", "room_version": 2,
                        "local_member_id": "member-b",
                        "members": [
                            {"member_id": "member-a", "seat": "member_a", "online_state": "online"},
                            {"member_id": "member-b", "seat": "member_b", "online_state": "online"},
                        ],
                    },
                    "member_token": "m" * 32, "reconnect_token": "r" * 32,
                }

            def room_command(self, *_args, **_kwargs):
                self.left = True

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "distributed-session.json"
            relay = Relay()
            with patch(
                "switchtrade.connection.distributed_harness.atomic_json",
                side_effect=OSError("simulated durable-write failure"),
            ), self.assertRaisesRegex(SystemExit, "DISTRIBUTED_SESSION_PERSIST_FAILED"):
                _room_session(
                    argparse.Namespace(command="join", invitation=_invitation(invitation)),
                    invitation["release"], invitation["source_sha"], relay, path,
                )
            self.assertTrue(relay.left)
            self.assertFalse(path.exists())

    def test_private_room_join_rejects_wrong_room_id_and_leaves_without_session(self):
        invitation = self.invitation()

        class Relay:
            def __init__(self):
                self.left = False

            @staticmethod
            def join_trade_room(room_code, _display_name, _client_id):
                return {
                    "room": {
                        "contract_version": "room-control.v1", "room_id": "other-room",
                        "room_code": room_code, "visibility": "private", "room_version": 2,
                        "local_member_id": "member-b",
                        "members": [
                            {"member_id": "member-a", "seat": "member_a", "online_state": "online"},
                            {"member_id": "member-b", "seat": "member_b", "online_state": "online"},
                        ],
                    },
                    "member_token": "m" * 32, "reconnect_token": "r" * 32,
                }

            def room_command(self, *_args, **_kwargs):
                self.left = True

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "distributed-session.json"
            relay = Relay()
            with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_INVITATION_IDENTITY_MISMATCH"):
                _room_session(
                    argparse.Namespace(command="join", invitation=_invitation(invitation)),
                    invitation["release"], invitation["source_sha"], relay, path,
                )
            self.assertTrue(relay.left)
            self.assertFalse(path.exists())

    def test_endpoint_config_and_closing_intent_are_launch_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "설정.json"
            value = {
                "contract_version": "distributed-endpoint-config.v1",
                "relay_url": "https://relay.example",
                "room_id": ROOM_ID,
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

    def test_operator_continue_is_run_role_and_checkpoint_bound(self):
        config = {"run_id": RUN_ID}
        command = {
            "action": "continue_checkpoint",
            "checkpoint": "CREATE_SWITCH_ROOM",
            "run_id": RUN_ID,
        }
        self.assertIsNone(_checkpoint_command(command, config, "CREATE_SWITCH_ROOM"))
        for changed in (
            {**command, "run_id": str(uuid.uuid4())},
            {**command, "checkpoint": "JOIN_SWITCH_GROUP"},
            {**command, "unexpected": True},
        ):
            with self.assertRaises(ValueError):
                _checkpoint_command(changed, config, "CREATE_SWITCH_ROOM")

        commands = object.__new__(_Commands)
        commands.values = queue.Queue()
        commands.values.put(command)
        self.assertIsNone(commands.wait_checkpoint(config, "CREATE_SWITCH_ROOM", 1))

    def test_recovery_before_attempt_closes_owner_room_without_peer_prompt(self):
        class Coordinator:
            def snapshot(self):
                return {
                    "run_id": RUN_ID,
                    "identity": {
                        "release": "release-a", "switch_role": "a_room_joiner",
                        "room_id": ROOM_ID, "attempt_id": None,
                    },
                    "cleanup": {"verified": False},
                    "last_passed_gate": "P0_SIDE_READY",
                }

        class Relay:
            def __init__(self):
                self.commands = []

            def room(self, room_id, member_token):
                return {
                    "contract_version": "room-control.v1", "room_id": ROOM_ID,
                    "room_code": "ABC123", "visibility": "private", "room_version": 3,
                    "local_member_id": "member-a", "attempt": None,
                    "members": [{
                        "member_id": "member-a", "seat": "member_a",
                        "online_state": "online",
                    }],
                }

            def begin_distributed_d(self, *args, **kwargs):
                raise AssertionError("D must not begin before an attempt exists")

            def room_command(self, *args, **kwargs):
                self.commands.append((args, kwargs))

        class Harness:
            def recover(self, run):
                return {"status": "recovered"}

        with tempfile.TemporaryDirectory() as temporary:
            session_path = Path(temporary) / "distributed-session.json"
            session_path.write_text("{}", encoding="utf-8")
            relay = Relay()
            session = {
                "release": "release-a", "switch_role": "a_room_joiner",
                "room_id": ROOM_ID, "room_code": "ABC123",
                "member_token": "member-token", "owner": True,
            }
            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
                recovered = _recover_distributed(
                    coordinator=Coordinator(), relay=relay, harness=Harness(),
                    session=session, session_path=session_path, control=FakeControl(),
                )

            self.assertEqual(recovered["status"], "recovered")
            self.assertFalse(session_path.exists())
            self.assertEqual(relay.commands[0][0][2], "")
            self.assertEqual(relay.commands[0][1]["method"], "DELETE")

    def test_pairing_failure_recovery_closes_room_without_local_hardware_run(self):
        class Coordinator:
            @staticmethod
            def snapshot():
                return None

        class Relay:
            def __init__(self):
                self.closed = False

            @staticmethod
            def room(_room_id, _member_token):
                return {
                    "contract_version": "room-control.v1", "room_id": ROOM_ID,
                    "room_code": "ABC123", "visibility": "private", "room_version": 1,
                    "local_member_id": "member-a",
                    "members": [{
                        "member_id": "member-a", "seat": "member_a",
                        "online_state": "online",
                    }],
                }

            def room_command(self, *_args, **_kwargs):
                self.closed = True

        class Harness:
            @staticmethod
            def recover(_run):
                raise AssertionError("no hardware run exists")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "distributed-session.json"
            path.write_text("{}", encoding="utf-8")
            relay = Relay()
            result = _recover_distributed(
                coordinator=Coordinator(), relay=relay, harness=Harness(),
                session={
                    "release": "release-a", "switch_role": "a_room_joiner",
                    "room_id": ROOM_ID, "room_code": "ABC123", "member_token": "token",
                    "reconnect_token": "reconnect", "owner": True,
                },
                session_path=path, control=FakeControl(),
            )
            self.assertEqual(result["status"], "recovered")
            self.assertEqual(result["local_recovery"], {"status": "not_required"})
            self.assertTrue(relay.closed)
            self.assertFalse(path.exists())

    def test_invalid_relay_credential_still_runs_exact_local_recovery(self):
        class Coordinator:
            def snapshot(self):
                return {
                    "run_id": RUN_ID,
                    "identity": {
                        "release": "release-a", "switch_role": "a_room_joiner",
                        "room_id": ROOM_ID, "attempt_id": None,
                    },
                    "cleanup": {"verified": False},
                    "last_passed_gate": "P0_SIDE_READY",
                }

        class Relay:
            def room(self, _room_id, _member_token):
                raise RelayError(
                    "member credential is invalid", status=401,
                    code="member_credential_invalid",
                )

            def reconnect_trade_room(self, _room_id, _reconnect_token):
                raise RelayError(
                    "reconnect credential is invalid", status=401,
                    code="reconnect_credential_invalid",
                )

        class Harness:
            called = False

            def recover(self, _run):
                self.called = True
                return {"status": "recovered"}

        harness = Harness()
        result = _recover_distributed(
            coordinator=Coordinator(), relay=Relay(), harness=harness,
            session={
                "release": "release-a", "switch_role": "a_room_joiner",
                "room_id": ROOM_ID, "room_code": "ABC123", "member_token": "expired",
                "reconnect_token": "expired-reconnect", "owner": True,
            },
            session_path=Path("unused.json"), control=FakeControl(),
        )
        self.assertTrue(harness.called)
        self.assertEqual(result["local_recovery"]["status"], "recovered")
        self.assertFalse(result["room_finalized"])

    def test_external_error_code_is_normalized_at_coordinator_boundary(self):
        error = RelayError(
            "member credential is invalid", status=401,
            code="member_credential_invalid",
        )
        self.assertEqual(_stable_error_code(error), "MEMBER_CREDENTIAL_INVALID")

    def test_peer_wait_stays_below_relay_member_rate_limit(self):
        clock = [0.0]

        def room(attempt=False):
            value = {
                "room_version": 3,
                "local_member_id": "member-a",
                "members": [
                    {"member_id": "member-a", "seat": "member_a",
                     "online_state": "online", "switch_room_role": "creator"},
                    {"member_id": "member-b", "seat": "member_b",
                     "online_state": "online", "switch_room_role": "finder"},
                ],
                "attempt": None,
            }
            if attempt:
                value["attempt"] = {
                    "attempt_id": "attempt-1", "role_locked": True,
                    "creator_member_id": "member-a", "role_lock_version": 4,
                    "activation_generation": 1,
                }
            return value

        class Relay:
            base_url = "https://relay.example"

            def __init__(self):
                self.member_requests = 0
                self.heartbeats = 0

            def command_id(self):
                return "command-1"

            def room(self, room_id, member_token):
                self.member_requests += 1
                if self.member_requests > 120 and clock[0] < 60:
                    raise AssertionError("relay member rate limit exceeded")
                return room(attempt=clock[0] >= 35)

            def v2_ready(self, *args, **kwargs):
                self.member_requests += 1
                return room()

            def room_command(self, *args, **kwargs):
                self.member_requests += 1
                self.heartbeats += 1
                return room(attempt=clock[0] >= 35)

        class Coordinator:
            def lock_attempt(self, run_id, **identity):
                return identity

        with tempfile.TemporaryDirectory() as temporary:
            run_root = Path(temporary)
            (run_root / "p0-side-ready.json").write_text("{}", encoding="utf-8")
            relay = Relay()
            lifecycle = DistributedLifecycle(
                coordinator=Coordinator(), relay=relay,
                session={
                    "room_id": ROOM_ID, "member_token": "member-token",
                    "switch_role": "a_room_joiner", "room_code": "ABC123",
                    "test_id": "test-1", "owner": True, "action": "end",
                },
                session_path=run_root / "session.json", distro="SwitchTrade",
                packaged_python="/opt/switchtrade/python", runtime_root="/opt/switchtrade",
                control=FakeControl(), timeout=60,
            )
            context = {
                "run_id": RUN_ID, "run_root": run_root,
                "run": {"identity": {
                    "release": "release-a", "run_generation": 1, "stage_generation": 1,
                }},
                "adapter": argparse.Namespace(instance_sha256="a" * 64),
                "p0b": {"wrapper_pid": 123}, "launch_nonce": "n" * 64,
            }
            with patch(
                "switchtrade.connection.distributed_harness.time.monotonic",
                side_effect=lambda: clock[0],
            ), patch(
                "switchtrade.connection.distributed_harness.time.sleep",
                side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            ):
                prepared = lifecycle.prepare(context)

            self.assertEqual(prepared["attempt_id"], "attempt-1")
            self.assertGreaterEqual(RELAY_POLL_INTERVAL, 1.0)
            self.assertLess(relay.member_requests, 120)
            self.assertGreaterEqual(relay.heartbeats, 3)

    def test_explicit_file_checkpoint_keeps_member_alive_without_stdin(self):
        heartbeat = threading.Event()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = DistributedControl(
                root, test_id=str(uuid.uuid4()), source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            failures = []

            def wait():
                try:
                    control.await_continue(
                        "PAIRING_CONFIRMED", run_id=None, timeout=3,
                        heartbeat=heartbeat.set,
                    )
                except BaseException as error:
                    failures.append(error)

            with patch(
                "switchtrade.connection.distributed_harness.RELAY_HEARTBEAT_INTERVAL", 0.01,
            ), patch("builtins.input", side_effect=AssertionError("stdin must not be used")):
                worker = threading.Thread(target=wait)
                worker.start()
                deadline = time.monotonic() + 1
                while control.read_state(control.state_path)["phase"] != "awaiting_user":
                    if failures:
                        raise failures[0]
                    if time.monotonic() >= deadline:
                        self.fail("control checkpoint was not published")
                    time.sleep(0.01)
                self.assertTrue(heartbeat.wait(0.5), "relay heartbeat did not run while awaiting")
                DistributedControl.submit(
                    root, action="continue", test_id=control.state["test_id"],
                    run_id=None, checkpoint="PAIRING_CONFIRMED",
                )
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertTrue(heartbeat.is_set())
            self.assertEqual(control.read_state(control.state_path)["phase"], "running")

    def test_control_status_is_read_only_and_stale_commands_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_id = str(uuid.uuid4())
            control = DistributedControl(
                root, test_id=test_id, source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            before = control.state_path.read_bytes()
            state = DistributedControl.read_state(control.state_path)
            self.assertEqual(state["contract_version"], CONTROL_STATE_CONTRACT)
            self.assertEqual(control.state_path.read_bytes(), before)
            with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_CONTROL_IDENTITY_MISMATCH"):
                DistributedControl.submit(
                    root, action="cancel", test_id=str(uuid.uuid4()),
                    run_id=None, checkpoint=None,
                )
            self.assertFalse(control.command_path.exists())

    def test_control_cancel_is_identity_bound_and_cleanup_owns_finalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_id = str(uuid.uuid4())
            control = DistributedControl(
                root, test_id=test_id, source_sha="a" * 40,
                release="release-a", role="b_ap_host",
            )
            control.publish("running", run_id=RUN_ID)
            accepted = DistributedControl.submit(
                root, action="cancel", test_id=test_id,
                run_id=RUN_ID, checkpoint=None,
            )
            self.assertEqual(accepted["action"], "cancel")
            self.assertTrue(control.cancel_requested())
            control.begin_cleanup(RUN_ID)
            self.assertEqual(control.read_state(control.state_path)["phase"], "cleaning")
            with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_CLEANUP_IN_PROGRESS"):
                DistributedControl.submit(
                    root, action="cancel", test_id=test_id,
                    run_id=RUN_ID, checkpoint=None,
                )

    def test_control_command_publication_never_overwrites_a_concurrent_submitter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_id = str(uuid.uuid4())
            control = DistributedControl(
                root, test_id=test_id, source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            control.publish("running", run_id=RUN_ID)
            barrier = threading.Barrier(3)
            results = []

            def submit():
                barrier.wait()
                try:
                    DistributedControl.submit(
                        root, action="cancel", test_id=test_id,
                        run_id=RUN_ID, checkpoint=None,
                    )
                    results.append("accepted")
                except SystemExit as error:
                    results.append(str(error))

            workers = [threading.Thread(target=submit) for _ in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait()
            for worker in workers:
                worker.join(2)
            self.assertFalse(any(worker.is_alive() for worker in workers))
            self.assertCountEqual(
                results, ["accepted", "DISTRIBUTED_CONTROL_COMMAND_PENDING"])
            self.assertEqual(
                DistributedControl._read_command(control.command_path)["action"], "cancel")

    def test_cleanup_removes_a_checkpoint_command_that_raced_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_id = str(uuid.uuid4())
            control = DistributedControl(
                root, test_id=test_id, source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            control.publish(
                "awaiting_user", run_id=RUN_ID,
                checkpoint="CREATE_SWITCH_ROOM", can_continue=True)
            DistributedControl.submit(
                root, action="continue", test_id=test_id, run_id=RUN_ID,
                checkpoint="CREATE_SWITCH_ROOM",
            )
            self.assertTrue(control.command_path.exists())
            control.begin_cleanup(RUN_ID)
            self.assertFalse(control.command_path.exists())
            self.assertEqual(control.read_state(control.state_path)["phase"], "cleaning")

    def test_control_submit_rejects_unknown_action_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test_id = str(uuid.uuid4())
            control = DistributedControl(
                root, test_id=test_id, source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_CONTROL_COMMAND_INVALID"):
                DistributedControl.submit(
                    root, action="unknown", test_id=test_id,
                    run_id=None, checkpoint=None,
                )
            self.assertFalse(control.command_path.exists())

    def test_control_state_rejects_boolean_schema_and_sequence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = DistributedControl(
                root, test_id=str(uuid.uuid4()), source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            for field in ("schema", "sequence"):
                invalid = {**control.state, field: True}
                control.state_path.write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "DISTRIBUTED_CONTROL_STATE_INVALID"):
                    DistributedControl.read_state(control.state_path)

    def test_canonical_launcher_contains_no_stdin_prompt_and_fixes_environment(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts" / "windows" / "Invoke-M7DistributedHarness.ps1").read_text(
            encoding="utf-8")
        self.assertNotIn("Read-Host", script)
        self.assertNotIn("builtins.input", script)
        for required in (
            ".audit-venv\\Scripts\\python.exe", "DISTRIBUTED_QUALIFICATION_SOURCE_DIRTY",
            "--cd", "/opt/switchtrade", "hardware-selection.json",
            "switchtrade.connection.distributed_harness", "Push-Location",
            "m7-qualification-kit.v1", "DISTRIBUTED_QUALIFICATION_INTEGRITY_FAILED",
            "qualification-manifest.json", "verify",
        ):
            self.assertIn(required, script)

    def test_packaged_source_identity_requires_matching_manifest_and_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            root = kit / "source"
            module = root / "switchtrade" / "connection" / "distributed_harness.py"
            module.parent.mkdir(parents=True)
            module.write_bytes(b"packaged source\n")
            digest = hashlib.sha256(module.read_bytes()).hexdigest()
            manifest = kit / "qualification-manifest.json"
            manifest.write_text(json.dumps({
                "contract_version": "m7-qualification-kit.v1",
                "schema": 1,
                "source_sha": "a" * 40,
                "release_id": "beta-aaaaaaaaaaaa",
                "source_root": "source",
                "artifacts": [{
                    "path": "source/switchtrade/connection/distributed_harness.py",
                    "size": module.stat().st_size,
                    "sha256": digest,
                }],
            }), encoding="utf-8")
            with patch.dict(os.environ, {
                    "SWITCHTRADE_QUALIFICATION_MANIFEST": str(manifest)}):
                self.assertEqual(_source_sha(root), "a" * 40)
                module.write_bytes(b"altered\n")
                with self.assertRaisesRegex(
                        SystemExit, "DISTRIBUTED_QUALIFICATION_MANIFEST_INVALID"):
                    _source_sha(root)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "PowerShell 7 is required")
    def test_canonical_launcher_status_is_read_only_from_an_arbitrary_cwd(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "windows" / "Invoke-M7DistributedHarness.ps1"
        with tempfile.TemporaryDirectory(prefix="스위치트레이드-") as temporary:
            state_root = Path(temporary) / "상태"
            state_root.mkdir()
            control = DistributedControl(
                state_root, test_id=str(uuid.uuid4()), source_sha="a" * 40,
                release="release-a", role="a_room_joiner",
            )
            before = control.state_path.read_bytes()
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                 "status", "-StateRoot", str(state_root)],
                cwd=Path(temporary), capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["test_id"], control.state["test_id"])
            self.assertEqual(control.state_path.read_bytes(), before)

    def test_switch_checkpoint_prompts_before_endpoint_continue(self):
        order = []

        class Events:
            @staticmethod
            def send(value):
                order.append(("send", value))

        lifecycle = object.__new__(DistributedLifecycle)
        lifecycle.session = {
            "switch_role": "a_room_joiner", "test_id": "test-1",
        }
        lifecycle.run_context = {"run_id": RUN_ID}
        lifecycle.last_gate = "C0_DATA_PLANE_PROVEN"
        lifecycle.control = FakeControl()
        lifecycle.timeout = 1
        lifecycle._continue_checkpoint(Events(), {
            "event": "user_checkpoint", "checkpoint": "CREATE_SWITCH_ROOM",
            "run_id": RUN_ID,
        })
        self.assertEqual(lifecycle.control.calls[0][0:2], ("continue", "CREATE_SWITCH_ROOM"))
        self.assertEqual([item[0] for item in order], ["send"])
        self.assertEqual(order[0][1], {
            "action": "continue_checkpoint", "checkpoint": "CREATE_SWITCH_ROOM",
            "run_id": RUN_ID,
        })

        with self.assertRaisesRegex(Exception, "changed run or role identity"):
            lifecycle._continue_checkpoint(Events(), {
                "event": "user_checkpoint", "checkpoint": "JOIN_SWITCH_GROUP",
                "run_id": RUN_ID,
            })

    def test_heartbeat_retries_only_explicit_room_version_conflict(self):
        class Relay:
            def __init__(self):
                self.commands = 0
                self.version = 1

            def room(self, _room_id, _member_token):
                return {"room_version": self.version}

            def room_command(self, *_args, **_kwargs):
                self.commands += 1
                if self.commands == 1:
                    self.version = 2
                    raise RelayError(
                        "room version conflict", status=409, code="room_version_conflict")
                self.version = 3
                return {"room_version": self.version}

        relay = Relay()
        lifecycle = DistributedLifecycle(
            coordinator=object(), relay=relay,
            session={
                "room_id": ROOM_ID, "member_token": "token",
                "switch_role": "a_room_joiner",
            },
            session_path=Path("unused.json"), distro="SwitchTrade",
            packaged_python="/opt/switchtrade/python", runtime_root="/opt/switchtrade",
            control=FakeControl(),
        )
        self.assertTrue(lifecycle._heartbeat(force=True))
        self.assertEqual(relay.commands, 2)
        self.assertEqual(lifecycle.room["room_version"], 3)

    def test_pairing_checkpoint_precedes_hardware_and_revalidates_two_members(self):
        room = {
            "contract_version": "room-control.v1", "room_id": ROOM_ID,
            "room_code": "ABC123", "visibility": "private", "room_version": 2,
            "local_member_id": "member-a",
            "members": [
                {"member_id": "member-a", "seat": "member_a", "online_state": "online"},
                {"member_id": "member-b", "seat": "member_b", "online_state": "online"},
            ],
        }

        class Relay:
            def __init__(self):
                self.heartbeats = 0

            def room(self, _room_id, _member_token):
                return room

            def room_command(self, *_args, **_kwargs):
                self.heartbeats += 1
                return room

        relay = Relay()
        lifecycle = DistributedLifecycle(
            coordinator=object(), relay=relay,
            session={
                "room_id": ROOM_ID, "room_code": "ABC123", "member_token": "token",
                "switch_role": "a_room_joiner", "test_id": "test-1", "owner": True,
            },
            session_path=Path("unused.json"), distro="SwitchTrade",
            packaged_python="/opt/switchtrade/python", runtime_root="/opt/switchtrade",
            control=FakeControl(), timeout=1,
        )
        with patch("builtins.input", side_effect=AssertionError("stdin must not be used")):
            lifecycle.confirm_pairing()
        checkpoint = next(call for call in lifecycle.control.calls if call[0] == "continue")
        self.assertEqual(checkpoint[1], "PAIRING_CONFIRMED")
        self.assertEqual(checkpoint[2]["run_id"], None)
        self.assertEqual(checkpoint[2]["timeout"], 1)
        self.assertTrue(callable(checkpoint[2]["heartbeat"]))

    def test_abort_preserves_recovery_until_local_cleanup_and_authority_release(self):
        room = {"room_version": 2}

        class Relay:
            def __init__(self):
                self.commands = 0

            @staticmethod
            def room(_room_id, _member_token):
                return room

            def room_command(self, *_args, **_kwargs):
                self.commands += 1
                return {"room_version": 3}

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "distributed-session.json"
            path.write_text("{}", encoding="utf-8")
            relay = Relay()
            lifecycle = DistributedLifecycle(
                coordinator=object(), relay=relay,
                session={
                    "room_id": ROOM_ID, "room_code": "ABC123", "member_token": "token",
                    "switch_role": "a_room_joiner", "test_id": "test-1", "owner": True,
                },
                session_path=path, distro="SwitchTrade",
                packaged_python="/opt/switchtrade/python", runtime_root="/opt/switchtrade",
                control=FakeControl(),
            )
            retained = lifecycle.abort(cleanup_verified=False)
            self.assertEqual(retained, {"authority_released": False, "session_retained": True})
            self.assertEqual(relay.commands, 0)
            self.assertTrue(path.exists())

            released = lifecycle.abort(cleanup_verified=True)
            self.assertTrue(released["authority_released"])
            self.assertTrue(path.exists())
            self.assertEqual(lifecycle.finalize_abort(released), {"session_removed": True})
            self.assertFalse(path.exists())

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

    def test_stage_failure_preserves_stable_code_gate_and_message(self):
        class Stage:
            session_handler = None

            @staticmethod
            async def run():
                return ({
                    "status": "failed",
                    "failure": {
                        "code": "A_ROOM_NOT_OBSERVED",
                        "gate": "A1_ROOM_DETECTION",
                        "message": "no Nintendo LDN room was observed",
                    },
                }, None)

        session = StageSession(Stage(), timeout=1, stop_timeout=1).start()
        with self.assertRaises(StageSessionError) as raised:
            session.wait_ready()
        self.assertEqual(raised.exception.code, "A_ROOM_NOT_OBSERVED")
        self.assertEqual(raised.exception.gate, "A1_ROOM_DETECTION")
        self.assertEqual(
            raised.exception.message, "no Nintendo LDN room was observed",
        )
        self.assertIsNone(raised.exception.last_passed_gate)
        session.stop()


if __name__ == "__main__":
    unittest.main()
