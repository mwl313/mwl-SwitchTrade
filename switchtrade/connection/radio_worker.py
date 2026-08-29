"""Long-lived Linux owner between P0b and one identity-bound endpoint launch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import uuid


CONTRACT_VERSION = "p0-side-ready.v1"
LAUNCH_TICKET_VERSION = "p0-launch-ticket.v1"
REQUIRED_MODULES = (
    "usbip_core", "vhci_hcd", "cfg80211", "libarc4", "mac80211", "led_class",
    "rtl8xxxu", "ccm", "cmac", "tun",
)
FIRMWARE_FILES = (
    "regulatory.db", "regulatory.db.p7s", "rtlwifi/rtl8192eu_nic.bin",
)
MODES = {
    "normal", "p0_harness", "direct_a", "direct_b", "diagnostic_automated",
    "diagnostic_a", "diagnostic_b", "diagnostic_suite",
}
_BUS_ID = re.compile(r"^[0-9]+-[0-9]+(?:\.[0-9]+)*$")
_LINUX_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class RadioWorkerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _bounded(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise RadioWorkerError("P0_IDENTITY_INVALID", f"{name} is invalid")
    return value


def _positive(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RadioWorkerError("P0_IDENTITY_INVALID", f"{name} is invalid")
    return value


def process_start_ticks(pid: int | None = None, proc_root: Path = Path("/proc")) -> int:
    process = pid or os.getpid()
    try:
        # The comm field may contain spaces and ')'; fields after its last ')' are stable.
        fields = (proc_root / str(process) / "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
        return _positive(int(fields[19]), "process_start_ticks")
    except (OSError, ValueError, IndexError) as error:
        raise RadioWorkerError(
            "P0_PROCESS_IDENTITY_UNAVAILABLE", "worker process start identity is unavailable") from error


def _sha256(path: Path, code: str = "P0_RUNTIME_ARTIFACT_MISSING") -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RadioWorkerError(code, f"required runtime artifact is missing: {path.name}") from error
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _emit(event: str, **value: object) -> None:
    print(json.dumps({"event": event, **value}, sort_keys=True, separators=(",", ":")), flush=True)


def quiesce_selected_radio(environ: dict[str, str] | None = None) -> None:
    env = environ if environ is not None else os.environ
    netdev = env.get("SWITCHTRADE_IFACE", "")
    if not _LINUX_NAME.fullmatch(netdev):
        raise RadioWorkerError("P0_RADIO_QUIESCE_FAILED", "selected radio netdev is unavailable")
    try:
        result = subprocess.run(
            ["ip", "link", "set", netdev, "down"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RadioWorkerError("P0_RADIO_QUIESCE_FAILED", "radio quiesce command is unavailable") from error
    if result.returncode != 0:
        raise RadioWorkerError("P0_RADIO_QUIESCE_FAILED", "radio interface did not become quiescent")


def _usb_id_for_netdev(netdev: str, sys_root: Path) -> str:
    try:
        path = (sys_root / "class" / "net" / netdev / "device").resolve(strict=True)
    except OSError as error:
        raise RadioWorkerError("P0_NETDEV_MISSING", "selected radio netdev disappeared") from error
    boundary = sys_root.resolve()
    while path != boundary and boundary in path.parents:
        vendor = path / "idVendor"
        product = path / "idProduct"
        if vendor.is_file() and product.is_file():
            return f"{vendor.read_text().strip()}:{product.read_text().strip()}".lower()
        path = path.parent
    raise RadioWorkerError("P0_ADAPTER_IDENTITY_MISMATCH", "netdev USB identity is unavailable")


def _driver_for_netdev(netdev: str, sys_root: Path) -> str:
    try:
        return (sys_root / "class" / "net" / netdev / "device" / "driver").resolve(strict=True).name
    except OSError as error:
        raise RadioWorkerError("P0_DRIVER_MISSING", "selected radio driver disappeared") from error


def build_side_ready(args: argparse.Namespace, environ: dict[str, str] | None = None) -> dict:
    env = environ if environ is not None else os.environ
    try:
        run_id = str(uuid.UUID(args.run_id))
    except (AttributeError, ValueError) as error:
        raise RadioWorkerError("P0_IDENTITY_INVALID", "run_id is invalid") from error
    release = _bounded(args.release, "release", 64)
    if args.mode not in MODES:
        raise RadioWorkerError("P0_IDENTITY_INVALID", "mode is invalid")
    instance_hash = _bounded(args.adapter_instance_sha256, "adapter_instance_sha256", 64).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", instance_hash):
        raise RadioWorkerError("P0_IDENTITY_INVALID", "adapter instance hash is invalid")
    bus_id = _bounded(args.bus_id, "bus_id", 64)
    if not _BUS_ID.fullmatch(bus_id):
        raise RadioWorkerError("P0_IDENTITY_INVALID", "bus_id is invalid")

    netdev = _bounded(env.get("SWITCHTRADE_IFACE"), "netdev", 64)
    phy = _bounded(env.get("SWITCHTRADE_PHY"), "phy", 64)
    usb_id = _bounded(env.get("SWITCHTRADE_USB_ID"), "usb_id", 32).lower()
    if not _LINUX_NAME.fullmatch(netdev) or not re.fullmatch(r"phy[0-9]+", phy):
        raise RadioWorkerError("P0_RADIO_IDENTITY_INVALID", "radio interface identity is invalid")
    if usb_id != "0bda:818b" or _usb_id_for_netdev(netdev, args.sys_root) != usb_id:
        raise RadioWorkerError("P0_ADAPTER_IDENTITY_MISMATCH", "radio USB identity changed during P0b")
    driver = _driver_for_netdev(netdev, args.sys_root)
    if driver != "rtl8xxxu":
        raise RadioWorkerError("P0_DRIVER_MISMATCH", f"unexpected selected radio driver: {driver}")

    missing = [name for name in REQUIRED_MODULES if not (args.sys_root / "module" / name).is_dir()]
    if missing:
        raise RadioWorkerError("P0_MODULE_NOT_LOADED", f"required modules are not loaded: {','.join(missing)}")
    tun_path = args.dev_root / "net" / "tun"
    if args.sys_root == Path("/sys"):
        if not tun_path.is_char_device():
            raise RadioWorkerError("P0_TUN_DEVICE_MISSING", "/dev/net/tun is not a character device")
    elif not tun_path.exists():
        raise RadioWorkerError("P0_TUN_DEVICE_MISSING", "test TUN device is missing")
    if env.get("SWITCHTRADE_P0_RX_PASSED") != "1":
        raise RadioWorkerError("P0_RX_NOT_PROVEN", "actual RX health evidence is missing")
    try:
        rx_channel = int(env["SWITCHTRADE_P0_RX_CHANNEL"])
        target_channel = int(env["SWITCHTRADE_P0_TARGET_CHANNEL"])
    except (KeyError, ValueError) as error:
        raise RadioWorkerError("P0_RX_NOT_PROVEN", "RX channel evidence is invalid") from error
    if not 1 <= rx_channel <= 196 or not 1 <= target_channel <= 196:
        raise RadioWorkerError("P0_RX_NOT_PROVEN", "RX channel evidence is out of range")

    firmware = {
        name: _sha256(args.firmware_root / name, "P0_FIRMWARE_MISSING")
        for name in FIRMWARE_FILES
    }
    kernel_release = platform.release()
    report = {
        "contract_version": CONTRACT_VERSION,
        "schema": 1,
        "run_id": run_id,
        "release": release,
        "mode": args.mode,
        "run_generation": _positive(args.run_generation, "run_generation"),
        "stage_generation": _positive(args.stage_generation, "stage_generation"),
        "wrapper_pid": os.getpid(),
        "process_start_ticks": process_start_ticks(proc_root=args.proc_root),
        "monotonic_ns": time.monotonic_ns(),
        "adapter": {
            "instance_sha256": instance_hash,
            "usb_id": usb_id,
            "bus_id": bus_id,
        },
        "radio": {
            "phy": phy,
            "netdev": netdev,
            "driver": driver,
            "rx_passed": True,
            "rx_channel": rx_channel,
            "target_channel": target_channel,
        },
        "runtime": {
            "kernel_release": kernel_release,
            "integrity_manifest_sha256": _sha256(args.runtime_root / ".switchtrade-integrity.json"),
            "modules": list(REQUIRED_MODULES),
            "firmware_sha256": firmware,
            "tun_device": True,
        },
        "outcome": {"status": "passed", "gate": "P0_SIDE_READY", "code": None},
    }
    return report


def _validate_ticket(ticket: object, report: dict) -> dict:
    if not isinstance(ticket, dict) or ticket.get("contract_version") != LAUNCH_TICKET_VERSION:
        raise RadioWorkerError("P0_LAUNCH_TICKET_INVALID", "launch ticket contract is invalid")
    if ticket.get("action") == "stop":
        return {"action": "stop"}
    endpoint = ticket.get("endpoint")
    expected_endpoint = {
        "p0_harness": "probe",
        "direct_a": "direct_a",
        "direct_b": "direct_b",
    }.get(report["mode"])
    if ticket.get("action") != "launch" or endpoint != expected_endpoint:
        raise RadioWorkerError("P0_LAUNCH_TICKET_INVALID", "launch ticket action is invalid")
    expected = {
        "run_id": report["run_id"],
        "release": report["release"],
        "run_generation": report["run_generation"],
        "stage_generation": report["stage_generation"],
        "adapter_instance_sha256": report["adapter"]["instance_sha256"],
        "usb_id": report["adapter"]["usb_id"],
        "bus_id": report["adapter"]["bus_id"],
        "wrapper_pid": report["wrapper_pid"],
        "process_start_ticks": report["process_start_ticks"],
    }
    if any(ticket.get(name) != value for name, value in expected.items()):
        raise RadioWorkerError("P0_LAUNCH_IDENTITY_MISMATCH", "launch ticket does not match P0 readiness")
    nonce = _bounded(ticket.get("launch_nonce"), "launch_nonce", 128)
    if len(nonce) < 32:
        raise RadioWorkerError("P0_LAUNCH_TICKET_INVALID", "launch nonce is too short")
    attempt_id = ticket.get("attempt_id")
    if report["mode"] not in {"p0_harness", "direct_a", "direct_b"}:
        _bounded(attempt_id, "attempt_id", 128)
    elif attempt_id is not None:
        _bounded(attempt_id, "attempt_id", 128)
    return {
        "action": "launch", "endpoint": endpoint,
        "launch_nonce": nonce, "attempt_id": attempt_id,
    }


def serve(args: argparse.Namespace) -> int:
    try:
        report = build_side_ready(args)
        _atomic_json(args.report, report)
        _emit("p0_side_ready", report=report)
        line = sys.stdin.readline(16 * 1024)
        if not line:
            quiesce_selected_radio()
            _emit("worker_stopping", reason="control_disconnected")
            return 0
        if len(line) >= 16 * 1024 and not line.endswith("\n"):
            raise RadioWorkerError("P0_LAUNCH_TICKET_INVALID", "launch ticket exceeds its bound")
        try:
            ticket = _validate_ticket(json.loads(line), report)
        except json.JSONDecodeError as error:
            raise RadioWorkerError("P0_LAUNCH_TICKET_INVALID", "launch ticket JSON is invalid") from error
        if ticket["action"] == "stop":
            quiesce_selected_radio()
            _emit("worker_stopping", reason="requested")
            return 0
        _emit(
            "endpoint_exec", run_id=report["run_id"], launch_nonce=ticket["launch_nonce"],
            endpoint=ticket["endpoint"], wrapper_pid=report["wrapper_pid"],
            process_start_ticks=report["process_start_ticks"],
        )
        if ticket["endpoint"] == "direct_a":
            endpoint_module = "switchtrade.connection.direct_a_endpoint"
            endpoint_args = [
                "--phy", report["radio"]["phy"],
                "--ifname", f"sta-a-{report['run_id'].replace('-', '')[:8]}",
                "--keys", str(args.runtime_root / "config" / "prod.keys"),
                "--report", str(args.report.with_name("direct-a-stage-report.json")),
            ]
        elif ticket["endpoint"] == "direct_b":
            suffix = report["run_id"].replace("-", "")[:8]
            endpoint_module = "switchtrade.connection.direct_b_endpoint"
            endpoint_args = [
                "--phy", report["radio"]["phy"],
                "--ap-ifname", f"ap-b-{suffix}",
                "--monitor-ifname", f"mon-b-{suffix}",
                "--tap-ifname", f"tap-b-{suffix}",
                "--keys", str(args.runtime_root / "config" / "prod.keys"),
                "--report", str(args.report.with_name("direct-b-stage-report.json")),
            ]
        else:
            endpoint_module = "switchtrade.connection.worker_probe"
            endpoint_args = []
        argv = [
            sys.executable, "-m", endpoint_module,
            "--run-id", report["run_id"], "--release", report["release"],
            "--launch-nonce", ticket["launch_nonce"],
            "--process-start-ticks", str(report["process_start_ticks"]),
            *endpoint_args,
        ]
        os.execv(sys.executable, argv)
    except RadioWorkerError as error:
        cleanup_verified = False
        cleanup_code = None
        if os.environ.get("SWITCHTRADE_IFACE"):
            try:
                quiesce_selected_radio()
                cleanup_verified = True
            except RadioWorkerError as cleanup_error:
                cleanup_code = cleanup_error.code
        _emit(
            "worker_failed", code=error.code, message=error.message,
            cleanup_verified=cleanup_verified, cleanup_code=cleanup_code,
        )
        return 2
    except (OSError, subprocess.SubprocessError) as error:
        _emit("worker_failed", code="P0_WORKER_INTERNAL", message=type(error).__name__)
        return 2
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="SwitchTrade ABC+D P0 radio worker")
    value.add_argument("--run-id", required=True)
    value.add_argument("--release", required=True)
    value.add_argument("--mode", choices=sorted(MODES), required=True)
    value.add_argument("--run-generation", type=int, default=1)
    value.add_argument("--stage-generation", type=int, default=1)
    value.add_argument("--adapter-instance-sha256", required=True)
    value.add_argument("--bus-id", required=True)
    value.add_argument("--report", type=Path, required=True)
    value.add_argument("--sys-root", type=Path, default=Path(os.environ.get("SWITCHTRADE_SYSFS_ROOT", "/sys")))
    value.add_argument("--dev-root", type=Path, default=Path(os.environ.get("SWITCHTRADE_DEV_ROOT", "/dev")))
    value.add_argument("--proc-root", type=Path, default=Path(os.environ.get("SWITCHTRADE_PROC_ROOT", "/proc")))
    value.add_argument(
        "--firmware-root", type=Path,
        default=Path(os.environ.get("SWITCHTRADE_FIRMWARE_ROOT", "/lib/firmware")),
    )
    value.add_argument("--runtime-root", type=Path, default=Path("/opt/switchtrade"))
    return value


def main() -> None:
    raise SystemExit(serve(parser().parse_args()))


if __name__ == "__main__":
    main()
