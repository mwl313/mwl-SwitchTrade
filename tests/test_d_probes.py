import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from switchtrade.connection import DProbeError, WslDProbes


class FakeRunner:
    def __init__(self, values):
        self.values = list(values)
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append((list(command), timeout))
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return subprocess.CompletedProcess(command, value.get("returncode", 0), json.dumps(value.get("body")))


class WslDProbesTests(unittest.TestCase):
    def identity(self):
        return {
            "run_id": "00000000-0000-0000-0000-000000000123",
            "endpoint_pid": 5001,
            "endpoint_start_ticks": 202,
            "wrapper_pid": 4001,
            "process_start_ticks": 101,
            "phy": "phy0",
            "netdev": "stmon0",
        }

    def test_process_generation_probe_uses_argument_vector_and_tristate_result(self):
        runner = FakeRunner([
            {"body": {"endpoint_actual": 202, "wrapper_actual": 202, "matching_processes": 0}},
            {"body": {"endpoint_actual": None, "wrapper_actual": None, "matching_processes": 0}},
        ])
        probes = WslDProbes(
            distro="SwitchTrade", packaged_python="/opt/switchtrade/python/bin/python3",
            runner=runner)
        self.assertEqual(probes.process_start_ticks(5001), 202)
        self.assertIsNone(probes.process_start_ticks(5001))
        command = runner.commands[0][0]
        self.assertEqual(command[:7], [
            "wsl.exe", "-d", "SwitchTrade", "-u", "root", "--",
            "/opt/switchtrade/python/bin/python3",
        ])
        self.assertEqual(command[-3:], ["probe-only", "5001", "5001"])

    def test_launch_probe_requires_exact_process_generation_and_private_file_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "사용자-자격증명.token"
            runner = FakeRunner([{
                "body": {"endpoint_actual": None, "wrapper_actual": 999, "matching_processes": 0},
            }])
            probes = WslDProbes(
                distro="SwitchTrade", packaged_python="python3",
                private_paths=[private], runner=runner)
            result = probes.launch(self.identity())
            self.assertEqual(result["status"], "absent")
            self.assertTrue(result["wrapper_exited"])

            private.write_text("secret", encoding="utf-8")
            runner.values.append({
                "body": {"endpoint_actual": None, "wrapper_actual": None, "matching_processes": 0},
            })
            result = probes.launch(self.identity())
            self.assertEqual(result["status"], "present")
            self.assertFalse(result["token_absent"])
            self.assertNotIn(str(private), " ".join(runner.commands[-1][0]))

    def test_radio_probe_distinguishes_temporary_interfaces_from_stable_quiescence(self):
        runner = FakeRunner([
            {"body": {
                "status": "active", "owned_interfaces": 2,
                "driver_threads": 1, "phy_active": True,
            }},
            {"body": {
                "status": "quiescent", "owned_interfaces": 0,
                "driver_threads": 0, "phy_active": False,
            }},
        ])
        probes = WslDProbes(
            distro="SwitchTrade", packaged_python="python3", runner=runner)
        temporary = probes.temporary_interfaces(self.identity())
        self.assertEqual(temporary, {"status": "active", "owned_interfaces": 2})
        stable = probes.radio(self.identity())
        self.assertEqual(stable["status"], "quiescent")
        self.assertFalse(stable["phy_active"])

    def test_run_binding_does_not_mutate_coordinator_identity(self):
        seen = []
        identity = {"phy": "phy0"}

        def probe(value):
            seen.append(value)
            return {"ok": True}

        bound = WslDProbes.for_run(
            probe, "00000000-0000-0000-0000-000000000123")
        self.assertEqual(bound(identity), {"ok": True})
        self.assertNotIn("run_id", identity)
        self.assertEqual(seen[0]["run_id"], "00000000-0000-0000-0000-000000000123")

    def test_timeout_and_malformed_output_are_unknown_not_success(self):
        runner = FakeRunner([subprocess.TimeoutExpired("wsl.exe", 5)])
        probes = WslDProbes(
            distro="SwitchTrade", packaged_python="python3", runner=runner)
        with self.assertRaises(DProbeError):
            probes.launch(self.identity())

        malformed = FakeRunner([{"body": {"endpoint_actual": "wrong"}}])
        probes = WslDProbes(
            distro="SwitchTrade", packaged_python="python3", runner=malformed)
        with self.assertRaises(DProbeError):
            probes.process_start_ticks(5001)


if __name__ == "__main__":
    unittest.main()
