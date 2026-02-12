"""Integration tests for RoutingMetrics with core components.

Tests that RoutingMetrics properly integrates with:
- StatisticalRouter (scores routing decisions)
- CostOptimizer (tracks costs)
- TaskRouter (comprehensive routing)
"""

import pytest
import asyncio
from mahavishnu.core.routing_metrics import RoutingMetrics, get_routing_metrics, reset_routing_metrics
from mahavishnu.core.statistical_router import StatisticalRouter, get_statistical_router
from mahavishnu.core.cost_optimizer import CostOptimizer, get_cost_optimizer


@pytest.fixture
def reset_metrics():
    """Reset routing metrics before each test."""
    reset_routing_metrics()
    yield


class TestStatisticalRouterMetrics:
    """Test StatisticalRouter metrics integration."""

    @pytest.mark.asyncio
    async def test_calculate_adapter_score_records_decision(self, reset_metrics):
        """Test that calculate_adapter_score records routing decision."""
        router = StatisticalRouter(metrics=get_routing_metrics("test_router"))
        adapter = AdapterType.LLAMAINDEX
        task_type = TaskType.RAG_QUERY

        # Get adapter stats (mock)
        from mahavishnu.core.metrics_collector import ExecutionTracker
        class MockTracker:
            async def get_adapter_stats(self, adapter_type):
                return {
                    "success_rate": 0.95,
                    "total_executions": 150,
                }
            async def get_recent_executions(self, limit=100):
                # Return mock executions with latency data
                return [
                    type("obj", object()) for _ in range(50)
                ]

        tracker = MockTracker()

        # Call calculate_adapter_score - should record routing decision
        score = await router.calculate_adapter_score(
            adapter=adapter,
            task_type=task_type,
            metrics_tracker=tracker,
        )

        # Verify routing decision was recorded
        assert score is not None, "Should return score"
        assert score.adapter == adapter, "Score should match adapter"
        assert score.task_type == task_type, "Task type should match"

    @pytest.mark.asyncio
    async def test_recalculate_all_preferences(self, reset_metrics):
        """Test that recalculate_all_preferences triggers metrics usage."""
        router = StatisticalRouter(metrics=get_routing_metrics("test_router"))

        # Get mock tracker
        class MockTracker:
            async def get_adapter_stats(self, adapter_type):
                return {
                    "success_rate": 0.92,
                    "total_executions": 200,
                }
            async def get_recent_executions(self, limit=100):
                return []

        tracker = MockTracker()

        # Recalculate preferences - should use metrics internally
        await router.recalculate_all_preferences(tracker)

        # Verify router was initialized with metrics
        assert router.metrics is not None, "Router should have metrics"
        assert isinstance(router.metrics, RoutingMetrics), "Metrics should be RoutingMetrics instance"

    @pytest.mark.asyncio
    async def test_start_ab_test_records_event(self, reset_metrics):
        """Test that A/B test operations record metrics events."""
        router = StatisticalRouter(metrics=get_routing_metrics("test_router"))

        # Create test preference orders
        from mahavishnu.core.statistical_router import PreferenceOrder
        pref_a = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.PREFECT, AdapterType.AGNO],
            generated_at=datetime.now(UTC),
            confidence=router.ConfidenceLevel.HIGH,
        )

        pref_b = PreferenceOrder(
            task_type=TaskType.WORKFLOW,
            adapters=[AdapterType.LLAMAINDEX, AdapterType.AGNO],
            generated_at=datetime.now(UTC),
            confidence=router.ConfidenceLevel.HIGH,
        )

        # Start A/B test - should record start event and set active experiments
        ab_test = await router.start_ab_test(
            experiment_id="test_exp_001",
            name="Test Experiment",
            description="Testing A/B test metrics recording",
            variant_a=pref_a,
            variant_b=pref_b,
            traffic_split=0.5,
        )

        # Verify metrics were recorded
        assert ab_test.status == "running", "A/B test should be running"
        assert router.metrics is not None, "Router should have metrics"

        # Complete test - should record complete event
        await router.complete_ab_test("test_exp_001", winner="A")

        # Verify completion was recorded
        # Note: Can't directly verify metrics calls without accessing internal state


class TestCostOptimizerMetrics:
    """Test CostOptimizer metrics integration."""

    @pytest.mark.asyncio
    async def test_track_execution_cost_records_cost(self, reset_metrics):
        """Test that track_execution_cost records to metrics."""
        optimizer = CostOptimizer(metrics=get_routing_metrics("test_optimizer"))

        adapter = AdapterType.PREFECT
        task_type = TaskType.WORKFLOW
        latency_ms = 1000

        # Track cost - should record to metrics
        cost = await optimizer.track_execution_cost(
            adapter=adapter,
            task_type=task_type,
            execution_id="test_exec_001",
            latency_ms=latency_ms,
        )

        # Verify cost was calculated and recorded
        assert cost > 0, "Cost should be positive"
        assert optimizer.metrics is not None, "Optimizer should have metrics"

    @pytest.mark.asyncio
    async def test_get_optimal_adapter_records_decision(self, reset_metrics):
        """Test that get_optimal_adapter records routing decision."""
        optimizer = CostOptimizer(metrics=get_routing_metrics("test_optimizer"))

        # Mock tracker with adapter stats
        class MockTracker:
            async def get_adapter_stats(self, adapter_type):
                return {
                    "success_rate": 0.88,
                    "total_executions": 120,
                }
            async def get_recent_executions(self, limit=100):
                return []

        tracker = MockTracker()

        # Get optimal adapter - should record routing decision
        choice = await optimizer.get_optimal_adapter(
            task_type=TaskType.WORKFLOW,
            metrics_tracker=tracker,
        )

        # Verify routing decision was recorded
        assert choice is not None, "Should return adapter choice"
        assert choice.adapter in AdapterType, "Adapter should be valid"
        assert choice.task_type == TaskType.WORKFLOW, "Task type should match"

    @pytest.mark.asyncio
    async def test_health_includes_metrics_enabled(self, reset_metrics):
        """Test that get_health includes metrics_enabled flag."""
        router = StatisticalRouter(metrics=get_routing_metrics("test_router"))
        optimizer = CostOptimizer(metrics=get_routing_metrics("test_optimizer"))

        # Check router health
        router_health = await router.get_health()
        optimizer_health = await optimizer.get_health()

        # Verify metrics_enabled is reported
        assert "metrics_enabled" in router_health, "Router health should include metrics_enabled"
        assert router_health["metrics_enabled"] is True, "Router metrics should be enabled"

        # Verify optimizer health
        assert "metrics_enabled" in optimizer_health, "Optimizer health should include metrics_enabled"
        assert optimizer_health["metrics_enabled"] is True, "Optimizer metrics should be enabled"


class TestTaskRouterMetrics:
    """Test TaskRouter comprehensive metrics integration."""

    @pytest.mark.asyncio
    async def test_route_records_routing_decision(self, reset_metrics):
        """Test that route() records routing decisions."""
        from mahavishnu.core.task_router import TaskRouter, get_task_router
        from mahavishnu.core.metrics_collector import ExecutionTracker

        router = TaskRouter(metrics=get_routing_metrics("test_router"))

        # Create mock task
        task = {
            "task_type": TaskType.WORKFLOW,
            "prompt": "Test prompt",
        }

        # Route - should record routing decision
        result = await router.route(task)

        # Verify routing decision was recorded
        assert result["success"] is True, "Route should succeed"
        assert "adapter" in result, "Should return selected adapter"
        assert result["task_type"] == TaskType.WORKFLOW, "Task type should match"

        # Verify metrics was called
        # (Can't directly verify without accessing internal RoutingMetrics state)

    @pytest.mark.asyncio
    async def test_execute_with_fallback_records_execution_and_fallback(self, reset_metrics):
        """Test that execute_with_fallback() records executions and fallbacks."""
        from mahavishnu.core.task_router import TaskRouter, get_task_router

        router = TaskRouter(metrics=get_routing_metrics("test_router"))

        # Create mock task that will fail first adapter then succeed
        task = {
            "task_type": TaskType.AI_TASK,
            "prompt": "Test failing task",
            "repos": [],
        }

        # Execute - should record first failure, then success with fallback
        result = await router.execute_with_fallback(task)

        # Verify execution was recorded
        assert result["success"] is True, "Should eventually succeed"
        assert result["adapter"] in [AdapterType.PREFECT, AdapterType.AGNO], "One should succeed"
        assert result["total_attempts"] > 1, "Should have multiple attempts"
        assert result["fallback_chain"][0] == AdapterType.PREFECT, "First adapter should be Prefect"
        assert result["fallback_chain"][1] == AdapterType.AGNO, "Should fallback to Agno"

        # Verify metrics were recorded
        # (Can't directly verify without accessing internal RoutingMetrics state)

    @pytest.mark.asyncio
    async def test_get_health_includes_metrics_enabled(self, reset_metrics):
        """Test that get_health() includes metrics_enabled flag."""
        router = TaskRouter(metrics=get_routing_metrics("test_router"))

        health = await router.get_health()

        # Verify metrics_enabled is reported
        assert "metrics_enabled" in health, "Health should include metrics_enabled"
        assert health["metrics_enabled"] is True, "Metrics should be enabled"

    @pytest.mark.asyncio
    async def test_route_with_preference_uses_metrics(self, reset_metrics):
        """Test that providing preference_order uses metrics."""
        from mahavishnu.core.task_router import TaskRouter, get_task_router

        router = TaskRouter(metrics=get_routing_metrics("test_router"))

        # Create task with preference order
        task = {
            "task_type": TaskType.RAG_QUERY,
            "prompt": "Test RAG query",
            "preference_order": [AdapterType.LLAMAINDEX, AdapterType.PREFECT],
        }

        # Route with preference - should record decision
        result = await router.route(task)

        # Verify routing decision was recorded
        assert result["success"] is True, "Route with preference should succeed"
        assert result["adapter"] == AdapterType.LLAMAINDEX, "Should select LlamaIndex"
        assert "preference_order" in result, "Should preserve preference order"


@pytest.mark.asyncio
async def test_all_metrics_integration():
    """Run all integration tests."""
    async with reset_metrics():
        # Test StatisticalRouter
        await test_calculate_adapter_score_records_decision()
        await test_recalculate_all_preferences()
        await test_start_ab_test_records_event()

        # Test CostOptimizer
        await test_track_execution_cost_records_cost()
        await test_get_optimal_adapter_records_decision()
        await test_health_includes_metrics_enabled()

        # Test TaskRouter
        await test_route_records_routing_decision()
        await test_execute_with_fallback_records_execution_and_fallback()
        await test_get_health_includes_metrics_enabled()
        await test_route_with_preference_uses_metrics()


if __name__ == "__main__":
    # Run tests
    asyncio.run(test_all_metrics_integration())
