"""Base adapter interface for terminal management."""

from abc import ABC, abstractmethod
from typing import Any

from ...core.errors import ErrorCode, MahavishnuError


class TerminalError(MahavishnuError):
    """Base exception for terminal operations."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, error_code, details=details)


class SessionNotFoundError(TerminalError):
    """Raised when a session ID is not tracked by the adapter."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, details=details)


__all__ = ["SessionNotFoundError", "TerminalAdapter", "TerminalError"]


class TerminalAdapter(ABC):
    """Abstract interface for terminal adapters.

    All terminal adapters must implement this interface to provide
    a consistent API for launching sessions, sending commands,
    capturing output, and managing sessions.
    """

    @abstractmethod
    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Launch a terminal session and return session ID.

        Args:
            command: Command to run in the terminal session
            columns: Terminal width in characters
            rows: Terminal height in lines
            **kwargs: Adapter-specific parameters (e.g., profile for iTerm2)

        Returns:
            Unique session identifier

        Raises:
            TerminalError: If session launch fails
        """

    @abstractmethod
    async def send_command(
        self,
        session_id: str,
        command: str,
    ) -> None:
        """Send command to a terminal session.

        Args:
            session_id: Terminal session identifier
            command: Command string to send

        Raises:
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If command send fails
        """

    @abstractmethod
    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture output from a terminal session.

        Args:
            session_id: Terminal session identifier
            lines: Number of lines to capture (None for all)

        Returns:
            Terminal output as string

        Raises:
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If output capture fails
        """

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Terminal session identifier to close

        Raises:
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If session close fails
        """

    @abstractmethod
    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active terminal sessions.

        Returns:
            List of session information dictionaries with keys:
            - id: Session identifier
            - [adapter-specific metadata]

        Raises:
            TerminalError: If listing fails
        """

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Return adapter name for identification."""

    async def run_applescript(self, script: str) -> str:
        """Execute an AppleScript snippet and return its raw output.

        Only meaningful on macOS adapters (iTerm2, mock with AppleScript
        shim). Adapters running on other platforms should raise
        ``NotImplementedError`` so callers can fall back. Defined on the
        ABC (rather than only on concrete macOS adapters) so the
        grid manager's static-typed call sites are valid.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support AppleScript execution")
