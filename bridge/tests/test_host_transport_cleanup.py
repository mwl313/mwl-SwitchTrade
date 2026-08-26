"""HostTransport must not race its radio thread or leak udev-renamed vifs."""

import unittest
from types import SimpleNamespace
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


class LiveTransportCleanupTest(unittest.TestCase):
    def test_stop_waits_full_grace_before_light_cleanup(self):
        client = transport.LiveTransport()
        thread = FakeThread()
        client._thread = thread

        with mock.patch.object(transport, "light_cleanup") as cleanup:
            client.stop()

        self.assertEqual(thread.join_timeout, client.THREAD_JOIN_GRACE)
        self.assertIsNone(client._thread)
        cleanup.assert_called_once_with(client.log)

    def test_stop_refuses_cleanup_while_radio_thread_is_alive(self):
        client = transport.LiveTransport()
        client._thread = FakeThread(alive=True)

        with mock.patch.object(transport, "light_cleanup") as cleanup:
            with self.assertRaisesRegex(RuntimeError, "thread still alive"):
                client.stop()

        cleanup.assert_not_called()


class LdnDestroyCompatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ldn
        cls.ldn = ldn

    def setUp(self):
        self.original = self.ldn.APNetwork._destroy_network
        transport._LDN_DESTROY_COMPAT_INSTALLED = False

    def tearDown(self):
        self.ldn.APNetwork._destroy_network = self.original
        transport._LDN_DESTROY_COMPAT_INSTALLED = False

    def _network(self, peer_connected):
        local = self.ldn.MACAddress("a0:47:d7:b0:2b:39")
        peer = self.ldn.MACAddress("98:41:5c:79:41:38")

        class Interface:
            def __init__(self):
                self.sent = []

            def address(self):
                return local

            async def send_custom_frame(self, address, frame):
                self.sent.append((address, frame))

        network = self.ldn.APNetwork.__new__(self.ldn.APNetwork)
        network._interface = Interface()
        network._network = SimpleNamespace(participants=[
            SimpleNamespace(connected=True, mac_address=local),
            SimpleNamespace(connected=peer_connected, mac_address=peer),
        ])
        return network, peer

    def test_destroy_skips_local_ap_and_departed_peer(self):
        import trio

        self.assertTrue(transport.install_ldn_destroy_compat(log=lambda *_: None))
        network, _ = self._network(peer_connected=False)
        trio.run(network._destroy_network)
        self.assertEqual(network._interface.sent, [])

    def test_destroy_still_notifies_connected_remote_peer(self):
        import trio

        transport.install_ldn_destroy_compat(log=lambda *_: None)
        network, peer = self._network(peer_connected=True)
        trio.run(network._destroy_network)
        self.assertEqual(len(network._interface.sent), 1)
        self.assertEqual(network._interface.sent[0][0], peer)


if __name__ == "__main__":
    unittest.main()
