import unittest
from unittest.mock import patch

from bridge.frlgsim.transport import LdnRoomNotFoundError, LiveTransport


class LiveTransportErrorTests(unittest.TestCase):
    def test_no_joinable_room_has_a_stable_error_type(self):
        live = LiveTransport(log=lambda _message: None)

        def no_room():
            live._err = "no joinable FRLG network (saw 0, 0 joinable)"
            live._ready.set()

        live._run_ldn = no_room
        with patch("bridge.frlgsim.transport.free_radio"), patch(
                "bridge.frlgsim.transport.light_cleanup"):
            with self.assertRaises(LdnRoomNotFoundError):
                live.start(timeout=0.1, attempts=1, settle=0)


if __name__ == "__main__":
    unittest.main()
