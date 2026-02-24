"""Application worker for MCP-based application control.

This worker type communicates with desktop applications via MCP protocol,
enabling automation of tools like GIMP, Inkscape, Blender, and mdinject.
"""

import asyncio
import logging
from typing import Any

from .base import BaseWorker, WorkerResult, WorkerStatus
from .registry import WorkerConfig, get_worker_config

logger = logging.getLogger(__name__)


class ApplicationWorker(BaseWorker):
    """Worker that controls applications via MCP protocol.

    Supports MCP-enabled applications for automation:
    - GIMP: Image editing operations
    - Inkscape: Vector graphics manipulation
    - Blender: 3D modeling and rendering
    - MDInject: Markdown prompt management

    Features:
    - MCP tool invocation
    - Progress tracking via MCP resources
    - Session-Buddy integration for result storage

    Example:
        >>> worker = ApplicationWorker(
        ...     worker_type="application-mdinject",
        ...     mcp_client=mcp_client,
        ... )
        >>> await worker.start()
        >>> result = await worker.execute({
        ...     "tool": "create_prompt",
        ...     "arguments": {"title": "My Prompt", "content": "..."}
        ... })
    """

    def __init__(
        self,
        worker_type: str,
        mcp_client: Any = None,
        config: WorkerConfig | None = None,
        session_buddy_client: Any = None,
        **kwargs: Any,
    ) -> None:
        """Initialize application worker.

        Args:
            worker_type: Type of application worker (e.g., "application-mdinject")
            mcp_client: MCP client for communicating with the application
            config: Optional WorkerConfig (loaded from registry if not provided)
            session_buddy_client: Optional Session-Buddy MCP client
            **kwargs: Additional parameters
        """
        self.config = config or get_worker_config(worker_type)
        if self.config is None:
            raise ValueError(f"Unknown worker type: {worker_type}")

        if not self.config.mcp_server:
            raise ValueError(f"Worker type {worker_type} is not an MCP application worker")

        super().__init__(worker_type=worker_type)
        self.mcp_client = mcp_client
        self.session_buddy_client = session_buddy_client
        self._start_time: float | None = None
        self._mcp_server_name = self.config.mcp_server

    async def start(self) -> str:
        """Initialize connection to MCP application.

        Returns:
            Worker ID (session identifier)

        Raises:
            RuntimeError: If MCP client is not available or connection fails
        """
        if self.mcp_client is None:
            raise RuntimeError(
                f"Cannot start {self.worker_type}: MCP client not provided. "
                f"Ensure MCP server '{self._mcp_server_name}' is configured and running."
            )

        self._status = WorkerStatus.RUNNING
        self._start_time = asyncio.get_event_loop().time()

        logger.info(f"Started {self.worker_type} worker connected to {self._mcp_server_name}")
        return self.worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute an MCP tool call on the application.

        Args:
            task: Task specification with keys:
                - tool: MCP tool name to call
                - arguments: Dictionary of arguments for the tool
                - timeout: Execution timeout (uses default if not specified)

        Returns:
            WorkerResult with execution results
        """
        if self._status != WorkerStatus.RUNNING:
            await self.start()

        tool_name = task.get("tool")
        arguments = task.get("arguments", {})
        timeout = task.get("timeout", self.config.default_timeout)

        if not tool_name:
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.FAILED,
                error="No tool name specified in task",
                metadata={"worker_type": self.worker_type},
            )

        try:
            # Call MCP tool
            result = await asyncio.wait_for(
                self._call_mcp_tool(tool_name, arguments),
                timeout=timeout,
            )

            # Extract output from result
            output = self._extract_output(result)

            # Build success result
            worker_result = WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                duration_seconds=asyncio.get_event_loop().time() - self._start_time
                if self._start_time
                else 0,
                metadata={
                    "tool": tool_name,
                    "arguments": arguments,
                    "worker_type": self.worker_type,
                    "mcp_server": self._mcp_server_name,
                },
            )

            # Store result in Session-Buddy
            if self.session_buddy_client:
                await self._store_result_in_session_buddy(worker_result, task)

            return worker_result

        except asyncio.TimeoutError:
            logger.error(f"MCP tool {tool_name} timed out after {timeout}s")
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.TIMEOUT,
                error=f"Tool execution timed out after {timeout}s",
                metadata={"tool": tool_name, "timeout": timeout},
            )

        except Exception as e:
            logger.error(f"MCP tool {tool_name} failed: {e}")
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                metadata={"tool": tool_name, "exception": type(e).__name__},
            )

    async def _call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool on the application server.

        Args:
            tool_name: Name of the MCP tool
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            RuntimeError: If MCP call fails
        """
        # The MCP client should be configured to route to the correct server
        # Tool names should be prefixed with server name, e.g., "mdinject__create_prompt"

        # Try both prefixed and unprefixed tool names
        prefixed_name = f"{self._mcp_server_name}__{tool_name}"

        try:
            # Try prefixed name first
            return await self.mcp_client.call_tool(prefixed_name, arguments)
        except Exception:
            # Fall back to unprefixed name
            return await self.mcp_client.call_tool(tool_name, arguments)

    def _extract_output(self, result: Any) -> str:
        """Extract output string from MCP tool result.

        Args:
            result: MCP tool result (can be various types)

        Returns:
            String representation of the result
        """
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            # Common MCP result structures
            if "content" in result:
                content = result["content"]
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            texts.append(item["text"])
                        elif isinstance(item, str):
                            texts.append(item)
                    return "\n".join(texts)

            if "result" in result:
                return str(result["result"])

            if "output" in result:
                return str(result["output"])

            # Fall back to JSON representation
            import json

            return json.dumps(result, indent=2)

        if isinstance(result, list):
            return "\n".join(str(item) for item in result)

        return str(result)

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
                        "type": "application_worker_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.worker_type,
                        "mcp_server": self._mcp_server_name,
                        "tool": task.get("tool"),
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                        "timestamp": result.timestamp,
                    },
                },
            )
            logger.info(f"Stored result for {self.worker_id} in Session-Buddy")
        except Exception as e:
            logger.warning(f"Failed to store result in Session-Buddy: {e}")

    async def stop(self) -> None:
        """Stop the worker (no-op for MCP workers)."""
        self._status = WorkerStatus.COMPLETED
        logger.info(f"Stopped {self.worker_type} worker")

    async def status(self) -> WorkerStatus:
        """Get current worker status.

        Returns:
            Current WorkerStatus
        """
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details
        """
        duration = asyncio.get_event_loop().time() - self._start_time if self._start_time else 0

        return {
            "status": self._status.value,
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "mcp_server": self._mcp_server_name,
            "duration_seconds": duration,
        }


__all__ = ["ApplicationWorker"]
