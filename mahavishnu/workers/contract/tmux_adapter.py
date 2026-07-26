from __future__ import annotations

import dataclasses
import os
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path


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
    cmd = ["tmux", "-S", socket, *args]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux {' '.join(args)} failed: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()}"
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
    socket_path = Path(socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    # Spec §9: 0600 on the tmux socket parent directory.
    os.chmod(socket_path.parent, 0o700)
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
            f"stderr={proc.stderr.strip()}"
        )
    stdout = proc.stdout.strip()
    line = stdout.splitlines()[-1] if stdout else ""
    parts = line.split(":")
    if len(parts) != 3:
        raise TmuxAdapterError(
            f"unexpected tmux new-session -P output: {proc.stdout!r}"
        )
    session_name, window_id, pane_id = parts
    # Spec §9: tighten the freshly-created socket file's mode.
    if socket_path.exists():
        os.chmod(socket, 0o600)
    # Launch the command inside the pane.
    _run(socket, "send-keys", "-t", pane_id, quoted, "Enter")
    return TmuxSessionInfo(
        socket=socket,
        session=session_name,
        window=window_id,
        pane=pane_id,
        attach_command=f"tmux -S {socket} attach -t {session_name}",
    )


def list_sessions(socket: str) -> list[TmuxSessionInfo]:
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
        out.append(
            TmuxSessionInfo(
                socket=socket,
                session=name,
                window=f"@{int(windows) - 1}" if windows else "",
                pane="",
                attach_command=f"tmux -S {socket} attach -t {name}",
            )
        )
    return out


def kill_session(socket: str, session: str) -> None:
    proc = _run(socket, "kill-session", "-t", session, check=False)
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux kill-session failed: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()}"
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
    parts = list(keys)
    proc = _run(socket, "send-keys", "-t", pane, "-H", *parts, check=False)
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux send-keys failed: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()}"
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


_ANSI_RE = None


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences from ``text``.

    The regex is compiled lazily on first use so module import stays cheap.
    """
    global _ANSI_RE
    import re

    if _ANSI_RE is None:
        _ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return _ANSI_RE.sub("", text)