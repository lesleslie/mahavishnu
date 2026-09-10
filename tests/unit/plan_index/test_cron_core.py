"""Tests for plan_index cron_core.run_rebuild_cycle.

REQ-PLAN-014/15/16: The cycle acquires a Dhara-backed mutex, scans
records (when repo_root is provided), upserts via the rebuilder, and
appends failures to a bounded recent_errors DLQ (max 20 entries).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mahavishnu.plan_index.cron_core import RebuildOutcome, run_rebuild_cycle
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


def _fake_records() -> list[PlanRecord]:
    return [
        PlanRecord(
            plan_id="11111111111111111111111111111111",
            path="docs/plans/2026-09-10-foo.md",
            title="Foo",
            status="active",
            role="implementation",
            topic="routing-composition",
            date="2026-09-10",
            last_reviewed="2026-09-10",
            superseded_by=None,
            blocks_on=[],
            sha="f" * 40,
            repo="https://github.com/lesleslie/mahavishnu",
            updated_at_ms=1700000000000,
        ),
        PlanRecord(
            plan_id="22222222222222222222222222222222",
            path="docs/plans/2026-09-10-bar.md",
            title="Bar",
            status="active",
            role="implementation",
            topic="routing-composition",
            date="2026-09-10",
            last_reviewed="2026-09-10",
            superseded_by=None,
            blocks_on=[],
            sha="e" * 40,
            repo="https://github.com/lesleslie/mahavishnu",
            updated_at_ms=1700000000000,
        ),
    ]


class TestRunRebuildCycleRealScan:
    @pytest.mark.asyncio
    async def test_cycles_total_increments_even_on_partial_failure(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        with patch(
            "mahavishnu.plan_index.cron_core.discover_records",
            return_value=_fake_records(),
        ):
            with patch.object(
                rebuilder,
                "upsert_all",
                return_value=(1, 1, [{"path_hash": "h", "err": "boom"}]),
            ):
                outcome: RebuildOutcome = await run_rebuild_cycle(
                    store, rebuilder, repo_root=Path("/tmp/fake"),
                )
        assert outcome.cycles_total == 1
        assert outcome.successful_cycles_total == 0

    @pytest.mark.asyncio
    async def test_successful_cycles_only_increments_on_full_success(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        with patch(
            "mahavishnu.plan_index.cron_core.discover_records",
            return_value=_fake_records(),
        ):
            outcome = await run_rebuild_cycle(
                store, rebuilder, repo_root=Path("/tmp/fake"),
            )
        assert outcome.errors == 0
        assert outcome.successful_cycles_total == 1
        entities_raw = await store._dhara.get("plan_index/meta/entities_count")  # type: ignore[attr-defined]
        assert int(entities_raw) == outcome.entities_count

    @pytest.mark.asyncio
    async def test_recent_errors_bounded_at_20(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()
        dhara = store._dhara  # type: ignore[attr-defined]
        seed = [{"ts_ms": i, "op": "upsert", "err": "old", "ctx": {}} for i in range(25)]
        await dhara.put("plan_index/meta/recent_errors", json.dumps(seed))
        with patch(
            "mahavishnu.plan_index.cron_core.discover_records",
            return_value=_fake_records(),
        ):
            with patch.object(
                rebuilder, "upsert_all",
                return_value=(0, 1, [{"path_hash": "h", "err": "boom"}]),
            ):
                await run_rebuild_cycle(store, rebuilder, repo_root=Path("/tmp/fake"))
        recent_raw = await dhara.get("plan_index/meta/recent_errors")
        recent: list[dict[str, object]] = json.loads(recent_raw) if recent_raw else []
        assert len(recent) <= 20
