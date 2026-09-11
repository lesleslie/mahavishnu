"""Round-2 fix: lock written 5+ minutes old is treated as stale.

The lock key includes `lock_acquired_at_ms`; if that timestamp is more
than REBUILD_LOCK_TTL_SECONDS (60s by default) in the past, the next
run_rebuild_cycle takes over the lock (the prior holder is presumed
dead). Verifies this takeover path AND that the new holder matches
the redaction regex `^[a-f0-9]{8}/\\d+$` (hostname_hash[:8] + pid).
"""

# REQ-PLAN-015: stale-PID detection enables takeover

from __future__ import annotations

import re
import time

from mahavishnu.plan_index.cron_core import _hostname_hash, run_rebuild_cycle
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestStalePidTakeover:
    async def test_stale_lock_takeover_succeeds(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        dhara = store._dhara  # type: ignore[attr-defined]

        # Write a lock with an acquisition timestamp 5 minutes in the past
        # (well past REBUILD_LOCK_TTL_SECONDS = 60s, so it is stale).
        five_min_ago_ms = int(time.time() * 1000) - 5 * 60 * 1000
        await dhara.put("plan_index/meta/rebuild_lock/holder", "deadhost/1111")
        await dhara.put("plan_index/meta/rebuild_lock/acquired_at_ms", str(five_min_ago_ms))

        # The next run_rebuild_cycle takes over the stale lock.
        result = await run_rebuild_cycle(store, rebuilder)
        assert result.cycles_total >= 1

        # The new holder is recorded AND matches the redaction regex.
        new_holder = await dhara.get("plan_index/meta/rebuild_lock/holder")
        assert new_holder is not None
        assert new_holder != "deadhost/1111"
        assert re.match(r"^[a-f0-9]{8}/\d+$", new_holder), (
            f"new lock_holder {new_holder!r} must match ^[a-f0-9]{{8}}/\\d+$ "
            "(hostname_hash[:8] + '/' + pid)"
        )
        # And it should match THIS host's hostname_hash prefix.
        assert new_holder.startswith(f"{_hostname_hash()}/"), (
            f"new_holder {new_holder!r} should start with local hostname_hash"
        )
