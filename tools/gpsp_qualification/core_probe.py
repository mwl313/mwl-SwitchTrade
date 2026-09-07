"""P2 harness: real Core/relay/gpSP endpoint; modeled Switch local boundary.

This is deliberately NOT P4's real Direct A/StageSession/TunnelSim qualification.
Reuse the isolated P0 public-menu process owner; the product owns no process.
"""
import asyncio
import json
import queue
import socket
import struct
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import uvicorn
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bridge"))

from bridge.frlgsim.beacon import build_application_data
from relay.core_server import create_app
from switchtrade.core.contracts import CleanupReport, GenerationOffer, EndpointKind, LinkPacket, PairCredentials, PairSeat
from switchtrade.core.supervisor import CoreSupervisor, SupervisorState
from switchtrade.endpoints.retroarch_gpsp.driver import RetroArchGpspEndpointDriver, PROTOCOL, clean
from switchtrade.endpoints.retroarch_gpsp.process import ProcessObserver
from switchtrade.endpoints.retroarch_gpsp.rfu import _gba, GBA_ACCEPT, GBA_TRANSFER
from switchtrade.transport import WireClient
from production_probe import ProbeConnection
from stock_reference import StockNetplayLaunch


class Origin:
    """Modeled Switch packet boundary, explicitly outside P2 qualification."""
    async def prepare(self):
        pass

    async def discover(self, cancel):
        return self

    async def receive(self):
        return await self.outgoing.get()

    async def send(self, packet):
        await self.incoming.put(packet)

    async def close(self, outcome="closed"):
        return CleanupReport(True, True, True)

    def start(self, number):
        self.offer = GenerationOffer(f"gpsp-core-{number}", PROTOCOL, EndpointKind.SWITCH_LDN,
            build_application_data(0x2211, "TEST", 0x1234, b"\x01"))
        self.incoming, self.outgoing = asyncio.Queue(), asyncio.Queue()

    async def expect(self, prefix):
        packet = await asyncio.wait_for(self.incoming.get(), 5)
        assert packet.payload.startswith(prefix), (prefix.hex(), packet.payload.hex())
        return packet.payload

    async def inject(self, payload):
        await self.outgoing.put(LinkPacket(self.offer.generation_id, PROTOCOL, payload, 7))


class CoreProbeLaunch(StockNetplayLaunch):
    def open(self, *, process):
        self.listener.close()
        value = CoreProbe(ProcessObserver.select(process.pid), self.port)
        try:
            value.call(value.open())
            return value
        except BaseException:
            value.close()
            raise


class CoreProbe:
    call = ProbeConnection.call

    def __init__(self, observer, port):
        self.loop = asyncio.new_event_loop()
        self.driver = RetroArchGpspEndpointDriver(observer=observer, port=port)
        self.thread = threading.Thread(target=self.loop.run_forever, name="gpsp-p2-core-probe")
        self.thread.start()
        self.origin = Origin()
        self.server = self.server_task = self.host = self.guest = None
        self.wires = []
        self.result = None

    async def open(self):
        await self.driver.prepare()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port,
            log_level="critical", access_log=False))
        self.server_task = asyncio.create_task(self.server.serve())
        async with asyncio.timeout(5):
            while not self.server.started:
                await asyncio.sleep(.01)
        async def post(path, value):
            def request():
                with urlopen(Request(f"http://127.0.0.1:{port}{path}", json.dumps(value).encode(),
                    {"content-type": "application/json"}), timeout=5) as response:
                    return json.loads(response.read())
            return await asyncio.to_thread(request)
        capabilities = {"endpoint_kind": "switch_ldn", "runtime_kind": "managed_wsl",
            "protocols": [PROTOCOL], "generation_roles": ["origin"]}
        host = await post("/core/v1/pairs", {"capabilities": capabilities})
        guest = await post("/core/v1/pairs:join", {"code": host["code"], "capabilities": {
            **capabilities, "endpoint_kind": "retroarch_gpsp", "runtime_kind": "native", "generation_roles": ["mirror"]}})
        supervisors = []
        for data, seat, driver in ((host, PairSeat.HOST, self.origin), (guest, PairSeat.GUEST, self.driver)):
            credentials = PairCredentials(data["pair_id"], seat, data["access_token"], data["reconnect_expires_at"])
            wire = WireClient(seat)
            self.wires.append(wire)
            connection = await websockets.connect(f"ws://127.0.0.1:{port}/core/v1/pairs/{data['pair_id']}/ws",
                additional_headers={"authorization": f"Bearer {data['access_token']}"}, proxy=None)
            assert json.loads(await connection.recv()) == {"seat": seat.value}
            await wire.connect(connection)
            supervisors.append(CoreSupervisor(credentials, driver, wire))
        self.host, self.guest = supervisors
        await self.driver._wait(self.driver._ready.wait())

    def exchange(self, number):
        async def exchange():
            self.origin.start(number)
            await asyncio.gather(self.host.offer_generation(), self.guest.accept_next_offer())
            await self.origin.expect(b"J\0")
            request = await self.origin.expect(b"WC")
            child = request[4:6]
            await self.origin.inject(_gba(GBA_ACCEPT, b"\x34\x12" + child + b"\0\0"))
            data = await self.origin.expect(b"WT")
            assert data[12:20] == struct.pack("<II", 0x53544631, number), "P2_RAM_COUNTER_OR_DATA_MISMATCH"
            await self.origin.inject(_gba(GBA_TRANSFER, number.to_bytes(4, "little") + b"\x08\0\0\0" +
                struct.pack("<II", 0x53544831, number)))
            await self.origin.expect(b"WK")
            await self.origin.expect(b"WD")
            await asyncio.gather(self.host.wait_generation_end(), self.guest.wait_generation_end())
            assert self.host.state == self.guest.state == SupervisorState.PAIRED
            assert self.driver.local.connected and self.driver.rfu_mode_verified
            assert self.host.credentials.pair_id == self.guest.credentials.pair_id
            return {"round": number, "rfu": "bidirectional-via-real-Core-relay",
                "in_ram_counter": number, "same_pair": True, "local_netplay_retained": True}
        return self.call(exchange())

    def close(self):
        if self.result is not None:
            return self.result
        async def stop():
            results = await asyncio.gather(*(owner.stop() for owner in (self.host, self.guest) if owner is not None),
                return_exceptions=True)
            report = await self.driver.close()
            await asyncio.gather(*(wire.close() for wire in self.wires))
            if self.server is not None:
                self.server.should_exit = True
                await self.server_task
            return clean(report) and not any(isinstance(value, BaseException) for value in results)
        try:
            self.result = self.call(stop())
        except Exception:
            self.result = False
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
            if self.thread.is_alive():
                self.result = False
            else:
                self.loop.close()
        return self.result
