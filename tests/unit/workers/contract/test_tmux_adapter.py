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


# ---------------------------------------------------------------------------
# Environment injection: the initial command must inherit it
# ---------------------------------------------------------------------------
#
# `new-session` starts the command immediately. Injecting the environment
# afterwards with `set-environment` is too late -- the command has already
# captured its environment, so the variables never arrive. The session
# dies with a `MAHAVISHNU_PROMPT` that is empty, and the agent is asked
# to do nothing.


@patch("mahavishnu.workers.contract.tmux_adapter.subprocess.run")
def test_create_session_passes_env_to_new_session(
    mock_subprocess_run: MagicMock,
    socket_path: str,
) -> None:
    """The env must be in the new-session argv, not applied afterwards."""
    mock_subprocess_run.return_value = _new_session_proc(name="test")

    create_session(
        socket=socket_path,
        session="test",
        window_name="main",
        command=["sh", "-lc", "qwen"],
        env={"MAHAVISHNU_PROMPT": "do the thing"},
    )

    argv = mock_subprocess_run.call_args_list[0].args[0]
    assert "-e" in argv
    assert "MAHAVISHNU_PROMPT=do the thing" in argv
    # The env has to come BEFORE the `--` that ends the options.
    assert argv.index("-e") < argv.index("--")


@patch("mahavishnu.workers.contract.tmux_adapter.subprocess.run")
def test_create_session_env_value_is_passed_verbatim(
    mock_subprocess_run: MagicMock,
    socket_path: str,
) -> None:
    """tmux reads the value from argv, so quoting would bake the quotes in.

    A prompt containing spaces or quotes must arrive exactly as written --
    shlex.quote would make the variable hold the quote characters too.
    """
    mock_subprocess_run.return_value = _new_session_proc(name="test")
    value = 'say "hi"; touch /tmp/pwned'

    create_session(
        socket=socket_path,
        session="test",
        window_name="main",
        command=["sh", "-lc", "qwen"],
        env={"MAHAVISHNU_PROMPT": value},
    )

    argv = mock_subprocess_run.call_args_list[0].args[0]
    assert f"MAHAVISHNU_PROMPT={value}" in argv
    assert not any("'" in part for part in argv if "MAHAVISHNU_PROMPT" in part)


# ---------------------------------------------------------------------------
# Keystrokes: text is text, Enter is a key
# ---------------------------------------------------------------------------


@patch("mahavishnu.workers.contract.tmux_adapter._run")
def test_send_keys_presses_enter_as_a_separate_key(mock_run: MagicMock) -> None:
    """The Enter that submits must not be typed into the input buffer.

    The implementation used to space-join the key sequence into one
    literal string, so a caller that passed ["text", "Enter"] typed the
    word "Enter" into the CLI's buffer as well as pressing the key. A
    prompt that happened to contain the word was then indistinguishable
    from the key press.
    """
    from mahavishnu.workers.contract.tmux_adapter import send_keys

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    send_keys("/tmp/x.sock", "%1", ["hello world"], press_enter=True)

    literal_call = mock_run.call_args_list[0]
    assert literal_call.args[1] == "send-keys"
    assert "-l" in literal_call.args
    assert literal_call.args[-1] == "hello world"

    enter_call = mock_run.call_args_list[1]
    assert enter_call.args[1] == "send-keys"
    assert enter_call.args[-1] == "Enter"


@patch("mahavishnu.workers.contract.tmux_adapter._run")
def test_send_keys_does_not_press_enter_by_default(mock_run: MagicMock) -> None:
    from mahavishnu.workers.contract.tmux_adapter import send_keys

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    send_keys("/tmp/x.sock", "%1", ["partial"])

    assert len(mock_run.call_args_list) == 1
    assert mock_run.call_args_list[0].args[-1] == "partial"
