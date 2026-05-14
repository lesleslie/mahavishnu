"""Shared task routing logic for workers.

Extracts task classification and model selection from OllamaWorker
so that both OllamaWorker and CloudWorker can share the same routing.

Task routing works in two layers:
1. classify_task() - regex-based prompt classification into TaskCategory
2. Model routing - maps TaskCategory to the best model for the provider

Each provider (Ollama, MiniMax, etc.) has its own model routing config.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Sliding-window rate limit for a single key (model or user).

    Scope: single-process, advisory-only. Not consistent across pool replicas.
    """

    limit: int
    window_seconds: float = 60.0


@dataclass
class _SlidingWindow:
    """Internal per-key state for a sliding window rate limiter."""

    timestamps: deque[float] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RateLimiter:
    """Async sliding-window rate limiter keyed by (model, user).

    Single-process, advisory-only — not consistent across pool replicas.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._config = config
        self._windows: dict[str, _SlidingWindow] = {}

    def _window_for(self, key: str) -> _SlidingWindow:
        if key not in self._windows:
            self._windows[key] = _SlidingWindow()
        return self._windows[key]

    async def check_and_record(self, model: str, user: str | None = None) -> bool:
        """Return True if the request is allowed; False if rate-limited.

        Also records the request timestamp on success.
        """
        key = f"{model}:{user or '*'}"
        window = self._window_for(key)
        now = time.monotonic()
        cutoff = now - self._config.window_seconds

        async with window.lock:
            while window.timestamps and window.timestamps[0] < cutoff:
                window.timestamps.popleft()
            if len(window.timestamps) >= self._config.limit:
                return False
            window.timestamps.append(now)
            return True


# Module-level rate limiter; None until configured via configure_rate_limiter().
_rate_limiter: RateLimiter | None = None


def configure_rate_limiter(config: RateLimitConfig) -> None:
    """Install a module-level rate limiter (replaces any existing instance)."""
    global _rate_limiter
    _rate_limiter = RateLimiter(config)


def get_rate_limiter() -> RateLimiter | None:
    """Return the module-level rate limiter, or None if not configured."""
    return _rate_limiter


class TaskCategory(StrEnum):
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
    SWARM = "swarm"
    QUICK = "quick"
    ML_INFERENCE = "ml_inference"  # GPU-required ML inference (routes to RunPod)
    AGENT_LOOP = "agent_loop"


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
    TaskCategory.ML_INFERENCE: [
        r"\b(inference|infer|predict|classify|detect)\b",
        r"\b(model|checkpoint|weights)\b.*\b(run|load|serve)\b",
        r"\bml\s*inference\b",
        r"\bgpu\b.*\btask\b",
    ],
    TaskCategory.AGENT_LOOP: [
        r"\b(agent\s*loop|agentic|autonomous\s*workflow)\b",
        r"\b(multi[-\s]?step\s*(agent|workflow|task))\b",
        r"\bdurable\b.*\b(workflow|task|loop)\b",
        r"\bhatchet\b",
        r"\bwait\s*for\s*approval\b",
        r"\bhuman[-\s]in[-\s]the[-\s]loop\b",
    ],
    TaskCategory.SWARM: [
        r"\b(swarm|parallel|batch|bulk|scale)\b",
        r"\bmultiple\s*(tasks|workers|agents)\b",
    ],
    TaskCategory.QUICK: [
        r"\b(quick|fast|simple|brief|short|summarize)\b",
    ],
}


# Default model routing for Ollama (local models)
DEFAULT_OLLAMA_ROUTING: dict[TaskCategory, str] = {
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
    TaskCategory.SWARM: "qwen2.5-coder:7b",
    TaskCategory.QUICK: "qwen2.5-coder:7b",
    TaskCategory.ML_INFERENCE: "llava:7b",
    TaskCategory.AGENT_LOOP: "llama3:8b",
}

# Default model routing for MiniMax cloud provider
DEFAULT_MINIMAX_ROUTING: dict[TaskCategory, str] = {
    TaskCategory.CODE_GENERATION: "MiniMax-M2.7",
    TaskCategory.CODE_REVIEW: "MiniMax-M2.7",
    TaskCategory.DEBUGGING: "MiniMax-M2.7",
    TaskCategory.REFACTORING: "MiniMax-M2.7",
    TaskCategory.DOCUMENTATION: "MiniMax-M2.7",
    TaskCategory.TESTING: "MiniMax-M2.7",
    TaskCategory.REASONING: "MiniMax-M2.7",
    TaskCategory.CREATIVE: "MiniMax-M2.7",
    TaskCategory.ANALYSIS: "MiniMax-M2.7",
    TaskCategory.VISION: "MiniMax-M2.7",
    TaskCategory.EMBEDDING: "MiniMax-M2.7",
    TaskCategory.GENERAL: "MiniMax-M2.7",
    TaskCategory.SWARM: "MiniMax-M2.7-highspeed",
    TaskCategory.QUICK: "MiniMax-M2.7-highspeed",
    TaskCategory.ML_INFERENCE: "MiniMax-M2.7-highspeed",
    TaskCategory.AGENT_LOOP: "MiniMax-M2.7",
}

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
    scores: dict[TaskCategory, int] = dict.fromkeys(TaskCategory, 0)

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
    model_routing: dict[TaskCategory, str],
    default_model: str,
    context: dict[str, Any] | None = None,
) -> tuple[str, TaskCategory]:
    """Select the best model for a given task using provider-specific routing.

    Args:
        prompt: The task prompt
        model_routing: Provider-specific category-to-model mapping
        default_model: Fallback model when no routing match
        context: Optional additional context

    Returns:
        Tuple of (model_name, task_category)
    """
    category = classify_task(prompt, context)
    model = model_routing.get(category, default_model)
    logger.debug("Task classified as %s, using model %s", category.value, model)
    return model, category


__all__ = [
    "RateLimitConfig",
    "RateLimiter",
    "TaskCategory",
    "TASK_PATTERNS",
    "DEFAULT_OLLAMA_ROUTING",
    "DEFAULT_MINIMAX_ROUTING",
    "classify_task",
    "configure_rate_limiter",
    "get_model_for_task",
    "get_rate_limiter",
]
