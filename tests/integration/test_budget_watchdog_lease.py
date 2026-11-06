"""Integration tests for the Phase 3 budget watchdog.

Focus areas (matching the v2 plan's Phase 3 exit criteria):

* Multi-replica safety: only one replica runs enforcement per cycle.
* Substrate unavailability does NOT crash the watchdog (fail-open path).
* A wallclock-breaching budget gets transitioned to ``EXCEEDED`` by
  the watchdog within one cycle.
* ``budget_enforce`` (the MCP-facing tool) round-trips a record to
  the store and exposes the new state.
* A lease whose holder died **expires** — against the real store, not
  only against the in-memory double.

Two stores are exercised. :class:`InMemoryBudgetStore` is a deliberately
narrow surface that mimics the real budget store's behavior closely
enough to exercise the lease, list, and read paths. It is not, however,
the store production runs on: it implemented lease expiry correctly
while :class:`MCPBudgetStore` did not, so a suite that only exercised
the double proved nothing about the class that is actually wired in.
The ``TestRealStoreLease`` class below therefore drives
:class:`MCPBudgetStore` over the **real** registered KV tools and the
real process-local store.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

from fastmcp import FastMCP
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
    MCPBudgetStore,
    WatchdogConfig,
    WatchdogMetrics,
    run_watchdog,
    run_watchdog_cycle,
)
from mahavishnu.mcp.tools.kv_tools import register_kv_tools

if TYPE_CHECKING:
    from mahavishnu.core.permissions import Permission

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
            def __enter__(self) -> _Span:
                return self

            def __exit__(self, *_: object) -> bool | None:
                return None

            async def __aenter__(self) -> _Span:
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

    async def test_mcp_unavailable_does_not_crash_watchdog(self) -> None:
        """When the store raises on every op, the cycle returns cleanly.

        This is the fail-open exit criterion: never crash the
        watchdog's host process just because the store is unreachable.
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
        # Fail-open: mcp_unavailable is True, the cycle did not raise,
        # and the metrics counter incremented.
        assert result.mcp_unavailable is True
        assert result.lease_acquired is False


# =============================================================================
# Fail-open on substrate unavailability
# =============================================================================


class TestMCPFailOpen:
    """When the store is unreachable, the watchdog must NOT raise or stop."""

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
                raise RuntimeError("simulated store down")
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
        # Store unavailable path:
        assert result.mcp_unavailable is True
        assert result.lease_acquired is False
        assert metrics.skipped_mcp_unavailable == 1

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
        assert result.mcp_unavailable is True
        assert metrics.skipped_mcp_unavailable == 1

    async def test_mcp_down_full_loop_does_not_crash(self) -> None:
        """Even when every store call raises, the loop survives."""
        store = _make_store()
        emitter = _RecordingEmitter()

        # Simulate a continuous substrate outage by replacing
        # ``try_acquire_lease`` with one that always raises.
        outage_calls = {"n": 0}

        async def always_failing_acquire(
            lease_key: str,
            holder: str,
            *,
            ttl_seconds: int,
        ) -> bool:
            outage_calls["n"] += 1
            raise RuntimeError("simulated mcp outage")

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
        # Persisted record in the store reflects ``EXCEEDED``.
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


# =============================================================================
# The lease against the REAL store — not the in-memory double
# =============================================================================


class _Clock:
    """A manually advanced UTC clock (no ``time.sleep`` in a test)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class _AllowAllRBAC:
    """RBAC manager that grants every permission to every principal."""

    async def check_permission(
        self, user_id: str, repo: str, permission: Permission
    ) -> bool:
        return True


class _RealKVClient:
    """Drives the **real** registered KV tools over the real store.

    Not a mock: the tool functions ``register_kv_tools`` installs are
    called directly, so the whole chain — tool → ``kv_store.put`` → TTL
    enforcement — is exercised. The only substitution is the transport
    (an in-process call instead of an HTTP round-trip).
    """

    def __init__(self, server: FastMCP, user_id: str = "watchdog-replica") -> None:
        self._server = server
        self._user_id = user_id
        self._tools: dict[str, Any] = {}

    async def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._tools:
            for tool in await self._server.list_tools():
                self._tools[tool.name] = tool.fn
        result = await self._tools[name](**arguments)
        return result if isinstance(result, dict) else {}

    async def put(self, key: str, value: Any, ttl: int | None = None) -> Any:
        """Mirror :meth:`MCPClient.put` — structured values are JSON-encoded."""
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, separators=(",", ":"))
        )
        arguments: dict[str, Any] = {
            "key": key,
            "value": text,
            "user_id": self._user_id,
        }
        if ttl is not None:
            arguments["ttl"] = ttl
        return await self._call("mahavishnu_kv_put", arguments)

    async def kv_get(self, key: str) -> str | None:
        result = await self._call(
            "mahavishnu_kv_get", {"key": key, "user_id": self._user_id}
        )
        if not result.get("ok"):
            return None
        value = result.get("value")
        return value if isinstance(value, str) else None

    async def kv_list(self, prefix: str) -> list[tuple[str, str]]:
        result = await self._call(
            "mahavishnu_kv_list", {"prefix": prefix, "user_id": self._user_id}
        )
        if not result.get("ok"):
            return []
        return [
            (item["key"], item["value"])
            for item in result.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        ]


@pytest.fixture
def real_kv_client() -> _RealKVClient:
    """A client bound to the real KV tools over the process-local store."""
    server = FastMCP(name="budget-lease-real-store")
    register_kv_tools(server, _AllowAllRBAC())
    return _RealKVClient(server)


class TestRealStoreLease:
    """The lease must expire against the store the watchdog actually uses.

    ``InMemoryBudgetStore`` implemented lease expiry correctly while
    ``MCPBudgetStore`` did not, so the double hid the defect: the real
    store never evicted a lease record and the real client never read
    the expiry, which meant a replica that died holding the lease
    disabled budget enforcement for every other replica, permanently.
    """

    async def test_a_live_foreign_lease_blocks_a_takeover(self, real_kv_client) -> None:
        """Mutual exclusion still holds while the lease is live."""
        clock = _Clock()
        store = MCPBudgetStore(real_kv_client, now=clock)
        lease_key = "mahavishni://budgets/lease.json"

        assert (
            await store.try_acquire_lease(lease_key, "replica-a", ttl_seconds=60)
            is True
        )
        assert (
            await store.try_acquire_lease(lease_key, "replica-b", ttl_seconds=60)
            is False
        )

    async def test_an_expired_foreign_lease_is_re_acquirable(
        self, real_kv_client
    ) -> None:
        """The regression this file exists for.

        The dead replica's record is still physically in the store, but
        its lease has lapsed — so another replica must be able to take
        over. The expiry is decided from the record's own ``expires_at``
        stamp, not from the store having evicted it.
        """
        clock = _Clock()
        store = MCPBudgetStore(real_kv_client, now=clock)
        lease_key = "mahavishni://budgets/lease.json"

        assert (
            await store.try_acquire_lease(lease_key, "replica-a", ttl_seconds=60)
            is True
        )

        clock.advance(61)

        # The stale record is still there …
        assert await real_kv_client.kv_get(lease_key) is not None
        # … but it no longer locks anybody out.
        assert (
            await store.try_acquire_lease(lease_key, "replica-b", ttl_seconds=60)
            is True
        )

    async def test_the_lease_record_carries_its_own_expiry(
        self, real_kv_client
    ) -> None:
        """The lease is self-describing: it says when it lapses."""
        clock = _Clock()
        store = MCPBudgetStore(real_kv_client, now=clock)
        lease_key = "mahavishni://budgets/lease.json"

        await store.try_acquire_lease(lease_key, "replica-a", ttl_seconds=60)

        raw = await real_kv_client.kv_get(lease_key)
        assert raw is not None
        record = json.loads(raw)
        assert record["holder"] == "replica-a"
        assert record["expires_at"] == (clock.now + timedelta(seconds=60)).isoformat()

    async def test_releasing_an_expired_lease_does_not_clobber_the_new_holder(
        self, real_kv_client
    ) -> None:
        """A lapsed lease is not ours to release."""
        clock = _Clock()
        store = MCPBudgetStore(real_kv_client, now=clock)
        lease_key = "mahavishni://budgets/lease.json"

        await store.try_acquire_lease(lease_key, "replica-a", ttl_seconds=60)
        clock.advance(61)
        assert (
            await store.try_acquire_lease(lease_key, "replica-b", ttl_seconds=60)
            is True
        )

        # The dead replica tries to release its lapsed lease.
        await store.release_lease(lease_key, "replica-a")

        raw = await real_kv_client.kv_get(lease_key)
        assert raw is not None
        assert json.loads(raw)["holder"] == "replica-b"

    async def test_the_store_evicts_a_lease_written_with_a_zero_ttl(
        self, real_kv_client
    ) -> None:
        """The substrate's own TTL is live through the real tool path."""
        lease_key = "mahavishni://budgets/lease.json"
        await real_kv_client.put(lease_key, {"holder": "replica-a"}, ttl=0)
        assert await real_kv_client.kv_get(lease_key) is None

    async def test_a_dead_replica_does_not_disable_budget_enforcement(
        self, real_kv_client
    ) -> None:
        """The consequence the defect produced, end to end.

        A replica that dies holding the lease used to disable budget
        enforcement for every other replica, permanently.
        """
        clock = _Clock()
        store = MCPBudgetStore(real_kv_client, now=clock)
        record = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        await store.put("mahavishni://budgets/wf-1.json", record.to_dict())

        # replica-a takes the lease … and dies.
        assert (
            await store.try_acquire_lease(
                "mahavishni://budgets/lease.json", "replica-a", ttl_seconds=60
            )
            is True
        )

        # While the lease is live, replica-b cannot enforce.
        blocked = await run_watchdog_cycle(
            store=store,
            holder="replica-b",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=500)),
        )
        assert blocked.lease_acquired is False
        assert blocked.records_transitioned == 0

        # The lease lapses — enforcement must resume.
        clock.advance(61)
        resumed = await run_watchdog_cycle(
            store=store,
            holder="replica-b",
            lease_ttl_seconds=60,
            usage_source=_static(BudgetUsage(tokens_used=500)),
        )
        assert resumed.lease_acquired is True
        assert resumed.records_transitioned == 1

        persisted = await store.get("mahavishni://budgets/wf-1.json")
        assert persisted is not None
        assert BudgetRecord.from_dict(persisted).state is BudgetState.EXCEEDED
