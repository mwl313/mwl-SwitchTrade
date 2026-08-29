import contextlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import trio

from switchtrade.connection.a_stage import (
    AStageError, DirectAStage, GATES, room_mismatches, select_room, validate_advertisement,
)


def valid_application_data():
    header = bytearray(0x5C)
    header[:5] = bytes.fromhex("005c160058")
    return bytes(header) + b"#" * 30


def network(**changes):
    value = {
        "local_communication_id": 0x01006FA0233F8000,
        "scene_id": 22287,
        "protocol": 3,
        "version": 4,
        "security_mode": 1,
        "app_version": 88,
        "accept_policy": 0,
        "max_participants": 6,
        "num_participants": 1,
        "channel": 6,
        "application_data": valid_application_data(),
        "server_random": b"s" * 16,
        "ssid": b"n" * 16,
        "address": b"\x02\x00\x00\x00\x00\x01",
    }
    value.update(changes)
    return SimpleNamespace(**value)


class FakeParam:
    def check(self):
        if not self.keys or self.network is None:
            raise ValueError("invalid")


class FakeKeyDerivation:
    def __init__(self, *_args):
        pass

    def derive_data_key(self, *_args):
        return b"k" * 16


class FakeStation:
    fail_key = False
    associated_address = b"\x02\x00\x00\x00\x00\x01"

    def __init__(self, _wlan, _router, name, index, address, _ssid, _channel, _key):
        self._name = name
        self._index = index
        self._address = address

    def index(self):
        return self._index

    async def _register_key(self, _key):
        if self.fail_key:
            raise FileNotFoundError("simulated ENOENT")

    @contextlib.asynccontextmanager
    async def connect(self):
        self._host_address = self.associated_address
        await self._register_key(b"k" * 16)
        yield


class FakeFactory:
    def __init__(self):
        self._wlan = object()
        self._router = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    @contextlib.asynccontextmanager
    async def _create_interface(self, *_args):
        yield {1: 7, 2: b"\x02\x00\x00\x00\x00\x02"}


class FakeSTANetwork:
    def __init__(self, station, param, _key_derivation):
        self._interface = station
        host = SimpleNamespace(
            connected=True, ip_address="169.254.21.1", mac_address=b"\x02\x00\x00\x00\x00\x01",
        )
        local = SimpleNamespace(
            connected=True, ip_address="169.254.21.2", mac_address=b"\x02\x00\x00\x00\x00\x02",
        )
        self._info = SimpleNamespace(participants=[host, local])
        self._local = local

    def info(self):
        return self._info

    def participant(self):
        return self._local

    async def _authenticate(self):
        pass

    async def _initialize_network(self):
        pass

    @contextlib.asynccontextmanager
    async def start(self):
        await self._authenticate()
        await self._initialize_network()
        yield

    async def next_event(self):
        await trio.sleep_forever()


class FakeWlan:
    nl80211 = SimpleNamespace(
        NL80211_IFTYPE_STATION=3,
        NL80211_ATTR_IFINDEX=1,
        NL80211_ATTR_MAC=2,
    )
    Station = FakeStation
    MACAddress = bytes

    @staticmethod
    def create_factory():
        return FakeFactory()


class FakeLdn:
    wlan = FakeWlan
    KeyDerivation = FakeKeyDerivation
    ConnectNetworkParam = FakeParam
    STANetwork = FakeSTANetwork
    DisconnectEvent = type("DisconnectEvent", (), {})
    rooms = [network()]

    @staticmethod
    def load_keys(_path):
        return {"key": b"value"}

    @classmethod
    async def scan(cls, *_args, **_kwargs):
        return list(cls.rooms)


@contextlib.contextmanager
def fake_data_plane(_network):
    yield {"netdev_resolved": True, "udp_bound": True, "packet_socket_bound": True}


class DirectAContractTests(unittest.TestCase):
    def test_advertisement_validation_retains_only_hash_and_length(self):
        value = valid_application_data()
        evidence = validate_advertisement(value)
        self.assertEqual(evidence, {"length": 122, "sha256": hashlib.sha256(value).hexdigest()})
        self.assertNotIn(value.hex(), json.dumps(evidence))

    def test_invalid_base85_and_pia_bounds_fail_at_a3(self):
        invalid = bytearray(valid_application_data())
        invalid[-1] = 0x5C
        with self.assertRaises(AStageError) as caught:
            validate_advertisement(invalid)
        self.assertEqual(caught.exception.gate, GATES[3])

    def test_selection_has_no_communication_id_fallback_or_ambiguous_choice(self):
        wrong = network(local_communication_id=1)
        self.assertIn("communication_id", room_mismatches(wrong))
        with self.assertRaises(AStageError) as caught:
            select_room([wrong])
        self.assertEqual(caught.exception.code, "A_ROOM_INCOMPATIBLE")
        with self.assertRaises(AStageError) as caught:
            select_room([network(), network()])
        self.assertEqual(caught.exception.code, "A_ROOM_AMBIGUOUS")

    def test_full_low_level_path_passes_a0_through_a9_without_raw_identity(self):
        FakeStation.fail_key = False
        FakeLdn.rooms = [network()]
        emitted = []
        stage = DirectAStage(
            run_id="00000000-0000-0000-0000-000000000001",
            release="test-release",
            phy="phy0",
            ifname="sta-a-test",
            keys_path="/runtime/config/prod.keys",
            gate_sink=emitted.append,
            hold_seconds=0.01,
            ldn_module=FakeLdn,
            trio_module=trio,
            data_plane_factory=fake_data_plane,
            version_resolver=lambda: "0.0.17",
        )
        report, advertisement = trio.run(stage.run)
        self.assertEqual(report["status"], "passed")
        self.assertEqual([item["gate"] for item in report["gates"]], list(GATES))
        self.assertEqual([item["gate"] for item in emitted], list(GATES))
        self.assertEqual(advertisement, valid_application_data())
        persisted = json.dumps(report, sort_keys=True).casefold()
        self.assertNotIn("mac_address", persisted)
        self.assertNotIn(advertisement.hex(), persisted)

    def test_key_install_failure_truthfully_stops_after_a5(self):
        FakeStation.fail_key = True
        FakeLdn.rooms = [network()]
        stage = DirectAStage(
            run_id="00000000-0000-0000-0000-000000000002",
            release="test-release",
            phy="phy0",
            ifname="sta-a-test",
            keys_path="/runtime/config/prod.keys",
            hold_seconds=0.01,
            ldn_module=FakeLdn,
            trio_module=trio,
            data_plane_factory=fake_data_plane,
            version_resolver=lambda: "0.0.17",
        )
        report, advertisement = trio.run(stage.run)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure"]["code"], "A_CCMP_KEY_INSTALL_FAILED")
        self.assertEqual(report["last_passed_gate"], GATES[5])
        self.assertIsNone(advertisement)
        FakeStation.fail_key = False

    def test_wrong_association_identity_never_passes_a5(self):
        FakeStation.associated_address = b"\x02\x00\x00\x00\x00\x09"
        FakeLdn.rooms = [network()]
        stage = DirectAStage(
            run_id="00000000-0000-0000-0000-000000000003",
            release="test-release", phy="phy0", ifname="sta-a-test",
            keys_path="/runtime/config/prod.keys", hold_seconds=0.01,
            ldn_module=FakeLdn, trio_module=trio, data_plane_factory=fake_data_plane,
            version_resolver=lambda: "0.0.17",
        )
        report, _advertisement = trio.run(stage.run)
        self.assertEqual(report["failure"]["code"], "A_ASSOCIATION_IDENTITY_MISMATCH")
        self.assertEqual(report["last_passed_gate"], GATES[4])
        FakeStation.associated_address = b"\x02\x00\x00\x00\x00\x01"

    def test_schema_forbids_unredacted_extension_fields(self):
        schema = json.loads((
            Path(__file__).resolve().parents[1] / "contracts" / "abcd" /
            "direct-a-stage.v1.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("application_data", schema["properties"])
        self.assertNotIn("bssid", schema["properties"])


if __name__ == "__main__":
    unittest.main()
