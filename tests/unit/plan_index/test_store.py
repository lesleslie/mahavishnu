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


class TestTTLConsistency:
    @pytest.mark.asyncio
    async def test_secondary_indexes_have_ttl(self, store: PlanIndexStore) -> None:
        rec = _sample_record()
        d = store._to_dict(rec)
        await store.upsert(rec)
        fake = store._dhara
        for key in (
            store._primary_key(rec.plan_id),
            store._status_key(d),
            store._topic_key(d),
        ):
            assert await fake.get(key) is not None
            assert fake.get_ttl(key) == 86400  # type: ignore[attr-defined]


class TestAtomicity:
    @pytest.mark.asyncio
    async def test_primary_failure_removes_secondaries(self, store: PlanIndexStore) -> None:
        rec = _sample_record()
        d = store._to_dict(rec)
        fake = store._dhara
        original_put = fake.put

        async def failing_put(key: str, value: str, *, ttl: int | None = None) -> None:
            if key == store._primary_key(rec.plan_id):
                raise RuntimeError("dhara down")
            await original_put(key, value, ttl=ttl)

        fake.put = failing_put  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="dhara down"):
            await store.upsert(rec)
        fake.put = original_put  # type: ignore[method-assign]

        assert await fake.get(store._status_key(d)) is None
        assert await fake.get(store._topic_key(d)) is None


class TestCorruptedValues:
    @pytest.mark.asyncio
    async def test_get_corrupted_returns_none(self, store: PlanIndexStore) -> None:
        rec = _sample_record()
        await store._dhara.put(store._primary_key(rec.plan_id), "not-json")
        assert await store.get(rec.plan_id) is None

    @pytest.mark.asyncio
    async def test_list_by_status_skips_corrupted(self, store: PlanIndexStore) -> None:
        good = _sample_record("aa" * 16)
        await store.upsert(good)
        await store._dhara.put("plan_index/status/active/2026-09-15/bbbbbbbb", "not-json")
        records = await store.list_by_status("active")
        assert len(records) == 1
        assert records[0]["plan_id"] == good.plan_id

    @pytest.mark.asyncio
    async def test_vitals_corrupted_counters_default_to_zero(self, store: PlanIndexStore) -> None:
        await store._dhara.put("plan_index/meta/cycles_total", "not-an-int")
        await store._dhara.put("plan_index/meta/errors_total", "oops")
        await store._dhara.put("plan_index/meta/recent_errors", "{{{")
        v = await store.vitals()
        assert v["cycles_total"] == 0
        assert v["errors_total"] == 0
        assert v["recent_errors"] == []

    @pytest.mark.asyncio
    async def test_rebuild_status_corrupted_counters(self, store: PlanIndexStore) -> None:
        await store._dhara.put("plan_index/meta/cycles_total", "nope")
        await store._dhara.put("plan_index/meta/last_rebuild_ms", "nope")
        s = await store.rebuild_status()
        assert s["cycles_total"] == 0
        assert "last_rebuild_ms" not in s

    @pytest.mark.asyncio
    async def test_search_tolerates_missing_fields(self, store: PlanIndexStore) -> None:
        await store._dhara.put("plan_index/" + "cc" * 16, '{"plan_id": "x"}')
        assert await store.search("foo") == []


class TestValidation:
    @pytest.mark.asyncio
    async def test_list_by_status_invalid(self, store: PlanIndexStore) -> None:
        with pytest.raises(ValueError, match="invalid status"):
            await store.list_by_status("not-a-status")

    @pytest.mark.asyncio
    async def test_get_invalid_plan_id(self, store: PlanIndexStore) -> None:
        with pytest.raises(ValueError, match="invalid plan_id"):
            await store.get("not-hex")

    @pytest.mark.asyncio
    async def test_get_uppercase_plan_id_rejected(self, store: PlanIndexStore) -> None:
        with pytest.raises(ValueError, match="invalid plan_id"):
            await store.get("A" * 32)

    @pytest.mark.asyncio
    async def test_list_by_topic_invalid_charset(self, store: PlanIndexStore) -> None:
        with pytest.raises(ValueError, match="invalid topic"):
            await store.list_by_topic("../etc/passwd")

    @pytest.mark.asyncio
    async def test_list_by_topic_too_long(self, store: PlanIndexStore) -> None:
        with pytest.raises(ValueError, match="invalid topic"):
            await store.list_by_topic("a" * 101)

    @pytest.mark.asyncio
    async def test_list_by_topic_valid(self, store: PlanIndexStore) -> None:
        await store.upsert(_sample_record("dd" * 16))
        found = await store.list_by_topic("routing-composition")
        assert len(found) == 1
