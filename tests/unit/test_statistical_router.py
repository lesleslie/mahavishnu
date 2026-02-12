"""Tests for statistical router and adaptive scoring."""

import pytest
import asyncio
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from mahavishnu.core.statistical_router import (
    StatisticalRouter,
    ScoringWeights,
    ConfidenceLevel,
    AdapterScore,
    PreferenceOrder,
    ABTest,
    get_statistical_router,
    initialize_statistical_router,
)
from mahavishnu.core.metrics_collector import ExecutionTracker, SamplingStrategy
from mahavishnu.core.metrics_schema import AdapterType, TaskType


@pytest.fixture
async def tracker():
    """Provide ExecutionTracker for tests."""
    t = ExecutionTracker(
        sampling_strategy=SamplingStrategy.FULL,
        batch_size=10,
    )
    await t.start()
    yield t
    await t.stop()


@pytest.fixture
async def router(tracker):
    """Provide StatisticalRouter for tests."""
    r = StatisticalRouter(min_samples=10)  # Low min samples for testing
    await r.start()
    yield r
    await r.stop()


class TestScoringWeights:
    """Test scoring weight configurations."""

    def test_default_weights(self):
        """Should have balanced default weights."""
        assert ScoringWeights.DEFAULT_SUCCESS_WEIGHT == 0.7
        assert ScoringWeights.DEFAULT_SPEED_WEIGHT == 0.3

    def test_interactive_weights(self):
        """Interactive tasks should prioritize speed."""
        assert ScoringWeights.INTERACTIVE["success"] == 0.5
        assert ScoringWeights.INTERACTIVE["speed"] == 0.5

    def test_batch_weights(self):
        """Batch tasks should prioritize success rate."""
        assert ScoringWeights.BATCH["success"] == 0.9
        assert ScoringWeights.BATCH["speed"] == 0.1

    def test_critical_weights(self):
        """Critical tasks should heavily weight success."""
        assert ScoringWeights.CRITICAL["success"] == 0.8
        assert ScoringWeights.CRITICAL["speed"] == 0.2


class TestAdapterScore:
    """Test adapter score calculation."""

    def test_create_valid_score(self):
        """Should create valid score."""
        score = AdapterScore(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            success_rate=0.85,
            latency_score=0.75,
            combined_score=0.82,
            sample_count=150,
            confidence_level=ConfidenceLevel.HIGH,
            last_updated=datetime.now(UTC),
        )

        assert score.adapter == AdapterType.PREFECT
        assert score.success_rate == 0.85
        assert score.latency_score == 0.75
        assert score.combined_score == 0.82
        assert score.sample_count == 150

    def test_score_validation_success_rate_too_high(self):
        """Should reject success rate > 1.0."""
        with pytest.raises(ValueError):
            AdapterScore(
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                success_rate=1.1,  # Invalid
                latency_score=0.5,
                combined_score=0.8,
                sample_count=50,
                confidence_level=ConfidenceLevel.MEDIUM,
                last_updated=datetime.now(UTC),
            )

    def test_score_validation_success_rate_negative(self):
        """Should reject negative success rate."""
        with pytest.raises(ValueError):
            AdapterScore(
                adapter=AdapterType.LLAMAINDEX,
                task_type=TaskType.RAG_QUERY,
                success_rate=-0.1,  # Invalid
                latency_score=0.5,
                combined_score=0.8,
                sample_count=30,
                confidence_level=ConfidenceLevel.LOW,
                last_updated=datetime.now(UTC),
            )


class TestConfidenceIntervals:
    """Test confidence interval calculations."""

    @pytest.mark.asyncio
    async def test_confidence_interval_sufficient_data(self, router):
        """Should calculate Wilson score interval with sufficient data."""
        # Success rate: 0.85, sample size: 100
        lower, upper = router.get_confidence_interval_width(0.85, 100)

        # Should be roughly 0.77-0.91 for 85% with 100 samples
        assert 0.75 < lower < 0.85
        assert 0.85 < upper < 0.95

    @pytest.mark.asyncio
    async def test_confidence_interval_small_sample(self, router):
        """Should have wider interval with small sample."""
        # Same success rate, smaller sample
        lower_small, upper_small = router.get_confidence_interval_width(0.85, 20)

        # Interval should be wider than with 100 samples
        assert (lower_small < lower)  # Lower bound is lower
        assert (upper_small > upper)  # Upper bound is higher

    @pytest.mark.asyncio
    async def test_confidence_interval_zero_samples(self, router):
        """Should return full range with zero samples."""
        lower, upper = router.get_confidence_interval_width(0.5, 0)

        assert lower == 0.0
        assert upper == 1.0

    @pytest.mark.asyncio
    async def test_confidence_interval_perfect_success(self, router):
        """Should narrow interval for 100% success rate."""
        lower, upper = router.get_confidence_interval_width(1.0, 100)

        # Should be very narrow around 1.0
        assert 0.95 <= lower <= 1.0
        assert 1.0 >= upper >= 0.99


class TestCalculateAdapterScore:
    """Test adapter score calculation."""

    @pytest.mark.asyncio
    async def test_calculate_score_with_sufficient_data(self, router, tracker):
        """Should calculate score with sufficient samples."""
        # Add mock statistics
        tracker._metrics.adapter_attempts["prefect"]["success"] = 80
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 20

        # Add mock latency data
        for i in range(10):
            execution_id = await tracker.record_execution_start(
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                repos=["/path/to/repo"],
            )
            await tracker.record_execution_end(
                execution_id=execution_id,
                success=True,
                latency_ms=1000 + i * 100,  # Varying latencies
            )

        score = await router.calculate_adapter_score(
            AdapterType.PREFECT,
            TaskType.WORKFLOW,
            tracker,
        )

        assert score is not None
        assert score.adapter == AdapterType.PREFECT
        assert abs(score.success_rate - 0.8) < 0.01  # Allow floating point diff
        assert 0.0 <= score.latency_score <= 1.0
        assert score.sample_count >= 10

    @pytest.mark.asyncio
    async def test_calculate_score_insufficient_data(self, router, tracker):
        """Should return None with insufficient samples."""
        # Only 5 executions
        tracker._metrics.adapter_attempts["agno"]["success"] = 4
        tracker._metrics.adapter_attempts["agno"]["failure"] = 1

        score = await router.calculate_adapter_score(
            AdapterType.AGNO,
            TaskType.AI_TASK,
            tracker,
        )

        # Min samples is 10, only have 5
        assert score is None

    @pytest.mark.asyncio
    async def test_latency_score_normalization(self, router, tracker):
        """Should normalize latency to 0-1 scale."""
        # Mock executions with specific latencies
        latencies = [100, 500, 1000, 5000, 10000]  # ms

        for i, latency in enumerate(latencies):
            execution_id = await tracker.record_execution_start(
                adapter=AdapterType.LLAMAINDEX,
                task_type=TaskType.RAG_QUERY,
                repos=["/path/to/repo"],
            )
            await tracker.record_execution_end(
                execution_id=execution_id,
                success=True,
                latency_ms=latency,
            )

        score = await router.calculate_adapter_score(
            AdapterType.LLAMAINDEX,
            TaskType.RAG_QUERY,
            tracker,
        )

        # Lower latency should have higher score
        # 100ms should be near 1.0, 10000ms should be near 0.0
        assert 0.0 < score.latency_score < 1.0


class TestPreferenceOrderGeneration:
    """Test preference order generation."""

    @pytest.mark.asyncio
    async def test_generate_preference_order_with_data(self, router, tracker):
        """Should generate preference order when data exists."""
        # Setup adapter stats
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            tracker._metrics.adapter_attempts[adapter.value]["success"] = 50
            tracker._metrics.adapter_attempts[adapter.value]["failure"] = 10

        pref = await router.calculate_preference_order(TaskType.WORKFLOW, tracker)

        assert pref.task_type == TaskType.WORKFLOW
        assert len(pref.adapters) == 2  # Only Prefect and Agno have data
        assert pref.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW)
        assert pref.generated_at < datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_generate_preference_order_no_data(self, router, tracker):
        """Should use default order with no data."""
        pref = await router.calculate_preference_order(TaskType.AI_TASK, tracker)

        # No adapter stats, should return default order with insufficient confidence
        assert pref.task_type == TaskType.AI_TASK
        assert len(pref.adapters) == 3  # All adapters in default order
        assert pref.confidence == ConfidenceLevel.INSUFFICIENT

    @pytest.mark.asyncio
    async def test_preference_order_sorting(self, router, tracker):
        """Should sort by combined score descending."""
        # Setup: Prefect best (0.9), Agno medium (0.7), LlamaIndex poor (0.5)
        scores_data = []

        for adapter, combined_score in [
            (AdapterType.PREFECT, 0.9),
            (AdapterType.AGNO, 0.7),
            (AdapterType.LLAMAINDEX, 0.5),
        ]:
            # Add mock stats to meet min samples
            tracker._metrics.adapter_attempts[adapter.value]["success"] = int(combined_score * 90)
            tracker._metrics.adapter_attempts[adapter.value]["failure"] = int(combined_score * 10)

            score = await router.calculate_adapter_score(adapter, TaskType.WORKFLOW, tracker)
            if score:
                scores_data.append(score)

        pref = await router.calculate_preference_order(TaskType.WORKFLOW, tracker)

        # Should be sorted: Prefect, Agno, LlamaIndex
        assert pref.adapters[0] == AdapterType.PREFECT
        assert pref.adapters[1] == AdapterType.AGNO
        assert pref.adapters[2] == AdapterType.LLAMAINDEX

        # Verify combined scores are descending
        if len(pref.scores) >= 2:
            assert pref.scores[0].combined_score >= pref.scores[1].combined_score

    @pytest.mark.asyncio
    async def test_task_type_weights(self, router, tracker):
        """Should apply task-type-specific weights."""
        # Interactive task (RAG_QUERY) should weight speed higher
        tracker._metrics.adapter_attempts["llamaindex"]["success"] = 40
        tracker._metrics.adapter_attempts["llamaindex"]["failure"] = 10

        score_rag = await router.calculate_adapter_score(
            AdapterType.LLAMAINDEX,
            TaskType.RAG_QUERY,  # Interactive
            tracker,
        )

        # Batch task (WORKFLOW) should weight success higher
        tracker._metrics.adapter_attempts["prefect"]["success"] = 45
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 5

        score_workflow = await router.calculate_adapter_score(
            AdapterType.PREFECT,
            TaskType.WORKFLOW,  # Batch
            tracker,
        )

        # Workflow (batch) should have lower speed component, RAG higher
        # Success rate should be weighted differently
        # We can't directly verify weights but can check scores are different
        assert score_rag.latency_score != score_workflow.latency_score or \
               score_rag.combined_score != score_workflow.combined_score

    @pytest.mark.asyncio
    async def test_preference_cache(self, router, tracker):
        """Should cache preference orders."""
        # First call
        tracker._metrics.adapter_attempts["agno"]["success"] = 30
        tracker._metrics.adapter_attempts["agno"]["failure"] = 5

        pref1 = await router.calculate_preference_order(TaskType.AI_TASK, tracker)
        pref2 = await router.calculate_preference_order(TaskType.AI_TASK, tracker)

        # Should return same cached object
        assert pref1 is pref2
        assert pref1.generated_at == pref2.generated_at


class TestABTesting:
    """Test A/B testing functionality."""

    @pytest.mark.asyncio
    async def test_start_ab_test(self, router):
        """Should create A/B test configuration."""
        variant_a = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT, AdapterType.AGNO],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        variant_b = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.AGNO, AdapterType.PREFECT],  # Swapped
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        ab_test = await router.start_ab_test(
            experiment_id="test_exp_001",
            name="Prefect vs Agno first",
            description="Test if Agno performs better as primary",
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=0.1,  # 10% to B
            duration_hours=168,
        )

        assert ab_test.experiment_id == "test_exp_001"
        assert ab_test.status == "running"
        assert ab_test.traffic_split == 0.1
        assert "test_exp_001" in router._ab_tests

    @pytest.mark.asyncio
    async def test_start_ab_test_duplicate_id(self, router):
        """Should reject duplicate experiment ID."""
        variant_a = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        variant_b = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.AGNO],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        # Create first test
        await router.start_ab_test(
            experiment_id="test_exp_002",
            name="Test",
            description="Test",
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=0.1,
            duration_hours=168,
        )

        # Try to create duplicate
        with pytest.raises(ValueError):
            await router.start_ab_test(
                experiment_id="test_exp_002",
                name="Test",
                description="Test",
                variant_a=variant_a,
                variant_b=variant_b,
                traffic_split=0.1,
                duration_hours=168,
            )

    @pytest.mark.asyncio
    async def test_complete_ab_test(self, router):
        """Should complete A/B test and apply winner."""
        # First create a test
        variant_a = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        variant_b = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.AGNO],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        await router.start_ab_test(
            experiment_id="test_exp_003",
            name="Winner test",
            description="Test completion",
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=0.1,
            duration_hours=168,
        )

        # Complete with B as winner
        result = await router.complete_ab_test("test_exp_003", winner="B")

        assert result["status"] == "completed"
        assert result["winner"] == "B"
        assert result["applied_preference"] == "agno"  # Variant B winner

        # Verify preference cache updated
        pref = await router.get_preference_order(TaskType.WORKFLOW)
        assert pref is not None
        assert pref.ab_test_active is True
        assert pref.ab_test_variant == "B"

    @pytest.mark.asyncio
    async def test_evaluate_ab_test(self, router):
        """Should evaluate A/B test statistics."""
        # Create test
        variant_a = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        variant_b = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.AGNO],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        await router.start_ab_test(
            experiment_id="test_exp_004",
            name="Evaluation test",
            description="Test",
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=0.1,
            duration_hours=168,
        )

        result = await router.evaluate_ab_test("test_exp_004")

        assert result["status"] == "running"
        assert "experiment_id" in result


class TestRecalculationLoop:
    """Test weekly recalculation scheduler."""

    @pytest.mark.asyncio
    async def test_recalculate_all_preferences(self, router, tracker):
        """Should recalculate all preference orders."""
        # Setup mock data
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            tracker._metrics.adapter_attempts[adapter.value]["success"] = 20
            tracker._metrics.adapter_attempts[adapter.value]["failure"] = 5

        preferences = await router.recalculate_all_preferences(tracker)

        assert len(preferences) > 0
        assert any(p.task_type in (TaskType.WORKFLOW, TaskType.AI_TASK, TaskType.RAG_QUERY)
                 for p in preferences.values())

    @pytest.mark.asyncio
    async def test_recalculation_clears_cache(self, router, tracker):
        """Should clear cache after recalculation."""
        # Generate initial preference (cached)
        tracker._metrics.adapter_attempts["prefect"]["success"] = 25
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 5

        pref1 = await router.calculate_preference_order(TaskType.WORKFLOW, tracker)
        cache_key = f"pref:{TaskType.WORKFLOW.value}"
        assert cache_key in router._preferences

        # Recalculate (should clear cache)
        await router.recalculate_all_preferences(tracker)

        # Cache should be cleared
        assert cache_key not in router._preferences or \
               router._preferences.get(cache_key) is not pref1


class TestRouterLifecycle:
    """Test router lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Should start and stop cleanly."""
        router = StatisticalRouter()

        assert router._recalc_task is None

        await router.start()
        assert router._recalc_task is not None
        assert not router._shutdown_event.is_set()

        await router.stop()
        assert router._recalc_task.cancelled() or router._recalc_task.done()
        assert router._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_double_start(self):
        """Should handle double start gracefully."""
        router = StatisticalRouter()

        await router.start()
        await router.start()  # Second start

        # Should log warning but not crash
        assert router._recalc_task is not None

        await router.stop()

    @pytest.mark.asyncio
    async def test_get_health(self):
        """Should return health status."""
        router = StatisticalRouter()

        # Add a test preference
        router._preferences["pref:test"] = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT],
            scores=[],
            generated_at=datetime.now(UTC),
            confidence=ConfidenceLevel.HIGH,
        )

        # Add active A/B test
        router._ab_tests["test_001"] = ABTest(
            experiment_id="test_001",
            name="Test",
            description="Test",
            variant_a=None,
            variant_b=None,
            traffic_split=0.1,
            start_time=datetime.now(UTC),
            end_time=None,
            status="running",
        )

        health = await router.get_health()

        assert health["status"] == "healthy"
        assert health["cached_preferences"] == 1
        assert health["active_ab_tests"] == 1
        assert health["recalculation_interval_hours"] == 168


class TestSingleton:
    """Test global singleton pattern."""

    @pytest.mark.asyncio
    async def test_get_statistical_router_singleton(self):
        """Should return same instance on multiple calls."""
        import mahavishnu.core.statistical_router as sr
        sr._router = None

        router1 = get_statistical_router()
        router2 = get_statistical_router()

        assert router1 is router2

    @pytest.mark.asyncio
    async def test_initialize_statistical_router(self):
        """Should initialize and start router."""
        import mahavishnu.core.statistical_router as sr
        sr._router = None

        router = await initialize_statistical_router(min_samples=50)

        assert router is not None
        assert router.min_samples == 50
        assert router._recalc_task is not None

        await router.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
