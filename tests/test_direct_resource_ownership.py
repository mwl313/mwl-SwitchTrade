"""Faults before readiness must exercise the actual Direct stage owner.

These focused tests replace WLAN primitives. Full protocol qualification is
separate; this suite makes no RFU/internet or physical qualification claim.
"""

import contextlib
import threading
import time
from unittest.mock import patch

import pytest
import trio

from switchtrade.connection.a_stage import DirectAStage
from switchtrade.connection.b_stage import DirectBStage
from switchtrade.connection.resource_scope import ResourceScope
from switchtrade.connection.stage_session import StageSession
from tests.test_direct_a_stage import FakeFactory, FakeLdn, FakeStation, FakeWlan, fake_data_plane


def stage_for(ldn):
    return DirectAStage(
        run_id="00000000-0000-0000-0000-000000000001", release="test",
        phy="phy7", ifname="sta-owned", keys_path="test.keys",
        hold_seconds=.01, ldn_module=ldn, trio_module=trio,
        data_plane_factory=fake_data_plane, version_resolver=lambda: "0.0.17")


def test_runtime_sockets_are_closed_even_when_library_objects_remain_referenced():
    retained = []

    class Ldn(FakeLdn):
        @classmethod
        async def scan(cls, *_args):
            retained.extend([trio.socket.socket(), trio.socket.socket()])
            return []

    stage = stage_for(Ldn)
    report, _ = trio.run(stage.run)
    assert report["failure"]["code"] == "A_ROOM_NOT_OBSERVED"
    assert retained and all(stream.fileno() == -1 for stream in retained)
    assert report["cleanup"]["resources"]["runtime.sockets"] == "released"
    assert report["cleanup"]["ldn_context_released"]


@pytest.mark.parametrize("delete_fails", [False, True])
def test_association_failure_retains_primary_and_independent_vif_release(delete_fails):
    inventory = {"health-monitor", "unrelated-wlan", "unrelated-tap"}
    removed = []

    class Factory(FakeFactory):
        @contextlib.asynccontextmanager
        async def _create_interface(self, phy, name, kind):
            assert phy == "phy7"
            inventory.add(name)
            try:
                yield {1: 7, 2: bytes.fromhex("020000000002")}
            finally:
                await trio.lowlevel.checkpoint()
                if delete_fails and name == "sta-owned":
                    raise OSError("injected delete failure")
                inventory.remove(name)
                removed.append(name)

    class Station(FakeStation):
        @contextlib.asynccontextmanager
        async def connect(self):
            raise ConnectionError("injected association failure")
            yield

    class Wlan(FakeWlan):
        create_factory = staticmethod(Factory)

    Wlan.Station = Station

    class Ldn(FakeLdn):
        wlan = Wlan

    stage = stage_for(Ldn)
    with patch.object(ResourceScope, "absent", side_effect=lambda name: name not in inventory):
        report, _ = trio.run(stage.run)
    assert report["failure"]["code"] == "A_ASSOCIATION_FAILED"
    assert report["cleanup"]["ldn_context_released"] is not delete_fails
    assert report["cleanup"]["resources"]["join.vif.3"] == (
        "unknown" if delete_fails else "released")
    assert inventory >= {"health-monitor", "unrelated-wlan", "unrelated-tap"}
    assert set(removed) <= {"scan-sta-owned", "sta-owned"}
    if delete_fails:
        assert report["cleanup"]["errors"] == ["join.vif.3:OSError"]


def test_cancel_after_vif_creation_shields_release_at_real_await():
    inventory = set()
    entered = threading.Event()

    class Factory(FakeFactory):
        @contextlib.asynccontextmanager
        async def _create_interface(self, phy, name, kind):
            inventory.add(name)
            try:
                yield {1: 7, 2: bytes.fromhex("020000000002")}
            finally:
                await trio.lowlevel.checkpoint()
                inventory.remove(name)

    class Station(FakeStation):
        @contextlib.asynccontextmanager
        async def connect(self):
            entered.set()
            await trio.sleep_forever()
            yield

    class Wlan(FakeWlan):
        create_factory = staticmethod(Factory)

    Wlan.Station = Station

    class Ldn(FakeLdn):
        wlan = Wlan

    stage = stage_for(Ldn)
    with patch.object(ResourceScope, "absent", side_effect=lambda name: name not in inventory):
        session = StageSession(stage, stop_timeout=1).start()
        try:
            assert entered.wait(2)
        finally:
            session.stop()
    assert not inventory
    assert session.report["failure"]["code"] == "A_CANCELLED"
    assert session.report["cleanup"]["ldn_context_released"]


def test_existing_station_name_is_never_deleted():
    stage = stage_for(FakeLdn)
    with patch.object(ResourceScope, "absent", side_effect=lambda name: name != "sta-owned"):
        report, _ = trio.run(stage.run)
    assert report["status"] == "failed"
    assert "join.vif.3" not in stage.resources.states


def test_missing_b_runtime_is_classified_before_base_exception_handler():
    stage = DirectBStage(
        run_id="test", release="test", phy="phy7", keys_path="test.keys",
        ap_ifname="ap-owned", monitor_ifname="mon-owned", tap_ifname="tap-owned",
        ldn_module=object(), trio_module=trio,
        version_resolver=lambda: (_ for _ in ()).throw(ImportError("missing runtime")))
    report = trio.run(stage.run)
    assert report["failure"]["code"] == "B_RUNTIME_DEPENDENCY_MISSING"
    assert report["cleanup"]["radio_quiescent"]


def test_stage_stop_timeout_is_bounded_and_remains_failed_after_late_exit():
    blocked = threading.Event()
    release = threading.Event()

    class StalledStage:
        async def run(self):
            blocked.set()
            release.wait(3)  # OS primitive that ignores Trio cancellation.
            return {"cleanup": {"ldn_context_released": True, "radio_quiescent": True}}

    session = StageSession(StalledStage(), stop_timeout=.03).start()
    try:
        assert blocked.wait(1)
        started = time.monotonic()
        with pytest.raises(RuntimeError) as first:
            session.stop()
        assert time.monotonic() - started < .5
    finally:
        release.set()
        assert session._done.wait(2)
    with pytest.raises(RuntimeError) as second:
        session.stop()
    assert second.value is first.value
    with pytest.raises(RuntimeError):
        session.start()


def test_stop_before_trio_token_publication_has_no_synchronous_ack_wait():
    release = threading.Event()

    class Stage:
        async def run(self):
            return {"cleanup": {"ldn_context_released": True, "radio_quiescent": True}}

    class DelayedSession(StageSession):
        def _run(self):
            release.wait(3)
            super()._run()

    session = DelayedSession(Stage(), stop_timeout=.03).start()
    try:
        with pytest.raises(RuntimeError) as first:
            session.stop()
    finally:
        release.set()
        assert session._done.wait(2)
    with pytest.raises(RuntimeError) as second:
        session.stop()
    assert first.value is second.value


@pytest.mark.parametrize("leaf", ["released", "unknown", None])
@pytest.mark.parametrize("exit_fails", [False, True])
def test_cancelled_nursery_requires_independent_leaf_release(leaf, exit_fails):
    async def exercise():
        resources = ResourceScope()
        if leaf is not None:
            resources.states["owned"] = leaf

        @contextlib.asynccontextmanager
        async def nursery():
            try:
                yield
            except BaseException as error:
                errors = [error]
                if exit_fails:
                    errors.append(OSError("real teardown failure"))
                raise BaseExceptionGroup("nursery exit", errors)

        with trio.CancelScope() as cancellation:
            async with resources.context(nursery(), "group", entry_owns_resource=False,
                                         release_dependencies=("owned",)):
                cancellation.cancel()
                await trio.lowlevel.checkpoint()
        assert cancellation.cancelled_caught  # Cleanup never suppresses the primary.
        assert resources.clean is (leaf == "released" and not exit_fails)
        assert resources.states["group"] == ("unknown" if exit_fails else "release_delegated")
        assert bool(resources.failures) is exit_fails
    trio.run(exercise)
