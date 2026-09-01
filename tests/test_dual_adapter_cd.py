import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from switchtrade.connection.b_fixture import FIXTURE, FIXTURE_ID, FIXTURE_SHA256
from switchtrade.connection.dual_adapter_cd import (
    CHALLENGE_BYTES,
    CONTRACT_VERSION,
    SuiteContractError,
    SuitePhase,
    SwitchlessCdState,
    challenge_evidence,
    new_challenge,
    validate_adapter_pair,
)
from switchtrade.connection.dual_adapter_cd_harness import (
    AUTHORITY_SUCCESS_OUTCOME,
    COMMAND_CONTRACT,
    WORKER_CONTRACT,
    SwitchlessHarnessError,
    _WorkerStatus,
    _command,
    _p0,
    _side_config,
    _worker_argv,
    _worker_config,
    run_software,
)
from switchtrade.connection.dual_adapter_radio import (
    AttachDeltaResolver, DualRadioOwner, requested_adapter_pair,
)
from switchtrade.connection.p0 import P0Error, USB_ID, UsbAdapter, UsbLease


class DualUsbRunner:
    """Model two identical USB radios with distinct stable Windows identities."""

    def __init__(self, adapters: tuple[UsbAdapter, UsbAdapter]):
        self.adapters = adapters
        self.attached = {adapter.bus_id: False for adapter in adapters}
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], _timeout: float):
        self.calls.append(list(command))
        if command[:2] == ["usbipd.exe", "state"]:
            devices = [{
                "BusId": adapter.bus_id,
                "InstanceId": adapter.instance_id,
                "PersistedGuid": f"shared-{adapter.bus_id}",
                "ClientIPAddress": (
                    "172.30.0.1" if self.attached[adapter.bus_id] else None
                ),
            } for adapter in self.adapters]
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"Devices": devices}), "",
            )
        if command[0] == "modprobe" or "modprobe" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] in (
            ["usbipd.exe", "attach"], ["usbipd.exe", "detach"],
        ):
            bus_id = command[command.index("--busid") + 1]
            self.attached[bus_id] = command[1] == "attach"
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)

    def count(self, operation: str, bus_id: str) -> int:
        return sum(
            call[:2] == ["usbipd.exe", operation] and
            call[call.index("--busid") + 1] == bus_id
            for call in self.calls
            if "--busid" in call
        )


class ExactLinuxProbe:
    def __init__(self, runner: DualUsbRunner, identities: dict[str, str]):
        self.runner = runner
        self.identities = identities
        self.targets: list[str] = []

    def __call__(self, target: str) -> dict:
        self.targets.append(target)
        if target == USB_ID:
            matches = sum(self.runner.attached.values())
        else:
            bus_id = self.identities.get(target)
            if bus_id is None:
                return {
                    "status": "unknown", "matches": None,
                    "interface_present": None, "phy_present": None,
                    "interfaces_up": None,
                }
            matches = int(self.runner.attached[bus_id])
        return {
            "status": "present" if matches else "absent",
            "matches": matches,
            "interface_present": bool(matches),
            "phy_present": bool(matches),
            "interfaces_up": 0,
        }


class SwitchlessCdContractTests(unittest.TestCase):
    @staticmethod
    def adapter(identity: str, *, shared: bool = True,
                attached: bool = False, usb_id: str = USB_ID) -> UsbAdapter:
        return UsbAdapter(
            usb_id=usb_id,
            instance_id=f"USB\\VID_0BDA&PID_818B\\SYNTHETIC-{identity}",
            bus_id=f"2-{identity}",
            shared=shared,
            attached=attached,
        )

    def state(self) -> SwitchlessCdState:
        return SwitchlessCdState(
            str(uuid.uuid4()), "beta-test",
            self.adapter("14"), self.adapter("18"),
        )

    @staticmethod
    def reach_c2(state: SwitchlessCdState) -> None:
        for phase in (
            SuitePhase.PASSIVE_PREFLIGHT,
            SuitePhase.ACQUIRING_A,
            SuitePhase.ACQUIRING_B,
            SuitePhase.P0_READY,
            SuitePhase.AUTHORITY_LOCKED,
            SuitePhase.C0,
            SuitePhase.C1,
            SuitePhase.C2,
        ):
            state.advance(phase)

    def test_fixture_reuses_the_immutable_package_owned_advertisement(self):
        record = self.state().snapshot()
        self.assertEqual(record["fixture"]["id"], FIXTURE_ID)
        self.assertEqual(record["fixture"]["advertisement_bytes"], len(FIXTURE))
        self.assertEqual(record["fixture"]["advertisement_sha256"], FIXTURE_SHA256)
        self.assertEqual(hashlib.sha256(FIXTURE).hexdigest(), FIXTURE_SHA256)
        self.assertEqual(record["fixture"]["rfu_payload"], "per-run-random")

    def test_challenge_report_contains_only_length_and_hash(self):
        challenge = new_challenge()
        evidence = challenge_evidence(challenge)
        self.assertEqual(len(challenge), CHALLENGE_BYTES)
        self.assertEqual(evidence, {
            "bytes": CHALLENGE_BYTES,
            "sha256": hashlib.sha256(challenge).hexdigest(),
        })
        self.assertNotIn(challenge.hex(), json.dumps(evidence))

    def test_pair_requires_two_distinct_authorized_windows_owned_adapters(self):
        room = self.adapter("14")
        validate_adapter_pair(room, self.adapter("18"))
        cases = (
            (room, room, "CD_ADAPTER_IDENTITY_DUPLICATE"),
            (room, self.adapter("18", shared=False), "CD_ADAPTER_NOT_AUTHORIZED"),
            (room, self.adapter("18", attached=True), "CD_ADAPTER_NOT_WINDOWS_OWNED"),
            (room, self.adapter("18", usb_id="1234:5678"), "CD_ADAPTER_PROFILE_UNSUPPORTED"),
        )
        for first, second, code in cases:
            with self.subTest(code=code), self.assertRaises(SuiteContractError) as caught:
                validate_adapter_pair(first, second)
            self.assertEqual(caught.exception.code, code)

    def test_status_snapshot_is_deeply_read_only_and_does_not_advance_revision(self):
        state = self.state()
        first = state.snapshot()
        first["phase"] = "terminal"
        first["sides"]["room_side"]["cleanup_verified"] = True
        second = state.snapshot()
        third = state.snapshot()
        self.assertEqual(second, third)
        self.assertEqual(second["phase"], "created")
        self.assertFalse(second["sides"]["room_side"]["cleanup_verified"])
        self.assertEqual(second["revision"], 1)

    def test_normal_result_is_not_passed_until_both_sides_and_authority_clean(self):
        state = self.state()
        self.reach_c2(state)
        state.pass_gate("room_side", "C_SYNTHETIC_RFU_PROVEN")
        state.begin_closing("passed")
        state.begin_cleanup()
        state.mark_authority_cleanup()
        state.mark_side_cleanup("ap_side")
        with self.assertRaises(SuiteContractError) as caught:
            state.finish_cleanup(True)
        self.assertEqual(caught.exception.code, "CD_CLEANUP_UNVERIFIED")
        state.mark_side_cleanup("room_side")
        terminal = state.finish_cleanup(True)
        self.assertEqual(terminal["phase"], "terminal")
        self.assertEqual(terminal["functional_status"], "passed")
        self.assertEqual(terminal["cleanup_status"], "verified")
        self.assertEqual(terminal["status"], "passed")
        self.assertFalse(terminal["recovery_required"])

    def test_cleanup_failure_preserves_the_primary_c_failure(self):
        state = self.state()
        state.advance(SuitePhase.PASSIVE_PREFLIGHT)
        state.begin_closing(
            "failed", code="C_PROBE_TIMEOUT", gate="C0_DATA_PLANE_PROVEN",
            message="two-way nonce did not complete",
        )
        state.begin_cleanup()
        terminal = state.finish_cleanup(
            False, code="CD_CLEANUP_UNKNOWN", gate="D10_USB_RETURN",
            message="adapter absence is unknown",
        )
        self.assertEqual(terminal["primary_failure"]["code"], "C_PROBE_TIMEOUT")
        self.assertEqual(terminal["secondary_failures"][0]["code"], "CD_CLEANUP_UNKNOWN")
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["cleanup_status"], "failed")
        self.assertTrue(terminal["recovery_required"])

    def test_schema_matches_projection_and_projection_contains_no_raw_instance_id(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((
            root / "contracts" / "abcd" /
            "single-pc-dual-adapter-cd.v1.schema.json"
        ).read_text(encoding="utf-8"))
        record = self.state().snapshot()
        self.assertEqual(set(record), set(schema["required"]))
        self.assertEqual(record["contract_version"], CONTRACT_VERSION)
        self.assertIn(record["phase"], schema["properties"]["phase"]["enum"])
        serialized = json.dumps(record, sort_keys=True)
        self.assertNotIn("SYNTHETIC-14", serialized)
        self.assertNotIn("SYNTHETIC-18", serialized)
        for side in record["sides"].values():
            self.assertRegex(side["adapter_identity_sha256"], r"^[0-9a-f]{64}$")

    def test_transition_order_fails_closed(self):
        state = self.state()
        with self.assertRaises(SuiteContractError) as caught:
            state.advance(SuitePhase.ACQUIRING_A)
        self.assertEqual(caught.exception.code, "CD_TRANSITION_INVALID")
        self.assertEqual(state.snapshot()["phase"], "created")

    def test_overall_pass_is_rejected_before_c2(self):
        state = self.state()
        state.advance(SuitePhase.PASSIVE_PREFLIGHT)
        with self.assertRaises(SuiteContractError) as caught:
            state.begin_closing("passed")
        self.assertEqual(caught.exception.code, "CD_PASS_PREMATURE")
        self.assertEqual(state.snapshot()["status"], "running")


class ExactUsbLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.room = SwitchlessCdContractTests.adapter("14")
        self.ap = SwitchlessCdContractTests.adapter("18")
        self.runner = DualUsbRunner((self.room, self.ap))
        self.linux_identities = {
            "/sys/devices/platform/vhci_hcd.0/usb1/1-1": self.room.bus_id,
            "/sys/devices/platform/vhci_hcd.0/usb2/2-1": self.ap.bus_id,
        }
        self.probe = ExactLinuxProbe(self.runner, self.linux_identities)

    def tearDown(self):
        self.temporary.cleanup()

    def lease(self, adapter: UsbAdapter, linux_identity: str) -> UsbLease:
        return UsbLease(
            adapter,
            self.root / f"{adapter.bus_id}-recovery.json",
            runner=self.runner,
            probe=self.probe,
            identity_resolver=lambda _adapter: linux_identity,
            deadline=1,
        )

    def test_two_identical_radios_are_probed_and_released_by_exact_identity(self):
        room_identity, ap_identity = tuple(self.linux_identities)
        room = self.lease(self.room, room_identity)
        ap = self.lease(self.ap, ap_identity)

        room_evidence = room.acquire()
        ap_evidence = ap.acquire()
        self.assertNotEqual(
            room_evidence["linux_identity_sha256"],
            ap_evidence["linux_identity_sha256"],
        )
        self.assertNotIn(room_identity, json.dumps(room_evidence))
        self.assertNotIn(ap_identity, json.dumps(ap_evidence))
        self.assertNotIn(USB_ID, self.probe.targets)

        ap.release()
        room.release()
        for adapter in (self.room, self.ap):
            self.assertEqual(self.runner.count("attach", adapter.bus_id), 1)
            self.assertEqual(self.runner.count("detach", adapter.bus_id), 1)
            self.assertFalse(self.runner.attached[adapter.bus_id])

    def test_default_single_adapter_public_and_recovery_shapes_are_unchanged(self):
        recovery_file = self.root / "legacy-shape.json"
        lease = UsbLease(
            self.room, recovery_file, runner=self.runner, probe=self.probe,
            deadline=1,
        )
        evidence = lease.acquire()
        self.assertEqual(set(evidence), {
            "adapter_instance_sha256", "usb_id", "bus_id", "prior_attached",
            "acquired_by_run", "active",
        })
        recovery = json.loads(recovery_file.read_text(encoding="utf-8"))
        self.assertEqual(set(recovery), {
            "schema", "usb_id", "instance_id", "bus_id", "prior_attached",
            "attach_intent", "acquired_by_run",
        })
        lease.release()

    def test_exact_linux_identity_survives_private_recovery_only(self):
        room_identity = next(iter(self.linux_identities))
        lease = self.lease(self.room, room_identity)
        evidence = lease.acquire()
        recovery_file = lease.recovery_file
        recovery = json.loads(recovery_file.read_text(encoding="utf-8"))
        self.assertEqual(recovery["linux_identity"], room_identity)
        self.assertNotIn("linux_identity", evidence)
        self.assertNotIn(room_identity, json.dumps(evidence))

        recovered = UsbLease.from_recovery(
            recovery_file, runner=self.runner, probe=self.probe, deadline=1,
        )
        recovered.release()
        self.assertFalse(recovery_file.exists())
        self.assertFalse(self.runner.attached[self.room.bus_id])

    def test_identity_resolution_failure_leaves_recoverable_guard(self):
        recovery_file = self.root / "failed-resolution.json"
        room_identity, ap_identity = tuple(self.linux_identities)
        room_lease = self.lease(self.room, room_identity)
        room_lease.acquire()

        def unavailable(_adapter: UsbAdapter) -> str:
            raise ValueError("synthetic resolver failure")

        lease = UsbLease(
            self.ap, recovery_file, runner=self.runner, probe=self.probe,
            identity_resolver=unavailable, deadline=1,
        )
        with self.assertRaises(P0Error) as caught:
            lease.acquire()
        self.assertEqual(caught.exception.code, "P0_LINUX_IDENTITY_UNAVAILABLE")
        self.assertTrue(recovery_file.exists())
        self.assertTrue(self.runner.attached[self.room.bus_id])
        self.assertTrue(self.runner.attached[self.ap.bus_id])

        ambiguous = UsbLease.from_recovery(
            recovery_file, runner=self.runner, probe=self.probe, deadline=1,
        )
        with self.assertRaises(P0Error) as recovery_error:
            ambiguous.release()
        self.assertEqual(
            recovery_error.exception.code, "P0_LINUX_IDENTITY_UNAVAILABLE",
        )
        self.assertTrue(recovery_file.exists())
        self.assertTrue(self.runner.attached[self.ap.bus_id])

        UsbLease.from_recovery(
            recovery_file, runner=self.runner, probe=self.probe,
            identity_resolver=lambda _adapter: ap_identity, deadline=1,
        ).release()
        self.assertFalse(recovery_file.exists())
        self.assertFalse(self.runner.attached[self.ap.bus_id])
        self.assertTrue(self.runner.attached[self.room.bus_id])
        room_lease.release()
        self.assertFalse(self.runner.attached[self.room.bus_id])

    def test_invalid_identity_fails_closed_and_remains_recoverable(self):
        recovery_file = self.root / "invalid-identity.json"
        lease = UsbLease(
            self.room, recovery_file, runner=self.runner, probe=self.probe,
            identity_resolver=lambda _adapter: "relative/linux/path", deadline=1,
        )
        with self.assertRaises(P0Error) as caught:
            lease.acquire()
        self.assertEqual(caught.exception.code, "P0_LINUX_IDENTITY_INVALID")
        self.assertTrue(recovery_file.exists())

        UsbLease.from_recovery(
            recovery_file, runner=self.runner, probe=self.probe,
            identity_resolver=lambda _adapter: next(iter(self.linux_identities)),
            deadline=1,
        ).release()
        self.assertFalse(recovery_file.exists())


class DualRadioOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.room = SwitchlessCdContractTests.adapter("14")
        self.ap = SwitchlessCdContractTests.adapter("18")
        self.runner = DualUsbRunner((self.room, self.ap))
        self.identity_by_bus = {
            self.room.bus_id: "/sys/bus/usb/devices/1-1",
            self.ap.bus_id: "/sys/bus/usb/devices/2-1",
        }
        self.probe = ExactLinuxProbe(
            self.runner,
            {identity: bus for bus, identity in self.identity_by_bus.items()},
        )

    def tearDown(self):
        self.temporary.cleanup()

    def inventory(self):
        return tuple(sorted(
            self.identity_by_bus[bus]
            for bus, attached in self.runner.attached.items() if attached
        ))

    def lease_factory(self, adapter, recovery, resolver):
        return UsbLease(
            adapter, recovery, runner=self.runner, probe=self.probe,
            identity_resolver=resolver, deadline=1,
        )

    def owner(self):
        return DualRadioOwner(
            (self.room, self.ap), self.root / "state",
            inventory=self.inventory, probe=self.probe,
            lease_factory=self.lease_factory, lock_root=self.root / "locks",
        )

    def test_two_exact_radios_acquire_in_role_order_and_release_in_reverse(self):
        owner = self.owner()
        evidence = owner.acquire()
        self.assertTrue(evidence["distinct_windows_identities"])
        self.assertTrue(evidence["distinct_linux_identities"])
        self.assertTrue(evidence["leases_active"])
        self.assertEqual(len(evidence["linux_identity_sha256"]), 2)
        cleanup = owner.release()
        self.assertTrue(cleanup["verified"])
        self.assertEqual(cleanup["release_order"], [
            self.ap.instance_sha256, self.room.instance_sha256,
        ])
        detach_calls = [
            call[call.index("--busid") + 1] for call in self.runner.calls
            if call[:2] == ["usbipd.exe", "detach"]
        ]
        self.assertEqual(detach_calls, [self.ap.bus_id, self.room.bus_id])
        self.assertFalse(any(self.runner.attached.values()))

    def test_attach_delta_rejects_ambiguity_and_disappearance(self):
        with self.assertRaises(P0Error) as ambiguous:
            AttachDeltaResolver((), lambda: ("/sys/a", "/sys/b"), timeout=0.1)(self.room)
        self.assertEqual(ambiguous.exception.code, "CD_LINUX_ATTACH_AMBIGUOUS")
        with self.assertRaises(P0Error) as changed:
            AttachDeltaResolver(("/sys/a",), lambda: (), timeout=0.1)(self.room)
        self.assertEqual(changed.exception.code, "CD_LINUX_IDENTITY_CHANGED")

    def test_second_attach_failure_recovers_first_and_releases_all_locks(self):
        calls = 0

        def inventory():
            nonlocal calls
            calls += 1
            current = list(self.inventory())
            if self.runner.attached[self.ap.bus_id]:
                return tuple(item for item in current if item != self.identity_by_bus[self.ap.bus_id])
            return tuple(current)

        owner = DualRadioOwner(
            (self.room, self.ap), self.root / "failed-state",
            inventory=inventory, probe=self.probe,
            lease_factory=self.lease_factory, lock_root=self.root / "failed-locks",
        )
        with self.assertRaises(P0Error) as caught:
            owner.acquire()
        self.assertEqual(caught.exception.code, "CD_LINUX_ATTACH_DELTA_MISSING")
        self.assertGreater(calls, 1)
        self.assertTrue(all(self.runner.attached.values()))
        self.assertTrue(owner.retry_recovery(inventory=self.inventory)["verified"])
        self.assertFalse(any(self.runner.attached.values()))
        replacement = DualRadioOwner(
            (self.room, self.ap), self.root / "retry-state",
            inventory=self.inventory, probe=self.probe,
            lease_factory=self.lease_factory, lock_root=self.root / "failed-locks",
        )
        self.assertTrue(replacement.acquire()["leases_active"])
        self.assertTrue(replacement.release()["verified"])

    def test_pair_resolution_never_uses_bus_enumeration_order(self):
        first, second = requested_adapter_pair([self.ap, self.room])
        self.assertEqual(
            (first.instance_sha256, second.instance_sha256),
            tuple(sorted((self.room.instance_sha256, self.ap.instance_sha256))),
        )


class SwitchlessSoftwareWorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "비공개 상태"
        self.root.mkdir()
        self.config_file = self.root / "config.json"
        self.config = {
            "contract_version": WORKER_CONTRACT,
            "relay_url": "https://relay.example.invalid",
            "room_code": "ABC123",
            "attempt_id": "attempt-1",
            "source_seat": "member_a",
            "switch_role": "a_room_joiner",
            "member_token": "secret-member-token",
            "run_id": str(uuid.uuid4()),
            "stage_generation": 1,
            "launch_nonce": "n" * 32,
            "activation_generation": 1,
            "local_payload": base64.b64encode(b"x" * 32).decode("ascii"),
            "peer_payload_sha256": "a" * 64,
            "status_file": str(self.root / "status.json"),
            "command_file": str(self.root / "command.json"),
        }
        self.config_file.write_text(
            json.dumps(self.config), encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_config_is_strict_and_decodes_exact_payload(self):
        loaded = _worker_config(self.config_file)
        self.assertEqual(loaded["local_payload_bytes"], b"x" * 32)
        invalid = dict(self.config, unexpected=True)
        self.config_file.write_text(json.dumps(invalid), encoding="utf-8")
        with self.assertRaises(SwitchlessHarnessError) as caught:
            _worker_config(self.config_file)
        self.assertEqual(caught.exception.code, "CD_WORKER_CONFIG_INVALID")

    def test_integrated_software_rejects_duplicate_p0_identity_before_relay(self):
        proof = _p0(str(uuid.uuid4()), "a", "release-a")
        with self.assertRaises(SwitchlessHarnessError) as caught:
            run_software(
                "https://relay.example.invalid", self.root / "invalid-integrated",
                p0_proofs=(proof, dict(proof)),
            )
        self.assertEqual(caught.exception.code, "CD_P0_ATTESTATION_INVALID")

    def test_worker_status_is_redacted_and_command_is_identity_bound(self):
        status = _WorkerStatus(Path(self.config["status_file"]), self.config)
        status.write("awaiting_activation", "C1_ADVERTISEMENT_DELIVERED", evidence={
            "advertisement_sha256": FIXTURE_SHA256,
        })
        serialized = Path(self.config["status_file"]).read_text(encoding="utf-8")
        self.assertNotIn(self.config["member_token"], serialized)
        self.assertNotIn(self.config["local_payload"], serialized)

        Path(self.config["command_file"]).write_text(json.dumps({
            "contract_version": COMMAND_CONTRACT,
            "run_id": self.config["run_id"],
            "attempt_id": self.config["attempt_id"],
            "action": "activate",
        }), encoding="utf-8")
        self.assertEqual(_command(self.config), "activate")
        command = json.loads(Path(self.config["command_file"]).read_text(encoding="utf-8"))
        command["run_id"] = str(uuid.uuid4())
        Path(self.config["command_file"]).write_text(json.dumps(command), encoding="utf-8")
        with self.assertRaises(SwitchlessHarnessError) as caught:
            _command(self.config)
        self.assertEqual(caught.exception.code, "CD_COMMAND_INVALID")

    def test_worker_argv_uses_the_canonical_module_when_parent_is_main(self):
        argv = _worker_argv(self.config_file)
        self.assertEqual(
            argv[argv.index("-m") + 1],
            "switchtrade.connection.dual_adapter_cd_harness",
        )
        self.assertNotIn("__main__", argv)

    def test_one_side_run_identity_drives_p0_and_worker_launch(self):
        run_id = str(uuid.uuid4())
        proof = _p0(run_id, "a", "q2-test")
        side = _side_config(
            self.root, "side-a", relay_url=self.config["relay_url"],
            room_code=self.config["room_code"], attempt_id=self.config["attempt_id"],
            token=self.config["member_token"], seat="member_a", role="a_room_joiner",
            run_id=run_id, activation_generation=1,
            local_payload=b"a" * 32, peer_payload=b"b" * 32,
        )
        self.assertEqual(proof["run_id"], side["run_id"])
        self.assertEqual(proof["stage_generation"], side["stage_generation"])

    def test_synthetic_success_never_claims_a_completed_physical_trade(self):
        self.assertEqual(AUTHORITY_SUCCESS_OUTCOME, "canceled")
        self.assertNotEqual(AUTHORITY_SUCCESS_OUTCOME, "completed")


if __name__ == "__main__":
    unittest.main()
