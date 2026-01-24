"""iTerm2 adapter for terminal management.

This adapter uses the iTerm2 Python API to launch and manage terminal sessions.
Requires iTerm2 to be running with the Python API server enabled.
"""
import asyncio
from typing import Any, Dict, List, Optional
import logging
from datetime import datetime

from .base import TerminalAdapter

logger = logging.getLogger(__name__)

# iTerm2 Python API is available as 'iterm2' package
# It connects via WebSocket to the iTerm2 application
try:
    import iterm2
    ITERM2_AVAILABLE = True
except ImportError:
    ITERM2_AVAILABLE = False
    logger.warning("iterm2 package not available. Install with: pip install iterm2")


class ITerm2Adapter(TerminalAdapter):
    """Terminal adapter for iTerm2 using the Python API.

    This adapter requires iTerm2 to be running with the Python API server enabled:
    - iTerm2 > Preferences > General > Magic > Enable Python API

    The adapter communicates with iTerm2 via WebSocket protocol automatically.

    Features:
    - Connection pooling for reduced overhead
    - Automatic health checking
    - Profile-based session creation
    """

    adapter_name: str = "iterm2"

    def __init__(
        self,
        connection: Optional[Any] = None,
        use_pooling: bool = True,
        default_profile: Optional[str] = None,
    ):
        """Initialize iTerm2 adapter.

        Args:
            connection: Optional iterm2 connection (for testing or reusing connections)
            use_pooling: Enable connection pooling (default: True)
            default_profile: Default iTerm2 profile name for new sessions

        Raises:
            ImportError: If iterm2 package is not available
            RuntimeError: If cannot connect to iTerm2
        """
        if not ITERM2_AVAILABLE:
            raise ImportError(
                "iterm2 package is not available. "
                "Install with: pip install iterm2"
            )

        self._connection = connection
        self._use_pooling = use_pooling
        self._default_profile = default_profile
        self._app: Optional[Any] = None
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._pool: Optional[Any] = None
        self._owns_connection: bool = False  # Track if we created the connection

    async def _ensure_connected(self) -> None:
        """Ensure connection to iTerm2 is established.

        This uses the iterm2.Connection which automatically handles WebSocket.
        With pooling enabled, reuses existing connections from the pool.
        """
        if self._connected:
            return

        try:
            if self._connection is None:
                if self._use_pooling:
                    # Use global connection pool
                    from ..pool import get_global_pool

                    self._pool = await get_global_pool()
                    self._connection = await self._pool.acquire()
                    self._owns_connection = True
                    logger.debug("Acquired iTerm2 connection from pool")
                else:
                    # Create direct connection
                    self._connection = await iterm2.Connection.async_connect()
                    self._owns_connection = True
                    logger.info("Created new iTerm2 connection (no pooling)")

            self._app = await iterm2.AsyncApp.async_get(self._connection)
            self._connected = True
            logger.info("Connected to iTerm2 via Python API")
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to iTerm2. Ensure iTerm2 is running "
                f"and Python API is enabled in Preferences > General > Magic: {e}"
            ) from e

    async def _release_connection(self) -> None:
        """Release connection back to pool or close it.

        Should be called when adapter is done with the connection.
        """
        if self._owns_connection and self._connection is not None:
            if self._pool is not None:
                await self._pool.release(self._connection)
                logger.debug("Released iTerm2 connection to pool")
            else:
                await self._connection.close()
                logger.info("Closed iTerm2 connection")

            self._owns_connection = False
    
    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs
    ) -> str:
        """Launch a new iTerm2 terminal session and run a command.

        Args:
            command: Command to run in the terminal session
            columns: Terminal width in characters
            rows: Terminal height in lines
            **kwargs: Additional parameters (profile_name, etc.)

        Returns:
            Session ID (unique identifier for the session)

        Raises:
            RuntimeError: If connection fails or session cannot be created
        """
        await self._ensure_connected()

        try:
            # Get the current terminal window or create a new one
            window = self._app.current_terminal_window

            # Create a new tab with specified profile
            # Priority: kwarg > default_profile > default profile
            profile_name = kwargs.get("profile_name", self._default_profile)

            if profile_name:
                try:
                    profile = await iterm2.Profile.async_get(self._connection, profile_name)
                    tab = await window.async_create_tab(profile=profile)
                    logger.debug(f"Created tab with profile: {profile_name}")
                except Exception as e:
                    logger.warning(f"Failed to create tab with profile '{profile_name}': {e}")
                    logger.info("Falling back to default profile")
                    tab = await window.async_create_tab()
            else:
                tab = await window.async_create_tab()

            # Get the session from the tab
            session = tab.sessions[0]

            # Set terminal dimensions
            await session.async_set_frame_size(columns, rows)

            # Get session ID (unique identifier)
            session_id = str(session.session_id)

            # Store session metadata
            self._sessions[session_id] = {
                "session": session,
                "tab": tab,
                "command": command,
                "created_at": datetime.now(),
                "profile": profile_name,
            }

            # Send the command
            await session.async_send_text(command + "\n")

            logger.info(f"Launched iTerm2 session {session_id} with command: {command}")
            return session_id
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to launch iTerm2 session: {e}")
            raise RuntimeError(f"Failed to launch iTerm2 session: {e}") from e
    
    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to an iTerm2 terminal session.
        
        Args:
            session_id: Session identifier
            command: Command text to send
        
        Raises:
            KeyError: If session_id not found
            RuntimeError: If send fails
        """
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")
        
        try:
            session_data = self._sessions[session_id]
            session = session_data["session"]
            
            # Send the command text (including newline for execution)
            await session.async_send_text(command + "\n")
            
            logger.debug(f"Sent command to {session_id}: {command}")
            
        except Exception as e:
            logger.error(f"Failed to send command to {session_id}: {e}")
            raise RuntimeError(f"Failed to send command: {e}") from e
    
    async def capture_output(
        self,
        session_id: str,
        lines: Optional[int] = None
    ) -> str:
        """Capture output from an iTerm2 terminal session.
        
        Args:
            session_id: Session identifier
            lines: Optional number of lines to capture (default: all buffer)
        
        Returns:
            Captured output as string
        
        Raises:
            KeyError: If session_id not found
            RuntimeError: If capture fails
        """
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")
        
        try:
            session_data = self._sessions[session_id]
            session = session_data["session"]
            
            # Get the screen contents
            # iTerm2 provides both screen contents and full buffer
            if lines:
                # Get last N lines from buffer
                screen = await session.async_get_screen_contents()
                all_lines = screen.contents.split("\n")
                output = "\n".join(all_lines[-lines:])
            else:
                # Get full buffer
                screen = await session.async_get_screen_contents()
                output = screen.contents
            
            logger.debug(f"Captured {len(output.splitlines())} lines from {session_id}")
            return output
            
        except Exception as e:
            logger.error(f"Failed to capture output from {session_id}: {e}")
            raise RuntimeError(f"Failed to capture output: {e}") from e
    
    async def close_session(self, session_id: str) -> None:
        """Close an iTerm2 terminal session.
        
        Args:
            session_id: Session identifier
        
        Raises:
            KeyError: If session_id not found
            RuntimeError: If close fails
        """
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")
        
        try:
            session_data = self._sessions[session_id]
            tab = session_data["tab"]
            
            # Close the tab (which closes the session)
            # Note: iTerm2 doesn't have a direct "close session" method
            # We close the entire tab instead
            await tab.async_close()
            
            # Remove from tracking
            del self._sessions[session_id]
            
            logger.info(f"Closed iTerm2 session {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
            raise RuntimeError(f"Failed to close session: {e}") from e
    
    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active iTerm2 terminal sessions.
        
        Returns:
            List of session information dictionaries
        
        Raises:
            RuntimeError: If listing fails
        """
        await self._ensure_connected()
        
        try:
            sessions_list = []
            
            for session_id, session_data in self._sessions.items():
                sessions_list.append({
                    "id": session_id,
                    "command": session_data["command"],
                    "created_at": session_data["created_at"].isoformat(),
                    "adapter": self.adapter_name,
                })
            
            logger.debug(f"Listed {len(sessions_list)} active sessions")
            return sessions_list
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            raise RuntimeError(f"Failed to list sessions: {e}") from e
    
    async def cleanup(self) -> None:
        """Clean up resources and release connection.

        This method should be called before shutting down the adapter.
        With pooling enabled, releases connection back to pool instead of closing.
        """
        try:
            # Close all tracked sessions
            session_ids = list(self._sessions.keys())
            for session_id in session_ids:
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    logger.warning(f"Failed to close session {session_id} during cleanup: {e}")

            # Release connection back to pool or close it
            await self._release_connection()
            self._connected = False

            logger.info("iTerm2 adapter cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during iTerm2 adapter cleanup: {e}")


