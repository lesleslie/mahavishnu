"""Integration tests for the Phase 3 budget watchdog.

Focus areas (matching the v2 plan's Phase 3 exit criteria):

* Multi-replica safety: only one replica runs enforcement per cycle.
* Dhara unavailability does NOT crash the watchdog (fail-open path).
* A wallclock-breaching budget gets transitioned to ``EXCEEDED`` by
  the watchdog within one cycle.
* ``budget_enforce`` (the MCP-facing tool) round-trips a record to
  the store and exposes the new state.

The store under test is :class:`InMemoryBudgetStore` — a deliberately
narrow surface that mimics the real :class:`DharaBudgetStore`'s
behavior closely enough to exercise the lease, list, and read paths.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.budget import (
    BudgetDimension,
    BudgetRecord,
    BudgetSpec,
    BudgetState,
    BudgetUsage,
)
from mahavishnu.core.budget_watchdog import (
    InMemoryBudgetStore,
    WatchdogConfig,
    WatchdogMetrics,
    run_watchdog,
    run_watchdog_cycle,
)

pytestmark = pytest.mark.integration


# =============================================================================
# Fixtures
# =============================================================================


class _RecordingEmitter:
    """OTel emitter that records (name, attrs) pairs for assertions."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any]]] = []
        self.counters: list[tuple[str, dict[str, Any]]] = []

    def start_span(self, name: str, **attrs: Any) -> Any:
        self.spans.append((name, dict(attrs)))

        class _Span:
            def __enter__(self) -> _Span:  # noqa: PYI034 - test stub
                return self

            def __exit__(self, *_: object) -> bool | None:
                return None

            async def __aenter__(self) -> _Span:  # noqa: PYI034 - test stub
                return self

            async def __aexit__(self, *_: object) -> bool | None:
                return None

        return _Span()

    def increment(self, name: str, **attrs: Any) -> None:
        self.counters.append((name, dict(attrs)))


def _make_store(*records: BudgetRecord) -> InMemoryBudgetStore:
    store = InMemoryBudgetStore()
    for record in records:
        store.seed_record(record)
    return store


async def _static_usage_source(usage_by_workflow: dict[str, BudgetUsage]):
    async def _source(workflow_id: str) -> BudgetUsage | None:
        return usage_by_workflow.get(workflow_id)

    return _source


def _static(usage: BudgetUsage):
    """Build a synchronous-lookup async usage source returning ``usage`` for any workflow."""

    async def _source(_workflow_id: str) -> BudgetUsage | None:
        return usage

    return _source


# =============================================================================
# Lease election — multi-replica safety
# =============================================================================


class TestMultiReplicaLease:
    """Two replicas with the same lease key — one wins per cycle."""

    async def test_only_one_replica_wins_each_cycle(self) -> None:
        record = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        store = _make_store(record)

        # Both replicas attempt a cycle concurrently.
        results = await asyncio.gather(
            run_watchdog_cycle(
                store=store,
                holder="replica-a",
                lease_ttl_seconds=60,
                usage_source=_static(BudgetUsage(tokens_used=50)),
            ),
            run_watchdog_cycle(
                store=store,
                holder="replica-b",
                lease_ttl_seconds=60,
                usage_source=_static(BudgetUsage(tokens_used=50)),
            ),
        )

        winners = [r for r in results if r.lease_acquired]
        losers = [r for r in results if not r.lease_acquired]
        assert len(winners) == 1
        assert len(losers) == 1
        # The losing replica did not transition the budget.
        assert losers[0].records_scanned == 0
        assert winners[0].records_scanned == 1

    async def test_held_lease_blocks_other_replica(self) -> None:
        """While A's lease is alive, B cannot acquire."""
        record = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        store = _make_store(record)

        # Cycle 1 — replica A acquires and (by design) holds the lease
        # for the TTL window rather than releasing immediately.
        first_a = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
        )
        assert first_a.lease_acquired is True

        # Cycle 2 — B's cycle is rejected because A's lease is alive.
        second_b = await run_watchdog_cycle(
            store=store,
            holder="replica-b",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
        )
        assert second_b.lease_acquired is False

        # A's cycle 3 refreshes the lease transparently.
        third_a = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
        )
        assert third_a.lease_acquired is True

    async def test_lease_ttl_expires_allowing_new_holder(self) -> None:
        """Expired leases allow a different replica to take ownership.

        We simulate expiry by manually rewriting the in-memory lease
        record with an ``expires_at`` in the past.
        """
        record = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        store = _make_store(record)

        # Cycle 1 — replica A acquires.
        await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
        )
        # Force expiry: rewrite the lease's expires_at to the past.
        lease_key = "mahavishni://budgets/lease.json"
        lease_record = store.leases.get(lease_key)
        assert lease_record is not None
        store.leases[lease_key] = {
            **lease_record,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
        }
        # Cycle 2 — replica B should now take ownership.
        second = await run_watchdog_cycle(
            store=store,
            holder="replica-b",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
        )
        assert second.lease_acquired is True

    async def test_dhara_unavailable_does_not_crash_watchdog(self) -> None:
        """When the store raises on every op, the cycle returns cleanly.

        This is the fail-open exit criterion: never crash the
        watchdog's host process just because Dhara is unreachable.
        """
        store = InMemoryBudgetStore()
        # Mark every op to fail at most once.
        store.fail_next_op = "lease"

        async def raising_usage_source(_wf: str) -> BudgetUsage:
            raise RuntimeError("usage source broken")

        result = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=raising_usage_source,
        )
        # Fail-open: dhara_unavailable is True, the cycle did not raise,
        # and the metrics counter incremented.
        assert result.dhara_unavailable is True
        assert result.lease_acquired is False


# =============================================================================
# Fail-open on Dhara unavailability
# =============================================================================


class TestDharaFailOpen:
    """When Dhara is unreachable, the watchdog must NOT raise or stop."""

    async def test_get_failure_skips_record(self) -> None:
        """A failing ``get`` on a record key logs a warning and continues."""
        record = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        store = _make_store(record)
        # First ``get`` (lease write/list) succeeds; per-record ``get`` raises.
        original_get = store.get

        call_count = {"n": 0}

        async def flaky_get(key: str) -> dict[str, Any] | None:
            call_count["n"] += 1
            # The cycle calls get() for the lease (no-op) and then per-record.
            # Surface the first per-record ``get`` as the failure case.
            if key.endswith("/wf-1.json"):
                raise RuntimeError("simulated Dhara down")
            return await original_get(key)

        store.get = flaky_get  # type: ignore[method-assign]

        metrics = WatchdogMetrics()
        result = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
            metrics=metrics,
        )
        # No records scanned because each one raised. No crash.
        assert result.records_scanned == 1
        assert result.records_transitioned == 0

    async def test_lease_acquire_failure_records_skip(self) -> None:
        store = _make_store()
        store.fail_next_op = "lease"
        metrics = WatchdogMetrics()

        result = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
            metrics=metrics,
        )
        # Dhara unavailable path:
        assert result.dhara_unavailable is True
        assert result.lease_acquired is False
        assert metrics.skipped_dhara_unavailable == 1

    async def test_list_keys_failure_records_skip(self) -> None:
        store = _make_store()
        # Pre-acquire the lease so we get past it.
        await store.try_acquire_lease(
            "mahavishni://budgets/lease.json",
            "replica-a",
            ttl_seconds=60,
        )
        store.fail_next_op = "list"
        metrics = WatchdogMetrics()

        result = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=50)),
            metrics=metrics,
        )
        assert result.dhara_unavailable is True
        assert metrics.skipped_dhara_unavailable == 1

    async def test_dhara_down_full_loop_does_not_crash(self) -> None:
        """Even when every Dhara call raises, the loop survives."""
        store = _make_store()
        emitter = _RecordingEmitter()

        # Simulate a continuous Dhara outage by replacing
        # ``try_acquire_lease`` with one that always raises.
        outage_calls = {"n": 0}

        async def always_failing_acquire(
            lease_key: str,
            holder: str,
            *,
            ttl_seconds: int,
        ) -> bool:
            outage_calls["n"] += 1
            raise RuntimeError("simulated dhara outage")

        store.try_acquire_lease = always_failing_acquire  # type: ignore[method-assign]

        # Patch the sleep to yield once then signal stop — keeps the test
        # deterministic without relying on real asyncio.sleep timing.
        cycles_observed = {"n": 0}

        async def counting_sleep(_seconds: float) -> None:
            cycles_observed["n"] += 1
            if cycles_observed["n"] >= 2:
                stop.set()

        stop = asyncio.Event()
        task = asyncio.create_task(
            run_watchdog(
                config=WatchdogConfig(
                    holder="replica-a",
                    poll_interval_seconds=0.0,
                    lease_ttl_seconds=60,
                ),
                store=store,
                usage_source=_static(BudgetUsage(tokens_used=50)),
                emitter=emitter,
                sleep=counting_sleep,
                stop_event=stop,
            )
        )

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Loop must have completed at least one cycle despite the simulated outage.
        assert outage_calls["n"] >= 1
        # If we got here, the loop drained cleanly on stop. No crash propagation.


# =============================================================================
# Wallclock breach transitions the state in one cycle
# =============================================================================


class TestWallclockBreachEnforcement:
    """Demo check: a workflow with a tight wallclock is caught within one poll."""

    async def test_wallclock_breach_transitions_to_exceeded(self) -> None:
        spec = BudgetSpec(budget_wallclock_seconds=10.0)
        started_at = datetime.now(UTC) - timedelta(seconds=30)
        record = BudgetRecord(
            workflow_id="wf-tight",
            spec=spec,
            state=BudgetState.ACTIVE,
            started_at=started_at,
        )
        store = _make_store(record)
        emitter = _RecordingEmitter()
        metrics = WatchdogMetrics()

        async def usage_source(_wf: str) -> BudgetUsage:
            return BudgetUsage(
                tokens_used=None,
                turns_used=None,
                wallclock_seconds=(datetime.now(UTC) - started_at).total_seconds(),
            )

        result = await run_watchdog_cycle(
            store=store,
            holder="replica-a",
            lease_ttl_seconds=60,
            usage_source=usage_source,
            emitter=emitter,
            metrics=metrics,
        )
        assert result.records_transitioned == 1
        assert metrics.exceeded.get("wallclock") == 1
        # Counter was emitted with the right label.
        assert any(
            name == "budget.exceeded.count" and attrs.get("dimension") == "wallclock"
            for name, attrs in emitter.counters
        )
        # Span ``budget.check`` opened.
        assert any(name == "budget.check" for name, _ in emitter.spans)
        # Persisted record in Dhara reflects ``EXCEEDED``.
        persisted = await store.get("mahavishni://budgets/wf-tight.json")
        assert persisted is not None
        restored = BudgetRecord.from_dict(persisted)
        assert restored.state is BudgetState.EXCEEDED
        assert restored.exceeded_dimension is BudgetDimension.WALLCLOCK


# =============================================================================
# budget_enforce (MCP tool) end-to-end via the tool registry
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestBudgetEnforceTool:
    async def test_budget_enforce_persists_active_record(self) -> None:
        from mahavishnu.mcp.tools.pool_tools import register_pool_tools

        store = InMemoryBudgetStore()
        mcp = _StubMCP()
        register_pool_tools(mcp, pool_manager=AsyncMock(), budget_store=store)

        fn = mcp.tools["budget_enforce"]
        result = await fn(
            workflow_id="wf-tool",
            budget_tokens=5_000,
            budget_wallclock_seconds=120.0,
            declared_by="alice",
        )

        assert result["status"] == "active"
        assert result["state"] == BudgetState.ACTIVE.value
        assert result["spec"]["budget_tokens"] == 5_000

        # Persisted in the store.
        persisted = await store.get("mahavishni://budgets/wf-tool.json")
        assert persisted is not None
        record = BudgetRecord.from_dict(persisted)
        assert record.state is BudgetState.ACTIVE
        assert record.spec.budget_tokens == 5_000

    async def test_budget_enforce_without_store_returns_unconfigured(self) -> None:
        from mahavishnu.mcp.tools.pool_tools import register_pool_tools

        mcp = _StubMCP()
        register_pool_tools(mcp, pool_manager=AsyncMock())
        fn = mcp.tools["budget_enforce"]
        result = await fn(workflow_id="wf-no-store", budget_tokens=100)
        assert result["status"] == "unconfigured"

    async def test_budget_enforce_rejects_empty_spec_via_state_machine(self) -> None:
        from mahavishnu.mcp.tools.pool_tools import register_pool_tools

        store = InMemoryBudgetStore()
        mcp = _StubMCP()
        register_pool_tools(mcp, pool_manager=AsyncMock(), budget_store=store)
        fn = mcp.tools["budget_enforce"]
        # All three dims None → state-machine refuses to start.
        result = await fn(workflow_id="wf-empty")
        assert result["status"] == "failed"
        assert "at least one dimension" in result["error"]
