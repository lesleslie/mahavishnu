"""Terminal management MCP tools.

This module provides FastMCP tools for terminal session management,
allowing Claude Code and other MCP clients to launch, control, and
capture output from terminal sessions.
"""

from typing import Any

from fastmcp import FastMCP

from ...terminal.manager import TerminalManager
from ...terminal.adapters.mcpretentious import McpretentiousAdapter
from ...terminal.adapters.iterm2 import ITerm2Adapter, ITERM2_AVAILABLE
from ...terminal.mcp_client import McpretentiousClient


def register_terminal_tools(
    mcp: FastMCP,
    terminal_manager: TerminalManager,
    mcp_client: Any = None,
) -> None:
    """Register terminal management tools with MCP server.

    Args:
        mcp: FastMCP server instance
        terminal_manager: TerminalManager instance for backend operations
        mcp_client: Optional MCP client for creating new adapters
    """

    @mcp.tool()
    async def terminal_launch(
        command: str,
        count: int = 1,
        columns: int = 120,
        rows: int = 40,
    ) -> list[str]:
        """Launch terminal sessions running a command.

        Args:
            command: Command to run in each terminal
            count: Number of sessions to launch (default: 1)
            columns: Terminal width in characters (default: 120)
            rows: Terminal height in lines (default: 40)

        Returns:
            List of session IDs

        Example:
            >>> session_ids = await terminal_launch("qwen", count=3)
            >>> print(f"Launched {len(session_ids)} sessions")
        """
        return await terminal_manager.launch_sessions(
            command,
            count,
            columns,
            rows,
        )

    @mcp.tool()
    async def terminal_send(
        session_id: str,
        command: str,
    ) -> None:
        """Send command to a terminal session.

        Args:
            session_id: Terminal session ID
            command: Command to send

        Example:
            >>> await terminal_send("term_123", "hello world")
        """
        await terminal_manager.send_command(session_id, command)

    @mcp.tool()
    async def terminal_capture(
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture output from terminal session.

        Args:
            session_id: Terminal session ID
            lines: Number of lines to capture (default: 100, None for all)

        Returns:
            Terminal output as string

        Example:
            >>> output = await terminal_capture("term_123", lines=50)
            >>> print(output)
        """
        return await terminal_manager.capture_output(session_id, lines)

    @mcp.tool()
    async def terminal_capture_all(
        session_ids: list[str],
        lines: int | None = None,
    ) -> dict[str, str]:
        """Capture output from multiple terminal sessions concurrently.

        Args:
            session_ids: List of session IDs
            lines: Number of lines to capture per session

        Returns:
            Dictionary mapping session_id -> output

        Example:
            >>> outputs = await terminal_capture_all(["term_1", "term_2"])
            >>> for sid, output in outputs.items():
            ...     print(f"{sid}: {output[:50]}...")
        """
        return await terminal_manager.capture_all_outputs(session_ids, lines)

    @mcp.tool()
    async def terminal_list() -> list[dict]:
        """List all active terminal sessions.

        Returns:
            List of session information dictionaries

        Example:
            >>> sessions = await terminal_list()
            >>> print(f"Active sessions: {len(sessions)}")
        """
        return await terminal_manager.list_sessions()

    @mcp.tool()
    async def terminal_close(session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Terminal session ID to close

        Example:
            >>> await terminal_close("term_123")
        """
        await terminal_manager.close_session(session_id)

    @mcp.tool()
    async def terminal_close_all() -> dict:
        """Close all terminal sessions.

        Returns:
            Dictionary with count of closed sessions

        Example:
            >>> result = await terminal_close_all()
            >>> print(f"Closed {result['closed_count']} sessions")
        """
        sessions = await terminal_manager.list_sessions()
        session_ids = [
            s.get("id", s.get("terminal_id", "")) for s in sessions
        ]
        if session_ids:
            await terminal_manager.close_all(session_ids)
        return {"closed_count": len(session_ids)}

    @mcp.tool()
    async def terminal_switch_adapter(
        adapter_name: str,
        migrate_sessions: bool = False,
    ) -> dict:
        """Hot-switch to a different terminal adapter without restart.

        Args:
            adapter_name: Name of adapter to switch to ("iterm2" or "mcpretentious")
            migrate_sessions: If True, attempt to migrate existing sessions

        Returns:
            Dictionary with switch result

        Example:
            >>> result = await terminal_switch_adapter("iterm2", migrate_sessions=False)
            >>> print(f"Switched to {result['new_adapter']}")
        """
        current = terminal_manager.current_adapter()

        if adapter_name == current:
            return {
                "status": "already_using",
                "current_adapter": current,
                "message": f"Already using {current} adapter"
            }

        # Create new adapter instance
        if adapter_name == "iterm2":
            if not ITERM2_AVAILABLE:
                return {
                    "status": "error",
                    "message": "iTerm2 adapter not available. Install with: pip install iterm2"
                }
            try:
                new_adapter = ITerm2Adapter()
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to initialize iTerm2 adapter: {e}"
                }
        elif adapter_name == "mcpretentious":
            if mcp_client is None:
                return {
                    "status": "error",
                    "message": "mcpretentious adapter requires MCP client"
                }
            new_adapter = McpretentiousAdapter(mcp_client)
        else:
            return {
                "status": "error",
                "message": f"Unknown adapter: {adapter_name}. Use 'iterm2' or 'mcpretentious'"
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
            return {
                "status": "error",
                "message": f"Failed to switch adapter: {e}"
            }

    @mcp.tool()
    async def terminal_current_adapter() -> dict:
        """Get information about the current terminal adapter.

        Returns:
            Dictionary with adapter information

        Example:
            >>> info = await terminal_current_adapter()
            >>> print(f"Using: {info['adapter']}")
        """
        return {
            "adapter": terminal_manager.current_adapter(),
            "history": terminal_manager.get_adapter_history(),
        }

    @mcp.tool()
    async def terminal_list_adapters() -> dict:
        """List all available terminal adapters.

        Returns:
            Dictionary with available adapters and their status

        Example:
            >>> adapters = await terminal_list_adapters()
            >>> for name, info in adapters['adapters'].items():
            ...     print(f"{name}: {info['status']}")
        """
        adapters = {
            "mcpretentious": {
                "status": "available",
                "description": "PTY-based terminal management (universal)",
            }
        }

        if ITERM2_AVAILABLE:
            adapters["iterm2"] = {
                "status": "available",
                "description": "Native iTerm2 Python API (WebSocket)",
            }
        else:
            adapters["iterm2"] = {
                "status": "unavailable",
                "description": "Install with: pip install iterm2",
            }

        return {
            "adapters": adapters,
            "current": terminal_manager.current_adapter(),
        }

    @mcp.tool()
    async def terminal_list_profiles() -> dict:
        """List available iTerm2 profiles (only works with iTerm2 adapter).

        Returns:
            Dictionary with list of profile names

        Example:
            >>> profiles = await terminal_list_profiles()
            >>> print(f"Available profiles: {profiles['profiles']}")
        """
        if terminal_manager.current_adapter() != "iterm2":
            return {
                "status": "error",
                "message": "Profile listing only available with iTerm2 adapter",
                "current_adapter": terminal_manager.current_adapter(),
                "profiles": [],
            }

        try:
            # Get the adapter's connection
            adapter = terminal_manager.adapter
            if not hasattr(adapter, "_connection") or adapter._connection is None:
                return {
                    "status": "error",
                    "message": "iTerm2 not connected",
                    "profiles": [],
                }

            # Import iterm2 and fetch profiles
            import iterm2

            profiles = await iterm2.Profile.async_get_all(adapter._connection)
            profile_names = [p.name for p in profiles]

            return {
                "status": "success",
                "profiles": profile_names,
                "count": len(profile_names),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list profiles: {e}",
                "profiles": [],
            }

    @mcp.tool()
    async def terminal_launch_with_profile(
        command: str,
        profile_name: str,
        count: int = 1,
        columns: int = 120,
        rows: int = 40,
    ) -> list[str]:
        """Launch terminal sessions with a specific iTerm2 profile.

        Args:
            command: Command to run in each terminal
            profile_name: iTerm2 profile name to use
            count: Number of sessions to launch (default: 1)
            columns: Terminal width in characters (default: 120)
            rows: Terminal height in lines (default: 40)

        Returns:
            List of session IDs

        Example:
            >>> session_ids = await terminal_launch_with_profile(
            ...     "qwen", "My Profile", count=2
            ... )
        """
        if terminal_manager.current_adapter() != "iterm2":
            raise RuntimeError(
                f"Profile selection requires iTerm2 adapter. Current: {terminal_manager.current_adapter()}"
            )

        return await terminal_manager.launch_sessions(
            command,
            count,
            columns,
            rows,
            profile_name=profile_name,
        )
