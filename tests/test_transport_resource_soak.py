"""Bounded-resource soak for the production RFU relay path (no radio required)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import gc
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relay.authority import uuid7
from switchtrade.relay_client import RelayClient
from switchtrade.rfu_tunnel import Kind
from switchtrade.tunnel_client import TunnelClient


FRAMES_PER_DIRECTION = 4096
BATCH_SIZE = 32
QUEUE_CAPACITY = 128
MAX_RSS_GROWTH = 64 * 1024 * 1024
MAX_LOG_BYTES = 128 * 1024


@dataclass(frozen=True)
class ProcessSample:
    rss: int | None
    threads: int | None
    descriptors: int | None
    sockets: int | None


def _linux_sample(pid: int) -> ProcessSample:
    status = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    fd_dir = Path(f"/proc/{pid}/fd")
    descriptors = list(fd_dir.iterdir())
    sockets = 0
    for descriptor in descriptors:
        try:
            sockets += os.readlink(descriptor).startswith("socket:")
        except OSError:
            pass
    return ProcessSample(
        int(status["VmRSS"].split()[0]) * 1024,
        int(status["Threads"]), len(descriptors), sockets,
    )


def _windows_sample(pid: int) -> ProcessSample:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessHandleCount.argtypes = (wintypes.HANDLE,
                                               ctypes.POINTER(wintypes.DWORD))
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x0400, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    class ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32.Thread32First.argtypes = (wintypes.HANDLE,
                                       ctypes.POINTER(ThreadEntry32))
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = (wintypes.HANDLE,
                                      ctypes.POINTER(ThreadEntry32))
    kernel32.Thread32Next.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        handle_count = wintypes.DWORD()
        if not kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count)):
            raise ctypes.WinError(ctypes.get_last_error())

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            threads = 0
            more = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                threads += entry.th32OwnerProcessID == pid
                more = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return ProcessSample(counters.WorkingSetSize, threads, handle_count.value, None)
    finally:
        kernel32.CloseHandle(handle)


def _sample(pid: int) -> ProcessSample:
    if sys.platform.startswith("linux"):
        return _linux_sample(pid)
    if os.name == "nt":
        return _windows_sample(pid)
    return ProcessSample(None, None, None, None)


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _payload(direction: bytes, sequence: int) -> bytes:
    header = struct.pack(">cI", direction, sequence)
    return header + bytes((sequence + direction[0] + 17 * offset) & 0xFF
                          for offset in range(507))


def _metric_max(samples: list[ProcessSample], field: str) -> int | None:
    values = [getattr(sample, field) for sample in samples
              if getattr(sample, field) is not None]
    return max(values) if values else None


class ProductionTransportSoakTest(unittest.TestCase):
    def test_bidirectional_opaque_rfu_soak_has_bounded_resources_and_logs(self):
        port = _port()
        base = f"http://127.0.0.1:{port}"
        relay_logs: Path | None = None
        relay_log = None
        proc = None
        host = guest = None
        client_logs: list[str] = []
        failure_context = ""
        with tempfile.TemporaryDirectory() as state:
            state_path = Path(state)
            relay_logs = state_path / "relay.log"
            relay_log = relay_logs.open("w+", encoding="utf-8")
            environment = dict(os.environ)
            environment["SWITCHTRADE_AUTH_DB"] = str(state_path / "authority.sqlite3")
            environment.pop("SWITCHTRADE_ENABLE_LEGACY_RELAY", None)
            environment["SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN"] = "1"
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "relay.server:app", "--host",
                 "127.0.0.1", "--port", str(port), "--log-level", "info",
                 "--no-access-log"],
                cwd=ROOT, env=environment, stdout=relay_log, stderr=relay_log,
            )
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        relay_log.flush()
                        raise AssertionError(f"relay exited during startup:\n{relay_logs.read_text()}")
                    try:
                        with urlopen(f"{base}/health", timeout=0.2) as response:
                            health = json.load(response)
                        break
                    except OSError:
                        time.sleep(0.05)
                else:
                    raise AssertionError("production relay did not become ready in 10 seconds")
                self.assertEqual(
                    (health["status"], health["payload_mode"], health["rfu_contract"]),
                    ("ready", "opaque", "rfu-tunnel.v1"),
                )
                with self.assertRaises(HTTPError) as legacy:
                    urlopen(Request(f"{base}/session/create", method="POST"), timeout=5)
                self.assertEqual(legacy.exception.code, 404)

                relay = RelayClient(base)
                first = relay.create_trade_room({
                    "name": "Resource soak", "visibility": "private",
                    "trainer_display_name": "Soak A", "game": "FireRed",
                    "language": "English",
                }, "resource-soak-a")
                second = relay.join_trade_room(
                    first["room"]["room_code"], "Soak B", "resource-soak-b")
                room_id = first["room"]["room_id"]
                for credential, role in ((first, "creator"), (second, "finder")):
                    room = relay.room(room_id, credential["member_token"])
                    relay.room_command(
                        room_id, credential["member_token"], "/ready",
                        {"ready": True, "switch_room_role": role},
                        expected_version=room["room_version"],
                    )
                room = relay.room(room_id, first["member_token"])
                room = relay.room_command(
                    room_id, first["member_token"], "/attempts",
                    expected_version=room["room_version"],
                )
                attempt_id = room["attempt"]["attempt_id"]
                sid = first["room"]["room_code"]

                relay_startup_baseline = _sample(proc.pid)
                client_startup_baseline = _sample(os.getpid())
                queue_high_water = {"host_out": 0, "host_in": 0,
                                    "guest_out": 0, "guest_in": 0}

                host = TunnelClient(
                    base, sid, "host", capacity=QUEUE_CAPACITY,
                    heartbeat_interval=1, member_token=first["member_token"],
                    attempt_id=attempt_id, log=client_logs.append,
                ).start()
                guest = TunnelClient(
                    base, sid, "guest", capacity=QUEUE_CAPACITY,
                    heartbeat_interval=1, member_token=second["member_token"],
                    attempt_id=attempt_id, log=client_logs.append,
                ).start()
                self.assertTrue(host.wait_connected(5), host.last_error)
                self.assertTrue(guest.wait_connected(5), guest.last_error)
                time.sleep(0.05)
                host.poll()
                guest.poll()
                host_stats_baseline = dict(host.stats)
                guest_stats_baseline = dict(guest.stats)
                relay_active_baseline = _sample(proc.pid)
                client_active_baseline = _sample(os.getpid())
                relay_samples = [relay_active_baseline]
                client_samples = [client_active_baseline]

                for start in range(0, FRAMES_PER_DIRECTION, BATCH_SIZE):
                    count = min(BATCH_SIZE, FRAMES_PER_DIRECTION - start)
                    expected_hg = [_payload(b"H", sequence)
                                   for sequence in range(start, start + count)]
                    expected_gh = [_payload(b"G", sequence)
                                   for sequence in range(start, start + count)]
                    for host_payload, guest_payload in zip(expected_hg, expected_gh):
                        host.send(host_payload)
                        guest.send(guest_payload)
                    queue_high_water["host_out"] = max(
                        queue_high_water["host_out"], host._outbox.qsize())
                    queue_high_water["guest_out"] = max(
                        queue_high_water["guest_out"], guest._outbox.qsize())

                    received_hg: list[bytes] = []
                    received_gh: list[bytes] = []
                    deadline = time.monotonic() + 5
                    while ((len(received_hg) < count or len(received_gh) < count) and
                           time.monotonic() < deadline):
                        queue_high_water["host_in"] = max(
                            queue_high_water["host_in"], host._inbox.qsize())
                        queue_high_water["guest_in"] = max(
                            queue_high_water["guest_in"], guest._inbox.qsize())
                        for frame in guest.poll():
                            if frame.kind == Kind.RFU:
                                received_hg.append(frame.payload)
                        for frame in host.poll():
                            if frame.kind == Kind.RFU:
                                received_gh.append(frame.payload)
                        if len(received_hg) < count or len(received_gh) < count:
                            time.sleep(0.002)
                    self.assertEqual(received_hg, expected_hg,
                                     f"host→guest mismatch at batch {start // BATCH_SIZE}")
                    self.assertEqual(received_gh, expected_gh,
                                     f"guest→host mismatch at batch {start // BATCH_SIZE}")

                    if start % (BATCH_SIZE * 16) == 0:
                        relay_samples.append(_sample(proc.pid))
                        client_samples.append(_sample(os.getpid()))

                expected_stats = {
                    "sent": FRAMES_PER_DIRECTION, "received": FRAMES_PER_DIRECTION,
                    "reconnects": 0, "stale": 0, "invalid": 0, "dropped": 0,
                }
                self.assertEqual({key: host.stats[key] - host_stats_baseline[key]
                                  for key in host.stats}, expected_stats)
                self.assertEqual({key: guest.stats[key] - guest_stats_baseline[key]
                                  for key in guest.stats}, expected_stats)
                self.assertTrue(all(value <= QUEUE_CAPACITY
                                    for value in queue_high_water.values()), queue_high_water)
                with urlopen(f"{base}/metrics", timeout=5) as response:
                    self.assertEqual(json.load(response)["live_rfu_sessions"], 1)

                relay_peak_rss = _metric_max(relay_samples, "rss")
                client_peak_rss = _metric_max(client_samples, "rss")
                if relay_peak_rss is not None:
                    self.assertLessEqual(relay_peak_rss - relay_active_baseline.rss,
                                         MAX_RSS_GROWTH, relay_samples)
                if client_peak_rss is not None:
                    self.assertLessEqual(client_peak_rss - client_active_baseline.rss,
                                         MAX_RSS_GROWTH, client_samples)
                self.assertLessEqual(_metric_max(relay_samples, "threads") or 0,
                                     (relay_active_baseline.threads or 0) + 1, relay_samples)
                self.assertLessEqual(_metric_max(client_samples, "threads") or 0,
                                     (client_active_baseline.threads or 0) + 1, client_samples)
                self.assertLessEqual(_metric_max(relay_samples, "descriptors") or 0,
                                     (relay_active_baseline.descriptors or 0) + 4, relay_samples)
                self.assertLessEqual(_metric_max(client_samples, "descriptors") or 0,
                                     (client_active_baseline.descriptors or 0) + 4, client_samples)
                if relay_active_baseline.sockets is not None:
                    self.assertLessEqual(_metric_max(relay_samples, "sockets"),
                                         relay_active_baseline.sockets + 1, relay_samples)
                if client_active_baseline.sockets is not None:
                    self.assertLessEqual(_metric_max(client_samples, "sockets"),
                                         client_active_baseline.sockets + 1, client_samples)

                host.stop()
                guest.stop()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with urlopen(f"{base}/metrics", timeout=5) as response:
                        if json.load(response)["live_rfu_sessions"] == 0:
                            break
                    time.sleep(0.05)
                else:
                    self.fail("relay retained the RFU session after both clients stopped")
                self.assertFalse(host._thread.is_alive())
                self.assertFalse(guest._thread.is_alive())
                gc.collect()
                time.sleep(0.05)
                relay_final = _sample(proc.pid)
                client_final = _sample(os.getpid())
                if relay_startup_baseline.descriptors is not None:
                    self.assertLessEqual(relay_final.descriptors,
                                         relay_startup_baseline.descriptors + 4,
                                         (relay_startup_baseline, relay_final))
                if client_startup_baseline.descriptors is not None:
                    self.assertLessEqual(client_final.descriptors,
                                         client_startup_baseline.descriptors + 16,
                                         (client_startup_baseline, client_final))
                if relay_startup_baseline.sockets is not None:
                    self.assertLessEqual(relay_final.sockets, relay_startup_baseline.sockets,
                                         (relay_startup_baseline, relay_final))
                if client_startup_baseline.sockets is not None:
                    self.assertLessEqual(client_final.sockets, client_startup_baseline.sockets,
                                         (client_startup_baseline, client_final))
                if client_startup_baseline.threads is not None:
                    self.assertLessEqual(client_final.threads, client_startup_baseline.threads,
                                         (client_startup_baseline, client_final))
                failure_context = json.dumps({
                    "frames_each_way": FRAMES_PER_DIRECTION,
                    "queue_high_water": queue_high_water,
                    "relay_startup_baseline": relay_startup_baseline.__dict__,
                    "relay_active_baseline": relay_active_baseline.__dict__,
                    "relay_peak": {name: _metric_max(relay_samples, name)
                                   for name in relay_active_baseline.__dict__},
                    "relay_final": relay_final.__dict__,
                    "client_startup_baseline": client_startup_baseline.__dict__,
                    "client_active_baseline": client_active_baseline.__dict__,
                    "client_peak": {name: _metric_max(client_samples, name)
                                    for name in client_active_baseline.__dict__},
                    "client_final": client_final.__dict__,
                }, sort_keys=True)
            finally:
                if host is not None:
                    host.stop()
                if guest is not None:
                    guest.stop()
                if proc is not None and proc.poll() is None:
                    try:
                        urlopen(Request(f"{base}/shutdown", method="POST"), timeout=2).close()
                    except OSError:
                        proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(5)
                relay_log.flush()
                relay_log.close()

            relay_text = relay_logs.read_text(encoding="utf-8")
            client_text = "\n".join(client_logs)
            self.assertLessEqual(len(relay_text.encode()), MAX_LOG_BYTES, failure_context)
            self.assertLessEqual(len(client_text.encode()), 16 * 1024, failure_context)
            secrets = [first["member_token"], first["reconnect_token"],
                       second["member_token"], second["reconnect_token"]]
            for secret in secrets:
                self.assertNotIn(secret, relay_text)
                self.assertNotIn(secret, client_text)
            self.assertNotIn("Authorization", relay_text)
            self.assertNotIn(_payload(b"H", 0).hex(), relay_text)


if __name__ == "__main__":
    unittest.main()
