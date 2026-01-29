"""Terminal session representation."""

from datetime import datetime, timedelta

from .adapters.base import TerminalAdapter


class TerminalSession:
    """Represent a single terminal session with metadata.

    Provides a convenient interface for interacting with a single
    terminal session, including sending commands, capturing output,
    and tracking session history.

    Example:
        >>> from mahavishnu.terminal import TerminalSession
        >>> session = TerminalSession(session_id, "qwen", adapter)
        >>> await session.send("what is 2+2?")
        >>> output = await session.read(lines=50)
        >>> print(output)
        >>> await session.close()
    """

    def __init__(
        self,
        session_id: str,
        command: str,
        adapter: TerminalAdapter,
    ) -> None:
        """Initialize a terminal session.

        Args:
            session_id: Unique session identifier
            command: Command that launched this session
            adapter: Terminal adapter for backend operations
        """
        self.session_id = session_id
        self.command = command
        self.adapter = adapter
        self.created_at = datetime.now()
        self.last_output: str | None = None
        self._output_buffer: list[str] = []

    async def send(self, command: str) -> None:
        """Send command to this session.

        Args:
            command: Command string to send

        Raises:
            TerminalError: If command send fails
        """
        await self.adapter.send_command(self.session_id, command)

    async def read(self, lines: int | None = None) -> str:
        """Read output from this session.

        Args:
            lines: Number of lines to capture (None for all)

        Returns:
            Terminal output as string

        Raises:
            TerminalError: If output capture fails
        """
        output = await self.adapter.capture_output(self.session_id, lines)
        self.last_output = output
        self._output_buffer.append(output)
        return output

    async def close(self) -> None:
        """Close this session.

        Raises:
            TerminalError: If session close fails
        """
        await self.adapter.close_session(self.session_id)

    @property
    def age(self) -> timedelta:
        """Get session age."""
        return datetime.now() - self.created_at

    def get_output_history(self) -> list[str]:
        """Get all captured outputs from this session.

        Returns:
            List of output strings in capture order
        """
        return self._output_buffer.copy()

    def __repr__(self) -> str:
        """Return string representation of session."""
        return f"TerminalSession(id={self.session_id!r}, command={self.command!r}, age={self.age})"
