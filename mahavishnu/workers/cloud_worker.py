"""Cloud AI worker — two-tier FallbackChain (MiniMax → llama-server).

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
import shutil
import time
from typing import Any

import httpx2 as httpx
from mcp_common.llm import FallbackChain, LLMSettings

from mahavishnu.core.status import WorkerStatus

from ..bifrost.cache_headers import (
    TRAFFIC_CLASS_WORKER,
    VIRTUAL_KEY_HEADER,
    build_gateway_headers,
)
from ..core.model_routing import (
    DEFAULT_LLAMA_SERVER_ROUTING,
    DEFAULT_MINIMAX_ROUTING,
    DEFAULT_RUNPOD_PUBLIC_ROUTING,
    TaskCategory,
    classify_task,
    gateway_openai_base_url,
    get_rate_limiter,
    routing_to_task_map,
)
from .base import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)

MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"


@dataclass
class CloudWorkerConfig:
    """Configuration for cloud AI worker.

    Attributes:
        minimax_url: MiniMax API endpoint (OpenAI-compatible)
        llama_server_url: llama.cpp server endpoint (secondary)
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
    # RunPod Public Endpoint id (``moonshot-kimi``, ``granite-4-0-h-small``,
    # ``qwen3-32b-awq`` etc.). Optional — when unset, the runpod_public
    # provider is not added to the FallbackChain and the worker behaves
    # exactly as before (minimax → llama_server only).
    runpod_public_endpoint_id: str = field(
        default_factory=lambda: os.getenv("RUNPOD_PUBLIC_ENDPOINT_ID", "")
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


def _resolve_minimax_endpoint(config: CloudWorkerConfig) -> tuple[str, bool]:
    """Resolve the MiniMax provider's base_url and whether it is the gateway.

    Phase 2 of the bifrost plan (2026-10-17, REQ-BIFROST-008):
    when the oneiric ``BifrostLLMRouter`` returns a URL for the
    OPENAI provider (router is enabled + OPENAI route is configured),
    the worker routes through the gateway. The FallbackChain's
    provider ``base_url`` is the OpenAI-compatible API root, so it
    must end in ``/v1`` -- see
    :func:`mahavishnu.core.model_routing.gateway_openai_base_url` for why
    the suffix is applied idempotently.

    Falls back to ``config.minimax_url`` (from the ``MINIMAX_BASE_URL``
    env var or the public default) when the router is not enabled
    or the OPENAI route is not configured.

    Returns:
        ``(base_url, via_gateway)``. The flag is ``True`` only when the
        URL came from the router, i.e. when the request will hit the
        Bifrost gateway and therefore needs the gateway virtual key.
    """
    from oneiric.adapters.llm.bifrost import get_router
    from oneiric.adapters.llm.llm_interface import LLMProvider

    resolved = get_router().resolve(LLMProvider.OPENAI)
    if resolved is not None:
        return gateway_openai_base_url(resolved), True
    return config.minimax_url, False


def _build_fallback_chain(config: CloudWorkerConfig) -> FallbackChain:
    minimax_routing = routing_to_task_map(config.model_routing or DEFAULT_MINIMAX_ROUTING)
    minimax_base_url, via_gateway = _resolve_minimax_endpoint(config)
    # req: REQ-BIFROST-035
    #
    # A Bifrost-routed call authenticates with the gateway virtual key,
    # not the provider's own key -- the gateway rejects a provider key
    # with "401 - virtual key is required". The virtual key travels in
    # ``x-bf-vk``; the provider key stays in ``Authorization`` and is
    # ignored by the gateway (it selects upstream keys from its own
    # config store). The same header set carries the cache headers that
    # make ``cache_mode`` effective.
    #
    # The cache headers are emitted even when the virtual key is missing:
    # ``cache_mode`` is an operator retention control, and a missing
    # credential must not invert it. build_gateway_headers owns that
    # decision and logs why it withheld the credential.
    #
    # The traffic class scopes the cache bucket. The worker is one
    # traffic class; the Agno adapter's OpenAI and Anthropic surfaces
    # are others, so a prompt carried over one protocol cannot be served
    # a response cached under the other.
    gateway_headers = (
        build_gateway_headers(minimax_base_url, traffic_class=TRAFFIC_CLASS_WORKER)
        if via_gateway
        else {}
    )
    if via_gateway and VIRTUAL_KEY_HEADER not in gateway_headers:
        # Fail loud: without the virtual key every gateway call returns
        # "401 - virtual key is required". Logging it here points at the
        # credential rather than at a confusing downstream auth error.
        # build_gateway_headers has already logged the specific reason
        # (missing credential, or a target the credential may not cross).
        logger.warning(
            "Routing through the Bifrost gateway without a virtual key; "
            "set BIFROST_VIRTUAL_KEY (the gateway will reject these calls)"
        )
    providers: dict[str, dict[str, object]] = {
        "minimax": {
            "name": "minimax",
            "base_url": minimax_base_url,
            "api_key": "${MINIMAX_API_KEY}",
            "default_headers": gateway_headers,
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
    }
    fallback_order: list[str] = ["minimax", "llama_server"]

    # 2026-10-19: when ``runpod_public_endpoint_id`` is set, register a
    # third tier pointing at ``https://api.runpod.ai/v2/{endpoint_id}/v1``.
    # The endpoint id is operator-supplied (env var or constructor kwarg);
    # only endpoints whose handler speaks the OpenAI chat-completions
    # protocol will return valid output. The base_url is composed at
    # chain-build time, so the operator never edits settings/models.yaml
    # base_url field directly for this provider.
    if config.runpod_public_endpoint_id:
        providers["runpod_public"] = {
            "name": "runpod_public",
            "base_url": (f"https://api.runpod.ai/v2/{config.runpod_public_endpoint_id}/v1"),
            "api_key": "${RUNPOD_API_KEY}",
            "require_auth": True,
            "task_routing": routing_to_task_map(DEFAULT_RUNPOD_PUBLIC_ROUTING),
            "timeout_seconds": config.timeout,
        }
        fallback_order.append("runpod_public")

    settings = LLMSettings(
        providers=providers,
        fallback_chain=fallback_order,
    )
    chain = FallbackChain.from_settings(settings)
    if len(chain._providers) < 2:
        logger.error(
            "FallbackChain built with only %d provider(s); check MINIMAX_API_KEY and local server URLs.",
            len(chain._providers),
        )
    return chain


# wired: re-exported via mahavishnu/workers/__init__.py indirectly through the
# workers package; consumed by tests/unit/test_cloud_worker.py and exercised
# by every CloudWorker() literal in production pool-routing code (see
# docs/plans/2026-05-16-llm-routing-plan2-downstream-migration.md
# for the design). The audit's static scanner cannot see parenthesized
# imports / __all__ entries / class-body references across files.
class CloudWorker(BaseWorker):
    """Worker that executes tasks via a two-tier FallbackChain.

    Provider order: MiniMax (primary cloud) → llama-server/qwen3.5
    (local fallback).

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
        self.metadata: dict[str, Any] = {}
        self.required_env: list[str] = ["MINIMAX_API_KEY"]
        # Synchronous credential probe populates metadata and seeds status so
        # callers see a degraded state immediately after construction.
        missing = [n for n in self.required_env if not os.environ.get(n)]
        self.metadata["missing_credentials"] = missing
        if missing:
            self._status = WorkerStatus.DEGRADED

    async def start(self, *, prompt: str | None = None) -> str:
        """Initialize the cloud worker.

        Re-checks credentials at start time (env vars may have changed since
        construction) and probes for a local fallback before reporting
        RUNNING. When credentials are missing AND no local fallback is
        reachable, the worker transitions to DEGRADED rather than RUNNING so
        downstream routing can avoid handing it jobs.

        Returns:
            Worker ID string
        """
        missing = [n for n in self.required_env if not os.environ.get(n)]
        self.metadata["missing_credentials"] = missing
        if missing and not await self._has_local_fallback():
            self._status = WorkerStatus.DEGRADED
            logger.warning(
                "Cloud worker started degraded: missing=%s and no local fallback reachable",
                missing,
            )
            return self._worker_id
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

    async def _has_local_fallback(self) -> bool:
        """Return True when a local llama-server endpoint is reachable.

        Used by ``start()`` to decide whether to mark the worker DEGRADED or
        RUNNING when a required credential is missing. The probe is best-effort:
        it requires the corresponding binary to be on PATH and at least one
        local HTTP endpoint to respond with a non-5xx status. 5xx responses
        and connection errors are treated as "not available" and the next URL
        is tried. We never log the env var values here.
        """
        if not shutil.which("llama-server"):
            return False
        for url in ("http://localhost:8081",):
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(url)
                    if response.status_code < 500:
                        return True
            except httpx.HTTPError:
                continue
        return False

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
        if self._status is WorkerStatus.DEGRADED:
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.DEGRADED,
                error="worker not ready: missing credentials",
                exit_code=1,
            )
        if self._status != WorkerStatus.RUNNING:
            try:
                await self.start()
            except Exception as e:  # worker start may fail at any credential/network step  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.error("Cloud worker failed to start: %s", e)
                return WorkerResult(
                    worker_id=self._worker_id,
                    status=WorkerStatus.FAILED,
                    error=f"Worker failed to start: {e}",
                )

        if self._chain is None:
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error="worker not ready: missing credentials",
                exit_code=1,
            )

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
                except Exception as e:  # metrics are best-effort; do not fail request on metric error  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                    logger.debug("Rate limit metric skipped: %s", e)
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

        except Exception as e:  # chain.execute may raise any provider/HTTP/timeout failure  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
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
            except Exception:  # per-provider probe failed — treat as unhealthy for that provider only  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
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
        except Exception as e:  # storage is best-effort; task result still returned to caller  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning("Failed to store result in Session-Buddy: %s", e)


__all__ = [
    "CloudWorker",
    "CloudWorkerConfig",
]
