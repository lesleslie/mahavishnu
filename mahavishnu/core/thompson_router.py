"""Thompson Sampling Router for Adaptive RAG Strategy Selection.

This module implements a Thompson Sampling-based router that uses Bayesian
optimization to balance exploration (trying new strategies) and exploitation
(using known good strategies).

Reference: "Thompson Sampling: An Optimal Finite Time Algorithm for Online
Stochastic Optimization" (Agrawal & Goyal, 2012)

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                  ThompsonSamplingRouter                      │
    ├─────────────────────────────────────────────────────────────┤
    │  Strategy Performance Tracking                              │
    │  - Beta distribution per strategy (α=successes, β=failures) │
    │  - Latency tracking for cost-aware routing                  │
    │  - Query complexity mapping                                 │
    ├─────────────────────────────────────────────────────────────┤
    │  Thompson Sampling Selection                                │
    │  1. Sample from each strategy's beta distribution           │
    │  2. Select strategy with highest sample                     │
    │  3. Update distribution based on outcome                    │
    └─────────────────────────────────────────────────────────────┘

Usage:
    from mahavishnu.core.thompson_router import ThompsonSamplingRouter

    router = ThompsonSamplingRouter()
    strategy = await router.select_strategy(complexity_score)
    # ... execute strategy ...
    router.update(strategy, success=True, latency_ms=50.0)
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RAGStrategy(Enum):
    """RAG strategy types for Thompson Sampling."""

    NAIVE = "naive"
    HYBRID = "hybrid"
    GRAPH = "graph"
    AGENTIC = "agentic"


@dataclass
class StrategyStats:
    """Statistics for a single strategy."""

    alpha: float = 1.0  # Prior successes + actual successes
    beta: float = 1.0  # Prior failures + actual failures
    total_invocations: int = 0
    total_successes: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0

    # For exponential moving average of latency
    latency_ema: float = 0.0
    latency_alpha: float = 0.1  # EMA smoothing factor

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "total_invocations": self.total_invocations,
            "total_successes": self.total_successes,
            "success_rate": self.success_rate,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "latency_ema": round(self.latency_ema, 3),
        }

    @property
    def success_rate(self) -> float:
        """Calculate empirical success rate."""
        if self.total_invocations == 0:
            return 0.5  # No data, return prior mean
        return self.total_successes / self.total_invocations

    def sample(self) -> float:
        """Sample from Beta(α, β) distribution using numpy if available."""
        try:
            import numpy as np

            return float(np.random.beta(self.alpha, self.beta))
        except ImportError:
            # Fallback: use simple approximation
            return self._sample_beta_approx()

    def _sample_beta_approx(self) -> float:
        """Approximate Beta sampling using Gamma distributions.

        Beta(α, β) = Gamma(α, 1) / (Gamma(α, 1) + Gamma(β, 1))
        """
        x = self._sample_gamma(self.alpha)
        y = self._sample_gamma(self.beta)
        return x / (x + y) if (x + y) > 0 else 0.5

    def _sample_gamma(self, shape: float) -> float:
        """Sample from Gamma distribution using Marsaglia and Tsang's method."""
        if shape < 1:
            # For shape < 1, use: Gamma(shape) = Gamma(shape+1) * U^(1/shape)
            return self._sample_gamma(shape + 1) * (random.random() ** (1 / shape))

        d = shape - 1 / 3
        c = 1 / math.sqrt(9 * d)

        while True:
            x = random.gauss(0, 1)
            v = (1 + c * x) ** 3

            if v > 0:
                u = random.random()
                if u < 1 - 0.0331 * (x**2) ** 2:
                    return d * v
                if math.log(u) < 0.5 * x**2 + d * (1 - v + math.log(v)):
                    return d * v

    def update(self, success: bool, latency_ms: float | None = None) -> None:
        """Update strategy statistics after an invocation.

        Args:
            success: Whether the strategy succeeded
            latency_ms: Latency of the invocation in milliseconds
        """
        self.total_invocations += 1

        if success:
            self.alpha += 1
            self.total_successes += 1
        else:
            self.beta += 1

        if latency_ms is not None:
            self.total_latency_ms += latency_ms
            self.avg_latency_ms = self.total_latency_ms / self.total_invocations

            # Update EMA
            if self.latency_ema == 0:
                self.latency_ema = latency_ms
            else:
                self.latency_ema = (
                    self.latency_alpha * latency_ms + (1 - self.latency_alpha) * self.latency_ema
                )


@dataclass
class ComplexityBand:
    """A band of complexity scores for strategy specialization."""

    min_score: float
    max_score: float
    stats: dict[RAGStrategy, StrategyStats] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize stats for all strategies."""
        if not self.stats:
            for strategy in RAGStrategy:
                self.stats[strategy] = StrategyStats()

    def contains(self, score: float) -> bool:
        """Check if a score falls within this band."""
        return self.min_score <= score < self.max_score


class ThompsonSamplingRouter:
    """Thompson Sampling-based router for RAG strategy selection.

    Uses Bayesian optimization to select strategies that balance:
    - Exploration: Trying strategies that might be good
    - Exploitation: Using strategies known to be good

    The router tracks performance per complexity band, allowing different
    strategies to be optimal for different query types.

    Example:
        >>> router = ThompsonSamplingRouter()
        >>> strategy = await router.select_strategy(0.5)
        >>> # ... execute strategy ...
        >>> router.update(strategy, success=True, latency_ms=50.0)
    """

    # Default complexity bands
    DEFAULT_BANDS = [
        (0.0, 0.3),  # Low complexity
        (0.3, 0.6),  # Medium complexity
        (0.6, 0.8),  # High complexity
        (0.8, 1.0),  # Very high complexity
    ]

    def __init__(
        self,
        bands: list[tuple[float, float]] | None = None,
        exploration_bonus: float = 0.0,
        latency_weight: float = 0.3,
    ) -> None:
        """Initialize Thompson Sampling router.

        Args:
            bands: Complexity bands for strategy specialization
            exploration_bonus: Bonus added to encourage exploration (0-1)
            latency_weight: Weight for latency in score calculation (0-1)
        """
        self.bands = [
            ComplexityBand(min_score=b[0], max_score=b[1]) for b in (bands or self.DEFAULT_BANDS)
        ]
        self.exploration_bonus = exploration_bonus
        self.latency_weight = latency_weight

        # Global stats for fallback
        self.global_stats: dict[RAGStrategy, StrategyStats] = {
            s: StrategyStats() for s in RAGStrategy
        }

        # History for analysis
        self._selection_history: list[dict[str, Any]] = []
        self._max_history = 1000

    def _get_band(self, complexity_score: float) -> ComplexityBand:
        """Get the complexity band for a given score."""
        for band in self.bands:
            if band.contains(complexity_score):
                return band
        # Default to last band if score is 1.0
        return self.bands[-1]

    def _calculate_latency_penalty(self, stats: StrategyStats) -> float:
        """Calculate latency penalty for a strategy.

        Lower latency = lower penalty = higher score.
        """
        if stats.latency_ema == 0:
            return 0.0  # No data, no penalty

        # Normalize latency to 0-1 range (assume 1000ms is max expected)
        max_latency = 1000.0
        normalized_latency = min(stats.latency_ema / max_latency, 1.0)

        return normalized_latency * self.latency_weight

    async def select_strategy(
        self,
        complexity_score: float,
        query: str | None = None,
    ) -> RAGStrategy:
        """Select a RAG strategy using Thompson Sampling.

        Args:
            complexity_score: Query complexity score (0-1)
            query: Optional query text for logging

        Returns:
            Selected RAG strategy
        """
        band = self._get_band(complexity_score)

        # Sample from each strategy's posterior distribution
        samples: dict[RAGStrategy, float] = {}

        for strategy in RAGStrategy:
            stats = band.stats.get(strategy, self.global_stats[strategy])

            # Thompson sample from Beta distribution
            sample = stats.sample()

            # Add exploration bonus
            sample += self.exploration_bonus

            # Subtract latency penalty
            sample -= self._calculate_latency_penalty(stats)

            samples[strategy] = max(0, sample)  # Ensure non-negative

        # Select strategy with highest sample
        selected = max(samples, key=samples.get)

        # Record selection
        self._record_selection(selected, complexity_score, samples, query)

        logger.debug(
            f"thompson_sampling_selection: strategy={selected.value}, "
            f"complexity={complexity_score:.2f}, samples={samples}"
        )

        return selected

    def _record_selection(
        self,
        strategy: RAGStrategy,
        complexity_score: float,
        samples: dict[RAGStrategy, float],
        query: str | None,
    ) -> None:
        """Record selection for analysis."""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "strategy": strategy.value,
            "complexity_score": complexity_score,
            "samples": {s.value: v for s, v in samples.items()},
            "query_preview": query[:50] if query else None,
        }

        self._selection_history.append(record)

        # Trim history if needed
        if len(self._selection_history) > self._max_history:
            self._selection_history = self._selection_history[-self._max_history :]

    def update(
        self,
        strategy: RAGStrategy,
        success: bool,
        latency_ms: float | None = None,
        complexity_score: float | None = None,
    ) -> None:
        """Update strategy statistics after execution.

        Args:
            strategy: The strategy that was used
            success: Whether the execution succeeded
            latency_ms: Execution latency in milliseconds
            complexity_score: Complexity score of the query
        """
        # Update global stats
        self.global_stats[strategy].update(success, latency_ms)

        # Update band-specific stats if complexity provided
        if complexity_score is not None:
            band = self._get_band(complexity_score)
            band.stats[strategy].update(success, latency_ms)

        logger.debug(
            f"thompson_sampling_update: strategy={strategy.value}, "
            f"success={success}, latency={latency_ms}, complexity={complexity_score}"
        )

    def get_stats(self) -> dict[str, Any]:
        """Get router statistics."""
        return {
            "global_stats": {s.value: stats.to_dict() for s, stats in self.global_stats.items()},
            "bands": [
                {
                    "range": f"{b.min_score:.1f}-{b.max_score:.1f}",
                    "stats": {s.value: stats.to_dict() for s, stats in b.stats.items()},
                }
                for b in self.bands
            ],
            "total_selections": len(self._selection_history),
            "exploration_bonus": self.exploration_bonus,
            "latency_weight": self.latency_weight,
        }

    def get_strategy_distribution(self) -> dict[str, int]:
        """Get distribution of selected strategies."""
        distribution: dict[str, int] = {s.value: 0 for s in RAGStrategy}

        for record in self._selection_history:
            strategy = record["strategy"]
            distribution[strategy] = distribution.get(strategy, 0) + 1

        return distribution

    def reset_stats(self) -> None:
        """Reset all statistics to prior values."""
        for strategy in RAGStrategy:
            self.global_stats[strategy] = StrategyStats()

        for band in self.bands:
            for strategy in RAGStrategy:
                band.stats[strategy] = StrategyStats()

        self._selection_history.clear()
        logger.info("thompson_sampling_router_reset")


def create_thompson_router(
    bands: list[tuple[float, float]] | None = None,
    exploration_bonus: float = 0.1,
    latency_weight: float = 0.3,
) -> ThompsonSamplingRouter:
    """Create a Thompson Sampling router.

    Args:
        bands: Complexity bands for specialization
        exploration_bonus: Bonus for exploration (default 0.1)
        latency_weight: Weight for latency in scoring (default 0.3)

    Returns:
        Configured ThompsonSamplingRouter
    """
    return ThompsonSamplingRouter(
        bands=bands,
        exploration_bonus=exploration_bonus,
        latency_weight=latency_weight,
    )


__all__ = [
    "RAGStrategy",
    "StrategyStats",
    "ThompsonSamplingRouter",
    "create_thompson_router",
]
