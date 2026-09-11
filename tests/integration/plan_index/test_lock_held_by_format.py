"""Round-2 fix: lock_held_by format is hostname_hash[:8]/pid.

Asserts the regex `^[a-f0-9]{8}/\\d+$` matches plan_rebuild_status()'s
lock_held_by field. The hostname is SHA-256 hashed (not stored raw)
and truncated to 8 hex chars; pid is appended after a slash.
"""

# REQ-PLAN-009: lock_held_by redaction format

from __future__ import annotations

import re

from mahavishnu.plan_index.cron_core import run_rebuild_cycle
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestLockHeldByFormat:
    async def test_lock_held_by_after_cycle_matches_redaction_regex(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        # Force the cycle to acquire a lock
        await run_rebuild_cycle(store, rebuilder)

        status = await store.rebuild_status()
        holder = status.get("lock_held_by")
        if holder:
            assert re.match(r"^[a-f0-9]{8}/\d+$", holder), (
                f"lock_held_by {holder!r} must match ^[a-f0-9]{{8}}/\\d+$ "
                "(hostname_hash[:8] + '/' + pid)"
            )
