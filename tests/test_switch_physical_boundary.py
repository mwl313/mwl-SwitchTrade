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
from switchtrade.endpoints.switch_ldn.driver import SwitchLdnEndpointDriver, SwitchLdnPolicy, SWITCH_LDN_PROTOCOL
from switchtrade.core.contracts import GenerationOffer
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


@pytest.mark.parametrize("interruption", [None, "burst", "active", "active-retry", "active-before-hello", "opening", "waiting"])
def test_actual_cli_relay_ldn_tunnelsim_two_generations(interruption):
    asyncio.run(qualify_two_generations(interruption))


def test_actual_mirror_readiness_survives_180_seconds_then_physical_join():
    """T15: real wall time, not a short fake StageSession or patched deadline."""
    async def exercise():
        import time
        from switchtrade.connection.b_fixture import FIXTURE
        os = VirtualLdnOS()
        with ExitStack() as stack:
            os.install(stack)
            policy = SwitchLdnPolicy(run_id="human-wait", release="test", usb_id="0bda:818b",
                hardware_profile="RTL8192EU", phy="phy2", proven_radio_iface="proven2",
                ifname="unused-sta", ap_ifname="waiting-ap", monitor_ifname="waiting-mon",
                tap_ifname="waiting-tap", keys_path="/synthetic-test.keys")
            driver = SwitchLdnEndpointDriver(policy)
            await driver.prepare()
            cancel = asyncio.Event()
            offer = GenerationOffer("long-human-wait", SWITCH_LDN_PROTOCOL, "switch_ldn", FIXTURE)
            pending = asyncio.create_task(driver.accept(offer, cancel))
            joining = None
            try:
                await eventually(lambda: any(link.type == "tap" for link in os.links.values()), tasks=(pending,))
                started = time.monotonic()
                # No global ready, fake session, timeout override, or clock patch.
                await asyncio.sleep(181)
                assert time.monotonic() - started > 180
                assert not pending.done(), "historical outer/association deadline returned"
                joining = StageSession(stage_a(3), timeout=25).start()
                await asyncio.to_thread(joining.wait_ready)
                generation = await asyncio.wait_for(pending, 25)
                assert isinstance(generation._session, StageSession)
                assert isinstance(generation._session.resources.network, ldn.APNetwork)
                assert generation._session.timeout is None
                assert generation._session.stage.association_timeout is None
                report = await generation.close("test complete")
                assert report.local_resources_released
            finally:
                cancel.set()
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                report = await driver.close()
                if joining:
                    await asyncio.to_thread(joining.stop)
                assert report.local_resources_released
            os.assert_clean()
    asyncio.run(exercise())


async def qualify_two_generations(interruption=None):
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
        if interruption in {"active-retry", "active-before-hello"}:
            # A new authenticated real stream can die while its opposite old
            # stream is still retiring. Fault the second Guest hello once;
            # require real CLI recovery and second-generation RFU afterward.
            from fastapi import WebSocket
            send_json = WebSocket.send_json
            guest_hellos = 0

            async def interrupt_resync(socket, data, *args, **kwargs):
                nonlocal guest_hellos
                if data == {"seat": "guest"}:
                    guest_hellos += 1
                    if guest_hellos == 2 and interruption == "active-before-hello":
                        await socket.close(code=1012)
                        return
                await send_json(socket, data, *args, **kwargs)
                if data == {"seat": "guest"} and guest_hellos == 2:
                    await socket.close(code=1012)

            stack.enter_context(patch.object(WebSocket, "send_json", interrupt_resync))
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

        async def tick(sim):
            while True:
                sim.tick()
                await asyncio.sleep(1 / 60)

        try:
            await eventually(lambda: any(x.startswith("Pair code: ") for x in messages["host"]), tasks=(host,))
            code = next(x.split(": ")[1] for x in messages["host"] if x.startswith("Pair code: "))
            host_offset = int(interruption == "waiting")
            if host_offset:
                # Local room ends while Internet Guest has not even joined.
                # Its actual LDN lifecycle must return the Host CLI to discovery.
                early = StageSession(stage_b(1), timeout=25).start()
                sessions.append(early)
                await eventually(lambda: "Group Leader room detected." in messages["host"], tasks=(host,))
                await asyncio.to_thread(early.wait_ready)
                await asyncio.to_thread(early.stop)
                await eventually(lambda: "Generation ended. Pair retained." in messages["host"], tasks=(host,))
            # First iteration is local-first / Internet guest late. Second is
            # guest-first / local room late, on the original CLI loops and Pair.
            for generation in range(2):
                if generation:
                    await asyncio.sleep(5.2)
                    assert not host.done() and not guest.done()
                leader = StageSession(stage_b(1), timeout=25).start()
                sessions.append(leader)
                await eventually(lambda: messages["host"].count("Group Leader room detected.") > generation + host_offset,
                                 tasks=(host,))
                parent_resources = await asyncio.to_thread(leader.wait_ready)
                parent_game = PhysicalGameInput()
                parent = build_tunnelsim(parent_resources, parent_game, True)
                simulations.append(parent)

                tickers.append(asyncio.create_task(tick(parent)))
                if guest is None:
                    await eventually(lambda: parent.conn.pia_connected, tasks=(host, *tickers))
                    before_idle = parent.rx_count
                    await asyncio.sleep(5.2)
                    assert not host.done()
                    assert parent.rx_count > before_idle, "pre-active local Pia/RTT stopped"
                    guest = asyncio.create_task(cli("guest", code))
                await eventually(lambda: any(x.ap and x.phy == 2 for x in os.links.values()), tasks=(host, guest))
                if interruption == "opening":
                    # A real server-side WebSocket loss while the actual DirectB
                    # nursery is awaiting the physical Switch, before readiness.
                    sockets = app.state.core_sockets
                    peer = next(ws for (pair_id, seat), ws in sockets.items() if seat == "guest")
                    await peer.close(code=1012)
                    results = await asyncio.wait_for(asyncio.gather(host, guest, return_exceptions=True), 20)
                    assert all(getattr(result, "code", None) in {"S_TRANSPORT_FAILED", "S_PEER_CLOSED"}
                               for result in results), results
                    assert not [link for link in os.links.values() if link.phy in {0, 2}]
                    break
                joining = StageSession(stage_a(3), timeout=25).start()
                sessions.append(joining)
                child_resources = await asyncio.to_thread(joining.wait_ready)
                child_game = PhysicalGameInput()
                child = build_tunnelsim(child_resources, child_game, False)
                simulations.append(child)
                tickers.append(asyncio.create_task(tick(child)))
                await eventually(lambda: all(messages[s].count("Bridge active.") > generation for s in messages),
                                 tasks=(host, guest))
                if generation == 0:
                    # No application RFU for longer than the transport's old
                    # timeout; actual local and relay maintenance must stay live.
                    await asyncio.sleep(5.2)
                    assert not host.done() and not guest.done()
                # Synthetic physical GBA input is encoded by the real peer-side
                # TunnelSim -> Pia/Reliable -> encrypted LDN datagrams. Nothing
                # invokes the production CoreTunnelAdapter's send_rfu()/poll().
                child_bytes = b"WJ" + bytes([generation]) + bytes(range(32))
                parent_bytes = b"WT" + bytes([generation]) + bytes(range(64))
                count = 64 if interruption == "burst" else 1
                child_packets = [(child_bytes + bytes([i]), 0x7F) for i in range(count)]
                parent_packets = [(parent_bytes + bytes([i]), 1) for i in range(count)]
                for payload, flags in child_packets:
                    child_game.press(payload, flags)
                for payload, flags in parent_packets:
                    parent_game.press(payload, flags)
                await eventually(lambda: len(parent_game.output) >= count and len(child_game.output) >= count,
                                 tasks=(host, guest, *tickers))
                assert parent_game.output == child_packets
                assert child_game.output == parent_packets
                if interruption in {"active", "active-retry", "active-before-hello"} and generation == 0:
                    sockets = app.state.core_sockets
                    old_sockets = dict(sockets)
                    peer = next(ws for (pair_id, seat), ws in sockets.items() if seat == "guest")
                    await peer.close(code=1012)
                # The physical Group Leader leaves. No supervisor lifecycle
                # method is invoked: real LDN disconnect drives both CLI loops.
                await asyncio.to_thread(leader.stop)
                await eventually(lambda: all(messages[s].count("Generation ended. Pair retained.") > generation + (host_offset if s == "host" else 0)
                                             for s in messages), tasks=(host, guest))
                if interruption in {"active", "active-retry", "active-before-hello"} and generation == 0:
                    await eventually(lambda: set(sockets) == set(old_sockets)
                                     and all(sockets[key] is not old_sockets[key] for key in old_sockets),
                                     tasks=(host, guest))
                await asyncio.to_thread(joining.stop)
                for ticker in tickers:
                    ticker.cancel()
                await asyncio.gather(*tickers, return_exceptions=True)
                tickers.clear()
            assert sum(x.startswith("Pair code: ") for x in messages["host"]) == 1
            if interruption in {"active-retry", "active-before-hello"}:
                assert guest_hellos >= 3
            if interruption != "opening":
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
