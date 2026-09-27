"""Tests for ConcurrencyGate per-TaskCategory + rate limiting (C-9, REQ-012, REQ-013).

FIX round-7 (Tier 3): the original ``test_acquire_beyond_limit_denied`` was
redundant with the real-concurrency test below — sequential ``await`` chains
cannot exercise the lock + counter under contention. Kept as a no-race
happy path.
"""

from __future__ import annotations

import asyncio

import pytest

from mahavishnu.core.concurrency_gate import ConcurrencyGate
from mahavishnu.core.config import (
    ConcurrencyLimitSpec,
    ConcurrencyLimitsSettings,
)
from mahavishnu.core.errors import RateLimitError
from mahavishnu.core.model_routing import TaskCategory
from mahavishnu.core.rate_limit import _estimate_retry


@pytest.fixture
def settings_with_limit() -> ConcurrencyLimitsSettings:
    spec = ConcurrencyLimitSpec(
        concurrency_limit=2,
        refill_rate_per_second=0.0,
        global_override=False,
    )
    return ConcurrencyLimitsSettings(by_category={TaskCategory.CODE_GENERATION: spec})


@pytest.mark.req(["REQ-012"])
class TestConcurrencyGate:
    async def test_no_spec_means_no_limit(self) -> None:
        gate = ConcurrencyGate(ConcurrencyLimitsSettings(by_category={}))
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_acquire_within_limit(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_acquire_beyond_limit_denied(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Happy-path no-race check (round-7 redundancy note)."""
        gate = ConcurrencyGate(settings_with_limit)
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is False

    async def test_release_frees_slot(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.release(TaskCategory.CODE_GENERATION, "pool-1")
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_release_clamps_at_zero(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Double-release cannot drive the counter negative."""
        gate = ConcurrencyGate(settings_with_limit)
        await gate.release(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.release(TaskCategory.CODE_GENERATION, "pool-1")
        # Counter stayed at 0; a fresh acquire still works.
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_per_pool_isolation(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Two pools with same category have separate limits."""
        gate = ConcurrencyGate(settings_with_limit)
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        # pool-2 has its own counter
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-2") is True

    async def test_global_override_spans_pools(self) -> None:
        spec = ConcurrencyLimitSpec(
            concurrency_limit=2,
            refill_rate_per_second=0.0,
            global_override=True,
        )
        settings = ConcurrencyLimitsSettings(by_category={TaskCategory.SWARM: spec})
        gate = ConcurrencyGate(settings)
        assert await gate.try_acquire(TaskCategory.SWARM, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.SWARM, "pool-2") is True
        assert await gate.try_acquire(TaskCategory.SWARM, "pool-3") is False


@pytest.mark.req(["REQ-013"])
class TestRateLimitErrorFailClosed:
    async def test_enforce_raises_on_denial(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        from mahavishnu.mcp.tools.pool_tools import (
            _enforce_concurrency_limit,
            set_concurrency_gate,
        )

        # Inject the test gate so _enforce uses the limit-2 spec from the
        # fixture instead of the module-level gate built from settings.
        test_gate = ConcurrencyGate(settings_with_limit)
        set_concurrency_gate(test_gate)
        try:
            await _enforce_concurrency_limit(TaskCategory.CODE_GENERATION, "pool-1")
            await _enforce_concurrency_limit(TaskCategory.CODE_GENERATION, "pool-1")
            with pytest.raises(RateLimitError):
                await _enforce_concurrency_limit(
                    TaskCategory.CODE_GENERATION, "pool-1"
                )
        finally:
            set_concurrency_gate(None)

    async def test_enforce_passes_when_no_spec(self) -> None:
        """No spec registered -> gate is pass-through, no raise."""
        from mahavishnu.mcp.tools.pool_tools import _enforce_concurrency_limit

        # Empty settings -> every category is pass-through.
        gate = ConcurrencyGate(ConcurrencyLimitsSettings(by_category={}))
        from mahavishnu.mcp.tools.pool_tools import set_concurrency_gate

        set_concurrency_gate(gate)
        try:
            await _enforce_concurrency_limit(TaskCategory.DEBUGGING, "pool-x")
            await _enforce_concurrency_limit(TaskCategory.DEBUGGING, "pool-x")
        finally:
            set_concurrency_gate(None)


@pytest.mark.req(["REQ-013"])
class TestEstimateRetry:
    def test_zero_refill_returns_one(self) -> None:
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=0.0, global_override=False
        )
        assert _estimate_retry(spec) == 1.0

    def test_low_refill_returns_reciprocal(self) -> None:
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=0.5, global_override=False
        )
        assert _estimate_retry(spec) == 2.0

    def test_high_refill_floor_at_one(self) -> None:
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=10.0, global_override=False
        )
        assert _estimate_retry(spec) == 1.0  # floor at 1s

    def test_none_spec_returns_one(self) -> None:
        assert _estimate_retry(None) == 1.0


@pytest.mark.req(["REQ-012"])
class TestRealConcurrency:
    """FIX (round-5): real concurrent tests using asyncio.gather.

    Sequential ``await`` chains in TestConcurrencyGate pass regardless of
    whether the lock + counter work correctly. These tests fire N
    concurrent calls and assert the gate's invariants under contention.
    """

    async def test_concurrent_try_acquire_never_exceeds_limit(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Fire 50 concurrent calls; exactly limit succeed."""
        spec = ConcurrencyLimitSpec(
            concurrency_limit=5,
            refill_rate_per_second=0.0,
            global_override=False,
        )
        settings = ConcurrencyLimitsSettings(
            by_category={TaskCategory.CODE_REVIEW: spec}
        )
        gate = ConcurrencyGate(settings)

        results = await asyncio.gather(
            *[gate.try_acquire(TaskCategory.CODE_REVIEW, "pool-1") for _ in range(50)]
        )
        # Exactly 5 succeeded; 45 denied
        assert sum(results) == 5
        assert sum(1 for r in results if not r) == 45
        # Internal counter agrees
        assert gate._counters[(TaskCategory.CODE_REVIEW, "pool-1")] == 5

    async def test_concurrent_per_pool_isolation(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Concurrent calls across different pool_ids do not interfere."""
        spec = ConcurrencyLimitSpec(
            concurrency_limit=2,
            refill_rate_per_second=0.0,
            global_override=False,
        )
        settings = ConcurrencyLimitsSettings(
            by_category={TaskCategory.CODE_GENERATION: spec}
        )
        gate = ConcurrencyGate(settings)

        # 4 concurrent calls each on pool-1 and pool-2
        tasks: list[asyncio.Future[bool]] = []
        for pool_id in ["pool-1", "pool-2"]:
            for _ in range(4):
                tasks.append(
                    asyncio.ensure_future(
                        gate.try_acquire(TaskCategory.CODE_GENERATION, pool_id)
                    )
                )
        results = await asyncio.gather(*tasks)
        # Per-pool limit = 2; 2 succeed per pool, 2 denied per pool
        pool_1_results = results[0:4]
        pool_2_results = results[4:8]
        assert sum(pool_1_results) == 2
        assert sum(pool_2_results) == 2

    async def test_release_under_contention(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        """Release during concurrent acquisitions correctly frees slots."""
        spec = ConcurrencyLimitSpec(
            concurrency_limit=3,
            refill_rate_per_second=0.0,
            global_override=False,
        )
        settings = ConcurrencyLimitsSettings(
            by_category={TaskCategory.SWARM: spec}
        )
        gate = ConcurrencyGate(settings)

        # Acquire 3 (saturate)
        for _ in range(3):
            assert await gate.try_acquire(TaskCategory.SWARM, "pool-1") is True
        # 4th denied
        assert await gate.try_acquire(TaskCategory.SWARM, "pool-1") is False
        # Release 1, then concurrent acquisition of 4 — exactly 1 succeeds
        await gate.release(TaskCategory.SWARM, "pool-1")
        results = await asyncio.gather(
            *[gate.try_acquire(TaskCategory.SWARM, "pool-1") for _ in range(4)]
        )
        assert sum(results) == 1


@pytest.mark.req(["REQ-012"])
class TestSpecForPublicAccessor:
    def test_returns_spec(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        spec = gate.spec_for(TaskCategory.CODE_GENERATION)
        assert spec is not None
        assert spec.concurrency_limit == 2

    def test_returns_none_for_unspecified(
        self, settings_with_limit: ConcurrencyLimitsSettings
    ) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        assert gate.spec_for(TaskCategory.TESTING) is None
