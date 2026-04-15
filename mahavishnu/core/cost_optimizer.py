"""Cost-aware routing with multi-objective optimization.

Implements budget tracking, cost aggregation, and Pareto frontier analysis
for adapter selection. Supports task-type-specific strategies and constraint solving.

Design:
- Cost tracking per adapter execution
- Budget management (daily/weekly/monthly, per-task-type)
- Pareto frontier analysis for non-dominated adapters
- Task-type strategies: interactive (latency), batch (cost), critical (success)
- Constraint solver for budgets and SLAs
- Recommendation API with reasoning
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from typing import Any, Awaitable, Callable
from enum import Enum
from decimal import Decimal

import numpy as np

from mahavishnu.core.metrics_collector import (
    ExecutionTracker,
    get_execution_tracker,
)
from mahavishnu.core.metrics_schema import (
    AdapterType,
    TaskType,
    CostTracking,
    ExecutionRecord,
    AdapterStats,
)
from mahavishnu.core.routing_metrics import get_routing_metrics


logger = logging.getLogger(__name__)


# Cost per adapter per second of execution (USD/second)
ADAPTER_COSTS = {
    AdapterType.PREFECT: Decimal("0.0001"),  # $0.0001 per workflow-second
    AdapterType.AGNO: Decimal("0.0002"),  # $0.0002 per agent-second
    AdapterType.LLAMAINDEX: Decimal("0.00005"),  # $0.00005 per query
}


class BudgetType(str, Enum):
    """Budget aggregation types."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    PER_TASK_TYPE = "per_task_type"


class TaskStrategy(str, Enum):
    """Optimization strategies for task types."""

    INTERACTIVE = "interactive"  # Minimize latency (user-facing)
    BATCH = "batch"  # Minimize cost (background jobs)
    CRITICAL = "critical"  # Maximize success (important workflows)


@dataclass
class Budget:
    """Budget configuration."""

    budget_type: BudgetType
    limit_usd: Decimal
    period_days: int | None = None
    task_type: TaskType | None = None
    adapter: AdapterType | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    alert_threshold: float = 0.9  # Alert at 90% of budget

    def __post_init__(self) -> None:
        if self.period_days is not None and self.period_days not in {1, 7, 30, 90, 365}:
            raise ValueError(
                f"Invalid period_days: {self.period_days}. Must be 1, 7, 30, 90, or 365"
            )

        if self.period_days is not None and self.period_start is None and self.period_end is None:
            now = datetime.now(UTC)
            self.period_start = now
            self.period_end = now + timedelta(days=self.period_days)

    def is_active(self, now: datetime | None = None) -> bool:
        """Check if budget is currently active."""
        if now is None:
            now = datetime.now(UTC)

        if self.period_start is None or self.period_end is None:
            return False

        return self.period_start <= now <= self.period_end


@dataclass
class CostAwareChoice:
    """Adapter selection with cost analysis."""

    adapter: AdapterType
    task_type: TaskType
    strategy: TaskStrategy
    cost_usd: Decimal
    success_rate: float
    latency_ms: int
    score: float
    reasoning: str = ""
    pareto_dominated: bool = False  # True if no other adapter is better in all metrics
    constraints_satisfied: bool = True  # True if within budget and SLA
    violated_budgets: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParetoFrontier:
    """Pareto frontier analysis results."""

    task_type: TaskType
    frontier: list[CostAwareChoice]  # Non-dominated options
    dominated: list[AdapterType]  # Dominated (excluded from frontier)
    analysis_timestamp: datetime


class CostOptimizer:
    """Multi-objective optimization for adapter selection.

    Features:
    - Cost tracking and budget enforcement
    - Pareto frontier identification
    - Task-type-specific strategy application
    - Constraint solving (budgets, SLAs)
    - Recommendation generation with reasoning
    """

    def __init__(
        self,
        budgets: list[Budget] | None = None,
        default_strategy: TaskStrategy = TaskStrategy.BATCH,
        max_latency_ms: int = 5000,  # Default SLA: 5 seconds
        min_success_rate: float = 0.8,  # Default SLA: 80%
        metrics: RoutingMetrics | None = None,
    ):
        """Initialize CostOptimizer.

        Args:
            budgets: Optional list of budget configurations
            default_strategy: Default optimization strategy
            max_latency_ms: Maximum acceptable latency (SLA)
            min_success_rate: Minimum acceptable success rate (SLA)
            metrics: Optional RoutingMetrics instance for Prometheus tracking
        """
        self.budgets = budgets or []
        self.default_strategy = default_strategy
        self.max_latency_ms = max_latency_ms
        self.min_success_rate = min_success_rate

        # Store or initialize routing metrics
        self.metrics = metrics if metrics is not None else get_routing_metrics()

        self._cost_tracking: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(Decimal))
        )
        self._frontier_cache: dict[str, ParetoFrontier] = {}
        self._recalc_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"CostOptimizer initialized: strategy={default_strategy.value}, "
            f"max_latency={max_latency_ms}ms, min_success={min_success_rate}, "
            f"metrics_enabled={self.metrics is not None}"
        )

    async def track_execution_cost(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        execution_id: str,
        latency_ms: int,
    ) -> Decimal:
        """Track and calculate execution cost.

        Args:
            adapter: Adapter type
            task_type: Task being executed
            execution_id: ULID identifier
            latency_ms: Execution duration

        Returns:
            Cost in USD
        """
        # Get cost per second for adapter
        cost_per_second = ADAPTER_COSTS.get(adapter, Decimal("0.00001"))

        # Calculate total cost
        duration_seconds = Decimal(latency_ms) / Decimal(1000)
        cost_usd = cost_per_second * duration_seconds

        # Store cost tracking
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        self._cost_tracking[date_key][adapter.value][task_type.value] += cost_usd

        # Record cost in Prometheus metrics
        self.metrics.record_cost(
            adapter=adapter,
            task_type=task_type,
            cost_usd=float(cost_usd),
        )

        logger.debug(
            f"Tracked cost: {adapter.value}/{task_type.value} = ${cost_usd:.6f} ({latency_ms}ms)"
        )

        return cost_usd

    async def get_budget_status(
        self,
        budget: Budget,
    ) -> dict[str, Any]:
        """Get budget utilization status.

        Args:
            budget: Budget configuration

        Returns:
            Status with spent, remaining, percentage
        """
        # Calculate total spent for this budget
        total_spent = Decimal("0")
        now = datetime.now(UTC)

        for date_costs in self._cost_tracking.values():
            for adapter_name, task_costs in date_costs.items():
                if budget.adapter and adapter_name != budget.adapter.value:
                    continue

                if budget.task_type is not None:
                    total_spent += task_costs.get(budget.task_type.value, Decimal("0"))
                else:
                    total_spent += sum(task_costs.values(), Decimal("0"))

        # Check if budget period is active
        active = budget.is_active(now)

        remaining = budget.limit_usd - total_spent if active else Decimal("0")
        percentage = (
            (total_spent / budget.limit_usd) if active and budget.limit_usd > 0 else Decimal("0")
        )

        return {
            "budget_type": budget.budget_type.value,
            "limit_usd": float(budget.limit_usd),
            "spent_usd": float(total_spent),
            "remaining_usd": float(remaining),
            "percentage_used": float(percentage),
            "is_active": active,
            "is_over_budget": active and percentage >= Decimal(str(budget.alert_threshold)),
        }

    async def check_budget_constraints(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        constraints: dict[str, Any] | None = None,
        metrics_tracker: ExecutionTracker | None = None,
    ) -> dict[str, Any]:
        """Check if adapter selection would violate budget constraints.

        Args:
            adapter: Adapter to select
            task_type: Task being executed

        Returns:
            Constraint check results
        """
        constraints_ok = True
        violated_budgets = []
        sla_result: dict[str, Any] | None = None

        for budget in self.budgets:
            # Check if budget applies to this adapter/task type
            if budget.adapter and budget.adapter != adapter:
                continue
            if budget.task_type and budget.task_type != task_type:
                continue

            # Check if budget is active
            if not budget.is_active():
                continue

            status = await self.get_budget_status(budget)

            # Check if over budget
            if status["is_over_budget"]:
                constraints_ok = False
                violated_budgets.append(
                    {
                        "budget_type": budget.budget_type.value,
                        "limit_usd": status["limit_usd"],
                        "spent_usd": status["spent_usd"],
                        "over_by": float(status["remaining_usd"]),
                    }
                )

        if constraints and constraints.get("sla"):
            sla = constraints["sla"]
            max_latency_ms = sla.get("max_latency_ms", self.max_latency_ms)
            min_success_rate = sla.get("min_success_rate", self.min_success_rate)

            tracker = metrics_tracker or get_execution_tracker()
            stats = await tracker.get_adapter_stats(adapter)
            recent = await tracker.get_recent_executions(limit=100)
            adapter_executions = [
                execution
                for execution in recent
                if execution.adapter == adapter and execution.task_type == task_type
            ]

            actual_latency_ms = 0
            if adapter_executions:
                latencies = [execution.latency_ms for execution in adapter_executions if execution.latency_ms]
                if latencies:
                    actual_latency_ms = int(np.mean(latencies))
            else:
                tracked_cost = self._get_tracked_cost(adapter, task_type)
                cost_per_second = ADAPTER_COSTS.get(adapter)
                if tracked_cost > 0 and cost_per_second:
                    actual_latency_ms = int((tracked_cost / cost_per_second) * Decimal("1000"))

            success_rate = stats["success_rate"] if stats is not None else 0.0

            sla_result = {
                "max_latency_ms": max_latency_ms,
                "min_success_rate": min_success_rate,
                "actual_latency_ms": actual_latency_ms,
                "actual_success_rate": success_rate,
                "satisfied": actual_latency_ms <= max_latency_ms and success_rate >= min_success_rate,
            }

            if not sla_result["satisfied"]:
                constraints_ok = False

        return {
            "constraints_satisfied": constraints_ok,
            "violated_budgets": violated_budgets,
            "sla": sla_result,
        }

    def _get_tracked_cost(self, adapter: AdapterType, task_type: TaskType) -> Decimal:
        """Return total tracked cost for an adapter/task pair."""
        total = Decimal("0")
        for date_costs in self._cost_tracking.values():
            adapter_costs = date_costs.get(adapter.value, {})
            total += adapter_costs.get(task_type.value, Decimal("0"))
        return total

    def calculate_pareto_frontier(
        self,
        choices: list[CostAwareChoice],
    ) -> ParetoFrontier:
        """Identify Pareto-optimal adapters (non-dominated).

        Args:
            choices: List of adapter choices with metrics

        Returns:
            ParetoFrontier with optimal adapters
        """
        if not choices:
            return ParetoFrontier(
                task_type=TaskType.WORKFLOW,  # Placeholder
                frontier=[],
                dominated=[],
                analysis_timestamp=datetime.now(UTC),
            )

        frontier = []
        dominated = []

        for choice in choices:
            # Check if any other choice dominates this one
            is_dominated = False

            for other in choices:
                if other.adapter == choice.adapter:
                    continue

                # Choice A dominates B if:
                # - A has higher success rate AND lower cost
                # - OR A has same success, lower cost AND lower latency
                # - OR A has same success+cost, lower latency
                other_better_success = other.success_rate > choice.success_rate
                other_not_worse_cost = other.cost_usd <= choice.cost_usd
                other_not_worse_latency = other.latency_ms <= choice.latency_ms
                other_strictly_better = (
                    other.success_rate > choice.success_rate
                    or other.cost_usd < choice.cost_usd
                    or other.latency_ms < choice.latency_ms
                )

                # Strict dominance: no worse in any dimension and better in at least one.
                if (
                    other_better_success
                    and other_not_worse_cost
                    and other_not_worse_latency
                    and other_strictly_better
                ):
                    is_dominated = True
                    break

            if is_dominated:
                dominated.append(choice.adapter)
            else:
                frontier.append(choice)

        return ParetoFrontier(
            task_type=choices[0].task_type if choices else TaskType.WORKFLOW,
            frontier=frontier,
            dominated=dominated,
            analysis_timestamp=datetime.now(UTC),
        )

    def score_adapter_choice(
        self,
        choice: CostAwareChoice,
        strategy: TaskStrategy,
    ) -> float:
        """Calculate multi-objective score for adapter choice.

        Args:
            choice: Adapter choice with metrics
            strategy: Optimization strategy

        Returns:
            Combined score (0-1 scale)
        """
        if strategy == TaskStrategy.INTERACTIVE:
            # Minimize latency, maximize success (50/50)
            # Normalize: cost inverse (lower is better), latency inverse
            cost_score = max(0.0, 1.0 - float(choice.cost_usd) / 0.01)
            latency_score = max(0.0, 1.0 - (choice.latency_ms / self.max_latency_ms))

            return (
                0.5 * choice.success_rate  # Success
                + 0.25 * cost_score  # Cost matters for interactive
                + 0.25 * latency_score  # Latency matters
            )

        elif strategy == TaskStrategy.BATCH:
            # Minimize cost, maximize success (90/10)
            cost_score = max(0.0, 1.0 - float(choice.cost_usd) / 0.01)
            latency_score = max(0.0, 1.0 - (choice.latency_ms / 10000))  # 10s max

            return (
                0.9 * choice.success_rate  # Success dominates
                + 0.1 * cost_score  # Minor cost consideration
                + 0.0 * latency_score  # Latency doesn't matter for batch
            )

        elif strategy == TaskStrategy.CRITICAL:
            # Maximize success, some latency consideration (80/20)
            cost_score = max(0.0, 1.0 - float(choice.cost_usd) / 0.01)
            latency_score = max(0.0, 1.0 - (choice.latency_ms / self.max_latency_ms))

            return (
                0.8 * choice.success_rate  # Success is primary
                + 0.0 * cost_score  # Cost doesn't matter for critical
                + 0.2 * latency_score  # Latency secondary
            )

        else:
            # Default balanced approach (70/30)
            latency_score = max(0.0, 1.0 - (choice.latency_ms / self.max_latency_ms))
            return 0.7 * choice.success_rate + 0.3 * latency_score

    async def get_optimal_adapter(
        self,
        task_type: TaskType,
        constraints: dict[str, Any] | None = None,
        strategy: TaskStrategy | None = None,
        metrics_tracker: ExecutionTracker | None = None,
    ) -> CostAwareChoice | None:
        """Get optimal adapter with full analysis.

        Args:
            task_type: Task to execute
            constraints: Optional constraint dict (budgets, SLAs)
            strategy: Override optimization strategy
            metrics_tracker: ExecutionTracker for statistics

        Returns:
            Best adapter choice with reasoning
        """
        # Use provided strategy or default
        if strategy is None:
            strategy = self.default_strategy
        else:
            strategy = strategy

        tracker = metrics_tracker or get_execution_tracker()

        # Get adapter statistics
        adapters_data = []
        for adapter in AdapterType:
            stats = await tracker.get_adapter_stats(adapter)
            if stats is None:
                continue

            adapters_data.append(
                {
                    "adapter": adapter,
                    "success_rate": stats["success_rate"],
                    "total_executions": stats["total_executions"],
                }
            )

        if not adapters_data:
            return None

        # Build cost-aware choices
        choices = []
        for adapter_data in adapters_data:
            # Get recent executions for latency/cost
            recent = await tracker.get_recent_executions(limit=100)
            adapter_executions = [
                e
                for e in recent
                if e.adapter == adapter_data["adapter"] and e.task_type == task_type
            ]

            # Calculate average latency
            latencies = [e.latency_ms for e in adapter_executions if e.latency_ms]
            if latencies:
                avg_latency = int(np.mean(latencies))
            else:
                tracked_cost = self._get_tracked_cost(adapter_data["adapter"], task_type)
                cost_per_second = ADAPTER_COSTS.get(adapter_data["adapter"])
                avg_latency = (
                    int((tracked_cost / cost_per_second) * Decimal("1000"))
                    if tracked_cost > 0 and cost_per_second
                    else 0
                )

            # Estimate cost (will be tracked during execution)
            # For now, calculate from latency
            cost_usd = await self.track_execution_cost(
                adapter=adapter_data["adapter"],
                task_type=task_type,
                execution_id="estimate",
                latency_ms=avg_latency,
            )

            # Calculate base score
            base_score = self.score_adapter_choice(
                choice=CostAwareChoice(
                    adapter=adapter_data["adapter"],
                    task_type=task_type,
                    strategy=strategy,
                    cost_usd=cost_usd,
                    success_rate=adapter_data["success_rate"],
                    latency_ms=avg_latency,
                    score=0.0,
                    reasoning="",
                    pareto_dominated=False,
                    constraints_satisfied=True,
                ),
                strategy=strategy,
            )

            choices.append(
                CostAwareChoice(
                    adapter=adapter_data["adapter"],
                    task_type=task_type,
                    strategy=strategy,
                    cost_usd=cost_usd,
                    success_rate=adapter_data["success_rate"],
                    latency_ms=avg_latency,
                    score=base_score,
                    reasoning="",
                    pareto_dominated=False,
                    constraints_satisfied=True,
                )
            )

        # Check budget constraints if provided
        constraint_check = {}
        if constraints:
            for choice in choices:
                check = await self.check_budget_constraints(
                    adapter=choice.adapter,
                    task_type=task_type,
                )
                choice.constraints_satisfied = check["constraints_satisfied"]
                choice.violated_budgets = check["violated_budgets"]

                # Disqualify if over budget
                if not choice.constraints_satisfied:
                    choice.score = 0.0  # Zero score if violates constraints

            constraint_check = {
                "constraints_applied": constraints is not None,
                "budget_violations": sum(1 for c in choices if not c.constraints_satisfied),
            }

        # Apply Pareto frontier analysis
        valid_choices = [c for c in choices if c.constraints_satisfied]
        frontier = self.calculate_pareto_frontier(valid_choices)

        # Select best from frontier
        if not frontier.frontier:
            return None

        # Pick adapter with highest score from frontier
        best = max(frontier.frontier, key=lambda c: c.score)

        # Generate reasoning
        reasoning_parts = []
        reasoning_parts.append(f"Strategy: {strategy.value}")

        if len(frontier.frontier) > 1:
            reasoning_parts.append(f"Pareto frontier: {len(frontier.frontier)} optimal adapters")
        else:
            reasoning_parts.append("Single adapter meets criteria")

        reasoning_parts.append(f"Success rate: {best.success_rate:.1%}")
        reasoning_parts.append(f"Cost: ${best.cost_usd:.6f}")
        reasoning_parts.append(f"Latency: {best.latency_ms}ms")

        if best.violated_budgets:
            reasoning_parts.append(f"⚠️  Over budget: {len(best.violated_budgets)} budget(s)")

        best.reasoning = " | ".join(reasoning_parts)

        # Record routing decision in Prometheus
        self.metrics.record_routing_decision(
            adapter=best.adapter,
            task_type=task_type,
            preference_order=1,
        )

        return best

    async def set_strategy_for_task_type(
        self,
        task_type: TaskType,
        strategy: TaskStrategy,
    ) -> None:
        """Set optimization strategy for a task type.

        Args:
            task_type: Task type
            strategy: Strategy to use
        """
        # TODO: Implement persistent storage
        logger.info(f"Strategy for {task_type.value}: {strategy.value}")

    async def add_budget(
        self,
        budget: Budget | None = None,
        budget_type: BudgetType | None = None,
        limit_usd: float | int | Decimal | None = None,
        task_type: TaskType | None = None,
        adapter: AdapterType | None = None,
        period_days: int | None = None,
    ) -> Budget:
        """Add budget configuration.

        Args:
            budget_type: Type of budget
            limit_usd: Spending limit
            task_type: Optional task type to scope budget
            adapter: Optional adapter to scope budget
            period_days: Duration in days (default 30)

        Returns:
            Created Budget object
        """
        now = datetime.now(UTC)

        if budget is not None:
            budget_to_add = budget
            if budget_to_add.period_start is None or budget_to_add.period_end is None:
                effective_days = (
                    budget_to_add.period_days
                    if budget_to_add.period_days is not None
                    else period_days
                    if period_days is not None
                    else {
                        BudgetType.DAILY: 1,
                        BudgetType.WEEKLY: 7,
                        BudgetType.MONTHLY: 30,
                        BudgetType.PER_TASK_TYPE: 30,
                    }[budget_to_add.budget_type]
                )
                budget_to_add.period_days = effective_days
                budget_to_add.period_start = now
                budget_to_add.period_end = now + timedelta(days=effective_days)
        else:
            if budget_type is None or limit_usd is None:
                raise TypeError("budget or budget_type/limit_usd must be provided")

            effective_days = period_days if period_days is not None else {
                BudgetType.DAILY: 1,
                BudgetType.WEEKLY: 7,
                BudgetType.MONTHLY: 30,
                BudgetType.PER_TASK_TYPE: 30,
            }[budget_type]

            budget_to_add = Budget(
                budget_type=budget_type,
                limit_usd=Decimal(str(limit_usd)),
                period_days=effective_days,
                task_type=task_type,
                adapter=adapter,
                period_start=now,
                period_end=now + timedelta(days=effective_days),
            )

        self.budgets.append(budget_to_add)

        logger.info(f"Added budget: {budget_to_add.budget_type.value} ${budget_to_add.limit_usd:.2f}")

        return budget_to_add

    async def get_all_budgets(self) -> list[Budget]:
        """Get all configured budgets."""
        return self.budgets.copy()

    async def delete_budget(self, budget: Budget) -> bool:
        """Delete a budget configuration."""
        if budget in self.budgets:
            self.budgets.remove(budget)
            logger.info(f"Deleted budget: {budget.budget_type.value}")
            return True
        return False

    async def start(self) -> None:
        """Start cost optimizer."""
        if self._recalc_task is not None:
            logger.warning("CostOptimizer already started")
            return

        self._shutdown_event.clear()
        # Start background budget monitoring task
        self._recalc_task = asyncio.create_task(self._budget_monitoring_loop())
        logger.info("CostOptimizer started")

    async def _budget_monitoring_loop(self) -> None:
        """Background task for budget monitoring and alerts."""
        while not self._shutdown_event.is_set():
            try:
                # Check budgets every minute
                await asyncio.sleep(60)

                # Check for budget violations
                for budget in self.budgets:
                    if budget.is_active():
                        status = await self.get_budget_status(budget)

                        # Alert if over budget
                        if status["percentage_used"] >= budget.alert_threshold * 100:
                            logger.warning(
                                f"Budget alert: {budget.budget_type.value} "
                                f"{status['percentage_used']:.1f}% used"
                            )

            except asyncio.CancelledError:
                logger.info("Budget monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Budget monitoring error: {e}", exc_info=True)
                await asyncio.sleep(300)  # Retry after 5 minutes

    async def stop(self) -> None:
        """Stop cost optimizer."""
        logger.info("Stopping CostOptimizer...")

        if self._recalc_task and not self._recalc_task.done():
            self._recalc_task.cancel()
            try:
                await self._recalc_task
            except asyncio.CancelledError:
                pass

        self._shutdown_event.set()
        logger.info("CostOptimizer stopped")

    async def get_health(self) -> dict[str, Any]:
        """Get health status."""
        return {
            "status": "healthy",
            "budgets_configured": len(self.budgets),
            "default_strategy": self.default_strategy.value,
            "sla_max_latency_ms": self.max_latency_ms,
            "sla_min_success_rate": self.min_success_rate,
            "metrics_enabled": self.metrics is not None,
        }


# Singleton instance
_optimizer: CostOptimizer | None = None


def get_cost_optimizer() -> CostOptimizer:
    """Get or create global CostOptimizer singleton."""
    global _optimizer
    if _optimizer is None:
        _optimizer = CostOptimizer()
    return _optimizer


async def initialize_cost_optimizer(
    budgets: list[Budget] | None = None,
    default_strategy: TaskStrategy = TaskStrategy.BATCH,
    max_latency_ms: int = 5000,
    min_success_rate: float = 0.8,
    metrics: RoutingMetrics | None = None,
) -> CostOptimizer:
    """Initialize and start global cost optimizer.

    Args:
        budgets: Optional list of budgets
        default_strategy: Default optimization strategy
        max_latency_ms: SLA maximum latency
        min_success_rate: SLA minimum success rate
        metrics: Optional RoutingMetrics instance for Prometheus tracking

    Returns:
        Started CostOptimizer instance
    """
    global _optimizer

    if _optimizer is None:
        _optimizer = CostOptimizer(
            budgets=budgets,
            default_strategy=default_strategy,
            max_latency_ms=max_latency_ms,
            min_success_rate=min_success_rate,
            metrics=metrics,
        )

    await _optimizer.start()
    return _optimizer


__all__ = [
    "ADAPTER_COSTS",
    "BudgetType",
    "TaskStrategy",
    "Budget",
    "CostAwareChoice",
    "ParetoFrontier",
    "CostOptimizer",
    "get_cost_optimizer",
    "initialize_cost_optimizer",
]
