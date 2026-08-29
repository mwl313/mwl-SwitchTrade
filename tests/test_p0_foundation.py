from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from switchtrade.connection.coordinator import ConnectionCoordinator, Phase, RunMode
from switchtrade.connection.p0 import (
    P0Error, PassiveValidator, USB_ID, UsbLease, _decode_native_output, parse_usbipd_state,
)
from switchtrade.connection.p0_harness import (
    P0Harness, _installed_release, _wsl_linux_usb_probe, _wsl_netdev_exists,
    _wsl_process_start_ticks,
)
from switchtrade.connection.radio_worker import (
    REQUIRED_MODULES, RadioWorkerError, _validate_ticket, build_side_ready,
)
from switchtrade.connection.runtime_probe import RuntimeProbeError, _verify_channel
from switchtrade.connection.runtime_probe import REQUIRED_MODULES as PASSIVE_REQUIRED_MODULES


INSTANCE = r"USB\VID_0BDA&PID_818B\RADIO-A"


def completed(command, stdout="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def usb_state(*, attached=False, bus_id="4-18", instance=INSTANCE, shared=True):
    return json.dumps({"Devices": [{
        "BusId": bus_id,
        "InstanceId": instance,
        "PersistedGuid": "shared" if shared else None,
        "ClientIPAddress": "172.30.0.1" if attached else None,
    }]})


class FakeRunner:
    def __init__(self, runtime, *, attached=False):
        self.runtime = runtime
        self.attached = attached
        self.calls = []

    def __call__(self, command, timeout):
        self.calls.append((list(command), timeout))
        if command[:2] == ["wsl.exe", "--version"]:
            return completed(command, "WSL version: 2.4.4\n")
        if command[:2] == ["usbipd.exe", "--version"]:
            return completed(command, "5.3.0\n")
        if command[:2] == ["usbipd.exe", "state"]:
            return completed(command, usb_state(attached=self.attached))
        if "switchtrade.connection.runtime_probe" in command:
            return completed(command, json.dumps(self.runtime))
        raise AssertionError(f"unexpected command: {command}")


class PassiveP0Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.selection = self.root / "hardware-selection.json"
        self.selection.write_text(json.dumps({
            "schema": 1, "usb_id": USB_ID, "instance_id": INSTANCE, "bus_id": "old-bus",
        }), encoding="utf-8")
        self.runtime = {
            "contract_version": "p0-runtime-passive.v1",
            "schema": 1,
            "release": "release-a",
            "status": "passed",
            "attached_usb_matches": 0,
            "checks": {"payload_hashes": True},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def validator(self, runner):
        return PassiveValidator(
            release="release-a", selection_file=self.selection,
            relay_health=lambda: {
                "status": "ready", "room_contract": "room-control.v1",
                "rfu_contract": "rfu-tunnel.v1",
                "capabilities": ["passive-websocket-health.v1"],
                "server_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            relay_websocket_health=lambda: True,
            runner=runner,
        )

    def test_passive_validation_resolves_exact_instance_and_never_mutates_usb(self):
        runner = FakeRunner(self.runtime)
        adapter, report = self.validator(runner).validate()
        self.assertEqual(adapter.instance_id, INSTANCE)
        self.assertEqual(adapter.bus_id, "4-18")
        self.assertEqual(report["adapter"]["instance_sha256"], hashlib.sha256(
            INSTANCE.casefold().encode()).hexdigest())
        flattened = [item for command, _ in runner.calls for item in command]
        self.assertNotIn("attach", flattened)
        self.assertNotIn("detach", flattened)
        self.assertNotIn("modprobe", flattened)

    def test_passive_validation_rejects_adapter_attached_outside_active_distro(self):
        runner = FakeRunner({**self.runtime, "attached_usb_matches": 0}, attached=True)
        with self.assertRaises(P0Error) as caught:
            self.validator(runner).validate()
        self.assertEqual(caught.exception.code, "P0_ADAPTER_OWNED_ELSEWHERE")

    def test_blocking_recovery_fails_before_any_external_probe(self):
        guard = self.root / "recovery.json"
        guard.write_text("{}", encoding="utf-8")
        runner = FakeRunner(self.runtime)
        validator = self.validator(runner)
        validator.blocking_state_paths = (guard,)
        with self.assertRaises(P0Error) as caught:
            validator.validate()
        self.assertEqual(caught.exception.code, "P0_RECOVERY_REQUIRED")
        self.assertEqual(runner.calls, [])

    def test_windows_harness_reads_release_marker_inside_selected_wsl_runtime(self):
        calls = []

        def runner(command, timeout):
            calls.append((command, timeout))
            return completed(command, json.dumps({
                "schema": 1, "release_id": "abcd-m2-test",
            }))

        with mock.patch("switchtrade.connection.p0_harness.os.name", "nt"):
            release = _installed_release("/opt/switchtrade", "SwitchTrade-test", runner)

        self.assertEqual(release, "abcd-m2-test")
        self.assertEqual(calls, [([
            "wsl.exe", "-d", "SwitchTrade-test", "-u", "root", "--",
            "cat", "/opt/switchtrade/.switchtrade-release.json",
        ], 10)])

    def test_native_output_decoder_accepts_wsl_utf16_and_usbipd_utf8(self):
        self.assertEqual(_decode_native_output("WSL version: 2.7.12.0\r\n".encode("utf-16-le")),
                         "WSL version: 2.7.12.0\r\n")
        self.assertEqual(_decode_native_output(b'{"Devices":[]}'), '{"Devices":[]}')

    def test_passive_channel_check_does_not_require_loaded_cfg80211(self):
        _verify_channel(1)
        _verify_channel(13)
        for channel in (0, 14):
            with self.assertRaises(RuntimeProbeError) as caught:
                _verify_channel(channel)
            self.assertEqual(caught.exception.code, "P0_CHANNEL_INVALID")

    def test_windows_usb_probe_runs_inside_selected_wsl_runtime(self):
        calls = []

        def runner(command, timeout):
            calls.append((command, timeout))
            return completed(command, json.dumps({
                "status": "absent", "matches": 0, "interface_present": False,
                "phy_present": False, "interfaces_up": 0,
            }))

        value = _wsl_linux_usb_probe(
            USB_ID, distro="SwitchTrade-test", packaged_python="/runtime/python", runner=runner)

        self.assertEqual(value["status"], "absent")
        self.assertEqual(calls[0][0][:7], [
            "wsl.exe", "-d", "SwitchTrade-test", "-u", "root", "--", "/runtime/python",
        ])
        self.assertEqual(calls[0][0][-1], USB_ID)

    def test_windows_recovery_probes_process_and_netdev_in_selected_wsl_runtime(self):
        calls = []

        def runner(command, timeout):
            calls.append((command, timeout))
            return completed(command, "12345" if command[-1] == "74" else "true")

        self.assertEqual(_wsl_process_start_ticks(
            74, distro="SwitchTrade-test", packaged_python="/runtime/python", runner=runner,
        ), 12345)
        self.assertTrue(_wsl_netdev_exists(
            "wlan0", distro="SwitchTrade-test", packaged_python="/runtime/python", runner=runner,
        ))
        for command, _timeout in calls:
            self.assertEqual(command[:7], [
                "wsl.exe", "-d", "SwitchTrade-test", "-u", "root", "--", "/runtime/python",
            ])

    def test_passive_and_active_module_identities_use_kernel_names(self):
        self.assertEqual(PASSIVE_REQUIRED_MODULES, REQUIRED_MODULES)


class StatefulUsbRunner:
    def __init__(self, *, attached=False, fail_attach=False, missing_state_reads_after_detach=0):
        self.attached = attached
        self.fail_attach = fail_attach
        self.missing_state_reads_after_detach = missing_state_reads_after_detach
        self.bus_id = "4-18"
        self.calls = []

    def __call__(self, command, timeout):
        self.calls.append(list(command))
        if command[:2] == ["usbipd.exe", "state"]:
            if not self.attached and self.missing_state_reads_after_detach > 0:
                self.missing_state_reads_after_detach -= 1
                return completed(command, json.dumps({"Devices": []}))
            return completed(command, usb_state(attached=self.attached, bus_id=self.bus_id))
        if command[0] == "modprobe" or "modprobe" in command:
            return completed(command)
        if command[:2] == ["usbipd.exe", "attach"]:
            if self.fail_attach:
                return subprocess.CompletedProcess(command, 1, "", "usbip: error: Attach Request for inactive port")
            self.attached = True
            return completed(command)
        if command[:2] == ["usbipd.exe", "detach"]:
            self.attached = False
            return completed(command)
        raise AssertionError(command)


class UsbLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def adapter(attached=False):
        return parse_usbipd_state(usb_state(attached=attached))[0]

    def test_detached_adapter_is_attached_and_detached_exactly_once(self):
        runner = StatefulUsbRunner()
        probe = lambda _usb: {
            "status": "present" if runner.attached else "absent",
            "matches": 1 if runner.attached else 0,
            "interface_present": runner.attached,
            "phy_present": runner.attached,
            "interfaces_up": 0,
        }
        lease = UsbLease(
            self.adapter(), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=1,
        )
        acquired = lease.acquire()
        self.assertTrue(acquired["acquired_by_run"])
        cleanup = lease.release()
        self.assertTrue(cleanup["detached_by_run"])
        self.assertEqual(sum(call[:2] == ["usbipd.exe", "attach"] for call in runner.calls), 1)
        self.assertEqual(sum(call[:2] == ["usbipd.exe", "detach"] for call in runner.calls), 1)
        self.assertTrue(any(call[-4:] == ["modprobe", "-a", "usbip-core", "vhci-hcd"]
                            for call in runner.calls))
        self.assertFalse((self.root / "recovery.json").exists())

    def test_pre_attached_adapter_is_never_detached(self):
        runner = StatefulUsbRunner(attached=True)
        probe = lambda _usb: {
            "status": "present", "matches": 1,
            "interface_present": True, "phy_present": True,
            "interfaces_up": 0,
        }
        lease = UsbLease(
            self.adapter(attached=True), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=1,
        )
        lease.acquire()
        cleanup = lease.release()
        self.assertFalse(cleanup["detached_by_run"])
        self.assertFalse(any(call[:2] == ["usbipd.exe", "attach"] for call in runner.calls))
        self.assertFalse(any(call[:2] == ["usbipd.exe", "detach"] for call in runner.calls))

    def test_post_detach_windows_reenumeration_gap_is_retried(self):
        runner = StatefulUsbRunner()
        probe = lambda _usb: {
            "status": "present" if runner.attached else "absent",
            "matches": 1 if runner.attached else 0,
            "interface_present": runner.attached, "phy_present": runner.attached,
            "interfaces_up": 0,
        }
        lease = UsbLease(
            self.adapter(), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=1,
        )
        lease.acquire()
        runner.missing_state_reads_after_detach = 2

        cleanup = lease.release()

        self.assertTrue(cleanup["prior_state_restored"])
        self.assertTrue(cleanup["windows_state_verified"])
        self.assertFalse((self.root / "recovery.json").exists())

    def test_unknown_linux_cleanup_is_failure_and_keeps_recovery_state(self):
        runner = StatefulUsbRunner()
        ready = True
        def probe(_usb):
            if ready and runner.attached:
                return {
                    "status": "present", "matches": 1, "interface_present": True,
                    "phy_present": True, "interfaces_up": 0,
                }
            return {
                "status": "unknown", "matches": None, "interface_present": None,
                "phy_present": None, "interfaces_up": None,
            }
        lease = UsbLease(
            self.adapter(), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=0.3,
        )
        lease.acquire()
        ready = False
        lease.deadline = 0.01
        with self.assertRaises(P0Error) as caught:
            lease.release()
        self.assertEqual(caught.exception.code, "P0_CLEANUP_UNKNOWN")
        self.assertTrue((self.root / "recovery.json").exists())

    def test_recovery_intent_detaches_only_adapter_that_was_previously_detached(self):
        runner = StatefulUsbRunner(attached=True)
        recovery = self.root / "recovery.json"
        recovery.write_text(json.dumps({
            "schema": 1, "usb_id": USB_ID, "instance_id": INSTANCE, "bus_id": "4-18",
            "prior_attached": False, "attach_intent": True, "acquired_by_run": False,
        }), encoding="utf-8")
        probe = lambda _usb: {
            "status": "present" if runner.attached else "absent",
            "matches": 1 if runner.attached else 0,
            "interface_present": runner.attached, "phy_present": runner.attached,
            "interfaces_up": 0,
        }
        lease = UsbLease.from_recovery(recovery, runner=runner, probe=probe, deadline=1)
        cleanup = lease.release()
        self.assertTrue(cleanup["detached_by_run"])
        self.assertEqual(sum(call[:2] == ["usbipd.exe", "detach"] for call in runner.calls), 1)
        self.assertFalse(recovery.exists())

    def test_radio_must_be_quiescent_before_detach(self):
        runner = StatefulUsbRunner()
        up = False
        def probe(_usb):
            return {
                "status": "present" if runner.attached else "absent",
                "matches": 1 if runner.attached else 0,
                "interface_present": runner.attached, "phy_present": runner.attached,
                "interfaces_up": 1 if up and runner.attached else 0,
            }
        lease = UsbLease(
            self.adapter(), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=1,
        )
        lease.acquire()
        up = True
        with self.assertRaises(P0Error) as caught:
            lease.release()
        self.assertEqual(caught.exception.code, "P0_RADIO_NOT_QUIESCENT")
        self.assertFalse(any(call[:2] == ["usbipd.exe", "detach"] for call in runner.calls))
        self.assertTrue((self.root / "recovery.json").exists())

    def test_bus_identity_change_during_enumeration_fails_closed(self):
        runner = StatefulUsbRunner()
        def probe(_usb):
            if runner.attached:
                runner.bus_id = "4-19"
            return {
                "status": "present" if runner.attached else "absent",
                "matches": 1 if runner.attached else 0,
                "interface_present": runner.attached, "phy_present": runner.attached,
                "interfaces_up": 0,
            }
        lease = UsbLease(
            self.adapter(), self.root / "recovery.json",
            runner=runner, probe=probe, deadline=1,
        )
        with self.assertRaises(P0Error) as caught:
            lease.acquire()
        self.assertEqual(caught.exception.code, "P0_ADAPTER_IDENTITY_CHANGED")

    def test_inactive_port_attach_failure_is_stable_and_recoverable(self):
        runner = StatefulUsbRunner(fail_attach=True)
        probe = lambda _usb: {
            "status": "present" if runner.attached else "absent",
            "matches": 1 if runner.attached else 0,
            "interface_present": runner.attached, "phy_present": runner.attached,
            "interfaces_up": 0,
        }
        recovery = self.root / "recovery.json"
        lease = UsbLease(self.adapter(), recovery, runner=runner, probe=probe, deadline=1)
        with self.assertRaises(P0Error) as caught:
            lease.acquire()
        self.assertEqual(caught.exception.code, "P0_ADAPTER_ATTACH_FAILED")
        self.assertTrue(recovery.exists())
        cleanup = lease.release()
        self.assertTrue(cleanup["prior_state_restored"])
        self.assertFalse(recovery.exists())


class RadioWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sys = self.root / "sys"
        self.dev = self.root / "dev"
        self.proc = self.root / "proc"
        self.firmware = self.root / "firmware"
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        (self.runtime / ".switchtrade-integrity.json").write_text("{}\n", encoding="utf-8")
        device = self.sys / "bus" / "usb" / "devices" / "1-1"
        interface = device / "interface0"
        interface.mkdir(parents=True)
        (device / "idVendor").write_text("0bda\n")
        (device / "idProduct").write_text("818b\n")
        (self.sys / "drivers" / "rtl8xxxu").mkdir(parents=True)
        (interface / "driver").symlink_to(self.sys / "drivers" / "rtl8xxxu", target_is_directory=True)
        net = self.sys / "class" / "net" / "wlan7"
        phy = self.sys / "class" / "ieee80211" / "phy7"
        net.mkdir(parents=True)
        phy.mkdir(parents=True)
        (net / "device").symlink_to(interface, target_is_directory=True)
        (net / "phy80211").symlink_to(phy, target_is_directory=True)
        for name in REQUIRED_MODULES:
            (self.sys / "module" / name).mkdir(parents=True)
        (self.dev / "net").mkdir(parents=True)
        (self.dev / "net" / "tun").touch()
        for relative in ("regulatory.db", "regulatory.db.p7s", "rtlwifi/rtl8192eu_nic.bin"):
            path = self.firmware / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode())
        stat = self.proc / str(os.getpid()) / "stat"
        stat.parent.mkdir(parents=True)
        fields = ["S", *("1" for _ in range(29))]
        fields[19] = "12345"
        stat.write_text(f"{os.getpid()} (worker) " + " ".join(fields), encoding="ascii")

    def tearDown(self):
        self.temporary.cleanup()

    def args(self):
        return SimpleNamespace(
            run_id="00000000-0000-0000-0000-000000000001",
            release="release-a", mode="p0_harness", run_generation=1, stage_generation=1,
            adapter_instance_sha256="a" * 64, bus_id="4-18",
            sys_root=self.sys, dev_root=self.dev, proc_root=self.proc,
            firmware_root=self.firmware, runtime_root=self.runtime,
        )

    def test_side_ready_is_bound_and_ticket_cannot_change_identity(self):
        report = build_side_ready(self.args(), {
            "SWITCHTRADE_IFACE": "wlan7",
            "SWITCHTRADE_PHY": "phy7",
            "SWITCHTRADE_USB_ID": USB_ID,
            "SWITCHTRADE_P0_RX_PASSED": "1",
            "SWITCHTRADE_P0_RX_CHANNEL": "6",
            "SWITCHTRADE_P0_TARGET_CHANNEL": "6",
        })
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "p0-side-ready.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(report), set(schema["required"]))
        self.assertEqual(len(report["runtime"]["modules"]), 10)
        self.assertEqual(report["wrapper_pid"], os.getpid())
        self.assertEqual(report["process_start_ticks"], 12345)
        ticket = {
            "contract_version": "p0-launch-ticket.v1", "action": "launch", "endpoint": "probe",
            "run_id": report["run_id"], "release": report["release"],
            "run_generation": 1, "stage_generation": 1,
            "adapter_instance_sha256": "a" * 64, "usb_id": USB_ID, "bus_id": "4-18",
            "wrapper_pid": report["wrapper_pid"], "process_start_ticks": 12345,
            "launch_nonce": "n" * 32, "attempt_id": None,
        }
        self.assertEqual(_validate_ticket(ticket, report)["launch_nonce"], "n" * 32)
        ticket["bus_id"] = "4-19"
        with self.assertRaises(RadioWorkerError) as caught:
            _validate_ticket(ticket, report)
        self.assertEqual(caught.exception.code, "P0_LAUNCH_IDENTITY_MISMATCH")


class QueueOutput:
    def __init__(self):
        self.items = __import__("queue").Queue()
        self.closed = False

    def feed(self, value):
        self.items.put(json.dumps(value, separators=(",", ":")) + "\n")

    def __iter__(self):
        return self

    def __next__(self):
        value = self.items.get(timeout=2)
        if value is None:
            raise StopIteration
        return value

    def close(self):
        if not self.closed:
            self.closed = True
            self.items.put(None)


class FakeWorkerProcess:
    def __init__(self, report):
        self.report = report
        self.stdout = QueueOutput()
        self.returncode = None
        self.exited = threading.Event()
        self.stdin = self.Input(self)
        self.stdout.feed({"event": "p0_side_ready", "report": report})

    class Input:
        def __init__(self, owner):
            self.owner = owner

        def write(self, text):
            value = json.loads(text)
            if value.get("action") == "launch":
                self.owner.stdout.feed({
                    "event": "endpoint_exec", "run_id": value["run_id"],
                    "launch_nonce": value["launch_nonce"],
                })
                self.owner.stdout.feed({
                    "event": "endpoint_started", "run_id": value["run_id"],
                    "release": value["release"], "launch_nonce": value["launch_nonce"],
                    "endpoint_pid": value["wrapper_pid"],
                    "process_start_ticks": value["process_start_ticks"], "endpoint": "probe",
                })
            elif value.get("action") == "stop":
                self.owner._exit(0)
            return len(text)

        def flush(self):
            pass

        def close(self):
            if self.owner.returncode is None:
                self.owner._exit(0)

    def _exit(self, code):
        self.returncode = code
        self.exited.set()
        self.stdout.close()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode

    def terminate(self):
        self._exit(-15)

    def kill(self):
        self._exit(-9)


class FakeLease:
    def __init__(self, adapter, recovery):
        self.adapter = adapter
        self.recovery = recovery
        self.acquires = 0
        self.releases = 0

    def acquire(self):
        self.acquires += 1
        return {"active": True, "acquired_by_run": True}

    def release(self):
        self.releases += 1
        return {"prior_state_restored": True, "detached_by_run": True}


class P0HarnessTests(unittest.TestCase):
    def test_cross_stage_hash_change_is_rejected(self):
        passive = {"runtime": {
            "kernel_release": "kernel-a", "integrity_manifest_sha256": "a" * 64,
            "firmware_sha256": {"regulatory.db": "b" * 64},
            "module_vermagic": {name.replace("_", "-"): "kernel-a" for name in REQUIRED_MODULES},
        }}
        active = {"runtime": {
            "kernel_release": "kernel-a", "integrity_manifest_sha256": "a" * 64,
            "firmware_sha256": {"regulatory.db": "c" * 64},
            "modules": list(REQUIRED_MODULES),
        }}
        with self.assertRaises(P0Error) as caught:
            P0Harness._validate_cross_stage(passive, active)
        self.assertEqual(caught.exception.code, "P0_EVIDENCE_MISMATCH")

    def test_harness_binds_atomic_report_preserves_pid_and_cleans_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(json.dumps({
                "schema": 1, "usb_id": USB_ID, "instance_id": INSTANCE, "bus_id": "4-18",
            }), encoding="utf-8")
            adapter = parse_usbipd_state(usb_state())[0]
            firmware = {
                "regulatory.db": "1" * 64,
                "regulatory.db.p7s": "2" * 64,
                "rtlwifi/rtl8192eu_nic.bin": "3" * 64,
            }
            integrity = "4" * 64
            validator = SimpleNamespace(
                requested_identity=lambda: (INSTANCE, USB_ID),
                validate=lambda: (adapter, {
                    "contract_version": "p0-passive.v1", "status": "passed",
                    "runtime": {
                        "kernel_release": "test-kernel",
                        "integrity_manifest_sha256": integrity,
                        "firmware_sha256": firmware,
                        "module_vermagic": {
                            name.replace("_", "-"): "test-kernel" for name in REQUIRED_MODULES
                        },
                    },
                }),
            )
            leases = []
            def lease_factory(selected, recovery):
                lease = FakeLease(selected, recovery)
                leases.append(lease)
                return lease
            processes = []
            def worker_factory(command, stdout_path, _stderr_path):
                def argument(name):
                    return command[command.index(name) + 1]
                report = {
                    "contract_version": "p0-side-ready.v1", "schema": 1,
                    "run_id": argument("--run-id"), "release": argument("--release"),
                    "mode": argument("--mode"),
                    "run_generation": int(argument("--run-generation")),
                    "stage_generation": int(argument("--stage-generation")),
                    "wrapper_pid": 4100, "process_start_ticks": 12345,
                    "adapter": {
                        "instance_sha256": adapter.instance_sha256,
                        "usb_id": USB_ID, "bus_id": "4-18",
                    },
                    "radio": {"phy": "phy0", "netdev": "wlan0", "rx_passed": True},
                    "runtime": {
                        "kernel_release": "test-kernel",
                        "integrity_manifest_sha256": integrity,
                        "firmware_sha256": firmware,
                        "modules": list(REQUIRED_MODULES),
                    },
                }
                side_report = stdout_path.parent / "p0-side-ready.json"
                side_report.write_text(json.dumps(report), encoding="utf-8")
                process = FakeWorkerProcess(report)
                processes.append(process)
                return process

            with ConnectionCoordinator(root / "coordinator", "release-a") as coordinator:
                result = P0Harness(
                    coordinator, validator, root / "runs",
                    worker_factory=worker_factory, lease_factory=lease_factory,
                ).run()
                snapshot = coordinator.snapshot(result["run_id"])
            self.assertEqual(result["functional_status"], "passed")
            self.assertEqual(result["cleanup_status"], "verified")
            self.assertEqual(snapshot["identity"]["wrapper_pid"], 4100)
            self.assertEqual(snapshot["identity"]["endpoint_pid"], 4100)
            self.assertEqual(snapshot["ownership"]["launch_count"], 1)
            self.assertEqual(leases[0].acquires, 1)
            self.assertEqual(leases[0].releases, 1)
            self.assertEqual(processes[0].returncode, 0)
            self.assertTrue(Path(result["report_path"]).is_file())

    def test_restart_recovery_clears_preflight_guard_without_hardware_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = ConnectionCoordinator(root / "coordinator", "release-a")
            run = first.start(RunMode.P0_HARNESS, adapter_instance_id=INSTANCE, usb_id=USB_ID)
            first.transition(run["run_id"], Phase.PREFLIGHT, "P0a_release")
            first.close()

            validator = SimpleNamespace(requested_identity=lambda: (INSTANCE, USB_ID))
            with ConnectionCoordinator(root / "coordinator", "release-a") as second:
                interrupted = second.snapshot(run["run_id"])
                self.assertEqual(interrupted["phase"], "cleaning")
                recovered = P0Harness(second, validator, root / "runs").recover(interrupted)
                self.assertEqual(recovered["status"], "recovered")
                self.assertTrue(second.snapshot(run["run_id"])["cleanup"]["verified"])
                next_run = second.start(
                    RunMode.P0_HARNESS, adapter_instance_id=INSTANCE, usb_id=USB_ID)
                self.assertNotEqual(next_run["run_id"], run["run_id"])


if __name__ == "__main__":
    unittest.main()
