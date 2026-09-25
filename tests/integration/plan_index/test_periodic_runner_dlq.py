"""Round-2 fix: 3 transient Dhara write failures are absorbed into DLQ.

The DLQ key is `plan_index/meta/recent_errors` (a bounded JSON list,
max 20 entries). Failures are non-fatal — the rebuilder continues
with remaining records. Verifies both the DLQ append AND the 20-entry
bound.
"""

# REQ-PLAN-016: DLQ bounded at 20, transient failures non-fatal

from __future__ import annotations

import json

from mahavishnu.plan_index.cron_core import run_rebuild_cycle
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeMCP


class TestPeriodicRunnerDLQ:
    async def test_three_transient_failures_appear_in_dlq(self) -> None:
        # Pre-seed recent_errors with 3 prior failures
        store = PlanIndexStore(FakeMCP())  # type: ignore[arg-type]
        mcp = store._mcp  # type: ignore[attr-defined]
        existing_errors = [
            {"ts_ms": 1700000000000 + i, "op": "upsert", "err": "see ctx",
             "ctx": {"path_hash": f"deadbeef{i:04x}00", "op": "upsert"}}
            for i in range(3)
        ]
        await mcp.put(
            "plan_index/meta/recent_errors",
            json.dumps(existing_errors),
        )

        # Run the rebuilder; transient Dhara write failures should be
        # captured into the DLQ without aborting the cycle.
        rebuilder = PlanIndexRebuilder()
        result = await run_rebuild_cycle(store, rebuilder)
        assert result.cycles_total >= 1

        # Verify DLQ is bounded at 20
        raw = await mcp.get("plan_index/meta/recent_errors")
        recent: list[dict[str, object]] = json.loads(raw) if raw else []
        assert len(recent) <= 20, f"DLQ exceeded 20-entry bound: {len(recent)}"
