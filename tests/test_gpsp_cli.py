"""Native CLI and actual PowerShell routing checks; real-process P4 is separate."""
import asyncio
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from switchtrade import core_cli as cli
from switchtrade.endpoints.retroarch_gpsp.driver import RetroArchGpspEndpointDriver
from switchtrade.endpoints.retroarch_gpsp.errors import GpspError
from switchtrade.core.contracts import CleanupReport

ROOT = Path(__file__).resolve().parents[1]


def test_native_imports_do_not_load_switch_or_ldn():
    code = "import sys; import switchtrade.core_cli; from switchtrade.composition import create_retroarch_gpsp_driver; create_retroarch_gpsp_driver(); assert not any(x.startswith(('switchtrade.endpoints.switch_ldn','switchtrade.connection','switchtrade.hardware','ldn','trio')) for x in sys.modules)"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, timeout=10)


def test_native_parser_does_not_require_usb_and_accepts_public_command_order():
    with patch.dict(os.environ, {}, clear=True):
        value = cli.parser().parse_args(["join", "003817", "--emulator", "gpsp", "--emulator-port", "55436", "--emulator-pid", "42"])
    assert (value.code, value.emulator, value.emulator_port, value.emulator_pid, value.usb_id) == ("003817", "gpsp", 55436, 42, None)


def test_no_emulator_fails_before_pair_and_does_not_print_technical_code():
    first = GpspError("RETROARCH_NOT_RUNNING", "RetroArch에서 gpSP로 게임을 실행한 뒤 다시 시도하세요.")
    driver = SimpleNamespace(prepare=AsyncMock(side_effect=first), close=AsyncMock(return_value=CleanupReport(True, True, True)))
    output = io.StringIO()
    with patch.object(cli, "create_retroarch_gpsp_driver", return_value=driver), patch.object(cli, "_request", AsyncMock()) as request, redirect_stdout(output):
        assert cli.main(["join", "003817", "--emulator", "gpsp"]) == 1
    request.assert_not_awaited()
    driver.close.assert_awaited_once()
    assert first.message in output.getvalue()
    assert first.code not in output.getvalue()
    assert "Bridge active" not in output.getvalue()


def test_native_waits_for_actual_rfu_before_bridge_message_and_preserves_endpoint():
    asyncio.run(_waits_for_actual_rfu())


async def _waits_for_actual_rfu():
    ready, finished = asyncio.Event(), asyncio.Event()
    generation = SimpleNamespace(wait_link_ready=ready.wait)
    supervisor = SimpleNamespace(wait_generation_end=finished.wait)
    output = io.StringIO()
    with redirect_stdout(output):
        pending = asyncio.create_task(cli._wait_gpsp_bridge(supervisor, generation))
        await asyncio.sleep(.02)
        assert "Bridge active" not in output.getvalue()
        ready.set()
        await asyncio.sleep(.02)
        assert "Bridge active." in output.getvalue()
        finished.set()
        await pending


def test_generation_end_before_game_input_cancels_ready_wait():
    asyncio.run(_end_before_input())


async def _end_before_input():
    finished = asyncio.Event()
    supervisor = SimpleNamespace(wait_generation_end=finished.wait)
    generation = SimpleNamespace(wait_link_ready=asyncio.Event().wait)
    output = io.StringIO()
    with redirect_stdout(output):
        pending = asyncio.create_task(cli._wait_gpsp_bridge(supervisor, generation))
        await asyncio.sleep(0)
        finished.set()
        await asyncio.wait_for(pending, .5)
    assert "Bridge active" not in output.getvalue()


def test_native_code_capabilities_user_flow_and_cleanup():
    asyncio.run(_native_flow())


async def _native_flow():
    class StopTest(Exception):
        pass
    driver = SimpleNamespace(prepare=AsyncMock(), capabilities=RetroArchGpspEndpointDriver.capabilities, generation=object())
    supervisor = SimpleNamespace(accept_next_offer=AsyncMock(side_effect=[None, StopTest()]), stop=AsyncMock())
    credentials = {"pair_id": "test", "access_token": "test", "reconnect_expires_at": "2099-01-01T00:00:00+00:00"}
    args = cli.parser().parse_args(["join", "003817", "--emulator", "gpsp"])
    with patch.object(cli, "create_retroarch_gpsp_driver", return_value=driver), \
         patch.object(cli, "_request", AsyncMock(return_value=credentials)) as request, \
         patch.object(cli, "_socket", AsyncMock()), patch.object(cli.WireClient, "connect", AsyncMock()), \
         patch.object(cli, "CoreSupervisor", return_value=supervisor), \
         patch.object(cli, "_wait_gpsp_bridge", AsyncMock()) as bridge:
        with pytest.raises(StopTest):
            await cli.run(args)
    assert request.call_args.args[2]["capabilities"] == {
        "endpoint_kind": "retroarch_gpsp", "runtime_kind": "native", "protocols": ["switchtrade.gba-frame.v1"], "generation_roles": ["mirror"]}
    driver.prepare.assert_awaited_once()
    bridge.assert_awaited_once_with(supervisor, driver.generation)
    supervisor.stop.assert_awaited_once()


@pytest.mark.parametrize("arguments", [
    ["run", "host", "--emulator", "gpsp"],
    ["run", "join", "003817", "--emulator", "mgba"],
    ["run", "join", "003817", "--emulator", "gpsp", "--usb-id", "0bda:818b"],
    ["run", "join", "003817", "--emulator", "gpsp", "--emulator-port", "0"],
    ["doctor", "--emulator", "gpsp", "--emulator-pid", "0"],
])
def test_native_invalid_arguments_never_reach_wsl_or_environment(arguments, tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable; Windows final qualification requires it")
    result = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "dev.ps1"), *arguments],
        cwd=ROOT, env={**os.environ, "LOCALAPPDATA": str(tmp_path), "SWITCHTRADE_NATIVE_PYTHON": str(tmp_path / "missing.exe")},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "DEV_CORE_ARGUMENT_INVALID" in result.stderr
    assert "DEV_ACTIVE_RUNTIME" not in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows emulator process boundary")
def test_actual_dev_native_doctor_uses_python_without_wsl(tmp_path):
    # A nonexistent explicit PID avoids interacting with any user's emulator.
    pwsh = shutil.which("pwsh")
    assert pwsh
    result = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "dev.ps1"), "doctor",
        "--emulator", "gpsp", "--emulator-pid", "4294967295"], cwd=ROOT,
        env={**os.environ, "LOCALAPPDATA": str(tmp_path), "SWITCHTRADE_NATIVE_PYTHON": sys.executable},
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "지정한 RetroArch PID" in result.stdout, (result.stdout, result.stderr)
    assert "DEV_ACTIVE_RUNTIME" not in result.stderr
    assert "Traceback" not in result.stderr
