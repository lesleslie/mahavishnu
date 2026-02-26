"""Generic shell worker for various terminal-based environments.

This worker can handle bash, zsh, python, ipython, node, ssh, and AI assistants
by using the worker registry for configuration.
"""

import asyncio
import contextlib
import json
import logging
import re
from typing import Any

from ..terminal.manager import TerminalManager
from .base import BaseWorker, WorkerResult, WorkerStatus
from .registry import WorkerCategory, WorkerConfig, get_worker_config

logger = logging.getLogger(__name__)


class GenericShellWorker(BaseWorker):
    """Generic worker for shell/REPL/AI environments.

    Supports multiple worker types through configuration:
    - Shell: bash, zsh
    - REPL: python, ipython, node
    - AI: qwen, claude, aider, opencode
    - Remote: ssh

    Features:
    - Configurable completion detection
    - Multiple output formats (text, json, line-delimited)
    - Session-Buddy integration
    - Timeout handling
    - Error detection

    Example:
        >>> worker = GenericShellWorker(
        ...     terminal_manager=tm,
        ...     worker_type="terminal-ipython",
        ... )
        >>> await worker.start()
        >>> result = await worker.execute({"prompt": "import pandas as pd"})
    """

    def __init__(
        self,
        terminal_manager: TerminalManager,
        worker_type: str,
        config: WorkerConfig | None = None,
        session_id: str | None = None,
        session_buddy_client: Any = None,
        **kwargs: Any,
    ) -> None:
        """Initialize generic shell worker.

        Args:
            terminal_manager: TerminalManager for session control
            worker_type: Type of worker (e.g., "terminal-shell", "terminal-python")
            config: Optional WorkerConfig (loaded from registry if not provided)
            session_id: Optional existing session ID
            session_buddy_client: Optional Session-Buddy MCP client
            **kwargs: Additional parameters (e.g., host for SSH)
        """
        # Load config from registry if not provided
        self.config = config or get_worker_config(worker_type)
        if self.config is None:
            raise ValueError(f"Unknown worker type: {worker_type}")

        super().__init__(worker_type=worker_type)
        self.terminal_manager = terminal_manager
        self.session_id = session_id
        self.session_buddy_client = session_buddy_client
        self._start_time: float | None = None
        self._kwargs = kwargs

        # For SSH, require host parameter
        if worker_type == "terminal-ssh" and "host" not in kwargs:
            raise ValueError("SSH worker requires 'host' parameter")

    async def start(self) -> str:
        """Launch terminal session with configured command.

        Returns:
            Session ID for the launched terminal

        Raises:
            RuntimeError: If terminal_manager is not available
            ValueError: If command cannot be formatted
        """
        if self.terminal_manager is None:
            raise RuntimeError(
                "Cannot start worker: terminal_manager is not available. "
                "Ensure terminal management is enabled."
            )

        # Format command with any parameters
        command = self.config.command
        if self._kwargs:
            try:
                command = command.format(**self._kwargs)
            except KeyError as e:
                raise ValueError(f"Missing parameter for command: {e}")

        # Launch terminal session
        session_ids = await self.terminal_manager.launch_sessions(
            command=command,
            count=1,
        )
        self.session_id = session_ids[0]
        self._status = WorkerStatus.RUNNING
        self._start_time = asyncio.get_event_loop().time()

        logger.info(f"Started {self.worker_type} worker: {self.session_id}")
        return self.session_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute task in the shell.

        Args:
            task: Task specification with keys:
                - prompt: Command/prompt to send
                - timeout: Execution timeout (uses default if not specified)
                - wait_for_completion: Whether to wait for completion marker

        Returns:
            WorkerResult with execution results
        """
        if not self.session_id:
            await self.start()

        prompt = task.get("prompt", "")
        timeout = task.get("timeout", self.config.default_timeout)
        wait_for_completion = task.get("wait_for_completion", True)

        # Send the prompt/command
        await self.terminal_manager.send_command(self.session_id, prompt)

        if wait_for_completion:
            # Monitor for completion
            result = await self._monitor_completion(task, timeout)
        else:
            # Just capture current output
            output = await self.terminal_manager.capture_output(self.session_id, lines=50)
            result = self._build_result(output, "", timeout)

        # Store result in Session-Buddy
        if self.session_buddy_client:
            await self._store_result_in_session_buddy(result, task)

        return result

    async def _monitor_completion(
        self,
        task: dict[str, Any],
        timeout: int,
    ) -> WorkerResult:
        """Monitor output for completion.

        Args:
            task: Original task specification
            timeout: Timeout in seconds

        Returns:
            WorkerResult when completion detected or timeout
        """
        output_lines: list[str] = []
        last_output = ""
        start_time = asyncio.get_event_loop().time()

        while True:
            # Capture latest output
            try:
                output = await self.terminal_manager.capture_output(self.session_id, lines=100)
            except Exception as e:
                logger.error(f"Failed to capture output: {e}")
                output = ""

            # Check for completion based on stream format
            if self.config.stream_format == "json":
                completed, content = self._check_json_completion(output)
                if content:
                    output_lines.append(content)
                    last_output = content
            else:
                # Text format - check for completion markers
                completed, content = self._check_text_completion(output)
                if content and content not in output_lines:
                    output_lines.append(content)
                    last_output = content

            if completed:
                return self._build_result("\n".join(output_lines), last_output, timeout)

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.warning(f"Worker {self.session_id} timed out after {elapsed}s")
                return WorkerResult(
                    worker_id=self.session_id or "unknown",
                    status=WorkerStatus.TIMEOUT,
                    output="\n".join(output_lines),
                    error="Task timed out",
                    exit_code=None,
                    duration_seconds=elapsed,
                    metadata={"timeout": timeout, "worker_type": self.worker_type},
                )

            await asyncio.sleep(0.5)

    def _check_json_completion(self, output: str) -> tuple[bool, str | None]:
        """Check for completion in JSON stream output.

        Args:
            output: Raw output from terminal

        Returns:
            Tuple of (is_complete, extracted_content)
        """
        for line in output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Check completion markers
                for marker in self.config.completion_markers:
                    if marker in data:
                        return True, self._extract_json_content(data)
                # Check error markers
                for marker in self.config.error_markers:
                    if marker.lower() in str(data).lower():
                        return True, self._extract_json_content(data)
            except json.JSONDecodeError:
                continue
        return False, None

    def _extract_json_content(self, data: dict) -> str:
        """Extract content from JSON message.

        Args:
            data: Parsed JSON data

        Returns:
            Extracted content string
        """
        # Try common content locations
        if "content" in data:
            content = data["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                    elif isinstance(item, str):
                        texts.append(item)
                return " ".join(texts)
        if "text" in data:
            return data["text"]
        if "delta" in data and isinstance(data["delta"], dict):
            return data["delta"].get("content", "")
        if "message" in data:
            return data["message"]
        return json.dumps(data)

    def _check_text_completion(self, output: str) -> tuple[bool, str | None]:
        """Check for completion in text output.

        Args:
            output: Raw output from terminal

        Returns:
            Tuple of (is_complete, extracted_content)
        """
        lines = output.strip().split("\n")
        if not lines:
            return False, None

        last_line = lines[-1].strip()

        # Check for prompt indicators (shell ready)
        for marker in self.config.completion_markers:
            if marker in last_line:
                # Shell is ready at prompt - extract content before prompt
                content = "\n".join(lines[:-1]) if len(lines) > 1 else ""
                return True, content

        # Check for error markers
        for marker in self.config.error_markers:
            if marker.lower() in output.lower():
                return True, output

        return False, None

    def _build_result(
        self,
        output: str,
        last_output: str,
        timeout: int,
    ) -> WorkerResult:
        """Build WorkerResult from collected output.

        Args:
            output: Full collected output
            last_output: Most recent output content
            timeout: Configured timeout

        Returns:
            Complete WorkerResult
        """
        duration = asyncio.get_event_loop().time() - self._start_time if self._start_time else 0

        # Detect errors in output
        has_error = any(marker.lower() in output.lower() for marker in self.config.error_markers)
        status = WorkerStatus.FAILED if has_error else WorkerStatus.COMPLETED

        return WorkerResult(
            worker_id=self.session_id or "unknown",
            status=status,
            output=output,
            error=None if not has_error else "Error detected in output",
            exit_code=0 if status == WorkerStatus.COMPLETED else 1,
            duration_seconds=duration,
            metadata={
                "last_output": last_output[:200] if last_output else "",
                "worker_type": self.worker_type,
                "category": self.config.category.value,
                "timeout": timeout,
            },
        )

    async def _store_result_in_session_buddy(
        self,
        result: WorkerResult,
        task: dict[str, Any],
    ) -> None:
        """Store worker execution result in Session-Buddy.

        Args:
            result: Worker execution result
            task: Original task specification
        """
        if not self.session_buddy_client:
            return

        try:
            await self.session_buddy_client.call_tool(
                "store_memory",
                arguments={
                    "content": result.output or "",
                    "metadata": {
                        "type": "worker_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.worker_type,
                        "category": self.config.category.value,
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
            logger.warning(f"Failed to store result in Session-Buddy: {e}")

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
        if self.session_id:
            try:
                sessions = await self.terminal_manager.list_sessions()
                for session in sessions:
                    if session.get("id") == self.session_id:
                        self._status = WorkerStatus.RUNNING
                        return self._status
            except Exception:
                pass

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
            with contextlib.suppress(Exception):
                output = await self.terminal_manager.capture_output(self.session_id, lines=10)

        duration = asyncio.get_event_loop().time() - self._start_time if self._start_time else 0

        return {
            "status": self._status.value,
            "session_id": self.session_id,
            "output_preview": output[:200] if output else "",
            "duration_seconds": duration,
            "worker_type": self.worker_type,
            "category": self.config.category.value,
        }


__all__ = ["GenericShellWorker"]
