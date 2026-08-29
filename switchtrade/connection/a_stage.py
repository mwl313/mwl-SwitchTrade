"""Direct ABC+D A0-A9 admission against one Switch-hosted FRLG room."""

from __future__ import annotations

import contextlib
import hashlib
from importlib import metadata
from pathlib import Path
import secrets
import socket
import time
from typing import Callable


COMMUNICATION_ID = 0x01006FA0233F8000
SCENE_ID = 22287
PROTOCOL = 3
LDN_VERSION = 4
SECURITY_MODE_PROD = 1
APP_VERSION = 88
ACCEPT_ALL = 0
MAX_PARTICIPANTS = 6
CHANNELS = (1, 6, 11)
PIA_HEADER_SIZE = 0x5C
APPLICATION_DATA_SIZE = 122
PIA_PORT = 12345
GBA_APP_PASSPHRASE = bytes.fromhex(
    "fcb6f6adb9dfea66aca9c326149d2b3b08a781895cbf78f720d78b85a57584a9"
    "9665d237797b2a41ddef14063ec28d259143af7832fb3cbcf2759cbfbdc81d8c"
)

GATES = (
    "A0_SCAN_PREPARATION",
    "A1_RADIO_SCAN",
    "A2_ROOM_IDENTIFICATION",
    "A3_ADVERTISEMENT_PARSING",
    "A4_JOIN_CONSTRUCTION",
    "A5_STATION_ASSOCIATION",
    "A6_ENCRYPTION_KEYS",
    "A7_NINTENDO_CONTROL_PORT",
    "A8_LDN_PARTICIPANT_STATE",
    "A9_DATA_PLANE",
)

GateSink = Callable[[dict], None]


class AStageError(RuntimeError):
    def __init__(self, code: str, gate: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message


def _base85_decode(value: bytes) -> bytes:
    """Decode the fixed FRLG base85 payload without importing legacy transport state."""
    if len(value) % 5:
        raise ValueError("base85 length is invalid")
    output = bytearray()
    for offset in range(0, len(value), 5):
        number = 0
        for character in reversed(value[offset:offset + 5]):
            if not 0x23 <= character <= 0x78 or character == 0x5C:
                raise ValueError("base85 alphabet is invalid")
            number = number * 85 + (
                character - 0x23 if character < 0x5C else character - 0x24
            )
        if number > 0xFFFFFFFF:
            raise ValueError("base85 group is out of range")
        output.extend(number.to_bytes(4, "little"))
    return bytes(output)


def validate_advertisement(application_data: object) -> dict:
    """Validate Pia/RFU structure and return only safe, redacted evidence."""
    try:
        value = bytes(application_data)
    except (TypeError, ValueError) as error:
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "FRLG application data is not bytes"
        ) from error
    if len(value) != APPLICATION_DATA_SIZE:
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "FRLG application data length is invalid"
        )
    if value[:5] != bytes.fromhex("005c160058"):
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "Pia application header is incompatible"
        )
    name_length = int.from_bytes(value[0x17:0x1B], "big")
    if name_length > 64 or 0x1C + name_length > PIA_HEADER_SIZE:
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "Pia player-name bounds are invalid"
        )
    try:
        record = _base85_decode(value[PIA_HEADER_SIZE:])
    except ValueError as error:
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "RFU advertisement encoding is invalid"
        ) from error
    if len(record) != 24:
        raise AStageError(
            "A_ADVERTISEMENT_INVALID", GATES[3], "RFU advertisement record is invalid"
        )
    return {"length": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def room_mismatches(network: object) -> tuple[str, ...]:
    """Return exact FRLG admission mismatches without exposing room identity."""
    checks = (
        (getattr(network, "local_communication_id", None) == COMMUNICATION_ID, "communication_id"),
        (getattr(network, "scene_id", None) == SCENE_ID, "scene_id"),
        (getattr(network, "protocol", None) == PROTOCOL, "protocol"),
        (getattr(network, "version", None) == LDN_VERSION, "ldn_version"),
        (getattr(network, "security_mode", None) == SECURITY_MODE_PROD, "security_mode"),
        (getattr(network, "app_version", None) == APP_VERSION, "app_version"),
        (getattr(network, "accept_policy", None) == ACCEPT_ALL, "accept_policy"),
        (getattr(network, "max_participants", None) == MAX_PARTICIPANTS, "max_participants"),
        (getattr(network, "channel", None) in CHANNELS, "channel"),
        (
            isinstance(getattr(network, "num_participants", None), int)
            and 0 < network.num_participants < getattr(network, "max_participants", 0),
            "capacity",
        ),
    )
    return tuple(name for passed, name in checks if not passed)


def select_room(networks: object) -> object:
    if not isinstance(networks, (list, tuple)) or not networks:
        raise AStageError("A_ROOM_NOT_OBSERVED", GATES[1], "no Nintendo LDN room was observed")
    matches = [network for network in networks if not room_mismatches(network)]
    if not matches:
        raise AStageError(
            "A_ROOM_INCOMPATIBLE", GATES[2], "no observed room matches the exact FRLG contract"
        )
    if len(matches) != 1:
        raise AStageError(
            "A_ROOM_AMBIGUOUS", GATES[2], "more than one exact FRLG room is visible"
        )
    return matches[0]


def _validate_participants(network: object) -> None:
    info = network.info()
    participants = list(getattr(info, "participants", ()) or ())
    local = network.participant()
    if not participants or local is participants[0]:
        raise AStageError(
            "A_PARTICIPANT_STATE_FAILED", GATES[8], "LDN participant roles are invalid"
        )
    host = participants[0]
    if not getattr(host, "connected", False) or not getattr(local, "connected", False):
        raise AStageError(
            "A_PARTICIPANT_STATE_FAILED", GATES[8], "LDN participants are not connected"
        )
    host_ip = getattr(host, "ip_address", "")
    local_ip = getattr(local, "ip_address", "")
    if (
        not isinstance(host_ip, str) or not host_ip.startswith("169.254.")
        or not isinstance(local_ip, str) or not local_ip.startswith("169.254.")
        or host_ip == local_ip
    ):
        raise AStageError(
            "A_PARTICIPANT_STATE_FAILED", GATES[8], "LDN participant IP state is invalid"
        )
    try:
        host_mac = bytes(host.mac_address)
        local_mac = bytes(local.mac_address)
    except (AttributeError, TypeError, ValueError) as error:
        raise AStageError(
            "A_PARTICIPANT_STATE_FAILED", GATES[8], "LDN participant identity is invalid"
        ) from error
    if len(host_mac) != 6 or len(local_mac) != 6 or host_mac == local_mac:
        raise AStageError(
            "A_PARTICIPANT_STATE_FAILED", GATES[8], "LDN participant identity is invalid"
        )


@contextlib.contextmanager
def _open_data_plane(network: object):
    """Open the station netdev's Pia sockets; retain no IP or MAC in evidence."""
    interface = network._interface  # ldn 0.0.17 runtime-contract boundary
    ifname = socket.if_indextoname(interface.index())
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
        yield {"netdev_resolved": True, "udp_bound": True, "packet_socket_bound": True}
    except OSError as error:
        raise AStageError(
            "A_DATA_PLANE_FAILED", GATES[9], "Pia data-plane sockets are unavailable"
        ) from error
    finally:
        if rx is not None:
            rx.close()
        tx.close()


class DirectAStage:
    """One-shot, no-retry A stage with run-local checkpoints and redacted evidence."""

    def __init__(
        self,
        *,
        run_id: str,
        release: str,
        phy: str,
        ifname: str,
        keys_path: str | Path,
        gate_sink: GateSink | None = None,
        scan_timeout: float = 8,
        join_timeout: float = 15,
        hold_seconds: float = 5,
        dwell_time: float = 1,
        ldn_module=None,
        trio_module=None,
        data_plane_factory=None,
        version_resolver=None,
    ):
        self.run_id = run_id
        self.release = release
        self.phy = phy
        self.ifname = ifname
        self.keys_path = str(keys_path)
        self.gate_sink = gate_sink or (lambda _event: None)
        self.scan_timeout = float(scan_timeout)
        self.join_timeout = float(join_timeout)
        self.hold_seconds = float(hold_seconds)
        self.dwell_time = float(dwell_time)
        self.ldn = ldn_module
        self.trio = trio_module
        self.data_plane_factory = data_plane_factory or _open_data_plane
        self.version_resolver = version_resolver or (lambda: metadata.version("ldn"))
        self.started = time.monotonic()
        self.passed: list[dict] = []
        self.result_level = None

    def _pass(self, gate: str) -> None:
        if gate not in GATES or any(item["gate"] == gate for item in self.passed):
            raise AStageError("A_GATE_ORDER_INVALID", gate, "A-stage checkpoint order is invalid")
        expected = GATES[len(self.passed)]
        if gate != expected:
            raise AStageError("A_GATE_ORDER_INVALID", gate, "A-stage checkpoint order is invalid")
        item = {"gate": gate, "elapsed_ms": round((time.monotonic() - self.started) * 1000)}
        self.passed.append(item)
        self.gate_sink({"event": "a_gate_passed", **item})

    def _preflight(self):
        if self.version_resolver() != "0.0.17":
            raise AStageError("A_LDN_VERSION_MISMATCH", GATES[0], "installed LDN version is incompatible")
        if (
            not self.phy.startswith("phy") or len(self.phy) > 15
            or not self.ifname or len(self.ifname.encode("utf-8")) > 15
            or self.scan_timeout <= 0 or self.join_timeout <= 0
            or self.hold_seconds <= 0 or self.dwell_time <= 0
        ):
            raise AStageError("A_POLICY_INVALID", GATES[0], "direct A policy is invalid")
        try:
            keys = self.ldn.load_keys(self.keys_path)
        except (OSError, ValueError, TypeError) as error:
            raise AStageError("A_KEYS_INVALID", GATES[0], "production LDN keys are unavailable") from error
        if not isinstance(keys, dict) or not keys:
            raise AStageError("A_KEYS_INVALID", GATES[0], "production LDN keys are invalid")
        self._pass(GATES[0])
        return keys

    @contextlib.asynccontextmanager
    async def _connect(self, param):
        """Mirror ldn.connect with run-local hooks at A5-A8; mutate no class/global state."""
        ldn = self.ldn
        wlan = ldn.wlan
        key_derivation = ldn.KeyDerivation(param.keys, param.network.protocol)
        wlan_key = key_derivation.derive_data_key(param.network.server_random, param.password)
        async with wlan.create_factory() as factory:
            async with factory._create_interface(
                param.phyname, param.ifname, wlan.nl80211.NL80211_IFTYPE_STATION
            ) as attributes:
                station = wlan.Station(
                    factory._wlan,
                    factory._router,
                    param.ifname,
                    attributes[wlan.nl80211.NL80211_ATTR_IFINDEX],
                    wlan.MACAddress(attributes[wlan.nl80211.NL80211_ATTR_MAC]),
                    param.network.ssid.hex(),
                    param.network.channel,
                    wlan_key,
                )
                register_key = station._register_key

                async def tracked_register_key(key):
                    try:
                        associated = bytes(station._host_address)
                        selected = bytes(param.network.address)
                    except (AttributeError, TypeError, ValueError) as error:
                        raise AStageError(
                            "A_ASSOCIATION_IDENTITY_MISMATCH", GATES[5],
                            "associated room identity is unavailable",
                        ) from error
                    if len(associated) != 6 or associated != selected:
                        raise AStageError(
                            "A_ASSOCIATION_IDENTITY_MISMATCH", GATES[5],
                            "station associated with a different room",
                        )
                    self._pass(GATES[5])
                    await register_key(key)
                    self._pass(GATES[6])

                station._register_key = tracked_register_key
                async with station.connect():
                    sta = ldn.STANetwork(station, param, key_derivation)
                    authenticate = sta._authenticate
                    initialize = sta._initialize_network

                    async def tracked_authenticate():
                        await authenticate()
                        self._pass(GATES[7])

                    async def tracked_initialize():
                        await initialize()
                        _validate_participants(sta)
                        self._pass(GATES[8])

                    sta._authenticate = tracked_authenticate
                    sta._initialize_network = tracked_initialize
                    async with sta.start():
                        yield sta

    async def _hold(self, network) -> None:
        disconnect_type = getattr(self.ldn, "DisconnectEvent", ())
        with self.trio.move_on_after(self.hold_seconds):
            while True:
                event = await network.next_event()
                if isinstance(event, disconnect_type):
                    raise AStageError(
                        "A_LOCAL_HOLD_LOST", GATES[9], "Switch room disconnected during local hold"
                    )

    def _failure(self, error: AStageError) -> dict:
        return {
            "contract_version": "direct-a-stage.v1",
            "schema": 1,
            "run_id": self.run_id,
            "release": self.release,
            "status": "failed",
            "result_level": self.result_level,
            "last_passed_gate": self.passed[-1]["gate"] if self.passed else None,
            "gates": list(self.passed),
            "advertisement": None,
            "data_plane": None,
            "failure": {"code": error.code, "gate": error.gate, "message": error.message},
            "duration_ms": round((time.monotonic() - self.started) * 1000),
        }

    async def run(self) -> tuple[dict, bytes | None]:
        try:
            if self.ldn is None:
                import ldn
                self.ldn = ldn
            if self.trio is None:
                import trio
                self.trio = trio
            keys = self._preflight()
            try:
                with self.trio.fail_after(self.scan_timeout):
                    networks = await self.ldn.scan(
                        keys,
                        ifname=f"scan-{self.ifname}"[:15],
                        phyname=self.phy,
                        channels=list(CHANNELS),
                        dwell_time=self.dwell_time,
                        protocols=[PROTOCOL],
                    )
            except self.trio.TooSlowError as error:
                raise AStageError("A_SCAN_TIMEOUT", GATES[1], "LDN room scan timed out") from error
            if not networks:
                raise AStageError("A_ROOM_NOT_OBSERVED", GATES[1], "no Nintendo LDN room was observed")
            self._pass(GATES[1])
            selected = select_room(networks)
            self._pass(GATES[2])
            advertisement = bytes(selected.application_data)
            advert_evidence = validate_advertisement(advertisement)
            self._pass(GATES[3])

            param = self.ldn.ConnectNetworkParam()
            param.keys = keys
            param.network = selected
            param.password = GBA_APP_PASSPHRASE
            param.name = b"SwitchTrade"
            param.app_version = APP_VERSION
            param.phyname = self.phy
            param.ifname = self.ifname
            param.client_random = secrets.token_bytes(16)
            try:
                param.check()
            except (TypeError, ValueError) as error:
                raise AStageError(
                    "A_JOIN_PARAM_INVALID", GATES[4], "LDN join parameters are invalid"
                ) from error
            self._pass(GATES[4])

            try:
                with self.trio.fail_after(self.join_timeout) as stage_scope:
                    async with self._connect(param) as network:
                        try:
                            with self.data_plane_factory(network) as plane:
                                if not all(plane.get(name) is True for name in (
                                    "netdev_resolved", "udp_bound", "packet_socket_bound"
                                )):
                                    raise AStageError(
                                        "A_DATA_PLANE_FAILED", GATES[9],
                                        "Pia data-plane evidence is incomplete",
                                    )
                                self._pass(GATES[9])
                                self.result_level = "A_CONTROL_READY"
                                # A0 fixes separate join and hold budgets. Once A9 passes, extend
                                # only for the requested hold plus bounded context teardown.
                                stage_scope.deadline = (
                                    self.trio.current_time() + self.hold_seconds + 3
                                )
                                await self._hold(network)
                        except AStageError:
                            raise
                        except (OSError, ValueError) as error:
                            raise AStageError(
                                "A_DATA_PLANE_FAILED", GATES[9],
                                "Pia data-plane initialization failed",
                            ) from error
            except self.trio.TooSlowError as error:
                index = min(len(self.passed), len(GATES) - 1)
                raise AStageError(
                    "A_STAGE_TIMEOUT", GATES[index], "direct A stage deadline expired"
                ) from error
            except AStageError:
                raise
            except BaseException as error:
                index = min(len(self.passed), len(GATES) - 1)
                codes = {
                    5: "A_ASSOCIATION_FAILED",
                    6: "A_CCMP_KEY_INSTALL_FAILED",
                    7: "A_CONTROL_PORT_FAILED",
                    8: "A_PARTICIPANT_STATE_FAILED",
                    9: "A_DATA_PLANE_FAILED",
                }
                raise AStageError(
                    codes.get(index, "A_STAGE_INTERNAL"), GATES[index],
                    "direct A failed at its current gate",
                ) from error

            report = {
                "contract_version": "direct-a-stage.v1",
                "schema": 1,
                "run_id": self.run_id,
                "release": self.release,
                "status": "passed",
                "result_level": self.result_level,
                "last_passed_gate": self.passed[-1]["gate"],
                "gates": list(self.passed),
                "advertisement": advert_evidence,
                "data_plane": {
                    "netdev_resolved": True,
                    "udp_bound": True,
                    "packet_socket_bound": True,
                    "local_hold_completed": True,
                },
                "failure": None,
                "duration_ms": round((time.monotonic() - self.started) * 1000),
            }
            return report, advertisement
        except AStageError as error:
            return self._failure(error), None
        except (ImportError, metadata.PackageNotFoundError):
            return self._failure(AStageError(
                "A_RUNTIME_DEPENDENCY_MISSING", GATES[0], "direct A runtime dependency is missing"
            )), None
        except BaseException:
            index = min(len(self.passed), len(GATES) - 1)
            return self._failure(AStageError(
                "A_STAGE_INTERNAL", GATES[index], "direct A failed unexpectedly"
            )), None


__all__ = [
    "AStageError", "DirectAStage", "GATES", "room_mismatches", "select_room",
    "validate_advertisement",
]
