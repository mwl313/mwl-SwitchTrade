"""Actual Direct A/B, StageSession and LDN qualification at OS primitives."""

import asyncio
from contextlib import ExitStack
import threading
import queue
import socket
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import uvicorn

from tests.virtual_ldn_os import VirtualLdnOS, ldn
from switchtrade.connection.a_stage import DirectAStage
from switchtrade.connection.b_stage import DirectBStage
from switchtrade.connection.stage_session import StageSession
from switchtrade.endpoints.switch_ldn.generation import build_tunnelsim
from switchtrade import core_cli
from switchtrade.rfu_tunnel import Envelope, Kind
from relay.core_server import create_app


def stage_a(phy=0):
    return DirectAStage(run_id=f"physical-{phy}", release="test", phy=f"phy{phy}",
        ifname=f"sta-test-{phy}", keys_path="/synthetic-test.keys")


def stage_b(phy=1):
    return DirectBStage(run_id=f"physical-{phy}", release="test", phy=f"phy{phy}",
        ap_ifname=f"ap-test-{phy}", monitor_ifname=f"mon-test-{phy}",
        tap_ifname=f"tap-test-{phy}", keys_path="/synthetic-test.keys")


def test_real_ldn_authentication_and_default_data_planes():
    os = VirtualLdnOS()
    with ExitStack() as stack:
        os.install(stack)
        leader, member = StageSession(stage_b(), timeout=20), StageSession(stage_a(), timeout=20)
        try:
            leader.start()
            member.start()
            a = member.wait_ready()
            b = leader.wait_ready()
            assert isinstance(a.network, ldn.STANetwork)
            assert isinstance(b.network, ldn.APNetwork)
            assert a.advertisement == b.advertisement
            assert a.transport.host_ip == b.transport.our_ip
            assert b.transport.host_ip == a.transport.our_ip
            a.transport.send(b"kernel-to-real-AP", a.transport.host_ip)
            import time
            end = time.monotonic() + 2
            packets = []
            while not packets and time.monotonic() < end:
                packets = b.transport.recv()
                time.sleep(.005)
            assert packets == [(b"kernel-to-real-AP", a.transport.our_ip)]
        finally:
            errors = []
            for session in (member, leader):
                try:
                    session.stop()
                except BaseException as error:
                    errors.append(error)
            if errors:
                raise ExceptionGroup(str([(s.report, s._error) for s in (member, leader)]), errors)
        os.assert_clean()
        assert not any(t.name == "switchtrade-direct-stage" for t in threading.enumerate())


class PhysicalGameInput:
    """Only the physical console's opaque application input/output is synthetic."""

    def __init__(self):
        self.input = queue.Queue()
        self.output = []

    def poll(self):
        result = []
        while not self.input.empty():
            result.append(self.input.get_nowait())
        return result

    def send_rfu(self, payload, *, flags):
        self.output.append((bytes(payload), flags))

    def press(self, payload, flags=1):
        self.input.put(SimpleNamespace(kind=Kind.RFU, payload=payload, flags=flags))


async def eventually(predicate, *, tasks=(), timeout=25):
    async with asyncio.timeout(timeout):
        while not predicate():
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("CLI exited unexpectedly")
            await asyncio.sleep(.01)


def test_actual_cli_relay_ldn_tunnelsim_two_generations():
    asyncio.run(qualify_two_generations())


async def qualify_two_generations():
    os = VirtualLdnOS()
    messages = {"host": [], "guest": []}
    pc = ContextVar("physical_pc", default="host")
    observed_sims = []
    import os as real_os

    class Environment:
        def get(self, key, default=None):
            return {"SWITCHTRADE_USB_ID": "0bda:818b", "SWITCHTRADE_P0_TARGET_CHANNEL": "6",
                "SWITCHTRADE_P0_RX_PASSED": "1", "SWITCHTRADE_PHY": "phy0" if pc.get() == "host" else "phy2",
                "SWITCHTRADE_IFACE": "proven0" if pc.get() == "host" else "proven2",
                "SWITCHTRADE_KEYS": "/synthetic-test.keys"}.get(key, real_os.environ.get(key, default))

        def __contains__(self, key):
            return self.get(key) is not None

    with ExitStack() as stack:
        os.install(stack)
        from frlgsim.tunnel import TunnelSim
        init_sim = TunnelSim.__init__

        def observe_sim(self, *args, **kwargs):
            init_sim(self, *args, **kwargs)
            self.test_log = []
            self.log = lambda *parts: self.test_log.append(" ".join(map(str, parts)))
            self.conn.log = self.log
            observed_sims.append(self)

        stack.enter_context(patch.object(TunnelSim, "__init__", observe_sim))
        stack.enter_context(patch.object(core_cli, "os", SimpleNamespace(environ=Environment())))
        stack.enter_context(patch.object(core_cli, "print", lambda line, **kw: messages[pc.get()].append(line), create=True))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
            log_level="critical", access_log=False))
        serving = asyncio.create_task(server.serve())
        await eventually(lambda: server.started, tasks=(serving,))
        args = dict(relay=f"http://127.0.0.1:{port}", usb_id="0bda:818b", channel=6,
                    verbose=False, log_dir=None)

        async def cli(seat, code=None):
            pc.set(seat)
            return await core_cli.run(SimpleNamespace(**args,
                command="host" if seat == "host" else "join", code=code))

        host = asyncio.create_task(cli("host"))
        guest = None
        sessions, simulations, tickers = [], [], []
        try:
            await eventually(lambda: any(x.startswith("Pair code: ") for x in messages["host"]), tasks=(host,))
            code = next(x.split(": ")[1] for x in messages["host"] if x.startswith("Pair code: "))
            # First iteration is local-first / Internet guest late. Second is
            # guest-first / local room late, on the original CLI loops and Pair.
            for generation in range(2):
                if generation:
                    await asyncio.sleep(5.2)
                    assert not host.done() and not guest.done()
                leader = StageSession(stage_b(1), timeout=25).start()
                sessions.append(leader)
                await eventually(lambda: messages["host"].count("Group Leader room detected.") > generation,
                                 tasks=(host,))
                parent_resources = await asyncio.to_thread(leader.wait_ready)
                parent_game = PhysicalGameInput()
                parent = build_tunnelsim(parent_resources, parent_game, True)
                simulations.append(parent)

                async def tick(sim):
                    while True:
                        sim.tick()
                        await asyncio.sleep(1 / 60)

                tickers.append(asyncio.create_task(tick(parent)))
                if guest is None:
                    await eventually(lambda: parent.conn.pia_connected, tasks=(host, *tickers))
                    before_idle = parent.rx_count
                    await asyncio.sleep(5.2)
                    assert not host.done()
                    assert parent.rx_count > before_idle, "pre-active local Pia/RTT stopped"
                    guest = asyncio.create_task(cli("guest", code))
                await eventually(lambda: any(x.ap and x.phy == 2 for x in os.links.values()), tasks=(host, guest))
                joining = StageSession(stage_a(3), timeout=25).start()
                sessions.append(joining)
                child_resources = await asyncio.to_thread(joining.wait_ready)
                child_game = PhysicalGameInput()
                child = build_tunnelsim(child_resources, child_game, False)
                simulations.append(child)
                tickers.append(asyncio.create_task(tick(child)))
                await eventually(lambda: all(messages[s].count("Bridge active.") > generation for s in messages),
                                 tasks=(host, guest))
                # Synthetic physical GBA input is encoded by the real peer-side
                # TunnelSim -> Pia/Reliable -> encrypted LDN datagrams. Nothing
                # invokes the production CoreTunnelAdapter's send_rfu()/poll().
                child_bytes = b"WJ" + bytes([generation]) + bytes(range(32))
                parent_bytes = b"WT" + bytes([generation]) + bytes(range(64))
                child_game.press(child_bytes, 0x7F)
                parent_game.press(parent_bytes, 0x01)
                await eventually(lambda: (child_bytes, 0x7F) in parent_game.output
                                 and (parent_bytes, 1) in child_game.output,
                                 tasks=(host, guest, *tickers))
                assert parent_game.output == [(child_bytes, 0x7F)]
                assert child_game.output == [(parent_bytes, 1)]
                # The physical Group Leader leaves. No supervisor lifecycle
                # method is invoked: real LDN disconnect drives both CLI loops.
                await asyncio.to_thread(leader.stop)
                await eventually(lambda: all(messages[s].count("Generation ended. Pair retained.") > generation
                                             for s in messages), tasks=(host, guest))
                await asyncio.to_thread(joining.stop)
                for ticker in tickers:
                    ticker.cancel()
                await asyncio.gather(*tickers, return_exceptions=True)
                tickers.clear()
            assert sum(x.startswith("Pair code: ") for x in messages["host"]) == 1
            assert os.udp_sent > 10 and os.decrypted_frames > 5
        except BaseException as error:
            error.add_note(str(messages))
            error.add_note(str([(s.report, repr(s._error)) for s in sessions]))
            error.add_note(str([(s.parent, s.rx_count, s.rx_fail, s.test_log[-15:]) for s in observed_sims]))
            error.add_note(str((os.udp_sent, os.radio_frames, os.decrypted_frames)))
            raise
        finally:
            for task in (host, guest, *tickers):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (host, guest, *tickers) if t), return_exceptions=True)
            for sim in simulations:
                sim.close()
            for session in sessions:
                await asyncio.to_thread(session.stop)
            server.should_exit = True
            await asyncio.wait_for(serving, 3)
        os.assert_clean()
        assert not any(t.name.startswith("switchtrade-") for t in threading.enumerate())
