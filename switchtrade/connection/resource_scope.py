"""Run-local ownership evidence for the pinned LDN context managers.

No recovery/delete-by-name is performed here. A name must be absent before
acquisition; its creating context is the only release owner. Unknown is sticky.
"""

from __future__ import annotations

import contextlib
import socket


@contextlib.contextmanager
def owned_trio_sockets():
    """Retain and explicitly close every socket created by this LDN Trio run.

LDN 0.0.17 Interface/Monitor retain sockets beyond factory exit (and Monitor
replaces its initial Interface socket). The returned sockets are still the real
Trio sockets; the run-local factory only records ownership, without changing IO.
"""
    import trio

    streams = []

    class Factory:
        def socket(self, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
            trio.socket.set_custom_socket_factory(previous)
            try:
                stream = trio.socket.socket(family, type, proto)
                streams.append(stream)
                return stream
            finally:
                trio.socket.set_custom_socket_factory(self)

    previous = trio.socket.set_custom_socket_factory(Factory())
    try:
        yield
    finally:
        trio.socket.set_custom_socket_factory(previous)
        failures = []
        for stream in reversed(streams):
            try:
                if stream.fileno() != -1:
                    stream.close()
                if stream.fileno() != -1:
                    raise RuntimeError("socket release unproven")
            except BaseException as error:
                failures.append(error)
        if failures:
            raise RuntimeError("LDN_RUNTIME_SOCKET_CLEANUP_FAILED") from failures[0]


async def run_with_owned_sockets(resources, operation):
    result = None
    try:
        with resources.sync_context(owned_trio_sockets(), "runtime.sockets"):
            result = await operation()
    except BaseException:
        if result is None:
            raise
        # The operation already supplied the first functional result. Cleanup
        # failure is separately retained by ResourceScope, never a replacement.
    return result


def cancelled(error: BaseException) -> bool:
    import trio

    if isinstance(error, BaseExceptionGroup):
        return all(cancelled(item) for item in error.exceptions)
    return isinstance(error, trio.Cancelled)


def propagates(error: BaseException, primary: BaseException) -> bool:
    """Exit contains only the body's failure, not a new cleanup failure."""
    if error is primary or cancelled(error) and cancelled(primary):
        return True
    if isinstance(error, BaseExceptionGroup):
        return all(propagates(item, primary) for item in error.exceptions)
    if isinstance(primary, BaseExceptionGroup):
        return any(propagates(error, item) for item in primary.exceptions)
    return False


class ResourceScope:
    def __init__(self):
        self.states: dict[str, str] = {}
        self.failures: list[str] = []
        self.release_dependencies: dict[str, tuple[str, ...]] = {}

    @property
    def clean(self) -> bool:
        return not self.failures and all(
            state in {"not_acquired", "released"} or (
                state == "release_delegated"
                and all(self.states.get(owner) == "released"
                        for owner in self.release_dependencies[label]))
            for label, state in self.states.items())

    @staticmethod
    def absent(name: str) -> bool:
        return name not in {item[1] for item in socket.if_nameindex()}

    @contextlib.asynccontextmanager
    async def context(self, manager, label, *, ifname=None, shield_exit=False,
                      entry_owns_resource=True, release_dependencies=()):
        import trio

        if ifname is not None and not self.absent(ifname):
            raise RuntimeError("DIRECT_RESOURCE_NAME_IN_USE")
        self.states[label] = "acquiring"
        try:
            value = await manager.__aenter__()
        except BaseException:
            # The lower-level VIF owner is independently tracked, including
            # failure before its context yields. Factory/nursery entry failures
            # without a kernel absence proof remain unknown.
            self.states[label] = "unknown" if entry_owns_resource else "not_acquired"
            if ifname is not None:
                try:
                    if self.absent(ifname):
                        self.states[label] = "released"
                except OSError:
                    pass
            raise
        self.states[label] = "acquired"
        primary = None
        try:
            yield value
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                args = (None, None, None) if primary is None else (
                    type(primary), primary, primary.__traceback__)
                if shield_exit:
                    # Only leaf VIF/TAP contexts (no nested Trio nursery) may
                    # be exited inside a new cancel scope.
                    with trio.fail_after(3, shield=True):
                        await manager.__aexit__(*args)
                else:
                    await manager.__aexit__(*args)
                if ifname is not None and not self.absent(ifname):
                    raise RuntimeError("DIRECT_RESOURCE_RELEASE_UNPROVEN")
                self.states[label] = "released"
            except BaseException as error:
                if (not entry_owns_resource and release_dependencies
                        and primary is not None and (cancelled(error) or propagates(error, primary))):
                    # Trio nursery exit may wrap the body's failure/cancellation.
                    # Mere propagation is NOT itself release evidence:
                    # only the explicitly named leaf owners can prove release.
                    self.release_dependencies[label] = tuple(release_dependencies)
                    self.states[label] = "release_delegated"
                else:
                    self.states[label] = "unknown"
                    self.failures.append(label + ":" + type(error).__name__)
                    if primary is None:
                        raise
                    # Keep the original exception (including cancellation) primary.
                    primary.add_note("cleanup failed: " + label + ":" + type(error).__name__)

    @contextlib.contextmanager
    def sync_context(self, manager, label):
        self.states[label] = "acquiring"
        try:
            value = manager.__enter__()
        except BaseException as error:
            self.states[label] = (
                "unknown" if getattr(error, "cleanup_failed", False) else "not_acquired")
            raise
        self.states[label] = "acquired"
        primary = None
        try:
            yield value
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                manager.__exit__(*( (None, None, None) if primary is None else
                    (type(primary), primary, primary.__traceback__) ))
                if primary is not None and getattr(primary, "cleanup_failed", False):
                    raise RuntimeError("DIRECT_RESOURCE_RELEASE_UNPROVEN")
                self.states[label] = "released"
            except BaseException as error:
                self.states[label] = "unknown"
                self.failures.append(label + ":" + type(error).__name__)
                if primary is None:
                    raise
                primary.add_note("cleanup failed: " + label + ":" + type(error).__name__)

    def instrument_factory(self, factory, prefix):
        create_interface = factory._create_interface

        def interface(phy, name, kind, *args, **kwargs):
            return self.context(
                create_interface(phy, name, kind, *args, **kwargs),
                prefix + ".vif." + str(kind), ifname=name, shield_exit=True)

        factory._create_interface = interface
        if hasattr(factory, "create_tap"):
            create_tap = factory.create_tap

            def tap(name, address):
                return self.context(create_tap(name, address), prefix + ".tap",
                                    ifname=name, shield_exit=True)

            factory.create_tap = tap
        return factory
