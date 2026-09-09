"""Async bounded client for the generation-bound pair wire."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from switchtrade.core.contracts import PairSeat
from switchtrade.transport.wire import Envelope, FrameKind, TransportError, WireState


logger = logging.getLogger(__name__)


class BinarySocket(Protocol):
    async def send(self, data: bytes) -> None: ...
    async def recv(self) -> bytes: ...
    async def close(self) -> None: ...


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
        self._discarded_generation_frames = 0
        self.revision = 0
        self._changed = asyncio.Event()
        self._outgoing_space, self._incoming_space = asyncio.Event(), asyncio.Event()
        self._close_lock = asyncio.Lock()
        self._close_failure: TransportError | None = None

    @property
    def discarded_generation_frames(self) -> int:
        return self._discarded_generation_frames

    @property
    def connected(self) -> bool:
        return self._socket is not None and self._failure is None

    async def connect(self, socket: BinarySocket) -> None:
        await self.close()
        self._outgoing, self._incoming = asyncio.Queue(self._queue_limit), asyncio.Queue(self._queue_limit)
        self._outgoing_space, self._incoming_space = asyncio.Event(), asyncio.Event()
        self._failed, self._ready, self._failure, self._socket = asyncio.Event(), asyncio.Event(), None, socket
        self._discarded_generation_frames = 0
        self._writer = asyncio.create_task(self._write_loop())
        self._reader = asyncio.create_task(self._read_loop())
        for envelope in self.state.start():
            self._enqueue(envelope)

    async def wait_ready(self, timeout: float = 5.0) -> None:
        await self._wait(self._ready, timeout)

    async def wait_interrupted(self, revision: int) -> None:
        failed = asyncio.create_task(self._failed.wait())
        changed = asyncio.create_task(self._changed.wait())
        try:
            if revision == self.revision:
                await asyncio.wait((failed, changed), return_when=asyncio.FIRST_COMPLETED)
            self._raise_if_failed()
            if revision != self.revision:
                raise TransportError("T_PEER_RECONNECTED")
            # connect() may replace the failure event while this old waiter is
            # resuming. The old stream still ended; never return as healthy.
            raise TransportError("T_TRANSPORT_REPLACED")
        finally:
            for task in (failed, changed):
                task.cancel()
            await asyncio.gather(failed, changed, return_exceptions=True)

    async def send(self, kind: FrameKind, generation_id: str = "", payload: bytes = b"", flags: int = 0) -> None:
        self._raise_if_failed()
        # Validate without consuming a sequence number. Admission and emit are
        # atomic after capacity is available, including concurrent senders.
        # Close/control frames wait behind earlier DATA; none overtake or drop it.
        Envelope(kind, self.state.seat, 0, 0, generation_id, payload, flags).encode()
        if kind is FrameKind.DATA and generation_id != self.state.active_generation:
            raise TransportError("T_GENERATION_INACTIVE")
        await self._wait_for_space(self._outgoing, self._outgoing_space, "T_SEND_BACKPRESSURE_TIMEOUT")
        self._enqueue(self.state.emit(kind, generation_id, payload, flags))

    async def receive(self, timeout: float | None = None) -> Envelope:
        self._raise_if_failed()
        failure_event = self._failed
        get = asyncio.create_task(self._incoming.get())
        failed = asyncio.create_task(self._failed.wait())
        try:
            done, _ = await asyncio.wait((get, failed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TransportError("T_RECEIVE_TIMEOUT")
            self._raise_if_failed()
            if failure_event is not self._failed:
                raise TransportError("T_TRANSPORT_REPLACED")
            return get.result()
        finally:
            for task in (get, failed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(get, failed, return_exceptions=True)
            self._incoming_space.set()

    async def drain(self, timeout: float = 5.0) -> None:
        self._raise_if_failed()
        drained = asyncio.create_task(self._outgoing.join())
        failed = asyncio.create_task(self._failed.wait())
        try:
            done, _ = await asyncio.wait((drained, failed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TransportError("T_DRAIN_TIMEOUT")
            self._raise_if_failed()
        finally:
            for task in (drained, failed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(drained, failed, return_exceptions=True)

    async def close(self) -> None:
        async with self._close_lock:
            if self._close_failure is not None:
                raise self._close_failure
            await self._close_socket()

    async def _close_socket(self) -> None:
        self._fail(TransportError("T_CLOSED"))
        self._ready.clear()
        socket = self._socket
        tasks = tuple(task for task in (self._writer, self._reader) if task is not None)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._writer = self._reader = None
        if socket is not None:
            try:
                await asyncio.wait_for(socket.close(), self._send_timeout)
            except BaseException as exc:
                self._close_failure = TransportError("T_CLOSE_UNCONFIRMED")
                self._close_failure.__cause__ = exc
                logger.warning("wire_close_unconfirmed cause_type=%s", type(exc).__name__)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise self._close_failure from exc
            else:
                self._socket = None
            finally:
                self._clear_queues()
        else:
            self._clear_queues()

    def _clear_queues(self) -> None:
        self._incoming_space.set()
        self._outgoing_space.set()
        while not self._incoming.empty():
            self._incoming.get_nowait()
        self._clear_outgoing()

    def _clear_outgoing(self) -> None:
        self._outgoing_space.set()
        while not self._outgoing.empty():
            self._outgoing.get_nowait()
            self._outgoing.task_done()

    def discard_generation(self, generation_id: str) -> int:
        kept: list[Envelope] = []
        discarded = 0
        while True:
            try:
                envelope = self._incoming.get_nowait()
            except asyncio.QueueEmpty:
                break
            if envelope.generation_id == generation_id:
                discarded += 1
            else:
                kept.append(envelope)
        for envelope in kept:
            self._incoming.put_nowait(envelope)
        self._discarded_generation_frames += discarded
        self._incoming_space.set()
        return discarded

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

    async def _wait_for_space(self, queue: asyncio.Queue, space: asyncio.Event, code: str) -> None:
        failed, changed, revision = self._failed, self._changed, self.revision
        try:
            async with asyncio.timeout(self._send_timeout):
                while True:
                    self._raise_if_failed()
                    if failed is not self._failed:
                        raise TransportError("T_TRANSPORT_REPLACED")
                    if revision != self.revision:
                        raise TransportError("T_PEER_RECONNECTED")
                    if not queue.full():
                        return
                    space.clear()
                    waits = [asyncio.create_task(event.wait()) for event in (space, failed, changed)]
                    try:
                        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in waits:
                            task.cancel()
                        await asyncio.gather(*waits, return_exceptions=True)
        except TimeoutError as exc:
            self._raise_if_failed()
            error = TransportError(code)
            error.__cause__ = exc
            self._fail(error)
            raise error from exc

    async def _write_loop(self) -> None:
        try:
            while True:
                envelope = await self._outgoing.get()
                self._outgoing_space.set()
                try:
                    await asyncio.wait_for(self._socket.send(envelope.encode()), self._send_timeout)  # type: ignore[union-attr]
                finally:
                    self._outgoing.task_done()
        except asyncio.CancelledError:
            raise
        except (Exception, asyncio.TimeoutError) as exc:
            self._fail(exc)

    async def _read_loop(self) -> None:
        try:
            while True:
                raw = await self._socket.recv()  # type: ignore[union-attr]
                envelope = Envelope.decode(raw)
                previous_epoch = self.state.peer_epoch
                previous_local_epoch = self.state.local_epoch
                already_retiring = self.state.is_retiring_generation(envelope.generation_id)
                replies = self.state.accept(envelope)
                if replies is None:
                    continue
                if previous_epoch is not None and previous_epoch != self.state.peer_epoch:
                    self.revision += 1
                    self._changed.set()
                    self._changed = asyncio.Event()
                    self._ready.clear()
                    # Only a rotated local epoch retires its pending frames.
                    # Expected peer resync keeps our already-new local epoch;
                    # clearing its unsent probe would create a sequence gap.
                    if previous_local_epoch != self.state.local_epoch:
                        self._clear_outgoing()
                for reply in replies:
                    self._enqueue(reply)
                if envelope.kind is FrameKind.PEER_CLOSE:
                    raise TransportError("T_PEER_CLOSED")
                if (envelope.kind is FrameKind.DATA and self.state.is_retiring_generation(envelope.generation_id)
                    or already_retiring and envelope.kind in {FrameKind.GENERATION_ACCEPT, FrameKind.GENERATION_CLOSE}):
                    self._discarded_generation_frames += 1
                elif envelope.kind in {FrameKind.GENERATION_OFFER, FrameKind.GENERATION_ACCEPT, FrameKind.GENERATION_CLOSE, FrameKind.DATA, FrameKind.CAPABILITIES, FrameKind.PEER_CLOSE}:
                    await self._wait_for_space(self._incoming, self._incoming_space, "T_RECEIVE_BACKPRESSURE_TIMEOUT")
                    # Generation cleanup can finish while admission waits.
                    # Never append its last buffered DATA after the purge.
                    if envelope.kind is FrameKind.DATA and self.state.is_retiring_generation(envelope.generation_id):
                        self._discarded_generation_frames += 1
                        continue
                    try:
                        self._incoming.put_nowait(envelope)
                    except asyncio.QueueFull as exc:
                        raise TransportError("T_RECEIVE_QUEUE_FULL") from exc
                if self.state.ready:
                    self._ready.set()
                else:
                    self._ready.clear()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _wait(self, ready: asyncio.Event, timeout: float) -> None:
        wait_ready = asyncio.create_task(ready.wait())
        wait_failed = asyncio.create_task(self._failed.wait())
        try:
            done, _ = await asyncio.wait((wait_ready, wait_failed), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TransportError("T_READY_TIMEOUT")
            self._raise_if_failed()
        finally:
            for task in (wait_ready, wait_failed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(wait_ready, wait_failed, return_exceptions=True)

    async def _wait_for_cancel_or_failure(self, cancel: asyncio.Event) -> None:
        wait_cancel = asyncio.create_task(cancel.wait())
        wait_failure = asyncio.create_task(self._failed.wait())
        try:
            await asyncio.wait((wait_cancel, wait_failure), return_when=asyncio.FIRST_COMPLETED)
            self._raise_if_failed()
        finally:
            for task in (wait_cancel, wait_failure):
                if not task.done():
                    task.cancel()
            await asyncio.gather(wait_cancel, wait_failure, return_exceptions=True)

    def _fail(self, exc: Exception) -> None:
        if self._failure is None:
            self._failure = exc if isinstance(exc, TransportError) else TransportError("T_TRANSPORT_FAILED")
            if self._failure is not exc:
                self._failure.__cause__ = exc
            if self._failure.code != "T_CLOSED":
                # Exception messages / WS reasons can contain credentials or
                # peer-provided text. Record types and numeric close codes only.
                cause = self._failure.__cause__ or exc
                codes = [getattr(getattr(cause, attr, None), "code", None) for attr in ("rcvd", "sent")]
                codes = [value if isinstance(value, int) else None for value in codes]
                logger.warning("wire_first_failure code=%s cause_type=%s ws_received=%s ws_sent=%s outgoing=%d incoming=%d",
                               self._failure.code, type(cause).__name__, *codes,
                               self._outgoing.qsize(), self._incoming.qsize())
            self._failed.set()

    def _raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure
