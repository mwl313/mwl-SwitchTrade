"""Actual pinned LDN + Direct + StageSession + driver failure paths."""

import asyncio
from contextlib import ExitStack
import threading
import io
from unittest.mock import patch

import pytest
import trio

from tests.virtual_ldn_os import VirtualLdnOS, N, ldn
from tests.test_switch_physical_boundary import stage_b, stage_a, eventually
from switchtrade.connection.b_fixture import FIXTURE
from switchtrade.connection.stage_session import StageSession
from switchtrade.core.contracts import GenerationOffer
from switchtrade.endpoints.switch_ldn.driver import SwitchLdnEndpointDriver, SwitchLdnPolicy, SWITCH_LDN_PROTOCOL


def policy(phy=0):
    return SwitchLdnPolicy(run_id="fault-test", release="test", usb_id="0bda:818b",
        hardware_profile="RTL8192EU", phy=f"phy{phy}", proven_radio_iface=f"proven{phy}",
        ifname=f"st-fault{phy}", ap_ifname=f"ap-fault{phy}", monitor_ifname=f"mon-fault{phy}",
        tap_ifname=f"tap-fault{phy}", keys_path="/synthetic-test.keys")


@pytest.mark.parametrize("dirty", [False, True])
def test_real_early_station_failure_keeps_first_code_and_independent_vif_cleanup(dirty):
    async def exercise():
        os = VirtualLdnOS()
        with ExitStack() as stack:
            os.install(stack)
            leader = StageSession(stage_b(1), timeout=20).start()
            driver = SwitchLdnEndpointDriver(policy())
            await driver.prepare()

            async def association(kernel, attrs):
                raise ConnectionError("injected kernel association failure")

            async def release(kernel, attrs):
                link = os.links[attrs[N.NL80211_ATTR_IFINDEX]]
                if dirty and link.type == N.NL80211_IFTYPE_STATION:
                    raise OSError("injected VIF delete failure")

            os.before_request[N.NL80211_CMD_CONNECT] = association
            os.before_request[N.NL80211_CMD_DEL_INTERFACE] = release
            try:
                with pytest.raises(Exception) as caught:
                    await asyncio.wait_for(driver.discover(asyncio.Event()), 20)
                assert caught.value.code == "A_ASSOCIATION_FAILED"
                report = await driver.close()
                assert report.local_resources_released is not dirty
                residue = [link for link in os.links.values() if link.phy == 0]
                assert bool(residue) is dirty
                if dirty:
                    with pytest.raises(Exception) as blocked:
                        await driver.prepare()
                    assert blocked.value.code == "SWITCH_ENDPOINT_CLEANUP_FAILED"
                    assert report.details["cleanup_errors"][0]["report"]["failure"]["code"] == "A_ASSOCIATION_FAILED"
            finally:
                await driver.close()
                try:
                    await asyncio.to_thread(leader.stop)
                except BaseException as error:
                    error.add_note(repr(leader.report))
                    raise
                # Fixture-only recovery of the explicitly observed failed-delete
                # object. Production driver is never readmitted after unknown.
                for link in list(os.links.values()):
                    assert dirty and link.phy == 0 and link.type == N.NL80211_IFTYPE_STATION
                    os.remove_link(link)
            os.assert_clean()
    asyncio.run(exercise())


@pytest.mark.parametrize("boundary", ["scan", "join", "ap", "association", "control"])
def test_actual_direct_cancel_at_kernel_await_releases_every_owned_resource(boundary):
    async def exercise():
        os = VirtualLdnOS()
        entered = threading.Event()
        sessions = []
        with ExitStack() as stack:
            os.install(stack)
            origin = boundary in {"scan", "join"}
            driver = SwitchLdnEndpointDriver(policy(0 if origin else 2))
            await driver.prepare()
            cancel = asyncio.Event()
            if boundary == "join":
                sessions.append(StageSession(stage_b(1), timeout=20).start())

            async def blocked(kernel, attrs):
                # Suspend the real netlink await, not Direct.run/session/driver.
                if boundary == "control":
                    index = attrs[N.NL80211_ATTR_IFINDEX]
                    if os.links[index].phy != 2:
                        return
                entered.set()
                await trio.sleep_forever()

            command = {"scan": N.NL80211_CMD_SET_CHANNEL, "join": N.NL80211_CMD_CONNECT,
                       "ap": N.NL80211_CMD_START_AP, "control": N.NL80211_CMD_CONTROL_PORT_FRAME}.get(boundary)
            if command is not None:
                os.before_request[command] = blocked
            offer = GenerationOffer("cancel-real", SWITCH_LDN_PROTOCOL, "switch_ldn", FIXTURE)
            pending = asyncio.create_task(driver.discover(cancel) if origin else driver.accept(offer, cancel))
            try:
                if boundary in {"association", "control"}:
                    await eventually(lambda: any(link.type == "tap" for link in os.links.values()), tasks=(pending,))
                    if boundary == "control":
                        sessions.append(StageSession(stage_a(3), timeout=20).start())
                    else:
                        entered.set()
                assert await asyncio.to_thread(entered.wait, 10)
                cancel.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(pending, 20)
                report = await driver.close()
                assert report.local_resources_released, report.details
                assert not [link for link in os.links.values() if link.phy == (0 if origin else 2)]
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await driver.close()
                for session in sessions:
                    try:
                        await asyncio.to_thread(session.stop)
                    except BaseException as error:
                        error.add_note(repr(session.report))
                        raise
            os.assert_clean()
            assert not any(t.name.startswith("switchtrade-") for t in threading.enumerate())
    asyncio.run(exercise())


@pytest.mark.parametrize("origin", [True, False])
@pytest.mark.parametrize("text", ["unrelated_key = 00", "master_key_12 = zz",
    "master_key_12 = 00\naes_kek_generation_source = 00\naes_key_generation_source = 00"])
def test_actual_key_loader_rejects_missing_malformed_and_short_keys_before_radio_admission(origin, text):
    async def exercise():
        os = VirtualLdnOS()
        with ExitStack() as stack:
            os.install(stack)
            opened = stack.enter_context(patch.object(ldn, "open", side_effect=lambda *_: io.StringIO(text)))
            driver = SwitchLdnEndpointDriver(policy())
            await driver.prepare()
            offer = GenerationOffer("invalid-keys", SWITCH_LDN_PROTOCOL, "switch_ldn", FIXTURE)
            try:
                with pytest.raises(Exception) as caught:
                    await (driver.discover(asyncio.Event()) if origin else driver.accept(offer, asyncio.Event()))
                assert caught.value.code == ("A_KEYS_INVALID" if origin else "B_KEYS_INVALID")
                assert opened.call_count == 1  # Fatal, never the no-room retry path.
            finally:
                report = await driver.close()
                assert report.local_resources_released
            os.assert_clean()
    asyncio.run(exercise())
