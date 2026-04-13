"""Shared task routing logic for workers.

Extracts task classification and model selection from OllamaWorker
so that both OllamaWorker and CloudWorker can share the same routing.

Task routing works in two layers:
1. classify_task() - regex-based prompt classification into TaskCategory
2. Model routing - maps TaskCategory to the best model for the provider

Each provider (Ollama, ZAI, etc.) has its own model routing config.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

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
    SWARM = "swarm"
    QUICK = "quick"


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
}

# Default model routing for ZAI cloud provider
DEFAULT_ZAI_ROUTING: dict[TaskCategory, str] = {
    TaskCategory.CODE_GENERATION: "glm-4.7",
    TaskCategory.CODE_REVIEW: "glm-4.7",
    TaskCategory.DEBUGGING: "glm-4.7",
    TaskCategory.REFACTORING: "glm-4.7",
    TaskCategory.DOCUMENTATION: "glm-4.5-air",
    TaskCategory.TESTING: "glm-4.7",
    TaskCategory.REASONING: "glm-5.1",
    TaskCategory.CREATIVE: "glm-4.5",
    TaskCategory.ANALYSIS: "glm-4.5",
    TaskCategory.VISION: "GLM-4.5V",
    TaskCategory.EMBEDDING: "glm-4.5-air",
    TaskCategory.GENERAL: "glm-4.5",
    TaskCategory.SWARM: "glm-4.5-air",
    TaskCategory.QUICK: "glm-4.5-air",
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
    "TaskCategory",
    "TASK_PATTERNS",
    "DEFAULT_OLLAMA_ROUTING",
    "DEFAULT_ZAI_ROUTING",
    "classify_task",
    "get_model_for_task",
]
