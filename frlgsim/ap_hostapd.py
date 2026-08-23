"""HostapdApEngine — hostapd-backed AP for HOST mode (A안, docs/plan/2026-08-22).

rtl8xxxu does not start periodic beaconing from NL80211_CMD_START_AP alone (docs/19),
so the HOST path delegates AP duties to hostapd and keeps the game protocol on the
existing ldn TAP path. This module owns:

  * build_hostapd_conf()   - pure config-text builder (open or WPA2-PSK)
  * HostapdApEngine        - subprocess lifecycle + ctrl-interface UNIX socket
                             (AP-STA-CONNECTED = switch joined)

hostapd_cli wire protocol used here:
    connect to <ctrl_dir>/<ifname> UNIX socket -> send "ATTACH\n" -> expect "OK\n"
    -> unsolicited event lines follow ("<ifname>-AP-STA-CONNECTED <mac> ...").
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import tempfile
import time

from frlgsim.ap_engine import EngineNotAvailable

DEFAULT_CTRL_DIR = "/tmp/hostapd-frlg"


# ---------------------------------------------------------------------------
# pure config builder
# ---------------------------------------------------------------------------
def build_hostapd_conf(*, iface: str, ssid: str, channel: int,
                       wpa_passphrase: str | None = None,
                       ctrl_dir: str = DEFAULT_CTRL_DIR,
                       extra_opts: tuple[str, ...] = ()) -> str:
    """Render hostapd.conf text. Pure - no filesystem access.

    beacon_int=100 / dtim_period=3 match the LDN values ldn's own create_network
    uses; keep them identical so the Switch sees a familiar AP."""
    lines = [
        f"interface={iface}",
        "driver=nl80211",
        f"ssid={ssid}",
        f"channel={channel}",
        "beacon_int=100",
        "dtim_period=3",
        "auth_algs=1",                 # open system only (LDN does its own auth)
        f"ctrl_interface={ctrl_dir}",
        "logger_stdout=-1",
        "logger_stdout_level=2",
    ]
    if wpa_passphrase is not None:
        if len(wpa_passphrase) < 8:
            raise ValueError("WPA passphrase must be >= 8 chars")
        lines += [
            "wpa=2",
            f"wpa_passphrase={wpa_passphrase}",
            "wpa_key_mgmt=WPA-PSK",
            "wpa_pairwise=CCMP",
        ]
    lines.extend(extra_opts)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
class HostapdApEngine:
    """ApEngine implementation driving hostapd as a subprocess.

    join detection: attaches to hostapd's ctrl interface and waits for the
    AP-STA-CONNECTED event, resolving with the station MAC."""

    def __init__(self, *, iface: str, ssid: str, channel: int,
                 wpa_passphrase: str | None = None,
                 extra_opts: tuple[str, ...] = (),
                 ctrl_dir: str = DEFAULT_CTRL_DIR,
                 hostapd_bin: str = "hostapd", log=print):
        self.iface = iface
        self.ssid = ssid
        self.channel = channel
        self.wpa_passphrase = wpa_passphrase
        self.extra_opts = tuple(extra_opts)
        self.ctrl_dir = ctrl_dir
        self.hostapd_bin = hostapd_bin
        self._log = log

        self._proc: asyncio.subprocess.Process | None = None
        self._conf_path: str | None = None
        self._ctrl_sock_path = os.path.join(ctrl_dir, iface)
        self._attached_sock: socket.socket | None = None
        self._sta_connected: asyncio.Queue[str] = asyncio.Queue()

    # -- ApEngine contract ---------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, timeout_s: float = 15.0) -> None:
        if self.is_running:
            raise RuntimeError("engine already running")

        import shutil
        if shutil.which(self.hostapd_bin) is None:
            raise EngineNotAvailable(
                f"{self.hostapd_bin!r} not found on PATH - install it with "
                "`sudo apt-get install -y hostapd` (docs/19: required for HOST "
                "mode on rtl8xxxu cards)")

        os.makedirs(self.ctrl_dir, exist_ok=True)
        conf_text = build_hostapd_conf(
            iface=self.iface, ssid=self.ssid, channel=self.channel,
            wpa_passphrase=self.wpa_passphrase, ctrl_dir=self.ctrl_dir,
            extra_opts=self.extra_opts)
        fd, self._conf_path = tempfile.mkstemp(
            prefix="hostapd-frlg-", suffix=".conf", text=True)
        with os.fdopen(fd, "w") as f:
            f.write(conf_text)

        self._log(f"[ap-engine] starting {self.hostapd_bin} "
                  f"(iface={self.iface} ch={self.channel} "
                  f"wpa={'on' if self.wpa_passphrase else 'off'})")
        self._proc = await asyncio.create_subprocess_exec(
            self.hostapd_bin, "-dd", self._conf_path,
            stdout=asyncio.subprocess.PIPE, stderr=subprocess.STDOUT)

        await self._wait_enabled(timeout_s)
        self._attach_ctrl_socket()
        self._log("[ap-engine] hostapd AP-ENABLED - waiting for a station")

    async def wait_station(self, timeout_s: float = 120.0) -> str:
        if not self.is_running:
            raise RuntimeError("engine not running")
        loop = asyncio.get_running_loop()
        reader_task = loop.create_task(self._pump_events())
        try:
            return await asyncio.wait_for(self._sta_connected.get(),
                                          timeout=timeout_s)
        finally:
            reader_task.cancel()

    async def stop(self) -> None:
        if self._attached_sock is not None:
            try:
                self._attached_sock.close()
            except OSError:
                pass
            self._attached_sock = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._proc = None
        if self._conf_path and os.path.exists(self._conf_path):
            try:
                os.unlink(self._conf_path)
            except OSError:
                pass
            self._conf_path = None
        self._log("[ap-engine] stopped")

    async def __aenter__(self) -> "HostapdApEngine":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # -- internals ------------------------------------------------------------
    async def _wait_enabled(self, timeout_s: float) -> None:
        """Read hostapd stdout until 'AP-ENABLED' or fail on error markers."""
        assert self._proc is not None and self._proc.stdout is not None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=5.0)
            if not line:                                   # EOF = process died
                raise RuntimeError("hostapd exited before AP-ENABLED")
            text = line.decode(errors="replace")
            if "AP-ENABLED" in text:
                return
            if any(m in text for m in ("Could not configure", "driver initialization failed",
                                       "Failed to setup interface")):
                raise RuntimeError(f"hostapd failed: {text.strip()}")
        raise TimeoutError(f"no AP-ENABLED within {timeout_s}s")

    def _attach_ctrl_socket(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        client_path = os.path.join(self.ctrl_dir, f"frlg-{os.getpid()}")
        try:
            os.unlink(client_path)
        except OSError:
            pass
        sock.bind(client_path)                             # hostapd replies here
        sock.setblocking(False)
        sock.connect(self._ctrl_sock_path)
        sock.send(b"ATTACH\n")
        # ATTACH ack is best-effort; events still arrive even if we miss the OK.
        self._attached_sock = sock

    async def _pump_events(self) -> None:
        """Drain the ctrl socket, feeding AP-STA-CONNECTED into the queue."""
        loop = asyncio.get_running_loop()
        assert self._attached_sock is not None
        while True:
            data = await loop.sock_recv(self._attached_sock, 4096)
            if not data:
                await asyncio.sleep(0.05)
                continue
            for raw_line in data.decode(errors="replace").splitlines():
                line = raw_line.strip()
                # formats: "<ifname>-AP-STA-CONNECTED aa:bb:... " or
                #          "AP-STA-CONNECTED aa:bb:..."
                if "AP-STA-CONNECTED" in line:
                    mac = line.split()[-1]
                    self._log(f"[ap-engine] station connected: {mac}")
                    await self._sta_connected.put(mac)
