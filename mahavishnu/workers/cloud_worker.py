"""Cloud AI worker — three-tier FallbackChain (MiniMax → llama-server → Ollama).

Delegates all LLM dispatch to mcp_common.llm.FallbackChain, which handles
per-provider retry, circuit breaking, and fail-closed auth checks.
Intelligent task classification via classify_task() feeds the task_type
field so each provider selects the right model from its routing table.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
import time
from typing import Any

from mcp_common.llm import FallbackChain, LLMSettings

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult
from .task_router import (
    DEFAULT_LLAMA_SERVER_ROUTING,
    DEFAULT_MINIMAX_ROUTING,
    DEFAULT_OLLAMA_ROUTING,
    TaskCategory,
    classify_task,
    get_rate_limiter,
    routing_to_task_map,
)

logger = logging.getLogger(__name__)

MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"


@dataclass
class CloudWorkerConfig:
    """Configuration for cloud AI worker.

    Attributes:
        minimax_url: MiniMax API endpoint (OpenAI-compatible)
        llama_server_url: llama.cpp server endpoint (secondary)
        ollama_url: Ollama endpoint (tertiary)
        model: Default MiniMax model when no task_type routing matches
        timeout: Request timeout in seconds (applied to each provider tier)
        temperature: Sampling temperature (0.0-2.0)
        max_tokens: Maximum tokens to generate
        intelligent_routing: Enable automatic model selection based on task type
        model_routing: Custom MiniMax model routing (overrides DEFAULT_MINIMAX_ROUTING)
    """

    minimax_url: str = field(
        default_factory=lambda: os.environ.get("MINIMAX_BASE_URL") or MINIMAX_OPENAI_BASE_URL
    )
    llama_server_url: str = field(
        default_factory=lambda: os.environ.get("LLAMA_SERVER_URL", "http://localhost:8081")
    )
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    )
    model: str = "MiniMax-M2.7"
    timeout: int = 300
    temperature: float = 0.7
    max_tokens: int = 4096
    intelligent_routing: bool = True
    model_routing: dict[TaskCategory, str] | None = None

    def get_model_for_category(self, category: TaskCategory) -> str:
        """Get the MiniMax model for a task category (used for rate limiting)."""
        routing = self.model_routing or DEFAULT_MINIMAX_ROUTING
        return routing.get(category, self.model)


def _build_fallback_chain(config: CloudWorkerConfig) -> FallbackChain:
    minimax_routing = routing_to_task_map(config.model_routing or DEFAULT_MINIMAX_ROUTING)
    settings = LLMSettings(
        providers={
            "minimax": {
                "name": "minimax",
                "base_url": config.minimax_url,
                "api_key": "${MINIMAX_API_KEY}",
                "require_auth": True,
                "task_routing": minimax_routing,
                "timeout_seconds": config.timeout,
            },
            "llama_server": {
                "name": "llama_server",
                "base_url": config.llama_server_url,
                "require_auth": False,
                "task_routing": routing_to_task_map(DEFAULT_LLAMA_SERVER_ROUTING),
                "timeout_seconds": config.timeout,
            },
            "ollama": {
                "name": "ollama",
                "base_url": config.ollama_url,
                "require_auth": False,
                "task_routing": routing_to_task_map(DEFAULT_OLLAMA_ROUTING),
                "timeout_seconds": config.timeout,
            },
        },
        fallback_chain=["minimax", "llama_server", "ollama"],
    )
    chain = FallbackChain.from_settings(settings)
    if len(chain._providers) < 3:
        logger.error(
            "FallbackChain built with only %d provider(s); check MINIMAX_API_KEY and local server URLs.",
            len(chain._providers),
        )
    return chain


class CloudWorker(BaseWorker):
    """Worker that executes tasks via a three-tier FallbackChain.

    Provider order: MiniMax (primary cloud) → llama-server/qwen3.5
    (local secondary) → Ollama/qwen2.5-coder (local tertiary).

    Args:
        config: Cloud worker configuration
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
        self._chain: FallbackChain | None = None
        self._start_time: float | None = None

    async def start(self) -> str:
        """Initialize the cloud worker by building the FallbackChain.

        Returns:
            Worker ID string
        """
        self._status = WorkerStatus.STARTING
        self._start_time = time.time()
        self._chain = _build_fallback_chain(self.config)
        self._status = WorkerStatus.RUNNING
        logger.info(
            "Started cloud worker: %s (primary: %s, model: %s)",
            self._worker_id,
            self.config.minimax_url,
            self.config.model,
        )
        return self._worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task via the three-tier FallbackChain.

        Args:
            task: Task specification with keys:
                - prompt: Task prompt (required)
                - timeout: Execution timeout override
                - model: Override model for primary provider
                - system: Optional system prompt
                - temperature: Override temperature
                - max_tokens: Override max tokens
                - context: Optional context dict for intelligent routing

        Returns:
            WorkerResult with execution results
        """
        if self._status != WorkerStatus.RUNNING:
            try:
                await self.start()
            except Exception as e:
                logger.error("Cloud worker failed to start: %s", e)
                return WorkerResult(
                    worker_id=self._worker_id,
                    status=WorkerStatus.FAILED,
                    error=f"Worker failed to start: {e}",
                )

        if self._chain is None:
            raise RuntimeError("invariant violated: _chain must be set after worker initialization")

        prompt = task.get("prompt", "")
        if not prompt:
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error="No prompt provided in task",
            )

        temperature = task.get("temperature", self.config.temperature)
        max_tokens = task.get("max_tokens", self.config.max_tokens)
        system = task.get("system")
        task_context = task.get("context")
        explicit_model = task.get("model")

        # Classify the task for intelligent model routing
        if explicit_model:
            task_category = TaskCategory.GENERAL
            logger.info("Using explicitly specified model: %s", explicit_model)
        elif self.config.intelligent_routing:
            task_category = classify_task(prompt, task_context)
            logger.info("Intelligent routing: %s", task_category.value)
        else:
            task_category = TaskCategory.GENERAL

        # Rate limit against the primary provider's expected model
        user_id: str | None = task.get("user_id")
        rate_limiter = get_rate_limiter()
        if rate_limiter is not None:
            model_for_rate = explicit_model or self.config.get_model_for_category(task_category)
            allowed = await rate_limiter.check_and_record(model_for_rate, user_id)
            if not allowed:
                logger.warning(
                    "Rate limit exceeded: model=%s user=%s", model_for_rate, user_id or "*"
                )
                try:
                    from mahavishnu.core.routing_metrics import get_routing_metrics

                    get_routing_metrics().record_rate_limit_rejected(model_for_rate)
                except Exception:
                    pass
                return WorkerResult(
                    worker_id=self._worker_id,
                    status=WorkerStatus.FAILED,
                    error=f"Rate limit exceeded for model {model_for_rate}",
                )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        chain_task: dict[str, Any] = {
            "task_type": task_category.value,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if explicit_model:
            chain_task["model"] = explicit_model

        start_time = time.time()

        try:
            result = await self._chain.execute(chain_task)
            duration = time.time() - start_time

            output = result.get("content", "")
            model = result.get("model", self.config.model)
            provider = result.get("provider", "unknown")
            usage = result.get("usage", {})

            worker_result = WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                exit_code=0,
                duration_seconds=duration,
                metadata={
                    "model": model,
                    "task_category": task_category.value,
                    "provider": provider,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "intelligent_routing": self.config.intelligent_routing and not explicit_model,
                    "usage": usage,
                },
            )

            if self.session_buddy_client:
                await self._store_result_in_session_buddy(worker_result, task)

            return worker_result

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Cloud task failed (all providers exhausted): %s", e)
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                duration_seconds=duration,
            )

    async def stop(self) -> None:
        """Stop the worker by releasing the chain reference."""
        self._chain = None
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
            "minimax_url": self.config.minimax_url,
        }

    async def health_check(self) -> dict[str, Any]:
        """Check worker health — reports per-provider availability."""
        if self._chain is None:
            return {
                "healthy": False,
                "status": self._status.value,
                "worker_type": self.worker_type,
                "details": {"error": "chain not initialized"},
            }

        provider_health: dict[str, bool] = {}
        for provider in self._chain._providers:
            try:
                provider_health[provider.name] = await asyncio.wait_for(
                    provider.health_check(), timeout=5.0
                )
            except Exception:
                provider_health[provider.name] = False

        any_healthy = any(provider_health.values())
        return {
            "healthy": self._status == WorkerStatus.RUNNING and any_healthy,
            "status": self._status.value,
            "worker_type": self.worker_type,
            "details": {
                "providers": provider_health,
                "model": self.config.model,
                "minimax_url": self.config.minimax_url,
            },
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
                        "model": result.metadata.get("model", self.config.model),
                        "provider": result.metadata.get("provider", "unknown"),
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
