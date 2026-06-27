"""Unit tests for mahavishnu/distill/skill_pipeline.py.

Spec #5: three-zone skill pipeline (intake, transform, publish) + audit log.

The Dhara-backed implementation is a follow-up (Workstream B: substrate).
These tests pin the interface and the InMemory implementation so the
Dhara implementation can be swapped in without breaking callers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from mahavishnu.distill.skill_pipeline import (
    DharaSkillPipeline,
    InMemorySkillPipeline,
    SkillPipeline,
    SkillTransition,
    SkillZone,
)


# ---------------------------------------------------------------------------
# SkillZone enum
# ---------------------------------------------------------------------------


class TestSkillZone:
    def test_zone_members(self) -> None:
        assert SkillZone.INTAKE.name == "INTAKE"
        assert SkillZone.TRANSFORM.name == "TRANSFORM"
        assert SkillZone.PUBLISH.name == "PUBLISH"

    def test_zone_count(self) -> None:
        # Three zones is the architectural contract (Spec #5 G4 / Data Flow).
        assert len(SkillZone) == 3

    def test_zone_values_are_strings(self) -> None:
        for zone in SkillZone:
            assert isinstance(zone.value, str)
            assert zone.value == zone.name.lower()


# ---------------------------------------------------------------------------
# SkillTransition dataclass
# ---------------------------------------------------------------------------


class TestSkillTransition:
    def test_required_fields(self) -> None:
        ts = SkillTransition(
            transition_id="abc-123",
            skill_name="my_skill",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:agent:worker-1",
            reason="passed lint",
            content_hash="deadbeef",
        )
        assert ts.transition_id == "abc-123"
        assert ts.skill_name == "my_skill"
        assert ts.from_zone == SkillZone.INTAKE
        assert ts.to_zone == SkillZone.TRANSFORM
        assert ts.actor == "system:agent:worker-1"
        assert ts.reason == "passed lint"
        assert ts.content_hash == "deadbeef"

    def test_default_optional_fields(self) -> None:
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:cli",
            reason="",
            content_hash="0" * 64,
        )
        assert ts.confidence is None
        assert isinstance(ts.transition_at, datetime)
        # Default timestamp should be UTC-aware and close to "now".
        assert ts.transition_at.tzinfo is not None
        delta = datetime.now(UTC) - ts.transition_at
        assert abs(delta.total_seconds()) < 5

    def test_confidence_field_optional(self) -> None:
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.TRANSFORM,
            to_zone=SkillZone.PUBLISH,
            actor="system:agent:worker-2",
            reason="human approval",
            content_hash="0" * 64,
            confidence=87,
        )
        assert ts.confidence == 87

    def test_immutable_after_creation(self) -> None:
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:cli",
            reason="",
            content_hash="0" * 64,
        )
        with pytest.raises(Exception):
            ts.skill_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SkillPipeline interface
# ---------------------------------------------------------------------------


class TestSkillPipelineInterface:
    def test_in_memory_implements_protocol(self) -> None:
        pipeline: SkillPipeline = InMemorySkillPipeline()
        assert isinstance(pipeline, SkillPipeline)

    def test_dhara_stub_raises_not_implemented(self) -> None:
        pipeline = DharaSkillPipeline()
        with pytest.raises(NotImplementedError):
            pipeline.record_transition(
                SkillTransition(
                    transition_id="t1",
                    skill_name="s1",
                    from_zone=SkillZone.INTAKE,
                    to_zone=SkillZone.TRANSFORM,
                    actor="system:cli",
                    reason="",
                    content_hash="0" * 64,
                )
            )


# ---------------------------------------------------------------------------
# InMemorySkillPipeline
# ---------------------------------------------------------------------------


class TestInMemorySkillPipeline:
    def test_starts_empty(self) -> None:
        pipeline = InMemorySkillPipeline()
        assert pipeline.history() == []

    def test_record_transition_appends(self) -> None:
        pipeline = InMemorySkillPipeline()
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:agent:w1",
            reason="auto",
            content_hash="0" * 64,
        )
        pipeline.record_transition(ts)
        history = pipeline.history()
        assert len(history) == 1
        assert history[0].transition_id == "t1"

    def test_history_for_filters_by_skill(self) -> None:
        pipeline = InMemorySkillPipeline()
        for i, name in enumerate(["a", "b", "a"]):
            pipeline.record_transition(
                SkillTransition(
                    transition_id=f"t{i}",
                    skill_name=name,
                    from_zone=SkillZone.INTAKE,
                    to_zone=SkillZone.TRANSFORM,
                    actor="system:cli",
                    reason="",
                    content_hash="0" * 64,
                )
            )
        a_history = pipeline.history_for("a")
        assert len(a_history) == 2
        assert all(t.skill_name == "a" for t in a_history)
        b_history = pipeline.history_for("b")
        assert len(b_history) == 1

    def test_history_is_append_only_no_clear(self) -> None:
        # Audit log is append-only (Spec #5 G3 / Schema note).
        pipeline = InMemorySkillPipeline()
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:cli",
            reason="",
            content_hash="0" * 64,
        )
        pipeline.record_transition(ts)
        # No method exists to delete or modify prior transitions.
        assert not hasattr(pipeline, "delete_transition")
        assert not hasattr(pipeline, "update_transition")
        # And the entry is still there.
        assert len(pipeline.history()) == 1

    def test_record_rejects_duplicate_transition_id(self) -> None:
        # Idempotency on PK collision - audit log is append-only with PK.
        pipeline = InMemorySkillPipeline()
        ts = SkillTransition(
            transition_id="dup",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:cli",
            reason="",
            content_hash="0" * 64,
        )
        pipeline.record_transition(ts)
        with pytest.raises(ValueError, match="duplicate"):
            pipeline.record_transition(ts)

    def test_content_hash_helper_accepts_bytes(self) -> None:
        # Convenience: most callers hash file contents or strings.
        pipeline = InMemorySkillPipeline()
        expected = hashlib.sha256(b"hello").hexdigest()
        ts = SkillTransition(
            transition_id="t1",
            skill_name="s1",
            from_zone=SkillZone.INTAKE,
            to_zone=SkillZone.TRANSFORM,
            actor="system:cli",
            reason="",
            content_hash=expected,
        )
        pipeline.record_transition(ts)
        assert pipeline.history()[0].content_hash == expected
