"""WP-E free_radio honest-deletion unit tests (docs/09 MEDIUM-2), OFFLINE.

`_run` swallows iw/ip exit status and output, so free_radio used to log "removed ..." whether the
delete actually worked or not - a silent EBUSY/EPERM looked like success. Now every delete is
verified by re-reading /sys/class/net/<iface> and the log tells the truth. The tests inject a
fake netdev state (a set standing in for /sys/class/net) plus a fake `_run` that mutates it:

  1. successful deletes -> "removed" logs, no FAILED, no root hint, netdevs really gone;
  2. every delete failing -> per-iface "FAILED to remove <iface> from <phy>" WARN logs AND the
     `ip link del` belt-and-suspenders still issued, with the sudo/root hint EXACTLY ONCE;
  3. mixed outcome -> FAILED only for what failed, NO root hint (not everything failed);
  4. `ip link del` rescuing a vif that iw could not remove is logged as removed (final truth);
  5. nothing to delete -> no logs at all, no hint;
  6. _iw_del itself returns the verified bool.

Run:  .venv/bin/python tests/test_free_radio.py
"""

import os
import sys
import unittest

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, EMU_ROOT)

from frlgsim import transport as tmod  # noqa: E402


class FakeKernel:
    """Stands in for /sys/class/net + the iw/ip tools: `_run` mutates the netdev set exactly like
    root would; without root every delete is a no-op (the EPERM case)."""

    def __init__(self, netdevs=(), root=True):
        self.netdevs = set(netdevs)
        self.root = root
        self.cmds = []

    # replacements for module-level hooks -------------------------------------
    def iface_exists(self, iface):
        return iface in self.netdevs

    def run(self, cmd):
        cmd = list(cmd)
        self.cmds.append(cmd)
        if cmd[:2] == ["iw", "dev"] and len(cmd) == 4 and cmd[3] == "del":
            target = cmd[2]
        elif cmd[:2] == ["ip", "link"] and len(cmd) == 4 and cmd[2] == "del":
            target = cmd[3]
        else:
            return                                  # pkill/nmcli/sysctl: recorded only
        if self.root:
            self.netdevs.discard(target)


class FreeRadioTest(unittest.TestCase):

    def setUp(self):
        self._orig = (tmod._run, tmod._iface_exists, tmod.list_phy_ifaces, tmod.time.sleep)
        tmod.time.sleep = lambda s: None             # no real settling delays

    def tearDown(self):
        tmod._run, tmod._iface_exists, tmod.list_phy_ifaces, tmod.time.sleep = self._orig

    def _arm(self, kernel, mapping=None):
        tmod._run = kernel.run
        tmod._iface_exists = kernel.iface_exists
        tmod.list_phy_ifaces = lambda: mapping or {}

    # -- 1. all deletes succeed ---------------------------------------------------
    def test_success_logs_removed_no_failed_no_hint(self):
        k = FakeKernel({"ldnclient", "wlxaabbccddeeff"}, root=True)
        self._arm(k, {"phy0": ["ldnclient", "wlxaabbccddeeff"]})
        logs = []

        tmod.free_radio({"phy0"}, logs.append)

        joined = "\n".join(logs)
        self.assertIn("removed ldnclient from phy0", joined)
        self.assertIn("removed wlxaabbccddeeff from phy0", joined)
        self.assertNotIn("FAILED", joined)
        self.assertNotIn("sudo", joined)             # not every attempt failed -> no hint
        self.assertEqual(k.netdevs, set())           # the phy is REALLY empty

    # -- 2. everything fails (non-root): FAILED warns + ip fallback + ONE hint ------
    def test_all_failed_warns_and_hints_once(self):
        k = FakeKernel({"ldnclient", "wlxaabbccddeeff"}, root=False)   # EPERM everywhere
        self._arm(k, {"phy0": ["ldnclient", "wlxaabbccddeeff"]})
        logs = []

        tmod.free_radio({"phy0"}, logs.append)

        joined = "\n".join(logs)
        self.assertIn("FAILED to remove ldnclient from phy0", joined)
        self.assertIn("FAILED to remove wlxaabbccddeeff from phy0", joined)
        self.assertIn("FAILED to remove stale LDN vif ldnclient", joined)   # belt-and-suspenders
        self.assertFalse(any("removed" in l and "FAILED" not in l for l in logs))
        self.assertIn("sudo로 실행했는지 확인", joined)
        self.assertEqual(joined.count("sudo로 실행했는지 확인"), 1)          # hint EXACTLY once
        self.assertIn(["ip", "link", "del", "ldnclient"], k.cmds)           # fallback kept
        self.assertEqual(k.netdevs, {"ldnclient", "wlxaabbccddeeff"})       # nothing actually gone

    # -- 3. mixed outcome: failures reported, but NO root hint ----------------------
    def test_partial_failure_no_hint(self):
        k = FakeKernel({"ldnclient", "wlgood"}, root=False)

        def run(cmd):                                # wlgood vanishes regardless (race sim)
            k.cmds.append(list(cmd))
            target = cmd[2] if cmd[0] == "iw" else cmd[-1]
            if target == "wlgood":
                k.netdevs.discard(target)
        tmod._run = run
        tmod._iface_exists = k.iface_exists
        tmod.list_phy_ifaces = lambda: {"phy0": ["ldnclient", "wlgood"]}
        logs = []

        tmod.free_radio({"phy0"}, logs.append)

        joined = "\n".join(logs)
        self.assertIn("removed wlgood from phy0", joined)
        self.assertIn("FAILED to remove ldnclient from phy0", joined)
        self.assertNotIn("sudo로 실행했는지 확인", joined)   # SOME delete succeeded -> silent

    # -- 4. ip link del rescue is logged as removed (final verdict after both) --------
    def test_ip_fallback_rescue_logged_as_removed(self):
        class IwBroken(FakeKernel):
            def run(self, cmd):                      # iw del never works; ip link del does
                cmd = list(cmd)
                self.cmds.append(cmd)
                if cmd[:1] == ["ip"]:
                    self.netdevs.discard(cmd[3])

        k = IwBroken({"ldnclient"}, root=True)
        self._arm(k, {"phy0": ["ldnclient"]})
        logs = []

        tmod.free_radio({"phy0"}, logs.append)

        joined = "\n".join(logs)
        self.assertIn("FAILED to remove ldnclient from phy0", joined)       # iw attempt failed...
        self.assertIn("removed stale LDN vif ldnclient", joined)            # ...ip link rescued
        self.assertNotIn("sudo로 실행했는지 확인", joined)                  # final state: gone
        self.assertEqual(k.netdevs, set())

    # -- 5. nothing to delete: quiet, no hint ------------------------------------------
    def test_nothing_to_delete_is_silent(self):
        k = FakeKernel(set(), root=False)
        self._arm(k, {"phy0": []})
        logs = []

        tmod.free_radio({"phy0"}, logs.append)

        self.assertEqual([l for l in logs if "freed radio" in l], [])
        self.assertEqual([c for c in k.cmds if c[:1] == ["iw"] or c[:1] == ["ip"]], [])

    # -- 6. _iw_del returns the verified truth -------------------------------------------
    def test_iw_del_returns_verified_bool(self):
        k = FakeKernel({"ldnclient"}, root=True)
        tmod._run = k.run
        tmod._iface_exists = k.iface_exists

        self.assertTrue(tmod._iw_del("ldn-mon"))     # never existed: goal state already met
        self.assertTrue(tmod._iw_del("ldnclient"))   # deleted for real -> True
        self.assertNotIn("ldnclient", k.netdevs)
        k.root = False
        k.netdevs.add("ldnclient")                   # leaked vif iw can no longer remove
        self.assertFalse(tmod._iw_del("ldnclient"))  # EPERM: still there -> honest False


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(FreeRadioTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_FREE_RADIO")
        sys.exit(0)
    sys.exit(1)
