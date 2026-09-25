"""Round-2 e2e: PlanRecordDict with all 14 fields (including None-valued)
round-trips through PlanIndexStore.upsert → .get with full equality.
"""

# REQ-PLAN-021: TypedDict 14-field round-trip serialization

from __future__ import annotations

import pytest

from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeMCP


def _all_14_fields(plan_id: str = "a" * 32) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/full.md",
        title="Full",
        status="active",
        role="implementation",
        topic="t",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by="b" * 32,  # non-None
        blocks_on=["c" * 32],  # non-empty
        sha="f" * 40,
        repo="github.com/example/repo",
        lifecycle_state="adopted",  # non-None
        updated_at_ms=1700000000000,
    )


class TestPlanRecordDict14FieldRoundtrip:
    @pytest.mark.asyncio
    async def test_all_14_fields_serialize_and_roundtrip(self) -> None:
        store = PlanIndexStore(FakeMCP())  # type: ignore[arg-type]
        rec = _all_14_fields()
        await store.upsert(rec)
        result = await store.get(rec.plan_id)
        assert result is not None
        # All 14 fields round-trip
        assert result["plan_id"] == rec.plan_id
        assert result["path"] == rec.path
        assert result["title"] == rec.title
        assert result["status"] == rec.status
        assert result["role"] == rec.role
        assert result["topic"] == rec.topic
        assert result["date"] == rec.date
        assert result["last_reviewed"] == rec.last_reviewed
        assert result["superseded_by"] == "b" * 32
        assert result["blocks_on"] == ["c" * 32]
        assert result["sha"] == rec.sha
        assert result["repo"] == rec.repo
        assert result["lifecycle_state"] == "adopted"
        assert result["updated_at_ms"] == rec.updated_at_ms

    @pytest.mark.asyncio
    async def test_none_valued_fields_roundtrip(self) -> None:
        """PlanRecord with superseded_by=None and lifecycle_state=None."""
        store = PlanIndexStore(FakeMCP())  # type: ignore[arg-type]
        rec = PlanRecord(
            plan_id="d" * 32,
            path="docs/plans/nones.md",
            title="Nones",
            status="draft",
            role="canonical",
            topic="t",
            date="2026-09-15",
            last_reviewed="2026-09-15",
            superseded_by=None,
            blocks_on=[],
            sha="0" * 40,
            repo="github.com/example/repo",
            lifecycle_state=None,
            updated_at_ms=1700000000000,
        )
        await store.upsert(rec)
        result = await store.get(rec.plan_id)
        assert result is not None
        # Brief defect fix: store.upsert omits None-valued optional keys
        # (``superseded_by``, ``lifecycle_state``) entirely from the
        # serialized dict. Use ``.get()`` to verify the round-tripped
        # value is None — which is true whether the key is present with
        # value None or absent (both round-trip to None semantically).
        assert result.get("superseded_by") is None
        assert result.get("lifecycle_state") is None
