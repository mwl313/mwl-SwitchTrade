"""Thread owner that keeps one admitted Direct A/B LDN context alive for C and D."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class StageResources:
    network: object
    transport: object
    advertisement: bytes


class StageSessionError(RuntimeError):
    """Preserve the stable failure identity returned by a Direct A/B stage."""

    def __init__(self, code: str, gate: str, message: str,
                 last_passed_gate: str | None = None):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.message = message
        self.last_passed_gate = last_passed_gate


class StageSession:
    """Run one Direct stage once; ``stop`` is the sole LDN-context exit owner."""

    def __init__(self, stage: object, *, timeout: float | None = None, stop_timeout: float = 15):
        if (timeout is not None and timeout <= 0) or stop_timeout <= 0:
            raise ValueError("stage session timeout must be positive")
        self.stage = stage
        self.timeout = timeout
        self.stop_timeout = stop_timeout
        self.resources: StageResources | None = None
        self.report: dict | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._trio_token = None
        self._cancel_scope = None
        self._trio_ready = threading.Event()
        self._stop_error: BaseException | None = None
        self._start_called = False
        self._owner_lock = threading.Lock()
        self.end_reason: str | None = None
        stage.session_handler = self._hold

    async def _hold(self, network: object, transport: object, advertisement: bytes) -> None:
        import trio

        self.resources = StageResources(network, transport, bytes(advertisement))
        self._ready.set()
        ldn = getattr(self.stage, "ldn", None)
        end_types = tuple(value for name in ("DisconnectEvent", "LeaveEvent")
                          if isinstance(value := getattr(ldn, name, None), type))

        async def watch_room():
            while True:
                event = await network.next_event()
                if isinstance(event, end_types):
                    self.end_reason = "local_room_ended"
                    nursery.cancel_scope.cancel()
                    return

        async with trio.open_nursery() as nursery:
            if end_types:
                nursery.start_soon(watch_room)
            while not self._stop.is_set():
                await trio.sleep(0.02)
            nursery.cancel_scope.cancel()

    def start(self) -> "StageSession":
        with self._owner_lock:
            if self._start_called or self._stop.is_set():
                raise RuntimeError("stage session was already started or stopped")
            self._start_called = True
            self._thread = threading.Thread(
                target=self._run, name="switchtrade-direct-stage", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        try:
            import trio

            async def run_stage():
                self._trio_token = trio.lowlevel.current_trio_token()
                with trio.CancelScope() as scope:
                    self._cancel_scope = scope
                    self._trio_ready.set()
                    if self._stop.is_set():
                        scope.cancel()
                    result = await self.stage.run()
                if scope.cancelled_caught:
                    raise StageSessionError(
                        "DIRECT_STAGE_CANCELLED", "DIRECT_STAGE_READY",
                        "direct stage was cancelled without a cleanup report",
                    )
                return result

            result = trio.run(run_stage)
            self.report = result[0] if isinstance(result, tuple) else result
        except BaseException as error:
            self._error = error
        finally:
            self._trio_ready.set()
            self._done.set()
            self._ready.set()

    def wait_ready(self) -> StageResources:
        if not self._ready.wait(self.timeout):
            raise StageSessionError(
                "DIRECT_STAGE_READY_TIMEOUT", "DIRECT_STAGE_READY",
                "direct stage did not reach its sustained-session checkpoint",
            )
        if self.resources is not None and not self._done.is_set() and not self._stop.is_set():
            return self.resources
        if self._error is not None:
            raise self._error
        failure = self.report.get("failure") if isinstance(self.report, dict) else None
        if isinstance(failure, dict):
            raise StageSessionError(
                str(failure.get("code") or "DIRECT_STAGE_FAILED"),
                str(failure.get("gate") or "DIRECT_STAGE_READY"),
                str(failure.get("message") or "direct stage failed before readiness"),
                str(self.report["last_passed_gate"])
                if self.report.get("last_passed_gate") is not None else None,
            )
        if self._stop.is_set():
            raise StageSessionError(
                "DIRECT_STAGE_CANCELLED", "DIRECT_STAGE_READY",
                "direct stage was stopped before readiness admission")
        raise StageSessionError(
            "DIRECT_STAGE_FAILED", "DIRECT_STAGE_READY",
            "direct stage failed before readiness",
        )

    def stop(self) -> None:
        with self._owner_lock:
            self._stop_owned()

    @property
    def ended(self) -> bool:
        return self._done.is_set()

    def raise_failure(self) -> None:
        if self._error is not None:
            raise self._error
        failure = self.report.get("failure") if isinstance(self.report, dict) else None
        if isinstance(failure, dict):
            raise StageSessionError(failure["code"], failure["gate"], failure["message"],
                                    self.report.get("last_passed_gate"))

    def _stop_owned(self) -> None:
        # A late thread exit must never turn an earlier unknown cleanup into a
        # successful retry. One session has exactly one admission and stop result.
        if self._stop_error is not None:
            raise self._stop_error
        self._stop.set()
        self._ready.set()
        if self._thread is None:
            return
        try:
            if self.resources is None and self._trio_token is not None and self._cancel_scope is not None:
                try:
                    # Enqueue, never synchronously wait for a possibly stalled
                    # OS operation in the Trio thread to acknowledge cancellation.
                    self._trio_token.run_sync_soon(self._cancel_scope.cancel)
                except RuntimeError:
                    pass
            self._thread.join(self.stop_timeout)
            if self._thread.is_alive():
                raise RuntimeError("direct stage did not release its LDN context")
            self._thread = None
            if self._error is not None:
                raise RuntimeError("direct stage failed during LDN teardown") from self._error
            if not isinstance(self.report, dict):
                raise RuntimeError("direct stage did not report LDN teardown")
            cleanup = self.report.get("cleanup")
            if (
                not isinstance(cleanup, dict)
                or cleanup.get("ldn_context_released") is not True
                or cleanup.get("radio_quiescent") is not True
                or cleanup.get("ap_stop_timed_out", False) is not False
            ):
                raise RuntimeError("direct stage did not prove LDN context cleanup")
        except BaseException as error:
            self._stop_error = error
            raise


__all__ = ["StageResources", "StageSession", "StageSessionError"]
