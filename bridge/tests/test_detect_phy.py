"""WP-F detect_phy deterministic-pick unit tests (docs/09 MEDIUM-1), OFFLINE.

With TWO Realtek radios plugged in, the old detect_phy returned the FIRST match of a
STRING-sorted glob - and "phy10" < "phy2", so which card got picked depended on how many
times usbreset had bumped the wiphy numbers. A wrong pick made free_radio (C-1) tear down the
WRONG card's netdevs. detect_phy now collects EVERY candidate, sorts by the phy NUMBER
(natural sort: phy2 < phy10), returns the lowest, and warns loudly when there was more than
one so a wrong pick can be overridden with --phy. `roots` is injectable: the tests build a
fake sysfs in a tempdir (no root, no /sys, macOS-safe):

  1. single card -> detected, "auto-detected" logged, NO warning;
  2. phy10 vs phy2 -> natural sort picks phy2 (string sort would pick phy10), ONE warning
     listing both and naming the choice + the --phy hint;
  3. nothing Realtek (empty sysfs / a non-Realtek USB card) -> None, never a guess;
  4. the phy's `device` link points at the USB *interface* (1-3:1.0) which has NO
     idVendor/idProduct -> _phy_usb_id's walk up to the parent USB device still matches;
  5. `roots` accepts a LIST: candidates from several roots merge and sort naturally as one.

Run:  .venv/bin/python tests/test_detect_phy.py
"""

import os
import sys
import tempfile
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

import frlgtrade  # noqa: E402


def _mk_usb_radio(root, phy, vid, pid, iface=True):
    """Fake sysfs under `root`: <root>/ieee80211/<phy>/device -> a USB device dir carrying the
    idVendor/idProduct pair. iface=True (the kernel's real shape) points the link one level
    deeper, at the USB *interface* dir which has NO idVendor/idProduct - forcing
    _phy_usb_id to walk up to the parent USB device to find its identity."""
    # Give every fake wiphy its own USB device. Reusing one parent silently made
    # multi-radio tests overwrite each other's VID:PID pair.
    usb_name = f"1-{phy.removeprefix('phy')}"
    usbdev = os.path.join(root, "devices", "usb1", usb_name)
    os.makedirs(usbdev, exist_ok=True)
    with open(os.path.join(usbdev, "idVendor"), "w") as f:
        f.write(vid + "\n")
    with open(os.path.join(usbdev, "idProduct"), "w") as f:
        f.write(pid + "\n")
    target = usbdev
    if iface:
        target = os.path.join(usbdev, f"{usb_name}:1.0")
        os.makedirs(target, exist_ok=True)
    phydir = os.path.join(root, "ieee80211", phy)
    os.makedirs(phydir, exist_ok=True)
    os.symlink(os.path.relpath(target, phydir), os.path.join(phydir, "device"))


class DetectPhyTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sysfs = tmp.name                     # fake sysfs root (ieee80211 lives under it)

    def _detect(self, roots=None):
        logs = []
        if roots is None:
            roots = os.path.join(self.sysfs, "ieee80211")
        phy = frlgtrade.detect_phy(logs.append, roots=roots)
        return phy, logs

    # -- 1. single card: detected, no warning -------------------------------------
    def test_single_card_detected_without_warning(self):
        _mk_usb_radio(self.sysfs, "phy3", "0bda", "818b")

        phy, logs = self._detect()

        self.assertEqual(phy, "phy3")
        joined = "\n".join(logs)
        self.assertIn("auto-detected 0bda:818b on phy3", joined)
        self.assertNotIn("WARNING", joined)       # one card -> no ambiguity to warn about

    # -- 2. phy10 vs phy2: NATURAL sort picks phy2 + one warning -------------------
    def test_natural_sort_picks_lowest_phy_number_with_warning(self):
        _mk_usb_radio(self.sysfs, "phy10", "0bda", "8179")
        _mk_usb_radio(self.sysfs, "phy2", "0bda", "818b")

        phy, logs = self._detect()

        self.assertEqual(phy, "phy2")             # the old string sort picked phy10 here
        joined = "\n".join(logs)
        self.assertIn("WARNING: 2 matching USB radios found (phy2, phy10) - using phy2. "
                      "pass --phy to override", joined)
        self.assertEqual(joined.count("WARNING"), 1)
        self.assertIn("auto-detected 0bda:818b on phy2", joined)

    # -- 3. nothing Realtek: None, never a guess -----------------------------------
    def test_no_realtek_returns_none(self):
        self.assertEqual(self._detect()[0], None)          # empty ieee80211
        _mk_usb_radio(self.sysfs, "phy0", "8086", "2723")  # a non-Realtek USB card
        self.assertEqual(self._detect()[0], None)
        self.assertEqual(self._detect()[1], [])            # silent: no match, no logs

    # -- 4. USB interface -> parent device walk --------------------------------------
    def test_usb_interface_symlink_walks_up_to_parent_device(self):
        _mk_usb_radio(self.sysfs, "phy7", "0bda", "8179", iface=True)
        iface_dir = os.path.join(self.sysfs, "devices", "usb1", "1-7", "1-7:1.0")
        self.assertFalse(os.path.exists(os.path.join(iface_dir, "idVendor")),
                         "precondition: the interface dir itself carries NO USB identity")

        phy, logs = self._detect()

        self.assertEqual(phy, "phy7")             # identity found one level UP (the USB device)
        self.assertIn("auto-detected 0bda:8179 on phy7", "\n".join(logs))

    # -- 5. roots as a LIST: several roots merge into one natural sort ------------------
    def test_roots_list_merges_and_naturally_sorts(self):
        _mk_usb_radio(self.sysfs, "phy9", "0bda", "8179")
        chroot = os.path.join(self.sysfs, "chroot")
        _mk_usb_radio(chroot, "phy4", "0bda", "818b")

        phy, logs = self._detect(roots=[os.path.join(self.sysfs, "ieee80211"),
                                        os.path.join(chroot, "ieee80211")])

        self.assertEqual(phy, "phy4")             # lowest NUMBER across ALL roots
        self.assertIn("WARNING: 2 matching USB radios found (phy4, phy9)", "\n".join(logs))

    # -- 6. health-gate-selected profile: future USB IDs work without source edits -------
    def test_selected_usb_id_accepts_profile_added_card(self):
        _mk_usb_radio(self.sysfs, "phy12", "1234", "abcd")
        _mk_usb_radio(self.sysfs, "phy1", "0bda", "818b")
        logs = []

        phy = frlgtrade.detect_phy(
            logs.append,
            roots=os.path.join(self.sysfs, "ieee80211"),
            selected_usb_id="1234:abcd",
        )

        self.assertEqual(phy, "phy12")
        self.assertIn("auto-detected 1234:abcd on phy12", "\n".join(logs))
        self.assertNotIn("WARNING", "\n".join(logs))

    def test_selected_usb_id_rejects_malformed_value(self):
        with self.assertRaisesRegex(ValueError, "invalid selected USB ID"):
            frlgtrade.detect_phy(lambda _: None, roots=[], selected_usb_id="not-an-id")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(DetectPhyTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_DETECT_PHY")
        sys.exit(0)
    sys.exit(1)
