"""Exercise the Docker-selected source set and command without Docker or hardware."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import websockets

from switchtrade.core.contracts import MAX_PACKET_BYTES, PairSeat
from switchtrade.transport.wire import Envelope, FrameKind, HEADER, MAX_GENERATION_ID_BYTES


ROOT = Path(__file__).resolve().parents[1]
DOCKER = (ROOT / "relay/Dockerfile").read_text(encoding="utf-8")
COMMAND = json.loads(next(line[4:] for line in DOCKER.splitlines() if line.startswith("CMD ")))


def test_core_deployment_configuration():
    assert COMMAND[:3] == ["uvicorn", "relay.core_server:create_app", "--factory"]
    assert COMMAND[COMMAND.index("--workers") + 1] == "1"
    assert int(COMMAND[COMMAND.index("--ws-max-size") + 1]) >= MAX_PACKET_BYTES + HEADER.size + MAX_GENERATION_ID_BYTES
    assert COMMAND[COMMAND.index("--ws-max-queue") + 1] == "8"
    assert "--no-access-log" in COMMAND
    assert COMMAND[COMMAND.index("--log-level") + 1] == "warning"
    assert "--proxy-headers" in COMMAND
    assert "USER 10001" in DOCKER
    compose = (ROOT / "relay/compose.yaml").read_text(encoding="utf-8")
    assert "/core/health" in compose and "switchtrade-core-relay" in compose
    assert "SWITCHTRADE_RELAY_REVISION:?" in compose
    assert "SWITCHTRADE_RELAY_TRUSTED_PROXIES:?" in compose
    assert "127.0.0.1:8788:8788" in compose and "read_only: true" in compose
    for legacy in ("authority.sqlite3", "SWITCHTRADE_AUTH_DB", "SWITCHTRADE_ENABLE_LEGACY_RELAY", "volumes:"):
        assert legacy not in compose


def test_packaged_command_serves_core_and_opaque_websockets(tmp_path):
    # Reproduce the actual source COPY set; a repo import could conceal missing files.
    for line in DOCKER.splitlines():
        if not line.startswith("COPY --chown="):
            continue
        *sources, target = line.split()[2:]
        destination = tmp_path / target
        for source in sources:
            path = ROOT / source
            if path.is_dir():
                shutil.copytree(path, destination, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination / path.name)
    assert not (tmp_path / "relay/server.py").exists()
    assert not (tmp_path / "switchtrade/endpoints").exists()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = COMMAND[1:].copy()
    command[command.index("--host") + 1] = "127.0.0.1"
    command[command.index("--port") + 1] = str(port)
    bootstrap = """
import sys
sys.path.insert(0, sys.argv.pop(1))
from relay.core_server import create_app
assert not any(name in sys.modules for name in ('relay.server', 'relay.authority',
    'switchtrade.endpoints', 'switchtrade.connection', 'ldn', 'bridge'))
from uvicorn.main import main
main()
"""
    revision = "a" * 40
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", bootstrap, str(tmp_path), *command],
        cwd=tmp_path, env={**os.environ, "SWITCHTRADE_RELAY_REVISION": revision},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base + path, data, {"Content-Type": "application/json"}), timeout=2) as response:
            return json.load(response)

    try:
        deadline = time.monotonic() + 15
        while True:
            assert process.poll() is None, "packaged Core process exited before readiness"
            try:
                health = request("/core/health")
                break
            except URLError:
                assert time.monotonic() < deadline, "packaged Core startup deadline"
                time.sleep(0.05)
        assert health == {"status": "ok", "service": "switchtrade-core-relay",
                          "contract_version": "switchtrade-pair.v1", "source_revision": revision}
        for path in ("/health", "/v1/trade-rooms", "/session/create"):
            try:
                request(path)
            except HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError("legacy route mounted by Core")
        capabilities = {"endpoint_kind": "switch_ldn", "runtime_kind": "managed_wsl",
                        "protocols": ["switchtrade.gba-frame.v1"], "generation_roles": ["origin"]}
        host = request("/core/v1/pairs", {"capabilities": capabilities})
        guest = request("/core/v1/pairs:join", {"code": host["code"], "capabilities": {
            **capabilities, "endpoint_kind": "retroarch_gpsp", "runtime_kind": "native",
            "generation_roles": ["mirror"]}})

        async def exchange():
            uri = f"ws://127.0.0.1:{port}/core/v1/pairs/{host['pair_id']}/ws"
            async with asyncio.timeout(5):
                async with websockets.connect(uri, additional_headers={"Authorization": f"Bearer {host['access_token']}"}, proxy=None) as left:
                    assert json.loads(await left.recv()) == {"seat": "host"}
                    async with websockets.connect(uri, additional_headers={"Authorization": f"Bearer {guest['access_token']}"}, proxy=None) as right:
                        assert json.loads(await right.recv()) == {"seat": "guest"}
                        for sender, receiver, seat in ((left, right, PairSeat.HOST), (right, left, PairSeat.GUEST)):
                            raw = Envelope(FrameKind.DATA, seat, 1, 0, "deployment-smoke", b"opaque", 0x0100).encode()
                            await sender.send(raw)
                            assert await receiver.recv() == raw
        asyncio.run(exchange())
    finally:
        # Only this test owns this child. Never find/kill another process by port/name.
        process.terminate()
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise AssertionError("packaged Core child did not stop")
        assert process.poll() is not None
