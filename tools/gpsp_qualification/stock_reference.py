# P0 test-only stock protocol reference, adapted from fbd2776.
# Not imported by product code; launch/configuration belong only to the harness.
"""Loopback RetroArch 1.22.2 netpacket host for an unmodified gpSP core."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import queue
import shutil
import socket
import struct
import threading
from typing import Final
import uuid



NETPLAY_MAGIC: Final = 0x52414E50  # RANP
NETPLAY_PROTOCOL: Final = 7
NETPLAY_CMD_DISCONNECT: Final = 0x0002
NETPLAY_CMD_NICK: Final = 0x0020
NETPLAY_CMD_INFO: Final = 0x0022
NETPLAY_CMD_SYNC: Final = 0x0023
NETPLAY_CMD_PLAY: Final = 0x0025
NETPLAY_CMD_MODE: Final = 0x0026
NETPLAY_CMD_NETPACKET: Final = 0x0048
NETPLAY_CMD_PING_REQUEST: Final = 0x1100
NETPLAY_CMD_PING_RESPONSE: Final = 0x1101
NETPLAY_NICK_LEN: Final = 32
MAX_INPUT_DEVICES: Final = 16
MAX_RFU1_PAYLOAD: Final = 104
MAX_QUEUED_PACKETS: Final = 256
CORE_NAME: Final = b"gpSP"
CORE_PROTOCOL: Final = b"gpSP v1.0"


class StockNetplayError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.gate = "E2_STOCK_HANDSHAKE"
        self.message = message


@dataclass(frozen=True)
class CorePacket:
    payload: bytes
    peer_id: int
    sequence: int


def retroarch_impl_magic(version: str = "1.22.2") -> int:
    value = 0
    encoded = version.encode("ascii")
    for index, byte in enumerate(encoded):
        value ^= byte << (index & 0xF)
    return value ^ (NETPLAY_PROTOCOL << (len(encoded) & 0xF))


def _fixed(value: bytes, size: int) -> bytes:
    if len(value) >= size:
        raise StockNetplayError("STOCK_NETPLAY_FIELD_TOO_LONG", "Netplay identity is too long")
    return value + b"\0" * (size - len(value))


def write_isolated_retroarch_config(config_path: Path, *, interactive: bool = False,
                                    persistent_data_root: Path | None = None) -> None:
    """Create a private config; physical runs retain only save and system data."""
    runtime_root = config_path.parent.resolve(strict=False)
    directories = {
        name: runtime_root / name for name in (
            "assets", "cache", "core-assets", "core-info", "logs", "playlists",
            "recordings", "remaps", "saves", "screenshots", "states", "system",
            "thumbnails")
    }
    if interactive:
        if persistent_data_root is None:
            raise StockNetplayError(
                "STOCK_NETPLAY_PERSISTENT_DATA_REQUIRED",
                "Interactive RetroArch needs an owned persistent data directory")
        persistent_data_root = persistent_data_root.resolve(strict=False)
        directories["saves"] = persistent_data_root / "saves"
        directories["system"] = persistent_data_root / "system"
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)

    def path_value(path: Path) -> str:
        return path.resolve(strict=False).as_posix()

    playlists = directories["playlists"]
    core_options_path = runtime_root / "core-options.cfg"
    try:
        with core_options_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write('gpsp_serial = "rfu"\n')
    except OSError as error:
        raise StockNetplayError(
            "STOCK_NETPLAY_CONFIG_FAILED", "The isolated gpSP options could not be created") from error
    drivers = "" if interactive else (
        'video_driver = "null"\n'
        'audio_driver = "null"\n'
        'input_driver = "null"\n'
        'joypad_driver = "null"\n'
    )
    config = (
        drivers +
        'config_save_on_exit = "false"\n'
        'history_list_enable = "false"\n'
        'core_info_cache_enable = "false"\n'
        'netplay_public_announce = "false"\n'
        'netplay_use_mitm_server = "false"\n'
        'netplay_start_as_spectator = "false"\n'
        'pause_nonactive = "false"\n'
        'rewind_enable = "false"\n'
        'run_ahead_enabled = "false"\n'
        'savestate_auto_load = "false"\n'
        'savestate_auto_save = "false"\n'
        f'assets_directory = "{path_value(directories["assets"])}"\n'
        f'cache_directory = "{path_value(directories["cache"])}"\n'
        f'core_assets_directory = "{path_value(directories["core-assets"])}"\n'
        f'libretro_info_path = "{path_value(directories["core-info"])}"\n'
        f'log_dir = "{path_value(directories["logs"])}"\n'
        f'runtime_log_directory = "{path_value(directories["logs"])}"\n'
        f'playlist_directory = "{path_value(playlists)}"\n'
        f'content_history_directory = "{path_value(playlists)}"\n'
        f'content_favorites_directory = "{path_value(playlists)}"\n'
        f'content_image_history_directory = "{path_value(playlists)}"\n'
        f'content_music_history_directory = "{path_value(playlists)}"\n'
        f'content_video_directory = "{path_value(playlists)}"\n'
        f'content_history_path = "{path_value(playlists / "content_history.lpl")}"\n'
        f'content_favorites_path = "{path_value(playlists / "content_favorites.lpl")}"\n'
        f'content_image_history_path = "{path_value(playlists / "content_image_history.lpl")}"\n'
        f'content_music_history_path = "{path_value(playlists / "content_music_history.lpl")}"\n'
        f'content_video_history_path = "{path_value(playlists / "content_video_history.lpl")}"\n'
        f'core_options_path = "{path_value(core_options_path)}"\n'
        f'input_remapping_directory = "{path_value(directories["remaps"])}"\n'
        f'recording_output_directory = "{path_value(directories["recordings"])}"\n'
        f'recording_config_directory = "{path_value(directories["recordings"])}"\n'
        f'savefile_directory = "{path_value(directories["saves"])}"\n'
        f'savestate_directory = "{path_value(directories["states"])}"\n'
        f'screenshot_directory = "{path_value(directories["screenshots"])}"\n'
        f'system_directory = "{path_value(directories["system"])}"\n'
        f'thumbnails_directory = "{path_value(directories["thumbnails"])}"\n'
    )
    try:
        with config_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(config)
    except OSError as error:
        raise StockNetplayError(
            "STOCK_NETPLAY_CONFIG_FAILED", "The isolated RetroArch config could not be created") from error


def _cleanup_config(config_path: Path | None, cleanup_root: Path | None) -> bool:
    try:
        if config_path is not None:
            config_path.unlink(missing_ok=True)
        if cleanup_root is not None and cleanup_root.exists():
            shutil.rmtree(cleanup_root)
    except OSError:
        return False
    return True


def _recv_exact(stream: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            value = stream.recv(size - len(chunks))
        except socket.timeout as error:
            raise StockNetplayError(
                "STOCK_NETPLAY_TIMEOUT", "Stock RetroArch did not complete its handshake") from error
        except OSError as error:
            raise StockNetplayError(
                "STOCK_NETPLAY_SOCKET_FAILED", "Stock RetroArch netplay socket failed") from error
        if not value:
            raise StockNetplayError(
                "STOCK_NETPLAY_CLOSED", "Stock RetroArch closed its netplay connection")
        chunks.extend(value)
    return bytes(chunks)


class StockNetplayConnection:
    """One bounded RetroArch client connection after a complete stock handshake."""

    def __init__(self, stream: socket.socket, listener: socket.socket, *, nickname: bytes,
                 config_path: Path | None = None, cleanup_root: Path | None = None):
        self._stream = stream
        self._listener = listener
        self._nickname = nickname
        self._config_path = config_path
        self._cleanup_root = cleanup_root
        self._packets: queue.Queue[CorePacket] = queue.Queue(MAX_QUEUED_PACKETS)
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._error: StockNetplayError | None = None
        self._receive_sequence = 0
        self._thread = threading.Thread(
            target=self._read_loop, name="stock-retroarch-netpacket", daemon=True)
        self._thread.start()

    @property
    def error(self) -> StockNetplayError | None:
        return self._error

    def poll(self) -> bool:
        return self._error is None and not self._stop.is_set() and self._thread.is_alive()

    def receive(self, timeout: float = 0.0) -> CorePacket | None:
        try:
            return self._packets.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def send(self, payload: bytes, *, peer_id: int = 0) -> None:
        if not 12 <= len(payload) <= MAX_RFU1_PAYLOAD:
            raise StockNetplayError(
                "STOCK_NETPACKET_SIZE_INVALID", "RFU1 payload length is outside the supported range")
        if not 0 <= peer_id <= 0xFFFF:
            raise StockNetplayError(
                "STOCK_NETPACKET_PEER_INVALID", "RFU1 peer identity is outside the supported range")
        frame = struct.pack("!III", NETPLAY_CMD_NETPACKET, len(payload), peer_id) + payload
        self._send(frame)

    def close(self) -> bool:
        self._stop.set()
        try:
            self._stream.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for resource in (self._stream, self._listener):
            try:
                resource.close()
            except OSError:
                pass
        self._thread.join(timeout=2.0)
        return not self._thread.is_alive() and _cleanup_config(
            self._config_path, self._cleanup_root)

    def _send(self, value: bytes) -> None:
        with self._send_lock:
            try:
                self._stream.sendall(value)
            except OSError as error:
                raise StockNetplayError(
                    "STOCK_NETPLAY_SOCKET_FAILED", "Stock RetroArch netplay socket failed") from error

    def _read_loop(self) -> None:
        try:
            self._stream.settimeout(0.25)
            while not self._stop.is_set():
                try:
                    header = self._stream.recv(8, socket.MSG_PEEK)
                except socket.timeout:
                    continue
                except OSError as error:
                    if self._stop.is_set():
                        return
                    raise StockNetplayError(
                        "STOCK_NETPLAY_SOCKET_FAILED",
                        "Stock RetroArch netplay socket failed") from error
                if not header:
                    raise StockNetplayError(
                        "STOCK_NETPLAY_CLOSED", "Stock RetroArch closed its netplay connection")
                if len(header) < 8:
                    continue
                command, size = struct.unpack("!II", _recv_exact(self._stream, 8))
                if command == NETPLAY_CMD_NETPACKET:
                    if not 12 <= size <= MAX_RFU1_PAYLOAD:
                        raise StockNetplayError(
                            "STOCK_NETPACKET_SIZE_INVALID", "RetroArch sent an invalid RFU1 length")
                    peer_id = struct.unpack("!I", _recv_exact(self._stream, 4))[0]
                    if peer_id not in (0, 0xFFFF):
                        raise StockNetplayError(
                            "STOCK_NETPACKET_PEER_INVALID", "RetroArch addressed an invalid RFU1 peer")
                    self._receive_sequence += 1
                    packet = CorePacket(
                        _recv_exact(self._stream, size), 1, self._receive_sequence)
                    try:
                        self._packets.put_nowait(packet)
                    except queue.Full as error:
                        raise StockNetplayError(
                            "STOCK_NETPACKET_QUEUE_FULL", "The RFU1 receive queue is saturated") from error
                elif command == NETPLAY_CMD_PING_REQUEST and size == 0:
                    self._send(struct.pack("!II", NETPLAY_CMD_PING_RESPONSE, 0))
                elif command == NETPLAY_CMD_PING_RESPONSE and size == 0:
                    continue
                elif command == NETPLAY_CMD_DISCONNECT and size == 0:
                    self._stop.set()
                else:
                    if size:
                        _recv_exact(self._stream, size)
                    raise StockNetplayError(
                        "STOCK_NETPLAY_COMMAND_INVALID", "RetroArch sent an unsupported netplay command")
        except StockNetplayError as error:
            if not self._stop.is_set():
                self._error = error
            self._stop.set()


class StockNetplayLaunch:
    """Pre-bound listener and private config that exist before RetroArch starts."""

    def __init__(self, *, content_path: Path, config_path: Path | None = None,
                 cleanup_root: Path | None = None, handshake_timeout: float = 10.0):
        if not content_path.is_file():
            raise StockNetplayError(
                "EMULATOR_CONTENT_NOT_FOUND", "The selected GBA content is unavailable")
        self.content_path = content_path.resolve(strict=True)
        self.config_path = config_path
        self.cleanup_root = cleanup_root
        self.handshake_timeout = handshake_timeout
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(handshake_timeout)
        self.port = int(self.listener.getsockname()[1])

    @property
    def arguments(self) -> tuple[str, ...]:
        values = [f"--connect=127.0.0.1", f"--port={self.port}"]
        if self.config_path is not None:
            values.append(f"--config={self.config_path}")
        values.append(str(self.content_path))
        return tuple(values)

    def open(self, *, process: ProcessHandle) -> StockNetplayConnection:
        del process  # Process identity is owned and polled by EmulatorRunner.
        try:
            stream, address = self.listener.accept()
        except socket.timeout as error:
            self.close()
            raise StockNetplayError(
                "STOCK_NETPLAY_ACCEPT_TIMEOUT", "Stock RetroArch did not connect to the local bridge") from error
        if address[0] != "127.0.0.1":
            stream.close()
            self.close()
            raise StockNetplayError(
                "STOCK_NETPLAY_REMOTE_REJECTED", "Only a loopback RetroArch client is accepted")
        stream.settimeout(self.handshake_timeout)
        try:
            nickname = self._handshake(stream)
        except BaseException:
            stream.close()
            self.close()
            raise
        return StockNetplayConnection(
            stream, self.listener, nickname=nickname, config_path=self.config_path,
            cleanup_root=self.cleanup_root)

    def close(self) -> bool:
        try:
            self.listener.close()
        except OSError:
            return False
        return _cleanup_config(self.config_path, self.cleanup_root)

    @staticmethod
    def _handshake(stream: socket.socket) -> bytes:
        header = struct.unpack("!6I", _recv_exact(stream, 24))
        if header[0] != NETPLAY_MAGIC or max(header[3], header[4]) < NETPLAY_PROTOCOL:
            raise StockNetplayError(
                "STOCK_NETPLAY_PROTOCOL_MISMATCH", "RetroArch netplay protocol is incompatible")
        stream.sendall(struct.pack(
            "!6I", NETPLAY_MAGIC, header[1], 0, 0, NETPLAY_PROTOCOL, retroarch_impl_magic()))

        command, size = struct.unpack("!II", _recv_exact(stream, 8))
        if command != NETPLAY_CMD_NICK or size != NETPLAY_NICK_LEN:
            raise StockNetplayError(
                "STOCK_NETPLAY_NICK_INVALID", "RetroArch sent an invalid netplay nickname")
        nickname = _recv_exact(stream, NETPLAY_NICK_LEN)
        nickname = nickname[:-1] + b"\0"
        server_nick = _fixed(b"SwitchTrade", NETPLAY_NICK_LEN)
        stream.sendall(struct.pack("!II", NETPLAY_CMD_NICK, NETPLAY_NICK_LEN) + server_nick)

        info = struct.pack("!I", 0) + _fixed(CORE_NAME, NETPLAY_NICK_LEN) + _fixed(
            CORE_PROTOCOL, NETPLAY_NICK_LEN)
        stream.sendall(struct.pack("!II", NETPLAY_CMD_INFO, len(info)) + info)

        command, size = struct.unpack("!II", _recv_exact(stream, 8))
        if command != NETPLAY_CMD_INFO or size != 68:
            raise StockNetplayError(
                "STOCK_NETPLAY_INFO_INVALID", "RetroArch sent invalid core identity information")
        client_info = _recv_exact(stream, size)
        core_name = client_info[4:36].split(b"\0", 1)[0]
        core_protocol = client_info[36:68].split(b"\0", 1)[0]
        if core_name.lower() != CORE_NAME.lower() or core_protocol != CORE_PROTOCOL:
            raise StockNetplayError(
                "STOCK_GPSP_PROTOCOL_MISMATCH", "The stock gpSP netpacket protocol is incompatible")

        sync = struct.pack("!II", 0, 1)
        sync += b"\0" * (MAX_INPUT_DEVICES * 4)
        sync += b"\0" * MAX_INPUT_DEVICES
        sync += b"\0" * (MAX_INPUT_DEVICES * 4)
        sync += nickname
        stream.sendall(struct.pack("!II", NETPLAY_CMD_SYNC, len(sync)) + sync)

        command, size = struct.unpack("!II", _recv_exact(stream, 8))
        if command != NETPLAY_CMD_PLAY or size != 4:
            raise StockNetplayError(
                "STOCK_NETPLAY_PLAY_REQUIRED", "RetroArch did not enter core-packet play mode")
        _recv_exact(stream, 4)
        mode = struct.pack("!III", 0, 0xC0000001, 0)
        mode += b"\0" * MAX_INPUT_DEVICES + nickname
        stream.sendall(struct.pack("!II", NETPLAY_CMD_MODE, len(mode)) + mode)
        return nickname
