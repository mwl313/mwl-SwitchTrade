"""HostTransport must not race its radio thread or leak udev-renamed vifs."""

import unittest
from unittest import mock

from frlgsim import transport


class FakeThread:
    def __init__(self, alive=False):
        self.alive = alive
        self.join_timeout = None

    def join(self, timeout=None):
        self.join_timeout = timeout

    def is_alive(self):
        return self.alive


class HostTransportCleanupTest(unittest.TestCase):
    def test_stop_waits_full_grace_then_sweeps_owned_phy(self):
        host = transport.HostTransport(phyname="phy9")
        thread = FakeThread()
        host._thread = thread

        with mock.patch.object(transport, "free_radio") as free_radio:
            host.stop()

        self.assertEqual(thread.join_timeout, host.THREAD_JOIN_GRACE)
        self.assertIsNone(host._thread)
        free_radio.assert_called_once_with({"phy9"}, host.log)

    def test_stop_refuses_cleanup_while_thread_is_alive(self):
        host = transport.HostTransport(phyname="phy9")
        host._thread = FakeThread(alive=True)

        with mock.patch.object(transport, "free_radio") as free_radio:
            with self.assertRaisesRegex(RuntimeError, "thread still alive"):
                host.stop()

        free_radio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
