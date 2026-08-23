"""Task 1/2 tests: CardProfile registry, engine factory, hostapd config builder."""
import sys
import unittest

sys.path.insert(0, ".")

from frlgsim.ap_engine import (CARD_REGISTRY, EngineNotImplemented,
                               get_card_profile, make_ap_engine)


class CardRegistryTest(unittest.TestCase):
    def test_known_cards_exist(self):
        self.assertIn("0bda:818b", CARD_REGISTRY)
        self.assertIn("0bda:8179", CARD_REGISTRY)

    def test_8192eu_prefers_hostapd(self):
        p = get_card_profile("0BDA:818B")            # case-insensitive too
        self.assertEqual(p.preferred_engine, "hostapd")
        self.assertEqual(p.driver_hint, "rtl8xxxu")

    def test_8188eu_is_guest_only(self):
        p = get_card_profile("0bda:8179")
        self.assertIsNone(p.preferred_engine)

    def test_unknown_card_raises_keyerror(self):
        with self.assertRaises(KeyError):
            get_card_profile("ffff:ffff")


class FactoryTest(unittest.TestCase):
    def test_make_hostapd_engine_for_8192eu(self):
        from frlgsim.ap_hostapd import HostapdApEngine
        eng = make_ap_engine(get_card_profile("0bda:818b"),
                             iface="ap0", ssid="aabb", channel=6)
        self.assertIsInstance(eng, HostapdApEngine)
        self.assertEqual(eng.iface, "ap0")
        self.assertEqual(eng.channel, 6)

    def test_nl80211_stub_raises_not_implemented(self):
        p = dataclasses.replace(get_card_profile("0bda:818b"),
                                preferred_engine="nl80211")
        eng = make_ap_engine(p, iface="x", ssid="s", channel=6)
        with self.assertRaises(EngineNotImplemented):
            __import__("asyncio").run(eng.start())

    def test_guest_only_card_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_ap_engine(get_card_profile("0bda:8179"),
                           iface="x", ssid="s", channel=6)


import dataclasses


class ConfigBuilderTest(unittest.TestCase):
    """Task 2: build_hostapd_conf is a pure function."""

    def test_open_network_minimal(self):
        from frlgsim.ap_hostapd import build_hostapd_conf
        conf = build_hostapd_conf(iface="ap0", ssid="aabbccdd", channel=6,
                                  wpa_passphrase=None)
        self.assertIn("interface=ap0", conf)
        self.assertIn("driver=nl80211", conf)
        self.assertIn("ssid=aabbccdd", conf)
        self.assertIn("channel=6", conf)
        self.assertIn("beacon_int=100", conf)       # LDN requirement
        self.assertIn("dtim_period=3", conf)
        self.assertNotIn("wpa=", conf)              # open network
        self.assertIn("ctrl_interface=", conf)      # join detection needs this

    def test_wpa2_when_passphrase_given(self):
        from frlgsim.ap_hostapd import build_hostapd_conf
        conf = build_hostapd_conf(iface="ap0", ssid="aabb", channel=6,
                                  wpa_passphrase="secret1234")
        self.assertIn("wpa=2", conf)
        self.assertIn("wpa_passphrase=secret1234", conf)
        self.assertIn("wpa_key_mgmt=WPA-PSK", conf)
        self.assertIn("wpa_pairwise=CCMP", conf)

    def test_ctrl_interface_dir_is_customisable(self):
        from frlgsim.ap_hostapd import build_hostapd_conf
        conf = build_hostapd_conf(iface="ap0", ssid="s", channel=6,
                                  ctrl_dir="/tmp/hostapd-frlg")
        self.assertIn("ctrl_interface=/tmp/hostapd-frlg", conf)


if __name__ == "__main__":
    unittest.main()
