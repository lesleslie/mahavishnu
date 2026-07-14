"""PTY toolserver backend registry.

Built-in backends. Each entry defines:
  - command + args: how to spawn the MCP subprocess
  - tool_map: how Mahavishnu's generic tool names map to backend-specific
                names (empty = adapter uses its own hardcoded names; populated
                when a future adapter wants to share McpretentiousAdapter with
                a backend whose tool names differ — e.g., {"read": "screenshot"})
  - requires: prerequisites that must be on PATH

Adding a new backend = one entry here + (if tool surface differs) a thin
adapter shim. Operators pick by name via terminal.adapter_preference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import shutil


@dataclass(frozen=True)
class PtyBackend:
    """A single built-in PTY toolserver backend."""

    name: str
    command: str
    args: tuple[str, ...]
    tool_map: dict[str, str] = field(default_factory=dict)
    requires: tuple[str, ...] = field(default_factory=tuple)

    def __hash__(self) -> int:
        # tool_map is mutable, so the default frozen-dataclass __hash__ (which
        # hashes all fields) raises TypeError on instances with non-empty
        # tool_map. Hash on the immutable fields so equal PtyBackends hash
        # identically and instances can be used as dict keys / set members.
        return hash((self.name, self.command, self.args, self.requires))


BUILTIN_BACKENDS: dict[str, PtyBackend] = {
    "mcpretentious": PtyBackend(
        name="mcpretentious",
        command="npx",                              # was: "uvx" — BUG
        args=("mcpretentious",),
        tool_map={},                                # uses default names
        requires=("node",),                         # npm package
    ),
    "pty_mcp_python": PtyBackend(
        name="pty_mcp_python",
        command="uvx",
        args=("--from", "luqm4nx-pty-mcp-server-python", "pty-mcp-server-python"),
        tool_map={},                                # see Tool-name mapping in spec
        requires=("uvx",),
    ),
}


def check_prerequisites(backend: PtyBackend) -> list[str]:
    """Return a list of missing prerequisites (empty = all good).

    Called at McpretentiousClient construction time so failures surface
    with a clear message instead of every subsequent tool call timing out.
    """
    return [req for req in backend.requires if shutil.which(req) is None]