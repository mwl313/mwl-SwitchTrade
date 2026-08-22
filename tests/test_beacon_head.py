"""STEP 8-fix offline tests: hostapd-style BEACON_HEAD builder + Station monkey-patch.

No real radio / ldn install needed - ldn and ldn.wlan are injected as stubs via
sys.modules (same pattern as test_bssid_patch.py).

Run:  .venv/bin/python tests/test_beacon_head.py
"""

import os
import sys
import types
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from frlgsim.transport import (                       # noqa: E402
    _build_host_beacon_head,
    install_beacon_head_override,
    _BEACON_HEAD_INSTALLED,
)


def _make_ldn_stub(version="0.0.17", with_station=True):
    """Build fresh ldn/ldn.wlan module stubs and register them in sys.modules."""
    ldn_mod = types.ModuleType("ldn")
    wlan_mod = types.ModuleType("ldn.wlan")

    ldn_mod.__version__ = version
    ldn_mod.wlan = wlan_mod
    sys.modules["ldn"] = ldn_mod
    sys.modules["ldn.wlan"] = wlan_mod

    if with_station:
        class _FakeAddr:
            def __init__(self, b):
                self._b = bytes(b)

            def encode(self):
                return self._b

            def __bytes__(self):
                return self._b

        class AccessPoint:
            def __init__(self):
                self._ssid = b"MWLTEST"
                self._channel = 6
                self._addr = _FakeAddr(bytes.fromhex("a047d7b02b39"))

            def address(self):
                return self._addr

            @staticmethod
            def stock_head():
                # mimic the measured stock output: no IEs at all
                return bytes.fromhex(
                    "80000000ffffffffffffa047d7b02b39a047d7b02b390000"
                    "000000000000000064001104"
                )

            def _create_beacon_head(self):
                return self.stock_head()

        wlan_mod.AccessPoint = AccessPoint
        wlan_mod._FakeAddr = _FakeAddr
    return ldn_mod, wlan_mod


class BeaconHeadBuilderTest(unittest.TestCase):
    SSID = b"MWLTEST"
    CH = 6
    BSSID = bytes.fromhex("a047d7b02b39")

    def setUp(self):
        self.head = _build_host_beacon_head(self.SSID, self.CH, self.BSSID)

    def test_starts_with_mgmt_beacon_fc_and_broadcast_da(self):
        self.assertEqual(self.head[:2], b"\x80\x00")          # mgmt subtype 8
        self.assertEqual(self.head[4:10], b"\xff" * 6)         # DA broadcast

    def test_sa_and_bssid_are_our_card(self):
        self.assertEqual(self.head[10:16], self.BSSID)         # SA
        self.assertEqual(self.head[16:22], self.BSSID)         # BSSID

    def test_fixed_fields_interval_capability(self):
        # offset 24: timestamp(8) then interval LE=100 (0x0064), capability=0x0401
        self.assertEqual(self.head[24:32], b"\x00" * 8)
        interval = int.from_bytes(self.head[32:34], "little")
        cap = int.from_bytes(self.head[34:36], "little")
        self.assertEqual(interval, 100)
        self.assertEqual(cap, 0x0401)

    def test_ssid_ie_present_with_mwltest_bytes(self):
        ie = bytes([0x00, len(self.SSID)]) + self.SSID
        self.assertIn(ie, self.head)
        # the known MWLTEST hex must appear byte-for-byte
        self.assertIn(bytes.fromhex("4d574c54455354"), self.head)

    def test_supported_rates_ie_present(self):
        rates_ie = bytes([0x01, 0x08, 0x82, 0x84, 0x8b, 0x96, 0x0c, 0x12, 0x18, 0x24])
        self.assertIn(rates_ie, self.head)

    def test_ds_params_reflect_channel(self):
        self.assertIn(bytes([0x03, 0x01, 6]), self.head)       # ch6 build
        h1 = _build_host_beacon_head(self.SSID, 1, self.BSSID)
        self.assertIn(bytes([0x03, 0x01, 1]), h1)              # ch1 build differs
        self.assertNotIn(bytes([0x03, 0x01, 6]), h1)

    def test_validation_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            _build_host_beacon_head(b"x" * 33, 6, self.BSSID)   # ssid too long
        with self.assertRaises(ValueError):
            _build_host_beacon_head(self.SSID, 15, self.BSSID)  # bad channel
        with self.assertRaises(ValueError):
            _build_host_beacon_head(self.SSID, 6, b"\x01\x02")  # short bssid
        with self.assertRaises(TypeError):
            _build_host_beacon_head("MWLTEST", 6, self.BSSID)   # str not bytes


class InstallOverrideTest(unittest.TestCase):
    def setUp(self):
        global _BEACON_HEAD_INSTALLED
        import frlgsim.transport as t
        t._BEACON_HEAD_INSTALLED = False                       # reset per-test

    def tearDown(self):
        global _BEACON_HEAD_INSTALLED
        import frlgsim.transport as t
        t._BEACON_HEAD_INSTALLED = False
        sys.modules.pop("ldn", None)
        sys.modules.pop("ldn.wlan", None)

    def test_override_wraps_station_and_uses_instance_state(self):
        _make_ldn_stub()
        logs = []
        installed = install_beacon_head_override(logs.append)
        self.assertTrue(installed)
        import ldn.wlan as W
        from ldn.wlan import AccessPoint
        st = AccessPoint.__new__(AccessPoint)                  # skip Interface.__init__
        st._ssid = b"MWLTEST"
        st._channel = 6
        st._addr = W._FakeAddr(bytes.fromhex("a047d7b02b39"))
        st.address = lambda: st._addr
        head = st._create_beacon_head()                        # patched path
        self.assertIn(bytes([0x00, 7]) + b"MWLTEST", head)     # our SSID IE
        self.assertIn(bytes([0x03, 0x01, 6]), head)            # DS params from self._channel
        self.assertTrue(any("overridden" in m for m in logs))

    def test_second_call_is_noop(self):
        _make_ldn_stub()
        self.assertTrue(install_beacon_head_override())
        self.assertFalse(install_beacon_head_override())       # already installed

    def test_missing_station_falls_back_to_false(self):
        _make_ldn_stub(with_station=False)
        logs = []
        self.assertFalse(install_beacon_head_override(logs.append))
        self.assertTrue(any("missing" in m or "stock" in m for m in logs))

    def test_patched_method_falls_back_when_attrs_missing(self):
        _make_ldn_stub()
        install_beacon_head_override()
        import ldn.wlan as W
        from ldn.wlan import AccessPoint
        st = AccessPoint.__new__(AccessPoint)
        st._ssid = b"MWLTEST"
        st._channel = 6
        st._addr = W._FakeAddr(bytes.fromhex("a047d7b02b39"))
        st.address = lambda: st._addr
        del st._ssid                                           # break the instance state
        # fallback path: the patched method catches the AttributeError and calls the
        # captured stock method - assert it returns bytes without raising
        result = st._create_beacon_head()
        self.assertIsInstance(result, (bytes, bytearray))


if __name__ == "__main__":
    unittest.main(verbosity=2)
