"""P0 only: real stock frontend, public menu commands, and a two-round homebrew.

The harness owns its isolated test process. The product must NEVER import this
module or its launcher/config/menu helpers. No --connect, RESET, LOAD_* or memory
commands are used: content is running before the user-equivalent menu connection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time

from stock_reference import StockNetplayLaunch, write_isolated_retroarch_config
from window_input import OwnedProcess, PrivateDesktop, WindowInput

RA_HASH = "81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a"
CORE_HASH = "c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def packet(kind, header, body=b"", total=16):
    return (struct.pack("!III", 0x52465531, kind, header) + body).ljust(total, b"\0")


def receive(connection, deadline):
    while time.monotonic() < deadline:
        if connection.error:
            raise connection.error
        value = connection.receive(.02)
        if value:
            magic, kind, header = struct.unpack("!III", value.payload[:12])
            assert magic == 0x52465531 and value.peer_id == 1
            return kind, header, value.payload[12:]
    raise TimeoutError("P0_RFU_RECEIVE_TIMEOUT")


def exchange(connection, round_number):
    host, child = 0x1234 + round_number, 0x4567 + round_number
    deadline = time.monotonic() + 15
    while True:
        connection.send(packet(0, host, total=36))
        try:
            kind, header, _ = receive(connection, min(deadline, time.monotonic() + .1))
        except TimeoutError:
            if time.monotonic() >= deadline:
                raise
            continue
        assert (kind, header) == (1, host), (kind, header)
        break
    connection.send(packet(2, child))
    while True:
        kind, header, body = receive(connection, deadline)
        if kind == 1:
            connection.send(packet(2, child))
            continue
        assert kind == 6 and header >> 24 == 8 and header & 0xffff == child
        assert body[:8] == struct.pack("<II", 0x53544631, round_number), (
            "P0_GAME_RESET_OR_DATA_MISMATCH", body[:8].hex(), round_number)
        break
    connection.send(packet(5, 8, struct.pack("<II", 0x53544831, round_number), total=104))
    assert receive(connection, deadline)[:2] == (7, child)
    assert receive(connection, deadline)[:2] == (4, child)
    return {"round": round_number, "rfu": "bidirectional", "in_ram_counter": round_number}


def run(root: Path, fixture: Path, output: Path):
    root, fixture = root.resolve(strict=True), fixture.resolve(strict=True)
    executable, core = root / "retroarch.exe", root / "cores/gpsp_libretro.dll"
    assert digest(executable) == RA_HASH and digest(core) == CORE_HASH, "P0_BINARY_IDENTITY_MISMATCH"
    before = sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in root.rglob("*") if p.is_file())
    output.mkdir(parents=True, exist_ok=False)
    # Copy only stock runtime inputs. Never run the original tree: frontend exit
    # may write per-core options beside its executable despite --config.
    runtime = output / "runtime"
    runtime.mkdir()
    for source in (executable, *root.glob("*.dll")):
        shutil.copy2(source, runtime / source.name)
    (runtime / "cores").mkdir()
    shutil.copy2(core, runtime / "cores" / core.name)
    executable, core = (runtime / "retroarch.exe").resolve(), (runtime / "cores/gpsp_libretro.dll").resolve()
    assert digest(executable) == RA_HASH and digest(core) == CORE_HASH
    config = output / "retroarch.cfg"
    write_isolated_retroarch_config(config)
    launch = StockNetplayLaunch(content_path=fixture, handshake_timeout=20)
    # Test profile only: leave Quick Menu and Netplay as the first two main items.
    isolated_config = config.read_text().replace('video_driver = "null"', 'video_driver = "sdl2"')
    isolated_config = isolated_config.replace('input_driver = "null"', 'input_driver = "sdl2"')
    config.write_text(isolated_config + '\n' + '\n'.join((
        f'rgui_config_directory = "{(output / "core-config").resolve().as_posix()}"',
        'audio_enable = "false"', 'microphone_enable = "false"', 'midi_driver = "null"',
        'video_fullscreen = "false"', 'video_threaded = "false"',
        'user_language = "0"', 'menu_driver = "rgui"',
        'menu_show_start_screen = "false"', 'menu_pause_libretro = "false"',
        'menu_show_load_core = "false"', 'menu_show_load_content = "false"',
        'menu_show_load_disc = "false"', 'menu_show_dump_disc = "false"',
        'content_show_settings = "false"', 'content_show_playlists = "false"',
        'content_show_history = "false"', 'content_show_favorites = "false"',
        'content_show_add_entry = "2"', 'content_show_netplay = "true"',
        'menu_show_online_updater = "false"', 'menu_swap_ok_cancel_buttons = "false"',
        'netplay_ip_address = "127.0.0.1"', f'netplay_ip_port = "{launch.port}"',
        'config_save_on_exit = "false"', 'log_verbosity = "true"',
    )) + '\n', encoding="utf-8")
    transcript, rounds, socket_cleanup = [], [], []
    process = None
    controls = None
    desktop = None
    connection = None
    failure = None
    report = {"scope": "P0 stock attach only; not Core/physical qualification",
              "retroarch_sha256": RA_HASH, "gpsp_sha256": CORE_HASH,
              "fixture_sha256": digest(fixture), "passed": False}
    def command(value):
        transcript.append(value)
        controls.command(value)
    def connect_menu(round_number):
        # First open: Quick Menu -> Main -> Netplay -> Connect. The stock menu
        # retains the Connect selection when it returns to the running game.
        actions = ("MENU_TOGGLE", "MENU_A") if round_number > 1 else (
            "MENU_TOGGLE", "MENU_B", "MENU_DOWN", "MENU_A", "MENU_DOWN", "MENU_A")
        for value in actions:
            command(value)
    try:
        with (output / "frontend.log").open("w", encoding="utf-8") as log:
            desktop = PrivateDesktop()
            process = OwnedProcess([str(executable), "-v", "-L", str(core),
                "--config=" + str(config.resolve()), str(fixture)], cwd=output.resolve(),
                desktop=desktop, log=log)
            time.sleep(2)
            controls = WindowInput(process, desktop)
            status = (output / "frontend.log").read_text(encoding="utf-8")
            assert "SET_NETPACKET_INTERFACE" in status and "Geometry: 240x160" in status
            report["started_before_netplay"] = True
            report["input_method"] = "owned SDL window public key messages"
            with ThreadPoolExecutor(max_workers=1) as pool:
                for number in (1, 2):
                    opening = pool.submit(launch.open, process=None)
                    connect_menu(number)
                    connection = opening.result(timeout=25)
                    launch = None
                    rounds.append(exchange(connection, number))
                    assert process.poll() is None
                    socket_cleanup.append(connection.close())
                    if not socket_cleanup[-1]:
                        raise RuntimeError("P0_LOCAL_SOCKET_CLEANUP_FAILED")
                    connection = None
                    time.sleep(1)
                    assert process.poll() is None
                    if number == 1:
                        launch = StockNetplayLaunch(content_path=fixture, handshake_timeout=20)
                        # Must retain the original configured endpoint without rewriting settings.
                        launch.listener.close()
                        launch.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        port = int(next(line.split('"')[1] for line in config.read_text().splitlines()
                                        if line.startswith("netplay_ip_port")))
                        launch.listener.bind(("127.0.0.1", port))
                        launch.listener.listen(1)
                        launch.listener.settimeout(20)
                        launch.port = port
            report["same_process_two_rounds"] = True
            report["rounds"] = rounds
            report["passed"] = True
    except BaseException as error:
        failure = error
        report["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if connection is not None:
            report["connection_cleanup"] = connection.close()
        if launch is not None:
            report["listener_cleanup"] = launch.close()
        if process is not None:
            if process.poll() is None:
                if controls is not None:
                    command("QUIT")
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    report["test_process_forced_exit"] = True
                    process.terminate()
                    process.wait(timeout=5)
                    report["passed"] = False
            report["test_process_exit"] = process.returncode
            report["process_handle_cleanup"] = process.close()
        if desktop is not None:
            report["desktop_cleanup"] = desktop.close()
            report["passed"] = report["passed"] and report["desktop_cleanup"]
        report["socket_cleanup"] = socket_cleanup
        report["passed"] = report["passed"] and socket_cleanup == [True, True] and all(
            value for key, value in report.items() if key.endswith("_cleanup"))
        after = sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
                       for p in root.rglob("*") if p.is_file())
        report["stock_tree_unchanged"] = before == after
        report["stock_tree_delta"] = sorted(set(before) ^ set(after))
        report["commands"] = transcript
        report["rounds"] = rounds
        report["passed"] = report["passed"] and before == after
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)
    if failure:
        raise failure
    if not report["passed"]:
        raise RuntimeError("P0_NOT_PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "fixture", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(**vars(parser.parse_args()))
