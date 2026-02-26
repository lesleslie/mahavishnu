"""Ollama AI worker for local HTTP API-based task execution.

This worker provides AI task execution through local Ollama models,
offering zero-cost, privacy-preserving AI capabilities without external
API dependencies.

Features:
- HTTP API communication (no CLI required)
- Intelligent model routing based on task type
- Support for all Ollama models
- Configurable generation parameters
- Connection health monitoring
- Session-Buddy integration for result storage
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)


class TaskCategory(str, Enum):
    """Categories for task classification."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REASONING = "reasoning"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    VISION = "vision"
    EMBEDDING = "embedding"
    GENERAL = "general"


# Model routing configuration - maps task categories to optimal models
DEFAULT_MODEL_ROUTING: dict[TaskCategory, str] = {
    TaskCategory.CODE_GENERATION: "qwen2.5-coder:7b",
    TaskCategory.CODE_REVIEW: "qwen2.5-coder:7b",
    TaskCategory.DEBUGGING: "qwen2.5-coder:7b",
    TaskCategory.REFACTORING: "qwen2.5-coder:7b",
    TaskCategory.DOCUMENTATION: "qwen2.5-coder:7b",
    TaskCategory.TESTING: "qwen2.5-coder:7b",
    TaskCategory.REASONING: "llama3:8b",
    TaskCategory.CREATIVE: "llava:7b",
    TaskCategory.ANALYSIS: "qwen2.5-coder:7b",
    TaskCategory.VISION: "llava:7b",
    TaskCategory.EMBEDDING: "nomic-embed-text",
    TaskCategory.GENERAL: "qwen2.5-coder:7b",
}

# Task classification patterns - keywords and patterns for each category
TASK_PATTERNS: dict[TaskCategory, list[str]] = {
    TaskCategory.CODE_GENERATION: [
        r"\b(write|create|implement|build|generate|code|function|class|module)\b",
        r"\b(add|new|feature|component)\b.*\b(code|function|class)\b",
        r"\bprogram\b",
        r"\bapi\b.*\bendpoint\b",
        r"\bscript\b",
    ],
    TaskCategory.CODE_REVIEW: [
        r"\b(review|check|audit|inspect|examine)\b.*\b(code|implementation)\b",
        r"\bcode\s*review\b",
        r"\bpull\s*request\b",
        r"\bpr\b.*\breview\b",
    ],
    TaskCategory.DEBUGGING: [
        r"\b(debug|fix|solve|resolve|troubleshoot|diagnose)\b",
        r"\b(error|bug|issue|problem|exception|crash)\b",
        r"\bnot\s*working\b",
        r"\bfailing\b",
        r"\btraceback\b",
        r"\bstack\s*trace\b",
    ],
    TaskCategory.REFACTORING: [
        r"\b(refactor|restructure|reorganize|clean\s*up|improve)\b",
        r"\boptimize\b.*\b(code|performance)\b",
        r"\bsimplify\b",
        r"\bremove\s*duplicate\b",
    ],
    TaskCategory.DOCUMENTATION: [
        r"\b(document|docs|readme|comment|explain|describe)\b",
        r"\bdocstring\b",
        r"\btype\s*hint\b",
        r"\bannotation\b",
        r"\buser\s*guide\b",
        r"\bapi\s*documentation\b",
    ],
    TaskCategory.TESTING: [
        r"\b(test|spec|unit\s*test|integration\s*test|pytest|unittest)\b",
        r"\bcoverage\b",
        r"\bmock\b",
        r"\bfixture\b",
        r"\bassert\b",
    ],
    TaskCategory.REASONING: [
        r"\b(why|explain|reason|compare|contrast|analyze)\b",
        r"\bhow\s*does\b",
        r"\bwhat\s*is\s*the\s*difference\b",
        r"\bpros\s*and\s*cons\b",
        r"\btrade\s*off\b",
        r"\barchitecture\b.*\bdecision\b",
    ],
    TaskCategory.CREATIVE: [
        r"\b(creative|brainstorm|design|imagine|suggest|ideate)\b",
        r"\bidea\b",
        r"\bnovel\b",
        r"\binnovative\b",
        r"\bprototype\b",
    ],
    TaskCategory.ANALYSIS: [
        r"\b(analyze|assess|evaluate|examine|investigate)\b",
        r"\bmetrics?\b",
        r"\bstatistics?\b",
        r"\bperformance\b.*\banalysis\b",
        r"\bdata\b.*\banalysis\b",
    ],
    TaskCategory.VISION: [
        r"\b(image|picture|photo|screenshot|visual|see|look)\b",
        r"\bdescribe\b.*\bimage\b",
        r"\bocr\b",
        r"\bwhat\b.*\bthis\b.*\bimage\b",
    ],
    TaskCategory.EMBEDDING: [
        r"\b(embed|embedding|vector|similarity)\b",
        r"\bsemantic\s*search\b",
        r"\bvectorize\b",
    ],
}


@dataclass
class OllamaConfig:
    """Configuration for Ollama worker.

    Attributes:
        base_url: Ollama API endpoint
        model: Default model identifier to use (overridden by intelligent routing)
        timeout: Request timeout in seconds
        temperature: Sampling temperature (0.0-2.0)
        num_ctx: Context window size
        num_predict: Maximum tokens to generate
        top_p: Nucleus sampling parameter
        top_k: Top-k sampling parameter
        keep_alive: How long to keep model loaded
        intelligent_routing: Enable automatic model selection based on task type
        model_routing: Custom model routing configuration (category -> model)
    """

    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    timeout: int = 300
    temperature: float = 0.7
    num_ctx: int = 4096
    num_predict: int = 2048
    top_p: float = 0.9
    top_k: int = 40
    keep_alive: str = "5m"
    intelligent_routing: bool = True
    model_routing: dict[TaskCategory, str] | None = None

    def get_model_for_category(self, category: TaskCategory) -> str:
        """Get the appropriate model for a task category.

        Args:
            category: The classified task category

        Returns:
            Model identifier to use
        """
        routing = self.model_routing or DEFAULT_MODEL_ROUTING
        return routing.get(category, self.model)


def classify_task(prompt: str, context: dict[str, Any] | None = None) -> TaskCategory:
    """Classify a task based on prompt content.

    Analyzes the prompt text for keywords and patterns to determine
    the most appropriate task category for model routing.

    Args:
        prompt: The task prompt to classify
        context: Optional additional context (file types, repo info, etc.)

    Returns:
        The most likely TaskCategory for this task
    """
    if not prompt:
        return TaskCategory.GENERAL

    prompt_lower = prompt.lower()

    # Check for vision tasks first (usually have image context)
    if context:
        if context.get("has_image") or context.get("file_type", "").startswith("image/"):
            return TaskCategory.VISION
        if context.get("embedding") or context.get("vector"):
            return TaskCategory.EMBEDDING

    # Score each category based on pattern matches
    scores: dict[TaskCategory, int] = {cat: 0 for cat in TaskCategory}

    for category, patterns in TASK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, prompt_lower):
                scores[category] += 1

    # Find the category with the highest score
    max_score = max(scores.values())
    if max_score == 0:
        return TaskCategory.GENERAL

    # Return the category with the highest score
    for category, score in scores.items():
        if score == max_score:
            return category

    return TaskCategory.GENERAL


def get_model_for_task(
    prompt: str,
    available_models: list[str],
    config: OllamaConfig,
    context: dict[str, Any] | None = None,
) -> tuple[str, TaskCategory]:
    """Select the best model for a given task.

    Args:
        prompt: The task prompt
        available_models: List of available model names
        config: Worker configuration with routing preferences
        context: Optional additional context

    Returns:
        Tuple of (model_name, task_category)
    """
    # Classify the task
    category = classify_task(prompt, context)

    # Get the preferred model for this category
    preferred_model = config.get_model_for_category(category)

    # Check if preferred model is available
    if preferred_model in available_models:
        logger.debug(f"Task classified as {category.value}, using {preferred_model}")
        return preferred_model, category

    # Fallback: find a model that matches the category's purpose
    model_families = {
        "coder": [
            TaskCategory.CODE_GENERATION,
            TaskCategory.CODE_REVIEW,
            TaskCategory.DEBUGGING,
            TaskCategory.REFACTORING,
            TaskCategory.TESTING,
        ],
        "llama": [TaskCategory.REASONING, TaskCategory.CREATIVE],
        "llava": [TaskCategory.VISION, TaskCategory.CREATIVE],
        "embed": [TaskCategory.EMBEDDING],
    }

    for model in available_models:
        model_lower = model.lower()
        for family, categories in model_families.items():
            if family in model_lower and category in categories:
                logger.debug(f"Task classified as {category.value}, using fallback {model}")
                return model, category

    # Final fallback: use config default or first available
    fallback = (
        config.model
        if config.model in available_models
        else (available_models[0] if available_models else config.model)
    )
    logger.debug(f"Task classified as {category.value}, using final fallback {fallback}")
    return fallback, category


class OllamaWorker(BaseWorker):
    """Worker that executes tasks via Ollama HTTP API.

    This worker type provides AI task execution through local Ollama models,
    offering zero-cost, privacy-preserving AI capabilities without external
    API dependencies.

    Args:
        config: Ollama configuration with model and API settings
        worker_id: Unique identifier for this worker instance
        session_buddy_client: Optional Session-Buddy client for result storage
    """

    def __init__(
        self,
        config: OllamaConfig | None = None,
        worker_id: str | None = None,
        session_buddy_client: Any = None,
    ) -> None:
        super().__init__(worker_type="terminal-ollama")
        self.config = config or OllamaConfig()
        self._worker_id = worker_id or f"ollama-{int(time.time())}"
        self.session_buddy_client = session_buddy_client
        self._client: httpx.AsyncClient | None = None
        self._start_time: float | None = None

    async def start(self) -> str:
        """Initialize the Ollama worker.

        Verifies Ollama server availability and model presence.

        Returns:
            Worker ID string

        Raises:
            RuntimeError: If Ollama server is not available
        """
        self._status = WorkerStatus.STARTING
        self._start_time = time.time()

        # Initialize HTTP client
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout),
        )

        # Verify Ollama is running
        if not await self._is_available():
            await self._cleanup_client()
            self._status = WorkerStatus.FAILED
            raise RuntimeError(
                f"Ollama server not available at {self.config.base_url}. Start with: ollama serve"
            )

        # Verify model exists
        models = await self._list_models()
        model_names = [m.get("name", "") for m in models]

        if self.config.model not in model_names:
            logger.warning(
                f"Model {self.config.model} not found. Available: {', '.join(model_names[:5])}..."
            )
            # Attempt to pull model
            try:
                logger.info(f"Attempting to pull model {self.config.model}...")
                await self._pull_model(self.config.model)
            except Exception as e:
                await self._cleanup_client()
                self._status = WorkerStatus.FAILED
                raise RuntimeError(
                    f"Model {self.config.model} not available and pull failed: {e}"
                ) from e

        self._status = WorkerStatus.RUNNING
        logger.info(f"Started Ollama worker: {self._worker_id} (model: {self.config.model})")
        return self._worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task using Ollama.

        Args:
            task: Task specification with keys:
                - prompt: Task prompt to send to AI (required)
                - timeout: Execution timeout in seconds (default: config.timeout)
                - model: Override model for this task (skips intelligent routing)
                - system: Optional system prompt
                - temperature: Override temperature for this task
                - raw: If True, use generate API; otherwise chat API
                - context: Optional context dict for intelligent routing
                    - has_image: bool - task involves image processing
                    - file_type: str - MIME type of input file
                    - embedding: bool - task needs embedding model

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
        use_raw = task.get("raw", False)
        task_context = task.get("context")

        # Intelligent model selection (unless explicitly specified)
        explicit_model = task.get("model")
        if explicit_model:
            model = explicit_model
            task_category = TaskCategory.GENERAL
            logger.info(f"Using explicitly specified model: {model}")
        elif self.config.intelligent_routing:
            # Get available models for intelligent routing
            available_models = [m.get("name", "") for m in await self._list_models()]
            model, task_category = get_model_for_task(
                prompt=prompt,
                available_models=available_models,
                config=self.config,
                context=task_context,
            )
            logger.info(f"Intelligent routing: {task_category.value} -> {model}")
        else:
            model = self.config.model
            task_category = TaskCategory.GENERAL

        start_time = time.time()

        try:
            # Build request based on API type
            if use_raw:
                # Use generate API for raw completion
                response = await asyncio.wait_for(
                    self._generate(prompt=prompt, model=model, temperature=temperature),
                    timeout=timeout,
                )
            else:
                # Use chat API with system prompt support
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                response = await asyncio.wait_for(
                    self._chat(messages=messages, model=model, temperature=temperature),
                    timeout=timeout,
                )

            output = response.get("response", "")
            duration = time.time() - start_time

            result = WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                exit_code=0,
                duration_seconds=duration,
                metadata={
                    "model": model,
                    "task_category": task_category.value,
                    "tokens_generated": response.get("eval_count"),
                    "total_duration_ms": response.get("total_duration"),
                    "temperature": temperature,
                    "api_type": "generate" if use_raw else "chat",
                    "intelligent_routing": self.config.intelligent_routing and not explicit_model,
                },
            )

            # Store in Session-Buddy if available
            if self.session_buddy_client:
                await self._store_result_in_session_buddy(result, task)

            return result

        except asyncio.TimeoutError:
            duration = time.time() - start_time
            logger.warning(f"Ollama task timed out after {duration}s")
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.TIMEOUT,
                error=f"Task timed out after {timeout}s",
                duration_seconds=duration,
                metadata={"timeout": timeout},
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Ollama task failed: {e}")
            return WorkerResult(
                worker_id=self._worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                duration_seconds=duration,
            )

    async def stop(self) -> None:
        """Stop the worker by closing HTTP client."""
        await self._cleanup_client()
        self._status = WorkerStatus.COMPLETED
        logger.info(f"Stopped Ollama worker: {self._worker_id}")

    async def status(self) -> WorkerStatus:
        """Get current worker status.

        Returns:
            Current WorkerStatus value
        """
        if self._client and self._status == WorkerStatus.RUNNING:
            # Verify connection is still alive
            if not await self._is_available():
                self._status = WorkerStatus.FAILED
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Get worker progress information.

        Returns:
            Dictionary with progress details
        """
        duration = time.time() - self._start_time if self._start_time else 0

        progress = {
            "status": self._status.value,
            "worker_id": self._worker_id,
            "worker_type": self.worker_type,
            "model": self.config.model,
            "duration_seconds": duration,
            "base_url": self.config.base_url,
        }

        # Add model availability if client is active
        if self._client:
            try:
                available = await self._is_available()
                progress["ollama_available"] = available
            except Exception:
                progress["ollama_available"] = False

        return progress

    async def health_check(self) -> dict[str, Any]:
        """Check worker health and availability.

        Returns:
            Dictionary with health status
        """
        try:
            current_status = await self.status()
            ollama_available = False
            model_available = False

            if self._client:
                ollama_available = await self._is_available()
                if ollama_available:
                    models = await self._list_models()
                    model_available = any(m.get("name") == self.config.model for m in models)

            return {
                "healthy": current_status == WorkerStatus.RUNNING and ollama_available,
                "status": current_status.value,
                "worker_type": self.worker_type,
                "details": {
                    "ollama_server": ollama_available,
                    "model_available": model_available,
                    "model": self.config.model,
                    "base_url": self.config.base_url,
                },
            }
        except Exception as e:
            return {
                "healthy": False,
                "status": WorkerStatus.FAILED.value,
                "worker_type": self.worker_type,
                "details": {"error": str(e)},
            }

    # Private helper methods

    async def _is_available(self) -> bool:
        """Check if Ollama server is running."""
        if not self._client:
            return False
        try:
            response = await self._client.get("/", timeout=5.0)
            return response.status_code == 200 or "Ollama is running" in response.text
        except Exception as e:
            logger.debug(f"Ollama availability check failed: {e}")
            return False

    async def _list_models(self) -> list[dict[str, Any]]:
        """List available models from Ollama server."""
        if not self._client:
            return []
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        data = response.json()
        return data.get("models", [])

    async def _pull_model(self, model_name: str) -> bool:
        """Pull a model from Ollama registry."""
        if not self._client:
            return False
        response = await self._client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
            timeout=600.0,
        )
        response.raise_for_status()
        return response.json().get("status") == "success"

    async def _generate(
        self,
        prompt: str,
        model: str,
        temperature: float,
    ) -> dict[str, Any]:
        """Generate completion using Ollama generate API."""
        if not self._client:
            raise RuntimeError("Client not initialized")

        response = await self._client.post(
            "/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": self.config.num_ctx,
                    "num_predict": self.config.num_predict,
                    "top_p": self.config.top_p,
                    "top_k": self.config.top_k,
                },
                "keep_alive": self.config.keep_alive,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
    ) -> dict[str, Any]:
        """Generate completion using Ollama chat API."""
        if not self._client:
            raise RuntimeError("Client not initialized")

        response = await self._client.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": self.config.num_ctx,
                    "num_predict": self.config.num_predict,
                    "top_p": self.config.top_p,
                    "top_k": self.config.top_k,
                },
                "keep_alive": self.config.keep_alive,
            },
        )
        response.raise_for_status()
        data = response.json()

        # Chat response has different structure
        return {
            "model": data.get("model", ""),
            "response": data.get("message", {}).get("content", ""),
            "done": True,
            "total_duration": data.get("total_duration"),
            "eval_count": data.get("eval_count"),
            "eval_duration": data.get("eval_duration"),
        }

    async def _cleanup_client(self) -> None:
        """Clean up HTTP client."""
        if self._client:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.error(f"Error closing Ollama client: {e}")
            finally:
                self._client = None

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
                        "type": "ollama_execution",
                        "worker_id": result.worker_id,
                        "worker_type": self.worker_type,
                        "model": self.config.model,
                        "task_prompt": task.get("prompt", "")[:500],
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                        "tokens_generated": result.metadata.get("tokens_generated"),
                    },
                },
            )
            logger.debug(f"Stored result in Session-Buddy: {self._worker_id}")
        except Exception as e:
            logger.warning(f"Failed to store result in Session-Buddy: {e}")


__all__ = [
    "OllamaWorker",
    "OllamaConfig",
    "TaskCategory",
    "classify_task",
    "get_model_for_task",
    "DEFAULT_MODEL_ROUTING",
    "TASK_PATTERNS",
]
