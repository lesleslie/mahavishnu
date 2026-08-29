"""PTY toolserver backend registry.

Built-in backends. Each entry defines:
  - command + args: how to spawn the MCP subprocess
  - requires: prerequisites that must be on PATH

Operators pick by name via ``terminal.adapter_preference``. Adding a new
backend = one entry here + (if tool surface differs) a thin adapter shim.
"""

from __future__ import annotations

from dataclasses import dataclass
import shutil


@dataclass(frozen=True)
class PtyBackend:
    """A single built-in PTY toolserver backend."""

    name: str
    command: str
    args: tuple[str, ...]
    requires: tuple[str, ...] = ()

    def __hash__(self) -> int:
        return hash((self.name, self.command, self.args, self.requires))


BUILTIN_BACKENDS: dict[str, PtyBackend] = {
    "tmux": PtyBackend(
        name="tmux",
        command="tmux",
        args=(),
        requires=("tmux",),
    ),
}


def check_prerequisites(backend: PtyBackend) -> list[str]:
    """Return a list of missing prerequisites (empty = all good).

    Used by any code that wants to fail fast on a missing PTY binary
    (e.g. tmux) instead of letting subprocess spawn fail at first call.
    """
    return [req for req in backend.requires if shutil.which(req) is None]
