"""Deterministic Linux radio/kernel primitives, not a replacement LDN stack.

The installed ldn 0.0.17 Factory/Scanner/Station/AccessPoint/APNetwork/STANetwork
still encode, authenticate, advertise, associate and forward encrypted frames.
Only netlink, netdev inventory, TAP files and raw/UDP sockets are virtual. Two
disjoint radio domains cannot communicate except through the real Core relay.
All keys and MACs below are synthetic test material.
"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
import io
import queue
import socket
import struct
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import trio

if sys.platform == "win32" and "fcntl" not in sys.modules:
    # Linux ioctl is an OS primitive. The actual LDN library is imported below.
    sys.modules["fcntl"] = ModuleType("fcntl")
import ldn
from ldn import wlan


N = wlan.nl80211
R = wlan.route
CURRENT = ContextVar("virtual_netlink")
KEY_TEXT = "\n".join(f"{name} = {'00' * 16}" for name in (
    "master_key_00", "master_key_12", "aes_kek_generation_source", "aes_key_generation_source"))


async def take(q):
    while True:
        try:
            return q.get_nowait()
        except queue.Empty:
            await trio.sleep(.001)


class Kernel:
    def __init__(self, os):
        self.os = os
        self.events = queue.Queue()

    def add_membership(self, _name):
        pass

    def event(self, cmd, attrs):
        self.events.put(SimpleNamespace(type=cmd, attributes=attrs))

    async def receive(self):
        return await take(self.events)

    async def request(self, cmd, attrs=None, flags=0, header=b""):
        del flags, header
        attrs = attrs or {}
        os = self.os
        os.commands.append(cmd)
        if hook := os.before_request.get(cmd):
            await hook(self, attrs)
        if cmd == N.NL80211_CMD_GET_WIPHY:
            return [SimpleNamespace(attributes={N.NL80211_ATTR_WIPHY_NAME: f"phy{i}",
                     N.NL80211_ATTR_WIPHY: i}) for i in range(4)]
        if cmd == N.NL80211_CMD_NEW_INTERFACE:
            link = os.add_link(attrs[N.NL80211_ATTR_IFNAME], attrs[N.NL80211_ATTR_WIPHY],
                               attrs[N.NL80211_ATTR_IFTYPE], self)
            return [SimpleNamespace(attributes={N.NL80211_ATTR_IFINDEX: link.index,
                     N.NL80211_ATTR_MAC: link.mac})]
        link = os.links.get(attrs.get(N.NL80211_ATTR_IFINDEX))
        if cmd == N.NL80211_CMD_DEL_INTERFACE:
            os.remove_link(link)
        elif cmd == N.NL80211_CMD_SET_CHANNEL:
            os.frequencies[link.phy] = attrs[N.NL80211_ATTR_WIPHY_FREQ]
        elif cmd == N.NL80211_CMD_START_AP:
            link.ssid = attrs[N.NL80211_ATTR_SSID]
            os.frequencies[link.phy] = attrs[N.NL80211_ATTR_WIPHY_FREQ]
            link.ap = True
            self.event(cmd, {})
        elif cmd == N.NL80211_CMD_STOP_AP:
            link.ap = False
            for sta in list(os.links.values()):
                if sta.peer is link:
                    sta.kernel.event(N.NL80211_CMD_DEL_STATION, {N.NL80211_ATTR_MAC: link.mac})
        elif cmd == N.NL80211_CMD_CONNECT:
            ap = next((x for x in os.links.values() if x.ap and x.domain == link.domain
                       and x.ssid == attrs[N.NL80211_ATTR_SSID]), None)
            if ap is not None:
                link.peer = ap
                os.frequencies[link.phy] = attrs[N.NL80211_ATTR_WIPHY_FREQ]
                request = wlan.AssociationRequest()
                request.source = wlan.MACAddress(link.mac)
                request.target = request.bssid = wlan.MACAddress(ap.mac)
                request.elements = {wlan.WLAN_EID_SSID: ap.ssid,
                                    wlan.WLAN_EID_SUPP_RATES: bytes.fromhex("82848b96")}
                ap.kernel.event(N.NL80211_CMD_FRAME, {N.NL80211_ATTR_FRAME: request.encode()})
        elif cmd == N.NL80211_CMD_FRAME:
            data = attrs[N.NL80211_ATTR_FRAME]
            mac = wlan.MACHeader()
            mac.decode(data)
            if mac.subtype == wlan.IEEE80211_STYPE_ASSOC_RESP:
                sta = os.by_mac(bytes(mac.address1), link.domain, station=True)
                response = wlan.AssociationResponse()
                response.decode(data)
                sta.kernel.event(N.NL80211_CMD_CONNECT, {
                    N.NL80211_ATTR_STATUS_CODE: response.status_code,
                    N.NL80211_ATTR_MAC: link.mac})
        elif cmd == N.NL80211_CMD_CONTROL_PORT_FRAME:
            target = os.by_mac(bytes(attrs[N.NL80211_ATTR_MAC]), link.domain)
            if target is not None:
                target.kernel.event(cmd, {N.NL80211_ATTR_MAC: link.mac,
                                         N.NL80211_ATTR_FRAME: attrs[N.NL80211_ATTR_FRAME]})
        elif cmd == N.NL80211_CMD_NEW_KEY:
            link.key = attrs[N.NL80211_ATTR_KEY][N.NL80211_KEY_DATA]
        elif cmd == N.NL80211_CMD_DISCONNECT:
            if link.peer and link.peer.index in os.links:
                frame = wlan.DisassociationFrame()
                frame.source = wlan.MACAddress(link.mac)
                frame.target = frame.bssid = wlan.MACAddress(link.peer.mac)
                link.peer.kernel.event(N.NL80211_CMD_FRAME, {N.NL80211_ATTR_FRAME: frame.encode()})
        elif cmd not in {N.NL80211_CMD_REGISTER_FRAME, N.NL80211_CMD_SET_KEY,
                         N.NL80211_CMD_NEW_STATION, N.NL80211_CMD_SET_STATION,
                         N.NL80211_CMD_DEL_STATION}:
            raise AssertionError(f"unimplemented kernel operation {cmd}")
        await trio.lowlevel.checkpoint()
        return []


class Router:
    def __init__(self, os):
        self.os = os

    async def update_link(self, _family, _kind, index, _flags, _change, attrs):
        if R.IFLA_ADDRESS in attrs:
            self.os.links[index].mac = attrs[R.IFLA_ADDRESS]
        await trio.lowlevel.checkpoint()

    async def add_address(self, _family, _prefix, _flags, _scope, index, attrs):
        self.os.links[index].ip = socket.inet_ntoa(attrs[R.IFA_LOCAL])
        await trio.lowlevel.checkpoint()

    async def add_neighbor(self, *args):
        await trio.lowlevel.checkpoint()

    async def remove_neighbor(self, *args):
        await trio.lowlevel.checkpoint()


class RawSocket:
    def __init__(self, os, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        self.os, self.family, self.type = os, family, type
        self.kernel = CURRENT.get(None)
        self.fd = os.next_id()
        self.bound = None
        self.incoming = queue.Queue()
        os.sockets.append(self)

    def fileno(self):
        return self.fd

    def close(self):
        self.fd = -1

    def setsockopt(self, *args):
        pass

    def setblocking(self, flag):
        pass

    def bind(self, address):
        self.bound = address

    def recv(self, _size):
        if self.fd < 0:
            raise OSError("closed")
        try:
            return self.incoming.get_nowait()
        except queue.Empty:
            raise BlockingIOError from None

    def sendto(self, payload, target):
        if self.fd < 0:
            raise OSError("closed")
        link = next(x for x in self.os.links.values() if x.ip == self.bound[0]
                    and x.kernel is self.kernel)
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 28 + len(payload), 0, 0,
                         64, 17, 0, socket.inet_aton(link.ip), socket.inet_aton(target[0]))
        udp = struct.pack("!HHHH", self.bound[1], target[1], 8 + len(payload), 0) + payload
        packet = b"\xff" * 6 + link.mac + b"\x08\x00" + ip + udp
        if link.type == "tap":
            link.tap.incoming.put(packet)
        else:
            frame = wlan.DataFrame()
            frame.source = wlan.MACAddress(link.mac)
            frame.target = frame.bssid = wlan.MACAddress(link.peer.mac)
            frame.tods = True
            frame.payload = wlan.SNAPHeader(protocol=0x800, payload=ip + udp).encode()
            frame.encrypt(link.key, self.os.next_id(), 0)
            self.os.broadcast(link, wlan.RadiotapFrame(frame.encode()).encode())
        self.os.udp_sent += 1
        return len(payload)


class AsyncRawSocket(RawSocket):
    async def bind(self, address):
        super().bind(address)
        await trio.lowlevel.checkpoint()

    async def recv(self, _size):
        return await take(self.incoming)

    async def send(self, data):
        self.os.broadcast(self.os.by_name(self.bound[0]), data)
        await trio.lowlevel.checkpoint()
        return len(data)


class TapFile:
    def __init__(self, os):
        self.os, self.kernel = os, CURRENT.get()
        self.fd = os.next_id()
        self.incoming = queue.Queue()
        self.link = None
        os.files.append(self)

    def fileno(self):
        return self.fd

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if self.link is not None:
            self.os.remove_link(self.link)
        self.fd = -1

    async def read(self, size):
        return await take(self.incoming)

    async def write(self, data):
        self.os.deliver_ip(self.link, data)
        await trio.lowlevel.checkpoint()
        return len(data)


class VirtualLdnOS:
    def __init__(self):
        self.links, self.frequencies = {}, {i: 2437 for i in range(4)}
        self.sockets, self.files, self.commands = [], [], []
        self.before_request = {}
        self.counter = 100
        self.udp_sent = self.radio_frames = self.decrypted_frames = 0

    def next_id(self):
        self.counter += 1
        return self.counter

    def add_link(self, name, phy, type, kernel):
        assert not any(x.name == name for x in self.links.values()), name
        index = self.next_id()
        # AP and monitor use the same radio MAC, a supported kernel assignment.
        link = SimpleNamespace(index=index, name=name, phy=phy, domain=phy // 2,
            type=type, kernel=kernel, mac=bytes([2, 0, 0, 0, 0, phy + 1]), ip=None,
            peer=None, key=None, ap=False, ssid=None, tap=None)
        self.links[index] = link
        return link

    def remove_link(self, link):
        assert self.links.pop(link.index) is link

    def by_name(self, name):
        return next(x for x in self.links.values() if x.name == name)

    def by_mac(self, mac, domain, station=False):
        return next((x for x in self.links.values() if x.mac == mac and x.domain == domain
                     and x.type == N.NL80211_IFTYPE_STATION), None) or (
            None if station else next((x for x in self.links.values()
                                       if x.mac == mac and x.domain == domain and x.ap), None))

    def deliver_ip(self, link, data):
        for sock in self.sockets:
            if sock.fd >= 0 and sock.bound == (link.name, 0) and not isinstance(sock, AsyncRawSocket):
                sock.incoming.put(data)

    def broadcast(self, source, raw):
        self.radio_frames += 1
        rt = wlan.RadiotapFrame()
        rt.decode(raw)
        rt.frequency = self.frequencies[source.phy]
        rt.channel_flags = 0
        raw = rt.encode()
        header = wlan.MACHeader()
        header.decode(rt.data)
        for link in list(self.links.values()):
            if link.domain != source.domain or link.phy == source.phy:
                continue
            if self.frequencies[link.phy] != self.frequencies[source.phy]:
                continue
            if link.type == N.NL80211_IFTYPE_MONITOR:
                # Scanner needs a physical received-frequency radiotap field.
                for sock in self.sockets:
                    if isinstance(sock, AsyncRawSocket) and sock.fd >= 0 and sock.bound == (link.name, 0):
                        sock.incoming.put(raw)
            elif link.type == N.NL80211_IFTYPE_STATION and link.peer:
                if header.type == wlan.IEEE80211_FTYPE_MGMT:
                    link.kernel.event(N.NL80211_CMD_FRAME, {N.NL80211_ATTR_FRAME: rt.data,
                        N.NL80211_ATTR_WIPHY_FREQ: self.frequencies[source.phy]})
                elif header.type == wlan.IEEE80211_FTYPE_DATA and link.key:
                    frame = wlan.DataFrame()
                    frame.decode(rt.data)
                    frame.decrypt(link.key)
                    snap = wlan.SNAPHeader()
                    snap.decode(frame.payload)
                    self.deliver_ip(link, bytes(frame.target) + bytes(frame.source)
                                    + struct.pack("!H", snap.protocol) + snap.payload)
                    self.decrypted_frames += 1

    def facade(self):
        values = {name: getattr(socket, name) for name in dir(socket) if not name.startswith("__")}
        values.update(AF_PACKET=17, socket=lambda *a, **kw: RawSocket(self, *a, **kw),
            if_nameindex=lambda: [(x.index, x.name) for x in self.links.values()],
            if_nametoindex=lambda name: self.by_name(name).index,
            if_indextoname=lambda index: self.links[index].name)
        return SimpleNamespace(**values)

    @asynccontextmanager
    async def netlink(self):
        kernel = Kernel(self)
        token = CURRENT.set(kernel)
        try:
            yield kernel
        finally:
            CURRENT.reset(token)

    @asynccontextmanager
    async def route(self):
        yield Router(self)

    async def open_tap(self, path, *args, **kwargs):
        assert path == "/dev/net/tun"
        return TapFile(self)

    def ioctl(self, fd, command, request):
        assert command == wlan.TUNSETIFF
        file = next(x for x in self.files if x.fd == fd)
        name = request[:16].split(b"\0")[0].decode()
        ap = next(x for x in self.links.values() if x.kernel is file.kernel and x.ap)
        file.link = self.add_link(name, ap.phy, "tap", file.kernel)
        file.link.tap = file
        return request

    def install(self, stack):
        from switchtrade.connection import a_stage, data_plane, resource_scope, b_stage
        original_run = trio.run
        os = self

        class Factory:
            def socket(self, *args, **kwargs):
                return AsyncRawSocket(os, *args, **kwargs)

        def run(function, *args, **kwargs):
            async def entry():
                trio.socket.set_custom_socket_factory(Factory())
                return await function(*args)
            return original_run(entry, **kwargs)

        for target, attr, value in (
            (trio, "run", run), (N, "connect", self.netlink), (R, "connect", self.route),
            (trio, "open_file", self.open_tap), (wlan.fcntl, "ioctl", self.ioctl),
            (wlan, "socket", self.facade()), (data_plane, "socket", self.facade()),
            (a_stage, "socket", self.facade()), (resource_scope, "socket", self.facade()),
            (b_stage, "reset_selected_phy", lambda phy: {"selected_phy_only": True}),
            (wlan, "open", lambda *a, **kw: io.StringIO()),
            (ldn, "open", lambda *a, **kw: io.StringIO(KEY_TEXT)),
        ):
            stack.enter_context(patch.object(target, attr, value, create=True))

    def assert_clean(self):
        assert not self.links, [(x.name, x.type) for x in self.links.values()]
        assert all(x.fileno() == -1 for x in self.sockets), "owned raw socket residue"
        assert all(x.fileno() == -1 for x in self.files), "owned TAP file residue"
