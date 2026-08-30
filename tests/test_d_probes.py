import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from switchtrade.connection import DProbeError, WslDProbes
from switchtrade.connection.d_probes import verify_stable_radio_quiescence


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
        self.assertEqual(command[:9], [
            "wsl.exe", "-d", "SwitchTrade", "-u", "root",
            "--cd", "/opt/switchtrade", "--", "/opt/switchtrade/python/bin/python3",
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

    def test_wsl_inventory_excludes_the_probe_process_from_run_residue(self):
        # The run ID is an argv item of the probe itself; failing to exclude self makes every clean
        # launch/radio observation look active forever in the installed WSL runtime.
        import switchtrade.connection.d_probes as module
        self.assertEqual(module._PROCESS_PROGRAM.count("item.name==str(os.getpid())"), 1)
        self.assertEqual(module._RADIO_PROGRAM.count("item.name==str(os.getpid())"), 1)

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

    def test_d9_active_sample_resets_the_required_clean_streak(self):
        now = [0.0]
        clean = {
            "status": "quiescent", "owned_interfaces": 0,
            "driver_threads": 0, "phy_active": False,
        }
        values = [clean, {**clean, "status": "active", "owned_interfaces": 1},
                  clean, clean, clean]
        calls = []

        def probe(_identity):
            calls.append(len(calls))
            return values[len(calls) - 1]

        evidence, passed = verify_stable_radio_quiescence(
            probe, self.identity(), stable_samples=3, sample_interval=0.1, timeout=1,
            monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )
        self.assertTrue(passed)
        self.assertEqual(evidence, clean)
        self.assertEqual(len(calls), 5)

    def test_probe_identity_and_private_path_inventory_are_bounded(self):
        with self.assertRaises(ValueError):
            WslDProbes(
                distro="SwitchTrade", packaged_python="python3",
                private_paths=[Path(f"token-{index}") for index in range(17)],
            )
        probes = WslDProbes(
            distro="SwitchTrade", packaged_python="python3", runner=FakeRunner([]))
        identity = self.identity()
        identity["run_id"] = "not-a-uuid"
        with self.assertRaises(DProbeError):
            probes.launch(identity)
        identity = self.identity()
        identity["netdev"] = "invalid interface name"
        with self.assertRaises(DProbeError):
            probes.radio(identity)


if __name__ == "__main__":
    unittest.main()
