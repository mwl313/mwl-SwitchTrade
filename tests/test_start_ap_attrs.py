"""STEP B4 offline tests: the START_AP attrs override (_wlan-proxy injection).

docs/plan/18-b2-gap분석.md: ldn 0.0.17's AccessPoint._start_ap builds its attrs LOCALLY
and hands them to self._wlan.request(NL80211_CMD_START_AP, attrs), so the override swaps
the AP's _wlan handle for a transparent proxy (same mechanism as C-4's _WlanProxy) and
rewrites START_AP requests IN PLACE. ldn/nl80211 are Linux-only (radio + netlink), so the
tests inject fake `ldn`, `ldn.wlan` and `nl80211` modules via sys.modules; FakeAP mirrors
the VERIFIED ldn 0.0.17 shape (docs/research/ldn-0.0.17-src/wlan.py:1572-1633):

  - local attrs dict incl. HIDDEN_SSID=ZERO_CONTENTS(2) [the GAP-4 stock value];
  - request(START_AP, attrs); receive() until a START_AP event;
  - optional NEW_KEY when a key is set; STOP_AP in the CM's finally.

Verified behaviors:
  1. the START_AP request carries all 4 injected attrs, pre-existing attrs untouched;
  2. BEACON_IES/PROBERESP_IES/ASSOCRESP_IES are EXACTLY the hostapd-measured
     Extended Capabilities IE 7f080400000200000040 (10 bytes);
  3. HIDDEN_SSID flips ZERO_CONTENTS(2) -> NOT_IN_USE(0);
  4. other commands (NEW_KEY/STOP_AP) pass through UNMODIFIED - no injection;
  5. double install does NOT double-wrap (second call no-op / marker guard, class
     attr identity preserved); plus install guards + wlan-handle restore.

Run:  .venv/bin/python tests/test_start_ap_attrs.py
"""

import asyncio
import contextlib
import os
import sys
import types
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from frlgsim import transport as tmod  # noqa: E402


# --- fake nl80211 constants (values only need self-consistency) ------------------------------

CMD_START_AP = 16
CMD_NEW_KEY = 14
CMD_STOP_AP = 15

ATTR_IFINDEX = 3
ATTR_MAC = 6
ATTR_SSID = 11
ATTR_BEACON_HEAD = 14
ATTR_BEACON_TAIL = 15
ATTR_BEACON_INTERVAL = 18
ATTR_DTIM_PERIOD = 27
ATTR_HIDDEN_SSID = 200
HIDDEN_NOT_IN_USE = 0
HIDDEN_ZERO_CONTENTS = 2
ATTR_BEACON_IES = 201
ATTR_PROBERESP_IES = 202
ATTR_ASSOCRESP_IES = 203

# The hostapd-measured Extended Capabilities IE (GAP-1..3 target value).
EXT_CAP_IE = bytes.fromhex("7f080400000200000040")
INJECTED_ATTRS = (ATTR_BEACON_IES, ATTR_PROBERESP_IES, ATTR_ASSOCRESP_IES,
                  ATTR_HIDDEN_SSID)

BSSID = bytes.fromhex("a047d7b02b39")


class FakeMessage:
    """Stand-in for a netlink message: .type + .attributes."""

    def __init__(self, type, attributes):
        self.type = type
        self.attributes = attributes


def _install_fake_modules(version="0.0.17", with_start_ap=True):
    """Inject fresh fake ldn/ldn.wlan/nl80211 modules into sys.modules; returns wlan_mod."""
    nl = types.ModuleType("nl80211")
    nl.NL80211_CMD_START_AP = CMD_START_AP
    nl.NL80211_CMD_NEW_KEY = CMD_NEW_KEY
    nl.NL80211_CMD_STOP_AP = CMD_STOP_AP
    nl.NL80211_ATTR_IFINDEX = ATTR_IFINDEX
    nl.NL80211_ATTR_MAC = ATTR_MAC
    nl.NL80211_ATTR_SSID = ATTR_SSID
    nl.NL80211_ATTR_BEACON_HEAD = ATTR_BEACON_HEAD
    nl.NL80211_ATTR_BEACON_TAIL = ATTR_BEACON_TAIL
    nl.NL80211_ATTR_BEACON_INTERVAL = ATTR_BEACON_INTERVAL
    nl.NL80211_ATTR_DTIM_PERIOD = ATTR_DTIM_PERIOD
    nl.NL80211_ATTR_HIDDEN_SSID = ATTR_HIDDEN_SSID
    nl.NL80211_HIDDEN_SSID_NOT_IN_USE = HIDDEN_NOT_IN_USE
    nl.NL80211_HIDDEN_SSID_ZERO_CONTENTS = HIDDEN_ZERO_CONTENTS
    nl.NL80211_ATTR_BEACON_IES = ATTR_BEACON_IES
    nl.NL80211_ATTR_PROBERESP_IES = ATTR_PROBERESP_IES
    nl.NL80211_ATTR_ASSOCRESP_IES = ATTR_ASSOCRESP_IES

    class FakeWlan:
        """Records every request, dispenses queued events."""

        def __init__(self):
            self.requests = []              # [(cmd, attrs)] in call order
            self.events = []
            self.receive_calls = 0

        async def request(self, cmd, attrs=None, *args, **kwargs):
            self.requests.append((cmd, attrs))

        async def receive(self):
            self.receive_calls += 1
            if self.events:
                return self.events.pop(0)
            return FakeMessage(CMD_START_AP, {})

    class FakeAddress:
        def __init__(self, b):
            self._b = bytes(b)

        def encode(self):
            return self._b

        def __bytes__(self):
            return self._b

    class FakeAP:
        """Mirrors ldn 0.0.17 AccessPoint._start_ap in shape: LOCAL attrs dict (with the
        stock GAP-4 value HIDDEN_SSID=ZERO_CONTENTS), request(START_AP), receive() until
        the START_AP event, optional NEW_KEY, yield, STOP_AP on exit."""

        def __init__(self, wlan, key=None):
            self._wlan = wlan
            self._key = key
            self._ssid = b"MWLTEST"
            self._channel = 6

        def index(self):
            return 1

        def address(self):
            return FakeAddress(BSSID)

        @contextlib.asynccontextmanager
        async def _start_ap(self):
            attrs = {
                ATTR_IFINDEX: self.index(),
                ATTR_SSID: self._ssid,
                ATTR_MAC: self.address().encode(),
                ATTR_BEACON_HEAD: b"\x80\x00head",
                ATTR_BEACON_TAIL: b"",
                ATTR_BEACON_INTERVAL: 100,
                ATTR_DTIM_PERIOD: 3,
                ATTR_HIDDEN_SSID: HIDDEN_ZERO_CONTENTS,   # the stock ldn value (GAP-4)
            }
            await self._wlan.request(CMD_START_AP, attrs)
            while True:
                message = await self._wlan.receive()
                if message.type == CMD_START_AP:
                    break
            if self._key is not None:
                await self._wlan.request(CMD_NEW_KEY,
                                         {ATTR_IFINDEX: 1, "key": self._key})
            try:
                yield
            finally:
                await self._wlan.request(CMD_STOP_AP, {ATTR_IFINDEX: 1})

    wlan_mod = types.ModuleType("ldn.wlan")
    if with_start_ap:
        wlan_mod.AccessPoint = FakeAP
    wlan_mod.FakeWlan = FakeWlan
    wlan_mod.FakeMessage = FakeMessage

    ldn_mod = types.ModuleType("ldn")
    ldn_mod.__path__ = []
    ldn_mod.__version__ = version
    wlan_mod.nl80211 = nl          # what frlgsim.transport resolves (ldn.wlan's global)
    ldn_mod.wlan = wlan_mod

    sys.modules["ldn"] = ldn_mod
    sys.modules["ldn.wlan"] = wlan_mod
    sys.modules["nl80211"] = nl
    return wlan_mod


def _quiet(*args, **kwargs):
    pass


def _open_ap(ap, body=None):
    """Drive ap._start_ap() like ldn's create_network does; `body(seen)` runs inside the
    CM with access to the live state; returns `seen`."""

    async def run():
        seen = {}
        async with ap._start_ap():
            if body is not None:
                body(seen)
        return seen

    return asyncio.run(run())


class StartApAttrsOverrideTest(unittest.TestCase):
    def setUp(self):
        self.wlan_mod = _install_fake_modules()
        tmod._START_AP_ATTRS_INSTALLED = False

    def tearDown(self):
        for name in ("ldn", "ldn.wlan", "nl80211"):
            sys.modules.pop(name, None)
        tmod._START_AP_ATTRS_INSTALLED = False

    # -- 1. START_AP carries all 4 attrs, rest untouched --------------------------
    def test_start_ap_request_gets_all_four_attrs(self):
        self.assertTrue(tmod.install_start_ap_attrs_override(_quiet))
        wlan = self.wlan_mod.FakeWlan()
        ap = self.wlan_mod.AccessPoint(wlan)

        _open_ap(ap)

        starts = [(cmd, attrs) for cmd, attrs in wlan.requests if cmd == CMD_START_AP]
        self.assertEqual(len(starts), 1)
        _, attrs = starts[0]
        # the 4 injected attrs are present...
        for attr in INJECTED_ATTRS:
            self.assertIn(attr, attrs)
        # ...with every pre-existing attr untouched
        self.assertEqual(attrs[ATTR_SSID], b"MWLTEST")
        self.assertEqual(attrs[ATTR_MAC], BSSID)
        self.assertEqual(attrs[ATTR_BEACON_HEAD], b"\x80\x00head")
        self.assertEqual(attrs[ATTR_BEACON_INTERVAL], 100)
        self.assertEqual(attrs[ATTR_DTIM_PERIOD], 3)

    # -- 2. the IEs values are byte-exact -----------------------------------------
    def test_ie_values_are_exact_hostapd_bytes(self):
        self.assertTrue(tmod.install_start_ap_attrs_override(_quiet))
        wlan = self.wlan_mod.FakeWlan()
        ap = self.wlan_mod.AccessPoint(wlan)

        _open_ap(ap)

        start = next(attrs for cmd, attrs in wlan.requests if cmd == CMD_START_AP)
        expected = bytes.fromhex("7f080400000200000040")
        for attr in (ATTR_BEACON_IES, ATTR_PROBERESP_IES, ATTR_ASSOCRESP_IES):
            self.assertEqual(start[attr], expected)
            self.assertEqual(start[attr].hex(), "7f080400000200000040")
            self.assertEqual(len(start[attr]), 10)      # [7f][08] + 8 payload bytes
            self.assertEqual(start[attr][0], 0x7F)      # Extended Capabilities eid
            self.assertEqual(start[attr][1], 0x08)      # len matches the payload

    # -- 3. HIDDEN_SSID flips ZERO_CONTENTS -> NOT_IN_USE ---------------------------
    def test_hidden_ssid_flipped_to_not_in_use(self):
        self.assertTrue(tmod.install_start_ap_attrs_override(_quiet))
        wlan = self.wlan_mod.FakeWlan()
        ap = self.wlan_mod.AccessPoint(wlan)

        _open_ap(ap)

        start = next(attrs for cmd, attrs in wlan.requests if cmd == CMD_START_AP)
        self.assertEqual(start[ATTR_HIDDEN_SSID], HIDDEN_NOT_IN_USE)   # 0, hostapd parity
        self.assertNotEqual(start[ATTR_HIDDEN_SSID], HIDDEN_ZERO_CONTENTS)

    # -- 4. other commands untouched -------------------------------------------------
    def test_other_commands_unaffected(self):
        self.assertTrue(tmod.install_start_ap_attrs_override(_quiet))
        key = b"k" * 16
        wlan = self.wlan_mod.FakeWlan()
        ap = self.wlan_mod.AccessPoint(wlan, key=key)   # key -> NEW_KEY fires mid-join

        _open_ap(ap)

        self.assertEqual([cmd for cmd, _ in wlan.requests],
                         [CMD_START_AP, CMD_NEW_KEY, CMD_STOP_AP])
        new_key_cmd, new_key_attrs = wlan.requests[1]
        stop_cmd, stop_attrs = wlan.requests[2]
        self.assertEqual(new_key_cmd, CMD_NEW_KEY)
        self.assertEqual(stop_cmd, CMD_STOP_AP)
        for attr in INJECTED_ATTRS:
            self.assertNotIn(attr, new_key_attrs)       # NO injection on NEW_KEY
            self.assertNotIn(attr, stop_attrs)          # NO injection on STOP_AP
        self.assertEqual(new_key_attrs, {ATTR_IFINDEX: 1, "key": key})
        self.assertEqual(stop_attrs, {ATTR_IFINDEX: 1})

    # -- 5a. proxy transparency + handle restore --------------------------------------
    def test_proxy_transparent_and_handle_restored(self):
        self.assertTrue(tmod.install_start_ap_attrs_override(_quiet))
        wlan = self.wlan_mod.FakeWlan()
        extra = FakeMessage(CMD_NEW_KEY, {"note": b"event"})
        ap = self.wlan_mod.AccessPoint(wlan)

        def body(seen):
            seen["handle"] = ap._wlan              # the handle INSIDE the window
            wlan.events.append(extra)
            seen["events"] = ap._wlan.events       # arbitrary attribute forwarding
            seen["requests"] = ap._wlan.requests   # same list object as the real wlan

        seen = _open_ap(ap, body)

        self.assertIsInstance(seen["handle"], tmod._StartApAttrsProxy)  # proxy inside CM
        self.assertIs(ap._wlan, wlan)                   # real handle restored after CM
        self.assertIs(seen["events"], wlan.events)      # attribute identity preserved
        self.assertIs(seen["requests"], wlan.requests)
        self.assertGreaterEqual(wlan.receive_calls, 1)  # receive() flowed through

    # -- 5b. double install must NOT double-wrap ---------------------------------------
    def test_double_install_no_double_wrap(self):
        logs1 = []
        self.assertTrue(tmod.install_start_ap_attrs_override(logs1.append))
        method_first = self.wlan_mod.AccessPoint.__dict__["_start_ap"]

        logs2 = []
        self.assertFalse(tmod.install_start_ap_attrs_override(logs2.append))  # flag: no-op
        self.assertEqual(logs2, [])                     # silent
        self.assertIs(self.wlan_mod.AccessPoint.__dict__["_start_ap"], method_first)

        # Flag reset (e.g. test harness re-import): the method marker still prevents
        # wrapping our own wrapper a second time.
        tmod._START_AP_ATTRS_INSTALLED = False
        self.assertTrue(tmod.install_start_ap_attrs_override(logs2.append))
        self.assertIs(self.wlan_mod.AccessPoint.__dict__["_start_ap"], method_first)
        self.assertFalse(getattr(method_first.__wrapped__, "_mwl_start_ap_attrs_patch",
                                 False))                # wraps the STOCK cm only

    # -- install guards ------------------------------------------------------------------
    def test_install_failure_missing_method(self):
        _install_fake_modules(with_start_ap=False)      # no AccessPoint at all
        logs = []
        self.assertFalse(tmod.install_start_ap_attrs_override(logs.append))
        self.assertTrue(any("missing" in m or "stock" in m for m in logs))

    def test_missing_constant_uses_kernel_fallback(self):
        """nl80211 binding omits IES constants (ldn 0.0.17 case) - the override should
        still install successfully using standard kernel values (BEACON_IES=22 etc)."""
        _install_fake_modules()
        import nl80211                                   # the fake we just installed
        del nl80211.NL80211_ATTR_BEACON_IES              # simulate missing constant
        logs = []
        result = tmod.install_start_ap_attrs_override(logs.append)
        self.assertTrue(result)                          # falls back, installs fine
        self.assertTrue(any("start-ap-attrs" in m for m in logs))

    def test_success_logs_once_and_mentions_the_gaps(self):
        logs = []
        self.assertTrue(tmod.install_start_ap_attrs_override(logs.append))
        self.assertEqual(len(logs), 1)
        self.assertIn("start-ap-attrs", logs[0])
        self.assertIn("patched", logs[0])


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(StartApAttrsOverrideTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_START_AP_ATTRS")
        sys.exit(0)
    sys.exit(1)
