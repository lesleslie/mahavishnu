"""In-process nanobot worker for lightweight AI task execution.

Two modes:
- Runner mode (in-process-nanobot): Uses nanobot.agent.runner.AgentRunner
  Bare LLM+tools loop, no sessions/memory, lightweight.
- Loop mode (in-process-nanobot-loop): Uses nanobot.agent.loop.AgentLoop
  Full features: sessions, memory, MCP tools, skills.

Key design:
- No terminal dependency, no MCP client dependency
- Timeout enforced via asyncio.wait_for()
- worker_id generated as nanobot_{uuid_hex[:12]}
- Loop mode creates a fresh AgentLoop per execute call (prevents state leakage)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
import uuid

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)


class NanobotWorker(BaseWorker):
    """In-process worker using nanobot's Python API for AI task execution.

    Args:
        worker_type: Either "in-process-nanobot" or "in-process-nanobot-loop"
        nanobot_provider: A nanobot LLM provider instance (e.g. OpenAICompatProvider)
        config: WorkerConfig from registry
        session_buddy_client: Optional Session-Buddy client for result storage
    """

    def __init__(
        self,
        worker_type: str = "in-process-nanobot",
        nanobot_provider: Any = None,
        config: Any = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(worker_type=worker_type)
        self._worker_id = f"nanobot_{uuid.uuid4().hex[:12]}"
        self._nanobot_provider = nanobot_provider
        self._config = config
        self._session_buddy_client = session_buddy_client
        self._start_time: float | None = None
        self._is_loop_mode = worker_type == "in-process-nanobot-loop"

    @property
    def worker_id(self) -> str:  # type: ignore[override]
        """Return the worker ID (read-only after init)."""
        return self._worker_id

    async def start(self) -> str:
        """Initialize the nanobot worker.

        Verifies that the nanobot provider is available.

        Returns:
            Worker ID string

        Raises:
            RuntimeError: If nanobot provider is not configured
        """
        self._status = WorkerStatus.STARTING
        self._start_time = time.time()

        if self._nanobot_provider is None:
            self._status = WorkerStatus.FAILED
            raise RuntimeError(
                "NanobotWorker requires a nanobot_provider. "
                "Ensure ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL are set, "
                "or pass a provider explicitly."
            )

        # Verify provider is callable / has expected interface
        if not hasattr(self._nanobot_provider, "complete"):
            logger.warning(
                "nanobot_provider does not have a 'complete' method; "
                "execution may fail if the provider interface differs."
            )

        self._status = WorkerStatus.RUNNING
        mode = "loop" if self._is_loop_mode else "runner"
        logger.info(f"Started NanobotWorker: {self._worker_id} (mode={mode})")
        return self._worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task via nanobot's Python API.

        Args:
            task: Task specification with keys:
                - prompt: Task prompt to send to AI (required)
                - timeout: Execution timeout in seconds
                - system: Optional system prompt
                - tools: Optional list of tool definitions
                - context: Optional context dict

        Returns:
            WorkerResult with execution results
        """
        if self._status != WorkerStatus.RUNNING:
            await self.start()

        prompt = task.get("prompt", "")
        if not prompt:
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error="No prompt provided in task",
            )

        timeout = task.get(
            "timeout",
            self._config.default_timeout if self._config else 300,
        )
        system = task.get("system")
        tools = task.get("tools")

        start_time = time.time()

        try:
            if self._is_loop_mode:
                output = await asyncio.wait_for(
                    self._execute_loop(prompt, system=system, tools=tools),
                    timeout=timeout,
                )
            else:
                output = await asyncio.wait_for(
                    self._execute_runner(prompt, system=system, tools=tools),
                    timeout=timeout,
                )

            duration = time.time() - start_time

            result = WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                exit_code=0,
                duration_seconds=duration,
                metadata={
                    "mode": "loop" if self._is_loop_mode else "runner",
                    "provider_type": type(self._nanobot_provider).__name__,
                },
            )

            # Store in Session-Buddy if available
            if self._session_buddy_client:
                await self._store_result(result, task)

            return result

        except TimeoutError:
            duration = time.time() - start_time
            logger.warning(f"Nanobot task timed out after {duration:.1f}s")
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.TIMEOUT,
                error=f"Task timed out after {timeout}s",
                duration_seconds=duration,
                metadata={"timeout": timeout},
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Nanobot task failed: {e}")
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                duration_seconds=duration,
            )

    async def stop(self) -> None:
        """Stop the worker."""
        self._status = WorkerStatus.COMPLETED
        logger.info(f"Stopped NanobotWorker: {self._worker_id}")

    async def status(self) -> WorkerStatus:
        """Get current worker status."""
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information."""
        duration = time.time() - self._start_time if self._start_time else 0
        return {
            "status": self._status.value,
            "worker_id": self._worker_id,
            "worker_type": self.worker_type,
            "mode": "loop" if self._is_loop_mode else "runner",
            "duration_seconds": duration,
            "provider": type(self._nanobot_provider).__name__ if self._nanobot_provider else None,
        }

    # ── Private helpers ──────────────────────────────────────────────

    async def _execute_runner(
        self,
        prompt: str,
        system: str | None = None,
        tools: list[Any] | None = None,
    ) -> str:
        """Execute using AgentRunner (bare LLM+tools loop, no sessions)."""
        from nanobot.agent.runner import AgentRunner

        runner = AgentRunner(
            provider=self._nanobot_provider,
            system=system or "You are a helpful coding assistant.",
            tools=tools or [],
        )
        response = await runner.run(prompt)
        return str(response)

    async def _execute_loop(
        self,
        prompt: str,
        system: str | None = None,
        tools: list[Any] | None = None,
    ) -> str:
        """Execute using AgentLoop (full features, fresh per call).

        Creates a new AgentLoop per execute call to prevent state leakage,
        then cleans up with close_mcp().
        """
        from nanobot.agent.loop import AgentLoop

        agent_loop = AgentLoop(
            provider=self._nanobot_provider,
            system=system or "You are a helpful coding assistant.",
            tools=tools or [],
        )
        try:
            response = await agent_loop.run(prompt)
            return str(response)
        finally:
            # Clean up MCP connections if the loop opened any
            cleanup = getattr(agent_loop, "close_mcp", None)
            if callable(cleanup):
                try:
                    await cleanup()
                except Exception as exc:
                    logger.debug(f"AgentLoop cleanup warning: {exc}")

    async def _store_result(
        self,
        result: WorkerResult,
        task: dict[str, Any],
    ) -> None:
        """Store execution result in Session-Buddy."""
        if not self._session_buddy_client:
            return

        try:
            await self._session_buddy_client.call_tool(
                "store_memory",
                arguments={
                    "content": result.output or "",
                    "metadata": {
                        "type": "nanobot_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.worker_type,
                        "mode": "loop" if self._is_loop_mode else "runner",
                        "task_prompt": task.get("prompt", "")[:500],
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                    },
                },
            )
            logger.debug(f"Stored result in Session-Buddy: {self._worker_id}")
        except Exception as e:
            logger.warning(f"Failed to store result in Session-Buddy: {e}")


__all__ = ["NanobotWorker"]
