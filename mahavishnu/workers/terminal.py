"""Terminal-based AI workers for headless execution with Session-Buddy storage."""

import asyncio
import json
import logging
from typing import Any

from ..terminal.manager import TerminalManager
from .base import BaseWorker, WorkerResult, WorkerStatus

logger = logging.getLogger(__name__)


class TerminalAIWorker(BaseWorker):
    """Worker that executes headless AI commands in terminals.

    Supports both Qwen and Claude Code CLI with JSON/streaming output.

    Features:
    - stream-json parsing for real-time updates
    - Session-Buddy integration for result storage
    - Exit code detection for completion
    - Timeout handling

    Args:
        terminal_manager: TerminalManager for session control
        ai_type: Type of AI CLI ("qwen" or "claude")
        session_id: Optional existing session ID
        session_buddy_client: Optional Session-Buddy MCP client for result storage
    """

    def __init__(
        self,
        terminal_manager: TerminalManager,
        ai_type: str,  # "qwen" | "claude"
        session_id: str | None = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(worker_type=f"terminal-{ai_type}")
        self.terminal_manager = terminal_manager
        self.ai_type = ai_type
        self.session_id = session_id
        self.session_buddy_client = session_buddy_client
        self._start_time: float | None = None

    async def start(self) -> str:
        """Launch terminal with AI CLI.

        Returns:
            Session ID for the launched terminal

        Raises:
            ValueError: If ai_type is not supported
        """
        if self.ai_type == "qwen":
            command = "qwen -o stream-json --approval-mode yolo"
        elif self.ai_type == "claude":
            command = "claude --output-format stream-json --permission-mode acceptEdits"
        else:
            raise ValueError(f"Unknown AI type: {self.ai_type}")

        # Launch terminal session
        session_ids = await self.terminal_manager.launch_sessions(
            command=command,
            count=1,
        )
        self.session_id = session_ids[0]
        self._status = WorkerStatus.RUNNING
        self._start_time = asyncio.get_event_loop().time()

        logger.info(f"Started {self.ai_type} worker: {self.session_id}")
        return self.session_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute task by sending prompt to AI worker.

        Args:
            task: Task specification with keys:
                - prompt: Task prompt to send to AI
                - timeout: Execution timeout in seconds (default: 300)
                - repo: Optional repository path for context

        Returns:
            WorkerResult with execution results
        """
        if not self.session_id:
            await self.start()

        # Send task prompt
        prompt = task.get("prompt", "")
        if task.get("repo"):
            prompt = f"Working in {task['repo']}. {prompt}"

        await self.terminal_manager.send_command(self.session_id, prompt)

        # Wait for completion (monitor stream-json output)
        result = await self._monitor_completion(task)

        # Store result in Session-Buddy
        if self.session_buddy_client:
            await self._store_result_in_session_buddy(result, task)

        return result

    async def _store_result_in_session_buddy(
        self,
        result: WorkerResult,
        task: dict[str, Any],
    ) -> None:
        """Store worker execution result in Session-Buddy for persistent history.

        Args:
            result: Worker execution result
            task: Original task specification
        """
        if not self.session_buddy_client:
            return

        try:
            # Store as memory with full context
            await self.session_buddy_client.call_tool(
                "store_memory",
                arguments={
                    "content": result.output or "",
                    "metadata": {
                        "type": "worker_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.ai_type,
                        "task_prompt": task.get("prompt", ""),
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                        "exit_code": result.exit_code,
                        "error": result.error,
                        "timestamp": result.timestamp,
                    },
                },
            )
            logger.info(f"Stored result for {self.session_id} in Session-Buddy")
        except Exception as e:
            # Log but don't fail - Session-Buddy is optional
            logger.warning(f"Failed to store result in Session-Buddy: {e}")

    async def _monitor_completion(self, task: dict[str, Any]) -> WorkerResult:
        """Monitor stream-json output for completion.

        Parses JSON lines to detect:
        - Assistant messages (response chunks)
        - Tool calls (execution progress)
        - Completion markers

        Args:
            task: Task specification for timeout settings

        Returns:
            WorkerResult with collected output
        """
        output_lines = []
        last_output = ""
        timeout = task.get("timeout", 300)

        while True:
            # Capture latest output
            try:
                output = await self.terminal_manager.capture_output(self.session_id, lines=50)
            except Exception as e:
                logger.error(f"Failed to capture output: {e}")
                output = ""

            # Parse stream-json lines
            for line in output.split("\n"):
                if line.strip():
                    try:
                        data = json.loads(line)
                        # Check for completion
                        if self._is_complete(data):
                            return self._build_result(output_lines, last_output)

                        # Extract assistant content
                        if "content" in data:
                            content = data["content"]
                            if isinstance(content, str):
                                output_lines.append(content)
                                last_output = content
                            elif isinstance(content, list):
                                # Handle multi-modal content
                                for item in content:
                                    if isinstance(item, dict) and "text" in item:
                                        output_lines.append(item["text"])
                                        last_output = item["text"]

                    except json.JSONDecodeError:
                        # Non-JSON line, append as text
                        output_lines.append(line)

            # Check timeout
            if self._start_time:
                elapsed = asyncio.get_event_loop().time() - self._start_time
                if elapsed > timeout:
                    logger.warning(f"Worker {self.session_id} timed out after {elapsed}s")
                    return WorkerResult(
                        worker_id=self.session_id,
                        status=WorkerStatus.TIMEOUT,
                        output="\n".join(output_lines),
                        error="Task timed out",
                        exit_code=None,
                        duration_seconds=elapsed,
                        metadata={"timeout": timeout},
                    )

            await asyncio.sleep(0.5)

    def _get_command_template(self) -> str:
        """Get command template for AI type.

        Returns:
            Command template string
        """
        if self.ai_type == "qwen":
            return "qwen -o stream-json --approval-mode yolo"
        elif self.ai_type == "claude":
            return "claude --output-format stream-json --permission-mode acceptEdits"
        else:
            raise ValueError(f"Unknown AI type: {self.ai_type}")

    def _is_complete(self, data: dict) -> bool:
        """Check if JSON message indicates completion.

        Args:
            data: Parsed JSON data from stream

        Returns:
            True if message indicates completion
        """
        # Qwen/Claude completion markers
        return (
            "finish_reason" in data
            or "done" in data
            or data.get("type") == "done"
            or data.get("type") == "completion"
            or data.get("status") == "completed"
        )

    def _extract_content(self, data: dict) -> str | None:
        """Extract content from JSON message.

        Args:
            data: Parsed JSON data from stream

        Returns:
            Extracted content string or None
        """
        # Try delta.content format (Qwen)
        if "delta" in data and isinstance(data["delta"], dict):
            return data["delta"].get("content")

        # Try direct text field (Claude)
        if "text" in data:
            return data["text"]

        # Try content field
        if "content" in data:
            content = data["content"]
            if isinstance(content, str):
                return content
            elif isinstance(content, list) and content:
                # Handle multi-modal content
                item = content[0]
                if isinstance(item, dict) and "text" in item:
                    return item["text"]

        return None

    def _build_result(
        self,
        output_lines: list[str],
        last_output: str,
    ) -> WorkerResult:
        """Build WorkerResult from collected output.

        Args:
            output_lines: All collected output lines
            last_output: Most recent output content

        Returns:
            Complete WorkerResult
        """
        duration = asyncio.get_event_loop().time() - self._start_time if self._start_time else 0

        full_output = "\n".join(output_lines)

        return WorkerResult(
            worker_id=self.session_id,
            status=WorkerStatus.COMPLETED,
            output=full_output,
            error=None,
            exit_code=0,
            duration_seconds=duration,
            metadata={
                "last_output": last_output,
                "output_lines": len(output_lines),
                "ai_type": self.ai_type,
            },
        )

    async def stop(self) -> None:
        """Stop the worker by closing terminal session."""
        if self.session_id:
            try:
                await self.terminal_manager.close_session(self.session_id)
                logger.info(f"Stopped worker {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to stop worker {self.session_id}: {e}")
            finally:
                self._status = WorkerStatus.COMPLETED

    async def status(self) -> WorkerStatus:
        """Get current worker status.

        Returns:
            Current WorkerStatus
        """
        # Try to get actual session status
        if self.session_id:
            try:
                sessions = await self.terminal_manager.list_sessions()
                for session in sessions:
                    if session.get("id") == self.session_id:
                        self._status = WorkerStatus.RUNNING
                        return self._status
            except Exception:
                pass

        # Session not found or error
        if self._status == WorkerStatus.RUNNING:
            self._status = WorkerStatus.COMPLETED

        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details
        """
        output = ""
        if self.session_id:
            try:
                output = await self.terminal_manager.capture_output(self.session_id, lines=10)
            except Exception:
                pass

        duration = asyncio.get_event_loop().time() - self._start_time if self._start_time else 0

        return {
            "status": self._status.value,
            "session_id": self.session_id,
            "output_preview": output[:200] if output else "",
            "duration_seconds": duration,
            "worker_type": self.worker_type,
            "ai_type": self.ai_type,
        }
