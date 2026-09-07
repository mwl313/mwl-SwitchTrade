"""Run-local ownership evidence for the pinned LDN context managers.

No recovery/delete-by-name is performed here. A name must be absent before
acquisition; its creating context is the only release owner. Unknown is sticky.
"""

from __future__ import annotations

import contextlib
import socket


def cancelled(error: BaseException) -> bool:
    import trio

    if isinstance(error, BaseExceptionGroup):
        return all(cancelled(item) for item in error.exceptions)
    return isinstance(error, trio.Cancelled)


class ResourceScope:
    def __init__(self):
        self.states: dict[str, str] = {}
        self.failures: list[str] = []

    @property
    def clean(self) -> bool:
        return not self.failures and all(
            state in {"not_acquired", "released"} for state in self.states.values())

    @staticmethod
    def absent(name: str) -> bool:
        return name not in {item[1] for item in socket.if_nameindex()}

    @contextlib.asynccontextmanager
    async def context(self, manager, label, *, ifname=None, shield_exit=False,
                      entry_owns_resource=True):
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
