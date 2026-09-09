"""Bounded stock Netplay v7 connection, independent of RFU Generation lifetime.

The wire layout/handshake is selectively ported from fbd2776's stock_netplay.
No launch, config, content, Room, WSL, or installer behavior is carried over.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import socket
import struct

from switchtrade.core.contracts import CleanupReport
from .errors import GpspError
from .process import ProcessObserver

MAGIC = 0x52414E50
PROTOCOL = 7
DISCONNECT, NICK, INFO, SYNC, PLAY, MODE = 2, 0x20, 0x22, 0x23, 0x25, 0x26
NETPACKET, PING, PONG = 0x48, 0x1100, 0x1101
CORE_NAME, CORE_PROTOCOL = b"gpSP", b"gpSP v1.0"
MAX_PACKET = 104
MAX_QUEUE = 256


@dataclass(frozen=True)
class CorePacket:
    payload: bytes
    peer_id: int
    sequence: int


def _field(value):
    return value.ljust(32, b"\0")


def _cstring(value):
    # Stock strlcpy terminates strings but does not zero the rest of the field.
    if b"\0" not in value:
        raise GpspError("EMULATOR_HANDSHAKE_INVALID", "RetroArch 통신 문자열이 잘못됐습니다.")
    return value.split(b"\0", 1)[0]


def _impl_magic():
    version = b"1.22.2"
    result = PROTOCOL << (len(version) & 15)
    for index, byte in enumerate(version):
        result ^= byte << (index & 15)
    return result


class LocalNetplay:
    def __init__(self, observer: ProcessObserver, port: int = 55435, *, handshake_timeout: float = 10):
        if type(port) is not int or not 1 <= port <= 65535 or handshake_timeout <= 0:
            raise GpspError("EMULATOR_PORT_INVALID", "올바른 --emulator-port를 지정하세요.")
        self.observer, self.port = observer, port
        self.handshake_timeout = handshake_timeout
        self._listener = self._socket = self._reader = self._writer = None
        self._watch = self._pump = self._opening = self._closing = None
        self._failure: BaseException | None = None
        self._ended = asyncio.Event()
        self.listening = asyncio.Event()
        self._packets = asyncio.Queue(MAX_QUEUE)
        self._send_lock, self._barrier_lock = asyncio.Lock(), asyncio.Lock()
        self._pongs = deque()
        self._sequence = 0
        self.connected = False

    @property
    def failure(self):
        return self._failure

    def _failed(self, error):
        if self._failure is None:
            self._failure = error
        self._ended.set()

    def _check(self):
        if self._failure is not None:
            raise self._failure
        if self._closing is not None or self._ended.is_set():
            raise GpspError("EMULATOR_NETPLAY_CLOSED", "로컬 Netplay 연결이 종료됐습니다. RetroArch에서 다시 연결하세요.")

    async def _observe(self):
        try:
            while True:
                self.observer.check()
                await asyncio.sleep(.25)  # Observation cadence, not a readiness deadline.
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._failed(error)

    async def _race(self, operation, cancel: asyncio.Event | None = None):
        task = asyncio.ensure_future(operation)
        stopped = asyncio.create_task(self._ended.wait())
        cancelled = asyncio.create_task(cancel.wait()) if cancel is not None else None
        tasks = [task, stopped] + ([cancelled] if cancelled is not None else [])
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if self._failure is not None:
                raise self._failure
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            self._check()
            return await task
        finally:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def open(self, cancel: asyncio.Event):
        self._check()
        if self.connected:
            self.observer.check()
            return
        if self._watch is not None:
            raise GpspError("EMULATOR_OPEN_IN_PROGRESS", "로컬 Netplay 연결을 이미 기다리고 있습니다.")
        self.observer.check()
        self._watch = asyncio.create_task(self._observe(), name="gpsp-process-observer")
        try:
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                self._listener.bind(("127.0.0.1", self.port))
            except OSError as error:
                raise GpspError("EMULATOR_PORT_UNAVAILABLE", "로컬 Netplay 포트가 사용 중입니다. 다른 프로그램을 확인하거나 --emulator-port를 지정하세요.") from error
            self._listener.listen(1)
            self._listener.setblocking(False)
            self.listening.set()
            self._opening = asyncio.create_task(self._establish(), name="gpsp-netplay-handshake")
            await self._race(self._opening, cancel)
            self.connected = True
            self._pump = asyncio.create_task(self._read_loop(), name="gpsp-netplay-reader")
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                self._failed(error)
            await self.close()
            raise

    async def _establish(self):
        # The accept wait has no human timeout; its owner observes cancellation,
        # process death and external Pair/transport failure throughout.
        self._socket, address = await asyncio.get_running_loop().sock_accept(self._listener)
        if address[0] != "127.0.0.1":
            raise GpspError("EMULATOR_LOOPBACK_REQUIRED", "로컬 RetroArch 연결만 허용합니다.")
        self.observer.check_connection(address[1], self.port)
        self._reader, self._writer = await asyncio.open_connection(sock=self._socket, limit=512)
        self._writer.transport.set_write_buffer_limits(high=16384, low=4096)
        try:
            async with asyncio.timeout(self.handshake_timeout):
                await self._handshake()
        except TimeoutError as error:
            raise GpspError("EMULATOR_HANDSHAKE_TIMEOUT", "RetroArch의 통신 규격 확인이 끝나지 않았습니다. 로컬 연결과 코어를 확인하세요.") from error

    async def _read(self, size):
        try:
            return await self._reader.readexactly(size)
        except (asyncio.IncompleteReadError, OSError) as error:
            raise GpspError("EMULATOR_NETPLAY_CLOSED", "RetroArch의 로컬 Netplay 연결이 종료됐습니다.") from error

    async def _write(self, value):
        self._check()
        async with self._send_lock:
            self._check()
            try:
                async with asyncio.timeout(self.handshake_timeout):
                    self._writer.write(value)
                    await self._writer.drain()
            except TimeoutError as error:
                failure = GpspError("EMULATOR_SEND_TIMEOUT", "로컬 Netplay 전송이 멈췄습니다. RetroArch 연결 상태를 확인하세요.")
                self._failed(failure)
                raise failure from error
            except (OSError, ConnectionError) as error:
                failure = GpspError("EMULATOR_SEND_FAILED", "RetroArch로 데이터를 전달하지 못했습니다.")
                self._failed(failure)
                raise failure from error

    async def _command(self, kind, payload):
        await self._write(struct.pack("!II", kind, len(payload)) + payload)

    async def _expect(self, kind, size):
        received = struct.unpack("!II", await self._read(8))
        if received != (kind, size):
            raise GpspError("EMULATOR_HANDSHAKE_INVALID", "RetroArch가 지원하지 않는 통신 응답을 보냈습니다.")
        return await self._read(size)

    async def _handshake(self):
        header = struct.unpack("!6I", await self._read(24))
        # Stock clients put the highest version in the old salt word (3),
        # and the lowest offered version in word 4, not the other way around.
        if header[0] != MAGIC or not header[4] <= PROTOCOL <= header[3] or header[5] != _impl_magic():
            raise GpspError("EMULATOR_NETPLAY_PROTOCOL_MISMATCH", "지원하는 RetroArch 통신 버전이 아닙니다.")
        await self._write(struct.pack("!6I", MAGIC, header[1], 0, 0, PROTOCOL, _impl_magic()))
        nickname = _field(_cstring(await self._expect(NICK, 32)))
        await self._command(NICK, _field(b"SwitchTrade"))
        await self._command(INFO, struct.pack("!I", 0) + _field(CORE_NAME) + _field(CORE_PROTOCOL))
        info = await self._expect(INFO, 68)
        if _cstring(info[4:36]).lower() != CORE_NAME.lower() or _cstring(info[36:]) != CORE_PROTOCOL:
            raise GpspError("EMULATOR_CORE_PROTOCOL_MISMATCH", "RetroArch에서 지원하는 gpSP 코어를 선택하세요.")
        sync = struct.pack("!II", 0, 1) + b"\0" * 144 + nickname
        await self._command(SYNC, sync)
        await self._expect(PLAY, 4)
        await self._command(MODE, struct.pack("!III", 0, 0xC0000001, 0) + b"\0" * 16 + nickname)

    async def _read_loop(self):
        try:
            while True:
                kind, size = struct.unpack("!II", await self._read(8))
                if kind == NETPACKET:
                    if not 12 <= size <= MAX_PACKET:
                        raise GpspError("EMULATOR_PACKET_LENGTH", "gpSP 통신 패킷 길이가 잘못됐습니다.")
                    peer = struct.unpack("!I", await self._read(4))[0]
                    if peer not in (0, 0xFFFF):
                        raise GpspError("EMULATOR_PACKET_PEER", "gpSP 통신 상대가 잘못됐습니다.")
                    payload = await self._read(size)
                    self._sequence += 1
                    packet = CorePacket(payload, 1, self._sequence)
                    if self._packets.full():
                        # Backpressure reaches TCP; process death/close still
                        # interrupts this wait through the independent observer.
                        await self._race(self._packets.put(packet))
                    else:
                        self._packets.put_nowait(packet)
                elif kind == PING and size == 0:
                    await self._command(PONG, b"")
                elif kind == PONG and size == 0 and self._pongs:
                    future = self._pongs.popleft()
                    if not future.done():
                        future.set_result(None)
                elif kind == DISCONNECT and size == 0:
                    raise GpspError("EMULATOR_NETPLAY_CLOSED", "RetroArch에서 Netplay 연결을 종료했습니다.")
                else:
                    # Reject the header before reading any attacker-sized body.
                    raise GpspError("EMULATOR_PACKET_COMMAND", "gpSP가 지원하지 않는 통신 명령을 보냈습니다.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._failed(error)

    async def send(self, payload: bytes, *, peer_id: int = 0):
        self._check()
        if not self.connected:
            raise GpspError("EMULATOR_NOT_CONNECTED", "RetroArch에서 로컬 Netplay 대상으로 연결하세요.")
        if not 12 <= len(payload) <= MAX_PACKET or peer_id not in (0, 0xFFFF):
            raise GpspError("EMULATOR_SEND_INVALID", "gpSP 송신 패킷이 잘못됐습니다.")
        # NETPACKET size excludes the extra peer ID word in stock v7.
        await self._write(struct.pack("!III", NETPACKET, len(payload), peer_id) + payload)

    async def receive(self):
        self._check()
        if not self._packets.empty():
            return self._packets.get_nowait()
        return await self._race(self._packets.get())

    async def barrier(self):
        """Ordered Netplay processing barrier; not game RFU ACK/readiness proof."""
        async with self._barrier_lock:
            self._check()
            future = asyncio.get_running_loop().create_future()
            self._pongs.append(future)
            await self._command(PING, b"")
            async def wait():
                async with asyncio.timeout(self.handshake_timeout):
                    await future
            try:
                await self._race(wait())
            except TimeoutError as error:
                failure = GpspError("EMULATOR_DRAIN_UNPROVEN", "로컬 통신 정리를 확인하지 못했습니다. 새 방 연결을 중단합니다.")
                self._failed(failure)
                raise failure from error

    def drain(self):
        drained = []
        while not self._packets.empty():
            drained.append(self._packets.get_nowait())
        return drained

    async def wait_ended(self):
        await self._ended.wait()
        self._check()

    async def close(self):
        # One sticky result owns completion even if callers cancel/retry close.
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(), name="gpsp-netplay-cleanup")
        while True:
            try:
                return await asyncio.shield(self._closing)
            except asyncio.CancelledError:
                if self._closing.cancelled():
                    raise

    async def _close(self):
        self.connected = False
        self._ended.set()
        tasks = [t for t in (self._watch, self._pump, self._opening) if t is not None]
        errors = []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), 5)
            except Exception as error:
                errors.append(type(error).__name__)
        for resource in (self._socket, self._listener):
            if resource is not None:
                try:
                    resource.close()
                except OSError as error:
                    errors.append(type(error).__name__)
        for future in self._pongs:
            future.cancel()
        self._pongs.clear()
        self.drain()
        return CleanupReport(not errors, not errors, not errors, {"cleanup_errors": tuple(errors)})
