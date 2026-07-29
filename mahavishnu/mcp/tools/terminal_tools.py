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
from ...terminal.adapters.mcpretentious import McpretentiousAdapter
from ...terminal.manager import TerminalManager  # noqa: TC001

# SECURITY: Define validation constraints for MCP tool inputs
SessionID = Annotated[
    str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100)
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
        session_ids = [s.get("id", s.get("terminal_id", "")) for s in sessions]
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
            raise NotImplementedError("iTerm2 adapter is deprecated; use tmux or mcpretentious")
        if adapter_name == "mcpretentious":
            if mcp_client is None:
                return {"status": "error", "message": "mcpretentious adapter requires MCP client"}
            new_adapter = McpretentiousAdapter(mcp_client)
        else:
            return {
                "status": "error",
                "message": f"Unknown adapter: {adapter_name}. Use 'mcpretentious'",
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
        except Exception as e:
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
        adapters = {
            "mcpretentious": {
                "status": "available",
                "description": "PTY-based terminal management (universal)",
            }
        }

        return {
            "adapters": adapters,
            "current": terminal_manager.current_adapter(),
        }
