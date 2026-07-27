from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from mahavishnu.workers.contract.tmux_adapter import (
    TmuxAdapterError,
    TmuxSessionInfo,
    capture_pane,
    create_session,
    kill_session,
    list_sessions,
    pane_alive,
    send_keys,
)

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux binary not on PATH"
)


@pytest.fixture
def socket_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    # Use /tmp on macOS/Linux so the socket path stays under the
    # `sun_path` limit (104 bytes on macOS, 108 on Linux). The
    # default pytest tmp_path on macOS resolves under
    # /private/var/folders/.../T/pytest-of-.../ which exceeds it.
    base = pathlib.Path("/tmp") / "mhv-tmux-test"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "test.sock")


def _run(args: list[str], socket: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", "-S", socket, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_create_session_returns_metadata(socket_path: str) -> None:
    info = create_session(
        socket=socket_path,
        session="test",
        window_name="main",
        command=["sh", "-c", "sleep 30"],
    )
    assert isinstance(info, TmuxSessionInfo)
    assert info.session == "test"
    assert info.socket == socket_path
    assert info.pane.startswith("%")
    assert pane_alive(socket_path, info.pane)
    kill_session(socket_path, "test")
    assert not pane_alive(socket_path, info.pane)


def test_send_keys_and_capture_pane(socket_path: str) -> None:
    info = create_session(
        socket=socket_path,
        session="echo",
        window_name="w",
        command=["sh", "-c", "cat > /tmp/tmux_test_out; sleep 30"],
    )
    try:
        send_keys(socket_path, info.pane, ["echo", "hello-tmux"])
        # Allow the command to consume the line
        import time

        for _ in range(20):
            txt = capture_pane(socket_path, info.pane, since_offset=0, max_bytes=4096)
            if "hello-tmux" in txt.text:
                break
            time.sleep(0.1)
        assert "hello-tmux" in txt.text
        assert txt.next_offset > 0
    finally:
        kill_session(socket_path, "echo")


def test_list_sessions(socket_path: str) -> None:
    info = create_session(
        socket=socket_path,
        session="ls",
        window_name="w",
        command=["sh", "-c", "sleep 30"],
    )
    try:
        sessions = list_sessions(socket_path)
        names = {s.session for s in sessions}
        assert "ls" in names
    finally:
        kill_session(socket_path, "ls")


def test_kill_missing_session_raises(socket_path: str) -> None:
    with pytest.raises(TmuxAdapterError):
        kill_session(socket_path, "nonexistent")
