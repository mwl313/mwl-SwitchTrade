"""C-4 --target-bssid unit tests (WP-B): the _wlan-proxy BSSID injection, OFFLINE.

ldn/nl80211 are Linux-only (radio + netlink), so the tests inject fake `ldn`, `ldn.wlan` and
`nl80211` modules into sys.modules and drive frlgsim.transport.install_target_bssid_patch against
a fake Station that mirrors the VERIFIED ldn 0.0.17 structure
(docs/research/ldn-0.0.17-src/wlan.py):

  - Station._connect_network(self): no args; builds a LOCAL attrs dict; calls
    self._wlan.request(NL80211_CMD_CONNECT, attrs) (wlan.py:1336); waits for the CONNECT event
    via self._wlan.receive(); stores its ATTR_MAC in self._host_address (wlan.py:1348);
    DISCONNECTs when the CM exits.
  - every other request (NEW_KEY / DISCONNECT) goes through the same self._wlan handle.

Verified behaviors:
  1. only the CONNECT request gets NL80211_ATTR_MAC injected (= the pin), rest of attrs untouched;
  2. NEW_KEY/DISCONNECT attrs pass through UNMODIFIED;
  3. receive() (and any other attribute) forwards transparently to the real wlan object;
  4. no pin (_ASSOC_TARGET empty) -> stock behavior: no proxy swap, no injection;
  5. kernel associated with a DIFFERENT BSSID (_host_address mismatch) -> immediate exception,
     wlan handle restored, clean DISCONNECT;
  6. install failure (version drift / missing method) -> returns False, ONE warning logged,
     Station left stock; success logs once and is idempotent.

Run:  .venv/bin/python tests/test_bssid_patch.py
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

CMD_CONNECT = 12
CMD_NEW_KEY = 14
CMD_DISCONNECT = 48
ATTR_MAC = 6

PIN_A = bytes.fromhex("98415c794138")
PIN_B = bytes.fromhex("020304050607")
OTHER = bytes.fromhex("aabbccddeeff")


class FakeMessage:
    """Stand-in for a netlink message: .type + .attributes, like ldn's wlan.py consumes."""

    def __init__(self, type, attributes):
        self.type = type
        self.attributes = attributes


def _install_fake_modules(version="0.0.17"):
    """Inject fresh fake ldn/ldn.wlan/nl80211 modules into sys.modules; returns wlan_mod."""
    nl = types.ModuleType("nl80211")
    nl.NL80211_CMD_CONNECT = CMD_CONNECT
    nl.NL80211_CMD_NEW_KEY = CMD_NEW_KEY
    nl.NL80211_CMD_DISCONNECT = CMD_DISCONNECT
    nl.NL80211_ATTR_MAC = ATTR_MAC

    class FakeWlan:
        """Stand-in for nl80211.NL80211: records every request, dispenses queued events."""

        def __init__(self, connect_mac=PIN_A):
            self.requests = []              # [(cmd, attrs)] in call order
            self.events = []                # messages returned by receive(), FIFO
            self.receive_calls = 0
            self.connect_mac = connect_mac  # ATTR_MAC reported on the CONNECT-complete event
            self.connect_event = FakeMessage(CMD_CONNECT, {ATTR_MAC: connect_mac})

        async def request(self, cmd, attrs=None, *args, **kwargs):
            self.requests.append((cmd, attrs))

        async def receive(self):
            self.receive_calls += 1
            if self.events:
                return self.events.pop(0)
            return self.connect_event

    class FakeStation:
        """Mirrors ldn 0.0.17 wlan.Station._connect_network EXACTLY in shape: local attrs dict,
        request(CONNECT, attrs) via self._wlan, receive() until the CONNECT event,
        _host_address = ATTR_MAC, optional NEW_KEY (like _register_key), yield, DISCONNECT."""

        def __init__(self, wlan, key=None):
            self._wlan = wlan
            self._key = key
            self._host_address = None

        @contextlib.asynccontextmanager
        async def _connect_network(self):
            attrs = {"ifindex": 1, "ssid": b"frlg"}            # LOCAL dict, like wlan.py:1309
            await self._wlan.request(CMD_CONNECT, attrs)       # wlan.py:1336 shape
            while True:
                message = await self._wlan.receive()
                if message.type == CMD_CONNECT:
                    break
            self._host_address = message.attributes[ATTR_MAC]  # wlan.py:1348 shape
            if self._key is not None:
                await self._wlan.request(CMD_NEW_KEY, {"ifindex": 1, "key": self._key})
            try:
                yield
            finally:
                await self._wlan.request(CMD_DISCONNECT, {"ifindex": 1})

    wlan_mod = types.ModuleType("ldn.wlan")
    wlan_mod.Station = FakeStation
    wlan_mod.FakeWlan = FakeWlan
    wlan_mod.FakeMessage = FakeMessage

    ldn_mod = types.ModuleType("ldn")
    ldn_mod.__path__ = []
    ldn_mod.__version__ = version
    ldn_mod.wlan = wlan_mod

    sys.modules["ldn"] = ldn_mod
    sys.modules["ldn.wlan"] = wlan_mod
    sys.modules["nl80211"] = nl
    return wlan_mod


def _quiet(*args, **kwargs):
    pass


def _join(station, body=None):
    """Drive station._connect_network() like ldn's Station.connect does; `body(seen, station)`
    runs inside the CM (with access to the station's live _wlan handle); returns `seen`."""

    async def run():
        seen = {}
        async with station._connect_network():
            if body is not None:
                body(seen, station)
        return seen

    return asyncio.run(run())


class BssidPatchTest(unittest.TestCase):
    def setUp(self):
        self.wlan_mod = _install_fake_modules()
        tmod._BSSID_PATCH.update(installed=False, failed=False, warned=False)
        tmod._ASSOC_TARGET.update(bssid=None, token=None)

    def tearDown(self):
        for name in ("ldn", "ldn.wlan", "nl80211"):
            sys.modules.pop(name, None)
        tmod._BSSID_PATCH.update(installed=False, failed=False, warned=False)
        tmod._ASSOC_TARGET.update(bssid=None, token=None)

    # -- 1. CONNECT-only injection -----------------------------------------------
    def test_connect_request_gets_mac_injected(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        # The reported BSSID must EQUAL the pin: b-lite (plan WP-B) aborts the join with a
        # ConnectionError when the kernel associated elsewhere (covered by test 5 below).
        wlan = self.wlan_mod.FakeWlan(connect_mac=PIN_B)
        station = self.wlan_mod.Station(wlan)
        tmod._ASSOC_TARGET["bssid"] = PIN_B

        _join(station)

        connects = [attrs for cmd, attrs in wlan.requests if cmd == CMD_CONNECT]
        self.assertEqual(len(connects), 1)
        self.assertEqual(connects[0][ATTR_MAC], PIN_B)   # the pin was injected...
        self.assertEqual(connects[0]["ssid"], b"frlg")   # ...with the rest of the attrs untouched
        self.assertEqual(station._host_address, PIN_B)   # the event's MAC stored as ldn does

    # -- 2. other commands untouched -----------------------------------------------
    def test_other_commands_untouched(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        wlan = self.wlan_mod.FakeWlan(connect_mac=PIN_B)
        station = self.wlan_mod.Station(wlan, key=b"k" * 16)   # key -> NEW_KEY fires mid-join
        tmod._ASSOC_TARGET["bssid"] = PIN_B

        _join(station)

        self.assertEqual([cmd for cmd, _ in wlan.requests],
                         [CMD_CONNECT, CMD_NEW_KEY, CMD_DISCONNECT])
        self.assertIn(ATTR_MAC, wlan.requests[0][1])           # CONNECT carries the pin
        self.assertNotIn(ATTR_MAC, wlan.requests[1][1])        # NEW_KEY: NO injection
        self.assertNotIn(ATTR_MAC, wlan.requests[2][1])        # DISCONNECT: NO injection

    # -- 3. receive()/attribute passthrough ------------------------------------------
    def test_receive_and_attrs_passthrough(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        wlan = self.wlan_mod.FakeWlan(connect_mac=PIN_A)
        extra = FakeMessage(CMD_NEW_KEY, {"note": b"event"})
        station = self.wlan_mod.Station(wlan)
        tmod._ASSOC_TARGET["bssid"] = PIN_A

        async def run():
            seen = {}
            async with station._connect_network():
                seen["handle"] = station._wlan                 # the handle INSIDE the window
                wlan.events.append(extra)                      # queue AFTER the CONNECT handshake
                seen["msg"] = await station._wlan.receive()    # passthrough receive()
                seen["events"] = station._wlan.events          # arbitrary attribute forwarding
            seen["after"] = station._wlan                      # handle AFTER the CM exits
            return seen

        seen = asyncio.run(run())

        self.assertIsInstance(seen["handle"], tmod._WlanProxy)  # proxy active during the join
        self.assertIs(seen["msg"], extra)                       # exact object from the REAL wlan
        self.assertIs(seen["events"], wlan.events)              # attribute identity preserved
        self.assertEqual(wlan.receive_calls, 2)                 # both receives hit the real wlan
        self.assertIs(seen["after"], wlan)                      # real handle restored afterwards

    # -- 4. no pin -> stock ------------------------------------------------------------
    def test_no_pin_stock_behavior(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        wlan = self.wlan_mod.FakeWlan(connect_mac=OTHER)
        station = self.wlan_mod.Station(wlan)
        # _ASSOC_TARGET stays empty: target_bssid=None never arms the pin (install isn't even
        # called on that path) - a stale/absent pin must keep the join fully stock.

        async def run():
            seen = {}
            async with station._connect_network():
                seen["handle"] = station._wlan
            return seen

        seen = asyncio.run(run())

        self.assertIs(seen["handle"], wlan)                     # NO proxy swap
        self.assertEqual(wlan.requests[0][0], CMD_CONNECT)
        self.assertNotIn(ATTR_MAC, wlan.requests[0][1])         # no injection anywhere
        self.assertFalse(hasattr(station._wlan, "_mwl_bssid"))  # never a proxy afterwards

    # -- 5. host_address mismatch -> exception -------------------------------------------
    def test_host_address_mismatch_raises(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        wlan = self.wlan_mod.FakeWlan(connect_mac=OTHER)        # kernel picked ANOTHER console
        station = self.wlan_mod.Station(wlan)
        tmod._ASSOC_TARGET["bssid"] = PIN_A

        with self.assertRaises(ConnectionError):
            _join(station)

        self.assertIs(station._wlan, wlan)                      # restored despite the exception
        self.assertEqual(wlan.requests[-1][0], CMD_DISCONNECT)  # clean teardown before restore

    def test_host_address_match_passes(self):
        self.assertTrue(tmod.install_target_bssid_patch(_quiet))
        wlan = self.wlan_mod.FakeWlan(connect_mac=PIN_A)        # associated with the RIGHT one
        station = self.wlan_mod.Station(wlan)
        tmod._ASSOC_TARGET["bssid"] = PIN_A

        _join(station)                                          # must NOT raise
        self.assertIs(station._wlan, wlan)

    # -- 6. install failure -> fallback + log conditions -----------------------------------
    def test_install_failure_version_drift(self):
        _install_fake_modules(version="9.9.9")                  # upstream moved on
        logs = []
        self.assertFalse(tmod.install_target_bssid_patch(logs.append))
        self.assertTrue(tmod._BSSID_PATCH["failed"])
        self.assertFalse(tmod._BSSID_PATCH["installed"])
        self.assertEqual(len(logs), 1)                          # exactly ONE warning
        self.assertIn("--target-bssid", logs[0])
        self.assertIn("not installed", logs[0])
        self.assertFalse(hasattr(self.wlan_mod.Station._connect_network, "_mwl_bssid_patch"))

        logs2 = []                                              # failed guard: silent afterwards
        self.assertFalse(tmod.install_target_bssid_patch(logs2.append))
        self.assertEqual(logs2, [])

    def test_install_failure_missing_method(self):
        del self.wlan_mod.Station._connect_network              # structural version drift
        logs = []
        self.assertFalse(tmod.install_target_bssid_patch(logs.append))
        self.assertTrue(tmod._BSSID_PATCH["failed"])
        self.assertEqual(len(logs), 1)
        self.assertIn("_connect_network", logs[0])

    def test_install_success_logs_once_and_is_idempotent(self):
        logs = []
        self.assertTrue(tmod.install_target_bssid_patch(logs.append))
        self.assertEqual(len(logs), 1)
        self.assertIn("--target-bssid", logs[0])
        self.assertIn("patched", logs[0])
        self.assertTrue(tmod.install_target_bssid_patch(logs.append))  # installed guard: True...
        self.assertEqual(len(logs), 1)                                 # ...without a new log

    # -- 7. WP-C (H-2): generation-token slot - a stale attempt's late finally-clear must not
    #       clobber the pin a newer attempt armed (start() retry race -> silent SSID+channel
    #       fallback). The proxy reads only ["bssid"], so the token lives beside it.
    def test_set_set_old_clear_keeps_new(self):
        t1 = tmod.set_assoc_target(PIN_A)
        self.assertEqual(tmod._ASSOC_TARGET["bssid"], PIN_A)
        t2 = tmod.set_assoc_target(PIN_B)                      # retry re-arms the single slot
        self.assertEqual(tmod._ASSOC_TARGET["bssid"], PIN_B)
        self.assertIsInstance(t1, int)
        self.assertNotEqual(t1, t2)                            # generations differ
        tmod.clear_assoc_target(t1)                            # OLD attempt's finally, late
        self.assertEqual(tmod._ASSOC_TARGET["bssid"], PIN_B)   # new pin survives untouched
        self.assertEqual(tmod._ASSOC_TARGET["token"], t2)
        tmod.clear_assoc_target(t2)                            # only the LIVE token disarms
        self.assertIsNone(tmod._ASSOC_TARGET["bssid"])
        self.assertIsNone(tmod._ASSOC_TARGET["token"])

    def test_clear_assoc_target_ignores_token_mismatch(self):
        tok = tmod.set_assoc_target(PIN_A)
        for stale in (None, tok - 1, tok + 1, "bogus", PIN_A):
            tmod.clear_assoc_target(stale)                     # every wrong token: silent no-op
            self.assertEqual(tmod._ASSOC_TARGET["bssid"], PIN_A)
            self.assertEqual(tmod._ASSOC_TARGET["token"], tok)
        tmod.clear_assoc_target(tok)                           # the matching token disarms
        self.assertIsNone(tmod._ASSOC_TARGET["bssid"])
        self.assertIsNone(tmod._ASSOC_TARGET["token"])
        tmod.clear_assoc_target(tok)                           # already disarmed: still a no-op


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(BssidPatchTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_BSSID")
        sys.exit(0)
    sys.exit(1)
