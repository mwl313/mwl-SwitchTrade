"""Real Direct/LDN/NetlinkSocket cancellation, with only kernel IO substituted."""

from contextlib import ExitStack, asynccontextmanager
import struct
import threading
from unittest.mock import patch

import netlink
import pytest
import trio

from switchtrade.connection.stage_session import StageSession
from tests.test_switch_physical_boundary import stage_a
from tests.virtual_ldn_os import VirtualLdnOS, N


class AckSocket:
    """An in-memory kernel ACK, dispatched by the real NetlinkSocket.start()."""

    def __init__(self):
        self.tx, self.rx = trio.open_memory_channel(8)
        self.closed = False

    def getsockname(self):
        return (123, 0)

    async def send(self, data):
        _, _, _, sequence, pid = struct.unpack_from("IHHII", data)
        await self.tx.send(struct.pack("IHHIIi", 20, netlink.NLMSG_ERROR, 0, sequence, pid, 0))
        return len(data)

    async def recv(self, _size):
        return await self.rx.receive()

    def close(self):
        self.tx.close()
        self.rx.close()
        self.closed = True


def with_ack_dispatcher(base_connect, sockets):
    @asynccontextmanager
    async def connect():
        async with base_connect() as kernel:
            raw = AckSocket()
            sockets.append(raw)
            sock = netlink.NetlinkSocket(raw)
            request = kernel.request

            async def acknowledged(*args, **kwargs):
                result = await request(*args, **kwargs)
                await sock.request(netlink.NLMSG_NOOP)
                return result

            kernel.request = acknowledged
            try:
                # Same receive-task lifetime as python-netlink.connect().
                with sock:
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(sock.start)
                        yield kernel
                        nursery.cancel_scope.cancel()
            finally:
                raw.close()
    return connect


@pytest.mark.parametrize("stop_kind", ["cancel", "deadline"])
@pytest.mark.parametrize("lose_delete_ack", [False, True])
def test_real_scan_cleanup_keeps_netlink_ack_reader_alive(stop_kind, lose_delete_ack):
    os = VirtualLdnOS()
    entered = threading.Event()
    sockets = []

    async def scan_wait(_kernel, _attrs):
        entered.set()
        await trio.sleep_forever()

    async def missing_ack(kernel, attrs):
        # The kernel deleted the exact owned VIF, but never confirms completion.
        os.remove_link(os.links[attrs[N.NL80211_ATTR_IFINDEX]])
        await trio.sleep_forever()

    with ExitStack() as stack:
        os.install(stack)
        stack.enter_context(patch.object(N, "connect", with_ack_dispatcher(N.connect, sockets)))
        os.before_request[N.NL80211_CMD_SET_CHANNEL] = scan_wait
        if lose_delete_ack:
            os.before_request[N.NL80211_CMD_DEL_INTERFACE] = missing_ack
        stage = stage_a()
        stage.scan_timeout = .1 if stop_kind == "deadline" else 8
        session = StageSession(stage).start()
        try:
            assert entered.wait(3)
            if stop_kind == "deadline":
                assert session._done.wait(5)
        finally:
            try:
                if lose_delete_ack:
                    with pytest.raises(RuntimeError, match="did not prove") as first:
                        session.stop()
                    with pytest.raises(RuntimeError) as second:
                        session.stop()
                    assert first.value is second.value
                else:
                    session.stop()
            except BaseException as error:
                error.add_note(repr(session.report))
                os.assert_clean()
                assert sockets and all(sock.closed for sock in sockets)
                assert session._thread is None
                raise
        assert session.report["failure"]["code"] == (
            "A_CANCELLED" if stop_kind == "cancel" else "A_SCAN_TIMEOUT")
        assert session.report["cleanup"]["ldn_context_released"] is not lose_delete_ack
        assert session.report["cleanup"]["resources"]["scan.vif.6"] == (
            "unknown" if lose_delete_ack else "released")
        os.assert_clean()
    assert sockets and all(sock.closed for sock in sockets)
    assert session._thread is None
