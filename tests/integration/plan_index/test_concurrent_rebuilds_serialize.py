"""Two concurrent rebuild invocations serialize via the Dhara-backed lock.

Verifies that when two coroutines race to call run_rebuild_cycle,
exactly one acquires the lock and proceeds while the other sees the
non-stale lock and raises PlanRebuildLockedError. Mirrors the jot
sub-plan 3 lock pattern.
"""

# REQ-PLAN-014: lock serializes concurrent rebuilds

from __future__ import annotations

import asyncio
import time

from mahavishnu.plan_index.cron_core import run_rebuild_cycle
from mahavishnu.plan_index.errors import PlanRebuildLockedError
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestConcurrentRebuildsSerialize:
    async def test_two_concurrent_invocations_one_proceeds_one_aborts(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()

        # Pre-acquire the lock with a FRESH timestamp (TTL not yet expired)
        # so the second coroutine sees a non-stale holder and aborts.
        dhara = store._dhara  # type: ignore[attr-defined]
        await dhara.put("plan_index/meta/rebuild_lock/holder", "otherhost/9999")
        fresh_ms = int(time.time() * 1000)
        await dhara.put(
            "plan_index/meta/rebuild_lock/acquired_at_ms", str(fresh_ms)
        )

        results = await asyncio.gather(
            run_rebuild_cycle(store, rebuilder),
            run_rebuild_cycle(store, rebuilder),
            return_exceptions=True,
        )
        # Exactly one proceeds, exactly one raises PlanRebuildLockedError.
        proceeded = [r for r in results if not isinstance(r, BaseException)]
        aborted = [r for r in results if isinstance(r, PlanRebuildLockedError)]
        assert len(proceeded) == 1, f"expected 1 proceed, got {len(proceeded)}"
        assert len(aborted) == 1, f"expected 1 PlanRebuildLockedError, got {len(aborted)}"

        # The cycle that succeeded released its lock afterwards.
        holder_after = await dhara.get("plan_index/meta/rebuild_lock/holder")
        # Either deleted (None) or overwritten by our local holder — both are valid.
        assert holder_after is None or holder_after != "otherhost/9999"
