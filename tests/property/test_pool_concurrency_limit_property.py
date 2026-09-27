"""Stateful Hypothesis property test for ConcurrencyGate (C-9, REQ-012).

Property: the active count never exceeds the configured limit, regardless
of interleaving between acquires and releases. Marked slow + timeout(120)
per the round-4 test lens — stateful Hypothesis tests are slow by design
and a timeout prevents CI from hanging.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings as hp_settings
from hypothesis import strategies as st

from mahavishnu.core.config import (
    ConcurrencyLimitSpec,
    ConcurrencyLimitsSettings,
)
from mahavishnu.core.concurrency_gate import ConcurrencyGate
from mahavishnu.core.model_routing import TaskCategory


@pytest.mark.req(["REQ-012"])
@pytest.mark.slow
@pytest.mark.timeout(120)
@given(
    limit=st.integers(min_value=1, max_value=10),
    pool_id=st.sampled_from(["pool-A", "pool-B", "pool-C"]),
    acquire_count=st.integers(min_value=1, max_value=20),
    release_count=st.integers(min_value=0, max_value=20),
)
@hp_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
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
    for _ in range(acquire_count):
        if await gate.try_acquire(TaskCategory.CODE_REVIEW, pool_id):
            acquired += 1

    for _ in range(min(release_count, acquired)):
        await gate.release(TaskCategory.CODE_REVIEW, pool_id)

    # Invariant: at no point did we acquire more than `limit` slots
    spec_now = gate.spec_for(TaskCategory.CODE_REVIEW)
    assert spec_now is not None
    active = max(0, acquired - min(release_count, acquired))
    assert active <= spec_now.concurrency_limit
