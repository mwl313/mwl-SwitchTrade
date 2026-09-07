from pathlib import Path

import pytest

from switchtrade.endpoints.retroarch_gpsp import process as p
from switchtrade.endpoints.retroarch_gpsp.errors import GpspError


@pytest.fixture
def observed(monkeypatch):
    identity = p.ProcessIdentity(123, Path("retroarch.exe"), 456)
    core = Path("gpsp_libretro.dll")
    monkeypatch.setattr(p, "_unsupported", lambda: None)
    monkeypatch.setattr(p, "_entries", lambda pid, modules=False: [core] if modules else [(123, "RetroArch.exe")])
    monkeypatch.setattr(p, "_identity", lambda pid: identity)
    monkeypatch.setattr(p, "_digest", lambda path: p.RETROARCH_SHA256 if path == identity.executable else p.GPSP_SHA256)
    monkeypatch.setattr(p, "_tcp_owners", lambda local, remote: {123})
    return identity, core


def test_observer_selects_exact_loaded_process_and_socket(observed):
    observer = p.ProcessObserver.select()
    assert observer.identity == observed[0]
    observer.check_connection(60000, 55435)
    assert not hasattr(observer, "terminate") and not hasattr(observer, "start")


def test_missing_multiple_and_explicit_pid(observed, monkeypatch):
    monkeypatch.setattr(p, "_entries", lambda pid, modules=False: [observed[1]] if modules else [])
    with pytest.raises(GpspError) as result:
        p.ProcessObserver.select()
    assert result.value.code == "RETROARCH_NOT_RUNNING"
    monkeypatch.setattr(p, "_entries", lambda pid, modules=False: [observed[1]] if modules else [(123, "retroarch.exe"), (789, "retroarch.exe")])
    with pytest.raises(GpspError) as result:
        p.ProcessObserver.select()
    assert result.value.code == "RETROARCH_AMBIGUOUS"
    assert p.ProcessObserver.select(123).identity.pid == 123
    with pytest.raises(GpspError) as result:
        p.ProcessObserver.select(999)
    assert result.value.code == "EMULATOR_PID_NOT_FOUND"


@pytest.mark.parametrize("phase", ["process", "module", "hash", "tcp"])
def test_unknown_query_is_never_reported_absent(observed, monkeypatch, phase):
    observer = p.ProcessObserver.select()
    failure = GpspError("EMULATOR_QUERY_FAILED", "denied")
    def denied(*args, **kwargs):
        raise failure
    monkeypatch.setattr(p, {"process": "_identity", "module": "_entries", "hash": "_digest", "tcp": "_tcp_owners"}[phase], denied)
    with pytest.raises(GpspError) as result:
        observer.check_connection(1, 2) if phase == "tcp" else p.ProcessObserver.select()
    assert result.value is failure


@pytest.mark.parametrize("bad", ["frontend", "core", "wrong_core"])
def test_wrong_binary_or_core_is_rejected(observed, monkeypatch, bad):
    if bad == "wrong_core":
        monkeypatch.setattr(p, "_entries", lambda pid, modules=False: [Path("other_libretro.dll")] if modules else [(123, "retroarch.exe")])
    else:
        monkeypatch.setattr(p, "_digest", lambda path: "bad" if bad == "frontend" or path == observed[1] else p.RETROARCH_SHA256)
    with pytest.raises(GpspError) as result:
        p.ProcessObserver.select()
    assert result.value.code == {"frontend": "RETROARCH_UNSUPPORTED_BUILD", "core": "GPSP_UNSUPPORTED_BUILD", "wrong_core": "GPSP_CORE_NOT_LOADED"}[bad]


def test_pid_reuse_core_unload_and_foreign_socket_are_rejected(observed, monkeypatch):
    observer = p.ProcessObserver.select()
    monkeypatch.setattr(p, "_identity", lambda pid: p.ProcessIdentity(123, observed[0].executable, 999))
    with pytest.raises(GpspError) as result:
        observer.check()
    assert result.value.code == "EMULATOR_IDENTITY_CHANGED"
    monkeypatch.setattr(p, "_identity", lambda pid: observed[0])
    monkeypatch.setattr(p, "_tcp_owners", lambda local, remote: {789})
    with pytest.raises(GpspError) as result:
        observer.check_connection(1, 2)
    assert result.value.code == "EMULATOR_SOCKET_IDENTITY_MISMATCH"
    monkeypatch.setattr(p, "_entries", lambda *args, **kwargs: [])
    with pytest.raises(GpspError) as result:
        observer.check()
    assert result.value.code == "EMULATOR_CORE_CHANGED"
