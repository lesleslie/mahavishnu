"""Mock terminal adapter for testing and development.

This adapter simulates terminal sessions without requiring actual terminal
hardware or applications. Useful for:
- Testing pool functionality
- Development without iTerm2/MCP dependencies
- CI/CD environments
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

# Generate UUID using uuid.uuid4()

from .base import TerminalAdapter


class MockTerminalAdapter(TerminalAdapter):
    """Mock terminal adapter that simulates terminal sessions.

    This adapter creates simulated terminal sessions that capture commands
    and return simulated outputs. Perfect for testing and development.

    Example:
        >>> adapter = MockTerminalAdapter()
        >>> session_id = await adapter.launch_session("qwen")
        >>> await adapter.send_command(session_id, "hello")
        >>> output = await adapter.capture_output(session_id)
        >>> print(output)  # Simulated output
    """

    def __init__(self, auto_respond: bool = True, response_delay: float = 0.1) -> None:
        """Initialize mock adapter.

        Args:
            auto_respond: If True, automatically generate responses to commands
            response_delay: Simulated response delay in seconds
        """
        self.auto_respond = auto_respond
        self.response_delay = response_delay
        self._sessions: dict[str, dict[str, Any]] = {}
        self._command_history: dict[str, list[str]] = {}

    @property
    def adapter_name(self) -> str:
        """Return adapter name."""
        return "mock"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Launch a mock terminal session.

        Args:
            command: Initial command (stored but not executed)
            columns: Terminal width (stored for metadata)
            rows: Terminal height (stored for metadata)
            **kwargs: Additional parameters (ignored)

        Returns:
            Session ID (UUID string)
        """
        session_id = str(uuid.uuid4())[:8]

        self._sessions[session_id] = {
            "command": command,
            "columns": columns,
            "rows": rows,
            "created_at": datetime.now(),
            "output_buffer": [f"[Mock Terminal Started - Session {session_id}]"],
        }
        self._command_history[session_id] = [command]

        # Simulate initial output
        if self.auto_respond:
            self._sessions[session_id]["output_buffer"].append(
                f"$ {command}\n[Mock: Command '{command}' received - session ready]"
            )

        return session_id

    async def send_command(
        self,
        session_id: str,
        command: str,
    ) -> None:
        """Send command to mock session.

        Args:
            session_id: Session ID from launch_session
            command: Command to send

        Raises:
            ValueError: If session doesn't exist
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        self._command_history[session_id].append(command)

        # Add to output buffer
        self._sessions[session_id]["output_buffer"].append(f"$ {command}")

        if self.auto_respond:
            # Simulate command execution with delay
            await asyncio.sleep(self.response_delay)

            # Generate mock response
            response = self._generate_mock_response(command)
            self._sessions[session_id]["output_buffer"].append(response)

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture output from mock session.

        Args:
            session_id: Session ID from launch_session
            lines: Number of lines to capture (None for all)

        Returns:
            Captured output as string

        Raises:
            ValueError: If session doesn't exist
        """
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        output_buffer = self._sessions[session_id]["output_buffer"]

        if lines is not None:
            output_buffer = output_buffer[-lines:]

        return "\n".join(output_buffer)

    async def close_session(self, session_id: str) -> None:
        """Close a mock session.

        Args:
            session_id: Session ID to close
        """
        if session_id in self._sessions:
            self._sessions[session_id]["output_buffer"].append(
                f"[Mock Terminal Closed - Session {session_id}]"
            )
            del self._sessions[session_id]

        if session_id in self._command_history:
            del self._command_history[session_id]

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active mock sessions.

        Returns:
            List of session info dictionaries
        """
        return [
            {
                "session_id": sid,
                "command": data["command"],
                "created_at": data["created_at"].isoformat(),
                "output_lines": len(data["output_buffer"]),
            }
            for sid, data in self._sessions.items()
        ]

    def _generate_mock_response(self, command: str) -> str:
        """Generate a mock response for a command.

        Args:
            command: Command that was sent

        Returns:
            Simulated response string
        """
        # Simple pattern matching for common commands
        command_lower = command.lower().strip()

        if command_lower in ("help", "?"):
            return "[Mock] Available commands: help, status, echo, exit"
        elif command_lower == "status":
            return "[Mock] Status: OK - All systems operational"
        elif command_lower.startswith("echo "):
            return f"[Mock] {command[5:]}"
        elif command_lower == "exit":
            return "[Mock] Session ended"
        else:
            return f"[Mock] Executed: {command}\n[Mock] Return code: 0"

    def get_command_history(self, session_id: str) -> list[str]:
        """Get command history for a session.

        Args:
            session_id: Session ID

        Returns:
            List of commands sent to the session
        """
        return self._command_history.get(session_id, [])
