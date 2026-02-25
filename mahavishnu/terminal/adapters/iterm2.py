"""iTerm2 adapter for terminal management.

This adapter uses AppleScript to launch and manage terminal sessions.
Works reliably in embedded asyncio applications.

IMPORTANT - Implementation Note:
    This adapter uses AppleScript via subprocess instead of the iTerm2 Python API
    because the iTerm2 Python API is designed for standalone scripts that run under
    iTerm2's event loop (via iterm2.Connection.run()). It does NOT work reliably
    when embedded in existing asyncio applications.

    For pool management and terminal orchestration within Mahavishnu:
    - This adapter works via AppleScript (reliable, but limited output capture)
    - Use mcpretentious adapter (PTY-based, full output capture)
    - Use mock adapter for testing
"""

import asyncio
import shutil
import uuid
from datetime import datetime
from logging import getLogger
from typing import Any

from .base import TerminalAdapter

logger = getLogger(__name__)

# Check if osascript is available (macOS only)
OSASCRIPT_AVAILABLE = shutil.which("osascript") is not None

# Legacy export for backward compatibility
ITERM2_AVAILABLE = OSASCRIPT_AVAILABLE


class ITerm2Adapter(TerminalAdapter):
    """Terminal adapter for iTerm2 using AppleScript.

    This adapter requires iTerm2 to be running on macOS.

    The adapter communicates with iTerm2 via AppleScript, which works
    reliably in embedded asyncio contexts unlike the iTerm2 Python API.

    Features:
    - Session-based terminal management
    - Profile support for custom terminal configurations
    - Window/tab creation options
    - Graceful error handling

    Limitations:
    - Output capture is limited (AppleScript doesn't support terminal buffer access)
    - For full output capture, use mcpretentious adapter
    """

    adapter_name: str = "iterm2"

    def __init__(
        self,
        default_profile: str | None = None,
    ):
        """Initialize iTerm2 adapter.

        Args:
            default_profile: Default iTerm2 profile name for new sessions

        Raises:
            ImportError: If osascript is not available (not macOS)
        """
        if not OSASCRIPT_AVAILABLE:
            raise ImportError(
                "osascript not available. iTerm2 adapter requires macOS."
            )

        self._default_profile = default_profile
        self._sessions: dict[str, dict[str, Any]] = {}

    async def _run_applescript(self, script: str) -> str:
        """Run an AppleScript and return output.

        Args:
            script: AppleScript to run

        Returns:
            Script output

        Raises:
            RuntimeError: If script fails
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                raise RuntimeError(f"AppleScript failed: {error_msg}")

            return stdout.decode().strip()

        except Exception as e:
            raise RuntimeError(f"Failed to run AppleScript: {e}") from e

    async def launch_session(
        self, command: str, columns: int = 80, rows: int = 24, **kwargs: Any
    ) -> str:
        """Launch a new iTerm2 terminal session and run a command.

        Args:
            command: Command to run in the terminal session
            columns: Terminal width in characters (not used with AppleScript)
            rows: Terminal height in lines (not used with AppleScript)
            **kwargs: Additional parameters:
                - profile_name: iTerm2 profile to use
                - new_window: If True, create a new window instead of tab

        Returns:
            Session ID (unique identifier for the session)

        Raises:
            RuntimeError: If session creation fails
        """
        try:
            # Check if iTerm2 is running
            await self._ensure_iterm2_running()

            # Get options
            profile_name = kwargs.get("profile_name", self._default_profile)
            new_window = kwargs.get("new_window", False)

            # Generate session ID
            session_id = str(uuid.uuid4())[:8]

            # Escape command for AppleScript
            escaped_command = command.replace("\\", "\\\\").replace('"', '\\"')

            # Create AppleScript to launch terminal
            if new_window:
                if profile_name:
                    script = f'''
                    tell application "iTerm2"
                        activate
                        set newWindow to (create window with profile "{profile_name}")
                        tell newWindow
                            tell current session
                                write text "{escaped_command}"
                            end tell
                        end tell
                    end tell
                    '''
                else:
                    script = f'''
                    tell application "iTerm2"
                        activate
                        set newWindow to (create window with default profile)
                        tell newWindow
                            tell current session
                                write text "{escaped_command}"
                            end tell
                        end tell
                    end tell
                    '''
            else:
                # Create tab in current window
                if profile_name:
                    script = f'''
                    tell application "iTerm2"
                        activate
                        tell current window
                            set newTab to (create tab with profile "{profile_name}")
                            tell newTab
                                tell current session
                                    write text "{escaped_command}"
                                end tell
                            end tell
                        end tell
                    end tell
                    '''
                else:
                    script = f'''
                    tell application "iTerm2"
                        activate
                        tell current window
                            set newTab to (create tab with default profile)
                            tell newTab
                                tell current session
                                    write text "{escaped_command}"
                                end tell
                            end tell
                        end tell
                    end tell
                    '''

            await self._run_applescript(script)

            # Store session metadata
            self._sessions[session_id] = {
                "session": None,  # Not used with AppleScript approach
                "tab": None,
                "window": None,
                "command": command,
                "created_at": datetime.now(),
                "profile": profile_name,
                "new_window": new_window,
            }

            logger.info(
                f"Launched iTerm2 session {session_id} "
                f"({'new window' if new_window else 'tab'}) with command: {command}"
            )
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
            # Escape command for AppleScript
            escaped_command = command.replace("\\", "\\\\").replace('"', '\\"')

            script = f'''
            tell application "iTerm2"
                tell current window
                    tell current session
                        write text "{escaped_command}"
                    end tell
                end tell
            end tell
            '''

            await self._run_applescript(script)
            logger.debug(f"Sent command to {session_id}: {command}")

        except Exception as e:
            logger.error(f"Failed to send command to {session_id}: {e}")
            raise RuntimeError(f"Failed to send command: {e}") from e

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        """Capture output from an iTerm2 terminal session.

        Note: Output capture via AppleScript is limited. For full output
        capture, use the mcpretentious adapter instead.

        Args:
            session_id: Session identifier
            lines: Optional number of lines to capture (not supported)

        Returns:
            Placeholder message (AppleScript doesn't support buffer access)

        Raises:
            KeyError: If session_id not found
        """
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")

        # AppleScript doesn't support terminal buffer access
        # Return placeholder - use mcpretentious adapter for real output capture
        session_info = self._sessions[session_id]
        return (
            f"[Output capture not available via AppleScript]\n"
            f"Session: {session_id}\n"
            f"Command: {session_info['command']}\n"
            f"For output capture, use mcpretentious adapter"
        )

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
            was_new_window = session_data.get("new_window", False)

            if was_new_window:
                # Close the window
                script = '''
                tell application "iTerm2"
                    tell current window
                        close
                    end tell
                end tell
                '''
            else:
                # Close the current tab
                script = '''
                tell application "iTerm2"
                    tell current window
                        tell current tab
                            close
                        end tell
                    end tell
                end tell
                '''

            await self._run_applescript(script)

            # Remove from tracking
            del self._sessions[session_id]

            logger.info(f"Closed iTerm2 session {session_id}")

        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
            # Still remove from tracking even if close failed
            if session_id in self._sessions:
                del self._sessions[session_id]
            raise RuntimeError(f"Failed to close session: {e}") from e

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active iTerm2 terminal sessions.

        Returns:
            List of session information dictionaries

        Raises:
            RuntimeError: If listing fails
        """
        try:
            sessions_list = []

            for session_id, session_data in self._sessions.items():
                sessions_list.append(
                    {
                        "id": session_id,
                        "command": session_data["command"],
                        "created_at": session_data["created_at"].isoformat(),
                        "adapter": self.adapter_name,
                        "profile": session_data.get("profile"),
                        "new_window": session_data.get("new_window", False),
                    }
                )

            logger.debug(f"Listed {len(sessions_list)} active sessions")
            return sessions_list

        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            raise RuntimeError(f"Failed to list sessions: {e}") from e

    async def cleanup(self) -> None:
        """Clean up resources and close all sessions.

        This method should be called before shutting down the adapter.
        """
        try:
            # Close all tracked sessions
            session_ids = list(self._sessions.keys())
            for session_id in session_ids:
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    logger.warning(f"Failed to close session {session_id} during cleanup: {e}")

            logger.info("iTerm2 adapter cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during iTerm2 adapter cleanup: {e}")

    async def _ensure_iterm2_running(self) -> None:
        """Ensure iTerm2 is running, launch if needed."""
        script = '''
        tell application "iTerm2"
            if it is not running then
                launch
            end if
        end tell
        '''
        await self._run_applescript(script)
