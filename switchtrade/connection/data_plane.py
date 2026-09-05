"""Feature-neutral Pia UDP adapter for an already admitted LDN network."""

from __future__ import annotations

import contextlib
import socket
import struct


ETH_P_IP = 0x0800
PROTO_UDP = 17
PIA_PORT = 12345


class LdnDataPlane(dict):
    """Keep the proven A/B sockets open and expose the transport used by ``TunnelSim``."""

    def __init__(self, network: object, ifname: str, evidence: dict[str, bool]):
        super().__init__(evidence)
        self.network = network
        self.ifname = ifname
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_IP))
        try:
            self._tx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._prepare_local_identity()
            self._tx.bind((self.our_ip, PIA_PORT))
            self._rx.bind((ifname, 0))
            self._rx.setblocking(False)
        except BaseException:
            self.close()
            raise

    def _prepare_local_identity(self) -> None:
        info = self.network.info()
        local = self.network.participant()
        self.our_ip = str(local.ip_address)
        self.our_mac = bytes(local.mac_address)
        self.ssid = bytes(info.ssid)
        if not self.our_ip.startswith("169.254.") or len(self.our_mac) != 6 or not self.ssid:
            raise RuntimeError("the physical LDN local data-plane identity is invalid")

    def bind_peer(self) -> None:
        """Bind the remote identity only after the joining Switch is observed."""
        info = self.network.info()
        local = self.network.participant()
        connected = [
            item for item in (getattr(info, "participants", ()) or ())
            if getattr(item, "connected", False)
        ]
        peer = next((item for item in connected if item is not local), None)
        if peer is None:
            raise RuntimeError("the physical LDN peer is unavailable")
        self.host_ip = str(peer.ip_address)
        self.host_mac = bytes(peer.mac_address)
        if (
            not self.host_ip.startswith("169.254.")
            or len(self.our_mac) != 6
            or len(self.host_mac) != 6
            or not self.ssid
        ):
            raise RuntimeError("the physical LDN data-plane identity is invalid")
        self.broadcast = self.our_ip.rsplit(".", 1)[0] + ".255"

    def send(self, datagram: bytes, dst_ip: str) -> None:
        destination = self.broadcast if dst_ip in {self.broadcast, "255.255.255.255"} else dst_ip
        self._tx.sendto(bytes(datagram), (destination, PIA_PORT))

    def recv(self) -> list[tuple[bytes, str]]:
        packets = []
        while True:
            try:
                frame = self._rx.recv(65535)
            except BlockingIOError:
                break
            parsed = self._parse_udp(frame)
            if parsed is None:
                continue
            src_ip, dst_ip, dst_port, payload = parsed
            accepted = (
                dst_ip == self.our_ip
                or (dst_ip.startswith("169.254.") and dst_ip.endswith(".255"))
                or dst_ip == "255.255.255.255"
            )
            if src_ip != self.our_ip and dst_port == PIA_PORT and accepted:
                packets.append((payload, src_ip))
        return packets

    @staticmethod
    def _parse_udp(frame: bytes) -> tuple[str, str, int, bytes] | None:
        if len(frame) < 42 or struct.unpack_from("!H", frame, 12)[0] != ETH_P_IP:
            return None
        ip = frame[14:]
        if ip[0] >> 4 != 4 or ip[9] != PROTO_UDP:
            return None
        ihl = (ip[0] & 0x0F) * 4
        if len(ip) < ihl + 8:
            return None
        src_ip = socket.inet_ntoa(ip[12:16])
        dst_ip = socket.inet_ntoa(ip[16:20])
        udp = ip[ihl:]
        _src_port, dst_port, length = struct.unpack_from("!HHH", udp, 0)
        payload = udp[8:][:max(0, length - 8)] if length >= 8 else udp[8:]
        return src_ip, dst_ip, dst_port, payload

    def close(self) -> None:
        for stream in (getattr(self, "_rx", None), getattr(self, "_tx", None)):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass


@contextlib.contextmanager
def open_ldn_data_plane(network: object, ifname: str, evidence: dict[str, bool]):
    plane = LdnDataPlane(network, ifname, evidence)
    try:
        yield plane
    finally:
        plane.close()


__all__ = ["LdnDataPlane", "open_ldn_data_plane"]
