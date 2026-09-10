"""Tests for plan_index PlanRecord dataclass."""

from __future__ import annotations

import pytest

from mahavishnu.plan_index.record import PlanRecord


def _sample(**overrides: object) -> PlanRecord:
    defaults: dict[str, object] = {
        "plan_id": "abcdef0123456789abcdef0123456789",  # 32 hex chars
        "path": "docs/plans/2026-09-15-foo.md",
        "title": "Foo",
        "status": "draft",
        "role": "implementation",
        "topic": "routing-composition",
        "date": "2026-09-15",
        "last_reviewed": "2026-09-15",
        "superseded_by": None,
        "blocks_on": [],
        "sha": "f" * 40,
        "repo": "github.com/example/repo",
        "updated_at_ms": 1700000000000,
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return PlanRecord(**defaults)  # type: ignore[arg-type]


class TestPlanRecordShape:
    def test_required_fields_construct(self) -> None:
        rec = _sample()
        assert rec.plan_id == "abcdef0123456789abcdef0123456789"
        assert rec.path == "docs/plans/2026-09-15-foo.md"
        assert rec.status == "draft"

    def test_frozen_prevents_mutation(self) -> None:
        rec = _sample()
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
            rec.title = "Bar"  # type: ignore[misc]

    def test_kw_only_required(self) -> None:
        # Positional args are rejected at construction
        with pytest.raises(TypeError):
            PlanRecord("id", "path", "title")  # type: ignore[call-arg,arg-type]

    def test_status_literal_rejected_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            _sample(status="in-review")  # type: ignore[arg-type]

    def test_role_literal_rejected_at_runtime(self) -> None:
        with pytest.raises(ValueError):
            _sample(role="spec")  # type: ignore[arg-type]

    def test_lifecycle_state_default_is_none(self) -> None:
        rec = _sample()
        assert rec.lifecycle_state is None

    def test_lifecycle_state_accepts_feature_tracking_values(self) -> None:
        rec = _sample(lifecycle_state="adopted")
        assert rec.lifecycle_state == "adopted"


class TestPlanRecordBlocksOn:
    def test_blocks_on_accepts_plan_ids(self) -> None:
        rec = _sample(blocks_on=["11111111111111111111111111111111", "22222222222222222222222222222222"])
        assert len(rec.blocks_on) == 2

    def test_blocks_on_empty_default(self) -> None:
        rec = _sample()
        assert rec.blocks_on == []
