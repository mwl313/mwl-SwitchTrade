"""P4 only: native dev/CLI + real Switch stack + stock gpSP homebrew.

Process/menu ownership belongs to this isolated qualification harness, never
the product. Reuse the existing LDN OS boundary, not fake sessions/simulations.
"""
import asyncio
import base64
import json
from collections import deque
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bridge"))
from bridge.frlgsim.beacon import build_application_data
from relay.core_server import create_app
from switchtrade import core_cli
from switchtrade.connection.b_stage import DirectBStage
from switchtrade.connection.stage_session import StageSession
from switchtrade.endpoints.switch_ldn.generation import build_tunnelsim
from switchtrade.endpoints.retroarch_gpsp.rfu import _gba, GBA_ACCEPT, GBA_TRANSFER
from switchtrade.endpoints.retroarch_gpsp.process import _identity, _tcp_owners, _handle, _kernel
from tests.test_switch_physical_boundary import PhysicalGameInput
from tests.virtual_ldn_os import VirtualLdnOS
from stock_reference import StockNetplayLaunch


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def resources(identity):
    """Read-only counters on an exact live process, not game-memory inspection."""
    import ctypes
    from ctypes import wintypes
    assert _identity(identity.pid) == identity, "P4_PROCESS_IDENTITY_CHANGED"
    class Counters(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD),
            *[(name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged",
                "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]]
    value = _kernel.OpenProcess(0x1000 | 0x10, False, identity.pid)
    assert value, "P4_RESOURCE_QUERY_DENIED"
    with _handle(value):
        _kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        _kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        count, memory = wintypes.DWORD(), Counters()
        memory.size = ctypes.sizeof(memory)
        assert _kernel.GetProcessHandleCount(value, ctypes.byref(count))
        assert _kernel.K32GetProcessMemoryInfo(value, ctypes.byref(memory), memory.size)
        return {"handles": count.value, "private_bytes": memory.private}


class FullStackLaunch(StockNetplayLaunch):
    def configure(self, controls, output, wait_seconds, soak_seconds):
        self.controls, self.output = controls, output
        self.wait_seconds, self.soak_seconds = wait_seconds, soak_seconds
        self.listening = threading.Event()

    def wait_listener(self, opening):
        end = time.monotonic() + 60
        while not self.listening.wait(.1):
            if opening.done():
                opening.result()
            if time.monotonic() > end:
                raise TimeoutError("P4_NATIVE_LISTENER_STARTUP")
        # Human waiting, not a patched product deadline. The actual child keeps
        # monitoring process/lease/transport while public Netplay remains idle.
        time.sleep(self.wait_seconds)

    def open(self, *, process):
        self.listener.close()
        value = FullStackProbe(self, process)
        try:
            value.call(value.open(), timeout=self.wait_seconds + 100)
            return value
        except BaseException:
            value.close()
            raise


class FullStackProbe:
    def __init__(self, launch, emulator):
        self.launch, self.emulator = launch, emulator
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="gpsp-p4-qualification")
        self.thread.start()
        self.stack = ExitStack()
        self.os = VirtualLdnOS()
        self.messages = {"host": deque(maxlen=100), "guest": deque(maxlen=100)}
        self.host = self.server = self.serving = self.guest = None
        self.sessions, self.tickers, self.simulations, self.readers = [], [], [], []
        self.result = None
        self.cleanup_errors = []
        self.observed_sims = []

    def call(self, coroutine, timeout=60):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=timeout)

    async def until(self, predicate, timeout=40):
        async with asyncio.timeout(timeout):
            while not predicate():
                self.live()
                await asyncio.sleep(.01)

    def live(self):
        assert self.emulator.poll() is None, "P4_EMULATOR_EXITED"
        for task in (self.host, *self.tickers):
            if task and task.done():
                task.result()
                raise AssertionError("P4_HOST_TASK_EXITED")
        if self.guest and self.guest.returncode is not None:
            raise AssertionError("P4_NATIVE_CLI_EXITED: " + str(list(self.messages["guest"])[-5:]))

    async def open(self):
        self.os.install(self.stack)
        from frlgsim.tunnel import TunnelSim
        init_sim = TunnelSim.__init__
        def observe_sim(sim, *args, **kwargs):
            init_sim(sim, *args, **kwargs)
            sim.test_log = deque(maxlen=40)
            sim.log = lambda *parts: sim.test_log.append(" ".join(map(str, parts)))
            sim.conn.log = sim.log
            self.observed_sims.append(sim)
        self.stack.enter_context(patch.object(TunnelSim, "__init__", observe_sim))
        proven = {"SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_P0_TARGET_CHANNEL": "6",
            "SWITCHTRADE_P0_RX_PASSED": "1", "SWITCHTRADE_PHY": "phy0",
            "SWITCHTRADE_IFACE": "proven0", "SWITCHTRADE_KEYS": "/synthetic-test.keys"}
        self.stack.enter_context(patch.object(core_cli, "os", SimpleNamespace(environ={**os.environ, **proven})))
        self.stack.enter_context(patch.object(core_cli, "print",
            lambda line, **kw: self.messages["host"].append(line), create=True))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.app = create_app()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port,
            log_level="critical", access_log=False))
        self.serving = asyncio.create_task(self.server.serve())
        await self.until(lambda: self.server.started)
        args = core_cli.parser().parse_args(["--relay", f"http://127.0.0.1:{port}",
            "--usb-id", "0bda:818b", "--log-dir", str(self.launch.output / "host-log"), "host"])
        self.host = asyncio.create_task(core_cli.run(args))
        await self.until(lambda: any(x.startswith("Pair code: ") for x in self.messages["host"]))
        code = next(x.split(": ")[1] for x in self.messages["host"] if x.startswith("Pair code: "))
        await self.room(1)
        setup = ('using System; using System.Runtime.InteropServices; public static class TestConsoleInput {'
            '[DllImport("kernel32.dll")] public static extern bool SetConsoleCtrlHandler(IntPtr p, bool add); }')
        command = [str(ROOT / "dev.ps1"), "run", "join", code, "--emulator", "gpsp",
            "--emulator-pid", str(self.emulator.pid), "--emulator-port", str(self.launch.port),
            "--relay", f"http://127.0.0.1:{port}", "--log-dir", str(self.launch.output / "native-log")]
        script = (f"Add-Type -TypeDefinition {quote(setup)}; "
            "if(-not [TestConsoleInput]::SetConsoleCtrlHandler([IntPtr]::Zero,$false)){throw 'console setup failed'}; "
            "& " + " ".join(map(quote, command)) + "; exit $LASTEXITCODE")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        environment = dict(os.environ)
        environment.pop("SWITCHTRADE_NATIVE_PYTHON", None)
        self.guest = await asyncio.create_subprocess_exec(shutil.which("pwsh"), "-NoProfile", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii"), cwd=ROOT, env=environment,
            creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def read(stream, name):
            with (self.launch.output / name).open("w", encoding="utf-8") as log:
                async for raw in stream:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    log.write(line + "\n")
                    log.flush()
                    self.messages["guest"].append(line)
                    if line.startswith("Connect RetroArch Netplay to "):
                        self.listening_at = time.monotonic()
                        self.launch.listening.set()
        self.readers = [asyncio.create_task(read(self.guest.stdout, "native-stdout.log")),
                        asyncio.create_task(read(self.guest.stderr, "native-stderr.log"))]
        await self.until(lambda: "Choose Join Group in the emulator." in self.messages["guest"],
                         timeout=self.launch.wait_seconds + 90)
        self.local_wait = time.monotonic() - self.listening_at
        self.pair_identity = set(self.app.state.core_sockets)
        assert len(self.pair_identity) == 2
        peer = next(ws for (_, seat), ws in self.app.state.core_sockets.items() if seat == "guest")
        owners = _tcp_owners(peer.client.port, port)
        assert len(owners) == 1, "P4_NATIVE_PROCESS_IDENTITY_UNPROVEN"
        self.identities = {"retroarch": _identity(self.emulator.pid), "native": _identity(owners.pop())}

    async def room(self, number):
        leader = StageSession(DirectBStage(run_id=f"gpsp-physical-{number}", release="test", phy="phy1",
            ap_ifname="test-ap", monitor_ifname="test-mon", tap_ifname="test-tap",
            keys_path="/synthetic-test.keys",
            application_data=build_application_data(0x2211, "TEST", 0x1234, b"\0\0\0\0\x04\x14")), timeout=30).start()
        self.sessions.append(leader)
        resources = await asyncio.to_thread(leader.wait_ready)
        self.game = PhysicalGameInput()
        self.game.output = deque()  # Consume continuously; no harness history leak.
        sim = build_tunnelsim(resources, self.game, True)
        self.simulations.append(sim)
        async def tick():
            while True:
                sim.tick()
                await asyncio.sleep(1 / 60)
        self.tickers.append(asyncio.create_task(tick()))

    async def expect(self, prefix):
        try:
            await self.until(lambda: bool(self.game.output), timeout=15)
        except TimeoutError:
            # Private, bounded harness evidence; never collect user game bytes.
            diagnostics = [{"parent": sim.parent, "state": sim.conn.state,
                "rx": sim.rx_count, "rx_failed": sim.rx_fail, "tx": sim.tx_count,
                "protocols": sim.rx_protos, "log": list(sim.test_log)} for sim in self.observed_sims]
            (self.launch.output / "timeout.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
            raise TimeoutError("P4_EXPECT_" + prefix.hex()) from None
        payload, flags = self.game.output.popleft()
        assert payload.startswith(prefix), (prefix, payload[:4])
        assert flags == (15 if prefix == b"J\0" else 7)
        return payload

    def exchange(self, number):
        async def exercise():
            if number == 2:
                await self.room(number)
                await self.until(lambda: self.messages["guest"].count("Choose Join Group in the emulator.") == 2)
            await self.expect(b"J\0")
            started = time.monotonic()
            if number == 1:
                while time.monotonic() - started < self.launch.wait_seconds:
                    self.live()
                    assert "Bridge active." not in self.messages["guest"]
                    await asyncio.sleep(.1)
            game_wait = time.monotonic() - started
            self.launch.controls.command("GAME_START")
            request = await self.expect(b"WC")
            self.game.press(_gba(GBA_ACCEPT, b"\x34\x12" + request[4:6] + b"\0\0"), 15)
            started, count = time.monotonic(), 0
            samples = []
            sampled_at = -60
            minimum = self.launch.soak_seconds if number == 1 else 2
            while True:
                data = await self.expect(b"WT")
                count += 1
                assert data[12:24] == struct.pack("<III", 0x53544632, number, count), "P4_RAM_COUNTER_OR_DATA_MISMATCH"
                elapsed = time.monotonic() - started
                if elapsed - sampled_at >= 60:
                    samples.append({"seconds": elapsed, **{name: resources(identity) for name, identity in self.identities.items()}})
                    sampled_at = elapsed
                    print(f"P4 round={number} exchanges={count} elapsed={elapsed:.1f}s", flush=True)
                if count > 1 and time.monotonic() - started >= minimum:
                    break  # Leave the game awaiting RFU; real radio loss ends it.
                self.game.press(_gba(GBA_TRANSFER, count.to_bytes(4, "little") + b"\x0c\0\0\0" +
                    struct.pack("<III", 0x53544832, number, count)), 7)
                await self.expect(b"WK")
                # The game's real RFU request/reply already paces this loop.
                # An extra half-second hides throughput/queue regressions.
            elapsed = time.monotonic() - started
            samples.append({"seconds": elapsed, **{name: resources(identity) for name, identity in self.identities.items()}})
            if elapsed >= 1800:
                warm = next(item for item in samples if item["seconds"] >= 60)
                for name in self.identities:
                    assert max(item[name]["handles"] for item in samples[2:]) <= warm[name]["handles"] + 8, "P4_HANDLE_GROWTH"
                    assert max(item[name]["private_bytes"] for item in samples[2:]) <= warm[name]["private_bytes"] + 16 * 1024 * 1024, "P4_MEMORY_GROWTH"
            await self.until(lambda: self.messages["guest"].count("Bridge active.") == number)
            assert set(self.app.state.core_sockets) == self.pair_identity
            self.tickers[-1].cancel()
            await asyncio.gather(self.tickers.pop(), return_exceptions=True)
            await asyncio.to_thread(self.sessions[-1].stop)
            await self.until(lambda: self.messages["guest"].count("Generation ended. Pair and local Netplay retained.") == number)
            await self.until(lambda: self.messages["host"].count("Generation ended. Pair retained.") == number)
            self.simulations[-1].close()
            self.live()
            return {"round": number, "in_ram_counter": number, "same_pair": True,
                "local_netplay_retained": True, "native_discovery_gate": True,
                "bidirectional_exchanges": count - 1,
                "real_traffic_seconds": elapsed, "game_wait_seconds": game_wait,
                "local_netplay_wait_seconds": self.local_wait, "radio_room_end": True,
                "encrypted_ldn_frames": self.os.decrypted_frames, "resource_samples": samples}
        return self.call(exercise(), timeout=self.launch.wait_seconds + self.launch.soak_seconds + 150)

    def close(self):
        if self.result is not None:
            return self.result
        async def stop():
            if self.guest and self.guest.returncode is None:
                sender = ("import ctypes,time; k=ctypes.WinDLL('kernel32',use_last_error=True); k.FreeConsole(); "
                    f"assert k.AttachConsole({self.guest.pid}),ctypes.get_last_error(); "
                    "assert k.SetConsoleCtrlHandler(None,True); assert k.GenerateConsoleCtrlEvent(0,0); "
                    "time.sleep(.3); k.FreeConsole()")
                signal = await asyncio.create_subprocess_exec(sys.executable, "-c", sender)
                assert await asyncio.wait_for(signal.wait(), 5) == 0
                assert await asyncio.wait_for(self.guest.wait(), 30) == 0, "P4_NATIVE_CLEANUP_EXIT"
            if self.guest:
                assert self.guest.returncode == 0, "P4_NATIVE_EXIT_NOT_CLEAN"
                await asyncio.gather(*self.readers)
                assert "SwitchTrade stopped. RetroArch was not closed." in self.messages["guest"]
        async def cleanup():
            try:
                await stop()
            except BaseException as error:
                self.cleanup_errors.append(type(error).__name__ + ": " + str(error))
            for task in (self.host, *self.tickers):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (self.host, *self.tickers) if t), return_exceptions=True)
            for sim in self.simulations:
                sim.close()
            for session in self.sessions:
                await asyncio.to_thread(session.stop)
            if self.server:
                self.server.should_exit = True
                await asyncio.wait_for(self.serving, 5)
            self.os.assert_clean()
            assert self.emulator.poll() is None, "P4_PRODUCT_CLOSED_EMULATOR"
            self.stack.close()
            return not self.cleanup_errors
        try:
            self.result = self.call(cleanup())
        except BaseException as error:
            self.cleanup_errors.append(type(error).__name__ + ": " + str(error))
            self.result = False
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
            self.result = self.result and not self.thread.is_alive()
            if not self.thread.is_alive():
                self.loop.close()
            if self.cleanup_errors:
                print("P4_CLEANUP: " + str(self.cleanup_errors), flush=True)
        return self.result
