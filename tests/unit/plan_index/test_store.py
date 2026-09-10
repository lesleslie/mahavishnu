# tests/unit/plan_index/test_store.py
from __future__ import annotations

from dataclasses import replace

import pytest

from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara  # to be added in this task


def _sample_record(plan_id: str = "11111111111111111111111111111111") -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/2026-09-15-foo.md",
        title="Foo",
        status="active",
        role="implementation",
        topic="routing-composition",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


@pytest.fixture
def store() -> PlanIndexStore:
    fake = FakeDhara()
    return PlanIndexStore(dhara=fake)  # type: ignore[arg-type]


class TestUpsertAndGet:
    @pytest.mark.asyncio
    async def test_upsert_then_get_roundtrips(self, store: PlanIndexStore) -> None:
        rec = _sample_record()
        await store.upsert(rec)
        result = await store.get(rec.plan_id)
        assert result is not None
        assert result["plan_id"] == rec.plan_id
        assert result["path"] == rec.path
        assert result["status"] == rec.status


class TestListByStatus:
    @pytest.mark.asyncio
    async def test_list_by_status_filters(self, store: PlanIndexStore) -> None:
        await store.upsert(_sample_record("11" * 16))
        await store.upsert(_sample_record("22" * 16))
        await store.upsert(replace(_sample_record("33" * 16), status="shipped"))
        active = await store.list_by_status("active")
        assert len(active) == 2
        shipped = await store.list_by_status("shipped")
        assert len(shipped) == 1


class TestVitals:
    @pytest.mark.asyncio
    async def test_vitals_empty(self, store: PlanIndexStore) -> None:
        v = await store.vitals()
        assert v["total"] == 0
        assert v["cycles_total"] == 0
        assert v["tripwire"] == "ok"

    @pytest.mark.asyncio
    async def test_vitals_after_upserts(self, store: PlanIndexStore) -> None:
        for i in range(3):
            await store.upsert(_sample_record(str(i + 1) * 16))
        v = await store.vitals()
        assert v["total"] == 3
        assert v["by_status"]["active"] == 3


class TestRebuildStatus:
    @pytest.mark.asyncio
    async def test_rebuild_status_never_ran(self, store: PlanIndexStore) -> None:
        s = await store.rebuild_status()
        assert s["cycles_total"] == 0
        assert s["stale"] is True
        assert "last_rebuild_ms" not in s
