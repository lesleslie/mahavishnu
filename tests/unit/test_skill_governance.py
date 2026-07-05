"""Tests for governed learning and skill promotion artifacts."""

from __future__ import annotations

import pytest

from mahavishnu.core import (
    LearningArtifactType,
    LearningEvidence,
    SkillDraft,
    SkillPromotionPolicy,
    SkillPromotionState,
    SkillReview,
    SkillReviewDecision,
    SkillRollback,
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


def test_validate_review_rejects_non_approved_review() -> None:
    """validate_review_for_activation raises for non-APPROVE decisions (line 187)."""
    policy = SkillPromotionPolicy()
    review = SkillReview(
        skill_id="skill-x",
        reviewer="reviewer",
        decision=SkillReviewDecision.REJECT,
        rationale="Needs work",
        required_changes=["fix bug"],
    )
    with pytest.raises(ValueError, match="approved review"):
        policy.validate_review_for_activation(review)


def test_validate_review_rejects_required_changes() -> None:
    """validate_review_for_activation raises when required_changes is non-empty (line 189)."""
    policy = SkillPromotionPolicy()
    review = SkillReview(
        skill_id="skill-x",
        reviewer="reviewer",
        decision=SkillReviewDecision.APPROVE,
        rationale="Almost there",
        required_changes=["tweak docstring"],
    )
    with pytest.raises(ValueError, match="required changes"):
        policy.validate_review_for_activation(review)


def test_promote_draft_rejects_active_state() -> None:
    """promote_draft raises when draft.state is not DRAFT or REVIEW (line 202)."""

    policy = SkillPromotionPolicy()
    draft = SkillDraft(
        name="dep-skill",
        version="1.0.0",
        description="Deprecated skill",
        trigger_conditions=["dep"],
        body="Do nothing",
        source_evidence_ids=["ev-1"],
    )
    review = SkillReview(
        skill_id=draft.skill_id,
        reviewer="reviewer",
        decision=SkillReviewDecision.APPROVE,
        rationale="ok",
    )
    # Activate first so draft.state becomes ACTIVE
    policy.promote_draft(draft, review, activated_by="ci")
    draft.state = SkillPromotionState.ACTIVE  # simulate already-active

    with pytest.raises(ValueError, match="DRAFT or REVIEW"):
        policy.promote_draft(draft, review, activated_by="ci")


def test_deprecate_nonexistent_skill_raises() -> None:
    """SkillRegistry.deprecate raises ValueError for unknown skill (line 120)."""
    from mahavishnu.core.skill_registry import SkillRegistry

    policy = SkillPromotionPolicy()
    registry = SkillRegistry(policy=policy)
    with pytest.raises(ValueError, match="No active version found"):
        registry.deprecate("nonexistent-skill", deprecated_by="ci")
