"""Two concurrent rebuild invocations serialize via the Dhara-backed lock.

Verifies that when two coroutines race to call run_rebuild_cycle from an
*unlocked* starting state, exactly one acquires the lock and proceeds
while the other raises PlanRebuildLockedError. Mirrors the jot sub-plan 3
lock pattern.

`FakeMCP`'s coroutines never suspend, so `asyncio.gather` runs the
first cycle to completion before the second starts and no interleaving is
possible. `YieldingFakeDhara` inserts a real suspension point before
every operation, which step-locks the two cycles and exercises the
read-then-write race the claim-based acquisition in `cron_core` exists to
close (Task 14.6).
"""

# REQ-PLAN-014: lock serializes concurrent rebuilds

from __future__ import annotations

import asyncio
import time

from mahavishnu.plan_index.cron_core import (
    REBUILD_LOCK_CLAIM_KEY_PREFIX,
    run_rebuild_cycle,
)
from mahavishnu.plan_index.errors import PlanRebuildLockedError
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeMCP


class YieldingFakeDhara(FakeMCP):
    """FakeMCP that yields to the event loop before every operation."""

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        await asyncio.sleep(0)
        await super().put(key, value, ttl=ttl)

    async def get(self, key: str) -> str | None:
        await asyncio.sleep(0)
        return await super().get(key)

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        await asyncio.sleep(0)
        return await super().list_prefix(prefix)

    async def delete(self, key: str) -> None:
        await asyncio.sleep(0)
        await super().delete(key)


class TestConcurrentRebuildsSerialize:
    async def test_two_concurrent_invocations_one_proceeds_one_aborts(self) -> None:
        mcp = YieldingFakeDhara()
        store = PlanIndexStore(mcp)  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()

        # No pre-existing lock: both coroutines start from an unheld lock
        # and race for it. Exactly one must win.
        results = await asyncio.gather(
            run_rebuild_cycle(store, rebuilder),
            run_rebuild_cycle(store, rebuilder),
            return_exceptions=True,
        )
        proceeded = [r for r in results if not isinstance(r, BaseException)]
        aborted = [r for r in results if isinstance(r, PlanRebuildLockedError)]
        assert len(proceeded) == 1, f"expected 1 proceed, got {len(proceeded)}"
        assert len(aborted) == 1, f"expected 1 PlanRebuildLockedError, got {len(aborted)}"

        # The cycle that succeeded released its lock afterwards.
        assert await mcp.get("plan_index/meta/rebuild_lock/holder") is None

        # Arbitration claims are transient: neither the winner nor the
        # loser may leave one behind to block the next cycle.
        assert await mcp.list_prefix(REBUILD_LOCK_CLAIM_KEY_PREFIX) == []

    async def test_a_live_lock_blocks_every_concurrent_invocation(self) -> None:
        """A fresh, non-stale holder aborts *both* racing cycles."""
        mcp = YieldingFakeDhara()
        store = PlanIndexStore(mcp)  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()

        fresh_ms = int(time.time() * 1000)
        await mcp.put("plan_index/meta/rebuild_lock/holder", "otherhost/9999")
        await mcp.put("plan_index/meta/rebuild_lock/acquired_at_ms", str(fresh_ms))

        results = await asyncio.gather(
            run_rebuild_cycle(store, rebuilder),
            run_rebuild_cycle(store, rebuilder),
            return_exceptions=True,
        )
        assert all(isinstance(r, PlanRebuildLockedError) for r in results)
        # The live holder survives — nobody stole or released it.
        assert await mcp.get("plan_index/meta/rebuild_lock/holder") == "otherhost/9999"
