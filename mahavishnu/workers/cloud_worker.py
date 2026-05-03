"""Cloud AI worker for OpenAI-compatible API task execution.

This worker provides AI task execution through cloud providers (ZAI, Qwen,
OpenAI) using the OpenAI-compatible chat completions API.

Features:
- OpenAI-compatible API support (ZAI, Qwen, OpenAI)
- Intelligent model routing based on task type
- Circuit breaker integration via mcp_common.llm
- Configurable generation parameters
- Connection health monitoring
- Session-Buddy integration for result storage
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
import time
from typing import Any

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult
from .task_router import (
    DEFAULT_ZAI_ROUTING,
    TaskCategory,
    get_model_for_task,
)

logger = logging.getLogger(__name__)

ZAI_CODING_PLAN_URL = "https://api.z.ai/api/coding/paas/v4"


@dataclass
class CloudWorkerConfig:
    """Configuration for cloud AI worker.

    Attributes:
        base_url: OpenAI-compatible API endpoint
        api_key: API key (or env var reference)
        model: Default model identifier
        timeout: Request timeout in seconds
        temperature: Sampling temperature (0.0-2.0)
        max_tokens: Maximum tokens to generate
        intelligent_routing: Enable automatic model selection based on task type
        model_routing: Custom model routing (category -> model)
    """

    base_url: str = field(
        default_factory=lambda: os.environ.get("ZAI_BASE_URL", ZAI_CODING_PLAN_URL)
    )
    api_key: str = field(default_factory=lambda: os.environ.get("ZAI_API_KEY", ""))
    model: str = "glm-4.7"
    timeout: int = 300
    temperature: float = 0.7
    max_tokens: int = 4096
    intelligent_routing: bool = True
    model_routing: dict[TaskCategory, str] | None = None

    def get_model_for_category(self, category: TaskCategory) -> str:
        """Get the appropriate model for a task category."""
        routing = self.model_routing or DEFAULT_ZAI_ROUTING
        return routing.get(category, self.model)


class CloudWorker(BaseWorker):
    """Worker that executes tasks via OpenAI-compatible cloud APIs.

    Supports ZAI GLM models, Qwen, OpenAI, and any provider that
    implements the OpenAI chat completions API.

    Args:
        config: Cloud worker configuration with API settings
        worker_id: Unique identifier for this worker instance
        session_buddy_client: Optional Session-Buddy client for result storage
    """

    def __init__(
        self,
        config: CloudWorkerConfig | None = None,
        worker_id: str | None = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(worker_type="terminal-cloud")
        self.config = config or CloudWorkerConfig()
        self._worker_id = worker_id or f"cloud-{int(time.time())}"
        self.session_buddy_client = session_buddy_client
        self._client: Any = None
        self._start_time: float | None = None

    async def start(self) -> str:
        """Initialize the cloud worker.

        Creates the OpenAI async client with configured credentials.

        Returns:
            Worker ID string

        Raises:
            RuntimeError: If API key is not configured
        """
        self._status = WorkerStatus.STARTING
        self._start_time = time.time()

        if not self.config.api_key:
            self._status = WorkerStatus.FAILED
            raise RuntimeError(
                "Cloud worker requires an API key. "
                "Set ZAI_API_KEY environment variable or pass api_key in config."
            )

        # Lazy import — openai is optional
        try:
            import openai
        except ImportError:
            self._status = WorkerStatus.FAILED
            raise RuntimeError(
                "openai package required for CloudWorker. Install with: pip install mcp-common[llm]"
            ) from None

        self._client = openai.AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            max_retries=2,
            timeout=self.config.timeout,
        )

        self._status = WorkerStatus.RUNNING
        logger.info(
            "Started cloud worker: %s (model: %s, base_url: %s)",
            self._worker_id,
            self.config.model,
            self.config.base_url,
        )
        return self._worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task using OpenAI-compatible cloud API.

        Args:
            task: Task specification with keys:
                - prompt: Task prompt to send to AI (required)
                - timeout: Execution timeout in seconds (default: config.timeout)
                - model: Override model for this task (skips intelligent routing)
                - system: Optional system prompt
                - temperature: Override temperature for this task
                - max_tokens: Override max tokens for this task
                - context: Optional context dict for intelligent routing

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

        timeout = task.get("timeout", self.config.timeout)
        system = task.get("system")
        temperature = task.get("temperature", self.config.temperature)
        max_tokens = task.get("max_tokens", self.config.max_tokens)
        task_context = task.get("context")

        # Intelligent model selection (unless explicitly specified)
        explicit_model = task.get("model")
        if explicit_model:
            model = explicit_model
            task_category = TaskCategory.GENERAL
            logger.info("Using explicitly specified model: %s", model)
        elif self.config.intelligent_routing:
            model, task_category = get_model_for_task(
                prompt=prompt,
                model_routing=self.config.model_routing or DEFAULT_ZAI_ROUTING,
                default_model=self.config.model,
                context=task_context,
            )
            logger.info("Intelligent routing: %s -> %s", task_category.value, model)
        else:
            model = self.config.model
            task_category = TaskCategory.GENERAL

        start_time = time.time()

        try:
            # Build messages
            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            # Call the API
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=timeout,
            )

            output = response.choices[0].message.content or ""
            duration = time.time() - start_time

            # Extract usage stats
            usage = response.usage.model_dump() if response.usage else {}

            result = WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                exit_code=0,
                duration_seconds=duration,
                metadata={
                    "model": model,
                    "task_category": task_category.value,
                    "provider": "cloud",
                    "base_url": self.config.base_url,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "intelligent_routing": self.config.intelligent_routing and not explicit_model,
                    "usage": usage,
                },
            )

            # Store in Session-Buddy if available
            if self.session_buddy_client:
                await self._store_result_in_session_buddy(result, task)

            return result

        except TimeoutError:
            duration = time.time() - start_time
            logger.warning("Cloud task timed out after %ss", duration)
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.TIMEOUT,
                error=f"Task timed out after {timeout}s",
                duration_seconds=duration,
                metadata={"timeout": timeout},
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Cloud task failed: %s", e)
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                duration_seconds=duration,
            )

    async def stop(self) -> None:
        """Stop the worker by closing the client."""
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.error("Error closing cloud client: %s", e)
            finally:
                self._client = None
        self._status = WorkerStatus.COMPLETED
        logger.info("Stopped cloud worker: %s", self._worker_id)

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
            "model": self.config.model,
            "duration_seconds": duration,
            "base_url": self.config.base_url,
        }

    async def health_check(self) -> dict[str, Any]:
        """Check worker health and availability."""
        try:
            if self._client:
                # Try listing models as a lightweight health check
                await asyncio.wait_for(
                    self._client.models.list(),
                    timeout=10.0,
                )
                ollama_available = True
            else:
                ollama_available = False

            return {
                "healthy": self._status == WorkerStatus.RUNNING and ollama_available,
                "status": self._status.value,
                "worker_type": self.worker_type,
                "details": {
                    "provider": "cloud",
                    "model": self.config.model,
                    "base_url": self.config.base_url,
                    "api_key_set": bool(self.config.api_key),
                },
            }
        except Exception as e:
            return {
                "healthy": False,
                "status": self._status.value,
                "worker_type": self.worker_type,
                "details": {"error": str(e)},
            }

    async def _store_result_in_session_buddy(
        self,
        result: WorkerResult,
        task: dict[str, Any],
    ) -> None:
        """Store execution result in Session-Buddy."""
        if not self.session_buddy_client:
            return

        try:
            await self.session_buddy_client.call_tool(
                "store_memory",
                arguments={
                    "content": result.output or "",
                    "metadata": {
                        "type": "cloud_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.worker_type,
                        "model": self.config.model,
                        "task_prompt": task.get("prompt", "")[:500],
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                    },
                },
            )
            logger.debug("Stored result in Session-Buddy: %s", self._worker_id)
        except Exception as e:
            logger.warning("Failed to store result in Session-Buddy: %s", e)


__all__ = [
    "CloudWorker",
    "CloudWorkerConfig",
]
