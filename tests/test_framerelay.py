"""Track B framerelay unit tests - OFFLINE (docs/07-framerelay-design.md section 6).

No sockets, no radio, no relay server: sockets and the WS are stubbed, so everything here
runs on any machine. Covered:

  1. radiotap: the measured TX header (00 00 08 00 00 00 00 00), wrap/strip round-trip,
     malformed captures rejected.
  2. MWLB 0x20 wrapping: exact wire bytes, round-trip, rejection cases, and byte parity
     with Track A's RemoteTransport framing (one wire format, two tracks).
  3. BSSID filter: host MAC match across all frame directions (beacon from AP,
     guest->host data, host->guest data, control frames) and rejection of foreign frames;
     MAC parsing.
  4. Beacon queue: dedupe + capacity + replay thread cadence; end-to-end offline pipe
     (capture -> 0x20 -> WS -> inject) with loop prevention.

Run:  .venv/bin/python tests/test_framerelay.py
"""

import os
import sys
import time
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from common import mwlb                                        # noqa: E402
from framerelay import radio as radiomod                       # noqa: E402
from framerelay.bridge import (BeaconCache, BeaconReplayer, EchoGuard,  # noqa: E402
                               RelayBridge, compose_relay_url)
from framerelay.rate_limit import TokenBucket                  # noqa: E402

HOST_MAC = bytes.fromhex("00ada7117309")       # card A (docs/07 section 3)
GUEST_MAC = bytes.fromhex("a047d7b02b39")      # card B
FOREIGN_MAC = bytes.fromhex("deadbeefcafe")
BROADCAST = b"\xff" * 6


def _quiet(*args, **kwargs):
    pass


def beacon_frame(bssid=HOST_MAC, timestamp=b"\x01\x02\x03\x04\x05\x06\x07\x08"):
    """Minimal mgmt subtype-8 frame: DA=broadcast, SA=BSSID, BSSID."""
    fc = bytes([0x80, 0x00])                   # type=0 subtype=8, flags=0
    return fc + b"\x00\x00" + BROADCAST + bssid + bssid + b"\x00" * 12 + timestamp


def data_to_ap_frame(sa=GUEST_MAC):
    """Guest -> host data: addr1 = BSSID(host), addr2 = SA(guest)."""
    return bytes([0x08, 0x01]) + b"\x00\x00" + HOST_MAC + sa + FOREIGN_MAC


def data_from_ap_frame(da=GUEST_MAC):
    """Host -> guest data: addr1 = DA(guest), addr2 = BSSID(host), addr3 = SA(host)."""
    return bytes([0x08, 0x02]) + b"\x00\x00" + da + HOST_MAC + HOST_MAC


def ctl_frame(ra):
    """Control (ACK-like): only addr1 present."""
    return bytes([0xd4, 0x00]) + b"\x00\x00" + ra


def foreign_beacon():
    return beacon_frame(bssid=FOREIGN_MAC, timestamp=b"\xff" * 8)


class FakeRadio:
    """MonitorRadio stand-in: records injections, feeds scripted captures, reuses the REAL
    filter logic so tests cover the production acceptance path."""

    def __init__(self, host_mac=None):
        self.iface = "stubmon"
        self.host_mac = host_mac
        self.sent = []                          # bare frames handed to send()
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True
        return self

    def close(self):
        self.closed = True

    def recv(self, timeout=0.05):
        return None

    def send(self, frame):
        self.sent.append(bytes(frame))

    def accepts(self, frame):
        if self.host_mac is None:
            return True
        return radiomod.matches_host(radiomod.parse_80211(frame), self.host_mac)


class RadiotapTest(unittest.TestCase):
    # -- 1. the measured header -------------------------------------------------
    def test_tx_header_is_the_measured_8_bytes(self):
        self.assertEqual(radiomod.RADIOTAP_TX_HEADER, b"\x00\x00\x08\x00\x00\x00\x00\x00")
        self.assertEqual(len(radiomod.RADIOTAP_TX_HEADER), 8)
        self.assertEqual(radiomod.wrap_radiotap(b"\xab"),
                         b"\x00\x00\x08\x00\x00\x00\x00\x00\xab")

    def test_monitor_radio_send_adds_exactly_one_radiotap_header(self):
        class SendSocket:
            def __init__(self):
                self.sent = []

            def sendto(self, data, address):
                self.sent.append((bytes(data), address))

        sock = SendSocket()
        radio = radiomod.MonitorRadio("mon-test").open(sock=sock)
        radio.send(b"\xab\xcd")
        self.assertEqual(sock.sent, [(radiomod.RADIOTAP_TX_HEADER + b"\xab\xcd",
                                      ("mon-test", 0))])

    def test_strip_roundtrip(self):
        raw = beacon_frame()
        stripped = radiomod.strip_radiotap(
            struct_pack_rtap(24) + raw)
        self.assertEqual(stripped, raw)
        # a different (realistic, longer) header length also strips correctly:
        # 32B header = 8 fixed bytes + 24 bytes of vendor/field data, then the frame.
        self.assertEqual(radiomod.strip_radiotap(struct_pack_rtap(32, fill=0x99) + raw),
                         raw)

    def test_strip_rejects_malformed(self):
        self.assertIsNone(radiomod.strip_radiotap(b"\x00"))            # too short
        self.assertIsNone(radiomod.strip_radiotap(b"\x00\x00\xff\xffab"))  # length overrun
        self.assertIsNone(radiomod.strip_radiotap(b"\x00\x00\x02\x00abcd"))  # < 8B header
        bare = beacon_frame()
        self.assertIsNone(radiomod.strip_radiotap(struct_pack_rtap(8)))  # header only


def struct_pack_rtap(length, fill=0):
    """A radiotap header that really OCCUPIES `length` bytes (8 fixed + filler fields)."""
    import struct as _s
    return _s.pack("<BBHI", 0, 0, length, 0) + bytes([fill]) * (length - 8)


class MwlbCodecTest(unittest.TestCase):
    # -- 2. wire format ---------------------------------------------------------
    def test_build_exact_bytes(self):
        self.assertEqual(mwlb.build_frame(0x20, b"\xaa\xbb"), b"MWLB\x20\x00\x02\xaa\xbb")
        self.assertEqual(mwlb.build_frame(mwlb.MSG_FRAME_RELAY, b""), b"MWLB \x00\x00")

    def test_roundtrip_and_constants(self):
        payload = beacon_frame()
        mtype, got = mwlb.parse_frame(mwlb.build_frame(mwlb.MSG_FRAME_RELAY, payload))
        self.assertEqual(mtype, mwlb.MSG_FRAME_RELAY)
        self.assertEqual(mtype, 0x20)
        self.assertEqual(got, payload)

    def test_parse_rejects_garbage(self):
        good = mwlb.build_frame(0x20, b"12345678")   # 15 bytes total
        bad_magic = b"XMLB" + good[4:]               # corrupt ONLY the magic
        self.assertIsNone(mwlb.parse_frame(bad_magic))
        self.assertEqual(mwlb.parse_frame(good), (0x20, b"12345678"))
        self.assertIsNone(mwlb.parse_frame(b"MWLB\x20\x00"))                # truncated hdr
        self.assertIsNone(mwlb.parse_frame(good[:10]))                      # short payload
        self.assertIsNone(mwlb.parse_frame("not bytes"))
        self.assertIsNotNone(mwlb.parse_frame(good + b"trailing"))          # trailing OK
        with self.assertRaises(ValueError):
            mwlb.build_frame(0x20, b"\x00" * 0x10000)

    def test_parity_with_track_a_transport(self):
        from frlgsim.transport import RemoteTransport
        for mtype in (mwlb.MSG_HEARTBEAT, mwlb.MSG_FRAME_RELAY):
            payload = beacon_frame() if mtype == 0x20 else b"\x00\x00\x00\x07"
            self.assertEqual(RemoteTransport._build_frame(mtype, payload),
                             mwlb.build_frame(mtype, payload))
            self.assertEqual(RemoteTransport._parse_frame(mwlb.build_frame(mtype, payload)),
                             mwlb.parse_frame(mwlb.build_frame(mtype, payload)))


class BssidFilterTest(unittest.TestCase):
    # -- 3. host-MAC filter across directions -----------------------------------
    def test_host_directions_match(self):
        for frame in (beacon_frame(), data_to_ap_frame(), data_from_ap_frame(),
                      ctl_frame(HOST_MAC)):
            info = radiomod.parse_80211(frame)
            self.assertTrue(radiomod.matches_host(info, HOST_MAC), frame.hex())

    def test_foreign_frames_rejected(self):
        self.assertFalse(radiomod.matches_host(radiomod.parse_80211(foreign_beacon()),
                                               HOST_MAC))
        self.assertFalse(radiomod.matches_host(radiomod.parse_80211(ctl_frame(GUEST_MAC)),
                                               HOST_MAC))

    def test_classification_helpers(self):
        self.assertTrue(radiomod.is_beacon(radiomod.parse_80211(beacon_frame())))
        probe = bytes([0x50, 0x00]) + beacon_frame()[2:]     # mgmt subtype 5
        self.assertFalse(radiomod.is_beacon(radiomod.parse_80211(probe)))
        self.assertFalse(radiomod.is_beacon(radiomod.parse_80211(data_to_ap_frame())))
        self.assertIsNone(radiomod.parse_80211(b"\x80\x00"))

    def test_radio_accepts_uses_filter(self):
        filtered = FakeRadio(host_mac=HOST_MAC)
        self.assertTrue(filtered.accepts(beacon_frame()))
        self.assertTrue(filtered.accepts(data_to_ap_frame()))
        self.assertFalse(filtered.accepts(foreign_beacon()))
        promisc = FakeRadio()
        self.assertTrue(promisc.accepts(foreign_beacon()))   # filter off relays all

    def test_parse_mac_formats(self):
        mac = radiomod.parse_mac("AA:Bb:Cc:Dd:Ee:Ff")
        self.assertEqual(mac, bytes.fromhex("aabbccddee" + "ff"))
        self.assertEqual(mac, radiomod.parse_mac("aa-bb-cc-dd-ee-ff"))
        self.assertEqual(radiomod.mac_str(mac), "aa:bb:cc:dd:ee:ff")
        for bad in ("nope", "aa:bb:cc:dd:ee", "zz:bb:cc:dd:ee:ff", b"\x00" * 5):
            with self.assertRaises(ValueError):
                radiomod.parse_mac(bad)


class BeaconQueueTest(unittest.TestCase):
    # -- 4a. cache semantics ------------------------------------------------------
    def test_cache_dedupes_and_caps(self):
        cache = BeaconCache(capacity=3)
        b1, b2 = beacon_frame(), beacon_frame(timestamp=b"\x09" * 8)
        cache.add(b1)
        cache.add(b1)                          # identical -> one entry
        self.assertEqual(len(cache), 1)
        cache.add(b2)
        cache.add(beacon_frame(timestamp=b"\x0a" * 8))
        cache.add(beacon_frame(timestamp=b"\x0b" * 8))   # over capacity -> oldest evicted
        snap = cache.snapshot()
        self.assertEqual(len(snap), 3)
        self.assertNotIn(b1, snap)             # b1 was oldest
        self.assertEqual(snap[-1], beacon_frame(timestamp=b"\x0b" * 8))

    def test_replayer_injects_at_interval(self):
        cache = BeaconCache()
        cache.add(beacon_frame())
        sent = []
        replayer = BeaconReplayer(cache, sent.append, interval=0.01, log=_quiet)
        replayer.start()
        try:
            deadline = time.monotonic() + 2.0
            while len(sent) < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertGreaterEqual(len(sent), 3)
            self.assertTrue(all(f == beacon_frame() for f in sent))
        finally:
            replayer.stop()
            replayer.join(timeout=2)
        self.assertFalse(replayer.is_alive())


class BridgePipeTest(unittest.TestCase):
    """The full transparent pipe offline: capture -> MWLB 0x20 -> [wire] -> inject."""

    def _bridge(self, host_mac=HOST_MAC):
        return RelayBridge(FakeRadio(host_mac=host_mac), "ws://relay:8000",
                           "AB12CD", role="guest", log=_quiet)

    # -- capture side -------------------------------------------------------------
    def test_capture_wraps_into_0x20_without_radiotap(self):
        app = self._bridge()
        self.assertTrue(app.on_radio_capture(beacon_frame()))
        outbox = app.drain_outbox()
        self.assertEqual(len(outbox), 1)
        mtype, payload = mwlb.parse_frame(outbox[0])
        self.assertEqual(mtype, 0x20)
        self.assertEqual(payload, beacon_frame())          # bare frame, no radiotap inside
        self.assertEqual(app.stats["relayed_out"], 1)

    def test_capture_drops_foreign_and_echo(self):
        app = self._bridge()
        self.assertFalse(app.on_radio_capture(foreign_beacon()))
        self.assertEqual(app.stats["dropped_filter"], 1)
        frame = data_to_ap_frame()
        app.echo_guard.record(frame)
        self.assertFalse(app.on_radio_capture(frame))      # our own injection echoed back
        self.assertEqual(app.stats["dropped_echo"], 1)
        self.assertEqual(app.drain_outbox(), [])

    def test_echo_guard_window_expires(self):
        guard = EchoGuard(window=0.05)
        guard.record(b"\x01\x02")
        self.assertTrue(guard.duplicate(b"\x01\x02"))
        time.sleep(0.07)
        self.assertFalse(guard.duplicate(b"\x01\x02"))     # past the window: relay again
        guard.prune()
        self.assertEqual(guard._seen, {})

    def test_url_composition(self):
        self.assertEqual(compose_relay_url("ws://r:8000/", "AB12CD", "host"),
                         "ws://r:8000/session/AB12CD/ws?role=host")
        pinned = "ws://r:8000/session/AB12CD/ws?role=guest"
        self.assertEqual(compose_relay_url(pinned, "AB12CD", "host"), pinned)

    def test_http_scheme_rewritten_to_ws(self):
        # STEP 9 finding: operators copy the relay's HTTP URL; websockets.connect
        # rejects an http scheme, so compose must rewrite it.
        self.assertEqual(compose_relay_url("http://r:8000", "AB12CD", "host"),
                         "ws://r:8000/session/AB12CD/ws?role=host")
        self.assertEqual(compose_relay_url("https://relay.example.com", "AB12CD", "guest"),
                         "wss://relay.example.com/session/AB12CD/ws?role=guest")
        pinned_https = "https://r:8000/session/AB12CD/ws?role=host"
        self.assertEqual(compose_relay_url(pinned_https, "AB12CD", "host"),
                         "wss://r:8000/session/AB12CD/ws?role=host")

    # -- injection side -------------------------------------------------------------
    def test_ws_frame_injects_with_fresh_radiotap(self):
        app = self._bridge()
        self.assertTrue(app.on_ws_message(mwlb.build_frame(mwlb.MSG_FRAME_RELAY,
                                                           beacon_frame())))
        self.assertEqual(app.radio.sent, [beacon_frame()])
        self.assertEqual(len(app.beacon_cache), 1)         # remote beacon kept alive
        self.assertEqual(app.stats["injected"], 1)

    def test_ws_swallows_heartbeat_and_garbage(self):
        app = self._bridge()
        hb = mwlb.build_frame(mwlb.MSG_HEARTBEAT, b"\x00\x00\x00\x01")
        self.assertTrue(app.on_ws_message(hb))             # consumed, never injected
        self.assertFalse(app.on_ws_message(b"garbage not mwlb"))
        self.assertFalse(app.on_ws_message(hb[:5]))        # truncated
        self.assertFalse(app.on_ws_message(mwlb.build_frame(0x7F, b"?")))  # unknown type
        self.assertEqual(app.radio.sent, [])
        self.assertEqual(app.stats["injected"], 0)

    def test_injected_frame_is_not_relayed_back(self):
        app = self._bridge()                                # loop prevention, end to end
        frame = beacon_frame()
        app.on_ws_message(mwlb.build_frame(mwlb.MSG_FRAME_RELAY, frame))
        self.assertFalse(app.on_radio_capture(frame))       # echo of our own injection
        self.assertEqual(app.drain_outbox(), [])

    # -- both halves in memory (A -> relay stub -> B) -------------------------------
    def test_two_bridges_exchange_like_the_field_setup(self):
        class WireStub:                                     # stands in for relay/server.py
            def __init__(self):
                self.pipes = {}

            def attach(self, bridge):
                self.pipes[bridge.role] = bridge
                return self

            def deliver(self, src_role, data):
                dst = self.pipes.get("guest" if src_role == "host" else "host")
                if dst is not None:
                    dst.on_ws_message(data)

        wire = WireStub()
        host_bridge = RelayBridge(FakeRadio(host_mac=HOST_MAC), "ws://relay:8000",
                                  "AB12CD", role="host", log=_quiet)
        guest_bridge = self._bridge()
        wire.attach(host_bridge)
        wire.attach(guest_bridge)

        # Switch A's beacon reaches bridge A's radio...
        self.assertTrue(host_bridge.on_radio_capture(beacon_frame()))
        for frame in host_bridge.drain_outbox():            # ...rides the relay untouched...
            wire.deliver("host", frame)
        # ...and MonitorRadio receives one bare frame; its send() adds radiotap once.
        self.assertEqual(guest_bridge.radio.sent, [beacon_frame()])
        # The reverse direction carries the guest's join request back to A.
        join_req = data_to_ap_frame()
        self.assertTrue(guest_bridge.on_radio_capture(join_req))
        for frame in guest_bridge.drain_outbox():
            wire.deliver("guest", frame)
        self.assertEqual(host_bridge.radio.sent, [join_req])
        # Neither half relayed anything twice (echo suppression held).
        self.assertEqual(host_bridge.drain_outbox() + guest_bridge.drain_outbox(), [])

    # -- lifecycle --------------------------------------------------------------------
    def test_start_stop_lifecycle_with_stub_radio(self):
        app = RelayBridge(FakeRadio(host_mac=HOST_MAC), "ws://127.0.0.1:1",
                          "AB12CD", role="host", log=_quiet)
        app.start()                                         # threads up on a stub socket
        time.sleep(0.05)
        app.stop()
        self.assertTrue(app.radio.opened and app.radio.closed)


class RateLimitWiringTest(unittest.TestCase):
    """STEP 6: the TokenBucket is actually wired into both data-plane paths (docs/13 §7)."""

    def _bridge(self, rate_fps):
        return RelayBridge(FakeRadio(host_mac=HOST_MAC), "ws://relay:8000", "AB12CD",
                           role="guest", log=_quiet, rate_fps=rate_fps)

    def test_capture_side_caps_and_counts_drops(self):
        # burst = rate by default, so a 3-frame bucket admits exactly 3 then drops.
        app = self._bridge(rate_fps=3)
        results = [app.on_radio_capture(data_to_ap_frame()) for _ in range(6)]
        self.assertEqual(results.count(True), 3)            # burst admitted
        self.assertEqual(results.count(False), 3)           # over cap -> dropped
        self.assertEqual(app.stats["dropped_rate"], 3)
        self.assertEqual(app.stats["relayed_out"], 3)

    def test_injection_side_caps_too(self):
        app = self._bridge(rate_fps=2)
        wire_frame = mwlb.build_frame(mwlb.MSG_FRAME_RELAY, beacon_frame())
        results = [app.on_ws_message(wire_frame) for _ in range(5)]
        self.assertEqual(results.count(True), 2)
        self.assertEqual(results.count(False), 3)
        self.assertEqual(len(app.radio.sent), 2)            # nothing injected over the cap
        self.assertEqual(app.stats["dropped_rate"], 3)

    def test_default_rate_is_the_docs_value(self):
        app = self._bridge(rate_fps=None)
        self.assertEqual(app.rate_limiter.rate, 200.0)      # docs/13 §7: DEFAULT_RATE_FPS

    def test_healthy_traffic_never_dropped(self):
        # A realistic second of LDN traffic (~40 frames incl. beacon replay ticks) passes.
        app = self._bridge(rate_fps=None)
        for i in range(40):
            self.assertTrue(app.on_radio_capture(data_to_ap_frame()),
                            f"frame {i} must not be dropped at default rate")
        self.assertEqual(app.stats["dropped_rate"], 0)

    def test_stats_line_includes_rate_limiter(self):
        import io
        buf = io.StringIO()
        app = RelayBridge(FakeRadio(host_mac=HOST_MAC), "ws://relay:8000", "AB12CD",
                          role="guest", log=lambda *a: buf.write(a[0] if a else ""))
        app.stop()                                          # threads never started - safe
        self.assertIn("rate_limiter", buf.getvalue())


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(RadiotapTest))
    suite.addTests(loader.loadTestsFromTestCase(MwlbCodecTest))
    suite.addTests(loader.loadTestsFromTestCase(BssidFilterTest))
    suite.addTests(loader.loadTestsFromTestCase(BeaconQueueTest))
    suite.addTests(loader.loadTestsFromTestCase(BridgePipeTest))
    suite.addTests(loader.loadTestsFromTestCase(RateLimitWiringTest))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_FRAMERELAY")
        sys.exit(0)
    sys.exit(1)
