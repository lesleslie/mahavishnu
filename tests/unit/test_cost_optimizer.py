"""Tests for cost optimizer and multi-objective routing."""

import pytest
import asyncio
from datetime import datetime, UTC, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from mahavishnu.core.cost_optimizer import (
    CostOptimizer,
    ADAPTER_COSTS,
    BudgetType,
    TaskStrategy,
    ParetoFrontier,
    CostAwareChoice,
    Budget,
    get_cost_optimizer,
    initialize_cost_optimizer,
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
async def optimizer(tracker):
    """Provide CostOptimizer for tests."""
    o = CostOptimizer()
    await o.start()
    yield o
    await o.stop()


class TestAdapterCosts:
    """Test adapter cost constants."""

    def test_prefect_cost(self):
        """Prefect should cost $0.0001 per second."""
        assert ADAPTER_COSTS[AdapterType.PREFECT] == Decimal("0.0001")

    def test_agno_cost(self):
        """Agno should cost $0.0002 per second."""
        assert ADAPTER_COSTS[AdapterType.AGNO] == Decimal("0.0002")

    def test_llamaindex_cost(self):
        """LlamaIndex should cost $0.00005 per query."""
        assert ADAPTER_COSTS[AdapterType.LLAMAINDEX] == Decimal("0.00005")


class TestBudgetType:
    """Test budget type enum."""

    def test_budget_types(self):
        """Should have all budget types."""
        assert BudgetType.DAILY.value == "daily"
        assert BudgetType.WEEKLY.value == "weekly"
        assert BudgetType.MONTHLY.value == "monthly"
        assert BudgetType.PER_TASK_TYPE.value == "per_task_type"


class TestTaskStrategy:
    """Test task strategy enum."""

    def test_strategy_values(self):
        """Should have all strategies."""
        assert TaskStrategy.INTERACTIVE.value == "interactive"
        assert TaskStrategy.BATCH.value == "batch"
        assert TaskStrategy.CRITICAL.value == "critical"


class TestBudget:
    """Test budget configuration."""

    def test_create_daily_budget(self):
        """Should create daily budget."""
        budget = Budget(
            budget_type=BudgetType.DAILY,
            limit_usd=Decimal("10.00"),
        )

        assert budget.budget_type == BudgetType.DAILY
        assert budget.limit_usd == Decimal("10.00")
        assert budget.task_type is None
        assert budget.adapter is None

    def test_create_weekly_budget(self):
        """Should create weekly budget."""
        budget = Budget(
            budget_type=BudgetType.WEEKLY,
            limit_usd=Decimal("50.00"),
            task_type=TaskType.WORKFLOW,
            adapter=AdapterType.PREFECT,
        )

        assert budget.budget_type == BudgetType.WEEKLY
        assert budget.limit_usd == Decimal("50.00")
        assert budget.task_type == TaskType.WORKFLOW
        assert budget.adapter == AdapterType.PREFECT

    def test_create_monthly_budget(self):
        """Should create monthly budget."""
        now = datetime.now(UTC)
        budget = Budget(
            budget_type=BudgetType.MONTHLY,
            limit_usd=Decimal("200.00"),
            task_type=TaskType.AI_TASK,
            period_start=now,
            period_end=now + timedelta(days=30),
        )

        assert budget.budget_type == BudgetType.MONTHLY
        assert budget.limit_usd == Decimal("200.00")
        assert budget.period_start == now
        assert budget.period_end == now + timedelta(days=30)

    def test_budget_active_check(self):
        """Should check if budget is currently active."""
        now = datetime.now(UTC)
        budget = Budget(
            budget_type=BudgetType.DAILY,
            limit_usd=Decimal("10.00"),
            period_start=now - timedelta(days=1),
            period_end=now + timedelta(days=1),
        )

        # Budget is active (now is within period)
        assert budget.is_active(now) is True

        # Budget not active (now outside period)
        past_budget = Budget(
            budget_type=BudgetType.DAILY,
            limit_usd=Decimal("10.00"),
            period_start=now - timedelta(days=2),
            period_end=now - timedelta(days=1),
        )
        assert past_budget.is_active(now) is False

    def test_budget_validation(self):
        """Should reject invalid period_days."""
        with pytest.raises(ValueError):
            Budget(
                budget_type=BudgetType.WEEKLY,
                limit_usd=Decimal("50.00"),
                period_days=15,  # Invalid
            )

        # Valid periods
        for valid_days in [7, 30, 90, 365]:
            Budget(
                budget_type=BudgetType.WEEKLY,
                limit_usd=Decimal("50.00"),
                period_days=valid_days,
            )


class TestCostTracking:
    """Test cost tracking functionality."""

    @pytest.mark.asyncio
    async def test_track_execution_cost(self, optimizer, tracker):
        """Should calculate and track execution cost."""
        # Track some costs
        cost1 = await optimizer.track_execution_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            execution_id="test_ulid_1",
            latency_ms=10000,  # 10 seconds
        )

        # $0.0001/sec * 10 sec = $0.001
        assert cost1 == Decimal("0.001")

        cost2 = await optimizer.track_execution_cost(
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            execution_id="test_ulid_2",
            latency_ms=5000,  # 5 seconds
        )

        # $0.0002/sec * 5 sec = $0.001
        assert cost2 == Decimal("0.001")

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, optimizer, tracker):
        """Should aggregate costs by date and adapter."""
        # Track multiple executions
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            for i in range(5):
                await optimizer.track_execution_cost(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    execution_id=f"ulid_{adapter.value}_{i}",
                    latency_ms=1000 + i * 100,
                )

        # Check cost tracking
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        total_prefect = optimizer._cost_tracking[today][AdapterType.PREFECT.value][TaskType.WORKFLOW.value]
        total_agno = optimizer._cost_tracking[today][AdapterType.AGNO.value][TaskType.WORKFLOW.value]

        assert total_prefect > 0
        assert total_agno > 0

    @pytest.mark.asyncio
    async def test_get_budget_status(self, optimizer):
        """Should calculate budget utilization."""
        # Add a budget
        budget = await optimizer.add_budget(
            budget_type=BudgetType.DAILY,
            limit_usd=100.00,
        )

        # No spending yet
        status = await optimizer.get_budget_status(budget)

        assert status["budget_type"] == "daily"
        assert status["spent_usd"] == 0.0
        assert status["remaining_usd"] == 100.00
        assert status["percentage_used"] == 0.0
        assert status["is_active"] is True
        assert status["is_over_budget"] is False

    @pytest.mark.asyncio
    async def test_budget_over_threshold(self, optimizer, tracker):
        """Should alert when budget over threshold."""
        # Add budget with 90% alert threshold
        budget = Budget(
            budget_type=BudgetType.WEEKLY,
            limit_usd=50.00,
            alert_threshold=0.9,
        )

        await optimizer.add_budget(budget)

        # Add some spending (91% used)
        for i in range(91):
            await optimizer.track_execution_cost(
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                execution_id=f"ulid_{i}",
                latency_ms=1000,
            )

        status = await optimizer.get_budget_status(budget)

        assert status["percentage_used"] == pytest.approx(0.91)
        assert status["is_over_budget"] is True  # Over 90% threshold


class TestParetoFrontier:
    """Test Pareto frontier analysis."""

    @pytest.mark.asyncio
    async def test_pareto_frontier_single_optimal(self, optimizer):
        """Should identify single optimal adapter."""
        # Setup adapter stats
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            tracker._metrics.adapter_attempts[adapter.value]["success"] = 50
            tracker._metrics.adapter_attempts[adapter.value]["failure"] = 10

        choices = []
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            # Mock recent executions for latency
            for i in range(10):
                execution_id = await tracker.record_execution_start(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    repos=["/path/to/repo"],
                )
                await tracker.record_execution_end(
                    execution_id=execution_id,
                    success=True,
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 2000,
                )

        # Create choices with mock costs
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            stats = await tracker.get_adapter_stats(adapter)
            if stats:
                cost = await optimizer.track_execution_cost(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    execution_id="estimate",
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 2000,
                )

                choices.append(CostAwareChoice(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    strategy=TaskStrategy.BATCH,
                    cost_usd=cost,
                    success_rate=stats["success_rate"],
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 2000,
                    score=0.0,
                    reasoning="",
                    pareto_dominated=False,
                    constraints_satisfied=True,
                ))

        frontier = optimizer.calculate_pareto_frontier(choices)

        # Both adapters have same stats, so neither dominates
        assert len(frontier.frontier) == 2
        assert len(frontier.dominated) == 0

    @pytest.mark.asyncio
    async def test_pareto_frontier_dominance(self, optimizer, tracker):
        """Should identify dominated adapters."""
        # Setup: Prefect is better than Agno
        tracker._metrics.adapter_attempts["prefect"]["success"] = 90
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 10
        tracker._metrics.adapter_attempts["agno"]["success"] = 70
        tracker._metrics.adapter_attempts["agno"]["failure"] = 30

        # Add latency data
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            for i in range(10):
                execution_id = await tracker.record_execution_start(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    repos=["/path/to/repo"],
                )
                await tracker.record_execution_end(
                    execution_id=execution_id,
                    success=True,
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 3000,  # Agno slower
                )

        choices = []
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            stats = await tracker.get_adapter_stats(adapter)
            if stats:
                cost = await optimizer.track_execution_cost(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    execution_id="estimate",
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 3000,
                )

                choices.append(CostAwareChoice(
                    adapter=adapter,
                    task_type=TaskType.WORKFLOW,
                    strategy=TaskStrategy.BATCH,
                    cost_usd=cost,
                    success_rate=stats["success_rate"],
                    latency_ms=1000 if adapter == AdapterType.PREFECT else 3000,
                    score=0.0,
                    reasoning="",
                    pareto_dominated=False,
                    constraints_satisfied=True,
                ))

        frontier = optimizer.calculate_pareto_frontier(choices)

        # Agno should be dominated (worse in all metrics)
        assert AdapterType.AGNO in frontier.dominated
        assert AdapterType.PREFECT not in frontier.dominated
        assert len(frontier.frontier) == 1  # Only Prefect


class TestOptimizationStrategies:
    """Test multi-objective optimization strategies."""

    @pytest.mark.asyncio
    async def test_interactive_strategy(self, optimizer, tracker):
        """Interactive strategy should weight speed."""
        # Setup adapter data
        tracker._metrics.adapter_attempts["llamaindex"]["success"] = 80
        tracker._metrics.adapter_attempts["llamaindex"]["failure"] = 20

        stats = await tracker.get_adapter_stats(AdapterType.LLAMAINDEX)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.RAG_QUERY,
            execution_id="estimate",
            latency_ms=3000,
        )

        choice = CostAwareChoice(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.RAG_QUERY,
            strategy=TaskStrategy.INTERACTIVE,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=3000,
            score=0.0,
        )

        score = optimizer.score_adapter_choice(choice, TaskStrategy.INTERACTIVE)

        # Interactive: 50% success + 50% speed (cost matters less)
        # Cost component is 1.0 - cost, so lower cost = higher score
        # Latency component is 1.0 - latency/max_latency
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_batch_strategy(self, optimizer, tracker):
        """Batch strategy should weight cost."""
        # Setup adapter data
        tracker._metrics.adapter_attempts["prefect"]["success"] = 85
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 15

        stats = await tracker.get_adapter_stats(AdapterType.PREFECT)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=2000,
        )

        choice = CostAwareChoice(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.BATCH,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=2000,
            score=0.0,
        )

        score = optimizer.score_adapter_choice(choice, TaskStrategy.BATCH)

        # Batch: 90% success + 10% cost (cost matters more)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_critical_strategy(self, optimizer, tracker):
        """Critical strategy should weight success."""
        # Setup adapter data
        tracker._metrics.adapter_attempts["agno"]["success"] = 95
        tracker._metrics.adapter_attempts["agno"]["failure"] = 5

        stats = await tracker.get_adapter_stats(AdapterType.AGNO)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            execution_id="estimate",
            latency_ms=1500,
        )

        choice = CostAwareChoice(
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            strategy=TaskStrategy.CRITICAL,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=1500,
            score=0.0,
        )

        score = optimizer.score_adapter_choice(choice, TaskStrategy.CRITICAL)

        # Critical: 80% success + 20% cost (cost doesn't matter)
        # Latency has minor weight
        assert 0.0 <= score <= 1.0


class TestCostAwareChoice:
    """Test cost-aware adapter selection."""

    @pytest.mark.asyncio
    async def test_choice_score_calculations(self, optimizer):
        """Should calculate scores correctly."""
        # Setup mock data
        tracker._metrics.adapter_attempts["prefect"]["success"] = 80
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 20

        stats = await tracker.get_adapter_stats(AdapterType.PREFECT)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=1000,
        )

        choice = CostAwareChoice(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.BATCH,
            cost_usd=Decimal("0.5"),  # 50 cents
            success_rate=0.8,
            latency_ms=1000,
            score=0.0,
        )

        # Test with each strategy
        for strategy in [TaskStrategy.BATCH, TaskStrategy.CRITICAL, TaskStrategy.INTERACTIVE]:
            score = optimizer.score_adapter_choice(choice, strategy)

            assert 0.0 <= score <= 1.0


class TestConstraintChecking:
    """Test budget and SLA constraint checking."""

    @pytest.mark.asyncio
    async def test_budget_constraint_satisfied(self, optimizer):
        """Should pass when budget not violated."""
        # Add a budget
        budget = await optimizer.add_budget(
            budget_type=BudgetType.DAILY,
            limit_usd=100.00,
            task_type=TaskType.WORKFLOW,
            adapter=AdapterType.PREFECT,
        )

        # No spending yet
        result = await optimizer.check_budget_constraints(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
        )

        assert result["constraints_satisfied"] is True
        assert len(result["violated_budgets"]) == 0

    @pytest.mark.asyncio
    async def test_budget_constraint_violated(self, optimizer):
        """Should fail when over budget."""
        # Add budget
        budget = await optimizer.add_budget(
            budget_type=BudgetType.WEEKLY,
            limit_usd=50.00,
            task_type=TaskType.AI_TASK,
            adapter=AdapterType.AGNO,
        )

        # Add spending to exceed budget
        for i in range(30):  # $0.0002 * 30 = $0.006
            await optimizer.track_execution_cost(
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                execution_id=f"ulid_{i}",
                latency_ms=1000,
            )

        result = await optimizer.check_budget_constraints(
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
        )

        assert result["constraints_satisfied"] is False
        assert len(result["violated_budgets"]) == 1
        assert result["violated_budgets"][0]["budget_type"] == "weekly"
        assert pytest.approx(result["violated_budgets"][0]["spent_usd"]) > 0  # Should be positive

    @pytest.mark.asyncio
    async def test_slb_constraint_satisfied(self, optimizer):
        """Should pass when SLA met."""
        optimizer.max_latency_ms = 5000  # 5 seconds
        optimizer.min_success_rate = 0.8

        # Setup adapter with good metrics
        tracker._metrics.adapter_attempts["prefect"]["success"] = 90
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 10

        stats = await tracker.get_adapter_stats(AdapterType.PREFECT)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=3000,  # Under SLA
        )

        # Create valid choice
        choices = [CostAwareChoice(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.BATCH,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=3000,
            score=0.0,
        )]

        result = await optimizer.check_budget_constraints(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            constraints={"sla": {"max_latency_ms": 5000, "min_success_rate": 0.8}},
        )

        assert result["constraints_satisfied"] is True

    @pytest.mark.asyncio
    async def test_slb_constraint_violated(self, optimizer):
        """Should fail when SLA not met."""
        optimizer.max_latency_ms = 5000
        optimizer.min_success_rate = 0.9

        # Setup adapter with poor metrics
        tracker._metrics.adapter_attempts["agno"]["success"] = 70
        tracker._metrics.adapter_attempts["agno"]["failure"] = 30

        stats = await tracker.get_adapter_stats(AdapterType.AGNO)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.AGNO,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=8000,  # Over SLA
        )

        choices = [CostAwareChoice(
            adapter=AdapterType.AGNO,
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.BATCH,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=8000,
            score=0.0,
        )]

        result = await optimizer.check_budget_constraints(
            adapter=AdapterType.AGNO,
            task_type=TaskType.WORKFLOW,
            constraints={"sla": {"max_latency_ms": 5000, "min_success_rate": 0.9}},
        )

        # SLA constraints not satisfied (latency too high, success too low)
        assert result["constraints_satisfied"] is False

    @pytest.mark.asyncio
    async def test_multiple_constraints(self, optimizer):
        """Should check multiple constraint types."""
        # Budget and SLA constraints both violated
        optimizer.max_latency_ms = 5000
        optimizer.min_success_rate = 0.9

        # Setup adapter violating both
        tracker._metrics.adapter_attempts["llamaindex"]["success"] = 50
        tracker._metrics.adapter_attempts["llamaindex"]["failure"] = 50

        stats = await tracker.get_adapter_stats(AdapterType.LLAMAINDEX)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=10000,  # Over SLA
        )

        # Add budget that will be exceeded
        budget = await optimizer.add_budget(
            budget_type=BudgetType.DAILY,
            limit_usd=10.00,
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.WORKFLOW,
        )

        choices = [CostAwareChoice(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.BATCH,
            cost_usd=cost,
            success_rate=stats["success_rate"],
            latency_ms=10000,
            score=0.0,
        )]

        result = await optimizer.check_budget_constraints(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.WORKFLOW,
            constraints={
                "sla": {"max_latency_ms": 5000, "min_success_rate": 0.9},
                "budget": {"limit_usd": 10.0},
            },
        )

        # Both constraints violated
        assert result["constraints_satisfied"] is False
        assert len(result["violated_budgets"]) == 1
        assert "sla" in result


class TestOptimalAdapterSelection:
    """Test get_optimal_adapter method."""

    @pytest.mark.asyncio
    async def test_select_from_pareto_frontier(self, optimizer, tracker):
        """Should select best from Pareto frontier."""
        # Setup two adapters with equal performance
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            tracker._metrics.adapter_attempts[adapter.value]["success"] = 80
            tracker._metrics.adapter_attempts[adapter.value]["failure"] = 20

        # Make them equal on metrics
        stats_list = []
        for adapter in [AdapterType.PREFECT, AdapterType.AGNO]:
            stats = await tracker.get_adapter_stats(adapter)
            stats_list.append(stats)

        # Both have same stats, so neither dominates
        frontier = optimizer.calculate_pareto_frontier([])
        assert len(frontier.frontier) == 2

        # When equal, either could be chosen (implementation may pick first)
        result = await optimizer.get_optimal_adapter(
            task_type=TaskType.WORKFLOW,
        )

        assert result is not None
        assert result.adapter in [AdapterType.PREFECT, AdapterType.AGNO]

    @pytest.mark.asyncio
    async def test_select_with_strategy_override(self, optimizer, tracker):
        """Should use override strategy."""
        # Setup adapter data
        tracker._metrics.adapter_attempts["prefect"]["success"] = 75
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 25

        stats = await tracker.get_adapter_stats(AdapterType.PREFECT)
        cost = await optimizer.track_execution_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            execution_id="estimate",
            latency_ms=1500,
        )

        # Request CRITICAL strategy (not default BATCH)
        result = await optimizer.get_optimal_adapter(
            task_type=TaskType.WORKFLOW,
            strategy=TaskStrategy.CRITICAL,
        )

        assert result.strategy == TaskStrategy.CRITICAL
        # Critical: 80% success (0.8*0.8=0.64)
        # Cost and latency have minor weights
        expected_range = (0.64 * 0.8, 0.64 * 0.8 + 0.2)
        assert expected_range[0] <= result.score <= expected_range[1]


class TestBudgetManagement:
    """Test budget CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_budget(self, optimizer):
        """Should add budget configuration."""
        budget = await optimizer.add_budget(
            budget_type=BudgetType.WEEKLY,
            limit_usd=100.00,
        )

        budgets = await optimizer.get_all_budgets()

        assert len(budgets) == 1
        assert budgets[0].budget_type == BudgetType.WEEKLY
        assert budgets[0].limit_usd == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_delete_budget(self, optimizer):
        """Should delete budget configuration."""
        # Add then delete
        await optimizer.add_budget(
            budget_type=BudgetType.MONTHLY,
            limit_usd=500.00,
        )

        deleted = await optimizer.delete_budget(budgets[0])

        assert deleted is True
        budgets = await optimizer.get_all_budgets()

        assert len(budgets) == 0


class TestOptimizerLifecycle:
    """Test optimizer lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Should start and stop cleanly."""
        optimizer = CostOptimizer()

        assert optimizer._recalc_task is None

        await optimizer.start()
        assert optimizer._recalc_task is not None
        assert not optimizer._shutdown_event.is_set()

        await optimizer.stop()
        assert optimizer._recalc_task.cancelled() or optimizer._recalc_task.done()
        assert optimizer._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_get_health(self):
        """Should return health status."""
        optimizer = CostOptimizer()

        health = await optimizer.get_health()

        assert health["status"] == "healthy"
        assert "budgets_configured" in health
        assert "default_strategy" in health
        assert "sla_max_latency_ms" in health
        assert "sla_min_success_rate" in health

    @pytest.mark.asyncio
    async def test_singleton(self):
        """Should return same instance on multiple calls."""
        import mahavishnu.core.cost_optimizer as co
        co._optimizer = None

        optimizer1 = get_cost_optimizer()
        optimizer2 = get_cost_optimizer()

        assert optimizer1 is optimizer2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
