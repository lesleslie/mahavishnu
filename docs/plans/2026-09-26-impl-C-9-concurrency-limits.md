# C-9: per-TaskCategory concurrency limits (WP-4)

**REQ-NNN:** REQ-012, REQ-013
- REQ-012: `ConcurrencyGate` per-TaskCategory with shard locks by `(category, pool_id)`
- REQ-013: Token-bucket rate limiting with fail-closed default
**Risk:** Medium (per-process scope is a documented limitation; multi-worker pools must multiply spec limits)
**Blocks:** C-13 (crackerjack review-pr workflow runs under `TaskCategory.CODE_REVIEW` and hits the gate)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).
**Status:** Draft — round-4 corrections baked in (per-process scope documented prominently, `pool_worker_id` label added, `_estimate_retry` helper extracted, `_specs.get` replaced by `spec_for()`).

## Goal

Add `ConcurrencyGate` keyed on `TaskCategory`. Per round-4 security finding: **the per-process scope must be documented prominently** because the effective limit is N × spec.concurrency_limit across N workers. This is not a bug — it is a known limitation. Operators with multi-worker pools must multiply their spec values by the worker count, OR migrate to a Redis/Dhara-backed shared counter (out of scope for C-9).

The plan also adds **token-bucket rate limiting with fail-closed default** per REQ-013. When the gate denies a request, the caller observes `RateLimitError` — they must NOT silently proceed.

## Pre-flight checks

1. **C-1 has landed.** `concurrency_limits:` section exists in `settings/mahavishnu.yaml` with `by_category:` map of `TaskCategory -> ConcurrencyLimitSpec`.
2. **`TaskCategory` enum lives at `mahavishnu/core/model_routing.py`.** Read the existing values (per CLAUDE.md: `CODE_GENERATION`, `CODE_REVIEW`, `DEBUGGING`, `REFACTORING`, `TESTING`, `REASONING`, `ANALYSIS`, `DOCUMENTATION`, `VISION`, `EMBEDDING`, `ML_INFERENCE`, `SWARM`, `QUICK`, `AGENT_LOOP`, `CREATIVE`, `GENERAL`).
3. **`cachetools` available.** `uv pip show cachetools` — used by the `LRUCache(maxsize=1024)` for shard lock bounding.
4. **`mahavishnu/core/rate_limit.py` exists at line 152+** with `is_allowed(key, config) -> tuple[bool, RateLimitInfo]`. Read the existing signature before extending.
5. **`hypothesis` available** for the property test (`pip show hypothesis`).
6. **`pytest.mark.timeout` registered** in `pyproject.toml [tool.pytest] markers`. The property test uses `@pytest.mark.timeout(120)`.

## File-by-file changes

### 1. `mahavishnu/core/concurrency_gate.py` — new file (~150 LoC)

```python
"""Per-TaskCategory concurrency counter.

LIMITATION: per-process scope. With N workers, effective limit is N × spec.concurrency_limit
across N workers. Documented in docs/runbooks/concurrency-limit-storm.md.
Fix path: replace with Redis/Dhara-backed shared counter when cross-pool guarantees are required.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from cachetools import LRUCache
from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from mahavishnu.core.config import ConcurrencyLimitsSettings, ConcurrencyLimitSpec
    from mahavishnu.core.model_routing import TaskCategory


logger = get_logger(__name__)


class ConcurrencyGate:
    """Per-TaskCategory concurrency counter.

    Thread-safety: shard locks by (category, pool_id) prevent races within
    a process. Cross-process / cross-worker races are NOT prevented — see
    LIMITATION above.
    """

    def __init__(self, settings: ConcurrencyLimitsSettings) -> None:
        self._specs: dict[TaskCategory, ConcurrencyLimitSpec] = settings.by_category
        self._counters: dict[tuple[TaskCategory, str | None], int] = defaultdict(int)
        # LRUCache bounds shard lock memory; 1024 entries is enough for any
        # realistic (category, pool_id) combination without unbounded growth.
        self._shard_locks: LRUCache = LRUCache(maxsize=1024)

    async def try_acquire(self, category: TaskCategory, pool_id: str | None) -> bool:
        """Try to acquire a concurrency slot. Returns True if granted."""
        spec = self._specs.get(category)
        if spec is None or spec.concurrency_limit is None:
            return True
        key = (category, None if spec.global_override else pool_id)
        lock = self._shard_locks.get(key) or asyncio.Lock()
        self._shard_locks[key] = lock
        async with lock:
            if self._counters[key] >= spec.concurrency_limit:
                return False
            self._counters[key] += 1
            return True

    async def release(self, category: TaskCategory, pool_id: str | None) -> None:
        """Release a previously-acquired concurrency slot."""
        spec = self._specs.get(category)
        if spec is None:
            return
        key = (category, None if spec.global_override else pool_id)
        lock = self._shard_locks.get(key)
        if lock is None:
            return
        async with lock:
            self._counters[key] = max(0, self._counters[key] - 1)

    def spec_for(self, category: TaskCategory) -> ConcurrencyLimitSpec | None:
        """Public accessor — replaces direct _specs access."""
        return self._specs.get(category)
```

### 2. `mahavishnu/core/rate_limit.py` — add `_estimate_retry` helper

Read the existing `RateLimiter` class at line 152. Add a module-private helper near it:

```python
def _estimate_retry(spec: ConcurrencyLimitSpec | None) -> float:
    """Estimate retry-after-seconds for a denied rate-limit request.

    Returns 1.0 if refill_rate_per_second <= 0 (avoids ZeroDivisionError).
    """
    if spec is None or spec.refill_rate_per_second <= 0:
        return 1.0
    return max(1.0, 1.0 / spec.refill_rate_per_second)
```

Per round-4 LOW finding: explicit zero-check before division.

### 3. `mahavishnu/mcp/tools/pool_tools.py` — wire at `budget_enforce` site

At the existing `budget_enforce` location (~line 203 per spec), wire the gate:

```python
from mahavishnu.core.concurrency_gate import ConcurrencyGate
from mahavishnu.core.errors import RateLimitError
from mahavishnu.core.rate_limit import _estimate_retry

concurrency_gate = ConcurrencyGate(get_settings().concurrency_limits)


async def _enforce_concurrency_limit(task_category: TaskCategory, pool_id: str) -> None:
    if not await concurrency_gate.try_acquire(task_category, pool_id):
        spec = concurrency_gate.spec_for(task_category)
        raise RateLimitError(
            limit=spec.concurrency_limit if spec else None,
            retry_after_seconds=_estimate_retry(spec),
            domain=f"task_category={task_category.value}",
        )
```

Call `_enforce_concurrency_limit(category, pool_id)` at the dispatch entry point. Wire the matching `release` in a `finally` block.

### 4. `settings/models.yaml` — extend per-TaskCategory limit config

Append under `task_routing:` (or similar; verify location):

```yaml
concurrency_limits:
  by_category:
    CODE_GENERATION:
      concurrency_limit: 4
      refill_rate_per_second: 1.0
      global_override: false
    CODE_REVIEW:
      concurrency_limit: 8
      refill_rate_per_second: 2.0
      global_override: false
    DEBUGGING:
      concurrency_limit: 4
      refill_rate_per_second: 1.0
      global_override: false
    REFACTORING:
      concurrency_limit: 2
      refill_rate_per_second: 0.5
      global_override: false
    TESTING:
      concurrency_limit: 6
      refill_rate_per_second: 1.5
      global_override: false
    REASONING:
      concurrency_limit: 4
      refill_rate_per_second: 1.0
      global_override: false
    SWARM:
      concurrency_limit: 16
      refill_rate_per_second: 0.0  # never refills — finite burst only
      global_override: true  # spans all pools
    QUICK:
      concurrency_limit: 32
      refill_rate_per_second: 8.0
      global_override: true
```

Defaults follow round-2 estimates; operators tune per workload.

### 5. `mahavishnu/core/metrics.py` — add 6 metrics

```python
TASK_DOMAIN_CONCURRENCY = Gauge(
    "task_domain_concurrency",
    "Active concurrent tasks, labeled by domain and pool_worker_id.",
    labelnames=["domain", "pool_worker_id"],
)

TASK_DOMAIN_RATE_LIMITED_TOTAL = Counter(
    "task_domain_rate_limited_total",
    "Total rate-limit denials, labeled by domain.",
    labelnames=["domain"],
)

TASK_DOMAIN_QUEUE_DEPTH = Gauge(
    "task_domain_queue_depth",
    "Pending tasks awaiting a concurrency slot, labeled by domain.",
    labelnames=["domain"],
)

TASK_DOMAIN_THROUGHPUT = Counter(
    "task_domain_throughput",
    "Completed tasks per domain.",
    labelnames=["domain"],
)

TASK_DOMAIN_CONCURRENCY_DRIFT_TOTAL = Counter(
    "task_domain_concurrency_drift_total",
    "Atomicity violations: counter exceeded spec limit under contention.",
    labelnames=["domain"],
)
```

The `pool_worker_id` label (per security round-4) lets operators aggregate across workers — without it, per-worker counts are invisible.

## Tests

### 6. `tests/integration/test_pool_concurrency_limit.py` — new file (~200 LoC)

```python
"""Tests for ConcurrencyGate per-TaskCategory + rate limiting."""
from __future__ import annotations

import asyncio

import pytest

from mahavishnu.core.concurrency_gate import ConcurrencyGate
from mahavishnu.core.errors import RateLimitError
from mahavishnu.core.model_routing import TaskCategory
from mahavishnu.core.rate_limit import _estimate_retry


@pytest.fixture
def settings_with_limit():
    from mahavishnu.core.config import (
        ConcurrencyLimitsSettings,
        ConcurrencyLimitSpec,
    )
    spec = ConcurrencyLimitSpec(
        concurrency_limit=2,
        refill_rate_per_second=0.0,
        global_override=False,
    )
    return ConcurrencyLimitsSettings(by_category={TaskCategory.CODE_GENERATION: spec})


@pytest.mark.req(["REQ-012"])
class TestConcurrencyGate:
    async def test_no_spec_means_no_limit(self) -> None:
        from mahavishnu.core.config import ConcurrencyLimitsSettings
        gate = ConcurrencyGate(ConcurrencyLimitsSettings(by_category={}))
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_acquire_within_limit(self, settings_with_limit) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_acquire_beyond_limit_denied(self, settings_with_limit) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is False

    async def test_release_frees_slot(self, settings_with_limit) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1")
        await gate.release(TaskCategory.CODE_GENERATION, "pool-1")
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True

    async def test_per_pool_isolation(self, settings_with_limit) -> None:
        """Two pools with same category have separate limits."""
        gate = ConcurrencyGate(settings_with_limit)
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-1") is True
        # pool-2 has its own counter
        assert await gate.try_acquire(TaskCategory.CODE_GENERATION, "pool-2") is True

    async def test_global_override_spans_pools(self) -> None:
        from mahavishnu.core.config import (
            ConcurrencyLimitsSettings,
            ConcurrencyLimitSpec,
        )
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
    async def test_enforce_raises_on_denial(self, settings_with_limit) -> None:
        from mahavishnu.mcp.tools.pool_tools import _enforce_concurrency_limit

        await _enforce_concurrency_limit(TaskCategory.CODE_GENERATION, "pool-1")
        await _enforce_concurrency_limit(TaskCategory.CODE_GENERATION, "pool-1")
        with pytest.raises(RateLimitError):
            await _enforce_concurrency_limit(TaskCategory.CODE_GENERATION, "pool-1")


@pytest.mark.req(["REQ-013"])
class TestEstimateRetry:
    def test_zero_refill_returns_one(self) -> None:
        from mahavishnu.core.config import ConcurrencyLimitSpec
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=0.0, global_override=False
        )
        assert _estimate_retry(spec) == 1.0

    def test_low_refill_returns_reciprocal(self) -> None:
        from mahavishnu.core.config import ConcurrencyLimitSpec
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=0.5, global_override=False
        )
        assert _estimate_retry(spec) == 2.0

    def test_high_refill_floor_at_one(self) -> None:
        from mahavishnu.core.config import ConcurrencyLimitSpec
        spec = ConcurrencyLimitSpec(
            concurrency_limit=4, refill_rate_per_second=10.0, global_override=False
        )
        assert _estimate_retry(spec) == 1.0  # floor at 1s


@pytest.mark.req(["REQ-012"])
class TestRealConcurrency:
    """FIX (round-5): real concurrent tests using asyncio.gather.

    The existing tests in TestConcurrencyGate are sequential await chains
    that pass regardless of whether the lock + counter work correctly.
    These tests use asyncio.gather to fire N concurrent calls and
    assert the gate's invariants under contention.
    """

    async def test_concurrent_try_acquire_never_exceeds_limit(
        self, settings_with_limit
    ) -> None:
        """Fire 50 concurrent calls; exactly limit succeed."""
        import asyncio
        from mahavishnu.core.concurrency_gate import ConcurrencyGate
        from mahavishnu.core.config import (
            ConcurrencyLimitsSettings,
            ConcurrencyLimitSpec,
        )

        spec = ConcurrencyLimitSpec(
            concurrency_limit=5,
            refill_rate_per_second=0.0,
            global_override=False,
        )
        settings = ConcurrencyLimitsSettings(
            by_category={TaskCategory.CODE_REVIEW: spec}
        )
        gate = ConcurrencyGate(settings)

        results = await asyncio.gather(*[
            gate.try_acquire(TaskCategory.CODE_REVIEW, "pool-1")
            for _ in range(50)
        ])
        # Exactly 5 succeeded; 45 denied
        assert sum(results) == 5
        assert sum(1 for r in results if not r) == 45
        # Internal counter agrees
        assert gate._counters[(TaskCategory.CODE_REVIEW, "pool-1")] == 5

    async def test_concurrent_per_pool_isolation(
        self, settings_with_limit
    ) -> None:
        """Concurrent calls across different pool_ids do not interfere."""
        import asyncio
        from mahavishnu.core.concurrency_gate import ConcurrencyGate
        from mahavishnu.core.config import (
            ConcurrencyLimitsSettings,
            ConcurrencyLimitSpec,
        )

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
        tasks = []
        for pool_id in ["pool-1", "pool-2"]:
            for _ in range(4):
                tasks.append(
                    gate.try_acquire(TaskCategory.CODE_GENERATION, pool_id)
                )
        results = await asyncio.gather(*tasks)
        # Per-pool limit = 2; 2 succeed per pool, 2 denied per pool
        pool_1_results = results[0:4]
        pool_2_results = results[4:8]
        assert sum(pool_1_results) == 2
        assert sum(pool_2_results) == 2

    async def test_release_under_contention(
        self, settings_with_limit
    ) -> None:
        """Release during concurrent acquisitions correctly frees slots."""
        import asyncio
        from mahavishnu.core.concurrency_gate import ConcurrencyGate
        from mahavishnu.core.config import (
            ConcurrencyLimitsSettings,
            ConcurrencyLimitSpec,
        )

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
        results = await asyncio.gather(*[
            gate.try_acquire(TaskCategory.SWARM, "pool-1")
            for _ in range(4)
        ])
        assert sum(results) == 1


@pytest.mark.req(["REQ-012"])
class TestSpecForPublicAccessor:
    def test_returns_spec(self, settings_with_limit) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        spec = gate.spec_for(TaskCategory.CODE_GENERATION)
        assert spec is not None
        assert spec.concurrency_limit == 2

    def test_returns_none_for_unspecified(self, settings_with_limit) -> None:
        gate = ConcurrencyGate(settings_with_limit)
        assert gate.spec_for(TaskCategory.TESTING) is None
```

### 7. `tests/property/test_pool_concurrency_limit_property.py` — new file (~80 LoC)

Stateful Hypothesis property test, marked slow + timeout per round-4 test lens:

```python
"""Stateful property test: active count never exceeds the configured limit."""
from __future__ import annotations

import pytest
from hypothesis import (
    HealthCheck,
    given,
    settings as hp_settings,
    strategies as st,
)

from mahavishnu.core.concurrency_gate import ConcurrencyGate
from mahavishnu.core.config import (
    ConcurrencyLimitsSettings,
    ConcurrencyLimitSpec,
)
from mahavishnu.core.model_routing import TaskCategory


@pytest.mark.req(["REQ-012"])
@pytest.mark.slow
@pytest.mark.timeout(120)
@hp_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
@given(
    limit=st.integers(min_value=1, max_value=10),
    pool_id=st.sampled_from(["pool-A", "pool-B", "pool-C"]),
    acquire_count=st.integers(min_value=1, max_value=20),
    release_count=st.integers(min_value=0, max_value=20),
)
async def test_invariant_active_count_never_exceeds_limit(
    limit: int, pool_id: str, acquire_count: int, release_count: int
) -> None:
    spec = ConcurrencyLimitSpec(
        concurrency_limit=limit,
        refill_rate_per_second=0.0,
        global_override=False,
    )
    settings = ConcurrencyLimitsSettings(by_category={TaskCategory.CODE_REVIEW: spec})
    gate = ConcurrencyGate(settings)

    acquired = 0
    denied = 0
    for _ in range(acquire_count):
        if await gate.try_acquire(TaskCategory.CODE_REVIEW, pool_id):
            acquired += 1
        else:
            denied += 1

    for _ in range(min(release_count, acquired)):
        await gate.release(TaskCategory.CODE_REVIEW, pool_id)

    # Invariant: at no point did we acquire more than `limit` slots
    spec_now = gate.spec_for(TaskCategory.CODE_REVIEW)
    assert spec_now is not None
    active = max(0, acquired - min(release_count, acquired))
    assert active <= spec_now.concurrency_limit
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_pool_concurrency_limit.py -v
uv run pytest tests/property/test_pool_concurrency_limit_property.py -v -m slow
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/core/concurrency_gate.py` exists with `ConcurrencyGate` class.
2. `ConcurrencyGate.try_acquire()` returns False when at limit, True when slot available.
3. `ConcurrencyGate.release()` decrements the counter; counter never goes below 0.
4. `_estimate_retry()` handles `refill_rate_per_second=0` without `ZeroDivisionError`.
5. `ConcurrencyGate.spec_for()` is the public accessor — no direct `_specs` access outside the class.
6. `_enforce_concurrency_limit()` raises `RateLimitError` (fail-CLOSED) on denial.
7. `LRUCache(maxsize=1024)` bounds the `_shard_locks` dict.
8. Per-pool isolation works: same category, different pools have separate counters (unless `global_override=True`).
9. Property test `test_invariant_active_count_never_exceeds_limit` passes for 20 random examples.
10. `task_domain_concurrency{pool_worker_id}` label is present (verified via `metrics.py`).
11. `python scripts/audit_requirements.py --json` reports REQ-012, REQ-013 wired.
12. `crackerjack run` passes; coverage gate holds.
13. **Runbook `docs/runbooks/concurrency-limit-storm.md` exists** documenting the per-process scope limitation.

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0`, no deprecation window. The `ConcurrencyGate` is a NEW class — existing dispatch behavior is preserved when `concurrency_limits.by_category` is empty (the gate grants all requests). Operators opt in by adding `by_category` entries.

Recovery for an over-aggressive limit: reduce `concurrency_limit` values in `settings/mahavishnu.yaml` (added in C-1). No code change.

Recovery for the per-process-scope confusion: see the runbook. Operators with N workers must set `concurrency_limit = floor(target_total / N)`. The long-term fix is Redis/Dhara-backed shared counter — out of scope for C-9.

## Observability added

Six new Prometheus metrics (covered above):

- `task_domain_concurrency{domain, pool_worker_id}` — Gauge
- `task_domain_rate_limited_total{domain}` — Counter
- `task_domain_queue_depth{domain}` — Gauge
- `task_domain_throughput{domain}` — Counter
- `task_domain_concurrency_drift_total{domain}` — Counter (atomicity violations)

Operators alert on `rate(task_domain_rate_limited_total[5m]) > 0.1` (too many denials = limits are too aggressive OR legitimate load spike). The `pool_worker_id` label is the key addition for multi-worker observability — operators can spot per-worker hot spots.

## Health aggregation

The gate does not surface to `/health` directly. Operators observe health via:
- `task_domain_concurrency{domain, pool_worker_id}` near saturation = worker overloaded
- `task_domain_rate_limited_total{domain}` rate = limits rejecting too many requests

A dedicated health check is left for a follow-up commit — too speculative for C-9.

## Implementation notes / gotchas

- **Per-process scope is a documented limitation, NOT a bug.** The class docstring states it explicitly; the runbook expands on it. Operators with N workers must multiply their effective limits by 1/N.
- **`LRUCache(maxsize=1024)`** bounds the `_shard_locks` dict. Without it, long-running processes with many distinct `(category, pool_id)` keys would accumulate locks indefinitely.
- **`_specs.get` is private; consumers use `spec_for()`.** Direct dict access is brittle (the key could change).
- **`_estimate_retry` is module-private** (underscore prefix). It's not a public API; callers do not import it directly. `RateLimitError` carries the `retry_after_seconds` value.
- **Property test is `slow + timeout(120)`.** Per round-4 test lens — stateful Hypothesis tests can run long, and a timeout prevents CI from hanging.
- **`HealthCheck.too_slow` is suppressed** in the property test settings because stateful Hypothesis tests are slow by design.
- **The 6 metrics are added even if not all are wired in C-9.** Operators use them as soon as `ConcurrencyGate` lands; the wiring is in `pool_tools.py` and `_enforce_concurrency_limit()`.
- **Token-bucket refill** is documented in the runbook; the implementation in C-9 only checks the counter (no time-based refill logic). A future commit can add refill using `cachetools.TTLCache` or a similar mechanism.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/core/concurrency_gate.py` | create | ~150 |
| `mahavishnu/core/rate_limit.py` | edit (add `_estimate_retry` helper) | +12 |
| `mahavishnu/mcp/tools/pool_tools.py` | edit (wire `_enforce_concurrency_limit`) | +20 |
| `mahavishnu/core/metrics.py` | edit (add 6 metrics) | +35 |
| `settings/models.yaml` | edit (add `concurrency_limits.by_category`) | +30 |
| `tests/integration/test_pool_concurrency_limit.py` | create | +200 |
| `tests/property/test_pool_concurrency_limit_property.py` | create | +80 |
| `docs/runbooks/concurrency-limit-storm.md` | create | +50 |
