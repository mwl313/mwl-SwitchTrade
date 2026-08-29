"""CLI-first cold P0 qualification using the production radio preparation path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import secrets
import signal
import subprocess
import threading
import time
from typing import Callable

from switchtrade.connection.coordinator import (
    ConnectionCoordinator, ConnectionCoordinatorError, FunctionalOutcome, Phase, RunMode,
)
from switchtrade.connection.p0 import (
    P0Error, PassiveValidator, UsbAdapter, UsbLease, atomic_json, linux_usb_probe, run_command,
)
from switchtrade.diagnostics import default_runs_root
from switchtrade.relay_client import RelayClient


WorkerFactory = Callable[[list[str], Path, Path], subprocess.Popen]
LeaseFactory = Callable[[UsbAdapter, Path], UsbLease]


def _unknown_linux_usb() -> dict:
    return {
        "status": "unknown", "matches": None, "interface_present": None,
        "phy_present": None, "interfaces_up": None,
    }


def _wsl_linux_usb_probe(
    usb_id: str,
    *,
    distro: str,
    packaged_python: str,
    runner=run_command,
) -> dict:
    program = (
        "import json,sys; from switchtrade.connection.p0 import linux_usb_probe; "
        "print(json.dumps(linux_usb_probe(sys.argv[1]),sort_keys=True,separators=(',',':')))"
    )
    try:
        result = runner([
            "wsl.exe", "-d", distro, "-u", "root", "--",
            packaged_python, "-c", program, usb_id,
        ], 5)
        value = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
        return _unknown_linux_usb()
    if (not isinstance(value, dict) or value.get("status") not in {"present", "absent", "unknown"} or
            not all(name in value for name in (
                "matches", "interface_present", "phy_present", "interfaces_up"))):
        return _unknown_linux_usb()
    return value


def _wsl_process_start_ticks(
    pid: int,
    *,
    distro: str,
    packaged_python: str,
    runner=run_command,
) -> int | None:
    program = (
        "import json,sys; from pathlib import Path; p=Path('/proc')/sys.argv[1]/'stat'; "
        "print('null' if not p.exists() else json.dumps(int(p.read_text(encoding='ascii').rsplit(')',1)[1].split()[19])))"
    )
    try:
        result = runner([
            "wsl.exe", "-d", distro, "-u", "root", "--",
            packaged_python, "-c", program, str(pid),
        ], 5)
        if result.returncode != 0:
            raise ValueError("process probe failed")
        value = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError) as error:
        raise P0Error(
            "P0_RECOVERY_PROCESS_UNKNOWN", "D8_endpoint_verification",
            "recovered worker process identity is unavailable",
        ) from error
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise P0Error(
            "P0_RECOVERY_PROCESS_UNKNOWN", "D8_endpoint_verification",
            "recovered worker process identity is invalid",
        )
    return value


def _wsl_netdev_exists(
    netdev: str,
    *,
    distro: str,
    packaged_python: str,
    runner=run_command,
) -> bool:
    program = (
        "import json,sys; from pathlib import Path; "
        "print(json.dumps((Path('/sys/class/net')/sys.argv[1]).exists()))"
    )
    try:
        result = runner([
            "wsl.exe", "-d", distro, "-u", "root", "--",
            packaged_python, "-c", program, netdev,
        ], 5)
        value = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError) as error:
        raise P0Error(
            "P0_RADIO_QUIESCE_FAILED", "D9_radio_quiescence",
            "recovery could not inspect the selected netdev",
        ) from error
    if not isinstance(value, bool):
        raise P0Error(
            "P0_RADIO_QUIESCE_FAILED", "D9_radio_quiescence",
            "recovery netdev evidence is invalid",
        )
    return value


def _wsl_path(path: Path) -> str:
    value = str(path.resolve())
    if len(value) >= 3 and value[1:3] == ":\\":
        return f"/mnt/{value[0].lower()}/{value[3:].replace(chr(92), '/')}"
    return value


def _worker_command(
    *,
    run: dict,
    adapter: UsbAdapter,
    report_path: Path,
    runtime_root: str,
    packaged_python: str,
    distro: str,
    target_channel: int,
) -> list[str]:
    worker = [
        packaged_python, "-m", "switchtrade.connection.radio_worker",
        "--run-id", run["run_id"], "--release", run["identity"]["release"],
        "--mode", run["identity"]["mode"],
        "--run-generation", str(run["identity"]["run_generation"]),
        "--stage-generation", str(run["identity"]["stage_generation"]),
        "--adapter-instance-sha256", adapter.instance_sha256,
        "--bus-id", adapter.bus_id,
        "--report", _wsl_path(report_path) if os.name == "nt" else str(report_path),
        "--runtime-root", runtime_root,
    ]
    radio = [
        "./scripts/wsl-radio-prepare.sh", "--usb-id", adapter.usb_id,
        "--role", "relay", "--target-channel", str(target_channel), "--", *worker,
    ]
    if os.name == "nt":
        return [
            "wsl.exe", "-d", distro, "-u", "root", "--cd", runtime_root,
            "--", "env", "SWITCHTRADE_LOG_FD=2", *radio,
        ]
    return ["env", "SWITCHTRADE_LOG_FD=2", *radio]


def _default_worker_factory(command: list[str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    # stdout is an NDJSON control channel; the preparation scripts use fd 2 for bounded human logs.
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("w", encoding="utf-8", newline="\n")
    stderr_file = stderr_path.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file,
            text=True, encoding="utf-8", bufsize=1,
        )
    except BaseException:
        stdout_file.close()
        stderr_file.close()
        raise
    process._switchtrade_stdout_log = stdout_file  # type: ignore[attr-defined]
    process._switchtrade_stderr_log = stderr_file  # type: ignore[attr-defined]
    return process


class WorkerEvents:
    def __init__(self, process: subprocess.Popen, log_path: Path):
        if process.stdout is None:
            raise P0Error("P0_WORKER_PIPE_MISSING", "P0b_worker", "worker stdout pipe is unavailable")
        self.process = process
        self.log_path = log_path
        self.events: queue.Queue[dict | BaseException | None] = queue.Queue()
        self.thread = threading.Thread(target=self._read, name="p0-worker-events", daemon=True)
        self.thread.start()

    def _read(self) -> None:
        stream = self.process.stdout
        log = getattr(self.process, "_switchtrade_stdout_log", None)
        try:
            for line in stream:
                if log is not None:
                    log.write(line[:16_384])
                    log.flush()
                if len(line) > 16_384:
                    raise P0Error("P0_WORKER_PROTOCOL_INVALID", "P0b_worker", "worker event exceeds its bound")
                try:
                    value = json.loads(line)
                except ValueError as error:
                    raise P0Error("P0_WORKER_PROTOCOL_INVALID", "P0b_worker", "worker emitted non-JSON output") from error
                if not isinstance(value, dict) or not isinstance(value.get("event"), str):
                    raise P0Error("P0_WORKER_PROTOCOL_INVALID", "P0b_worker", "worker event is invalid")
                self.events.put(value)
        except BaseException as error:
            self.events.put(error)
        finally:
            self.events.put(None)

    def wait_for(self, wanted: set[str], timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise P0Error("P0_WORKER_TIMEOUT", "P0b_worker", "worker checkpoint deadline expired")
            try:
                value = self.events.get(timeout=remaining)
            except queue.Empty as error:
                raise P0Error("P0_WORKER_TIMEOUT", "P0b_worker", "worker checkpoint deadline expired") from error
            if value is None:
                raise P0Error("P0_WORKER_EXITED", "P0b_worker", "worker exited before its checkpoint")
            if isinstance(value, BaseException):
                raise value
            if value["event"] == "worker_failed":
                raise P0Error(
                    str(value.get("code") or "P0_WORKER_FAILED"), "P0b_worker",
                    str(value.get("message") or "worker failed"),
                )
            if value["event"] in wanted:
                return value

    def send(self, value: dict) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise P0Error("P0_WORKER_EXITED", "P0b_worker", "worker is not accepting commands")
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(serialized) >= 16_384:
            raise P0Error("P0_LAUNCH_TICKET_INVALID", "P0b_worker", "worker command exceeds its bound")
        try:
            self.process.stdin.write(serialized + "\n")
            self.process.stdin.flush()
        except OSError as error:
            raise P0Error("P0_WORKER_PIPE_FAILED", "P0b_worker", "worker command pipe failed") from error

    def stop(self, *, endpoint_started: bool) -> dict:
        forced = False
        if self.process.poll() is None:
            try:
                if endpoint_started:
                    self.send({"action": "stop"})
                else:
                    self.send({"contract_version": "p0-launch-ticket.v1", "action": "stop"})
            except P0Error:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forced = True
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.thread.join(timeout=1)
        for name in ("_switchtrade_stdout_log", "_switchtrade_stderr_log"):
            stream = getattr(self.process, name, None)
            if stream is not None:
                stream.close()
        return {
            "worker_exited": self.process.poll() is not None,
            "worker_exit_code": self.process.returncode,
            "worker_forced": forced,
        }


class P0Harness:
    def __init__(
        self,
        coordinator: ConnectionCoordinator,
        validator: PassiveValidator,
        root: Path,
        *,
        worker_factory: WorkerFactory = _default_worker_factory,
        lease_factory: LeaseFactory | None = None,
        distro: str = "SwitchTrade",
        runtime_root: str = "/opt/switchtrade",
        packaged_python: str = "/opt/switchtrade/bridge/.venv/bin/python",
        target_channel: int = 6,
    ):
        self.coordinator = coordinator
        self.validator = validator
        self.root = Path(root)
        self.worker_factory = worker_factory
        self.command_runner = run_command
        if lease_factory is None:
            self.linux_probe = (
                (lambda usb_id: _wsl_linux_usb_probe(
                    usb_id, distro=distro, packaged_python=packaged_python))
                if os.name == "nt" else linux_usb_probe
            )
            lease_factory = lambda adapter, recovery: UsbLease(
                adapter, recovery, distro=distro, probe=self.linux_probe)
        else:
            self.linux_probe = linux_usb_probe
        self.lease_factory = lease_factory
        self.distro = distro
        self.runtime_root = runtime_root
        self.packaged_python = packaged_python
        self.target_channel = target_channel

    @staticmethod
    def _validate_ready(report: object, run: dict, adapter: UsbAdapter, report_path: Path) -> dict:
        if not isinstance(report, dict):
            raise P0Error("P0_WORKER_REPORT_INVALID", "P0b_worker", "P0 readiness report is invalid")
        expected = {
            "contract_version": "p0-side-ready.v1",
            "run_id": run["run_id"],
            "release": run["identity"]["release"],
            "mode": run["identity"]["mode"],
            "run_generation": run["identity"]["run_generation"],
            "stage_generation": run["identity"]["stage_generation"],
        }
        if any(report.get(name) != value for name, value in expected.items()):
            raise P0Error("P0_WORKER_IDENTITY_MISMATCH", "P0b_worker", "P0 readiness identity changed")
        adapter_report = report.get("adapter")
        radio = report.get("radio")
        if (not isinstance(adapter_report, dict) or
                adapter_report.get("instance_sha256") != adapter.instance_sha256 or
                adapter_report.get("usb_id") != adapter.usb_id or
                adapter_report.get("bus_id") != adapter.bus_id or
                not isinstance(radio, dict) or radio.get("rx_passed") is not True):
            raise P0Error("P0_WORKER_IDENTITY_MISMATCH", "P0b_worker", "P0 radio identity changed")
        try:
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise P0Error("P0_WORKER_REPORT_MISSING", "P0b_worker", "atomic P0 report is unavailable") from error
        if persisted != report:
            raise P0Error("P0_WORKER_REPORT_MISMATCH", "P0b_worker", "P0 event and report differ")
        return report

    @staticmethod
    def _validate_cross_stage(p0a: dict, p0b: dict) -> None:
        passive = p0a.get("runtime") if isinstance(p0a, dict) else None
        active = p0b.get("runtime") if isinstance(p0b, dict) else None
        if not isinstance(passive, dict) or not isinstance(active, dict):
            raise P0Error("P0_EVIDENCE_MISMATCH", "P0b_worker", "P0 runtime evidence is incomplete")
        passive_modules = passive.get("module_vermagic")
        active_modules = active.get("modules")
        expected_modules = {
            str(name).replace("-", "_") for name in passive_modules
        } if isinstance(passive_modules, dict) else set()
        if (passive.get("kernel_release") != active.get("kernel_release") or
                passive.get("integrity_manifest_sha256") != active.get("integrity_manifest_sha256") or
                passive.get("firmware_sha256") != active.get("firmware_sha256") or
                expected_modules != set(active_modules or [])):
            raise P0Error(
                "P0_EVIDENCE_MISMATCH", "P0b_worker",
                "runtime, module, or firmware evidence changed between P0a and P0b",
            )

    def _process_start_ticks(self, pid: int) -> int | None:
        if os.name == "nt":
            return _wsl_process_start_ticks(
                pid, distro=self.distro, packaged_python=self.packaged_python,
                runner=self.command_runner,
            )
        path = Path("/proc") / str(pid) / "stat"
        try:
            fields = path.read_text(encoding="ascii").rsplit(")", 1)[1].split()
            return int(fields[19])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, IndexError) as error:
            raise P0Error(
                "P0_RECOVERY_PROCESS_UNKNOWN", "D8_endpoint_verification",
                "recovered worker process identity is unavailable",
            ) from error

    def recover(self, snapshot: dict | None = None) -> dict:
        """Finish one interrupted P0 cleanup before allowing another explicit run."""
        run = snapshot or self.coordinator.snapshot()
        if not isinstance(run, dict):
            return {"status": "not_required"}
        run_id = run["run_id"]
        if run["phase"] == "terminal" and run["cleanup"]["verified"]:
            return {"status": "not_required", "run_id": run_id}
        if run["phase"] == "terminal":
            self.coordinator.retry_cleanup(run_id)
        elif run["phase"] != "cleaning":
            raise P0Error(
                "P0_RECOVERY_STATE_INVALID", "D8_endpoint_verification",
                "coordinator did not enter recovery cleanup",
            )
        identity = run["identity"]
        wrapper_pid = identity.get("endpoint_pid") or identity.get("wrapper_pid")
        start_ticks = identity.get("endpoint_start_ticks") or identity.get("process_start_ticks")
        netdev = identity.get("netdev")
        side_report_path = self.root / run_id / "p0-side-ready.json"
        if wrapper_pid is None and side_report_path.exists():
            try:
                side = json.loads(side_report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise P0Error(
                    "P0_RECOVERY_STATE_INVALID", "D8_endpoint_verification",
                    "interrupted worker report is invalid",
                ) from error
            instance_hash = hashlib.sha256(
                identity["adapter_instance_id"].casefold().encode("utf-8")).hexdigest()
            side_adapter = side.get("adapter") if isinstance(side, dict) else None
            side_radio = side.get("radio") if isinstance(side, dict) else None
            if (not isinstance(side, dict) or side.get("run_id") != run_id or
                    side.get("release") != identity["release"] or
                    not isinstance(side_adapter, dict) or
                    side_adapter.get("instance_sha256") != instance_hash or
                    side_adapter.get("usb_id") != identity["usb_id"] or
                    not isinstance(side_radio, dict)):
                raise P0Error(
                    "P0_RECOVERY_STATE_INVALID", "D8_endpoint_verification",
                    "interrupted worker identity does not match the run",
                )
            wrapper_pid = side.get("wrapper_pid")
            start_ticks = side.get("process_start_ticks")
            netdev = side_radio.get("netdev")
            if (not isinstance(wrapper_pid, int) or wrapper_pid <= 0 or
                    not isinstance(start_ticks, int) or start_ticks <= 0):
                raise P0Error(
                    "P0_RECOVERY_STATE_INVALID", "D8_endpoint_verification",
                    "interrupted worker process identity is invalid",
                )
        evidence = {
            "worker_exited": wrapper_pid is None,
            "radio_quiescent": wrapper_pid is None,
            "prior_usb_state_restored": False,
        }
        try:
            if wrapper_pid is not None:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    actual = self._process_start_ticks(wrapper_pid)
                    if actual is None or actual != start_ticks:
                        break
                    time.sleep(0.1)
                actual = self._process_start_ticks(wrapper_pid)
                if actual == start_ticks:
                    if os.name == "nt":
                        result = self.command_runner([
                            "wsl.exe", "-d", self.distro, "-u", "root", "--",
                            "kill", "-TERM", str(wrapper_pid),
                        ], 5)
                        if result.returncode != 0 and self._process_start_ticks(wrapper_pid) == start_ticks:
                            raise P0Error(
                                "P0_RECOVERY_PROCESS_STILL_ACTIVE", "D8_endpoint_verification",
                                "interrupted worker could not be signalled",
                            )
                    else:
                        os.kill(wrapper_pid, signal.SIGTERM)
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and self._process_start_ticks(wrapper_pid) == start_ticks:
                        time.sleep(0.1)
                if self._process_start_ticks(wrapper_pid) == start_ticks:
                    raise P0Error(
                        "P0_RECOVERY_PROCESS_STILL_ACTIVE", "D8_endpoint_verification",
                        "interrupted worker did not exit",
                    )
                evidence["worker_exited"] = True
            if isinstance(netdev, str) and netdev:
                if os.name == "nt":
                    if _wsl_netdev_exists(
                            netdev, distro=self.distro, packaged_python=self.packaged_python,
                            runner=self.command_runner):
                        result = self.command_runner([
                            "wsl.exe", "-d", self.distro, "-u", "root", "--",
                            "ip", "link", "set", "dev", netdev, "down",
                        ], 5)
                        if result.returncode != 0:
                            raise P0Error(
                                "P0_RADIO_QUIESCE_FAILED", "D9_radio_quiescence",
                                "recovery could not quiesce the selected netdev",
                            )
                else:
                    try:
                        result = subprocess.run(
                            ["ip", "link", "set", "dev", netdev, "down"],
                            capture_output=True, text=True, timeout=2, check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired) as error:
                        raise P0Error(
                            "P0_RADIO_QUIESCE_FAILED", "D9_radio_quiescence",
                            "recovery could not quiesce the selected netdev",
                        ) from error
                    # A missing netdev is already quiescent; other failures remain uncertain.
                    if result.returncode != 0 and "does not exist" not in (result.stderr or "").lower():
                        raise P0Error(
                            "P0_RADIO_QUIESCE_FAILED", "D9_radio_quiescence",
                            "recovery could not quiesce the selected netdev",
                        )
            evidence["radio_quiescent"] = True
            recovery_file = self.root / run_id / "p0-usb-recovery.json"
            if recovery_file.exists():
                lease = UsbLease.from_recovery(
                    recovery_file, distro=self.distro, probe=self.linux_probe)
                usb = lease.release()
                evidence["prior_usb_state_restored"] = usb["prior_state_restored"]
            elif run["ownership"]["wrapper_acquired"]:
                raise P0Error(
                    "P0_RECOVERY_STATE_MISSING", "D10_usb_return",
                    "USB ownership recovery state is missing",
                )
            else:
                evidence["prior_usb_state_restored"] = True
            terminal = self.coordinator.complete_cleanup(
                run_id, verified=True, evidence=evidence)
            return {"status": "recovered", "run_id": run_id, "cleanup": terminal["cleanup"]}
        except (P0Error, OSError, subprocess.SubprocessError) as error:
            terminal = self.coordinator.complete_cleanup(
                run_id, verified=False, evidence=evidence,
                code="P0_CLEANUP_FAILED", message=getattr(error, "message", type(error).__name__),
            )
            return {
                "status": "failed", "run_id": run_id,
                "code": getattr(error, "code", "P0_CLEANUP_FAILED"),
                "cleanup": terminal["cleanup"],
            }

    def run(self, *, launch_probe: bool = True) -> dict:
        requested_instance, requested_usb = self.validator.requested_identity()
        run = self.coordinator.start(
            RunMode.P0_HARNESS, adapter_instance_id=requested_instance, usb_id=requested_usb)
        run_id = run["run_id"]
        run_root = self.root / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        report_path = run_root / "p0-side-ready.json"
        final_path = run_root / "p0-harness-report.json"
        lease = None
        events = None
        process = None
        endpoint_started = False
        p0a = None
        p0b = None
        primary = None
        cleanup = {}
        try:
            self.coordinator.transition(run_id, Phase.PREFLIGHT, "P0a_release")
            adapter, p0a = self.validator.validate()
            if adapter.instance_id.casefold() != requested_instance.casefold():
                raise P0Error("P0_ADAPTER_IDENTITY_CHANGED", "P0a_adapter", "selected adapter changed during P0a")
            self.coordinator.pass_gate(run_id, "P0a_PASSIVE_READY")
            run = self.coordinator.transition(run_id, Phase.RUNNING, "P0b_lease")
            lease = self.lease_factory(adapter, run_root / "p0-usb-recovery.json")
            lease_evidence = lease.acquire()
            command = _worker_command(
                run=run, adapter=adapter, report_path=report_path,
                runtime_root=self.runtime_root, packaged_python=self.packaged_python,
                distro=self.distro, target_channel=self.target_channel,
            )
            process = self.worker_factory(
                command, run_root / "worker-events.ndjson", run_root / "worker.stderr.log")
            events = WorkerEvents(process, run_root / "worker-events.ndjson")
            ready_event = events.wait_for({"p0_side_ready"}, 45)
            p0b = self._validate_ready(ready_event.get("report"), run, adapter, report_path)
            self._validate_cross_stage(p0a, p0b)
            self.coordinator.acquire_wrapper(
                run_id, wrapper_pid=p0b["wrapper_pid"],
                process_start_ticks=p0b["process_start_ticks"],
                adapter_instance_id=adapter.instance_id, usb_id=adapter.usb_id, bus_id=adapter.bus_id)
            self.coordinator.mark_p0_ready(
                run_id, wrapper_pid=p0b["wrapper_pid"],
                process_start_ticks=p0b["process_start_ticks"],
                phy=p0b["radio"]["phy"], netdev=p0b["radio"]["netdev"])
            if launch_probe:
                nonce = secrets.token_hex(32)
                self.coordinator.reserve_endpoint_launch(run_id, launch_nonce=nonce)
                events.send({
                    "contract_version": "p0-launch-ticket.v1",
                    "action": "launch",
                    "endpoint": "probe",
                    "run_id": run_id,
                    "release": run["identity"]["release"],
                    "run_generation": run["identity"]["run_generation"],
                    "stage_generation": run["identity"]["stage_generation"],
                    "adapter_instance_sha256": adapter.instance_sha256,
                    "usb_id": adapter.usb_id,
                    "bus_id": adapter.bus_id,
                    "wrapper_pid": p0b["wrapper_pid"],
                    "process_start_ticks": p0b["process_start_ticks"],
                    "launch_nonce": nonce,
                    "attempt_id": None,
                })
                events.wait_for({"endpoint_exec"}, 5)
                endpoint = events.wait_for({"endpoint_started"}, 5)
                if (endpoint.get("run_id") != run_id or endpoint.get("launch_nonce") != nonce or
                        endpoint.get("endpoint_pid") != p0b["wrapper_pid"] or
                        endpoint.get("process_start_ticks") != p0b["process_start_ticks"]):
                    raise P0Error(
                        "P0_ENDPOINT_IDENTITY_MISMATCH", "P0b_launch",
                        "PID-preserving endpoint acknowledgement changed identity",
                    )
                self.coordinator.acknowledge_endpoint(
                    run_id, launch_nonce=nonce, endpoint_pid=endpoint["endpoint_pid"],
                    process_start_ticks=endpoint["process_start_ticks"])
                endpoint_started = True
            self.coordinator.close_run(run_id, FunctionalOutcome.PASSED)
            cleanup["lease"] = lease_evidence
        except (P0Error, ConnectionCoordinatorError, OSError, subprocess.SubprocessError) as error:
            primary = {
                "code": getattr(error, "code", "P0_INTERNAL_ERROR"),
                "gate": getattr(error, "gate", "P0"),
                "message": getattr(error, "message", type(error).__name__),
            }
            try:
                self.coordinator.close_run(
                    run_id, FunctionalOutcome.FAILED,
                    code=primary["code"], message=primary["message"])
            except ConnectionCoordinatorError:
                pass
        try:
            self.coordinator.begin_cleanup(run_id)
            if events is not None:
                cleanup["worker"] = events.stop(endpoint_started=endpoint_started)
            elif process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            if lease is not None:
                cleanup["usb"] = lease.release()
            worker_verified = (
                events is None or (
                    cleanup.get("worker", {}).get("worker_exited") is True and
                    cleanup.get("worker", {}).get("worker_forced") is False
                )
            )
            usb_verified = (
                lease is None or cleanup.get("usb", {}).get("prior_state_restored") is True
            )
            cleanup_verified = (
                worker_verified and usb_verified
            )
            self.coordinator.complete_cleanup(
                run_id, verified=cleanup_verified,
                evidence={
                    "worker_exited": None if events is None else worker_verified,
                    "prior_usb_state_restored": None if lease is None else usb_verified,
                    "endpoint_exited": None if not endpoint_started else worker_verified,
                },
                code=None if cleanup_verified else "P0_CLEANUP_FAILED",
                message=None if cleanup_verified else "P0 cleanup could not be verified",
            )
        except (P0Error, ConnectionCoordinatorError, OSError, subprocess.SubprocessError) as error:
            cleanup["failure"] = {
                "code": getattr(error, "code", "P0_CLEANUP_FAILED"),
                "message": getattr(error, "message", type(error).__name__),
            }
            try:
                self.coordinator.complete_cleanup(
                    run_id, verified=False,
                    evidence={"worker_exited": False, "prior_usb_state_restored": False},
                    code="P0_CLEANUP_FAILED", message="P0 cleanup could not be verified",
                )
            except ConnectionCoordinatorError:
                pass
        snapshot = self.coordinator.snapshot(run_id)
        result = {
            "contract_version": "p0-harness-report.v1",
            "schema": 1,
            "run_id": run_id,
            "release": run["identity"]["release"],
            "p0a": p0a,
            "p0b": p0b,
            "primary_failure": primary,
            "cleanup": cleanup,
            "functional_status": snapshot["functional"]["status"],
            "cleanup_status": snapshot["cleanup"]["status"],
            "last_passed_gate": snapshot["last_passed_gate"],
        }
        atomic_json(final_path, result)
        return {**result, "report_path": str(final_path)}


def _installed_release(root: str, distro: str, runner=run_command) -> str:
    marker_path = PurePosixPath(root) / ".switchtrade-release.json"
    try:
        if os.name == "nt":
            result = runner([
                "wsl.exe", "-d", distro, "-u", "root", "--",
                "cat", marker_path.as_posix(),
            ], 10)
            if result.returncode != 0:
                raise OSError("release marker probe failed")
            text = result.stdout
        else:
            text = Path(marker_path).read_text(encoding="utf-8")
        marker = json.loads(text)
        value = marker["release_id"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("P0_RELEASE_MARKER_INVALID") from error
    if not isinstance(value, str) or not value:
        raise SystemExit("P0_RELEASE_MARKER_INVALID")
    return value


def parser() -> argparse.ArgumentParser:
    runtime = default_runs_root().parent / "runtime"
    value = argparse.ArgumentParser(description="SwitchTrade cold P0 qualification harness")
    value.add_argument("--state-root", type=Path, default=default_runs_root().parent / "connection-v2")
    value.add_argument("--selection-file", type=Path, default=runtime / "hardware-selection.json")
    value.add_argument("--runtime-root", default="/opt/switchtrade")
    value.add_argument("--distro", default=os.environ.get("SWITCHTRADE_WSL_DISTRO", "SwitchTrade"))
    value.add_argument("--relay-url", default=os.environ.get(
        "SWITCHTRADE_RELAY_URL", "https://relay.pangyostonefist.org"))
    value.add_argument("--target-channel", type=int, default=6)
    value.add_argument("--no-launch-probe", action="store_true")
    return value


def main() -> None:
    args = parser().parse_args()
    release = _installed_release(args.runtime_root, args.distro)
    relay = RelayClient(args.relay_url)
    validator = PassiveValidator(
        release=release,
        selection_file=args.selection_file,
        relay_health=relay.health,
        relay_websocket_health=relay.websocket_health,
        distro=args.distro,
        runtime_root=args.runtime_root,
        target_channel=args.target_channel,
        blocking_state_paths=(
            default_runs_root().parent / "runtime" / "production-diagnostic-recovery.json",
        ),
    )
    with ConnectionCoordinator(args.state_root / "coordinator", release) as coordinator:
        harness = P0Harness(
            coordinator, validator, args.state_root / "runs",
            distro=args.distro, runtime_root=args.runtime_root,
            target_channel=args.target_channel,
        )
        current = coordinator.snapshot()
        if current is not None and not current["cleanup"]["verified"]:
            recovery = harness.recover(current)
            if recovery["status"] == "failed":
                print(json.dumps(recovery, indent=2, sort_keys=True))
                raise SystemExit(2)
        result = harness.run(launch_probe=not args.no_launch_probe)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["functional_status"] == "passed" and result["cleanup_status"] == "verified" else 2)


if __name__ == "__main__":
    main()
