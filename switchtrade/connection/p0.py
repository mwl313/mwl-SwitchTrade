"""ABC+D P0 passive validation and exact USB lease ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import locale
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

from switchtrade.hardware import HardwarePolicyError, require_hardware, select_profile


PASSIVE_CONTRACT = "p0-passive.v1"
USB_ID = "0bda:818b"
QUALIFIED_USBIPD_VERSION = (5, 3, 0)
MINIMUM_WSL_VERSION = (2, 4, 4)
_INSTANCE_USB = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)
_BUS_ID = re.compile(r"^[0-9]+-[0-9]+(?:\.[0-9]+)*$")


class P0Error(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


@dataclass(frozen=True)
class UsbAdapter:
    usb_id: str
    instance_id: str
    bus_id: str
    shared: bool
    attached: bool

    @property
    def instance_sha256(self) -> str:
        return hashlib.sha256(self.instance_id.casefold().encode("utf-8")).hexdigest()

    def public(self) -> dict:
        return {
            "usb_id": self.usb_id,
            "instance_sha256": self.instance_sha256,
            "bus_id": self.bus_id,
            "shared": self.shared,
            "prior_attached": self.attached,
        }


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _decode_native_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    sample = value[:256]
    even_nulls = sample[0::2].count(0)
    odd_nulls = sample[1::2].count(0)
    if odd_nulls >= 2 and odd_nulls > even_nulls * 2:
        return value.decode("utf-16-le")
    if even_nulls >= 2 and even_nulls > odd_nulls * 2:
        return value.decode("utf-16-be")
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False)):
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return value.decode("utf-8", errors="replace")


def run_command(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, capture_output=True, timeout=timeout, check=False,
    )
    return subprocess.CompletedProcess(
        result.args, result.returncode,
        _decode_native_output(result.stdout), _decode_native_output(result.stderr),
    )


def atomic_json(path: Path, value: dict, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if private:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path, code: str, gate: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise P0Error(code, gate, f"invalid state file: {path.name}") from error
    if not isinstance(value, dict):
        raise P0Error(code, gate, f"invalid state file: {path.name}")
    return value


def _run(runner: Runner, command: list[str], timeout: float, *, code: str, gate: str) -> str:
    try:
        result = runner(command, timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise P0Error(code, gate, f"command unavailable: {command[0]}") from error
    if result.returncode != 0:
        raise P0Error(code, gate, f"command failed: {command[0]}")
    return result.stdout.strip()


def _version(text: str, code: str, gate: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", text)
    if not match:
        raise P0Error(code, gate, "tool version is unavailable")
    return tuple(int(item) for item in match.groups())


def parse_usbipd_state(text: str) -> list[UsbAdapter]:
    try:
        value = json.loads(text)
        devices = value["Devices"]
    except (TypeError, ValueError, KeyError) as error:
        raise P0Error("P0_USBIPD_STATE_INVALID", "P0a_adapter", "usbipd state is invalid") from error
    if not isinstance(devices, list):
        raise P0Error("P0_USBIPD_STATE_INVALID", "P0a_adapter", "usbipd device inventory is invalid")
    result = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        instance_id = item.get("InstanceId")
        bus_id = item.get("BusId")
        if not isinstance(instance_id, str) or not isinstance(bus_id, str) or not _BUS_ID.fullmatch(bus_id):
            continue
        match = _INSTANCE_USB.search(instance_id)
        if not match:
            continue
        result.append(UsbAdapter(
            usb_id=f"{match.group(1)}:{match.group(2)}".lower(),
            instance_id=instance_id,
            bus_id=bus_id,
            shared=bool(item.get("PersistedGuid") or item.get("StubInstanceId")),
            attached=bool(item.get("ClientIPAddress")),
        ))
    return result


def selected_adapter(selection_file: Path, inventory: list[UsbAdapter]) -> UsbAdapter:
    selection = _read_json(selection_file, "P0_ADAPTER_SELECTION_INVALID", "P0a_adapter")
    instance_id = selection.get("instance_id")
    if (selection.get("schema") != 1 or selection.get("usb_id") != USB_ID or
            not isinstance(instance_id, str) or not instance_id):
        raise P0Error(
            "P0_ADAPTER_SELECTION_INVALID", "P0a_adapter",
            "select one authorized production adapter before P0",
        )
    matches = [item for item in inventory if item.instance_id.casefold() == instance_id.casefold()]
    if len(matches) != 1 or matches[0].usb_id != USB_ID:
        raise P0Error(
            "P0_ADAPTER_IDENTITY_UNAVAILABLE", "P0a_adapter",
            "the saved Windows adapter identity does not resolve exactly once",
        )
    adapter = matches[0]
    if not adapter.shared:
        raise P0Error(
            "P0_ADAPTER_NOT_AUTHORIZED", "P0a_usbipd",
            "the selected adapter is not shared with usbipd",
        )
    return adapter


def linux_usb_probe(usb_id: str = USB_ID, sys_root: Path = Path("/sys")) -> dict:
    try:
        devices = []
        for vendor in (sys_root / "bus" / "usb" / "devices").glob("*/idVendor"):
            try:
                found = f"{vendor.read_text().strip()}:{(vendor.parent / 'idProduct').read_text().strip()}".lower()
                if found == usb_id:
                    devices.append(vendor.parent.resolve())
            except OSError:
                continue
        def linked_items(root: Path) -> list[Path]:
            result = []
            for item in root.glob("*/device"):
                try:
                    target = item.resolve(strict=True)
                except OSError:
                    continue
                if any(target == device or device in target.parents for device in devices):
                    result.append(item.parent)
            return result
        interfaces = linked_items(sys_root / "class" / "net")
        interfaces_up = 0
        for interface in interfaces:
            try:
                interfaces_up += bool(int((interface / "flags").read_text().strip(), 0) & 1)
            except (OSError, ValueError):
                return {
                    "status": "unknown", "matches": len(devices),
                    "interface_present": bool(interfaces),
                    "phy_present": bool(linked_items(sys_root / "class" / "ieee80211")),
                    "interfaces_up": None,
                }
        return {
            "status": "present" if devices else "absent",
            "matches": len(devices),
            "interface_present": bool(interfaces),
            "phy_present": bool(linked_items(sys_root / "class" / "ieee80211")),
            "interfaces_up": interfaces_up,
        }
    except OSError:
        return {
            "status": "unknown", "matches": None, "interface_present": None,
            "phy_present": None, "interfaces_up": None,
        }


class PassiveValidator:
    """P0a is read-only: it never issues usbipd attach/detach or modprobe."""

    def __init__(
        self,
        *,
        release: str,
        selection_file: Path,
        relay_health: Callable[[], dict] | None = None,
        relay_websocket_health: Callable[[], bool] | None = None,
        runner: Runner = run_command,
        distro: str = "SwitchTrade",
        runtime_root: str = "/opt/switchtrade",
        packaged_python: str = "/opt/switchtrade/bridge/.venv/bin/python",
        target_channel: int = 6,
        required_room_contract: str = "room-control.v1",
        required_rfu_contract: str = "rfu-tunnel.v1",
        required_capabilities: frozenset[str] = frozenset({"passive-websocket-health.v1"}),
        blocking_state_paths: tuple[Path, ...] = (),
        require_relay: bool = True,
    ):
        self.release = release
        self.selection_file = Path(selection_file)
        self.relay_health = relay_health
        self.relay_websocket_health = relay_websocket_health
        self.runner = runner
        self.distro = distro
        self.runtime_root = runtime_root
        self.packaged_python = packaged_python
        self.target_channel = target_channel
        self.required_room_contract = required_room_contract
        self.required_rfu_contract = required_rfu_contract
        self.required_capabilities = required_capabilities
        self.blocking_state_paths = tuple(Path(item) for item in blocking_state_paths)
        self.require_relay = require_relay

    def requested_identity(self) -> tuple[str, str]:
        """Read only the requested identity so a failed P0a still receives a run record."""
        selection = _read_json(
            self.selection_file, "P0_ADAPTER_SELECTION_INVALID", "P0a_adapter")
        instance_id = selection.get("instance_id")
        if (selection.get("schema") != 1 or selection.get("usb_id") != USB_ID or
                not isinstance(instance_id, str) or not instance_id):
            raise P0Error(
                "P0_ADAPTER_SELECTION_INVALID", "P0a_adapter",
                "select one authorized production adapter before P0",
            )
        return instance_id, USB_ID

    def _runtime_probe(self) -> dict:
        arguments = [
            self.packaged_python, "-m", "switchtrade.connection.runtime_probe",
            "--release", self.release, "--target-channel", str(self.target_channel),
            "--root", self.runtime_root,
        ]
        if os.name == "nt":
            command = [
                "wsl.exe", "-d", self.distro, "-u", "root", "--cd", self.runtime_root,
                "--", *arguments,
            ]
        else:
            command = arguments
        try:
            result = self.runner(command, 30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise P0Error("P0_RUNTIME_PROBE_UNAVAILABLE", "P0a_runtime", "WSL runtime probe is unavailable") from error
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError) as error:
            raise P0Error("P0_RUNTIME_PROBE_INVALID", "P0a_runtime", "WSL runtime probe result is invalid") from error
        if not isinstance(value, dict):
            raise P0Error("P0_RUNTIME_PROBE_INVALID", "P0a_runtime", "WSL runtime probe result is invalid")
        if result.returncode != 0 or value.get("status") != "passed":
            raise P0Error(
                str(value.get("code") or "P0_RUNTIME_PROBE_FAILED"),
                str(value.get("gate") or "P0a_runtime"),
                str(value.get("message") or "WSL runtime validation failed"),
            )
        if value.get("contract_version") != "p0-runtime-passive.v1" or value.get("release") != self.release:
            raise P0Error("P0_RUNTIME_CONTRACT_MISMATCH", "P0a_release", "WSL runtime probe contract differs")
        return value

    def validate(self) -> tuple[UsbAdapter, dict]:
        try:
            require_hardware(select_profile(USB_ID), "relay")
        except (HardwarePolicyError, ValueError) as error:
            raise P0Error("P0_HARDWARE_POLICY_REJECTED", "P0a_adapter", str(error)) from error
        if any(path.exists() for path in self.blocking_state_paths):
            raise P0Error(
                "P0_RECOVERY_REQUIRED", "P0a_exclusivity",
                "unresolved endpoint, diagnostic, or cleanup state blocks P0",
            )
        wsl_text = _run(
            self.runner, ["wsl.exe", "--version"], 5,
            code="P0_WSL_UNAVAILABLE", gate="P0a_tools",
        )
        if _version(wsl_text, "P0_WSL_VERSION_UNKNOWN", "P0a_tools") < MINIMUM_WSL_VERSION:
            raise P0Error("P0_WSL_VERSION_UNSUPPORTED", "P0a_tools", "installed WSL is too old")
        usbipd_text = _run(
            self.runner, ["usbipd.exe", "--version"], 5,
            code="P0_USBIPD_UNAVAILABLE", gate="P0a_tools",
        )
        if _version(usbipd_text, "P0_USBIPD_VERSION_UNKNOWN", "P0a_tools") != QUALIFIED_USBIPD_VERSION:
            raise P0Error(
                "P0_USBIPD_VERSION_UNSUPPORTED", "P0a_tools",
                "installed usbipd-win does not match the qualified release",
            )
        state_text = _run(
            self.runner, ["usbipd.exe", "state"], 5,
            code="P0_USBIPD_STATE_UNAVAILABLE", gate="P0a_adapter",
        )
        adapter = selected_adapter(self.selection_file, parse_usbipd_state(state_text))
        runtime = self._runtime_probe()
        matches = runtime.get("attached_usb_matches")
        if adapter.attached and matches != 1:
            raise P0Error(
                "P0_ADAPTER_OWNED_ELSEWHERE", "P0a_usbipd",
                "the selected adapter is attached outside the active SwitchTrade runtime",
            )
        if not adapter.attached and matches not in {0, None}:
            raise P0Error("P0_ADAPTER_STATE_CONFLICT", "P0a_usbipd", "Windows and Linux USB state disagree")
        if self.require_relay:
            if self.relay_health is None or self.relay_websocket_health is None:
                raise P0Error(
                    "P0_RELAY_CONFIGURATION_INVALID", "P0a_relay",
                    "relay validation is not configured",
                )
            try:
                health = self.relay_health()
            except Exception as error:
                raise P0Error("P0_RELAY_UNAVAILABLE", "P0a_relay", "relay health is unavailable") from error
            capabilities = set(health.get("capabilities", [])) if isinstance(health, dict) else set()
            if (not isinstance(health, dict) or health.get("status") != "ready" or
                    health.get("room_contract") != self.required_room_contract or
                    health.get("rfu_contract") != self.required_rfu_contract or
                    not self.required_capabilities.issubset(capabilities)):
                raise P0Error("P0_RELAY_CONTRACT_MISMATCH", "P0a_relay", "relay contracts are incompatible")
            try:
                server_time = datetime.fromisoformat(str(health["server_time_utc"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError) as error:
                raise P0Error("P0_RELAY_TIME_UNAVAILABLE", "P0a_relay", "relay time evidence is unavailable") from error
            if abs((datetime.now(timezone.utc) - server_time).total_seconds()) > 300:
                raise P0Error("P0_SYSTEM_TIME_SKEW", "P0a_relay", "system clock differs from the relay")
            try:
                websocket_ok = self.relay_websocket_health()
            except Exception as error:
                raise P0Error("P0_RELAY_WEBSOCKET_UNAVAILABLE", "P0a_relay", "relay WebSocket path is unavailable") from error
            if websocket_ok is not True:
                raise P0Error("P0_RELAY_WEBSOCKET_UNAVAILABLE", "P0a_relay", "relay WebSocket path is unavailable")
            relay = {
                "room_contract": self.required_room_contract,
                "rfu_contract": self.required_rfu_contract,
                "capabilities": sorted(self.required_capabilities),
                "https": True,
                "websocket": True,
                "clock_within_300_seconds": True,
            }
            relay_path = True
        else:
            relay = {"status": "not_required"}
            relay_path = None
        report = {
            "contract_version": PASSIVE_CONTRACT,
            "schema": 1,
            "release": self.release,
            "status": "passed",
            "adapter": adapter.public(),
            "runtime": runtime,
            "relay": relay,
            "checks": {
                "topology": True,
                "release_contracts": True,
                "runtime": True,
                "tools_privilege": True,
                "relay_path": relay_path,
                "exclusive": True,
                "adapter_identity": True,
                "usbipd": True,
                "modules": True,
                "firmware_regulatory": True,
            },
        }
        return adapter, report


class UsbLease:
    """One run owns one exact Windows adapter and restores its prior attach state."""

    def __init__(
        self,
        adapter: UsbAdapter,
        recovery_file: Path,
        *,
        runner: Runner = run_command,
        distro: str = "SwitchTrade",
        probe: Callable[[str], dict] = linux_usb_probe,
        deadline: float = 12,
    ):
        self.adapter = adapter
        self.recovery_file = Path(recovery_file)
        self.runner = runner
        self.distro = distro
        self.probe = probe
        self.deadline = deadline
        self.acquired_by_run = False
        self.active = False

    @classmethod
    def from_recovery(
        cls,
        recovery_file: Path,
        *,
        runner: Runner = run_command,
        distro: str = "SwitchTrade",
        probe: Callable[[str], dict] = linux_usb_probe,
        deadline: float = 12,
    ) -> "UsbLease":
        value = _read_json(Path(recovery_file), "P0_RECOVERY_STATE_INVALID", "D10_usb_return")
        required = ("usb_id", "instance_id", "bus_id", "prior_attached", "attach_intent")
        if (value.get("schema") != 1 or value.get("usb_id") != USB_ID or
                not all(name in value for name in required) or
                not isinstance(value.get("instance_id"), str) or not value["instance_id"] or
                not isinstance(value.get("bus_id"), str) or not _BUS_ID.fullmatch(value["bus_id"]) or
                not isinstance(value.get("prior_attached"), bool) or
                not isinstance(value.get("attach_intent"), bool)):
            raise P0Error("P0_RECOVERY_STATE_INVALID", "D10_usb_return", "USB recovery state is invalid")
        lease = cls(
            UsbAdapter(
                usb_id=value["usb_id"], instance_id=value["instance_id"],
                bus_id=value["bus_id"], shared=True, attached=value["prior_attached"],
            ),
            Path(recovery_file), runner=runner, distro=distro, probe=probe, deadline=deadline,
        )
        # An attach intent written for a previously detached adapter is sufficient recovery
        # authority. The attach command may have succeeded just before the control process died.
        lease.acquired_by_run = bool(value["attach_intent"] and not value["prior_attached"])
        lease.active = True
        return lease

    def _inventory(self) -> list[UsbAdapter]:
        value = _run(
            self.runner, ["usbipd.exe", "state"], 5,
            code="P0_USBIPD_STATE_UNAVAILABLE", gate="P0b_lease",
        )
        return parse_usbipd_state(value)

    def _current(self) -> UsbAdapter:
        matches = [
            item for item in self._inventory()
            if item.instance_id.casefold() == self.adapter.instance_id.casefold()
        ]
        if len(matches) != 1 or matches[0].usb_id != self.adapter.usb_id:
            raise P0Error("P0_ADAPTER_IDENTITY_CHANGED", "P0b_lease", "selected adapter identity changed")
        return matches[0]

    def _current_after_detach(self) -> UsbAdapter | None:
        """Allow Windows' bounded post-detach re-enumeration gap without losing identity."""
        matches = [
            item for item in self._inventory()
            if item.instance_id.casefold() == self.adapter.instance_id.casefold()
        ]
        if not matches:
            return None
        if (len(matches) != 1 or matches[0].usb_id != self.adapter.usb_id or
                matches[0].bus_id != self.adapter.bus_id):
            raise P0Error(
                "P0_ADAPTER_IDENTITY_CHANGED", "D10_usb_return",
                "selected adapter identity changed during USB return",
            )
        return matches[0]

    def _persist(self, *, attach_intent: bool) -> None:
        atomic_json(self.recovery_file, {
            "schema": 1,
            "usb_id": self.adapter.usb_id,
            "instance_id": self.adapter.instance_id,
            "bus_id": self.adapter.bus_id,
            "prior_attached": self.adapter.attached,
            "attach_intent": attach_intent,
            "acquired_by_run": self.acquired_by_run,
        }, private=True)

    def acquire(self) -> dict:
        if self.active:
            return self.evidence()
        current = self._current()
        if current.bus_id != self.adapter.bus_id or current.attached != self.adapter.attached:
            raise P0Error("P0_ADAPTER_IDENTITY_CHANGED", "P0b_lease", "adapter changed after P0a")
        self._persist(attach_intent=not current.attached)
        if current.attached:
            linux = self.probe(self.adapter.usb_id)
            if linux.get("status") != "present" or linux.get("matches") != 1:
                raise P0Error(
                    "P0_ADAPTER_OWNED_ELSEWHERE", "P0b_lease",
                    "pre-attached adapter does not belong to this SwitchTrade runtime",
                )
        else:
            prerequisite = ["modprobe", "-a", "usbip-core", "vhci-hcd"]
            if os.name == "nt":
                prerequisite = [
                    "wsl.exe", "-d", self.distro, "-u", "root", "--", *prerequisite,
                ]
            _run(
                self.runner, prerequisite, 5,
                code="P0_USBIP_MODULE_FAILED", gate="P0b_usbip",
            )
            # From this point onward cleanup may detach only because P0a proved the prior state
            # was detached. Persist that intent before the external attach command can succeed.
            self.acquired_by_run = True
            self._persist(attach_intent=True)
            _run(
                self.runner,
                ["usbipd.exe", "attach", f"--wsl={self.distro}", "--busid", current.bus_id],
                15, code="P0_ADAPTER_ATTACH_FAILED", gate="P0b_usbip",
            )
            deadline = time.monotonic() + self.deadline
            stable = 0
            while time.monotonic() < deadline:
                now = self._current()
                if now.bus_id != self.adapter.bus_id:
                    raise P0Error(
                        "P0_ADAPTER_IDENTITY_CHANGED", "P0b_enumeration",
                        "adapter bus identity changed during P0b",
                    )
                linux = self.probe(self.adapter.usb_id)
                matches = now.attached and linux.get("status") == "present" and linux.get("matches") == 1
                stable = stable + 1 if matches else 0
                if stable >= 2:
                    break
                time.sleep(0.1)
            if stable < 2:
                code = "P0_LINUX_ENUMERATION_UNKNOWN" if linux.get("status") == "unknown" else "P0_LINUX_ENUMERATION_TIMEOUT"
                raise P0Error(code, "P0b_enumeration", "Linux did not stably enumerate the selected adapter")
        self.active = True
        return self.evidence()

    def evidence(self) -> dict:
        return {
            "adapter_instance_sha256": self.adapter.instance_sha256,
            "usb_id": self.adapter.usb_id,
            "bus_id": self.adapter.bus_id,
            "prior_attached": self.adapter.attached,
            "acquired_by_run": self.acquired_by_run,
            "active": self.active,
        }

    def release(self) -> dict:
        if not self.recovery_file.exists() and not self.active:
            return {
                "prior_state_restored": True,
                "windows_state_verified": True,
                "linux_state_verified": True,
                "detached_by_run": False,
            }
        current = self._current()
        if self.acquired_by_run:
            if current.bus_id != self.adapter.bus_id:
                if current.attached:
                    raise P0Error(
                        "P0_ADAPTER_IDENTITY_CHANGED", "D10_usb_return",
                        "attached adapter bus identity changed before USB return",
                    )
                # Windows can renumber USB buses across a reboot. The stable InstanceId and USB ID
                # still identify the exact detached device; subsequent reads bind to its new bus.
                self.adapter = current
            if current.attached:
                before_detach = self.probe(self.adapter.usb_id)
                if (before_detach.get("status") != "present" or
                        before_detach.get("matches") != 1 or
                        before_detach.get("interfaces_up") != 0):
                    code = (
                        "P0_CLEANUP_UNKNOWN" if before_detach.get("status") == "unknown"
                        else "P0_RADIO_NOT_QUIESCENT"
                    )
                    raise P0Error(
                        code, "D9_radio_quiescence",
                        "radio quiescence was not proven before USB detach",
                    )
                _run(
                    self.runner, ["usbipd.exe", "detach", "--busid", current.bus_id], 15,
                    code="P0_ADAPTER_DETACH_FAILED", gate="D10_usb_return",
                )
            deadline = time.monotonic() + self.deadline
            stable = 0
            windows_seen = False
            while time.monotonic() < deadline:
                now = self._current_after_detach()
                linux = self.probe(self.adapter.usb_id)
                windows_seen = windows_seen or now is not None
                matches = (
                    now is not None and not now.attached and linux.get("status") == "absent" and
                    linux.get("matches") == 0 and linux.get("interface_present") is False and
                    linux.get("phy_present") is False and linux.get("interfaces_up") == 0
                )
                stable = stable + 1 if matches else 0
                if stable >= 3:
                    break
                time.sleep(0.1)
            if stable < 3:
                code = (
                    "P0_CLEANUP_UNKNOWN"
                    if not windows_seen or linux.get("status") == "unknown"
                    else "P0_CLEANUP_FAILED"
                )
                raise P0Error(code, "D10_usb_return", "adapter release could not be verified")
        else:
            linux = self.probe(self.adapter.usb_id)
            if (not current.attached or linux.get("status") != "present" or
                    linux.get("matches") != 1 or linux.get("interfaces_up") != 0):
                raise P0Error(
                    "P0_PRIOR_OWNERSHIP_NOT_RESTORED", "D10_usb_return",
                    "the pre-existing adapter attachment changed",
                )
        self.active = False
        self.recovery_file.unlink(missing_ok=True)
        return {
            "prior_state_restored": True,
            "windows_state_verified": True,
            "linux_state_verified": True,
            "detached_by_run": self.acquired_by_run,
        }


__all__ = [
    "PASSIVE_CONTRACT", "P0Error", "PassiveValidator", "USB_ID", "UsbAdapter", "UsbLease",
    "atomic_json", "linux_usb_probe", "parse_usbipd_state", "run_command", "selected_adapter",
]
