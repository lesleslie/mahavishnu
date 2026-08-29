from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.workers.contract.tmux_adapter import (
    TmuxAdapterError,
    TmuxSessionInfo,
    create_session,
    kill_session,
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


def _new_session_proc(name: str = "test", window: str = "@0", pane: str = "%1") -> MagicMock:
    """Return a MagicMock that mimics `tmux new-session -P -F` output:
    ``<session_name>:<window_id>:<pane_id>``.
    """
    return MagicMock(
        returncode=0,
        stdout=f"{name}:{window}:{pane}\n",
        stderr="",
    )


@patch("mahavishnu.workers.contract.tmux_adapter.subprocess.run")
def test_create_session_invokes_new_session_with_quoted_command_argv(
    mock_subprocess_run: MagicMock,
    socket_path: str,
) -> None:
    """create_session must exec the command via
    ``tmux new-session ... -- <command>``, passing argv verbatim.

    Previously the implementation shlex.joined the command and typed it
    into the pane via ``send-keys``, which zsh cannot parse correctly.
    Asserting ``assert_called_with`` against the new-session shape fails
    against the current implementation (the last subprocess.run call is
    ``send-keys``, not ``new-session``).
    """
    socket = socket_path
    session = "test"
    window_name = "main"
    command = ["bash", "-c", "echo 'quoted shell'"]
    mock_subprocess_run.return_value = _new_session_proc(name=session)
    info = create_session(
        socket=socket,
        session=session,
        window_name=window_name,
        command=command,
    )
    assert isinstance(info, TmuxSessionInfo)
    assert info.session == session
    assert info.socket == socket
    assert info.pane.startswith("%")
    mock_subprocess_run.assert_called_with(
        ["tmux", "-S", socket, "new-session", "-d",
         "-s", session, "-n", window_name,
         "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
         "--"] + list(command),
        check=False,
        capture_output=True,
        text=True,
    )


@patch("mahavishnu.workers.contract.tmux_adapter.subprocess.run")
def test_create_session_invokes_new_session_with_long_running_command(
    mock_subprocess_run: MagicMock,
    socket_path: str,
) -> None:
    """The send-keys test path must also launch the command via the new
    ``tmux new-session ... -- <command>`` shape.
    """
    socket = socket_path
    session = "echo"
    window_name = "w"
    command = ["sh", "-c", "cat > /tmp/tmux_test_out; sleep 30"]
    mock_subprocess_run.return_value = _new_session_proc(name=session)
    info = create_session(
        socket=socket,
        session=session,
        window_name=window_name,
        command=command,
    )
    assert isinstance(info, TmuxSessionInfo)
    assert info.session == session
    mock_subprocess_run.assert_called_with(
        ["tmux", "-S", socket, "new-session", "-d",
         "-s", session, "-n", window_name,
         "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
         "--"] + list(command),
        check=False,
        capture_output=True,
        text=True,
    )


@patch("mahavishnu.workers.contract.tmux_adapter.subprocess.run")
def test_create_session_invokes_new_session_for_list_sessions_path(
    mock_subprocess_run: MagicMock,
    socket_path: str,
) -> None:
    """The list-sessions test path must also launch the command via the
    new ``tmux new-session ... -- <command>`` shape.
    """
    socket = socket_path
    session = "ls"
    window_name = "w"
    command = ["sh", "-c", "sleep 30"]
    mock_subprocess_run.return_value = _new_session_proc(name=session)
    info = create_session(
        socket=socket,
        session=session,
        window_name=window_name,
        command=command,
    )
    assert isinstance(info, TmuxSessionInfo)
    assert info.session == session
    mock_subprocess_run.assert_called_with(
        ["tmux", "-S", socket, "new-session", "-d",
         "-s", session, "-n", window_name,
         "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
         "--"] + list(command),
        check=False,
        capture_output=True,
        text=True,
    )


def test_kill_missing_session_raises(socket_path: str) -> None:
    with pytest.raises(TmuxAdapterError):
        kill_session(socket_path, "nonexistent")
