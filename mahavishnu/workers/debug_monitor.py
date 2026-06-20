"""Debug monitor worker for iTerm2 log tailing with Session-Buddy streaming."""

from __future__ import annotations

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
        raise NotImplementedError(
            "DebugMonitorWorker is deprecated. "
            "Use CrowTerminalAdapter with GenericShellWorker for terminal debugging. "
            "Full removal scheduled for Wave 2."
        )

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

    async def _capture_iterm2_screen(self, iterm2: Any) -> str | None:
        if not self._iterm2_connection or not self.session_id:
            return None
        app = await iterm2.App.async_get_connection(self._iterm2_connection)
        sessions = await app.async_get_sessions()
        debug_session = next(
            (s for s in sessions if getattr(s, "session_id", None) == self.session_id), None
        )
        if not debug_session:
            return None
        contents = await debug_session.async_get_contents(first_line=-100, number_of_lines=100)
        lines = [text for line in contents if (text := getattr(line, "string", None))]
        return "\n".join(lines)

    async def _store_log_to_session_buddy(self, log_text: str, line_count: int) -> None:
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

    async def _stream_to_session_buddy(self) -> None:
        """Stream captured log lines to Session-Buddy for persistent storage."""
        if not self.session_buddy_client:
            return

        import iterm2

        try:
            line_count = 0
            while self._running:
                try:
                    try:
                        log_text = await self._capture_iterm2_screen(iterm2)
                        if log_text and log_text.strip():
                            await self._store_log_to_session_buddy(log_text, line_count)
                            line_count += 1
                            if line_count % 60 == 0:
                                logger.debug(
                                    f"Streamed {line_count} updates to Session-Buddy "
                                    f"for {self.session_id}"
                                )
                    except Exception as e:
                        logger.warning(f"Failed to capture iTerm2 screen: {e}")

                    await asyncio.sleep(1)
                except Exception as e:
                    if self._running:
                        logger.warning(f"Error in streaming loop: {e}")
                    await asyncio.sleep(5)

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
