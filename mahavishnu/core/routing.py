"""Unified routing module for intent classification and adapter selection.

This module provides the core routing infrastructure required for
integration implementations, including:

- RoutingStrategy enum for multi-objective optimization
- Intent classification from natural language
- Fallback chain generation for graceful degradation
- Adapter scoring and selection

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-1)

Storage: docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md
Schema: migrations/versions/V202604021300__routing_metrics_schema.sql
"""

from __future__ import annotations

from enum import StrEnum
import logging
import re
from typing import Any

from mahavishnu.core.metrics_schema import AdapterType, TaskType

logger = logging.getLogger(__name__)


class RoutingStrategy(StrEnum):
    """Routing strategies for adapter selection.

    Each strategy optimizes for a different objective:
    - COST: Minimize execution cost (use cheapest adapter)
    - LATENCY: Minimize response time (use fastest adapter)
    - SUCCESS_RATE: Maximize reliability (use most reliable adapter)
    - BALANCED: Multi-objective optimization (Pareto frontier)
    """

    COST = "cost"
    LATENCY = "latency"
    SUCCESS_RATE = "success_rate"
    BALANCED = "balanced"


# Intent classification patterns for natural language task descriptions
INTENT_PATTERNS: dict[TaskType, list[str]] = {
    TaskType.AI_TASK: [
        r"\bai\s*(?:task|agent|assistant|model)",
        r"\bmulti[- ]?agent",
        r"\bllm\b",
        r"\bclaude\b",
        r"\bgpt\b",
        r"\bollama\b",
        r"\bgenerate\b.*\bcode\b",
        r"\banalyze\b.*\bcode\b",
        r"\bwrite\b.*\bfunction\b",
        r"\bsweep\b.*\brepo",
        r"\bsecurity\s*scan\b",
        r"\bcode\s*review\b",
        r"\bimplement\b.*\bfeature\b",
    ],
    TaskType.RAG_QUERY: [
        r"\brag\b",
        r"\bretrieval\b",
        r"\bvector\s*search\b",
        r"\bembed\b",
        r"\bsemantic\s*search\b",
        r"\bquery\b.*\bdocument",
        r"\bsearch\b.*\bknowledge",
        r"\bcontext\b.*\bretrieval",
        r"\bchunk\b.*\bembed",
        r"\bindex\b.*\bdocument",
    ],
    TaskType.WORKFLOW: [
        r"\bworkflow\b",
        r"\bflow\b",
        r"\bpipeline\b",
        r"\bdeploy\b",
        r"\bschedule\b",
        r"\bautomation\b",
        r"\btask\s*chain\b",
        r"\bstep\b.*\bstep\b",
        r"\bmulti[- ]?stage\b",
        r"\borchestrate\b",
        r"\bcoordinate\b.*\brepo",
    ],
    TaskType.BATCH_TASK: [
        r"\bbatch\b",
        r"\bbulk\b",
        r"\bparallel\b",
        r"\bscale\b",
        r"\bmultiple\s*repo",
        r"\bsweep\b.*\bbackend\b",
        r"\bsweep\b.*\bfrontend\b",
        r"\ball\s*repo",
        r"\bmass\s*update\b",
    ],
    TaskType.CRITICAL_TASK: [
        r"\bcritical\b",
        r"\bproduction\b",
        r"\bdeploy\b.*\bprod\b",
        r"\bhotfix\b",
        r"\bemergency\b",
        r"\burgent\b",
        r"\bsecurity\s*patch\b",
    ],
    TaskType.INTERACTIVE_TASK: [
        r"\binteractive\b",
        r"\breal[- ]?time\b",
        r"\bchat\b",
        r"\bstreaming\b",
        r"\bwebsocket\b",
        r"\blive\b",
    ],
}


class TaskRouter:
    """Intent classification and adapter selection router.

    This class provides the routing infrastructure required for
    integration implementations:

    - classify_intent(): Parse natural language into TaskType
    - generate_fallback_chain(): Get ordered adapter list for task
    - get_adapter_scores(): Score adapters for a task type
    - select_adapter(): Choose optimal adapter based on strategy

    Example:
        >>> router = TaskRouter()
        >>> task_type = router.classify_intent("sweep backend repos for security")
        >>> print(task_type)  # TaskType.AI_TASK
        >>> chain = router.generate_fallback_chain(TaskType.AI_TASK)
        >>> print(chain)  # [AdapterType.AGNO, AdapterType.LLAMAINDEX, AdapterType.PREFECT]
    """

    # Default fallback chains for each task type
    DEFAULT_FALLBACK_CHAINS: dict[TaskType, list[AdapterType]] = {
        TaskType.AI_TASK: [
            AdapterType.AGNO,  # Best for multi-agent AI tasks
            AdapterType.LLAMAINDEX,  # Good for RAG + AI
            AdapterType.PREFECT,  # General orchestration fallback
        ],
        TaskType.RAG_QUERY: [
            AdapterType.LLAMAINDEX,  # Primary RAG engine
            AdapterType.AGNO,  # Can use tools for RAG
            AdapterType.PREFECT,  # Orchestration fallback
        ],
        TaskType.WORKFLOW: [
            AdapterType.PREFECT,  # Primary workflow engine
            AdapterType.AGNO,  # Can orchestrate via agents
            AdapterType.LLAMAINDEX,  # Pipeline fallback
        ],
        TaskType.BATCH_TASK: [
            AdapterType.PREFECT,  # Best for batch orchestration
            AdapterType.AGNO,  # Parallel agent execution
            AdapterType.LLAMAINDEX,  # Batch indexing
        ],
        TaskType.CRITICAL_TASK: [
            AdapterType.PREFECT,  # Most reliable for critical tasks
            AdapterType.AGNO,  # Agent-based monitoring
            AdapterType.LLAMAINDEX,  # Documented fallback
        ],
        TaskType.INTERACTIVE_TASK: [
            AdapterType.AGNO,  # Best for interactive chat
            AdapterType.LLAMAINDEX,  # Streaming queries
            AdapterType.PREFECT,  # Real-time workflows
        ],
    }

    def __init__(
        self,
        fallback_chains: dict[TaskType, list[AdapterType]] | None = None,
        default_strategy: RoutingStrategy = RoutingStrategy.BALANCED,
    ):
        """Initialize TaskRouter.

        Args:
            fallback_chains: Override default fallback chains
            default_strategy: Default routing strategy
        """
        self.fallback_chains = fallback_chains or self.DEFAULT_FALLBACK_CHAINS.copy()
        self.default_strategy = default_strategy

        logger.info(
            f"TaskRouter initialized: strategy={default_strategy.value}, "
            f"chains={len(self.fallback_chains)}"
        )

    def classify_intent(self, intent: str) -> TaskType:
        """Classify natural language intent into TaskType.

        Uses pattern matching to determine the most likely task type
        from a natural language description.

        Args:
            intent: Natural language task description

        Returns:
            TaskType enum value

        Example:
            >>> router = TaskRouter()
            >>> router.classify_intent("sweep backend repos for security")
            TaskType.AI_TASK
            >>> router.classify_intent("search documents about APIs")
            TaskType.RAG_QUERY
            >>> router.classify_intent("deploy to production")
            TaskType.WORKFLOW
        """
        if not intent:
            logger.warning("Empty intent provided, defaulting to WORKFLOW")
            return TaskType.WORKFLOW

        intent_lower = intent.lower()

        # Score each task type based on pattern matches
        scores: dict[TaskType, int] = {}

        for task_type, patterns in INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, intent_lower, re.IGNORECASE))
                score += matches

            if score > 0:
                scores[task_type] = score

        # Return highest scoring task type
        if scores:
            best_type = max(scores, key=lambda t: scores[t], default=TaskType.WORKFLOW)
            logger.debug(
                f"Intent classified: '{intent[:50]}...' -> {best_type.value} (scores: {scores})"
            )
            return best_type

        # Default to WORKFLOW for unrecognized intents
        logger.debug(f"Intent defaulted to WORKFLOW: '{intent[:50]}...'")
        return TaskType.WORKFLOW

    def generate_fallback_chain(
        self,
        task_type: TaskType,
        preferred_adapter: AdapterType | None = None,
    ) -> list[AdapterType]:
        """Generate ordered fallback chain for a task type.

        Returns an ordered list of adapters to try, starting with
        the preferred adapter (if specified) or the default for the
        task type.

        Args:
            task_type: Type of task to route
            preferred_adapter: Optional preferred adapter to prioritize

        Returns:
            Ordered list of AdapterType values

        Example:
            >>> router = TaskRouter()
            >>> router.generate_fallback_chain(TaskType.AI_TASK)
            [AdapterType.AGNO, AdapterType.LLAMAINDEX, AdapterType.PREFECT]
            >>> router.generate_fallback_chain(TaskType.AI_TASK, AdapterType.LLAMAINDEX)
            [AdapterType.LLAMAINDEX, AdapterType.AGNO, AdapterType.PREFECT]
        """
        # Get default chain for task type
        default_chain = self.fallback_chains.get(
            task_type,
            [AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX],
        )

        # If no preferred adapter, return default chain
        if preferred_adapter is None:
            logger.debug(
                f"Fallback chain for {task_type.value}: {[a.value for a in default_chain]}"
            )
            return default_chain.copy()

        # Reorder chain to put preferred adapter first
        chain = [preferred_adapter]
        for adapter in default_chain:
            if adapter != preferred_adapter:
                chain.append(adapter)

        logger.debug(
            f"Fallback chain for {task_type.value} (preferred={preferred_adapter.value}): "
            f"{[a.value for a in chain]}"
        )
        return chain

    async def get_adapter_scores(
        self,
        task_type: TaskType,
        context: dict[str, Any] | None = None,
    ) -> dict[AdapterType, float]:
        """Calculate scores for each adapter given a task type.

        Scores are normalized to 0.0-1.0 range, with higher being better.
        This is a simplified implementation - production use would integrate
        with StatisticalRouter for data-driven scoring.

        Args:
            task_type: Type of task to score for
            context: Optional context (budget, latency requirements, etc.)

        Returns:
            Dictionary mapping AdapterType to score (0.0-1.0)

        Example:
            >>> router = TaskRouter()
            >>> scores = await router.get_adapter_scores(TaskType.AI_TASK)
            >>> print(scores)
            {AdapterType.AGNO: 0.9, AdapterType.LLAMAINDEX: 0.7, AdapterType.PREFECT: 0.5}
        """
        # Default scores based on task type specialization
        default_scores: dict[TaskType, dict[AdapterType, float]] = {
            TaskType.AI_TASK: {
                AdapterType.AGNO: 0.9,  # Best for multi-agent
                AdapterType.LLAMAINDEX: 0.7,  # Good for RAG+AI
                AdapterType.PREFECT: 0.5,  # General purpose
            },
            TaskType.RAG_QUERY: {
                AdapterType.LLAMAINDEX: 0.95,  # Primary RAG engine
                AdapterType.AGNO: 0.7,  # Can use tools
                AdapterType.PREFECT: 0.4,  # Orchestration only
            },
            TaskType.WORKFLOW: {
                AdapterType.PREFECT: 0.95,  # Primary workflow
                AdapterType.AGNO: 0.7,  # Agent orchestration
                AdapterType.LLAMAINDEX: 0.5,  # Pipeline
            },
            TaskType.BATCH_TASK: {
                AdapterType.PREFECT: 0.9,  # Best for batch
                AdapterType.AGNO: 0.8,  # Parallel agents
                AdapterType.LLAMAINDEX: 0.6,  # Batch indexing
            },
            TaskType.CRITICAL_TASK: {
                AdapterType.PREFECT: 0.95,  # Most reliable
                AdapterType.AGNO: 0.8,  # Monitored agents
                AdapterType.LLAMAINDEX: 0.7,  # Documented
            },
            TaskType.INTERACTIVE_TASK: {
                AdapterType.AGNO: 0.9,  # Best for chat
                AdapterType.LLAMAINDEX: 0.8,  # Streaming
                AdapterType.PREFECT: 0.6,  # Real-time workflows
            },
        }

        scores = default_scores.get(
            task_type,
            {AdapterType.PREFECT: 0.7, AdapterType.AGNO: 0.6, AdapterType.LLAMAINDEX: 0.5},
        )

        # Apply context-based adjustments
        if context:
            scores = self._apply_context_adjustments(scores, context)

        logger.debug(f"Adapter scores for {task_type.value}: {scores}")
        return scores

    def _apply_context_adjustments(
        self,
        scores: dict[AdapterType, float],
        context: dict[str, Any],
    ) -> dict[AdapterType, float]:
        """Apply context-based score adjustments.

        Args:
            scores: Base scores for each adapter
            context: Context with budget, latency, reliability requirements

        Returns:
            Adjusted scores
        """
        adjusted = scores.copy()

        # Budget constraint: penalize expensive adapters
        max_cost = context.get("max_cost_usd")
        if max_cost is not None and max_cost < 0.10:
            # Tight budget: prefer LlamaIndex (local models)
            adjusted[AdapterType.LLAMAINDEX] *= 1.2
            adjusted[AdapterType.AGNO] *= 0.9  # Often uses paid APIs

        # Latency constraint: penalize slow adapters
        max_latency_ms = context.get("max_latency_ms")
        if max_latency_ms is not None and max_latency_ms < 5000:
            # Need fast response: prefer Prefect (orchestration overhead)
            adjusted[AdapterType.PREFECT] *= 1.1
            adjusted[AdapterType.AGNO] *= 0.95  # Agent reasoning time

        # Reliability constraint: prefer most reliable
        min_success_rate = context.get("min_success_rate")
        if min_success_rate is not None and min_success_rate > 0.95:
            # Critical: prefer Prefect (most tested)
            adjusted[AdapterType.PREFECT] *= 1.15

        # Normalize scores back to 0-1 range
        max_score = max(adjusted.values())
        if max_score > 1.0:
            adjusted = {k: v / max_score for k, v in adjusted.items()}

        return adjusted

    async def select_adapter(
        self,
        task_type: TaskType,
        strategy: RoutingStrategy | None = None,
        context: dict[str, Any] | None = None,
    ) -> AdapterType:
        """Select optimal adapter based on routing strategy.

        Args:
            task_type: Type of task to route
            strategy: Routing strategy (defaults to self.default_strategy)
            context: Optional context for scoring adjustments

        Returns:
            Selected AdapterType

        Example:
            >>> router = TaskRouter()
            >>> adapter = await router.select_adapter(
            ...     TaskType.AI_TASK,
            ...     RoutingStrategy.BALANCED,
            ...     {"max_cost_usd": 1.0}
            ... )
            >>> print(adapter)
            AdapterType.AGNO
        """
        strategy = strategy or self.default_strategy
        scores = await self.get_adapter_scores(task_type, context)

        # Apply strategy-specific adjustments
        if strategy == RoutingStrategy.COST:
            # Already handled in context adjustments
            pass
        elif strategy == RoutingStrategy.LATENCY:
            # Prefer faster adapters
            latency_bonus = {
                AdapterType.PREFECT: 1.15,
                AdapterType.LLAMAINDEX: 1.1,
                AdapterType.AGNO: 1.0,
            }
            scores = {k: v * latency_bonus.get(k, 1.0) for k, v in scores.items()}
        elif strategy == RoutingStrategy.SUCCESS_RATE:
            # Prefer most reliable
            reliability_bonus = {
                AdapterType.PREFECT: 1.2,
                AdapterType.AGNO: 1.1,
                AdapterType.LLAMAINDEX: 1.0,
            }
            scores = {k: v * reliability_bonus.get(k, 1.0) for k, v in scores.items()}
        # BALANCED: use scores as-is

        # Select highest scoring adapter
        if not scores:
            return AdapterType.PREFECT  # safe fallback when no scores available
        selected = max(scores, key=lambda a: scores[a], default=AdapterType.PREFECT)

        logger.info(
            f"Adapter selected: {selected.value} for {task_type.value} "
            f"(strategy={strategy.value}, score={scores[selected]:.2f})"
        )

        return selected  # type: ignore[no-any-return]

    def get_routing_info(
        self,
        task_type: TaskType,
        strategy: RoutingStrategy | None = None,
    ) -> dict[str, Any]:
        """Get complete routing information for a task type.

        Useful for debugging and logging routing decisions.

        Args:
            task_type: Type of task
            strategy: Routing strategy

        Returns:
            Dictionary with fallback chain, default adapter, and strategy
        """
        strategy = strategy or self.default_strategy
        fallback_chain = self.generate_fallback_chain(task_type)

        return {
            "task_type": task_type.value,
            "strategy": strategy.value,
            "fallback_chain": [a.value for a in fallback_chain],
            "primary_adapter": fallback_chain[0].value if fallback_chain else None,
            "total_adapters": len(fallback_chain),
        }


# Singleton instance for global access
_router: TaskRouter | None = None


def get_task_router() -> TaskRouter:
    """Get or create global TaskRouter singleton.

    Returns:
        Global TaskRouter instance
    """
    global _router
    if _router is None:
        _router = TaskRouter()
    return _router


def reset_task_router() -> None:
    """Reset the global TaskRouter singleton.

    Useful for testing and configuration reloads.
    """
    global _router
    _router = None
    logger.info("TaskRouter singleton reset")


__all__ = [
    "RoutingStrategy",
    "TaskRouter",
    "INTENT_PATTERNS",
    "get_task_router",
    "reset_task_router",
]
