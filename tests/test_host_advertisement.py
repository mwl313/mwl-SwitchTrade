"""Wire-level check for the Nintendo Vendor Action advertisement used for discovery."""

import sys
import types
import unittest

from frlgsim.advert_check import issues


@unittest.skipIf(sys.version_info < (3, 12), "ldn 0.0.17 requires Python 3.12+")
class HostAdvertisementTest(unittest.TestCase):
    def test_ldn_roundtrip_preserves_frlg_identity(self):
        # fcntl is imported by ldn.wlan even though this encoder-only test never uses it.
        if sys.platform == "win32" and "fcntl" not in sys.modules:
            fcntl = types.ModuleType("fcntl")
            fcntl.ioctl = lambda *args: None
            sys.modules["fcntl"] = fcntl

        import ldn
        from ldn import wlan
        from frlgsim.beacon import build_application_data, build_pia_header
        from frlgsim.transport import HostTransport, _build_host_beacon_head

        class FakeAccessPoint:
            def address(self):
                return wlan.MACAddress("A0:47:D7:B0:2B:39")

        param = ldn.CreateNetworkParam()
        param.local_communication_id = HostTransport.LOCAL_COMMUNICATION_ID
        param.scene_id = HostTransport.SCENE_ID
        param.max_participants = HostTransport.MAX_PARTICIPANTS
        param.application_data = build_application_data(
            0x9CA7, "DESTROY", 0x1EFD,
            header=build_pia_header(player_name="Min"))
        param.app_version = HostTransport.APPLICATION_VERSION
        param.name = b"Min"
        param.channel = 6
        param.ssid = bytes(range(16))
        param.server_random = b"R" * 16

        key = b"K" * 16
        keys = ldn.KeyDerivation({}, 1, override_advertise_key=key)
        network = ldn.APNetwork(FakeAccessPoint(), object(), object(), param, keys, key)
        encoded = network.info().build_advertisement(keys).encode()

        self.assertTrue(encoded.startswith(bytes.fromhex("7f0022aa04000101")))
        decoded_frame = ldn.AdvertisementFrame(keys, 1)
        decoded_frame.decode(encoded)
        decoded = ldn.NetworkInfo(1)
        decoded.address = FakeAccessPoint().address()
        decoded.parse_advertisement(decoded_frame)

        self.assertEqual(decoded.local_communication_id, 0x01006FA0233F8000)
        self.assertEqual(decoded.scene_id, 22287)
        self.assertEqual(decoded.max_participants, 6)
        self.assertEqual(decoded.num_participants, 1)
        self.assertEqual(decoded.security_mode, ldn.SECURITY_MODE_PROD)
        self.assertEqual(decoded.application_data, param.application_data)
        self.assertEqual(issues(decoded), [])

        # The Action frame carries 16 raw bytes; the associated hidden Wi-Fi BSS uses
        # their 32-character lowercase hex representation as its SSID.
        wifi_ssid = decoded.ssid.hex().encode("ascii")
        self.assertEqual(len(wifi_ssid), 32)
        beacon = _build_host_beacon_head(
            wifi_ssid, param.channel, bytes(FakeAccessPoint().address()))
        self.assertIn(b"\x00\x20" + b"\x00" * 32, beacon)


if __name__ == "__main__":
    unittest.main(verbosity=2)
