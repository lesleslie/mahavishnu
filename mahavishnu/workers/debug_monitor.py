"""Debug monitor worker for iTerm2 log tailing with Session-Buddy streaming."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..terminal.manager import TerminalManager
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)


class DebugMonitorWorker(BaseWorker):
    """Worker that tails debug logs in iTerm2 with Session-Buddy streaming.

    Hybrid implementation:
    1. iTerm2 Python API for screen capture
    2. Session-Buddy integration for persistent log storage
    3. Auto-launch when --debug mode is enabled

    Args:
        log_path: Path to debug log file
        terminal_manager: TerminalManager for session control
        session_buddy_client: Session-Buddy MCP client for streaming

    Example:
        >>> monitor = DebugMonitorWorker(
        ...     log_path=Path("/var/log/mahavishnu-debug.log"),
        ...     terminal_manager=terminal_mgr,
        ...     session_buddy_client=session_buddy_client
        ... )
        >>> monitor_id = await monitor.start()
        >>> # Streams logs to Session-Buddy automatically
    """

    def __init__(
        self,
        log_path: Path,
        terminal_manager: TerminalManager,
        session_buddy_client: Any = None,
    ) -> None:
        """Initialize debug monitor worker.

        Args:
            log_path: Path to debug log file
            terminal_manager: TerminalManager for terminal control
            session_buddy_client: Session-Buddy MCP client
        """
        super().__init__(worker_type="debug-monitor")
        self.log_path = log_path
        self.terminal_manager = terminal_manager
        self.session_buddy_client = session_buddy_client
        self.session_id: str | None = None
        self._iterm2_connection = None
        self._streaming_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> str:
        """Launch iTerm2 window with tail -f and start streaming to Session-Buddy.

        Returns:
            Session ID for the monitor terminal

        Raises:
            RuntimeError: If monitor fails to start
        """
        # Use iTerm2 adapter if available
        if self.terminal_manager.current_adapter() == "iterm2":
            return await self._start_iterm2_monitor()
        else:
            # Fallback to regular terminal
            return await self._start_terminal_monitor()

    async def _start_iterm2_monitor(self) -> str:
        """Start iTerm2-native debug monitor with screen capture.

        Returns:
            Session ID
        """
        # Get iTerm2 connection from adapter
        adapter = self.terminal_manager.adapter
        if hasattr(adapter, "_connection") and adapter._connection:
            self._iterm2_connection = adapter._connection

        # Launch tail -f in iTerm2
        command = f"tail -f {self.log_path}"
        session_ids = await self.terminal_manager.launch_sessions(
            command=command,
            count=1,
        )
        self.session_id = session_ids[0]

        # Start streaming to Session-Buddy
        if self.session_buddy_client:
            self._running = True
            self._streaming_task = asyncio.create_task(self._stream_to_session_buddy())

        logger.info(f"Started iTerm2 debug monitor: {self.session_id}")
        return self.session_id

    async def _start_terminal_monitor(self) -> str:
        """Start fallback terminal monitor.

        Returns:
            Session ID
        """
        command = f"tail -f {self.log_path}"
        session_ids = await self.terminal_manager.launch_sessions(
            command=command,
            count=1,
        )
        self.session_id = session_ids[0]

        # Still attempt streaming if Session-Buddy available
        if self.session_buddy_client:
            self._running = True
            self._streaming_task = asyncio.create_task(self._stream_to_session_buddy())

        logger.info(f"Started terminal debug monitor: {self.session_id}")
        return self.session_id

    async def _stream_to_session_buddy(self) -> None:
        """Stream captured log lines to Session-Buddy for persistent storage.

        Captures iTerm2 screen contents every second and stores in Session-Buddy
        as memories for searchable debug history.

        This method runs in the background until the worker is stopped.
        """
        if not self.session_buddy_client:
            return

        import iterm2

        try:
            line_count = 0

            while self._running:
                try:
                    # Capture screen contents using iTerm2 API
                    if self._iterm2_connection and self.session_id:
                        # Find the session
                        app = await iterm2.App.async_get_connection(self._iterm2_connection)
                        sessions = await app.async_get_sessions()

                        # Find our debug session by session_id
                        debug_session = None
                        for session in sessions:
                            session_id = getattr(session, "session_id", None)
                            if session_id == self.session_id:
                                debug_session = session
                                break

                        if debug_session:
                            # Get screen contents (last 100 lines)
                            try:
                                contents = await debug_session.async_get_contents(
                                    first_line=-100, number_of_lines=100
                                )

                                # Extract text from screen contents
                                log_lines = []
                                for line in contents:
                                    text = getattr(line, "string", None)
                                    if text:
                                        log_lines.append(text)

                                log_text = "\n".join(log_lines)

                                # Store in Session-Buddy as memory
                                if log_text.strip():  # Only store non-empty
                                    await self.session_buddy_client.call_tool(
                                        "store_memory",
                                        arguments={
                                            "content": log_text,
                                            "metadata": {
                                                "type": "debug_log",
                                                "source": "mahavishnu_debug_monitor",
                                                "log_path": str(self.log_path),
                                                "session_id": self.session_id,
                                                "line_count": line_count,
                                            },
                                        },
                                    )

                                    line_count += 1
                                    if line_count % 60 == 0:  # Log every minute
                                        logger.debug(
                                            f"Streamed {line_count} updates to Session-Buddy "
                                            f"for {self.session_id}"
                                        )

                            except Exception as e:
                                logger.warning(f"Failed to capture iTerm2 screen: {e}")

                    # Wait before next capture
                    await asyncio.sleep(1)

                except Exception as e:
                    if self._running:
                        logger.warning(f"Error in streaming loop: {e}")
                    await asyncio.sleep(5)  # Wait before retry

        except asyncio.CancelledError:
            logger.info("Debug monitor streaming cancelled")
        except Exception as e:
            logger.error(f"Fatal error in streaming: {e}")
        finally:
            logger.info(f"Debug monitor streaming stopped for {self.session_id}")

    async def stop(self) -> None:
        """Stop debug monitor and cancel streaming.

        Raises:
            RuntimeError: If monitor fails to stop
        """
        self._running = False

        if self._streaming_task:
            self._streaming_task.cancel()
            try:
                await self._streaming_task
            except asyncio.CancelledError:
                pass
            finally:
                self._streaming_task = None

        if self.session_id:
            try:
                await self.terminal_manager.close_session(self.session_id)
                logger.info(f"Stopped debug monitor: {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to close debug monitor session: {e}")
            finally:
                self.session_id = None

        self._status = WorkerStatus.COMPLETED

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Debug monitor doesn't execute tasks, just monitors.

        Args:
            task: Task specification (ignored for monitor)

        Returns:
            WorkerResult indicating passive monitoring

        Raises:
            NotImplementedError: Always - debug monitor is passive
        """
        raise NotImplementedError(
            "Debug monitor is passive and does not execute tasks. "
            "It only tails log files and streams to Session-Buddy."
        )

    async def status(self) -> WorkerStatus:
        """Get debug monitor status.

        Returns:
            Current WorkerStatus
        """
        if not self.session_id:
            return WorkerStatus.PENDING

        # Check if streaming task is still running
        if self._streaming_task and not self._streaming_task.done():
            return WorkerStatus.RUNNING

        # Check if session is still active
        try:
            sessions = await self.terminal_manager.list_sessions()
            for session in sessions:
                if session.get("id") == self.session_id:
                    return WorkerStatus.RUNNING
        except Exception:
            pass

        return WorkerStatus.COMPLETED

    async def get_progress(self) -> dict[str, Any]:
        """Get debug monitor progress information.

        Returns:
            Dictionary with progress details
        """
        streaming_active = self._streaming_task is not None and not self._streaming_task.done()

        return {
            "status": await self.status(),
            "session_id": self.session_id,
            "log_path": str(self.log_path),
            "streaming_active": streaming_active,
            "iterm2_connected": self._iterm2_connection is not None,
            "running": self._running,
        }
