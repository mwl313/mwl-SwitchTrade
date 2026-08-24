"""rtl8xxxu monitor frames may retain CCMP metadata after hardware decryption."""

import unittest

from frlgsim import transport


class MonitorCcmpCompatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        transport.install_monitor_ccmp_compat(log=lambda *_: None)
        from ldn import wlan
        cls.wlan = wlan

    @classmethod
    def _frame(cls, payload):
        header = cls.wlan.MACHeader()
        header.type = cls.wlan.IEEE80211_FTYPE_DATA
        header.flags = 0x40
        header.address1 = cls.wlan.MACAddress("ff:ff:ff:ff:ff:ff")
        header.address2 = cls.wlan.MACAddress("98:41:5c:79:41:38")
        header.address3 = cls.wlan.MACAddress("a0:47:d7:b0:2b:39")
        ccmp = b"\x01\x00\x00\x60\x00\x00\x00\x00"
        return header.encode() + ccmp + payload

    def test_retained_wrapper_plaintext_skips_second_decrypt(self):
        snap = b"\xaa\xaa\x03\x00\x00\x00\x08\x06" + bytes(range(28))
        frame = self.wlan.DataFrame()
        frame.decode(self._frame(snap + b"retMIC!!"))

        self.assertFalse(frame.protected)
        self.assertEqual(frame.payload, snap)

    def test_ciphertext_stays_on_normal_decrypt_path(self):
        ciphertext = b"not plaintext SNAP" + b"realMIC!"
        frame = self.wlan.DataFrame()
        frame.decode(self._frame(ciphertext))

        self.assertTrue(frame.protected)
        self.assertEqual(frame.payload, ciphertext)


if __name__ == "__main__":
    unittest.main()
