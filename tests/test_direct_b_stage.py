import contextlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import trio

from switchtrade.connection.b_stage import (
    BStageError,
    DirectBStage,
    FIXTURE,
    FIXTURE_ID,
    FIXTURE_NAME,
    FIXTURE_SHA256,
    GATES,
    _build_beacon_head,
    quiesce_selected_phy,
    reset_selected_phy,
)
from switchtrade.connection import direct_b_endpoint


class FakeParam:
    override_advertise_key = None
    override_data_key = None
    override_challenge_key = None

    def check(self):
        if not self.keys or len(self.application_data) != 122 or self.protocol != 3:
            raise ValueError("invalid")


class FakeJoinEvent:
    pass


class FakeLeaveEvent:
    pass


class FakeLdn:
    CreateNetworkParam = FakeParam
    JoinEvent = FakeJoinEvent
    LeaveEvent = FakeLeaveEvent
    DisconnectEvent = type("DisconnectEvent", (), {})

    @staticmethod
    def load_keys(_path):
        return {"key": b"value"}


class FakeKeyDerivation:
    def __init__(self, *_args, **_kwargs):
        pass

    def derive_data_key(self, *_args):
        return b"k" * 16


class FakeAccessPoint:
    def __init__(self, _wlan, _router, name, index, address, ssid, channel, key, maximum):
        self._wlan = _wlan
        self._name = name
        self._index = index
        self._address = address
        self._ssid = ssid
        self._channel = channel
        self.sent = []

    def name(self):
        return self._name

    def address(self):
        return self._address

    def _create_beacon_head(self):
        return b"stock"

    @contextlib.asynccontextmanager
    async def create(self):
        self.created_head = self._create_beacon_head()
        try:
            yield
        finally:
            await self._wlan.request(16, {1: self._index})

    async def send_custom_frame(self, address, frame):
        self.sent.append((bytes(address), bytes(frame)))


class Named:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeMonitor(Named):
    def __init__(self, name):
        super().__init__(name)
        self._address = b"\x02\x00\x00\x00\x00\x01"

    def address(self):
        return self._address

    async def recv_frame(self):
        await trio.sleep_forever()


class FakeTap(Named):
    pass


class FakeNetlink:
    def __init__(self, hang_stop=False):
        self.hang_stop = hang_stop
        self.commands = []

    async def request(self, command, _attrs=None, _flags=0, _header=b""):
        self.commands.append(command)
        if self.hang_stop and command == 16:
            await trio.sleep_forever()
        return []


class LowLevelFactory:
    def __init__(self, netlink=None):
        self._wlan = netlink or FakeNetlink()
        self._router = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    @contextlib.asynccontextmanager
    async def _create_interface(self, *_args):
        yield {1: 7, 2: b"\x02\x00\x00\x00\x00\x01"}

    @contextlib.asynccontextmanager
    async def create_monitor(self, _phy, name):
        yield FakeMonitor(name)

    @contextlib.asynccontextmanager
    async def create_tap(self, name, _address):
        yield FakeTap(name)


class LowLevelAPNetwork:
    def __init__(self, access_point, monitor, tap, _param, _derivation, _key):
        local = SimpleNamespace(
            connected=True, ip_address="169.254.21.1",
            mac_address=access_point.address(), app_version=88,
        )
        self._interface = access_point
        self._monitor = monitor
        self._tap = tap
        self._local = local
        self._info = SimpleNamespace(num_participants=1, participants=[local])

    def participant(self):
        return self._local

    def info(self):
        return self._info

    async def _destroy_network(self):
        raise AssertionError("stock destroy must be replaced on this run")

    @contextlib.asynccontextmanager
    async def start(self):
        try:
            yield
        finally:
            await self._destroy_network()


class FakeDisconnectFrame:
    reason = None

    def encode(self):
        return b"disconnect"


class LowLevelWlan:
    nl80211 = SimpleNamespace(
        NL80211_IFTYPE_AP=3,
        NL80211_ATTR_IFINDEX=1,
        NL80211_ATTR_MAC=2,
        NL80211_CMD_STOP_AP=16,
    )
    AccessPoint = FakeAccessPoint
    DataFrame = type("DataFrame", (), {})
    MACAddress = bytes

    @staticmethod
    def create_factory():
        return LowLevelFactory()


class LowLevelLdn(FakeLdn):
    wlan = LowLevelWlan
    KeyDerivation = FakeKeyDerivation
    APNetwork = LowLevelAPNetwork
    DisconnectFrame = FakeDisconnectFrame
    DISCONNECT_NETWORK_DESTROYED = 3


class HangingStopWlan(LowLevelWlan):
    @staticmethod
    def create_factory():
        return LowLevelFactory(FakeNetlink(hang_stop=True))


class HangingStopLdn(LowLevelLdn):
    wlan = HangingStopWlan


class FakeNetwork:
    def __init__(self, names):
        local = SimpleNamespace(
            connected=True,
            ip_address="169.254.21.1",
            mac_address=b"\x02\x00\x00\x00\x00\x01",
            app_version=88,
        )
        peer = SimpleNamespace(
            connected=True,
            ip_address="169.254.21.2",
            mac_address=b"\x02\x00\x00\x00\x00\x02",
            app_version=88,
        )
        self._local = local
        self._info = SimpleNamespace(num_participants=2, participants=[local, peer])
        self._interface, self._monitor, self._tap = map(Named, names)
        self._first = True

    def info(self):
        return self._info

    def participant(self):
        return self._local

    async def next_event(self):
        if self._first:
            self._first = False
            return FakeJoinEvent()
        await trio.sleep_forever()


@contextlib.contextmanager
def fake_data_plane(_network):
    yield {"tap_ready": True, "udp_bound": True, "packet_socket_bound": True}


def make_stage(**changes):
    options = {
        "run_id": "00000000-0000-0000-0000-000000000004",
        "release": "test-release",
        "phy": "phy0",
        "keys_path": "/runtime/config/prod.keys",
        "ap_ifname": "ap-b-test",
        "monitor_ifname": "mon-b-test",
        "tap_ifname": "tap-b-test",
        "hold_seconds": 0.01,
        "association_timeout": 0.1,
        "ldn_module": FakeLdn,
        "trio_module": trio,
        "radio_reset": lambda: {
            "selected_phy_only": True, "interfaces_removed": 1, "tap_removed": False,
        },
        "data_plane_factory": fake_data_plane,
        "version_resolver": lambda: "0.0.17",
    }
    options.update(changes)
    return DirectBStage(**options)


class DirectBContractTests(unittest.TestCase):
    def test_fixture_is_exact_validated_release_owned_input(self):
        self.assertEqual(len(FIXTURE), 122)
        self.assertEqual(hashlib.sha256(FIXTURE).hexdigest(), FIXTURE_SHA256)
        self.assertEqual(FIXTURE_ID, "frlg-search-v2")
        self.assertEqual(int.from_bytes(FIXTURE[23:27], "big"), len(FIXTURE_NAME))
        self.assertEqual(FIXTURE[27], 1)
        self.assertEqual(FIXTURE[28:28 + len(FIXTURE_NAME)], FIXTURE_NAME)

        def decode_base85(value):
            decoded = bytearray()
            for offset in range(0, len(value), 5):
                number = 0
                for char in reversed(value[offset:offset + 5]):
                    number = number * 85 + ((char - 0x23) if char < 0x5C else (char - 0x24))
                decoded.extend((number & 0xFFFFFFFF).to_bytes(4, "little"))
            return bytes(decoded)

        rfu = decode_base85(FIXTURE[92:])
        self.assertEqual(rfu[12:20], bytes.fromhex("0000000084150000"))

    def test_beacon_head_has_hidden_ssid_rates_channel_and_rsn(self):
        ssid = b"a" * 32
        bssid = bytes.fromhex("020000000001")
        head = _build_beacon_head(ssid, 6, bssid)
        self.assertEqual(head[:2], b"\x80\x00")
        self.assertIn(bytes([0, 32]) + bytes(32), head)
        self.assertIn(bytes.fromhex("010882848b960c121824"), head)
        self.assertIn(bytes([3, 1, 6]), head)
        self.assertIn(bytes([48, 20]), head)

    def test_radio_reset_touches_only_selected_phy_and_reserved_tap(self):
        with tempfile.TemporaryDirectory() as temporary:
            sys_net = Path(temporary)
            for name in ("wlan0", "builtin0", "ldn-tap"):
                (sys_net / name).mkdir()
            commands = []

            def runner(command, _timeout):
                commands.append(command)
                if command == ["iw", "dev"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout="phy#0\n\tInterface wlan0\nphy#1\n\tInterface builtin0\n",
                        stderr="",
                    )
                target = command[2] if command[:2] == ["iw", "dev"] else command[-1]
                (sys_net / target).rmdir()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            result = reset_selected_phy("phy0", runner=runner, sys_net=sys_net)
            self.assertEqual(result, {
                "selected_phy_only": True, "interfaces_removed": 1, "tap_removed": True,
            })
            self.assertFalse((sys_net / "wlan0").exists())
            self.assertTrue((sys_net / "builtin0").exists())
            self.assertNotIn(["iw", "dev", "builtin0", "del"], commands)

    def test_cleanup_verifies_every_interface_on_selected_phy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sys_net = root / "net"
            sys_phy = root / "phy"
            (sys_phy / "phy0").mkdir(parents=True)
            for name in ("ap-b-test", "builtin0", "tap-b-test"):
                (sys_net / name).mkdir(parents=True)
            (sys_net / "ap-b-test" / "flags").write_text("0x1003\n", encoding="ascii")
            commands = []

            def runner(command, _timeout):
                commands.append(command)
                if command == ["iw", "dev"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout="phy#0\n\tInterface ap-b-test\nphy#1\n\tInterface builtin0\n",
                        stderr="",
                    )
                if command == ["ip", "link", "set", "dev", "ap-b-test", "down"]:
                    (sys_net / "ap-b-test" / "flags").write_text("0x1002\n", encoding="ascii")
                elif command == ["ip", "link", "del", "dev", "tap-b-test"]:
                    (sys_net / "tap-b-test").rmdir()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            result = quiesce_selected_phy(
                "phy0", "tap-b-test", runner=runner, sys_net=sys_net, sys_phy=sys_phy)
            self.assertEqual(result, {
                "selected_phy_only": True, "interfaces_quiescent": 1, "tap_absent": True,
            })
            self.assertNotIn(["ip", "link", "set", "dev", "builtin0", "down"], commands)

    def test_low_level_factory_applies_compatibility_only_to_run_objects(self):
        stage = make_stage(ldn_module=LowLevelLdn)
        original_beacon = FakeAccessPoint._create_beacon_head
        original_receive = FakeMonitor.recv_frame
        original_destroy = LowLevelAPNetwork._destroy_network

        async def exercise():
            param = stage._build_param({"key": b"value"})
            async with stage._create_network(param) as (network, control_done):
                self.assertNotEqual(network._interface._create_beacon_head(), b"stock")
                peer = SimpleNamespace(
                    connected=True, ip_address="169.254.21.2",
                    mac_address=b"\x02\x00\x00\x00\x00\x02", app_version=88,
                )
                network.info().participants.append(peer)
                network.info().num_participants = 2
                await network._interface.send_custom_frame(peer.mac_address, b"auth-ok")
                self.assertTrue(control_done.is_set())

        trio.run(exercise)
        self.assertTrue(all(stage.compatibility.values()))
        self.assertIs(FakeAccessPoint._create_beacon_head, original_beacon)
        self.assertIs(FakeMonitor.recv_frame, original_receive)
        self.assertIs(LowLevelAPNetwork._destroy_network, original_destroy)
        self.assertEqual(stage.cleanup["ldn_last_checkpoint"], "factory_released")

    def test_joined_ap_stop_timeout_falls_through_to_interface_release(self):
        stage = make_stage(ldn_module=HangingStopLdn, teardown_timeout=0.01)

        async def exercise():
            param = stage._build_param({"key": b"value"})
            async with stage._tracked_network_context(stage._create_network(param)):
                pass

        trio.run(exercise)
        self.assertTrue(stage.cleanup["ap_stop_timed_out"])
        self.assertTrue(stage.cleanup["ldn_context_released"])
        self.assertEqual(stage.cleanup["ldn_last_checkpoint"], "factory_released")

    def test_full_direct_path_passes_b2_through_b10_without_raw_identity(self):
        emitted = []
        stage = make_stage(gate_sink=emitted.append)

        @contextlib.asynccontextmanager
        async def network_factory(param):
            self.assertEqual(param.local_communication_id, 0x01006FA0233F8000)
            self.assertEqual(param.scene_id, 22287)
            self.assertEqual(param.protocol, 3)
            self.assertEqual(param.max_participants, 6)
            self.assertEqual(param.application_data, FIXTURE)
            self.assertEqual(param.name, FIXTURE_NAME)
            async with trio.open_nursery():
                stage.compatibility = {
                    "beacon_head": True, "monitor_ccmp": True, "remote_destroy": True,
                }
                control = trio.Event()
                control.set()
                yield FakeNetwork(
                    (stage.ap_ifname, stage.monitor_ifname, stage.tap_ifname)
                ), control

        stage.network_factory = network_factory
        report = trio.run(stage.run)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["result_level"], "B_CONTROL_READY")
        self.assertEqual([item["gate"] for item in report["gates"]], list(GATES))
        self.assertEqual([item["gate"] for item in emitted], list(GATES))
        self.assertTrue(report["cleanup"]["ldn_context_released"])
        self.assertFalse(report["cleanup"]["radio_quiescent"])
        serialized = json.dumps(report, sort_keys=True).casefold()
        self.assertNotIn("mac_address", serialized)
        self.assertNotIn(FIXTURE.hex(), serialized)

    def test_post_b10_teardown_timeout_does_not_reclassify_functional_success(self):
        stage = make_stage(teardown_timeout=0.01)

        @contextlib.asynccontextmanager
        async def network_factory(_param):
            stage.compatibility = {
                "beacon_head": True, "monitor_ccmp": True, "remote_destroy": True,
            }
            control = trio.Event()
            control.set()
            try:
                yield FakeNetwork(
                    (stage.ap_ifname, stage.monitor_ifname, stage.tap_ifname)
                ), control
            finally:
                await trio.sleep_forever()

        stage.network_factory = network_factory
        report = trio.run(stage.run)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["result_level"], "B_CONTROL_READY")
        self.assertEqual(report["last_passed_gate"], GATES[-1])
        self.assertIsNone(report["failure"])
        self.assertFalse(report["cleanup"]["ldn_context_released"])

    def test_schema_tracks_the_release_owned_fixture(self):
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "direct-b-stage.v1.schema.json"
        ).read_text(encoding="utf-8"))
        fixture = schema["properties"]["fixture"]["properties"]
        self.assertEqual(fixture["id"]["const"], FIXTURE_ID)
        self.assertEqual(fixture["length"]["const"], len(FIXTURE))
        self.assertEqual(fixture["sha256"]["const"], FIXTURE_SHA256)

    def test_no_join_times_out_at_external_advertisement_gate(self):
        stage = make_stage(association_timeout=0.01)

        class NoJoin(FakeNetwork):
            async def next_event(self):
                await trio.sleep_forever()

        @contextlib.asynccontextmanager
        async def network_factory(_param):
            stage.compatibility = {
                "beacon_head": True, "monitor_ccmp": True, "remote_destroy": True,
            }
            yield NoJoin((stage.ap_ifname, stage.monitor_ifname, stage.tap_ifname)), trio.Event()

        stage.network_factory = network_factory
        report = trio.run(stage.run)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure"]["code"], "B_SWITCH_ASSOCIATION_TIMEOUT")
        self.assertEqual(report["failure"]["gate"], GATES[5])
        self.assertEqual(report["last_passed_gate"], GATES[4])
        self.assertTrue(report["cleanup"]["ldn_context_released"])

    def test_schema_forbids_raw_fixture_and_identity_fields(self):
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "direct-b-stage.v1.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("application_data", schema["properties"])
        self.assertNotIn("mac_address", schema["properties"])

    def test_endpoint_preserves_stage_context_cleanup_evidence(self):
        report = {
            "status": "passed",
            "failure": None,
            "cleanup": {
                "ldn_context_released": False,
                "radio_quiescent": False,
                "ldn_last_checkpoint": "ap_started",
                "ap_stop_timed_out": True,
            },
        }

        class FakeStage:
            def __init__(self, **_options):
                pass

            async def run(self):
                return report

        args = SimpleNamespace(
            process_start_ticks=11, run_id="run", release="release",
            launch_nonce="nonce", phy="phy0", keys=Path("keys"),
            ap_ifname="ap-b-test", monitor_ifname="mon-b-test",
            tap_ifname="tap-b-test", channel=6, ap_timeout=1,
            association_timeout=1, control_timeout=1, hold_seconds=1,
            teardown_timeout=1, report=Path("report.json"),
        )
        written = []
        with (
            mock.patch.object(direct_b_endpoint, "process_start_ticks", return_value=11),
            mock.patch.object(direct_b_endpoint, "DirectBStage", FakeStage),
            mock.patch.object(direct_b_endpoint, "quiesce_selected_phy"),
            mock.patch.object(
                direct_b_endpoint, "atomic_json",
                side_effect=lambda _path, value: written.append(dict(value["cleanup"])),
            ),
            mock.patch.object(direct_b_endpoint, "_emit"),
        ):
            self.assertEqual(direct_b_endpoint.run(args), 0)
        self.assertEqual(written, [{
            "ldn_context_released": False,
            "radio_quiescent": True,
            "ldn_last_checkpoint": "ap_started",
            "ap_stop_timed_out": True,
        }])


if __name__ == "__main__":
    unittest.main()
