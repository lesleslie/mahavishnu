"""Tests for governed learning and skill promotion artifacts."""

from __future__ import annotations

import pytest

from mahavishnu.core import (
    LearningArtifactType,
    LearningEvidence,
    SkillPromotionPolicy,
    SkillPromotionState,
    SkillDraft,
    SkillRollback,
    SkillReview,
    SkillReviewDecision,
)


def test_learning_evidence_and_artifact_types() -> None:
    evidence = LearningEvidence(
        session_id="sess-1",
        goal="review code",
        outcome="success",
        repo_paths=["repo-a"],
        tool_calls=["mcp:review"],
        observations=["good result"],
    )

    assert evidence.evidence_id.startswith("le_")
    assert evidence.repo_paths == ["repo-a"]
    assert LearningArtifactType.EVIDENCE.value == "learning_evidence"
    assert LearningArtifactType.SKILL_DRAFT.value == "skill_draft"


def test_skill_draft_requires_trigger_conditions() -> None:
    with pytest.raises(ValueError, match="trigger_conditions"):
        SkillDraft(
            name="security-review",
            version="1.0.0",
            description="Review security issues",
            trigger_conditions=[],
            body="Do the review",
        )


def test_review_requires_changes_when_not_approved() -> None:
    with pytest.raises(ValueError, match="required_changes"):
        SkillReview(
            skill_id="skill-1",
            reviewer="les",
            decision=SkillReviewDecision.REJECT,
            rationale="Needs work",
            required_changes=[],
        )


def test_promotion_policy_requires_approved_review_before_activation() -> None:
    policy = SkillPromotionPolicy()
    draft = SkillDraft(
        name="security-review",
        version="1.0.0",
        description="Review security issues",
        trigger_conditions=["security", "review"],
        body="Focus on auth and secrets",
        source_evidence_ids=["ev-1"],
    )
    review = SkillReview(
        skill_id=draft.skill_id,
        reviewer="reviewer-1",
        decision=SkillReviewDecision.APPROVE,
        rationale="Looks good",
    )

    activation = policy.promote_draft(draft, review, activated_by="mahavishnu")

    assert activation.skill_id == draft.skill_id
    assert activation.version == "1.0.0"
    assert activation.previous_state == SkillPromotionState.REVIEW
    assert activation.approved_review_id == review.review_id


def test_policy_rejects_invalid_transitions_and_rollback_versions() -> None:
    policy = SkillPromotionPolicy()

    with pytest.raises(ValueError, match="Invalid skill promotion transition"):
        policy.validate_transition(SkillPromotionState.DRAFT, SkillPromotionState.ACTIVE)

    with pytest.raises(ValueError, match="from_version and to_version must be different"):
        SkillRollback(
            skill_id="skill-1",
            from_version="1.0.0",
            to_version="1.0.0",
            reason="no-op",
            performed_by="mahavishnu",
        )

    rollback = policy.rollback_skill(
        skill_id="skill-1",
        from_version="2.0.0",
        to_version="1.0.0",
        performed_by="mahavishnu",
        reason="regression",
    )

    assert rollback.from_version == "2.0.0"
    assert rollback.to_version == "1.0.0"
    assert rollback.rollback_id.startswith("rb_")

