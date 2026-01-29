"""Base adapter interface for terminal management."""

from abc import ABC, abstractmethod
from typing import Any


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
        pass

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
        pass

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
        pass

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Terminal session identifier to close

        Raises:
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If session close fails
        """
        pass

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
        pass

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Return adapter name for identification."""
        pass
