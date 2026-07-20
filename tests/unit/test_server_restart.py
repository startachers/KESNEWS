from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.maintenance import restart as restart_service
from scripts import restart_server


def test_schedule_restart_starts_detached_local_helper(monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(restart_service.subprocess, "Popen", fake_popen)

    restart_service.schedule_server_restart(1234)

    assert captured["command"][-2:] == [str(restart_service.RESTART_HELPER), "1234"]
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["close_fds"] is True


def test_helper_uses_launchd_kickstart_for_managed_parent(monkeypatch):
    commands = []
    sleeps = []
    monkeypatch.setattr(restart_server.time, "sleep", sleeps.append)
    monkeypatch.setattr(restart_server, "launchd_server_pid", lambda: 1234)
    monkeypatch.setattr(restart_server, "log", lambda _message: None)
    monkeypatch.setattr(
        restart_server.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    assert restart_server.restart(1234) == 0
    assert sleeps == [2.0]
    assert commands == [
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{restart_server.os.getuid()}/{restart_server.LAUNCHD_LABEL}",
        ]
    ]


def test_helper_replaces_manual_server_after_parent_exits(monkeypatch):
    signals = []
    monkeypatch.setattr(restart_server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(restart_server, "launchd_server_pid", lambda: None)
    monkeypatch.setattr(restart_server, "process_exists", lambda _pid: False)
    monkeypatch.setattr(restart_server, "log", lambda _message: None)
    monkeypatch.setattr(
        restart_server.os, "kill", lambda pid, sig: signals.append((pid, sig))
    )

    def fake_execv(executable, command):
        raise RuntimeError((executable, command))

    monkeypatch.setattr(restart_server.os, "execv", fake_execv)

    with pytest.raises(RuntimeError) as raised:
        restart_server.restart(4321)

    executable, command = raised.value.args[0]
    assert signals == [(4321, restart_server.signal.SIGTERM)]
    assert executable == restart_server.sys.executable
    assert command[-1] == str(restart_server.RUN_SERVER)
