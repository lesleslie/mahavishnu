"""Tests for plan_index PeriodicTaskRunner.

REQ-PLAN-013: PeriodicTaskRunner hosts the rebuild cycle on an asyncio loop
with start/stop/force_run semantics; the cycle delegates the actual work to
cron_core.run_rebuild_cycle (kept separate for unit-testability without
asyncio).
"""

from __future__ import annotations

import pytest

from mahavishnu.plan_index.cron import PeriodicTaskRunner
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestPeriodicTaskRunner:
    @pytest.mark.asyncio
    async def test_force_run_increments_cycles(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        runner = PeriodicTaskRunner(store=store, cron_every_seconds=3600)
        await runner.force_run()
        status = await store.rebuild_status()
        assert status["cycles_total"] == 1

    @pytest.mark.asyncio
    async def test_force_run_with_empty_records(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        runner = PeriodicTaskRunner(store=store, cron_every_seconds=3600)
        await runner.force_run()
        # No records → no entities_count > 0
        v = await store.vitals()
        assert v["total"] == 0
        assert v["cycles_total"] == 1
