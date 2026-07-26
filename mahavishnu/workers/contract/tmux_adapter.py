from __future__ import annotations

import dataclasses
import os
import re
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

# Session and socket identifiers must be path-safe. tmux names that
# contain whitespace, `:`, shell metacharacters, or newlines can be
# used to inject arguments into the constructed attach_command or to
# confuse tmux's own parser. Restrict to a conservative subset.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SAFE_SOCKET_RE = re.compile(r"^[A-Za-z0-9._/:-]{1,256}$")
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _validate_session_name(name: str) -> None:
    if not _SAFE_NAME_RE.match(name):
        raise TmuxAdapterError(f"unsafe tmux session name: {name!r}")


def _validate_socket_path(socket: str) -> None:
    if not _SAFE_SOCKET_RE.match(socket):
        raise TmuxAdapterError(f"unsafe tmux socket path: {socket!r}")


def _attach_command(socket: str, session: str) -> str:
    """Build an attach command. Both fields are already validated by
    ``_validate_*`` before this is called, so plain concatenation is safe.
    """
    return f"tmux -S {socket} attach -t {session}"


def _safe_stderr(stderr: str) -> str:
    """Strip control characters and ANSI escapes from tmux stderr to
    prevent log injection. Truncate to 2 KiB.
    """
    if not stderr:
        return ""
    stripped = _ANSI_RE.sub("", stderr)
    safe = re.sub(r"[^\x20-\x7e\n]", "?", stripped)
    return safe[:2048]


class TmuxAdapterError(RuntimeError):
    """Raised when a tmux invocation fails or the target is missing."""


@dataclasses.dataclass(frozen=True)
class TmuxSessionInfo:
    socket: str
    session: str
    window: str
    pane: str
    attach_command: str


@dataclasses.dataclass(frozen=True)
class CapturedOutput:
    text: str
    next_offset: int
    truncated: bool
    pane_alive: bool


def _run(
    socket: str, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    _validate_socket_path(socket)
    cmd = ["tmux", "-S", socket, *args]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and proc.returncode != 0:
        # Use repr() for `args` and the sanitized stderr to prevent log
        # injection through crafted names.
        raise TmuxAdapterError(
            f"tmux {args!r} failed: rc={proc.returncode} "
            f"stderr={_safe_stderr(proc.stderr)}"
        )
    return proc


def create_session(
    *,
    socket: str,
    session: str,
    window_name: str,
    command: Sequence[str],
) -> TmuxSessionInfo:
    """Create a new detached tmux session and launch ``command`` in its first pane.

    Returns the session metadata, including the pane id and attach command.
    Raises :class:`TmuxAdapterError` on failure.
    """
    _validate_socket_path(socket)
    _validate_session_name(session)
    _validate_session_name(window_name)
    socket_path = Path(socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    # Spec §9: 0700 on the tmux socket parent directory. Wrapped in
    # try/except because the parent may be a system path we don't own
    # (e.g. /tmp on multi-user hosts).
    try:
        os.chmod(socket_path.parent, 0o700)
    except PermissionError as e:
        raise TmuxAdapterError(
            f"cannot chmod socket parent {socket_path.parent!s} to 0700: {e}"
        ) from e
    # -d: detached, -s: session name, -n: window name, -P: print info
    quoted = " ".join(shlex.quote(part) for part in command)
    proc = subprocess.run(
        [
            "tmux",
            "-S",
            socket,
            "new-session",
            "-d",
            "-s",
            session,
            "-n",
            window_name,
            "-P",
            "-F",
            "#{session_name}:#{window_id}:#{pane_id}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux new-session failed: rc={proc.returncode} "
            f"stderr={_safe_stderr(proc.stderr)}"
        )
    stdout = proc.stdout.strip()
    line = stdout.splitlines()[-1] if stdout else ""
    parts = line.split(":")
    if len(parts) != 3:
        raise TmuxAdapterError(
            f"unexpected tmux new-session -P output: {proc.stdout!r}"
        )
    session_name, window_id, pane_id = parts
    # Validate the parsed session name too (the -F template is fixed
    # but we should still reject anything malformed).
    _validate_session_name(session_name)
    # Spec §9: tighten the freshly-created socket file's mode.
    if socket_path.exists():
        try:
            os.chmod(socket, 0o600)
        except PermissionError as e:
            raise TmuxAdapterError(
                f"cannot chmod socket {socket} to 0600: {e}"
            ) from e
    # Launch the command inside the pane.
    _run(socket, "send-keys", "-t", pane_id, quoted, "Enter")
    return TmuxSessionInfo(
        socket=socket,
        session=session_name,
        window=window_id,
        pane=pane_id,
        attach_command=_attach_command(socket, session_name),
    )


def list_sessions(socket: str) -> list[TmuxSessionInfo]:
    _validate_socket_path(socket)
    proc = _run(
        socket,
        "list-sessions",
        "-F",
        "#{session_name}:#{session_windows}",
        check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[TmuxSessionInfo] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name, windows = line.split(":", 1)
        # Reject anything that does not match our safe-name policy
        # before echoing it into attach_command.
        try:
            _validate_session_name(name)
        except TmuxAdapterError:
            continue
        out.append(
            TmuxSessionInfo(
                socket=socket,
                session=name,
                window=f"@{int(windows) - 1}" if windows else "",
                pane="",
                attach_command=_attach_command(socket, name),
            )
        )
    return out


def kill_session(socket: str, session: str) -> None:
    _validate_socket_path(socket)
    _validate_session_name(session)
    proc = _run(socket, "kill-session", "-t", session, check=False)
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux kill-session failed: rc={proc.returncode} "
            f"stderr={_safe_stderr(proc.stderr)}"
        )


def pane_alive(socket: str, pane: str) -> bool:
    proc = _run(
        socket,
        "display-message",
        "-p",
        "-t",
        pane,
        "#{pane_dead}",
        check=False,
    )
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "0"


def send_keys(socket: str, pane: str, keys: Sequence[str]) -> None:
    if not keys:
        return
    parts = [str(k) for k in keys]
    # `-l` sends the key as a literal string. `-H` (hex) silently drops
    # non-hex input. We space-join the parts so
    # `send_keys(s, p, ["echo", "hi"])` types `echo hi` rather than
    # `echohi`.
    literal = " ".join(parts)
    proc = _run(socket, "send-keys", "-t", pane, "-l", literal, check=False)
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux send-keys failed: rc={proc.returncode} "
            f"stderr={_safe_stderr(proc.stderr)}"
        )
    # Always press Enter unless the caller appended a literal "\n" already.
    if not (len(parts) == 1 and parts[0].endswith("\n")):
        _run(socket, "send-keys", "-t", pane, "Enter", check=False)


def capture_pane(
    socket: str,
    pane: str,
    *,
    since_offset: int,
    max_bytes: int = 65_536,
    strip_ansi: bool = True,
) -> CapturedOutput:
    proc = _run(
        socket,
        "capture-pane",
        "-p",
        "-J",
        "-S",
        f"-{since_offset}",
        "-t",
        pane,
        check=False,
    )
    if proc.returncode != 0:
        return CapturedOutput(
            text="",
            next_offset=since_offset,
            truncated=False,
            pane_alive=False,
        )
    text = proc.stdout
    if strip_ansi:
        text = _strip_ansi(text)
    truncated = False
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
        encoded = text.encode("utf-8")
    return CapturedOutput(
        text=text,
        next_offset=since_offset + len(encoded),
        truncated=truncated,
        pane_alive=pane_alive(socket, pane),
    )


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences from ``text``."""
    return _ANSI_RE.sub("", text)