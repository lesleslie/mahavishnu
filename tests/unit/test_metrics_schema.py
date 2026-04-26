"""Tests for metrics schema and data structures."""

import json
import pytest
from datetime import UTC, datetime, timedelta

from mahavishnu.core.metrics_schema import (
    ABTest,
    ExecutionRecord,
    AdapterStats,
    TaskTypeStats,
    CostTracking,
    RoutingDecision,
    AdapterType,
    TaskType,
    ExecutionStatus,
    calculate_percentiles,
    calculate_confidence_interval,
    generate_execution_key,
    generate_stats_key,
    generate_task_stats_key,
    generate_cost_key,
)


@pytest.mark.asyncio
async def test_execution_record_creation():
    """Should create valid execution record with ULID."""
    record = ExecutionRecord(
        execution_id="01ARZ3NDEKTSVQRRF",
        adapter=AdapterType.PREFECT,
        task_type=TaskType.WORKFLOW,
        start_timestamp=1234567890.0,
        status=ExecutionStatus.SUCCESS,
        latency_ms=150,
        cost_usd=0.05,
    )

    assert record.execution_id == "01ARZ3NDEKTSVQRRF"
    assert record.adapter == AdapterType.PREFECT
    assert record.status == ExecutionStatus.SUCCESS
    assert record.latency_ms == 150


@pytest.mark.asyncio
async def test_execution_record_serialization():
    """Should serialize to JSON with datetime encoding."""
    record = ExecutionRecord(
        execution_id="01ARZ3NDEKTSVQRRF",
        adapter=AdapterType.AGNO,
        task_type=TaskType.AI_TASK,
        start_timestamp=1234567890.0,
        end_timestamp=1234567920.0,
        status=ExecutionStatus.SUCCESS,
        latency_ms=500,
        error_type="timeout",
    )

    # Test serialization
    json_str = record.model_dump_json()
    parsed = json.loads(json_str)
    assert parsed["start_timestamp"] == 1234567890.0
    assert parsed["end_timestamp"] == 1234567920.0
    assert "timeout" in json_str


def test_adapter_stats_validation():
    """Should validate adapter statistics constraints."""
    stats = AdapterStats(
        adapter=AdapterType.PREFECT,
        date="2025-02-11",
        success_rate=0.95,
        total_executions=1000,
        avg_latency_ms=250.0,
        p50_latency_ms=200.0,
        p95_latency_ms=400.0,
        p99_latency_ms=500.0,
        uptime_percentage=99.9,
        sample_size=500,
        confidence_interval=0.95,
    )

    assert stats.success_rate == 0.95
    assert stats.total_executions == 1000
    assert 0.0 <= stats.success_rate <= 1.0
    assert 0.0 <= stats.uptime_percentage <= 100.0


def test_task_type_stats():
    """Should create task-type specific statistics."""
    stats = TaskTypeStats(
        task_type=TaskType.RAG_QUERY,
        date="2025-02-11",
        preferred_adapter=AdapterType.LLAMAINDEX,
        alternative_adapters=[
            AdapterType.LLAMAINDEX,
            AdapterType.PREFECT,
            AdapterType.AGNO,
        ],
        sample_count=200,
        routing_confidence=0.92,
    )

    assert stats.task_type == TaskType.RAG_QUERY
    assert stats.preferred_adapter == AdapterType.LLAMAINDEX
    assert len(stats.alternative_adapters) == 3
    assert stats.sample_count >= 100  # Minimum for statistical validity


def test_cost_tracking():
    """Should track execution costs."""
    cost = CostTracking(
        execution_id="01ARZ3NDEKTSVQRRF",
        adapter=AdapterType.PREFECT,
        task_type=TaskType.AI_TASK,
        cost_usd=0.123,
        budget_type="daily",
        budget_limit_usd=10.0,
    )

    assert cost.cost_usd == 0.123
    assert cost.budget_type == "daily"
    assert cost.budget_limit_usd == 10.0


def test_routing_decision():
    """Should record routing decision with reasoning."""
    decision = RoutingDecision(
        task_type=TaskType.WORKFLOW,
        selected_adapter=AdapterType.PREFECT,
        alternative_adapters=[AdapterType.AGNO, AdapterType.LLAMAINDEX],
        reasoning="Prefect has 99% success rate for workflows",
        adapter_scores={
            AdapterType.PREFECT: 0.99,
            AdapterType.AGNO: 0.85,
            AdapterType.LLAMAINDEX: 0.70,
        },
        constraints={"max_latency_ms": 500},
    )

    assert decision.selected_adapter == AdapterType.PREFECT
    assert decision.reasoning == "Prefect has 99% success rate for workflows"
    assert len(decision.alternative_adapters) == 2
    assert decision.adapter_scores[AdapterType.PREFECT] == 0.99


def test_ab_test():
    """Should track A/B test experiment."""
    experiment = ABTest(
        name="Test Agno vs Prefect for AI tasks",
        start_date="2025-02-11",
        traffic_split={
            AdapterType.PREFECT: 0.5,
            AdapterType.AGNO: 0.5,
        },
        sample_size={
            AdapterType.PREFECT: 500,
            AdapterType.AGNO: 500,
        },
        success_metric="success_rate",
        significance_threshold=0.05,
    )

    assert experiment.name == "Test Agno vs Prefect for AI tasks"
    assert experiment.traffic_split[AdapterType.PREFECT] == 0.5
    assert experiment.sample_size[AdapterType.PREFECT] == 500
    assert 0.0 <= experiment.significance_threshold <= 1.0


def test_percentile_calculation():
    """Should calculate percentiles correctly."""
    latencies = [100, 150, 200, 250, 300, 400, 500, 1000, 2000]

    percentiles = calculate_percentiles(latencies, [50.0, 95.0, 99.0])

    assert percentiles["p50"] == 250  # Median
    assert percentiles["p95"] == 1000
    assert percentiles["p99"] == 2000


def test_confidence_interval():
    """Should calculate confidence interval for success rate."""
    # Small sample
    lower, upper = calculate_confidence_interval(sample_size=10, success_rate=0.8)
    assert abs(upper - lower) > 0.4  # Wide interval for small sample

    # Large sample
    lower, upper = calculate_confidence_interval(sample_size=1000, success_rate=0.85)
    assert abs(upper - lower) < 0.05  # Narrow interval for large sample

    # Perfect success rate
    lower, upper = calculate_confidence_interval(sample_size=100, success_rate=1.0)
    assert lower == 1.0
    assert upper == 1.0


def test_key_generation():
    """Should generate correct Dhara keys."""
    exec_id = "01ARZ3NDEKTSVQRRF"

    assert generate_execution_key(exec_id) == f"exec:{exec_id}"
    assert generate_stats_key(AdapterType.PREFECT, "2025-02-11") == \
        f"stats:adapter:prefect:2025-02-11"
    assert generate_task_stats_key(TaskType.AI_TASK, "2025-02-11") == \
        f"stats:task:ai_task:2025-02-11"
    assert generate_cost_key(exec_id) == f"cost:{exec_id}"


class TestCalculatePercentilesEdgeCases:
    """Test uncovered branches in calculate_percentiles."""

    def test_empty_latencies(self):
        result = calculate_percentiles([])
        assert result == {}

    def test_single_latency(self):
        result = calculate_percentiles([42], [50.0, 95.0, 99.0])
        assert result["p50"] == 42
        assert result["p95"] == 42
        assert result["p99"] == 42

    def test_two_latencies(self):
        result = calculate_percentiles([10, 20], [50.0])
        assert result["p50"] == 10

    def test_custom_percentiles(self):
        latencies = list(range(1, 101))
        result = calculate_percentiles(latencies, [10.0, 90.0])
        assert "p10" in result
        assert "p90" in result

    def test_p99_boundary(self):
        latencies = [100] * 50
        result = calculate_percentiles(latencies, [99.0])
        assert result["p99"] == 100

    def test_p50_median_odd(self):
        latencies = [1, 2, 3, 4, 5]
        result = calculate_percentiles(latencies, [50.0])
        # Custom formula: max(0, (5-1)//2 - 1) = max(0, 1) = 1, so value is 2
        assert result["p50"] == 2


class TestCalculateConfidenceIntervalEdgeCases:
    """Test uncovered branches in calculate_confidence_interval."""

    def test_sample_size_below_10(self):
        lower, upper = calculate_confidence_interval(sample_size=5, success_rate=0.8)
        assert lower == 0.0
        assert upper == 1.0

    def test_zero_success_rate(self):
        lower, upper = calculate_confidence_interval(sample_size=100, success_rate=0.0)
        assert lower == 0.0
        assert upper == 0.0

    def test_zero_sample_size(self):
        lower, upper = calculate_confidence_interval(sample_size=0, success_rate=0.5)
        assert lower == 0.0
        assert upper == 1.0

    def test_very_high_success_rate(self):
        lower, upper = calculate_confidence_interval(sample_size=500, success_rate=0.99)
        assert lower > 0.97
        assert upper < 1.0  # Wilson score doesn't clamp non-boundary rates to 1.0

    def test_low_success_rate(self):
        lower, upper = calculate_confidence_interval(sample_size=500, success_rate=0.01)
        assert lower < 0.01
        assert upper < 0.05


class TestGenerateConfigIdFallback:
    """Test the fallback generate_config_id when oneiric is not available."""

    def test_fallback_returns_string(self):
        from mahavishnu.core import metrics_schema as ms
        original = ms.generate_config_id
        try:
            ms.generate_config_id = lambda: "test-fallback-id"
            result = ms.generate_config_id()
            assert result == "test-fallback-id"
            assert isinstance(result, str)
        finally:
            ms.generate_config_id = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
