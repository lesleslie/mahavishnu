"""Tests for routing metrics PostgreSQL persistence.

Tests the RoutingMetricsPersistence class that integrates
ExecutionTracker with Mahavishnu's PostgreSQL storage.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import UTC, datetime
from decimal import Decimal

from mahavishnu.core.metrics_schema import (
    ExecutionRecord,
    AdapterStats,
    AdapterType,
    TaskType,
    ExecutionStatus,
    CostTracking,
    RoutingDecision,
)
from mahavishnu.core.routing_metrics_persistence import (
    RoutingMetricsPersistence,
)


@pytest.fixture
def persistence(test_postgres_dsn: str):
    """Create persistence instance for testing."""
    return RoutingMetricsPersistence(dsn=test_postgres_dsn)


class TestRoutingMetricsPersistence:
    """Test suite for RoutingMetricsPersistence."""

    @pytest.mark.asyncio
    async def test_initialize_and_close(self, persistence):
        """Test initialization and cleanup."""
        await persistence.initialize()
        assert persistence._pool is not None

        health = await persistence.health_check()
        assert health["status"] == "healthy"

        await persistence.close()
        assert persistence._pool is None

    @pytest.mark.asyncio
    async def test_write_and_get_execution(self, persistence):
        """Test writing and retrieving execution records."""
        await persistence.initialize()

        # Create test record
        record = ExecutionRecord(
            execution_id="test-exec-001",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            start_timestamp=datetime.now(UTC).timestamp(),
            end_timestamp=datetime.now(UTC).timestamp(),
            status=ExecutionStatus.SUCCESS,
            latency_ms=150,
            metadata={"test": True},
        )

        # Write record
        await persistence.write_execution(record)

        # Flush to ensure write
        await persistence._flush_executions()

        # Retrieve record
        retrieved = await persistence.get_execution("test-exec-001")

        assert retrieved is not None
        assert retrieved.execution_id == "test-exec-001"
        assert retrieved.adapter == AdapterType.AGNO
        assert retrieved.task_type == TaskType.AI_TASK
        assert retrieved.status == ExecutionStatus.COMPLETED
        assert retrieved.latency_ms == 150

        await persistence.close()

    @pytest.mark.asyncio
    async def test_write_adapter_stats(self, persistence):
        """Test writing adapter statistics."""
        await persistence.initialize()

        # Create test stats
        stats = AdapterStats(
            adapter=AdapterType.PREFECT,
            date="2026-04-02",
            success_rate=0.95,
            total_executions=100,
            avg_latency_ms=200.5,
            sample_size=100,
        )

        # Write stats
        await persistence.write_adapter_stats(stats)

        # Retrieve stats
        retrieved = await persistence.get_adapter_stats(AdapterType.PREFECT, days=1)

        assert len(retrieved) == 1
        assert retrieved[0].adapter == AdapterType.PREFECT
        assert abs(retrieved[0].success_rate - 0.95) < 0.01

        await persistence.close()

    @pytest.mark.asyncio
    async def test_write_routing_decision(self, persistence):
        """Test writing routing decisions."""
        await persistence.initialize()

        # Create test decision
        decision = RoutingDecision(
            decision_id="test-decision-001",
            task_type=TaskType.RAG_QUERY,
            selected_adapter=AdapterType.LLAMAINDEX,
            alternative_adapters=[AdapterType.AGNO],
            reasoning="LlamaIndex best for RAG queries",
            adapter_scores={
                AdapterType.LLAMAINDEX: 0.9,
                AdapterType.AGNO: 0.7,
            },
        )

        # Write decision
        await persistence.write_routing_decision(decision)
        await persistence._flush_decisions()

        await persistence.close()

    @pytest.mark.asyncio
    async def test_write_cost_tracking(self, persistence):
        """Test writing cost tracking records."""
        await persistence.initialize()

        # Create test cost record
        cost = CostTracking(
            execution_id="test-exec-002",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            cost_usd=0.05,
            budget_type="daily",
            budget_limit_usd=10.0,
        )

        # Write cost
        await persistence.write_cost(cost)
        await persistence._flush_costs()

        await persistence.close()

    @pytest.mark.asyncio
    async def test_batch_write_interface(self, persistence):
        """Test ExecutionTracker-compatible batch_write interface."""
        await persistence.initialize()

        # Create test records
        records = [
            ExecutionRecord(
                execution_id=f"batch-test-{i}",
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                start_timestamp=datetime.now(UTC).timestamp(),
                status=ExecutionStatus.SUCCESS,
                latency_ms=100 + i,
            )
            for i in range(10)
        ]

        # Use batch_write interface
        result = await persistence.batch_write(records)

        assert result["status"] == "success"
        assert result["written"] == 10

        await persistence.close()

    @pytest.mark.asyncio
    async def test_get_recent_executions(self, persistence):
        """Test retrieving recent execution records."""
        await persistence.initialize()

        # Write test records
        for i in range(5):
            record = ExecutionRecord(
                execution_id=f"recent-test-{i}",
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                start_timestamp=datetime.now(UTC).timestamp(),
                status=ExecutionStatus.SUCCESS,
                latency_ms=100,
            )
            await persistence.write_execution(record)

        await persistence._flush_executions()

        # Get recent executions
        recent = await persistence.get_recent_executions(
            adapter=AdapterType.PREFECT,
            limit=10,
        )

        assert len(recent) >= 5

        await persistence.close()

    @pytest.mark.asyncio
    async def test_health_check(self, persistence):
        """Test health check endpoint."""
        await persistence.initialize()

        health = await persistence.health_check()

        assert health["status"] == "healthy"
        assert "pool_size" in health
        assert "pending_executions" in health

        await persistence.close()


# Test fixture for PostgreSQL DSN
@pytest.fixture
def test_postgres_dsn():
    """Provide test PostgreSQL DSN."""
    import os
    return os.environ.get(
        "TEST_POSTGRES_DSN",
        "postgresql://les@localhost/mahavishnu"
    )
