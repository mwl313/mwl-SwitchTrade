"""Endpoint-local control liveness, independent of opaque remote RFU."""

from types import SimpleNamespace

from frlgsim import pia_connect as pia, reliable
from frlgsim.crypto import PiaCrypto
from frlgsim.tunnel import TunnelSim
from bridge.tests.test_pia_host import NATIVE_JOIN, pia_reliable_datagram


def manager():
    return pia.HostConnectionManager(bytes.fromhex("020000000001"), "169.254.1.1", 1,
        our_var=0x1234, peer_provider=lambda: (bytes.fromhex("020000000002"), "169.254.1.2"),
        maintain_rtt=True)


def test_mirror_retransmits_session_accept_then_maintains_rtt_without_remote_data():
    host = manager()
    host.on_message(pia.PROTO_SESSION, NATIVE_JOIN, tick=1)
    accept = host.drain()
    host.poll(pia.HOST_NET_PERIOD)
    assert host.drain() == []
    host.poll(pia.HOST_NET_PERIOD + 1)
    assert host.drain() == accept
    host.on_message(pia.PROTO_SESSION, bytes([pia.SESSION_FINALIZE]), tick=40)
    host.poll(41)
    request, = host.drain()
    assert request["proto"] == pia.PROTO_RTT
    assert (request["dst"], request["src"], request["footer_var"]) == (1, 0x1234, host.host_var)
    assert pia.parse_rtt(request["payload"])["version"] == 3
    host.on_message(pia.PROTO_RTT, pia.build_rtt_response(request["payload"]), tick=43)
    assert host.rtt_samples == [2]
    host.on_message(pia.PROTO_RTT, request["payload"], tick=44)
    echo, = host.drain()
    assert echo["payload"] == pia.build_rtt_response(request["payload"])
    for tick in range(51, 2000, 10):
        host.poll(tick)
        host.drain()
    assert len(host._rtt_pending) <= 64


def test_real_reliable_receive_releases_child_finalize_without_rtt():
    crypto = PiaCrypto(bytes(range(16)))
    child = pia.ConnectionManager(b"\x02" * 6, b"\x04" * 6, "169.254.1.2", "169.254.1.1")
    child.state = pia.ST_FINALIZE
    delivered = []
    tunnel = SimpleNamespace(send_rfu=lambda payload, flags: delivered.append((payload, flags)))
    sim = TunnelSim(SimpleNamespace(), crypto, "169.254.1.2", "169.254.1.1", tunnel,
                    conn=child, our_var=0x5678)
    packet = pia_reliable_datagram(crypto, "169.254.1.1", 0x5678, 0x1234, 1,
                                   0xFFF0, 0xFFF0, reliable.FLAGSA_GBA, b"opaque")
    assert sim.process_datagram(packet, "169.254.1.1")
    assert child.connected
    assert delivered == [(b"opaque", reliable.FLAGSA_GBA)]
