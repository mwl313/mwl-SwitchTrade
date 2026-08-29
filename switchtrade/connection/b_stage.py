"""Direct ABC+D B2-B10 admission against one real searching Switch."""

from __future__ import annotations

import contextlib
import hashlib
from importlib import metadata
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import time
from typing import Callable

from .a_stage import (
    ACCEPT_ALL,
    AStageError,
    APP_VERSION,
    COMMUNICATION_ID,
    GBA_APP_PASSPHRASE,
    MAX_PARTICIPANTS,
    PROTOCOL,
    SCENE_ID,
    validate_advertisement,
)
from .b_fixture import FIXTURE, FIXTURE_ID, FIXTURE_NAME, FIXTURE_SHA256


PIA_PORT = 12345
_LINUX_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")

GATES = (
    "B2_ADVERTISEMENT_VALIDATION",
    "B3_RADIO_RESET",
    "B4_NETWORK_CONSTRUCTION",
    "B5_AP_MONITOR_TAP_CREATION",
    "B6_DATA_PLANE",
    "B7_OVER_AIR_ROOM_ADVERTISEMENT",
    "B8_SWITCH_ASSOCIATION",
    "B9_NINTENDO_CONTROL_PORT",
    "B10_HOLD",
)

GateSink = Callable[[dict], None]
Runner = Callable[[list[str], float], subprocess.CompletedProcess]


class BStageError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _phy_interfaces(iw_output: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    current = None
    for raw in iw_output.splitlines():
        line = raw.strip()
        if line.startswith("phy#") and line[4:].isdigit():
            current = f"phy{line[4:]}"
            mapping[current] = []
        elif line.startswith("Interface ") and current is not None:
            name = line.split()[1]
            if not _LINUX_NAME.fullmatch(name):
                raise ValueError("radio interface name is invalid")
            mapping[current].append(name)
    return mapping


def _wait_absent(path: Path, timeout: float = 1) -> bool:
    deadline = time.monotonic() + timeout
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    return not path.exists()


def reset_selected_phy(
    phy: str,
    *,
    runner: Runner = _default_runner,
    sys_net: Path = Path("/sys/class/net"),
) -> dict:
    """Delete only vifs on the run-owned PHY plus the exact reserved TAP."""
    try:
        result = runner(["iw", "dev"], 3)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "radio interface inventory failed") from error
    if result.returncode != 0:
        raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "radio interface inventory failed")
    try:
        mapping = _phy_interfaces(result.stdout or "")
    except ValueError as error:
        raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "radio interface inventory is invalid") from error
    if phy not in mapping:
        raise BStageError("B_RADIO_IDENTITY_MISSING", GATES[1], "selected PHY is unavailable")
    removed = 0
    for interface in mapping[phy]:
        try:
            deleted = runner(["iw", "dev", interface, "del"], 3)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "selected PHY reset failed") from error
        if deleted.returncode != 0 or not _wait_absent(sys_net / interface):
            raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "selected PHY reset was not verified")
        removed += 1
    tap_removed = False
    tap = sys_net / "ldn-tap"
    if tap.exists():
        try:
            deleted = runner(["ip", "link", "del", "dev", "ldn-tap"], 3)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "stale TAP reset failed") from error
        if deleted.returncode != 0 or not _wait_absent(tap):
            raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "stale TAP reset was not verified")
        tap_removed = True
    return {
        "selected_phy_only": True,
        "interfaces_removed": removed,
        "tap_removed": tap_removed,
    }


def quiesce_selected_phy(
    phy: str,
    tap_ifname: str,
    *,
    runner: Runner = _default_runner,
    sys_net: Path = Path("/sys/class/net"),
    sys_phy: Path = Path("/sys/class/ieee80211"),
) -> dict:
    """Quiesce every remaining vif on the run-owned PHY and remove its exact TAP."""
    if not re.fullmatch(r"phy[0-9]+", phy) or not _LINUX_NAME.fullmatch(tap_ifname):
        raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio cleanup identity is invalid")
    if not (sys_phy / phy).exists():
        raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "selected PHY disappeared before cleanup")
    try:
        inventory = runner(["iw", "dev"], 3)
        mapping = _phy_interfaces(inventory.stdout or "") if inventory.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio cleanup inventory failed") from error
    if mapping is None:
        raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio cleanup inventory failed")
    interfaces = mapping.get(phy, [])
    for interface in interfaces:
        try:
            stopped = runner(["ip", "link", "set", "dev", interface, "down"], 3)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio interface did not stop") from error
        if stopped.returncode != 0:
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio interface did not stop")
        try:
            flags = int((sys_net / interface / "flags").read_text(encoding="ascii").strip(), 16)
        except (OSError, ValueError) as error:
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio interface state is unknown") from error
        if flags & 1:
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "radio interface remained active")
    tap = sys_net / tap_ifname
    if tap.exists():
        try:
            deleted = runner(["ip", "link", "del", "dev", tap_ifname], 3)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "LDN TAP cleanup failed") from error
        if deleted.returncode != 0 or not _wait_absent(tap):
            raise BStageError("B_RADIO_QUIESCE_FAILED", GATES[-1], "LDN TAP cleanup was not verified")
    return {
        "selected_phy_only": True,
        "interfaces_quiescent": len(interfaces),
        "tap_absent": True,
    }


def _build_beacon_head(ssid: bytes, channel: int, bssid: bytes) -> bytes:
    """Build the measured rtl8xxxu-compatible hidden WPA2 LDN beacon head."""
    ssid = bytes(ssid)
    bssid = bytes(bssid)
    if len(ssid) > 32 or not 1 <= channel <= 14 or len(bssid) != 6:
        raise ValueError("beacon identity is invalid")
    rsn_body = (
        struct.pack("<H", 1)
        + bytes.fromhex("000fac04")
        + struct.pack("<H", 1)
        + bytes.fromhex("000fac04")
        + struct.pack("<H", 1)
        + bytes.fromhex("000fac02")
        + struct.pack("<H", 0x000C)
    )
    return (
        bytes.fromhex("80000000") + b"\xff" * 6 + bssid + bssid + b"\x00\x00"
        + b"\x00" * 8 + struct.pack("<HH", 100, 0x0511)
        + bytes([0, len(ssid)]) + bytes(len(ssid))
        + bytes.fromhex("010882848b960c121824")
        + bytes([3, 1, channel, 48, len(rsn_body)]) + rsn_body
    )


def _validate_peer(network: object) -> dict:
    info = network.info()
    participants = list(getattr(info, "participants", ()) or ())
    connected = [participant for participant in participants if getattr(participant, "connected", False)]
    if getattr(info, "num_participants", None) != 2 or len(connected) != 2:
        raise BStageError("B_PARTICIPANT_STATE_FAILED", GATES[6], "LDN participant count is invalid")
    local = network.participant()
    peer = next((participant for participant in connected if participant is not local), None)
    if peer is None or getattr(peer, "app_version", None) != APP_VERSION:
        raise BStageError("B_PARTICIPANT_STATE_FAILED", GATES[6], "joining participant is incompatible")
    try:
        local_mac = bytes(local.mac_address)
        peer_mac = bytes(peer.mac_address)
    except (AttributeError, TypeError, ValueError) as error:
        raise BStageError("B_PARTICIPANT_STATE_FAILED", GATES[6], "participant identity is invalid") from error
    local_ip = getattr(local, "ip_address", "")
    peer_ip = getattr(peer, "ip_address", "")
    if (
        len(local_mac) != 6 or len(peer_mac) != 6 or local_mac == peer_mac
        or not isinstance(local_ip, str) or not local_ip.startswith("169.254.")
        or not isinstance(peer_ip, str) or not peer_ip.startswith("169.254.")
        or local_ip == peer_ip
    ):
        raise BStageError("B_PARTICIPANT_STATE_FAILED", GATES[6], "participant state is invalid")
    return {"participant_count": 2, "peer_recorded": True}


@contextlib.contextmanager
def _open_data_plane(network: object):
    tap = network._tap  # ldn 0.0.17 runtime-contract boundary
    ifname = tap.name()
    local_ip = network.participant().ip_address
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx = None
    try:
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        tx.bind((local_ip, PIA_PORT))
        rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
        rx.bind((ifname, 0))
        rx.setblocking(False)
        yield {"tap_ready": True, "udp_bound": True, "packet_socket_bound": True}
    except OSError as error:
        raise BStageError("B_DATA_PLANE_FAILED", GATES[4], "Pia data-plane sockets are unavailable") from error
    finally:
        if rx is not None:
            rx.close()
        tx.close()


class DirectBStage:
    """One-shot, no-retry B stage with run-local compatibility hooks."""

    def __init__(
        self,
        *,
        run_id: str,
        release: str,
        phy: str,
        keys_path: str | Path,
        ap_ifname: str,
        monitor_ifname: str,
        tap_ifname: str,
        gate_sink: GateSink | None = None,
        channel: int = 6,
        ap_timeout: float = 45,
        association_timeout: float = 120,
        control_timeout: float = 10,
        hold_seconds: float = 5,
        ldn_module=None,
        trio_module=None,
        radio_reset=None,
        data_plane_factory=None,
        network_factory=None,
        version_resolver=None,
    ):
        self.run_id = run_id
        self.release = release
        self.phy = phy
        self.keys_path = str(keys_path)
        self.ap_ifname = ap_ifname
        self.monitor_ifname = monitor_ifname
        self.tap_ifname = tap_ifname
        self.gate_sink = gate_sink or (lambda _event: None)
        self.channel = int(channel)
        self.ap_timeout = float(ap_timeout)
        self.association_timeout = float(association_timeout)
        self.control_timeout = float(control_timeout)
        self.hold_seconds = float(hold_seconds)
        self.ldn = ldn_module
        self.trio = trio_module
        self.radio_reset = radio_reset or (lambda: reset_selected_phy(self.phy))
        self.data_plane_factory = data_plane_factory or _open_data_plane
        self.network_factory = network_factory
        self.version_resolver = version_resolver or (lambda: metadata.version("ldn"))
        self.started = time.monotonic()
        self.passed: list[dict] = []
        self.result_level = None
        self.compatibility = {
            "beacon_head": False,
            "monitor_ccmp": False,
            "remote_destroy": False,
        }

    def _pass(self, gate: str) -> None:
        if gate not in GATES or len(self.passed) >= len(GATES) or gate != GATES[len(self.passed)]:
            raise BStageError("B_GATE_ORDER_INVALID", gate, "B-stage checkpoint order is invalid")
        item = {"gate": gate, "elapsed_ms": round((time.monotonic() - self.started) * 1000)}
        self.passed.append(item)
        self.gate_sink({"event": "b_gate_passed", **item})

    def _policy(self) -> None:
        names = (self.ap_ifname, self.monitor_ifname, self.tap_ifname)
        if (
            self.version_resolver() != "0.0.17"
            or not re.fullmatch(r"phy[0-9]+", self.phy)
            or any(not _LINUX_NAME.fullmatch(name) for name in names)
            or len(set(names)) != 3
            or self.channel not in {1, 6, 11}
            or min(
                self.ap_timeout, self.association_timeout,
                self.control_timeout, self.hold_seconds,
            ) <= 0
        ):
            raise BStageError("B_POLICY_INVALID", GATES[0], "direct B policy is invalid")

    def _build_param(self, keys: dict):
        param = self.ldn.CreateNetworkParam()
        param.keys = keys
        param.local_communication_id = COMMUNICATION_ID
        param.scene_id = SCENE_ID
        param.max_participants = MAX_PARTICIPANTS
        param.application_data = FIXTURE
        param.accept_policy = ACCEPT_ALL
        param.password = GBA_APP_PASSPHRASE
        param.channel = self.channel
        param.name = FIXTURE_NAME
        param.app_version = APP_VERSION
        param.protocol = PROTOCOL
        param.phyname = self.phy
        param.phyname_monitor = self.phy
        param.ifname = self.ap_ifname
        param.ifname_monitor = self.monitor_ifname
        param.ifname_tap = self.tap_ifname
        param.ssid = secrets.token_bytes(16)
        param.server_random = secrets.token_bytes(16)
        try:
            param.check()
        except (TypeError, ValueError) as error:
            raise BStageError("B_NETWORK_PARAM_INVALID", GATES[2], "LDN host parameters are invalid") from error
        return param

    @contextlib.asynccontextmanager
    async def _create_network(self, param):
        """Mirror ldn.create_network with object-local compatibility hooks only."""
        ldn = self.ldn
        wlan = ldn.wlan
        derivation = ldn.KeyDerivation(
            param.keys,
            param.protocol,
            override_advertise_key=param.override_advertise_key,
            override_data_key=param.override_data_key,
            override_challenge_key=param.override_challenge_key,
        )
        key = derivation.derive_data_key(param.server_random, param.password)
        async with wlan.create_factory() as factory:
            async with factory._create_interface(
                param.phyname, param.ifname, wlan.nl80211.NL80211_IFTYPE_AP
            ) as attributes:
                ap = wlan.AccessPoint(
                    factory._wlan,
                    factory._router,
                    param.ifname,
                    attributes[wlan.nl80211.NL80211_ATTR_IFINDEX],
                    wlan.MACAddress(attributes[wlan.nl80211.NL80211_ATTR_MAC]),
                    param.ssid.hex(),
                    param.channel,
                    key,
                    param.max_participants,
                )
                ap._create_beacon_head = lambda: _build_beacon_head(
                    param.ssid.hex().encode("ascii"), param.channel, bytes(ap.address())
                )
                self.compatibility["beacon_head"] = True
                async with ap.create():
                    async with factory.create_monitor(
                        param.phyname_monitor, param.ifname_monitor
                    ) as monitor:
                        receive_frame = monitor.recv_frame

                        async def receive_compat():
                            frame = await receive_frame()
                            if (
                                isinstance(frame, wlan.DataFrame)
                                and frame.protected
                                and frame.payload.startswith(b"\xaa\xaa\x03")
                                and len(frame.payload) >= 16
                            ):
                                frame.payload = frame.payload[:-8]
                                frame.protected = False
                            return frame

                        monitor.recv_frame = receive_compat
                        self.compatibility["monitor_ccmp"] = True
                        async with factory.create_tap(param.ifname_tap, monitor.address()) as tap:
                            network = ldn.APNetwork(ap, monitor, tap, param, derivation, key)
                            control_done = self.trio.Event()
                            send_custom = ap.send_custom_frame

                            async def tracked_control(address, frame):
                                await send_custom(address, frame)
                                peers = [
                                    item for item in network.info().participants
                                    if getattr(item, "connected", False)
                                    and bytes(item.mac_address) != bytes(network.participant().mac_address)
                                ]
                                if any(bytes(item.mac_address) == bytes(address) for item in peers):
                                    control_done.set()

                            ap.send_custom_frame = tracked_control

                            async def destroy_remote_only():
                                local = bytes(network.participant().mac_address)
                                for participant in network.info().participants:
                                    if (
                                        not getattr(participant, "connected", False)
                                        or bytes(participant.mac_address) == local
                                    ):
                                        continue
                                    frame = ldn.DisconnectFrame()
                                    frame.reason = ldn.DISCONNECT_NETWORK_DESTROYED
                                    await ap.send_custom_frame(participant.mac_address, frame.encode())

                            network._destroy_network = destroy_remote_only
                            self.compatibility["remote_destroy"] = True
                            async with network.start():
                                yield network, control_done

    async def _hold(self, network) -> None:
        leave_type = getattr(self.ldn, "LeaveEvent", ())
        disconnect_type = getattr(self.ldn, "DisconnectEvent", ())
        with self.trio.move_on_after(self.hold_seconds):
            while True:
                event = await network.next_event()
                if isinstance(event, (leave_type, disconnect_type)):
                    raise BStageError("B_LOCAL_HOLD_LOST", GATES[8], "joining Switch left during local hold")
        _validate_peer(network)

    def _failure(self, error: BStageError) -> dict:
        return {
            "contract_version": "direct-b-stage.v1",
            "schema": 1,
            "run_id": self.run_id,
            "release": self.release,
            "status": "failed",
            "result_level": self.result_level,
            "last_passed_gate": self.passed[-1]["gate"] if self.passed else None,
            "gates": list(self.passed),
            "fixture": {"id": FIXTURE_ID, "length": len(FIXTURE), "sha256": FIXTURE_SHA256},
            "radio_reset": None,
            "compatibility": dict(self.compatibility),
            "data_plane": None,
            "association": None,
            "failure": {"code": error.code, "gate": error.gate, "message": error.message},
            "duration_ms": round((time.monotonic() - self.started) * 1000),
        }

    async def run(self) -> dict:
        radio_evidence = None
        plane_evidence = None
        association_evidence = None
        try:
            if self.ldn is None:
                import ldn
                self.ldn = ldn
            if self.trio is None:
                import trio
                self.trio = trio
            self._policy()
            try:
                advertisement = validate_advertisement(FIXTURE)
            except AStageError as error:
                raise BStageError(
                    "B_FIXTURE_INVALID", GATES[0], "diagnostic fixture is incompatible"
                ) from error
            if advertisement["sha256"] != FIXTURE_SHA256:
                raise BStageError("B_FIXTURE_HASH_MISMATCH", GATES[0], "diagnostic fixture hash changed")
            self._pass(GATES[0])

            radio_evidence = self.radio_reset()
            if not isinstance(radio_evidence, dict) or radio_evidence.get("selected_phy_only") is not True:
                raise BStageError("B_RADIO_RESET_FAILED", GATES[1], "radio reset evidence is incomplete")
            self._pass(GATES[1])

            try:
                keys = self.ldn.load_keys(self.keys_path)
            except (OSError, ValueError, TypeError) as error:
                raise BStageError("B_KEYS_INVALID", GATES[2], "production LDN keys are unavailable") from error
            if not isinstance(keys, dict) or not keys:
                raise BStageError("B_KEYS_INVALID", GATES[2], "production LDN keys are invalid")
            param = self._build_param(keys)
            self._pass(GATES[2])

            factory = self.network_factory or self._create_network
            try:
                with self.trio.fail_after(self.ap_timeout) as stage_scope:
                    async with factory(param) as opened:
                        network, control_done = opened
                        names = (
                            network._interface.name(), network._monitor.name(), network._tap.name()
                        )
                        if names != (self.ap_ifname, self.monitor_ifname, self.tap_ifname):
                            raise BStageError("B_RESOURCE_IDENTITY_MISMATCH", GATES[3], "LDN resource identity changed")
                        if not all(self.compatibility.values()):
                            raise BStageError("B_COMPATIBILITY_MISSING", GATES[3], "required host compatibility is missing")
                        self._pass(GATES[3])

                        with self.data_plane_factory(network) as plane:
                            if not all(plane.get(name) is True for name in (
                                "tap_ready", "udp_bound", "packet_socket_bound"
                            )):
                                raise BStageError("B_DATA_PLANE_FAILED", GATES[4], "Pia data-plane evidence is incomplete")
                            plane_evidence = dict(plane)
                            self._pass(GATES[4])

                            stage_scope.deadline = self.trio.current_time() + self.association_timeout
                            join_type = getattr(self.ldn, "JoinEvent", ())
                            while True:
                                event = await network.next_event()
                                if isinstance(event, join_type):
                                    association_evidence = _validate_peer(network)
                                    # A successful real association is stronger external evidence
                                    # than interface-up and proves the room was observable first.
                                    self._pass(GATES[5])
                                    self._pass(GATES[6])
                                    self.result_level = "B_SWITCH_ASSOCIATED"
                                    break

                            stage_scope.deadline = self.trio.current_time() + self.control_timeout
                            await control_done.wait()
                            _validate_peer(network)
                            self._pass(GATES[7])
                            self.result_level = "B_CONTROL_READY"

                            stage_scope.deadline = self.trio.current_time() + self.hold_seconds + 3
                            await self._hold(network)
                            self._pass(GATES[8])
            except self.trio.TooSlowError as error:
                index = min(len(self.passed), len(GATES) - 1)
                codes = {
                    3: "B_AP_CREATION_TIMEOUT",
                    5: "B_SWITCH_ASSOCIATION_TIMEOUT",
                    7: "B_CONTROL_PORT_TIMEOUT",
                    8: "B_HOLD_TIMEOUT",
                }
                raise BStageError(
                    codes.get(index, "B_STAGE_TIMEOUT"), GATES[index],
                    "direct B stage deadline expired",
                ) from error
            except BStageError:
                raise
            except BaseException as error:
                index = min(len(self.passed), len(GATES) - 1)
                codes = {
                    3: "B_AP_CREATION_FAILED",
                    4: "B_DATA_PLANE_FAILED",
                    5: "B_ROOM_ADVERTISEMENT_FAILED",
                    6: "B_SWITCH_ASSOCIATION_FAILED",
                    7: "B_CONTROL_PORT_FAILED",
                    8: "B_LOCAL_HOLD_LOST",
                }
                raise BStageError(
                    codes.get(index, "B_STAGE_INTERNAL"), GATES[index],
                    "direct B failed at its current gate",
                ) from error

            return {
                "contract_version": "direct-b-stage.v1",
                "schema": 1,
                "run_id": self.run_id,
                "release": self.release,
                "status": "passed",
                "result_level": self.result_level,
                "last_passed_gate": self.passed[-1]["gate"],
                "gates": list(self.passed),
                "fixture": {"id": FIXTURE_ID, "length": len(FIXTURE), "sha256": FIXTURE_SHA256},
                "radio_reset": radio_evidence,
                "compatibility": dict(self.compatibility),
                "data_plane": {**plane_evidence, "local_hold_completed": True},
                "association": association_evidence,
                "failure": None,
                "duration_ms": round((time.monotonic() - self.started) * 1000),
            }
        except BStageError as error:
            report = self._failure(error)
            report["radio_reset"] = radio_evidence
            report["data_plane"] = plane_evidence
            report["association"] = association_evidence
            return report
        except (ImportError, metadata.PackageNotFoundError):
            return self._failure(BStageError(
                "B_RUNTIME_DEPENDENCY_MISSING", GATES[0], "direct B runtime dependency is unavailable"
            ))
