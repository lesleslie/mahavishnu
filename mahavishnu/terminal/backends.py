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
    "mcpretentious": PtyBackend(
        name="mcpretentious",
        command="npx",  # was: "uvx" — BUG
        args=("mcpretentious",),
        requires=("node",),  # npm package
    ),
}


def check_prerequisites(backend: PtyBackend) -> list[str]:
    """Return a list of missing prerequisites (empty = all good).

    Called at McpretentiousClient construction time so failures surface
    with a clear message instead of every subsequent tool call timing out.
    """
    return [req for req in backend.requires if shutil.which(req) is None]
