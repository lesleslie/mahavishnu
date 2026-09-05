"""Terminal management MCP tools.

This module provides FastMCP tools for terminal session management,
allowing Claude Code and other MCP clients to launch, control, and
capture output from terminal sessions.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp_common.fastmcp import FastMCP  # noqa: TC002
from pydantic import Field, StringConstraints

from ...observability.worker_metrics import WorkerMetrics
from ...terminal.adapters.tmux import TmuxTerminalAdapter
from ...terminal.manager import TerminalManager  # noqa: TC001

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

# SECURITY: Dangerous command patterns to block in MCP tools
DANGEROUS_COMMAND_PATTERNS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    "> /dev/sd",
    "chmod 000",
    "chown root:",
    "curl | sh",
    "wget | sh",
    "&& rm",
    "; rm",
    "| rm",
    "nc -e",
    "ncat",
    "/dev/tcp",
    "/dev/udp",
    "bind shell",
    "reverse shell",
    "kill -9",
    "pkill",
    "killall",
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

    Args:
        command: Command string to validate

    Raises:
        ValueError: If command contains dangerous patterns
    """
    command_lower = command.lower()

    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.lower() in command_lower:
            raise ValueError(
                f"Command contains dangerous pattern '{pattern}'. "
                "This command is not allowed for security reasons."
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
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
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
        # Built dynamically from the live terminal manager + crow_enabled flag.
        # tmux and mock are always available; crow is opt-in via crow_enabled.
        config = getattr(terminal_manager, "config", None)
        crow_enabled = bool(getattr(config, "crow_enabled", False))

        adapters: dict[str, dict[str, str]] = {
            "tmux": {
                "status": "available",
                "description": "Durable-worker terminal via local tmux subprocess",
            },
            "mock": {
                "status": "available",
                "description": "Simulated terminal for tests and offline fallbacks",
            },
        }
        if crow_enabled:
            adapters["crow"] = {
                "status": "available",
                "description": "PTY via bodai-crow HTTP MCP bridge",
            }

        return {
            "adapters": adapters,
            "current": terminal_manager.current_adapter(),
        }
