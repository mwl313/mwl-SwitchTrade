"""Offline relay integration test.

Starts relay/server.py with uvicorn in a subprocess, then exercises the
RemoteTransport remote channel (no LiveTransport.start(), i.e. no LDN radio):

  1. relay/server.py launched via uvicorn (subprocess)
  2. two RemoteTransport instances (host / guest) - remote channel only
  3. host.remote_send(TRADE_SELECT, slot=2) -> guest.remote_poll() == (0x01, b"\\x02")
  4. guest -> host round-trip (bidirectional)
  5. HEARTBEAT (0x04) and STATE_SYNC (0x10) transmit/receive
  6. relay session create/join API via the Python standard library (3rd join -> 409)

Run:  .venv/bin/python tests/test_relay_offline.py
"""

import os
import socket
import struct
import subprocess
import sys
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = next(
    (str(parent) for parent in Path(__file__).resolve().parents
     if (parent / "relay" / "server.py").is_file()),
    os.path.abspath(os.path.join(EMU_ROOT, "..")),
)  # MWL-SwitchTrade/ production checkout
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, EMU_ROOT)

import websockets.sync.client as ws_sync

from frlgsim.transport import RemoteTransport

TRADE_SELECT = RemoteTransport.MSG_TRADE_SELECT       # 0x01
STATE_SYNC = RemoteTransport.MSG_STATE_SYNC           # 0x10
HEARTBEAT = RemoteTransport.MSG_HEARTBEAT             # 0x04


def _quiet(*args, **kwargs):
    pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RelayOfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.http = f"http://127.0.0.1:{cls.port}"
        cls.ws = f"ws://127.0.0.1:{cls.port}"
        environment = dict(os.environ)
        environment["SWITCHTRADE_ENABLE_LEGACY_RELAY"] = "1"
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "relay.server:app",
             "--host", "127.0.0.1", "--port", str(cls.port),
             "--log-level", "warning"],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        cls._wait_server()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)
        if cls.proc.stderr:
            cls.proc.stderr.close()

    @classmethod
    def _wait_server(cls, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                err = cls.proc.stderr.read()
                raise RuntimeError(f"relay server exited early: {err}")
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("relay server did not start in time")

    # -- helpers -------------------------------------------------------------
    def _request(self, method, path):
        request = Request(f"{self.http}{path}", method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            try:
                return error.code, error.read().decode("utf-8")
            finally:
                error.close()

    def _create_session(self):
        status, body = self._request("POST", "/session/create")
        self.assertEqual(status, 200, f"session/create failed: {body}")
        import json
        return json.loads(body)["session_id"]

    def _wait_connected(self, t, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if t._ws is not None:
                return
            time.sleep(0.05)
        raise RuntimeError(f"{t.role} RemoteTransport did not connect in time")

    def _wait_inbox(self, t, n=1, timeout=5.0):
        frames = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            frames.extend(t.remote_poll())
            if len(frames) >= n:
                return frames
            time.sleep(0.05)
        return frames

    # -- 6. session create/join API ------------------------------------------
    def test_session_api_via_http(self):
        status, body = self._request("POST", "/session/create")
        self.assertEqual(status, 200)
        import json
        sid = json.loads(body)["session_id"]
        self.assertEqual(len(sid), 6)

        status, body = self._request("POST", f"/session/{sid}/join")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["participants"], 1)

        status, body = self._request("POST", f"/session/{sid}/join")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["participants"], 2)

        status, body = self._request("POST", f"/session/{sid}/join")
        self.assertEqual(status, 409, f"3rd join should be 409, got {status}: {body}")

    # -- 3/4. TRADE_SELECT + bidirectional -----------------------------------
    def test_trade_select_and_bidirectional(self):
        sid = self._create_session()
        host = RemoteTransport(relay_url=f"{self.ws}/session/{sid}/ws?role=host",
                               session_id=sid, role="host", log=_quiet)
        guest = RemoteTransport(relay_url=f"{self.ws}/session/{sid}/ws?role=guest",
                                session_id=sid, role="guest", log=_quiet)
        try:
            host.start_remote()
            guest.start_remote()
            self._wait_connected(host)
            self._wait_connected(guest)

            host.remote_send(b"\x02", TRADE_SELECT)          # slot=2
            self.assertEqual(self._wait_inbox(guest)[0], (0x01, b"\x02"))

            guest.remote_send(b"\x03", TRADE_SELECT)         # slot=3 back
            self.assertEqual(self._wait_inbox(host)[0], (0x01, b"\x03"))
        finally:
            host.stop()
            guest.stop()

    # -- 5. STATE_SYNC round-trip --------------------------------------------
    def test_state_sync_roundtrip(self):
        sid = self._create_session()
        host = RemoteTransport(relay_url=f"{self.ws}/session/{sid}/ws?role=host",
                               session_id=sid, role="host", log=_quiet)
        guest = RemoteTransport(relay_url=f"{self.ws}/session/{sid}/ws?role=guest",
                                session_id=sid, role="guest", log=_quiet)
        try:
            host.start_remote()
            guest.start_remote()
            self._wait_connected(host)
            self._wait_connected(guest)

            host.remote_send(b'{"trades": 1}', STATE_SYNC)
            self.assertEqual(self._wait_inbox(guest)[0], (0x10, b'{"trades": 1}'))

            guest.remote_send(b'{"trades": 2}', STATE_SYNC)
            self.assertEqual(self._wait_inbox(host)[0], (0x10, b'{"trades": 2}'))
        finally:
            host.stop()
            guest.stop()

    # -- 5. HEARTBEAT transmit/receive ---------------------------------------
    def test_heartbeat_transmit_receive(self):
        sid = self._create_session()
        ws_base = f"{self.ws}/session/{sid}/ws"
        guest_ws = ws_sync.connect(f"{ws_base}?role=guest")
        host = RemoteTransport(relay_url=f"{ws_base}?role=host",
                               session_id=sid, role="host", log=_quiet)
        host.HEARTBEAT_INTERVAL = 0.5                       # don't wait the real 30s
        host.start_remote()
        try:
            self._wait_connected(host)
            # host auto-emits a HEARTBEAT; the raw guest peer observes it
            data = guest_ws.recv(timeout=5.0, decode=False)
            parsed = RemoteTransport._parse_frame(data)
            self.assertIsNotNone(parsed, f"expected a MWLB frame, got {data!r}")
            msg_type, payload = parsed
            self.assertEqual(msg_type, HEARTBEAT)
            self.assertEqual(len(payload), 4)

            # a RemoteTransport swallows inbound HEARTBEATs (never surfaced)
            guest_ws.send(RemoteTransport._build_frame(HEARTBEAT, struct.pack("!I", 7)))
            time.sleep(0.6)
            self.assertEqual(list(host.remote_poll()), [])
        finally:
            host.stop()
            try:
                guest_ws.close()
            except Exception:
                pass


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(RelayOfflineTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("DONE_MARKER_4")
        sys.exit(0)
    sys.exit(1)
