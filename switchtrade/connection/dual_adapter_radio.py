"""Exact two-radio ownership for the Switchless C+D qualification suite.

The normal one-radio product path remains in :mod:`p0`.  This module composes two
of those leases, adds attach-delta identity and deterministic outer locks, and is
only imported by the explicit qualification harness.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Callable

from switchtrade.connection.dual_adapter_cd import validate_adapter_pair
from switchtrade.connection.p0 import (
    P0Error, USB_ID, UsbAdapter, UsbLease, parse_usbipd_state, run_command,
    wsl_root_command,
)
from switchtrade.process_guard import AlreadyRunningError, SingleInstanceLock


Inventory = Callable[[], tuple[str, ...]]
Probe = Callable[[str], dict]
LeaseFactory = Callable[[UsbAdapter, Path, Callable[[UsbAdapter], str]], UsbLease]


def _identity_key(adapter: UsbAdapter) -> str:
    return adapter.instance_sha256


def requested_adapter_pair(
    inventory: list[UsbAdapter], instance_ids: tuple[str, str] | None = None,
) -> tuple[UsbAdapter, UsbAdapter]:
    """Resolve exactly two stable Windows identities; never infer by bus order."""
    compatible = [item for item in inventory if item.usb_id == USB_ID]
    if instance_ids is None:
        if len(compatible) != 2:
            raise P0Error(
                "CD_ADAPTER_COUNT_INVALID", "Q3_PREFLIGHT",
                "exactly two compatible adapters must be present",
            )
        selected = tuple(sorted(compatible, key=_identity_key))
    else:
        selected_items = []
        for requested in instance_ids:
            matches = [
                item for item in compatible
                if item.instance_id.casefold() == requested.casefold()
            ]
            if len(matches) != 1:
                raise P0Error(
                    "CD_ADAPTER_IDENTITY_UNAVAILABLE", "Q3_PREFLIGHT",
                    "a requested adapter identity did not resolve exactly once",
                )
            selected_items.append(matches[0])
        selected = tuple(selected_items)
    validate_adapter_pair(selected[0], selected[1])
    return selected


class AttachDeltaResolver:
    """Bind an attach to its sole new sysfs identity, never enumeration order."""

    def __init__(self, before: tuple[str, ...], inventory: Inventory,
                 *, timeout: float = 12.0):
        self.before = frozenset(before)
        self.inventory = inventory
        self.timeout = timeout

    def __call__(self, _adapter: UsbAdapter) -> str:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            after = frozenset(self.inventory())
            disappeared = self.before - after
            added = after - self.before
            if disappeared:
                raise P0Error(
                    "CD_LINUX_IDENTITY_CHANGED", "P0b_enumeration",
                    "an existing Linux USB identity changed during attach",
                )
            if len(added) > 1:
                raise P0Error(
                    "CD_LINUX_ATTACH_AMBIGUOUS", "P0b_enumeration",
                    "more than one Linux USB identity appeared during attach",
                )
            if len(added) == 1:
                return next(iter(added))
            time.sleep(0.1)
        raise P0Error(
            "CD_LINUX_ATTACH_DELTA_MISSING", "P0b_enumeration",
            "no exact Linux USB identity appeared during attach",
        )


class WslExactUsb:
    """Read the source-qualified exact probe inside one explicit WSL runtime."""

    def __init__(self, *, distro: str, runtime_root: str, packaged_python: str,
                 source_root: str, runner=run_command):
        self.distro = distro
        self.runtime_root = runtime_root
        self.packaged_python = packaged_python
        self.source_root = source_root
        self.runner = runner

    def _call(self, function: str, argument: str) -> object:
        program = (
            "import json,sys; sys.path.insert(0,sys.argv[1]); "
            "from switchtrade.connection.p0 import linux_usb_descendants,linux_usb_inventory,linux_usb_probe; "
            f"print(json.dumps({function}(sys.argv[2]),sort_keys=True,separators=(',',':')))"
        )
        try:
            result = self.runner(wsl_root_command(
                self.distro, self.runtime_root, self.packaged_python, "-c", program,
                self.source_root, argument,
            ), 8)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise P0Error(
                "CD_LINUX_PROBE_UNAVAILABLE", "Q3_LINUX_IDENTITY",
                "the exact Linux USB probe is unavailable",
            ) from error
        if result.returncode != 0:
            raise P0Error(
                "CD_LINUX_PROBE_FAILED", "Q3_LINUX_IDENTITY",
                "the exact Linux USB probe failed",
            )
        try:
            return json.loads(result.stdout)
        except (TypeError, ValueError) as error:
            raise P0Error(
                "CD_LINUX_PROBE_INVALID", "Q3_LINUX_IDENTITY",
                "the exact Linux USB probe returned invalid evidence",
            ) from error

    def inventory(self) -> tuple[str, ...]:
        value = self._call("linux_usb_inventory", USB_ID)
        if (
            not isinstance(value, list) or
            any(not isinstance(item, str) or not item.startswith("/sys/") for item in value) or
            len(value) != len(set(value))
        ):
            raise P0Error(
                "CD_LINUX_INVENTORY_INVALID", "Q3_LINUX_IDENTITY",
                "the Linux USB inventory is invalid",
            )
        return tuple(sorted(value))

    def probe(self, identity: str) -> dict:
        value = self._call("linux_usb_probe", identity)
        if (
            not isinstance(value, dict) or
            value.get("status") not in {"present", "absent", "unknown"} or
            not all(name in value for name in (
                "matches", "interface_present", "phy_present", "interfaces_up"))
        ):
            raise P0Error(
                "CD_LINUX_PROBE_INVALID", "Q3_LINUX_IDENTITY",
                "the exact Linux USB probe contract is invalid",
            )
        return value

    def descendants(self, identity: str) -> dict:
        value = self._call("linux_usb_descendants", identity)
        if (
            not isinstance(value, dict) or value.get("status") not in {"present", "absent"} or
            not isinstance(value.get("netdevs"), list) or
            not isinstance(value.get("phys"), list) or
            any(not isinstance(item, str) for item in value["netdevs"] + value["phys"])
        ):
            raise P0Error(
                "CD_LINUX_DESCENDANTS_INVALID", "Q3_P0_IDENTITY",
                "the exact Linux radio descendants are invalid",
            )
        return value


class DualRadioOwner:
    """Acquire A then B, retain both, and release B then A with exact evidence."""

    def __init__(self, adapters: tuple[UsbAdapter, UsbAdapter], root: Path,
                 *, inventory: Inventory, probe: Probe,
                 lease_factory: LeaseFactory | None = None,
                 lock_root: Path | None = None):
        validate_adapter_pair(*adapters)
        self.adapters = adapters
        self.root = Path(root)
        self.inventory = inventory
        self.probe = probe
        self.lock_root = Path(lock_root or self.root / "locks")
        self.lease_factory = lease_factory or self._lease
        self.locks: list[SingleInstanceLock] = []
        self.leases: list[UsbLease] = []
        self.identities: list[str] = []
        self.before_snapshots: list[tuple[str, ...]] = []

    def _lease(self, adapter: UsbAdapter, recovery: Path,
               resolver: Callable[[UsbAdapter], str]) -> UsbLease:
        return UsbLease(
            adapter, recovery, probe=self.probe, identity_resolver=resolver,
        )

    def _acquire_locks(self) -> None:
        names = ["dual-radio-suite", *(
            f"radio-{item.instance_sha256}" for item in sorted(
                self.adapters, key=_identity_key)
        )]
        try:
            for name in names:
                self.locks.append(SingleInstanceLock(name, self.lock_root).acquire())
        except AlreadyRunningError as error:
            self._close_locks()
            raise P0Error(
                "CD_RADIO_BUSY", "Q3_LOCKS",
                "another room, diagnostic, or dual-radio run owns a selected adapter",
            ) from error

    def _close_locks(self) -> None:
        for lock in reversed(self.locks):
            lock.close()
        self.locks.clear()

    def acquire(self) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        self._acquire_locks()
        try:
            for index, adapter in enumerate(self.adapters):
                before = self.inventory()
                self.before_snapshots.append(before)
                resolver = AttachDeltaResolver(before, self.inventory)
                lease = self.lease_factory(
                    adapter, self.root / f"side-{index + 1}-usb-recovery.json", resolver,
                )
                self.leases.append(lease)
                evidence = lease.acquire()
                identity = lease.linux_identity
                if identity is None or self.probe(identity).get("matches") != 1:
                    raise P0Error(
                        "CD_LINUX_IDENTITY_UNPROVEN", "Q3_LINUX_IDENTITY",
                        "the exact attached Linux device is not present",
                    )
                for previous in self.identities:
                    if self.probe(previous).get("matches") != 1:
                        raise P0Error(
                            "CD_LINUX_IDENTITY_CHANGED", "Q3_LINUX_IDENTITY",
                            "an earlier radio identity changed while acquiring the second",
                        )
                self.identities.append(identity)
                if len(set(self.identities)) != len(self.identities):
                    raise P0Error(
                        "CD_LINUX_IDENTITY_DUPLICATE", "Q3_LINUX_IDENTITY",
                        "both leases resolved to the same Linux USB identity",
                    )
                evidence["side"] = "room_side" if index == 0 else "ap_side"
            return self.evidence()
        except BaseException:
            try:
                self.release()
            except BaseException:
                pass
            raise

    def evidence(self) -> dict:
        return {
            "acquisition_order": [item.instance_sha256 for item in self.adapters],
            "linux_identity_sha256": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in self.identities
            ],
            "distinct_windows_identities": (
                self.adapters[0].instance_sha256 != self.adapters[1].instance_sha256
            ),
            "distinct_linux_identities": len(set(self.identities)) == 2,
            "leases_active": len(self.leases) == 2 and all(item.active for item in self.leases),
        }

    def release(self) -> dict:
        released: list[dict] = []
        failures: list[dict] = []
        try:
            for index in range(len(self.leases) - 1, -1, -1):
                lease = self.leases[index]
                try:
                    if lease.exact_identity_required and lease.linux_identity is None:
                        lease.identity_resolver = AttachDeltaResolver(
                            self.before_snapshots[index], self.inventory,
                        )
                    released.append(lease.release())
                except BaseException as error:
                    failures.append({
                        "code": str(getattr(error, "code", "CD_RADIO_RELEASE_FAILED")),
                        "gate": str(getattr(error, "gate", "D10_USB_RETURN")),
                    })
                    break
        finally:
            self._close_locks()
        verified = (
            not failures and len(released) == len(self.leases) and
            all(item.get("prior_state_restored") is True for item in released)
        )
        return {
            "verified": verified,
            "release_order": list(reversed([
                item.instance_sha256 for item in self.adapters[:len(self.leases)]
            ])),
            "sides": released,
            "failures": failures,
        }

    def retry_recovery(self, *, inventory: Inventory | None = None) -> dict:
        """Retry exact cleanup after an unknown probe without broad detachment."""
        if inventory is not None:
            self.inventory = inventory
        return self.release()


def usbipd_inventory(runner=run_command) -> list[UsbAdapter]:
    try:
        result = runner(["usbipd.exe", "state"], 5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise P0Error(
            "P0_USBIPD_STATE_UNAVAILABLE", "Q3_PREFLIGHT",
            "usbipd inventory is unavailable",
        ) from error
    if result.returncode != 0:
        raise P0Error(
            "P0_USBIPD_STATE_UNAVAILABLE", "Q3_PREFLIGHT",
            "usbipd inventory failed",
        )
    return parse_usbipd_state(result.stdout)


__all__ = [
    "AttachDeltaResolver", "DualRadioOwner", "WslExactUsb",
    "requested_adapter_pair", "usbipd_inventory",
]
