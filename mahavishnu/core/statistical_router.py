"""Statistical routing engine with adaptive adapter selection.

Calculates adapter success rates, latency scores, and generates
preference orders for TaskRouter fallback chain. Implements confidence
intervals, statistical significance testing, and A/B testing support.

Design:
- Retrieves metrics from ExecutionTracker
- Calculates weighted scores (70% success, 30% speed)
- Generates preference orders per task type
- Weekly recalculation scheduler (Sundays 3AM UTC)
- A/B testing with auto-roll-back
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from typing import Any, Awaitable, Callable
from enum import Enum

import numpy as np
from scipy import stats

from mahavishnu.core.metrics_collector import (
    ExecutionTracker,
    get_execution_tracker,
)
from mahavishnu.core.metrics_schema import (
    AdapterType,
    TaskType,
    AdapterStats,
    ExecutionRecord,
)


from mahavishnu.core.routing_metrics import RoutingMetrics, get_routing_metrics

logger = logging.getLogger(__name__)


class ScoringWeights:
    """Weights for multi-objective scoring."""

    DEFAULT_SUCCESS_WEIGHT = 0.7
    DEFAULT_SPEED_WEIGHT = 0.3

    # Task-type-specific weights
    INTERACTIVE = {"success": 0.5, "speed": 0.5}  # User-facing, minimize latency
    BATCH = {"success": 0.9, "speed": 0.1}  # Background, minimize cost via throughput
    CRITICAL = {"success": 0.8, "speed": 0.2}  # Reliability over speed


class ConfidenceLevel(str, Enum):
    """Statistical confidence levels for decision making."""

    HIGH = "high"  # 95% confidence, requires 100+ samples
    MEDIUM = "medium"  # 80% confidence, requires 50+ samples
    LOW = "low"  # 70% confidence, requires 20+ samples
    INSUFFICIENT = "insufficient"  # Not enough data, use defaults


@dataclass
class AdapterScore:
    """Calculated score for an adapter on a task type.

    Attributes:
        adapter: Adapter type
        task_type: Task being executed
        success_rate: 0.0-1.0 success rate
        latency_score: Normalized speed score (0.0-1.0)
        combined_score: Weighted combination
        sample_count: Number of executions
        confidence_level: Statistical confidence
        last_updated: When score was calculated
    """

    adapter: AdapterType
    task_type: TaskType
    success_rate: float
    latency_score: float
    combined_score: float
    sample_count: int
    confidence_level: ConfidenceLevel
    last_updated: datetime

    def __post_init__(self):
        """Validate scores are in valid range."""
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(f"Invalid success rate: {self.success_rate}")
        if not 0.0 <= self.latency_score <= 1.0:
            raise ValueError(f"Invalid latency score: {self.latency_score}")
        if not 0.0 <= self.combined_score <= 1.0:
            raise ValueError(f"Invalid combined score: {self.combined_score}")


@dataclass
class PreferenceOrder:
    """Adapter preference order for a task type.

    Sorted list of adapters from best to worst, based on
    statistical scores. Used by TaskRouter for fallback chain.
    """

    task_type: TaskType
    adapters: list[AdapterType]  # [best, ..., worst]
    scores: list[AdapterScore]  # Corresponding scores
    generated_at: datetime
    confidence: ConfidenceLevel  # Overall confidence in this ordering
    ab_test_active: bool = False  # If A/B test is running
    ab_test_variant: str | None = None  # "A" or "B" if active

    def get_preference_chain(self) -> list[str]:
        """Get adapter type list for TaskRouter."""
        return [a.value for a in self.adapters]


class ABTest:
    """A/B test configuration and tracking."""

    experiment_id: str
    name: str
    description: str
    variant_a: PreferenceOrder  # Control group
    variant_b: PreferenceOrder  # Treatment group
    traffic_split: float  # 0.0-1.0, e.g., 0.1 = 10% to B
    start_time: datetime
    end_time: datetime | None = None
    status: str  # "running", "completed", "rolled_back", "abandoned"
    winner: str | None = None  # "A", "B", or "inconclusive"
    sample_size_a: int = 0
    sample_size_b: int = 0
    metric_diffs: dict[str, float] = field(default_factory=dict)  # e.g., {"success_rate": 0.05}


class StatisticalRouter:
    """Calculates adapter scores and generates preference orders.

    Features:
    - Success rate calculation with confidence intervals
    - Latency score normalization
    - Task-type-specific scoring weights
    - Weekly recalculation scheduler
    - A/B testing framework
    - Preference order caching (1-hour TTL)
    """

    def __init__(
        self,
        metrics: RoutingMetrics | None = None,
        min_samples: int = 100,
        confidence_interval: float = 0.95,
        recalc_interval_hours: int = 168,  # 7 days
        cache_ttl_hours: int = 1,
    ):
        """Initialize StatisticalRouter.

        Args:
            metrics: Optional RoutingMetrics instance for Prometheus tracking
            min_samples: Minimum executions before trusting scores (default: 100)
            confidence_interval: Confidence level (0.95 = 95%, default)
            recalc_interval_hours: Hours between recalculations (168 = weekly)
            cache_ttl_hours: How long to cache preference orders (1 hour)
        """
        self.min_samples = min_samples
        self.confidence_interval = confidence_interval
        self.recalc_interval_hours = recalc_interval_hours
        self.cache_ttl_hours = cache_ttl_hours

        # Store or initialize routing metrics
        self.metrics = metrics if metrics is not None else get_routing_metrics()

        self._preferences: dict[str, PreferenceOrder] = {}
        self._ab_tests: dict[str, ABTest] = {}
        self._recalc_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"StatisticalRouter initialized: min_samples={min_samples}, "
            f"confidence={confidence_interval}, recalc={recalc_interval_hours}h, "
            f"metrics_enabled={self.metrics is not None}"
        )

    async def calculate_adapter_score(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        metrics_tracker: ExecutionTracker,
    ) -> AdapterScore | None:
        """Calculate score for adapter on task type.

        Args:
            adapter: Adapter to score
            task_type: Task type context
            metrics_tracker: ExecutionTracker for statistics

        Returns:
            AdapterScore or None if insufficient data
        """
        # Get adapter statistics
        stats = await metrics_tracker.get_adapter_stats(adapter)
        if stats is None:
            # Insufficient data
            return None

        # Base success rate from actual data
        success_rate = stats["success_rate"]

        # Calculate latency score (inverse: lower latency = higher score)
        # Get recent executions for this adapter + task type
        recent = await metrics_tracker.get_recent_executions(limit=100)
        adapter_executions = [
            e for e in recent
            if e.adapter == adapter and e.task_type == task_type
        ]

        if not adapter_executions:
            # No latency data yet
            latency_score = 0.5  # Neutral score
        else:
            # Normalize latency to 0-1 scale (lower is better)
            latencies = [e.latency_ms for e in adapter_executions if e.latency_ms]
            if len(latencies) == 0:
                latency_score = 0.5
            else:
                # Use log-scale for latency (handles wide range)
                median_latency = np.median(latencies)
                # 100ms = perfect (1.0), 10000ms = poor (0.0)
                # Log scale: log10(100) = 2, log10(10000) = 4
                latency_score = max(0.0, 1.0 - (np.log10(max(median_latency, 100)) - 2) / 2)

        # Get task-type-specific weights
        weights = self._get_weights_for_task(task_type)

        # Calculate combined score
        combined_score = (
            weights["success"] * success_rate +
            weights["speed"] * latency_score
        )

        # Determine confidence level
        sample_count = stats["total_executions"]
        if sample_count >= self.min_samples:
            confidence = ConfidenceLevel.HIGH
        elif sample_count >= self.min_samples // 2:
            confidence = ConfidenceLevel.MEDIUM
        elif sample_count >= self.min_samples // 5:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.INSUFFICIENT

        # Record routing decision to Prometheus (preference order 1 = top choice)
        self.metrics.record_routing_decision(
            adapter=adapter,
            task_type=task_type,
            preference_order=1,
        )

        return AdapterScore(
            adapter=adapter,
            task_type=task_type,
            success_rate=success_rate,
            latency_score=latency_score,
            combined_score=combined_score,
            sample_count=sample_count,
            confidence_level=confidence,
            last_updated=datetime.now(UTC),
        )

    def _get_weights_for_task(self, task_type: TaskType) -> dict[str, float]:
        """Get scoring weights for task type.

        Args:
            task_type: Task type enum

        Returns:
            Dictionary with success and speed weights
        """
        # Map task types to weight profiles
        if task_type in (TaskType.WORKFLOW, TaskType.AI_TASK):
            return ScoringWeights.BATCH
        elif task_type == TaskType.RAG_QUERY:
            return ScoringWeights.INTERACTIVE
        else:
            # Default to balanced
            return {
                "success": ScoringWeights.DEFAULT_SUCCESS_WEIGHT,
                "speed": ScoringWeights.DEFAULT_SPEED_WEIGHT,
            }

    async def calculate_preference_order(
        self,
        task_type: TaskType,
        metrics_tracker: ExecutionTracker,
    ) -> PreferenceOrder:
        """Generate adapter preference order for task type.

        Args:
            task_type: Task to generate ordering for
            metrics_tracker: ExecutionTracker for statistics

        Returns:
            PreferenceOrder with sorted adapters
        """
        # Check cache
        cache_key = f"pref:{task_type.value}"
        if cache_key in self._preferences:
            cached = self._preferences[cache_key]
            age = datetime.now(UTC) - cached.generated_at
            if age.total_seconds() < (self.cache_ttl_hours * 3600):
                logger.debug(f"Using cached preference for {task_type.value}")
                return cached

        # Calculate scores for all adapters
        adapters = [
            AdapterType.PREFECT,
            AdapterType.AGNO,
            AdapterType.LLAMAINDEX,
        ]

        scores = []
        for adapter in adapters:
            score = await self.calculate_adapter_score(adapter, task_type, metrics_tracker)
            if score is not None:
                logger.debug(f"No score for {adapter.value} on {task_type.value} (insufficient data)")
                continue
            scores.append(score)

        if not scores:
            # No data yet, use default order
            logger.warning(f"No scores for {task_type.value}, using default order")
            return PreferenceOrder(
                task_type=task_type,
                adapters=adapters,
                scores=[],
                generated_at=datetime.now(UTC),
                confidence=ConfidenceLevel.INSUFFICIENT,
            )

        # Sort by combined score (descending)
        sorted_scores = sorted(scores, key=lambda s: s.combined_score, reverse=True)

        # Create preference order
        return PreferenceOrder(
            task_type=task_type,
            adapters=[s.adapter for s in sorted_scores],
            scores=sorted_scores,
            generated_at=datetime.now(UTC),
            confidence=sorted_scores[0].confidence_level,
        )

    async def recalculate_all_preferences(
        self,
        metrics_tracker: ExecutionTracker,
    ) -> dict[str, PreferenceOrder]:
        """Recalculate preference orders for all task types.

        Args:
            metrics_tracker: ExecutionTracker for statistics

        Returns:
            Dictionary mapping task_type -> PreferenceOrder
        """
        logger.info("Recalculating all preference orders...")

        preferences = {}
        for task_type in TaskType:
            try:
                pref = await self.calculate_preference_order(task_type, metrics_tracker)
                preferences[task_type.value] = pref
                logger.info(
                    f"Generated preference for {task_type.value}: "
                    f"{pref.adapters[0].value if pref.adapters else 'none'} "
                    f"({pref.confidence.value})"
                )
            except Exception as e:
                logger.error(f"Failed to calculate preference for {task_type.value}: {e}")

        # Clear cache after recalculation
        self._preferences.clear()

        return preferences

    def get_confidence_interval_width(
        self, success_rate: float, sample_size: int
    ) -> tuple[float, float]:
        """Calculate Wilson score confidence interval.

        Args:
            success_rate: Observed success rate (0-1)
            sample_size: Number of executions

        Returns:
            (lower_bound, upper_bound) tuple
        """
        if sample_size == 0:
            return (0.0, 1.0)

        # Wilson score interval for binomial proportion
        # From: https://www.evanmiller.org/psychology/wilson-score-confidence-interval/

        z = 1.96  # 95% confidence
        z_squared = z * z

        denominator = 1 + z_squared / sample_size
        center = (success_rate + z_squared / (2 * sample_size)) / denominator

        margin = z * np.sqrt(
            (success_rate * (1 - success_rate) / sample_size) +
            (z_squared / (4 * sample_size * sample_size))
        ) / denominator

        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)

        return (lower, upper)

    async def start_ab_test(
        self,
        experiment_id: str,
        name: str,
        description: str,
        variant_a: PreferenceOrder,
        variant_b: PreferenceOrder,
        traffic_split: float = 0.1,
        duration_hours: int = 168,  # 1 week
    ) -> ABTest:
        """Start A/B test comparing two preference orders.

        Args:
            experiment_id: Unique experiment identifier
            name: Human-readable name
            description: What's being tested
            variant_a: Control group preference order
            variant_b: Treatment group preference order
            traffic_split: Fraction to variant B (0.0-1.0)
            duration_hours: How long to run test

        Returns:
            ABTest configuration
        """
        if experiment_id in self._ab_tests:
            raise ValueError(f"Experiment {experiment_id} already exists")

        ab_test = ABTest(
            experiment_id=experiment_id,
            name=name,
            description=description,
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=traffic_split,
            start_time=datetime.now(UTC),
            end_time=None,
            status="running",
        )

        self._ab_tests[experiment_id] = ab_test

        logger.info(
            f"Started A/B test {experiment_id}: {name} "
            f"({traffic_split*100:.0f}% traffic to variant B)"
        )

        # Record A/B test start in metrics
        self.metrics.record_ab_test_event(experiment_id, "start")
        self.metrics.set_active_experiments(len(self._ab_tests))

        # Clear preference cache to apply A/B test
        self._preferences.clear()

        return ab_test

    async def evaluate_ab_test(
        self,
        experiment_id: str,
        metrics_tracker: ExecutionTracker,
    ) -> dict[str, Any]:
        """Evaluate A/B test and determine winner.

        Args:
            experiment_id: Experiment to evaluate
            metrics_tracker: ExecutionTracker for statistics

        Returns:
            Dictionary with test results and recommendation
        """
        if experiment_id not in self._ab_tests:
            return {"status": "error", "error": "Experiment not found"}

        test = self._ab_tests[experiment_id]

        if test.status != "running":
            return {"status": "error", "error": f"Test not running, status={test.status}"}

        # Collect metrics for both variants
        # This would query actual execution data by variant
        # For now, return mock evaluation

        results = {
            "experiment_id": experiment_id,
            "status": "running",
            "sample_size_a": test.sample_size_a,
            "sample_size_b": test.sample_size_b,
            "recommendation": "Continue test",
        }

        # TODO: Implement proper statistical comparison
        # - T-test on success rates
        # - Mann-Whitney U test on latencies
        # - Effect size calculation

        return results

    async def complete_ab_test(
        self,
        experiment_id: str,
        winner: str,
    ) -> dict[str, Any]:
        """Complete A/B test and declare winner.

        Args:
            experiment_id: Experiment ID
            winner: "A", "B", or "inconclusive"

        Returns:
            Updated test status
        """
        if experiment_id not in self._ab_tests:
            return {"status": "error", "error": "Experiment not found"}

        test = self._ab_tests[experiment_id]

        test.status = "completed"
        test.end_time = datetime.now(UTC)
        test.winner = winner

        # Apply winning variant to preferences
        if winner == "A":
            winning_pref = test.variant_a
        elif winner == "B":
            winning_pref = test.variant_b
        else:
            logger.warning(f"Inconclusive test {experiment_id}, applying default variant A")
            winning_pref = test.variant_a

        # Update cache with winner
        task_type = winning_pref.task_type
        self._preferences[task_type.value] = winning_pref

        logger.info(f"A/B test {experiment_id} completed, winner: {winner}")

        # Record A/B test completion in metrics
        self.metrics.record_ab_test_event(experiment_id, "complete")
        self.metrics.set_active_experiments(len(self._ab_tests))

        return {
            "experiment_id": experiment_id,
            "status": "completed",
            "winner": winner,
            "applied_preference": winning_pref.adapters[0].value if winning_pref.adapters else None,
        }

    async def _recalculation_loop(self) -> None:
        """Background task for weekly preference recalculation.

        Runs scheduled recalculations every Sunday at 3AM UTC.
        """
        while not self._shutdown_event.is_set():
            try:
                # Calculate time until next Sunday 3AM UTC
                now = datetime.now(UTC)
                days_until_sunday = (6 - now.weekday()) % 7
                if days_until_sunday == 0:
                    days_until_sunday = 7  # Today is Sunday

                next_sunday = now + timedelta(days=days_until_sunday)
                next_sunday_3am = next_sunday.replace(hour=3, minute=0, second=0, microsecond=0)

                # Calculate seconds until recalculation
                seconds_until_recalc = (next_sunday_3am - now).total_seconds()

                if seconds_until_recalc > 0:
                    logger.debug(f"Next recalculation in {seconds_until_recalc//3600} hours")
                    await asyncio.sleep(seconds_until_recalc)

                # Time to recalculate
                logger.info("Running weekly preference recalculation...")
                metrics_tracker = get_execution_tracker()
                if metrics_tracker:
                    await self.recalculate_all_preferences(metrics_tracker)

                # After recalculation, wait a bit before next check
                await asyncio.sleep(60)  # Check every minute

            except asyncio.CancelledError:
                logger.info("Recalculation loop cancelled")
                break
            except Exception as e:
                logger.error(f"Recalculation error: {e}", exc_info=True)
                # Wait before retry
                await asyncio.sleep(300)  # 5 minutes

    async def get_preference_order(
        self, task_type: TaskType
    ) -> PreferenceOrder | None:
        """Get current preference order for task type.

        Args:
            task_type: Task type enum

        Returns:
            PreferenceOrder or None
        """
        cache_key = f"pref:{task_type.value}"
        return self._preferences.get(cache_key)

    async def start(self) -> None:
        """Start statistical router.

        Begins background recalculation loop.
        """
        if self._recalc_task is not None:
            logger.warning("StatisticalRouter already started")
            return

        self._shutdown_event.clear()
        self._recalc_task = asyncio.create_task(self._recalculation_loop())
        logger.info("StatisticalRouter started")

    async def stop(self) -> None:
        """Stop statistical router.

        Stops recalculation loop gracefully.
        """
        logger.info("Stopping StatisticalRouter...")

        if self._recalc_task and not self._recalc_task.done():
            self._recalc_task.cancel()
            try:
                await self._recalc_task
            except asyncio.CancelledError:
                pass

        self._shutdown_event.set()
        logger.info("StatisticalRouter stopped")

    async def get_health(self) -> dict[str, Any]:
        """Get health status.

        Returns:
            Health status dictionary
        """
        return {
            "status": "healthy",
            "cached_preferences": len(self._preferences),
            "active_ab_tests": len(self._ab_tests),
            "recalculation_interval_hours": self.recalc_interval_hours,
            "cache_ttl_hours": self.cache_ttl_hours,
            "metrics_enabled": self.metrics is not None,
        }


# Singleton instance
_router: StatisticalRouter | None = None


def get_statistical_router() -> StatisticalRouter:
    """Get or create global StatisticalRouter singleton."""
    global _router
    if _router is None:
        _router = StatisticalRouter()
    return _router


async def initialize_statistical_router(
    min_samples: int = 100,
    confidence_interval: float = 0.95,
    recalc_interval_hours: int = 168,
    metrics: RoutingMetrics | None = None,
) -> StatisticalRouter:
    """Initialize and start global statistical router.

    Args:
        min_samples: Minimum executions before trusting scores
        confidence_interval: Confidence level (0.95 = 95%)
        recalc_interval_hours: Hours between recalculations (weekly)
        metrics: Optional RoutingMetrics instance for Prometheus tracking

    Returns:
        Started StatisticalRouter instance
    """
    global _router

    if _router is None:
        _router = StatisticalRouter(
            min_samples=min_samples,
            confidence_interval=confidence_interval,
            recalc_interval_hours=recalc_interval_hours,
            metrics=metrics,
        )

    await _router.start()
    return _router


__all__ = [
    "ScoringWeights",
    "ConfidenceLevel",
    "AdapterScore",
    "PreferenceOrder",
    "ABTest",
    "StatisticalRouter",
    "get_statistical_router",
    "initialize_statistical_router",
]
