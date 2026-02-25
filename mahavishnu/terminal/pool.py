"""Session pooling for iTerm2 terminal management.

This module provides a session pool for managing iTerm2 terminal sessions.
It uses AppleScript for reliable communication with iTerm2, avoiding the
iTerm2 Python API's event loop compatibility issues.

IMPORTANT: The iTerm2 Python API is designed for standalone scripts that run
under iTerm2's event loop (via iterm2.Connection.run()). It does NOT work
reliably when embedded in existing asyncio applications. This implementation
uses AppleScript via subprocess for reliable operation.

For pool management in production:
- Use mcpretentious adapter (PTY-based, works with any async app)
- Use mock adapter for testing
- Use this pool only when iTerm2 terminal visualization is needed
"""

import asyncio
import contextlib
import shutil
import uuid
from datetime import datetime, timedelta
from logging import getLogger
from typing import Any

logger = getLogger(__name__)

# Check if osascript is available (macOS only)
OSASCRIPT_AVAILABLE = shutil.which("osascript") is not None


class ITerm2SessionPool:
    """Pool for managing iTerm2 terminal sessions via AppleScript.

    This pool uses AppleScript to communicate with iTerm2, which works
    reliably in embedded asyncio contexts unlike the iTerm2 Python API.

    Benefits:
    - Works in embedded asyncio applications
    - No event loop conflicts
    - Session-based (not connection-based)
    - Proper resource cleanup

    Example:
        >>> pool = ITerm2SessionPool(max_size=5)
        >>> session_id = await pool.acquire_session("python -m qwen")
        >>> # Use session...
        >>> await pool.release_session(session_id)
    """

    def __init__(
        self,
        max_size: int = 10,
        idle_timeout: float = 300.0,
        health_check_interval: float = 60.0,
    ) -> None:
        """Initialize iTerm2 session pool.

        Args:
            max_size: Maximum number of sessions to pool
            idle_timeout: Close sessions idle for this many seconds
            health_check_interval: Check session health every N seconds
        """
        if not OSASCRIPT_AVAILABLE:
            raise ImportError(
                "osascript not available. iTerm2 pool requires macOS with osascript."
            )

        self.max_size = max_size
        self.idle_timeout = timedelta(seconds=idle_timeout)
        self.health_check_interval = health_check_interval

        self._pool: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._health_check_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"Initialized iTerm2 session pool (max_size={max_size}, "
            f"idle_timeout={idle_timeout}s)"
        )

    async def acquire_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        profile: str | None = None,
    ) -> str:
        """Acquire a terminal session from the pool.

        Creates a new session if pool has capacity.

        Args:
            command: Command to run in the terminal
            columns: Terminal width in characters
            rows: Terminal height in lines
            profile: Optional iTerm2 profile name

        Returns:
            Session ID (UUID string)

        Raises:
            RuntimeError: If pool is full
        """
        async with self._lock:
            # Check if pool has capacity
            if len(self._pool) >= self.max_size:
                # Try to find an idle session to reuse
                for session_id, session_info in self._pool.items():
                    if not session_info["in_use"]:
                        # Reuse idle session
                        session_info["in_use"] = True
                        session_info["last_used"] = datetime.now()
                        session_info["command"] = command
                        logger.debug(f"Reusing idle session {session_id}")
                        return session_id

                raise RuntimeError(
                    f"Session pool exhausted (max_size={self.max_size}). "
                    f"Wait for a session to be released or increase pool size."
                )

            # Create new session
            session_id = await self._create_session(command, columns, rows, profile)

            self._pool[session_id] = {
                "command": command,
                "columns": columns,
                "rows": rows,
                "profile": profile,
                "created_at": datetime.now(),
                "last_used": datetime.now(),
                "in_use": True,
                "iterm2_tab_id": None,  # Will be set after creation
            }

            logger.info(
                f"Created iTerm2 session {session_id} "
                f"(pool size: {len(self._pool)}/{self.max_size})"
            )
            return session_id

    async def release_session(self, session_id: str) -> None:
        """Release a session back to the pool.

        Args:
            session_id: Session to release
        """
        async with self._lock:
            if session_id not in self._pool:
                logger.warning(f"Attempted to release unknown session {session_id}")
                return

            self._pool[session_id]["in_use"] = False
            self._pool[session_id]["last_used"] = datetime.now()
            logger.debug(f"Released session {session_id}")

    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to a terminal session.

        Args:
            session_id: Target session
            command: Command to send

        Raises:
            KeyError: If session not found
            RuntimeError: If command fails
        """
        if session_id not in self._pool:
            raise KeyError(f"Session {session_id} not found")

        script = f'''
        tell application "iTerm2"
            tell current window
                tell current session
                    write text "{command}"
                end tell
            end tell
        end tell
        '''

        await self._run_applescript(script)
        logger.debug(f"Sent command to {session_id}: {command}")

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        """Capture output from a terminal session.

        Args:
            session_id: Target session
            lines: Number of lines to capture (None for all)

        Returns:
            Captured output

        Raises:
            KeyError: If session not found
        """
        if session_id not in self._pool:
            raise KeyError(f"Session {session_id} not found")

        # iTerm2 AppleScript doesn't support output capture directly
        # This is a limitation - use mcpretentious adapter if you need output capture
        return f"[Output capture not available via AppleScript for session {session_id}]"

    async def close_session(self, session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Session to close
        """
        async with self._lock:
            if session_id not in self._pool:
                return

            try:
                script = '''
                tell application "iTerm2"
                    tell current window
                        tell current session
                            close
                        end tell
                    end tell
                end tell
                '''
                await self._run_applescript(script)
            except Exception as e:
                logger.warning(f"Error closing iTerm2 session {session_id}: {e}")
            finally:
                del self._pool[session_id]
                logger.info(f"Closed iTerm2 session {session_id}")

    async def close_all(self) -> None:
        """Close all sessions in the pool.

        Should be called before shutdown.
        """
        self._shutdown_event.set()

        async with self._lock:
            # Stop health check task
            if self._health_check_task:
                try:
                    await asyncio.wait_for(self._health_check_task, timeout=5.0)
                except asyncio.TimeoutError:
                    self._health_check_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None

            # Close all sessions
            session_ids = list(self._pool.keys())
            for session_id in session_ids:
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    logger.warning(f"Error closing session {session_id}: {e}")

            self._pool.clear()
            logger.info("Closed all iTerm2 sessions")

    async def _create_session(
        self,
        command: str,
        columns: int,
        rows: int,
        profile: str | None,
    ) -> str:
        """Create a new iTerm2 session via AppleScript.

        Args:
            command: Command to run
            columns: Terminal width
            rows: Terminal height
            profile: Optional profile name

        Returns:
            New session ID
        """
        session_id = str(uuid.uuid4())[:8]

        # Escape command for AppleScript
        escaped_command = command.replace('"', '\\"')

        if profile:
            script = f'''
            tell application "iTerm2"
                activate
                set newWindow to (create window with profile "{profile}")
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
        return session_id

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

    async def _is_session_healthy(self, session_id: str) -> bool:
        """Check if a session is healthy.

        Args:
            session_id: Session to check

        Returns:
            True if session is healthy
        """
        try:
            script = '''
            tell application "iTerm2"
                return "true"
            end tell
            '''
            await self._run_applescript(script)
            return True
        except Exception:
            return False

    async def start_health_check(self) -> None:
        """Start background health check task."""
        if self._health_check_task is not None:
            return

        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("Started iTerm2 session pool health check")

    async def _health_check_loop(self) -> None:
        """Background health check loop."""
        while not self._shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=self.health_check_interval
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                await self._remove_stale_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _remove_stale_sessions(self) -> None:
        """Remove stale sessions from the pool."""
        async with self._lock:
            now = datetime.now()
            stale_ids = []

            for session_id, session_info in self._pool.items():
                if session_info["in_use"]:
                    continue

                idle_time = now - session_info["last_used"]
                if idle_time > self.idle_timeout:
                    stale_ids.append(session_id)
                    continue

                if not await self._is_session_healthy(session_id):
                    stale_ids.append(session_id)

            for session_id in stale_ids:
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    logger.warning(f"Error closing stale session {session_id}: {e}")

            if stale_ids:
                logger.info(f"Removed {len(stale_ids)} stale sessions")

    def stats(self) -> dict[str, Any]:
        """Get pool statistics.

        Returns:
            Dictionary with pool stats
        """
        total = len(self._pool)
        in_use = sum(1 for s in self._pool.values() if s["in_use"])
        idle = total - in_use

        return {
            "total_sessions": total,
            "in_use": in_use,
            "idle": idle,
            "max_size": self.max_size,
            "utilization_percent": round((in_use / self.max_size) * 100, 1)
            if self.max_size > 0
            else 0,
            "backend": "applescript",
        }


# Global session pool singleton
_global_pool: ITerm2SessionPool | None = None
_pool_lock = asyncio.Lock()


async def get_global_pool() -> ITerm2SessionPool:
    """Get or create the global iTerm2 session pool.

    Returns:
        Global session pool instance
    """
    global _global_pool

    async with _pool_lock:
        if _global_pool is None:
            _global_pool = ITerm2SessionPool()
            await _global_pool.start_health_check()
            logger.info("Created global iTerm2 session pool")

        return _global_pool


async def close_global_pool() -> None:
    """Close the global session pool.

    Should be called on application shutdown.
    """
    global _global_pool

    async with _pool_lock:
        if _global_pool is not None:
            await _global_pool.close_all()
            _global_pool = None
            logger.info("Closed global iTerm2 session pool")


# Legacy aliases for backward compatibility
ITerm2ConnectionPool = ITerm2SessionPool
