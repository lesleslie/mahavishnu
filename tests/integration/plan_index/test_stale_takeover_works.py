"""Round-3 follow-up: stale takeover retains a lock-history provenance key.

Task 14.7 fix: when Cycle B takes over a stale lock from Cycle A, the
``finally`` block must release only the active lock holder, NOT the
history key. After takeover, ``plan_index/meta/rebuild_lock/history/*``
must contain at least one entry whose ``previous_holder`` matches the
stale Cycle A holder. This is what makes the takeover observability
("Cycle B took over from stale Cycle A at T") durable across cycle exit.
"""

# REQ-PLAN-015: stale-PID detection enables takeover (history provenance)

from __future__ import annotations

import json
import re
import time

from mahavishnu.plan_index.cron_core import (
    REBUILD_LOCK_HISTORY_KEY_PREFIX,
    _hostname_hash,
    run_rebuild_cycle,
)
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestStaleTakeoverWorks:
    async def test_stale_takeover_retains_history_key(self) -> None:
        """After a stale takeover, a history key is preserved on cycle exit.

        Reproduces the Task 14.5 test failure: before the fix, the
        ``finally`` block deleted the history key along with the holder,
        so subsequent cycles had no provenance of the takeover event.
        """
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        dhara = store._dhara  # type: ignore[attr-defined]

        # Plant a lock acquired 5 minutes ago (well past the 60s TTL).
        five_min_ago_ms = int(time.time() * 1000) - 5 * 60 * 1000
        stale_holder = "deadhost/1111"
        await dhara.put("plan_index/meta/rebuild_lock/holder", stale_holder)
        await dhara.put("plan_index/meta/rebuild_lock/acquired_at_ms", str(five_min_ago_ms))

        # Cycle B takes over.
        result = await run_rebuild_cycle(store, rebuilder)
        assert result.cycles_total >= 1

        # The active holder was released (finally block ran).
        new_holder_after = await dhara.get("plan_index/meta/rebuild_lock/holder")
        assert new_holder_after is None, (
            "finally should delete the active lock holder; "
            f"but it is still {new_holder_after!r}"
        )

        # The history key was written and SURVIVED the finally block.
        history_entries = await dhara.list_prefix(REBUILD_LOCK_HISTORY_KEY_PREFIX)
        assert history_entries, (
            "expected at least one lock-history key to be retained "
            f"under prefix {REBUILD_LOCK_HISTORY_KEY_PREFIX!r}"
        )

        # Exactly one takeover was recorded; the payload matches the
        # takeover contract: previous_holder + took_over_at_ms + took_over_by.
        assert len(history_entries) == 1
        history_key, history_value = history_entries[0]
        assert history_key.startswith(REBUILD_LOCK_HISTORY_KEY_PREFIX)
        # The key suffix is a uuid4 hex (32 chars).
        suffix = history_key[len(REBUILD_LOCK_HISTORY_KEY_PREFIX):]
        assert re.fullmatch(r"[0-9a-f]{32}", suffix), (
            f"history key suffix {suffix!r} must be a uuid4 hex string"
        )

        payload = json.loads(history_value)
        assert payload["previous_holder"] == stale_holder
        assert payload["took_over_at_ms"] == five_min_ago_ms + (
            (result.last_rebuild_ms - five_min_ago_ms)
        ) or payload["took_over_at_ms"] >= five_min_ago_ms
        # The new holder must match the redaction regex.
        new_holder = payload["took_over_by"]
        assert re.match(r"^[a-f0-9]{8}/\d+$", new_holder), (
            f"new lock_holder {new_holder!r} must match ^[a-f0-9]{{8}}/\\d+$ "
            "(hostname_hash[:8] + '/' + pid)"
        )
        assert new_holder.startswith(f"{_hostname_hash()}/")

    async def test_fresh_lock_acquisition_does_not_write_history(self) -> None:
        """No takeover == no history key (no false-positive provenance)."""
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        dhara = store._dhara  # type: ignore[attr-defined]

        # No prior holder — fresh acquisition path.
        await run_rebuild_cycle(store, rebuilder)

        history_entries = await dhara.list_prefix(REBUILD_LOCK_HISTORY_KEY_PREFIX)
        assert history_entries == [], (
            "fresh lock acquisition must NOT write a history key; "
            f"got {history_entries!r}"
        )
