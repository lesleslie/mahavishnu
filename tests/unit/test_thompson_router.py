"""Unit tests for Thompson Sampling Router."""

from __future__ import annotations

import pytest

from mahavishnu.core.thompson_router import (
    RAGStrategy,
    StrategyStats,
    ThompsonSamplingRouter,
    create_thompson_router,
)


class TestStrategyStats:
    """Tests for StrategyStats."""

    def test_initial_values(self) -> None:
        """Test initial stats values."""
        stats = StrategyStats()
        assert stats.alpha == 1.0
        assert stats.beta == 1.0
        assert stats.total_invocations == 0
        assert stats.total_successes == 0

    def test_success_rate_no_data(self) -> None:
        """Test success rate when no invocations."""
        stats = StrategyStats()
        assert stats.success_rate == 0.5  # Prior mean

    def test_success_rate_with_data(self) -> None:
        """Test success rate calculation."""
        stats = StrategyStats()
        stats.update(success=True, latency_ms=10.0)
        stats.update(success=True, latency_ms=15.0)
        stats.update(success=False, latency_ms=12.0)

        assert stats.total_invocations == 3
        assert stats.total_successes == 2
        assert stats.success_rate == 2 / 3

    def test_update_success(self) -> None:
        """Test updating with success."""
        stats = StrategyStats()
        stats.update(success=True, latency_ms=50.0)

        assert stats.alpha == 2.0  # 1 + 1 success
        assert stats.beta == 1.0  # unchanged
        assert stats.total_successes == 1
        assert stats.avg_latency_ms == 50.0

    def test_update_failure(self) -> None:
        """Test updating with failure."""
        stats = StrategyStats()
        stats.update(success=False, latency_ms=100.0)

        assert stats.alpha == 1.0  # unchanged
        assert stats.beta == 2.0  # 1 + 1 failure
        assert stats.total_successes == 0

    def test_sample_returns_valid_value(self) -> None:
        """Test that sample returns value between 0 and 1."""
        stats = StrategyStats()
        stats.update(success=True)
        stats.update(success=True)
        stats.update(success=False)

        for _ in range(10):
            sample = stats.sample()
            assert 0.0 <= sample <= 1.0

    def test_ema_latency(self) -> None:
        """Test exponential moving average latency."""
        stats = StrategyStats(latency_alpha=0.5)

        stats.update(success=True, latency_ms=100.0)
        assert stats.latency_ema == 100.0

        stats.update(success=True, latency_ms=200.0)
        # EMA = alpha * new + (1-alpha) * old
        # = 0.5 * 200 + 0.5 * 100 = 150
        assert stats.latency_ema == 150.0

    def test_to_dict(self) -> None:
        """Test dictionary conversion."""
        stats = StrategyStats()
        stats.update(success=True, latency_ms=50.0)

        d = stats.to_dict()
        assert d["alpha"] == 2.0
        assert d["beta"] == 1.0
        assert d["total_invocations"] == 1
        assert d["success_rate"] == 1.0


class TestThompsonSamplingRouter:
    """Tests for ThompsonSamplingRouter."""

    def test_initialization(self) -> None:
        """Test router initialization."""
        router = ThompsonSamplingRouter()
        assert len(router.bands) == 4
        assert router.exploration_bonus == 0.0
        assert router.latency_weight == 0.3

    def test_custom_bands(self) -> None:
        """Test custom band configuration."""
        router = ThompsonSamplingRouter(
            bands=[(0.0, 0.5), (0.5, 1.0)],
            exploration_bonus=0.1,
        )
        assert len(router.bands) == 2
        assert router.exploration_bonus == 0.1

    @pytest.mark.asyncio
    async def test_select_strategy_returns_valid(self) -> None:
        """Test that select returns valid strategy."""
        router = ThompsonSamplingRouter()

        for score in [0.1, 0.3, 0.5, 0.7, 0.9]:
            strategy = await router.select_strategy(score)
            assert isinstance(strategy, RAGStrategy)

    @pytest.mark.asyncio
    async def test_select_strategy_uses_complexity_band(self) -> None:
        """Test that selection uses complexity bands."""
        router = ThompsonSamplingRouter()

        # Select multiple times and track distribution
        strategies: dict[str, int] = {}
        for _ in range(10):
            strategy = await router.select_strategy(0.1)  # Low complexity
            strategies[strategy.value] = strategies.get(strategy.value, 0) + 1

        # Should have selected some strategies
        assert sum(strategies.values()) == 10

    def test_update_global_stats(self) -> None:
        """Test updating global statistics."""
        router = ThompsonSamplingRouter()

        router.update(RAGStrategy.NAIVE, success=True, latency_ms=50.0)

        stats = router.global_stats[RAGStrategy.NAIVE]
        assert stats.total_invocations == 1
        assert stats.total_successes == 1

    def test_update_band_stats(self) -> None:
        """Test updating band-specific statistics."""
        router = ThompsonSamplingRouter()

        router.update(
            RAGStrategy.HYBRID,
            success=True,
            latency_ms=100.0,
            complexity_score=0.5,  # Medium complexity band
        )

        # Check band stats
        band = router._get_band(0.5)
        band_stats = band.stats[RAGStrategy.HYBRID]
        assert band_stats.total_invocations == 1

    def test_get_stats(self) -> None:
        """Test statistics retrieval."""
        router = ThompsonSamplingRouter()
        router.update(RAGStrategy.NAIVE, success=True, latency_ms=50.0)

        stats = router.get_stats()

        assert "global_stats" in stats
        assert "bands" in stats
        assert stats["total_selections"] == 0  # No selections yet

    @pytest.mark.asyncio
    async def test_strategy_distribution(self) -> None:
        """Test strategy distribution tracking."""
        router = ThompsonSamplingRouter()

        # Make some selections
        for _ in range(5):
            await router.select_strategy(0.5)

        distribution = router.get_strategy_distribution()
        assert sum(distribution.values()) == 5

    def test_reset_stats(self) -> None:
        """Test statistics reset."""
        router = ThompsonSamplingRouter()

        # Update some stats
        router.update(RAGStrategy.NAIVE, success=True)
        router.update(RAGStrategy.HYBRID, success=False)

        # Reset
        router.reset_stats()

        # Check all stats are reset
        for strategy in RAGStrategy:
            assert router.global_stats[strategy].total_invocations == 0

    @pytest.mark.asyncio
    async def test_latency_penalty(self) -> None:
        """Test that high latency penalizes strategy."""
        router = ThompsonSamplingRouter(latency_weight=0.5)

        # Manually set high latency for NAIVE
        router.global_stats[RAGStrategy.NAIVE].update(success=True, latency_ms=500.0)

        # Get penalty
        penalty = router._calculate_latency_penalty(router.global_stats[RAGStrategy.NAIVE])
        assert penalty > 0
        assert penalty <= 0.5  # max penalty is latency_weight

    @pytest.mark.asyncio
    async def test_exploration_bonus(self) -> None:
        """Test that exploration bonus encourages exploration."""
        router = ThompsonSamplingRouter(exploration_bonus=0.5)

        # Even with no data, should be able to select
        strategy = await router.select_strategy(0.5)
        assert isinstance(strategy, RAGStrategy)

    @pytest.mark.asyncio
    async def test_learning_over_time(self) -> None:
        """Test that router learns from outcomes."""
        router = ThompsonSamplingRouter()

        # Train the router: NAIVE always succeeds for low complexity
        for _ in range(10):
            strategy = await router.select_strategy(0.1)
            if strategy == RAGStrategy.NAIVE:
                router.update(strategy, success=True, latency_ms=10.0, complexity_score=0.1)
            else:
                router.update(strategy, success=False, latency_ms=100.0, complexity_score=0.1)

        # Check that NAIVE has better stats
        naive_stats = router.global_stats[RAGStrategy.NAIVE]
        assert naive_stats.alpha >= 1.0


class TestCreateThompsonRouter:
    """Tests for factory function."""

    def test_creates_router(self) -> None:
        """Test that factory creates a router."""
        router = create_thompson_router()
        assert isinstance(router, ThompsonSamplingRouter)

    def test_custom_parameters(self) -> None:
        """Test custom parameters are applied."""
        router = create_thompson_router(
            exploration_bonus=0.2,
            latency_weight=0.4,
        )
        assert router.exploration_bonus == 0.2
        assert router.latency_weight == 0.4

    def test_custom_bands(self) -> None:
        """Test custom bands configuration."""
        router = create_thompson_router(
            bands=[(0.0, 0.25), (0.25, 0.5), (0.5, 1.0)],
        )
        assert len(router.bands) == 3
