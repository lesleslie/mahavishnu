"""PostgreSQL persistence layer for adaptive routing metrics.

This module provides PostgreSQL-backed storage for the ExecutionTracker,
replacing the Dhara-based storage assumptions with Mahavishnu's consolidated
PostgreSQL cluster.

Design:
- Implements storage_client interface expected by ExecutionTracker
- Uses asyncpg for efficient async database operations
- Batch writes for performance optimization
- Automatic aggregation and statistics calculation

Architecture: docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md
Completes: PLAN_INDEX.md Item 7
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import Any

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

import contextlib

from mahavishnu.core.metrics_schema import (
    AdapterStats,
    AdapterType,
    CostTracking,
    ExecutionRecord,
    ExecutionStatus,
    RoutingDecision,
    TaskType,
)

logger = logging.getLogger(__name__)


class RoutingMetricsPersistence:
    """PostgreSQL persistence layer for routing metrics.

    This class implements the storage_client interface expected by
    ExecutionTracker, persisting metrics to the `metrics` schema
    in Mahavishnu's PostgreSQL cluster.

    Usage:
        persistence = RoutingMetricsPersistence(dsn="postgresql://...")
        tracker = ExecutionTracker(storage_client=persistence)
        await persistence.initialize()
    """

    def __init__(self, dsn: str, batch_size: int = 100, batch_timeout_ms: int = 5000):
        """Initialize persistence layer.

        Args:
            dsn: PostgreSQL connection string
            batch_size: Max records before forcing batch write
            batch_timeout_ms: Max time before forcing batch write
        """
        if asyncpg is None:
            raise ImportError("asyncpg required. Install with: pip install asyncpg")

        self.dsn = dsn
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self._pool: asyncpg.Pool | None = None
        self._pending_executions: list[ExecutionRecord] = []
        self._pending_costs: list[CostTracking] = []
        self._pending_decisions: list[RoutingDecision] = []
        self._write_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        if self._pool is not None:
            logger.warning("RoutingMetricsPersistence already initialized")
            return

        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=30.0,
        )

        # Start periodic flush task
        self._shutdown_event.clear()
        self._flush_task = asyncio.create_task(self._periodic_flush())

        logger.info("RoutingMetricsPersistence initialized")

    async def close(self) -> None:
        """Close database connection pool."""
        logger.info("Closing RoutingMetricsPersistence...")

        # Stop flush task
        if self._flush_task and not self._flush_task.done():
            self._shutdown_event.set()
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        # Flush pending writes
        async with self._write_lock:
            await self._flush_all_pending()

        # Close pool
        if self._pool:
            await self._pool.close()
            self._pool = None

        logger.info("RoutingMetricsPersistence closed")

    async def _periodic_flush(self) -> None:
        """Periodically flush pending writes."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.batch_timeout_ms / 1000)
                async with self._write_lock:
                    await self._flush_all_pending()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic flush error: {e}", exc_info=True)

    async def _flush_all_pending(self) -> None:
        """Flush all pending records to database."""
        if self._pending_executions:
            await self._flush_executions()
        if self._pending_costs:
            await self._flush_costs()
        if self._pending_decisions:
            await self._flush_decisions()

    # =========================================================================
    # Execution Records
    # =========================================================================

    async def write_execution(self, record: ExecutionRecord) -> None:
        """Write a single execution record.

        Args:
            record: Execution record to persist
        """
        async with self._write_lock:
            self._pending_executions.append(record)

            if len(self._pending_executions) >= self.batch_size:
                await self._flush_executions()

    async def write_executions_batch(self, records: list[ExecutionRecord]) -> None:
        """Write multiple execution records.

        Args:
            records: List of execution records to persist
        """
        async with self._write_lock:
            self._pending_executions.extend(records)

            if len(self._pending_executions) >= self.batch_size:
                await self._flush_executions()

    async def _flush_executions(self) -> int:
        """Flush pending execution records to database.

        Returns:
            Number of records written
        """
        if not self._pending_executions or not self._pool:
            return 0

        records = self._pending_executions.copy()
        self._pending_executions.clear()

        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO metrics.execution_records (
                        execution_id, adapter, task_type, start_timestamp, end_timestamp,
                        status, latency_ms, error_type, error_message, cost_usd, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (execution_id) DO UPDATE SET
                        end_timestamp = EXCLUDED.end_timestamp,
                        status = EXCLUDED.status,
                        latency_ms = EXCLUDED.latency_ms,
                        error_type = EXCLUDED.error_type,
                        error_message = EXCLUDED.error_message,
                        cost_usd = EXCLUDED.cost_usd
                    """,
                    [
                        (
                            r.execution_id,
                            r.adapter.value,
                            r.task_type.value,
                            datetime.fromtimestamp(r.start_timestamp, UTC),
                            datetime.fromtimestamp(r.end_timestamp, UTC)
                            if r.end_timestamp
                            else None,
                            r.status.value,
                            r.latency_ms,
                            r.error_type,
                            r.error_message,
                            Decimal(str(r.cost_usd)) if r.cost_usd is not None else None,
                            r.metadata,
                        )
                        for r in records
                    ],
                )

            logger.debug(f"Wrote {len(records)} execution records to PostgreSQL")
            return len(records)

        except Exception as e:
            logger.error(f"Failed to write execution records: {e}")
            # Re-queue failed records
            self._pending_executions.extend(records)
            return 0

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        """Get a single execution record by ID.

        Args:
            execution_id: Execution identifier

        Returns:
            Execution record or None
        """
        if not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM metrics.execution_records WHERE execution_id = $1
                    """,
                    execution_id,
                )

                if row:
                    return self._row_to_execution_record(row)
                return None

        except Exception as e:
            logger.error(f"Failed to get execution {execution_id}: {e}")
            return None

    async def get_recent_executions(
        self,
        adapter: AdapterType | None = None,
        task_type: TaskType | None = None,
        limit: int = 100,
    ) -> list[ExecutionRecord]:
        """Get recent execution records.

        Args:
            adapter: Optional adapter filter
            task_type: Optional task type filter
            limit: Maximum records to return

        Returns:
            List of execution records
        """
        if not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                query = """
                    SELECT * FROM metrics.execution_records
                    WHERE ($1::text IS NULL OR adapter = $1)
                    AND ($2::text IS NULL OR task_type = $2)
                    ORDER BY created_at DESC
                    LIMIT $3
                """
                rows = await conn.fetch(
                    query,
                    adapter.value if adapter else None,
                    task_type.value if task_type else None,
                    limit,
                )

                return [self._row_to_execution_record(r) for r in rows]

        except Exception as e:
            logger.error(f"Failed to get recent executions: {e}")
            return []

    def _row_to_execution_record(self, row: asyncpg.Record) -> ExecutionRecord:
        """Convert database row to ExecutionRecord."""
        return ExecutionRecord(
            execution_id=row["execution_id"],
            adapter=AdapterType(row["adapter"]),
            task_type=TaskType(row["task_type"]),
            start_timestamp=row["start_timestamp"].timestamp(),
            end_timestamp=row["end_timestamp"].timestamp() if row["end_timestamp"] else None,
            status=ExecutionStatus(row["status"]),
            latency_ms=row["latency_ms"],
            error_type=row["error_type"],
            error_message=row["error_message"],
            cost_usd=float(row["cost_usd"]) if row["cost_usd"] else None,
            metadata=dict(row["metadata"]) if row["metadata"] else {},
        )

    # =========================================================================
    # Adapter Statistics
    # =========================================================================

    async def write_adapter_stats(self, stats: AdapterStats) -> None:
        """Write adapter statistics.

        Args:
            stats: Adapter statistics to persist
        """
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO metrics.adapter_stats (
                        adapter, stat_date, success_rate, total_executions, avg_latency_ms,
                        p50_latency_ms, p95_latency_ms, p99_latency_ms, error_counts,
                        cost_total_usd, uptime_percentage, sample_size, confidence_interval
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (adapter, stat_date) DO UPDATE SET
                        success_rate = EXCLUDED.success_rate,
                        total_executions = EXCLUDED.total_executions,
                        avg_latency_ms = EXCLUDED.avg_latency_ms,
                        p50_latency_ms = EXCLUDED.p50_latency_ms,
                        p95_latency_ms = EXCLUDED.p95_latency_ms,
                        p99_latency_ms = EXCLUDED.p99_latency_ms,
                        error_counts = EXCLUDED.error_counts,
                        cost_total_usd = EXCLUDED.cost_total_usd,
                        uptime_percentage = EXCLUDED.uptime_percentage,
                        sample_size = EXCLUDED.sample_size,
                        confidence_interval = EXCLUDED.confidence_interval,
                        updated_at = NOW()
                    """,
                    stats.adapter.value,
                    datetime.strptime(stats.date, "%Y-%m-%d").date()
                    if isinstance(stats.date, str)
                    else stats.date,
                    Decimal(str(stats.success_rate)),
                    stats.total_executions,
                    Decimal(str(stats.avg_latency_ms)) if stats.avg_latency_ms else None,
                    Decimal(str(stats.p50_latency_ms)) if stats.p50_latency_ms else None,
                    Decimal(str(stats.p95_latency_ms)) if stats.p95_latency_ms else None,
                    Decimal(str(stats.p99_latency_ms)) if stats.p99_latency_ms else None,
                    stats.error_counts,
                    Decimal(str(stats.cost_total_usd)) if stats.cost_total_usd else None,
                    stats.uptime_percentage,
                    stats.sample_size,
                    Decimal(str(stats.confidence_interval)) if stats.confidence_interval else None,
                )

            logger.debug(f"Wrote adapter stats for {stats.adapter.value} on {stats.date}")

        except Exception as e:
            logger.error(f"Failed to write adapter stats: {e}")

    async def get_adapter_stats(
        self,
        adapter: AdapterType,
        days: int = 7,
    ) -> list[AdapterStats]:
        """Get adapter statistics for the last N days.

        Args:
            adapter: Adapter type
            days: Number of days to retrieve

        Returns:
            List of adapter statistics
        """
        if not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT * FROM metrics.adapter_stats
                    WHERE adapter = $1
                    AND stat_date >= CURRENT_DATE - INTERVAL '{days} days'
                    ORDER BY stat_date DESC
                    """,
                    adapter.value,
                )

                return [self._row_to_adapter_stats(r) for r in rows]

        except Exception as e:
            logger.error(f"Failed to get adapter stats: {e}")
            return []

    def _row_to_adapter_stats(self, row: asyncpg.Record) -> AdapterStats:
        """Convert database row to AdapterStats."""
        return AdapterStats(
            adapter=AdapterType(row["adapter"]),
            date=str(row["stat_date"]),
            success_rate=float(row["success_rate"]),
            total_executions=row["total_executions"],
            avg_latency_ms=float(row["avg_latency_ms"]) if row["avg_latency_ms"] else None,
            p50_latency_ms=float(row["p50_latency_ms"]) if row["p50_latency_ms"] else None,
            p95_latency_ms=float(row["p95_latency_ms"]) if row["p95_latency_ms"] else None,
            p99_latency_ms=float(row["p99_latency_ms"]) if row["p99_latency_ms"] else None,
            error_counts=dict(row["error_counts"]) if row["error_counts"] else {},
            cost_total_usd=float(row["cost_total_usd"]) if row["cost_total_usd"] else None,
            uptime_percentage=float(row["uptime_percentage"]) if row["uptime_percentage"] else None,
            sample_size=row["sample_size"],
            confidence_interval=float(row["confidence_interval"])
            if row["confidence_interval"]
            else None,
        )

    # =========================================================================
    # Routing Decisions
    # =========================================================================

    async def write_routing_decision(self, decision: RoutingDecision) -> None:
        """Write a routing decision.

        Args:
            decision: Routing decision to persist
        """
        async with self._write_lock:
            self._pending_decisions.append(decision)

            if len(self._pending_decisions) >= self.batch_size:
                await self._flush_decisions()

    async def _flush_decisions(self) -> int:
        """Flush pending routing decisions to database."""
        if not self._pending_decisions or not self._pool:
            return 0

        decisions = self._pending_decisions.copy()
        self._pending_decisions.clear()

        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO metrics.routing_decisions (
                        decision_id, task_type, selected_adapter, alternative_adapters,
                        reasoning, adapter_scores, constraints, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    [
                        (
                            d.decision_id,
                            d.task_type.value,
                            d.selected_adapter.value,
                            [a.value for a in d.alternative_adapters],
                            d.reasoning,
                            dict(d.adapter_scores.items()),
                            d.constraints,
                            datetime.fromtimestamp(d.timestamp, UTC),
                        )
                        for d in decisions
                    ],
                )

            logger.debug(f"Wrote {len(decisions)} routing decisions to PostgreSQL")
            return len(decisions)

        except Exception as e:
            logger.error(f"Failed to write routing decisions: {e}")
            self._pending_decisions.extend(decisions)
            return 0

    # =========================================================================
    # Cost Tracking
    # =========================================================================

    async def write_cost(self, cost: CostTracking) -> None:
        """Write a cost tracking record.

        Args:
            cost: Cost tracking to persist
        """
        async with self._write_lock:
            self._pending_costs.append(cost)

            if len(self._pending_costs) >= self.batch_size:
                await self._flush_costs()

    async def _flush_costs(self) -> int:
        """Flush pending cost records to database."""
        if not self._pending_costs or not self._pool:
            return 0

        costs = self._pending_costs.copy()
        self._pending_costs.clear()

        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO metrics.cost_tracking (
                        execution_id, adapter, task_type, cost_usd, budget_type, budget_limit_usd
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (
                            c.execution_id,
                            c.adapter.value,
                            c.task_type.value,
                            Decimal(str(c.cost_usd)),
                            c.budget_type,
                            Decimal(str(c.budget_limit_usd)) if c.budget_limit_usd else None,
                        )
                        for c in costs
                    ],
                )

            logger.debug(f"Wrote {len(costs)} cost records to PostgreSQL")
            return len(costs)

        except Exception as e:
            logger.error(f"Failed to write cost records: {e}")
            self._pending_costs.extend(costs)
            return 0

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> dict[str, Any]:
        """Check health of persistence layer.

        Returns:
            Health status dictionary
        """
        if not self._pool:
            return {
                "status": "unhealthy",
                "error": "Pool not initialized",
            }

        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")

                return {
                    "status": "healthy",
                    "pending_executions": len(self._pending_executions),
                    "pending_costs": len(self._pending_costs),
                    "pending_decisions": len(self._pending_decisions),
                    "pool_size": self._pool.get_size(),
                    "pool_idle": self._pool.get_idle_size(),
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    # =========================================================================
    # Storage Client Interface (for ExecutionTracker compatibility)
    # =========================================================================

    async def batch_write(self, records: list[ExecutionRecord]) -> dict[str, Any]:
        """Batch write interface for ExecutionTracker compatibility.

        Args:
            records: List of execution records

        Returns:
            Write result dictionary
        """
        await self.write_executions_batch(records)
        return {"status": "success", "written": len(records)}


# =============================================================================
# Factory Function
# =============================================================================

_persistence: RoutingMetricsPersistence | None = None


def get_routing_metrics_persistence() -> RoutingMetricsPersistence | None:
    """Get global persistence instance."""
    return _persistence


async def initialize_routing_metrics_persistence(
    dsn: str,
    batch_size: int = 100,
    force_recreate: bool = False,
) -> RoutingMetricsPersistence:
    """Initialize global persistence instance.

    Args:
        dsn: PostgreSQL connection string
        batch_size: Batch size for writes
        force_recreate: If True, create new instance even if one exists

    Returns:
        Initialized persistence instance
    """
    global _persistence

    if force_recreate and _persistence:
        await _persistence.close()
        _persistence = None

    if _persistence is None:
        _persistence = RoutingMetricsPersistence(dsn=dsn, batch_size=batch_size)
        await _persistence.initialize()

    return _persistence


__all__ = [
    "RoutingMetricsPersistence",
    "get_routing_metrics_persistence",
    "initialize_routing_metrics_persistence",
]
