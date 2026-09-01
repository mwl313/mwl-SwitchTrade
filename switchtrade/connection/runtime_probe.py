"""Strict, non-mutating Linux half of ABC+D P0a."""

from __future__ import annotations

import argparse
try:
    import fcntl
except ImportError:  # imported by Windows source tests; the probe itself runs only inside WSL
    fcntl = None
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from switchtrade.hardware import (
    HardwarePolicyError, require_hardware, required_firmware, required_modules, select_profile,
)

CONTRACT_VERSION = "p0-runtime-passive.v1"
REQUIRED_COMMANDS = (
    "bash", "flock", "timeout", "ip", "iw", "tcpdump", "rfkill", "readlink",
    "pgrep", "pkill", "modprobe", "modinfo", "usbreset",
)
REQUIRED_ARTIFACTS = (
    "switchtrade/connection/coordinator.py",
    "switchtrade/connection/radio_worker.py",
    "switchtrade/endpoint.py",
    "bridge/frlgsim/transport.py",
    "scripts/wsl-radio-prepare.sh",
    "scripts/radio-health-gate.sh",
    "config/prod.keys",
)


class RuntimeProbeError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


def _read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise RuntimeProbeError(code, "P0a_runtime", f"invalid runtime metadata: {path.name}") from error
    if not isinstance(value, dict):
        raise RuntimeProbeError(code, "P0a_runtime", f"invalid runtime metadata: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RuntimeProbeError(
            "P0_RUNTIME_ARTIFACT_MISSING", "P0a_release", f"runtime artifact is missing: {path.name}") from error
    return digest.hexdigest()


def _command(args: list[str], code: str) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeProbeError(code, "P0a_runtime", f"runtime command unavailable: {args[0]}") from error
    if result.returncode != 0:
        raise RuntimeProbeError(code, "P0a_runtime", f"runtime command failed: {args[0]}")
    return result.stdout.strip()


def _capabilities(proc_root: Path) -> None:
    if os.geteuid() != 0:
        raise RuntimeProbeError("P0_PRIVILEGE_MISSING", "P0a_privilege", "P0 requires the packaged root user")
    try:
        status = (proc_root / "self" / "status").read_text(encoding="ascii")
        effective = int(re.search(r"^CapEff:\s*([0-9a-f]+)$", status, re.M).group(1), 16)
    except (OSError, ValueError, AttributeError) as error:
        raise RuntimeProbeError(
            "P0_PRIVILEGE_UNKNOWN", "P0a_privilege", "effective Linux capabilities are unavailable") from error
    required = (1 << 12) | (1 << 13)  # CAP_NET_ADMIN and CAP_NET_RAW
    if effective & required != required:
        raise RuntimeProbeError(
            "P0_PRIVILEGE_MISSING", "P0a_privilege", "CAP_NET_ADMIN and CAP_NET_RAW are required")


def _verify_integrity(root: Path, release: str) -> tuple[str, int]:
    marker = _read_json(root / ".switchtrade-release.json", "P0_RELEASE_MARKER_INVALID")
    if marker.get("schema") != 1 or marker.get("release_id") != release:
        raise RuntimeProbeError("P0_RELEASE_MISMATCH", "P0a_release", "installed WSL release does not match")
    integrity = _read_json(root / ".switchtrade-integrity.json", "P0_INTEGRITY_MANIFEST_INVALID")
    hashes = integrity.get("artifact_hashes")
    if integrity.get("schema") != 1 or integrity.get("release_id") != release or not isinstance(hashes, dict):
        raise RuntimeProbeError("P0_INTEGRITY_MANIFEST_INVALID", "P0a_release", "runtime integrity manifest is invalid")
    for relative in REQUIRED_ARTIFACTS:
        if relative not in hashes:
            raise RuntimeProbeError(
                "P0_RUNTIME_ARTIFACT_MISSING", "P0a_release", f"required artifact is not manifested: {relative}")
    for relative, expected in hashes.items():
        if (not isinstance(relative, str) or not isinstance(expected, str) or
                not re.fullmatch(r"[0-9a-f]{64}|symlink:.+", expected)):
            raise RuntimeProbeError("P0_INTEGRITY_MANIFEST_INVALID", "P0a_release", "runtime hash entry is invalid")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeProbeError(
                "P0_INTEGRITY_MANIFEST_INVALID", "P0a_release", "runtime hash path escapes its root")
        path = root / relative_path
        if expected.startswith("symlink:"):
            if not path.is_symlink() or os.readlink(path) != expected.removeprefix("symlink:"):
                raise RuntimeProbeError("P0_PAYLOAD_HASH_MISMATCH", "P0a_release", "runtime symlink changed")
        elif _sha256(path) != expected:
            raise RuntimeProbeError("P0_PAYLOAD_HASH_MISMATCH", "P0a_release", f"runtime artifact changed: {relative}")
    return _sha256(root / ".switchtrade-integrity.json"), len(hashes)


def _verify_dependencies(root: Path) -> dict[str, str]:
    requirements = root / "bridge" / "requirements.txt"
    if Path(sys.executable).resolve() != (root / "bridge" / ".venv" / "bin" / "python").resolve():
        raise RuntimeProbeError("P0_PYTHON_RUNTIME_MISMATCH", "P0a_runtime", "probe is not using packaged Python")
    found = {}
    try:
        lines = requirements.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeProbeError("P0_DEPENDENCY_LOCK_MISSING", "P0a_runtime", "dependency lock is missing") from error
    for raw in lines:
        item = raw.strip()
        if not item or item.startswith("#") or item.startswith("-r "):
            continue
        if "==" not in item:
            raise RuntimeProbeError("P0_DEPENDENCY_LOCK_INVALID", "P0a_runtime", "dependency is not exactly pinned")
        name, expected = item.split("==", 1)
        try:
            actual = version(name)
        except PackageNotFoundError as error:
            raise RuntimeProbeError("P0_DEPENDENCY_MISSING", "P0a_runtime", f"dependency is missing: {name}") from error
        if actual != expected:
            raise RuntimeProbeError("P0_DEPENDENCY_MISMATCH", "P0a_runtime", f"dependency mismatch: {name}")
        found[name.lower()] = actual
    return found


def _verify_modules(kernel_release: str, modules_root: Path,
                    names: tuple[str, ...]) -> dict[str, str]:
    tree = modules_root / kernel_release
    if not tree.is_dir():
        raise RuntimeProbeError("P0_MODULE_TREE_MISSING", "P0a_modules", "running kernel module tree is missing")
    evidence = {}
    for name in names:
        path = _command(["modinfo", "-n", name], "P0_MODULE_MISSING")
        if path == "(builtin)":
            evidence[name] = f"builtin:{kernel_release}"
            continue
        if not Path(path).is_file():
            raise RuntimeProbeError("P0_MODULE_MISSING", "P0a_modules", f"module file is missing: {name}")
        value = _command(["modinfo", "-F", "vermagic", name], "P0_MODULE_VERMAGIC_UNKNOWN").split()
        if not value:
            raise RuntimeProbeError(
                "P0_MODULE_VERMAGIC_UNKNOWN", "P0a_modules", f"module vermagic is missing: {name}")
        vermagic = value[0]
        if vermagic != kernel_release:
            raise RuntimeProbeError("P0_MODULE_VERMAGIC_MISMATCH", "P0a_modules", f"module mismatch: {name}")
        evidence[name] = vermagic
    return evidence


def _verify_firmware(firmware_root: Path, manifest_path: Path,
                     files: tuple[str, ...]) -> dict[str, str]:
    try:
        entries = {
            relative: expected.lower()
            for expected, relative in (
                line.split(maxsplit=1) for line in manifest_path.read_text(encoding="ascii").splitlines() if line.strip()
            )
        }
    except (OSError, ValueError) as error:
        raise RuntimeProbeError("P0_FIRMWARE_MANIFEST_INVALID", "P0a_firmware", "firmware manifest is invalid") from error
    evidence = {}
    for relative in files:
        expected = entries.get(f"firmware/{relative}") or entries.get(relative)
        if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RuntimeProbeError("P0_FIRMWARE_MANIFEST_INVALID", "P0a_firmware", f"firmware is not pinned: {relative}")
        actual = _sha256(firmware_root / relative)
        if actual != expected:
            raise RuntimeProbeError("P0_FIRMWARE_HASH_MISMATCH", "P0a_firmware", f"firmware changed: {relative}")
        evidence[relative] = actual
    return evidence


def _verify_channel(channel: int) -> None:
    if not 1 <= channel <= 13:
        raise RuntimeProbeError("P0_CHANNEL_INVALID", "P0a_regulatory", "only 2.4 GHz channels are supported")
    # P0a stays passive and validates the pinned regulatory database above. The live kernel
    # regulatory decision is proven in P0b when the prepared PHY accepts the target channel.


def _usb_matches(sys_root: Path, usb_id: str) -> int:
    found = 0
    for vendor in (sys_root / "bus" / "usb" / "devices").glob("*/idVendor"):
        try:
            actual = f"{vendor.read_text().strip()}:{(vendor.parent / 'idProduct').read_text().strip()}".lower()
        except OSError:
            continue
        found += actual == usb_id
    return found


def _radio_lock_available(lock_path: Path) -> bool:
    if fcntl is None:
        raise RuntimeProbeError("P0_RUNTIME_NOT_WSL", "P0a_runtime", "radio lock probe requires Linux")
    if not lock_path.exists():
        return True
    try:
        with lock_path.open("r+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return True
    except (OSError, BlockingIOError):
        return False


def _active_endpoint_count(proc_root: Path) -> int:
    count = 0
    needles = (b"switchtrade.endpoint", b"run-beta-endpoint.sh", b"switchtrade.connection.radio_worker")
    for command_line in proc_root.glob("[0-9]*/cmdline"):
        try:
            value = command_line.read_bytes()
        except OSError:
            continue
        count += any(needle in value for needle in needles)
    return count


def probe(args: argparse.Namespace) -> dict:
    try:
        profile = require_hardware(select_profile(args.usb_id), "relay")
    except (HardwarePolicyError, ValueError) as error:
        raise RuntimeProbeError(
            "P0_HARDWARE_POLICY_REJECTED", "P0a_adapter",
            "selected hardware profile is unavailable",
        ) from error
    missing = [name for name in REQUIRED_COMMANDS if shutil.which(name) is None]
    if missing:
        raise RuntimeProbeError("P0_TOOL_MISSING", "P0a_tools", f"required tools are missing: {','.join(missing)}")
    _capabilities(args.proc_root)
    distro = _read_json(args.distro_marker, "P0_DISTRO_MARKER_INVALID")
    if distro.get("owner") != "switchtrade-provisioner" or distro.get("release_id") != args.release:
        raise RuntimeProbeError("P0_DISTRO_MISMATCH", "P0a_runtime", "active WSL distribution is not the installed release")
    integrity_sha, artifact_count = _verify_integrity(args.root, args.release)
    dependencies = _verify_dependencies(args.root)
    kernel_release = os.uname().release
    modules = _verify_modules(kernel_release, args.modules_root, required_modules(profile))
    firmware = _verify_firmware(
        args.firmware_root, args.firmware_manifest, required_firmware(profile))
    _verify_channel(args.target_channel)
    keys = args.root / "config" / "prod.keys"
    try:
        if not keys.is_file() or keys.stat().st_mode & 0o077:
            raise RuntimeProbeError("P0_KEYS_PERMISSIONS_INVALID", "P0a_runtime", "prod.keys must be private")
    except OSError as error:
        raise RuntimeProbeError("P0_KEYS_MISSING", "P0a_runtime", "prod.keys is unavailable") from error
    active_endpoints = _active_endpoint_count(args.proc_root)
    if active_endpoints:
        raise RuntimeProbeError("P0_ENDPOINT_ACTIVE", "P0a_exclusivity", "an endpoint or radio worker is already active")
    radio_lock = args.radio_lock or Path(
        f"/run/lock/switchtrade-radio-{profile.usb_id.replace(':', '-')}.lock")
    if not _radio_lock_available(radio_lock):
        raise RuntimeProbeError("P0_RADIO_BUSY", "P0a_exclusivity", "the Linux radio lock is already owned")
    return {
        "contract_version": CONTRACT_VERSION,
        "schema": 1,
        "release": args.release,
        "status": "passed",
        "kernel_release": kernel_release,
        "integrity_manifest_sha256": integrity_sha,
        "artifact_count": artifact_count,
        "module_vermagic": modules,
        "firmware_sha256": firmware,
        "dependency_versions": dependencies,
        "target_channel": args.target_channel,
        "attached_usb_matches": _usb_matches(args.sys_root, args.usb_id),
        "active_endpoint_count": active_endpoints,
        "checks": {
            "release": True, "payload_hashes": True, "distro": True, "python": True,
            "dependencies": True, "tools": True, "privileges": True, "modules": True,
            "firmware": True, "regulatory": True, "keys_private": True,
            "radio_lock_available": True, "endpoint_absent": True,
        },
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="SwitchTrade passive P0 runtime probe")
    value.add_argument("--release", required=True)
    value.add_argument("--target-channel", type=int, default=6)
    value.add_argument("--root", type=Path, default=Path("/opt/switchtrade"))
    value.add_argument("--proc-root", type=Path, default=Path("/proc"))
    value.add_argument("--sys-root", type=Path, default=Path("/sys"))
    value.add_argument("--modules-root", type=Path, default=Path("/lib/modules"))
    value.add_argument("--firmware-root", type=Path, default=Path("/lib/firmware"))
    value.add_argument("--firmware-manifest", type=Path, default=Path("/etc/switchtrade/firmware-manifest.sha256"))
    value.add_argument("--distro-marker", type=Path, default=Path("/etc/switchtrade-distro.json"))
    value.add_argument("--radio-lock", type=Path)
    value.add_argument("--usb-id", required=True)
    return value


def main() -> None:
    try:
        result = probe(parser().parse_args())
    except RuntimeProbeError as error:
        result = {
            "contract_version": CONTRACT_VERSION, "schema": 1, "status": "failed",
            "code": error.code, "gate": error.gate, "message": error.message,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
