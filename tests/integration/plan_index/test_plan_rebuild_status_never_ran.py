"""Round-2 e2e: ``plan_rebuild_status`` against a fresh Dhara substrate.

REQ-PLAN-007 (§4 §6.4, empty-substrate coverage): when no rebuilder has
fired yet, the tool returns:
  - ``last_rebuild_ms`` absent or ``None``
  - ``cycles_total == 0``
  - ``successful_cycles_total == 0``
  - ``errors_total == 0``
  - ``recent_errors == []``
  - ``stale is True`` (per spec §6: no last_rebuild_ms ⇒ stale)
"""

from __future__ import annotations

from typing import Any


class TestPlanRebuildStatusNeverRan:
    async def test_fresh_dhara_reports_stale(self, call_tool: Any) -> None:
        """No rebuilder has fired; the tool surfaces the "never ran" envelope."""
        result = await call_tool("plan_rebuild_status", {})

        assert result["cycles_total"] == 0
        assert result["successful_cycles_total"] == 0
        assert result["errors_total"] == 0
        assert result["recent_errors"] == []
        assert result["stale"] is True
        # last_rebuild_ms absent or explicitly None — store contract
        assert result.get("last_rebuild_ms") is None
        # last_success_ms absent or explicitly None
        assert result.get("last_success_ms") is None

    async def test_recent_rebuilder_run_unmarks_stale(
        self, call_tool: Any, store: Any
    ) -> None:
        """Seeding ``last_rebuild_ms`` to a recent timestamp clears the stale flag.

        Documents the staleness rule (spec §6): ``stale`` is False only
        when ``now - last_rebuild_ms <= 5 hours``. We seed within that
        window to confirm the flag flips.
        """
        # Within the 5-hour staleness window.
        import time

        recent_ms = int(time.time() * 1000) - 60 * 1000  # 60s ago
        await store._dhara.put(
            "plan_index/meta/last_rebuild_ms", str(recent_ms)
        )

        result = await call_tool("plan_rebuild_status", {})

        assert result["stale"] is False
        assert result["last_rebuild_ms"] == recent_ms
