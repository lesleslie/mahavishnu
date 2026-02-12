"""Unified task routing and state synchronization.

Intelligent dispatcher that routes tasks to appropriate orchestration adapters
based on task type, capabilities, and system state. Enables Prefect, Agno,
and LlamaIndex to work together in coordinated workflows.

Architecture:
    ┌─────────────────┐
    │  Mahavishnu Core          │
    │  • Task Analyzer            │
    │  • Adapter Registry            │
    │  • State Manager             │
    └─────────────────┘
                   ↓
        [Intelligent Routing]
                   ↓
    ┌─────────────────┐
    │ Statistical Router          │
    │  • Success rates            │
    │  • Latency scores          │
    │  • Pareto frontier           │
    │  • Confidence intervals      │
    └─────────────────┘
                   ↓
        [Multi-Objective Optimization]
                   ↓
    ┌─────────────────┐
    │  Cost Optimizer            │
    │  • Budget tracking           │
    │  • Constraint solving       │
    │  • Strategy selection       │
    └─────────────────┘
                   ↓
        [Adapter Execution]
                   ↓
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any, Awaitable

from mahavishnu.core.adapters.base import (
    AdapterType,
    AdapterCapabilities,
    OrchestratorAdapter,
)
from mahavishnu.core.statistical_router import StatisticalRouter, get_statistical_router
from mahavishnu.core.cost_optimizer import CostOptimizer, get_cost_optimizer
from mahavishnu.core.routing_metrics import RoutingMetrics, get_routing_metrics

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Types of tasks that can be routed."""

    WORKFLOW = "workflow"
    AI_TASK = "ai_task"
    RAG_QUERY = "rag_query"


class RouterMode(str, Enum):
    """Routing modes for adapter selection."""

    STATISTICAL = "statistical"  # Use success rates and latency scores
    COST_OPTIMIZED = "cost_optimized"  # Use cost optimization and budgets
    ADAPTIVE = "adaptive"  # Switch strategies based on performance


class TaskRouter:
    """Intelligent task routing with graceful fallback.

    Features:
    - Task type analysis (workflow, AI task, RAG query)
    - Adapter capability detection
    - Multi-mode routing (statistical, cost-optimized, adaptive)
    - Graceful fallback with retry logic
    - State synchronization across adapters
    - Execution tracking and statistics

    Routing Modes:
    - STATISTICAL: Use StatisticalRouter for data-driven decisions
    - COST_OPTIMIZED: Use CostOptimizer for budget-aware routing
    - ADAPTIVE: Automatically switch strategies based on performance
    """

    def __init__(
        self,
        adapter_registry: "AdapterManager",
        state_manager: "StateManager",
        router_mode: RouterMode = RouterMode.STATISTICAL,
        metrics: RoutingMetrics | None = None,
    ):
        """Initialize TaskRouter.

        Args:
            adapter_registry: Adapter registry for orchestration engines
            state_manager: State manager for cross-adapter synchronization
            router_mode: How to select adapters (statistical, cost-optimized, adaptive)
            metrics: Optional RoutingMetrics instance for Prometheus tracking
        """
        self.adapter_registry = adapter_registry
        self.state_manager = state_manager
        self.router_mode = router_mode

        # Store or initialize routing metrics
        self.metrics = metrics if metrics is not None else get_routing_metrics()

        # Initialize routers based on mode
        self._statistical_router: StatisticalRouter | None = None
        self._cost_optimizer: CostOptimizer | None = None

        logger.info(
            f"TaskRouter initialized: mode={router_mode.value}, "
            f"metrics_enabled={self.metrics is not None}"
        )

    async def analyze_task(
        self,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze task requirements and determine optimal routing strategy.

        Args:
            task: Task specification with task_type, requirements

        Returns:
            Analysis with recommended adapter and mode
        """
        task_type = task.get("task_type", "unknown")

        # Analyze requirements
        needs_deployment = task.get("needs_deployment", False)
        needs_monitoring = task.get("needs_monitoring", False)
        needs_ai_agents = task_type == TaskType.AI_TASK
        needs_rag = task_type == TaskType.RAG_QUERY

        # Select adapter based on task type
        if task_type == TaskType.WORKFLOW:
            recommended_adapter = AdapterType.PREFECT
        elif task_type == TaskType.AI_TASK:
            recommended_adapter = AdapterType.AGNO
        elif task_type == TaskType.RAG_QUERY:
            recommended_adapter = AdapterType.LLAMAINDEX
        else:
            recommended_adapter = AdapterType.PREFECT  # Default

        # Get adapter health
        adapter_health = await self._get_adapter_health(recommended_adapter)

        return {
            "task_type": task_type,
            "recommended_adapter": recommended_adapter,
            "adapter_health": adapter_health,
            "routing_mode": self.router_mode.value,
            "analysis": f"Task requires {'deployment' if needs_deployment else 'standard'} processing",
        }

    async def route(
        self,
        task: dict[str, Any],
        preference_order: list[AdapterType] | None = None,
    ) -> dict[str, Any]:
        """Route task to optimal adapter with metrics tracking.

        Args:
            task: Task specification
            preference_order: Optional adapter preference order (overrides automatic selection)

        Returns:
            Routing decision with adapter selection
        """
        task_type_str = task.get("task_type", "unknown")

        # Use provided preference order or determine automatically
        if preference_order is None:
            analysis = await self.analyze_task(task)

            # Select first available adapter from preference order
            for adapter in preference_order or [analysis["recommended_adapter"]]:
                adapter = self.adapter_registry.adapters.get(adapter)
                if adapter and await adapter.is_available():
                    selected_adapter = adapter
                    break

            if not selected_adapter:
                return {
                    "success": False,
                    "error": f"No adapter available for task type {task_type_str}",
                    "task_type": task_type_str,
                }

        # Record routing decision to Prometheus
        self.metrics.record_routing_decision(
            adapter=selected_adapter,
            task_type=TaskType(task_type_str),
            preference_order=1,
        )

        logger.info(
            f"Routed {task_type_str} to {selected_adapter.value} "
            f"(mode: {self.router_mode.value})"
        )

        return {
            "success": True,
            "adapter": selected_adapter.value,
            "task_type": task_type_str,
            "routing_mode": self.router_mode.value,
        }

    async def execute_with_fallback(
        self,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute task with graceful fallback across adapters.

        Args:
            task: Task specification to execute

        Returns:
            Execution result with fallback chain
        """
        task_type_str = task.get("task_type", "unknown")
        prompt = task.get("prompt", "")
        repos = task.get("repos", [])

        # Get routing decision
        routing = await self.route(task)

        if not routing["success"]:
            return routing

        selected_adapter = AdapterType(routing["adapter"])
        adapter = self.adapter_registry.adapters.get(selected_adapter)

        if not adapter:
            return {
                "success": False,
                "error": f"Adapter {selected_adapter} not available",
                "task_type": task_type_str,
            }

        # Prepare task execution
        execution_context = {
            "task_type": task_type_str,
            "prompt": prompt,
            "repos": repos,
        }

        # Try adapter with retries
        max_retries = 3
        retry_delay = 1.0  # seconds
        total_attempts = 0
        fallback_chain = []

        for attempt in range(1, max_retries + 1):
            total_attempts += 1

            try:
                # Execute via adapter
                if hasattr(adapter, "execute"):
                    result = await adapter.execute(
                        task=execution_context,
                    repos=repos,
                    )

                    # Check if execution succeeded
                    if result.get("success", False):
                        # Record successful execution
                        self.metrics.record_adapter_execution(
                            adapter=selected_adapter,
                            success=True,
                            latency_ms=result.get("latency_ms", 0),
                        )
                        logger.info(
                            f"Task succeeded on {selected_adapter.value} "
                            f"(attempt {attempt}/{max_retries})"
                        )

                        return result

            except Exception as e:
                logger.warning(f"Execution attempt {attempt}/{max_retries} failed: {e}")

                # Fallback to next adapter
                if attempt < max_retries:
                    # Find next adapter to try
                    next_adapter_idx = preference_order.index(selected_adapter) + 1 if preference_order else None

                    if next_adapter_idx < len(preference_order or [AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX]):
                        next_adapter = (preference_order or [AdapterType.PREFECT, AdapterType.AGNO, AdapterType.LLAMAINDEX])[next_adapter_idx]
                        next_adapter_type = AdapterType(next_adapter)
                        next_adapter = self.adapter_registry.adapters.get(next_adapter_type)

                        if next_adapter:
                            logger.info(f"Falling back from {selected_adapter.value} to {next_adapter_type.value}")
                            fallback_chain.append(selected_adapter)
                            selected_adapter = next_adapter_type

                            # Record fallback event
                            self.metrics.record_fallback(
                                original_adapter=selected_adapter,
                                fallback_adapter=next_adapter_type,
                            )

                            # Reset retry delay for next adapter
                            retry_delay = 0.0

                            # Try next adapter immediately
                            break

                    # Exponential backoff for retries
                    await asyncio.sleep(retry_delay)
                    retry_delay = retry_delay * 2

        # All adapters failed
        if not result.get("success", False):
            logger.error(f"All {max_retries} attempts failed for task type {task_type_str}")
            return {
                "success": False,
                "error": "All adapters failed",
                "adapter": None,
                "task_type": task_type_str,
                "fallback_chain": fallback_chain,
                "total_attempts": total_attempts,
            }

    async def get_adapter_statistics(self) -> dict[str, dict[str, Any]]:
        """Get execution statistics for all adapters.

        Returns:
            Dictionary mapping adapter_type to statistics
        """
        stats = {}
        for adapter_type, adapter in self.adapter_registry.adapters.items():
            if adapter is None:
                continue

            try:
                # Get statistics from adapter if available
                if hasattr(adapter, "get_statistics"):
                    adapter_stats = await adapter.get_statistics()
                    stats[adapter_type.value] = adapter_stats
                else:
                    # Adapter doesn't support statistics
                    stats[adapter_type.value] = {
                        "status": "available_but_no_stats",
                    "message": "Statistics not available",
                    }

            except Exception as e:
                logger.error(f"Failed to get statistics for {adapter_type.value}: {e}")
                stats[adapter_type.value] = {
                    "status": "error",
                    "error": str(e),
                }

        return stats

    async def get_health(self) -> dict[str, Any]:
        """Get health status of routing system.

        Returns:
            Health status with metrics enabled flag
        """
        adapter_health = await self._get_adapter_health()

        return {
            "status": "healthy",
            "routing_mode": self.router_mode.value,
            "metrics_enabled": self.metrics is not None,
            "adapters_configured": len(self.adapter_registry.adapters),
            "adapters_healthy": sum(
                1 for h in adapter_health.values()
                if h.get("status") == "healthy"
            ),
        }


async def _get_adapter_health(self, adapter_type: str) -> dict[str, Any]:
        """Get health status for specific adapter."""
        adapter = self.adapter_registry.adapters.get(AdapterType(adapter_type))

        if not adapter:
            return {
                "status": "not_configured",
                "error": f"Adapter {adapter_type} not registered",
            }

        try:
            # Get adapter health if available
            if hasattr(adapter, "get_health"):
                health = await adapter.get_health()
                return {
                    "adapter_type": adapter_type,
                    **health,
                }
            else:
                return {
                    "adapter_type": adapter_type,
                    "status": "available_but_no_health_check",
                }

        except Exception as e:
            return {
                "adapter_type": adapter_type,
                "status": "error",
                "error": str(e),
            }
