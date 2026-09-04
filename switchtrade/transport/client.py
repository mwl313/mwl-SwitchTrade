"""Async bounded client for the generation-bound pair wire."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from switchtrade.core.contracts import PairSeat
from switchtrade.transport.wire import Envelope, FrameKind, TransportError, WireState


class BinarySocket(Protocol):
    async def send(self, data: bytes) -> None: ...
    async def recv(self) -> bytes: ...


class WireClient:
    def __init__(self, seat: PairSeat, *, queue_limit: int = 8, send_timeout: float = 5.0) -> None:
        if queue_limit < 2 or send_timeout <= 0:
            raise ValueError("invalid wire client bound")
        self.state = WireState(seat)
        self._queue_limit, self._send_timeout = queue_limit, send_timeout
        self._outgoing: asyncio.Queue[Envelope] = asyncio.Queue(queue_limit)
        self._incoming: asyncio.Queue[Envelope] = asyncio.Queue(queue_limit)
        self._socket: BinarySocket | None = None
        self._writer: asyncio.Task[None] | None = None
        self._reader: asyncio.Task[None] | None = None
        self._failed = asyncio.Event()
        self._ready = asyncio.Event()
        self._failure: TransportError | None = None

    async def connect(self, socket: BinarySocket) -> None:
        await self.close()
        self._outgoing, self._incoming = asyncio.Queue(self._queue_limit), asyncio.Queue(self._queue_limit)
        self._failed, self._ready, self._failure, self._socket = asyncio.Event(), asyncio.Event(), None, socket
        self._writer = asyncio.create_task(self._write_loop())
        self._reader = asyncio.create_task(self._read_loop())
        for envelope in self.state.start():
            self._enqueue(envelope)

    async def wait_ready(self, timeout: float = 5.0) -> None:
        await self._wait(self._ready, timeout)

    async def send(self, kind: FrameKind, generation_id: str = "", payload: bytes = b"") -> None:
        self._raise_if_failed()
        self._enqueue(self.state.emit(kind, generation_id, payload))

    async def receive(self, timeout: float = 5.0) -> Envelope:
        self._raise_if_failed()
        get = asyncio.create_task(self._incoming.get())
        failed = asyncio.create_task(self._failed.wait())
        done, pending = await asyncio.wait((get, failed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            get.cancel()
            raise TransportError("T_RECEIVE_TIMEOUT")
        self._raise_if_failed()
        return get.result()

    async def close(self) -> None:
        tasks = tuple(task for task in (self._writer, self._reader) if task is not None)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._writer = self._reader = None
        self._socket = None

    async def run(self, connector: Callable[[], Awaitable[BinarySocket]], cancel: asyncio.Event, *, backoff_base: float = 0.1, backoff_cap: float = 1.0) -> None:
        if not 0 < backoff_base <= backoff_cap:
            raise ValueError("invalid reconnect backoff")
        attempts = 0
        try:
            while not cancel.is_set():
                try:
                    await self.connect(await connector())
                    await self._wait_for_cancel_or_failure(cancel)
                    self._raise_if_failed()
                except Exception as exc:
                    if isinstance(exc, TransportError) and exc.code == "T_AUTH_INVALID":
                        raise
                finally:
                    await self.close()
                if not cancel.is_set():
                    delay = min(backoff_base * 2 ** attempts, backoff_cap)
                    attempts += 1
                    try:
                        await asyncio.wait_for(cancel.wait(), delay)
                    except asyncio.TimeoutError:
                        pass
        finally:
            await self.close()

    def _enqueue(self, envelope: Envelope) -> None:
        try:
            self._outgoing.put_nowait(envelope)
        except asyncio.QueueFull as exc:
            raise TransportError("T_SEND_QUEUE_FULL") from exc

    async def _write_loop(self) -> None:
        try:
            while True:
                envelope = await self._outgoing.get()
                await asyncio.wait_for(self._socket.send(envelope.encode()), self._send_timeout)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            raise
        except (Exception, asyncio.TimeoutError) as exc:
            self._fail(exc)

    async def _read_loop(self) -> None:
        try:
            while True:
                raw = await self._socket.recv()  # type: ignore[union-attr]
                envelope = Envelope.decode(raw)
                replies = self.state.accept(envelope)
                for reply in replies:
                    self._enqueue(reply)
                if envelope.kind in {FrameKind.GENERATION_OFFER, FrameKind.GENERATION_ACCEPT, FrameKind.GENERATION_CLOSE, FrameKind.DATA, FrameKind.CAPABILITIES, FrameKind.PEER_CLOSE}:
                    try:
                        self._incoming.put_nowait(envelope)
                    except asyncio.QueueFull as exc:
                        raise TransportError("T_RECEIVE_QUEUE_FULL") from exc
                if self.state.ready:
                    self._ready.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _wait(self, ready: asyncio.Event, timeout: float) -> None:
        wait_ready = asyncio.create_task(ready.wait())
        wait_failed = asyncio.create_task(self._failed.wait())
        done, pending = await asyncio.wait((wait_ready, wait_failed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            raise TransportError("T_READY_TIMEOUT")
        self._raise_if_failed()

    async def _wait_for_cancel_or_failure(self, cancel: asyncio.Event) -> None:
        wait_cancel = asyncio.create_task(cancel.wait())
        wait_failure = asyncio.create_task(self._failed.wait())
        done, pending = await asyncio.wait((wait_cancel, wait_failure), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._raise_if_failed()

    def _fail(self, exc: Exception) -> None:
        if self._failure is None:
            self._failure = exc if isinstance(exc, TransportError) else TransportError("T_TRANSPORT_FAILED")
            self._failed.set()

    def _raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure
