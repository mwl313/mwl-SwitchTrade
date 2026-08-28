"""Staged, redacted WSL USB radio diagnostics for existing and candidate cards."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

from switchtrade.diagnostics import RunLogger, redact_text
from switchtrade.hardware import (
    BLOCKED_STATUSES, DEFAULT_PROFILE_PATH, EXPERIMENTAL_STATUSES, USB_ID,
    load_profiles,
)
from switchtrade.endpoint import runtime_phy


DIAGNOSTIC_CONTRACT = "hardware-diagnostic.v1"
ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts" / "wsl-radio-prepare.sh"
KNOWN_FAILURES = (
    ("FIRMWARE_LOAD_FAILED", re.compile(r"firmware.*(?:failed|not found|error)", re.I),
     "Install the exact firmware named in the log and rerun diagnostics."),
    ("MODULE_KERNEL_MISMATCH", re.compile(r"invalid module format|version magic|vermagic", re.I),
     "Rebuild the driver module for the running WSL kernel."),
    ("MODULE_SYMBOL_MISSING", re.compile(r"unknown symbol|unresolved symbol", re.I),
     "Enable the missing kernel prerequisite or use an in-tree driver."),
    ("DRIVER_PROBE_FAILED", re.compile(r"probe with driver .* failed|probe failed", re.I),
     "Inspect the driver/firmware pairing for this exact USB ID."),
    ("INTERFACE_OPEN_FAILED", re.compile(r"failed (?:its first )?interface open|ndo_open", re.I),
     "The driver cannot open the radio on this kernel; inspect dmesg and driver compatibility."),
    ("AP_MONITOR_CONCURRENCY_FAILED", re.compile(r"ap\+monitor.*(?:fail|deadlock)|resource busy", re.I),
     "Use a driver that supports concurrent AP and monitor interfaces on one phy."),
    ("RADIO_BLOCKED", re.compile(r"soft blocked:\s*yes|hard blocked:\s*yes", re.I),
     "Unblock Wi-Fi with rfkill and verify no Windows/VM owner reclaimed the adapter."),
    ("ACTUAL_RX_FAILED", re.compile(r"actual.rx.*(?:fail|timeout)|no packets", re.I),
     "Verify USB attachment, antenna/regulatory settings, and monitor-mode receive support."),
    ("LDN_ROOM_FAILED", re.compile(r"ldn create_network (?:failed|timed out)|tap netdev .* not found", re.I),
     "Review AP+monitor concurrency, LDN keys, TAP creation, and the captured engine log."),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage(name: str, status: str, code: str, message: str, **details) -> dict:
    return {
        "name": name, "status": status, "code": code, "message": message,
        "details": details, "checked_utc": _now(),
    }


def classify_output(text: str) -> list[dict]:
    """Return stable incompatibility codes for known kernel/driver failure text."""
    found = []
    for code, pattern, action in KNOWN_FAILURES:
        if pattern.search(text):
            found.append({"code": code, "action": action})
    return found


def parse_iw_capabilities(text: str) -> dict:
    modes = set(re.findall(r"^\s*\*\s+(AP|monitor|managed)\s*$", text, re.M | re.I))
    lower_modes = {mode.lower() for mode in modes}
    combinations = re.findall(
        r"valid interface combinations:(.*?)(?:\n\S|\Z)", text, re.I | re.S)
    concurrent = any(
        re.search(r"#\{\s*AP\s*\}", block, re.I) and
        re.search(r"#\{\s*monitor\s*\}", block, re.I)
        for block in combinations
    )
    return {
        "ap": "ap" in lower_modes,
        "monitor": "monitor" in lower_modes,
        "managed": "managed" in lower_modes,
        "ap_monitor_concurrent": concurrent,
    }


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _capture(logger: RunLogger, name: str, command: list[str],
             runner: Callable = _default_runner, timeout: float = 10) -> tuple[int, str]:
    try:
        result = runner(command, timeout)
        returncode = int(result.returncode)
        output = f"$ {' '.join(command)}\n{result.stdout or ''}{result.stderr or ''}"
    except FileNotFoundError as error:
        returncode, output = 127, f"$ {' '.join(command)}\n{error}\n"
    except subprocess.TimeoutExpired as error:
        returncode = 124
        output = f"$ {' '.join(command)}\nTIMEOUT after {timeout}s\n{error.stdout or ''}{error.stderr or ''}"
    output = redact_text(output)[:256_000]
    (logger.run_dir / f"diagnostic-{name}.txt").write_text(output, encoding="utf-8")
    logger.event("diagnostic_command", stage=name, exit_code=returncode, command=command[0])
    return returncode, output


def diagnose_hardware(usb_id: str, *, mode: str = "quick", role: str = "host",
                      allow_experimental: bool = False,
                      active_check: bool = False,
                      profile_path: str | Path = DEFAULT_PROFILE_PATH,
                      runs_root: str | Path | None = None,
                      runner: Callable = _default_runner) -> tuple[dict, RunLogger]:
    usb_id = usb_id.lower()
    if not USB_ID.fullmatch(usb_id):
        raise ValueError("usb_id must be VID:PID")
    if mode not in {"quick", "certify", "full"}:
        raise ValueError("mode must be quick, certify, or full")
    if role not in {"host", "guest", "relay"}:
        raise ValueError("role must be host, guest, or relay")

    profiles = {profile.usb_id: profile for profile in load_profiles(profile_path)}
    profile = profiles.get(usb_id)
    logger = RunLogger("hardware-diagnostic", runs_root, {
        "usb_id": usb_id, "mode": mode, "role": role,
        "known_profile": profile is not None, "active_check": active_check,
    })
    stages: list[dict] = []
    incompatibilities: list[dict] = []

    if profile is None:
        stages.append(_stage(
            "profile_policy", "warning", "HARDWARE_PROFILE_UNKNOWN",
            "The card is not in the compatibility matrix; read-only diagnostics will continue.",
        ))
    elif profile.status in BLOCKED_STATUSES:
        stages.append(_stage(
            "profile_policy", "failed", "HARDWARE_QUARANTINED",
            "The card is quarantined for trading attempts.", profile_status=profile.status,
        ))
        incompatibilities.append({
            "code": "HARDWARE_QUARANTINED",
            "action": "Keep this card diagnostic-only unless new physical evidence changes its status.",
        })
    else:
        stages.append(_stage(
            "profile_policy", "passed", "HARDWARE_POLICY_ACCEPTED",
            "The profile is eligible for this diagnostic mode.", profile_status=profile.status,
            host_engine=profile.host_engine,
        ))
    can_mutate = profile is not None and profile.status not in BLOCKED_STATUSES

    uname_rc, uname = _capture(logger, "platform", ["uname", "-r"], runner)
    is_wsl = uname_rc == 0 and "microsoft" in uname.lower()
    stages.append(_stage(
        "platform", "passed" if is_wsl else "failed",
        "PLATFORM_WSL_READY" if is_wsl else "PLATFORM_NOT_WSL",
        "Running inside a WSL kernel." if is_wsl else "The radio runtime requires WSL2.",
        kernel=uname.splitlines()[-1] if uname.splitlines() else "unknown",
    ))

    usb_rc, usb = _capture(logger, "usb", ["lsusb", "-d", usb_id], runner)
    usb_present = usb_rc == 0 and any(
        line.startswith("Bus ") and usb_id in line.lower() for line in usb.splitlines()
    )
    stages.append(_stage(
        "usb_attachment", "passed" if usb_present else "failed",
        "USB_ATTACHED" if usb_present else "USB_NOT_FOUND",
        "The adapter is visible inside WSL." if usb_present else
        "The requested adapter is not visible inside WSL.",
    ))
    if not usb_present:
        incompatibilities.append({
            "code": "USB_NOT_FOUND",
            "action": "Authorize and attach the selected Windows USB adapter before checking its Linux driver.",
        })

    active_rx: tuple[int, str] | None = None
    if active_check and usb_present and can_mutate:
        command = [str(PREPARE), "--usb-id", usb_id, "--role", role,
                   "--reset-on-rx-failure"]
        if allow_experimental:
            command.append("--allow-experimental-hardware")
        command += ["--", "true"]
        active_rx = _capture(logger, "actual-rx", command, runner, timeout=50)

    binding_command = [
        "bash", "-c",
        "wanted=$1; for vendor in /sys/bus/usb/devices/*/idVendor; do "
        "[ -r \"$vendor\" ] || continue; dev=${vendor%/idVendor}; "
        "id=$(cat \"$vendor\"):$(cat \"$dev/idProduct\" 2>/dev/null); "
        "[ \"${id,,}\" = \"$wanted\" ] || continue; "
        "for link in \"$dev\"/*:*/driver; do if [ -L \"$link\" ]; then "
        "echo USB_PATH=$(basename \"$dev\"); "
        "basename \"$(readlink -f \"$link\")\"; exit 0; fi; done; done; exit 3",
        "switchtrade-driver", usb_id,
    ]
    binding_rc, binding = _capture(logger, "driver-binding", binding_command, runner)
    bound_driver = next((
        line.strip() for line in reversed(binding.splitlines())
        if re.fullmatch(r"[A-Za-z0-9_-]+", line.strip())
    ), None)
    usb_path_match = re.search(r"^USB_PATH=([0-9]+-[0-9]+(?:\.[0-9]+)*)$", binding, re.M)
    usb_path = usb_path_match.group(1) if usb_path_match else None
    allowed = set(profile.allowed_drivers) if profile else set()
    binding_ok = binding_rc == 0 and bound_driver is not None and (
        not allowed or bound_driver in allowed)
    binding_code = (
        "DRIVER_BOUND" if binding_ok else
        "DRIVER_UNEXPECTED" if bound_driver else "DRIVER_UNBOUND"
    )
    stages.append(_stage(
        "driver_binding", "passed" if binding_ok else "failed", binding_code,
        f"The adapter is bound to {bound_driver}." if binding_ok else
        "The adapter is not bound to an allowed matrix driver.",
        driver=bound_driver, usb_path=usb_path, allowed_drivers=sorted(allowed),
    ))
    if not binding_ok:
        incompatibilities.append({
            "code": binding_code,
            "action": "Attach the USB device to WSL and load an allowed driver for this exact profile.",
        })

    iw_rc, iw = _capture(logger, "iw-capabilities", ["iw", "list"], runner)
    capabilities = parse_iw_capabilities(iw) if iw_rc == 0 else {
        "ap": False, "monitor": False, "managed": False, "ap_monitor_concurrent": False,
    }
    capability_failures = ["IW_CAPABILITY_QUERY_FAILED"] if iw_rc else []
    if not iw_rc:
        if not capabilities["ap"]:
            capability_failures.append("AP_UNSUPPORTED")
        if not capabilities["monitor"]:
            capability_failures.append("MONITOR_UNSUPPORTED")
        if capabilities["ap"] and capabilities["monitor"] and not capabilities["ap_monitor_concurrent"]:
            capability_failures.append("AP_MONITOR_CONCURRENCY_UNCONFIRMED")
    cap_status = "failed" if iw_rc or any(
        code.endswith("UNSUPPORTED") for code in capability_failures) else (
        "warning" if capability_failures else "passed")
    stages.append(_stage(
        "radio_capabilities", cap_status,
        capability_failures[0] if capability_failures else "RADIO_CAPABILITIES_READY",
        "Driver capability inspection completed.", **capabilities,
        additional_codes=capability_failures[1:],
    ))
    for code in capability_failures:
        incompatibilities.append({
            "code": code,
            "action": "Install iw and use a driver/firmware combination exposing AP and monitor concurrency.",
        })

    rfkill_rc, rfkill = _capture(logger, "rfkill", ["rfkill", "list", "wifi"], runner)
    blocked = bool(re.search(r"(?:soft|hard) blocked:\s*yes", rfkill, re.I))
    stages.append(_stage(
        "rfkill", "failed" if blocked else "warning" if rfkill_rc else "passed",
        "RADIO_BLOCKED" if blocked else "RFKILL_CLEAR" if not rfkill_rc else "RFKILL_UNAVAILABLE",
        "Wi-Fi is blocked." if blocked else "No Wi-Fi block was reported.",
    ))

    driver_name = bound_driver if binding_ok and bound_driver else (
        profile.allowed_drivers[0] if profile and profile.allowed_drivers else ""
    )
    if driver_name:
        module_rc, module = _capture(
            logger, "driver-module", [
                "bash", "-c",
                "modinfo \"$1\" 2>/dev/null || { [ -d \"/sys/module/$1\" ] && "
                "echo loaded-from-sysfs; }",
                "switchtrade-module", driver_name,
            ], runner)
        module_source = "loaded_sysfs" if "loaded-from-sysfs" in module else "module_tree"
        stages.append(_stage(
            "driver_module", "passed" if module_rc == 0 else "failed",
            "DRIVER_MODULE_AVAILABLE" if module_rc == 0 else "DRIVER_MODULE_MISSING",
            f"Kernel module {driver_name} is available." if module_rc == 0 else
            f"Kernel module {driver_name} is unavailable.", driver=driver_name,
            source=module_source if module_rc == 0 else None,
        ))
    else:
        module = ""
        stages.append(_stage(
            "driver_module", "warning", "DRIVER_UNKNOWN",
            "No matrix driver is available for this unprofiled card.",
        ))

    dmesg_rc, dmesg = _capture(
        logger, "kernel-log", ["dmesg", "--level=err,warn"], runner)
    driver_terms = (bound_driver,) if binding_ok and bound_driver else (
        tuple(profile.allowed_drivers) if profile else ()
    )
    dmesg_scope = "\n".join(
        line for line in dmesg.splitlines()
        if (not driver_terms or any(term.lower() in line.lower() for term in driver_terms))
        and (not usb_path or re.search(rf"(?<![0-9.-]){re.escape(usb_path)}(?=[:.\s-])", line))
    )
    known = classify_output(dmesg_scope)
    for item in known:
        if item not in incompatibilities:
            incompatibilities.append(item)
    stages.append(_stage(
        "kernel_firmware_log", "failed" if known else "warning" if dmesg_rc else "passed",
        known[0]["code"] if known else "KERNEL_LOG_UNAVAILABLE" if dmesg_rc else "KERNEL_LOG_CLEAR",
        "Known incompatibility signatures were found." if known else
        "No known driver/firmware failure signature was found.",
        additional_codes=[item["code"] for item in known[1:]],
    ))

    if active_rx is not None:
        rx_rc, rx = active_rx
        stages.append(_stage(
            "actual_rx", "passed" if rx_rc == 0 else "failed",
            "ACTUAL_RX_PASSED" if rx_rc == 0 else "ACTUAL_RX_FAILED",
            "The production multi-channel actual-RX gate passed." if rx_rc == 0 else
            "The actual-RX gate failed; inspect diagnostic-actual-rx.txt.",
        ))
        for item in classify_output(rx):
            if item not in incompatibilities:
                incompatibilities.append(item)
    elif mode in {"certify", "full"} and can_mutate:
        command = [str(PREPARE), "--usb-id", usb_id, "--role", role]
        command += ["--", "true"]
        rx_rc, rx = _capture(logger, "actual-rx", command, runner, timeout=50)
        stages.append(_stage(
            "actual_rx", "passed" if rx_rc == 0 else "failed",
            "ACTUAL_RX_PASSED" if rx_rc == 0 else "ACTUAL_RX_FAILED",
            "The existing multi-channel actual-RX gate passed." if rx_rc == 0 else
            "The actual-RX gate failed; inspect diagnostic-actual-rx.txt.",
        ))
        for item in classify_output(rx):
            if item not in incompatibilities:
                incompatibilities.append(item)
    else:
        stages.append(_stage(
            "actual_rx", "not_tested", "ACTUAL_RX_NOT_TESTED",
            "Run certify/full mode to exercise RX.",
        ))

    if mode == "full" and can_mutate:
        smoke = [
            str(PREPARE), "--usb-id", usb_id, "--role", role, "--",
            sys.executable, "-m", "switchtrade.hardware_diagnostics",
            "--ldn-smoke-worker", "--usb-id", usb_id,
        ]
        ldn_rc, ldn = _capture(logger, "ldn-room", smoke, runner, timeout=75)
        stages.append(_stage(
            "ldn_room_lifecycle", "passed" if ldn_rc == 0 else "failed",
            "LDN_ROOM_LIFECYCLE_PASSED" if ldn_rc == 0 else "LDN_ROOM_FAILED",
            "HostTransport + ldn.create_network() opened and tore down locally." if ldn_rc == 0 else
            "The LDN room lifecycle failed; inspect diagnostic-ldn-room.txt.",
        ))
        for item in classify_output(ldn):
            if item not in incompatibilities:
                incompatibilities.append(item)
    else:
        stages.append(_stage(
            "ldn_room_lifecycle", "not_tested", "LDN_ROOM_NOT_TESTED",
            "Full mode is required to open and tear down a local LDN room.",
        ))

    stages.extend([
        _stage("over_air_beacon", "not_tested", "BEACON_NOT_OBSERVED_EXTERNALLY",
               "A second radio or physical Switch is required to prove over-air beacon visibility."),
        _stage("switch_association", "not_tested", "SWITCH_ASSOCIATION_NOT_TESTED",
               "A physical Switch is required to prove authentication and association."),
        _stage("nintendo_control_port", "not_tested", "CONTROL_PORT_NOT_TESTED",
               "A physical Switch exchange is required to validate Nintendo control-port behavior."),
        _stage("encrypted_data_plane", "not_tested", "CCMP_TAP_NOT_TESTED",
               "A physical peer is required to validate encrypted data and TAP forwarding."),
    ])

    failed = [stage for stage in stages if stage["status"] == "failed"]
    incomplete = [stage for stage in stages if stage["status"] in {"warning", "not_tested"}]
    overall = "failed" if failed else "partial" if incomplete else "passed"
    report = {
        "contract_version": DIAGNOSTIC_CONTRACT,
        "run_id": logger.run_id,
        "usb_id": usb_id,
        "mode": mode,
        "role": role,
        "active_check": active_check,
        "overall_status": overall,
        "profile": profile.public() if profile else None,
        "stages": stages,
        "incompatibilities": incompatibilities,
        "limitations": [
            "Software-only diagnostics cannot certify over-air beaconing, physical Switch association, "
            "Nintendo control-port behavior, or an end-to-end trade.",
        ],
    }
    (logger.run_dir / "diagnostic-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.event(
        "diagnostic_finished", outcome=overall, failures=len(failed),
        incompatibilities=[item["code"] for item in incompatibilities],
    )
    logger.close(overall)
    return report, logger


def _ldn_smoke_worker(usb_id: str) -> int:
    """Open the production host engine locally; external visibility remains unproven."""
    bridge = ROOT / "bridge"
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    from frlgsim.transport import HostTransport

    transport = HostTransport(host_engine="ldn", nickname="DIAG", phyname=runtime_phy())
    try:
        transport.start(timeout=45)
        print(f"LDN room ready for {usb_id}; tap={transport.iface}")
        return 0
    finally:
        transport.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-id", required=True)
    parser.add_argument("--mode", choices=("quick", "certify", "full"), default="quick")
    parser.add_argument("--role", choices=("host", "guest", "relay"), default="host")
    parser.add_argument("--allow-experimental-hardware", action="store_true")
    parser.add_argument("--active-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile-file", default=str(DEFAULT_PROFILE_PATH))
    parser.add_argument("--runs-root")
    parser.add_argument("--ldn-smoke-worker", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.ldn_smoke_worker:
        raise SystemExit(_ldn_smoke_worker(args.usb_id.lower()))
    report, _ = diagnose_hardware(
        args.usb_id, mode=args.mode, role=args.role,
        allow_experimental=args.allow_experimental_hardware,
        active_check=args.active_check,
        profile_path=args.profile_file, runs_root=args.runs_root,
    )
    print(json.dumps(report, separators=(",", ":")))
    raise SystemExit(1 if report["overall_status"] == "failed" else 0)


if __name__ == "__main__":
    main()
