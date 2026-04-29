"""Governed learning and skill promotion artifacts for Bodai.

This module defines the canonical Phase 1 learning artifacts and the
review-gated state machine used to promote generated skills.

The module is intentionally lightweight:
- it defines schemas and policy
- it does not own persistence
- it does not auto-activate skills
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class LearningArtifactType(StrEnum):
    """Artifact types produced by the governed learning pipeline."""

    EVIDENCE = "learning_evidence"
    SKILL_DRAFT = "skill_draft"
    SKILL_REVIEW = "skill_review"
    SKILL_ACTIVATION = "skill_activation"
    SKILL_ROLLBACK = "skill_rollback"


class SkillPromotionState(StrEnum):
    """Promotion states for skills and skill drafts."""

    DRAFT = "draft"
    REVIEW = "review"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillReviewDecision(StrEnum):
    """Allowed review decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class LearningEvidence(BaseModel):
    """Evidence captured from a successful or failed run."""

    evidence_id: str = Field(default_factory=lambda: f"le_{uuid4().hex}")
    session_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    outcome: str = Field(min_length=1, description="Outcome label or summary")
    repo_paths: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class SkillDraft(BaseModel):
    """Drafted skill awaiting review."""

    skill_id: str = Field(default_factory=lambda: f"skill_{uuid4().hex}")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    trigger_conditions: list[str] = Field(default_factory=list)
    body: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(default_factory=list)
    proposed_by: str = Field(default="ecosystem", min_length=1)
    state: SkillPromotionState = Field(default=SkillPromotionState.DRAFT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_trigger_conditions(self) -> "SkillDraft":
        if not self.trigger_conditions:
            raise ValueError("trigger_conditions must contain at least one condition")
        return self


class SkillReview(BaseModel):
    """Human review decision for a skill draft."""

    review_id: str = Field(default_factory=lambda: f"sr_{uuid4().hex}")
    skill_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    decision: SkillReviewDecision = Field(default=SkillReviewDecision.REQUEST_CHANGES)
    rationale: str = Field(min_length=1)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    required_changes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_required_changes(self) -> "SkillReview":
        if self.decision in {SkillReviewDecision.REJECT, SkillReviewDecision.REQUEST_CHANGES}:
            if not self.required_changes:
                raise ValueError("required_changes must be provided when review is not approved")
        return self


class SkillActivation(BaseModel):
    """Activation record for a reviewed skill draft."""

    activation_id: str = Field(default_factory=lambda: f"sa_{uuid4().hex}")
    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    approved_review_id: str = Field(min_length=1)
    previous_state: SkillPromotionState = Field(default=SkillPromotionState.REVIEW)
    activated_by: str = Field(min_length=1)
    activated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class SkillRollback(BaseModel):
    """Rollback record for a previously activated skill version."""

    rollback_id: str = Field(default_factory=lambda: f"rb_{uuid4().hex}")
    skill_id: str = Field(min_length=1)
    from_version: str = Field(min_length=1)
    to_version: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    performed_by: str = Field(min_length=1)
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_version_pair(self) -> "SkillRollback":
        if self.from_version == self.to_version:
            raise ValueError("from_version and to_version must be different")
        return self


@dataclass(slots=True)
class SkillPromotionPolicy:
    """Review-gated transition policy for generated skills."""

    allow_autopromotion: bool = False

    @staticmethod
    def allowed_transitions() -> dict[SkillPromotionState, set[SkillPromotionState]]:
        return {
            SkillPromotionState.DRAFT: {SkillPromotionState.REVIEW},
            SkillPromotionState.REVIEW: {SkillPromotionState.ACTIVE, SkillPromotionState.DEPRECATED},
            SkillPromotionState.ACTIVE: {SkillPromotionState.DEPRECATED},
            SkillPromotionState.DEPRECATED: set(),
        }

    def can_transition(
        self,
        current_state: SkillPromotionState,
        next_state: SkillPromotionState,
    ) -> bool:
        return next_state in self.allowed_transitions().get(current_state, set())

    def validate_transition(
        self,
        current_state: SkillPromotionState,
        next_state: SkillPromotionState,
    ) -> None:
        if not self.can_transition(current_state, next_state):
            raise ValueError(
                f"Invalid skill promotion transition: {current_state.value} -> {next_state.value}"
            )

    def validate_review_for_activation(self, review: SkillReview) -> None:
        if review.decision != SkillReviewDecision.APPROVE:
            raise ValueError("Skill activation requires an approved review")
        if review.required_changes:
            raise ValueError("Approved reviews must not include required changes")
        if self.allow_autopromotion:
            raise ValueError("Autopromotion is disabled in the Bodai governance model")

    def promote_draft(
        self,
        draft: SkillDraft,
        review: SkillReview,
        activated_by: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SkillActivation:
        """Create an activation record after validating the review gate."""

        if draft.state != SkillPromotionState.REVIEW:
            raise ValueError(
                f"promote_draft requires a draft in REVIEW state, got {draft.state.value}"
            )
        self.validate_review_for_activation(review)
        if review.skill_id != draft.skill_id:
            raise ValueError("Review skill_id does not match the draft")

        self.validate_transition(SkillPromotionState.REVIEW, SkillPromotionState.ACTIVE)
        return SkillActivation(
            skill_id=draft.skill_id,
            version=draft.version,
            approved_review_id=review.review_id,
            previous_state=SkillPromotionState.REVIEW,
            activated_by=activated_by,
            metadata=metadata or {},
        )

    def deprecate_skill(
        self,
        skill_id: str,
        version: str,
        deprecated_by: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SkillActivation:
        """Create a deprecation record for an active skill version."""

        return SkillActivation(
            skill_id=skill_id,
            version=version,
            approved_review_id=f"deprecated:{skill_id}:{version}",
            previous_state=SkillPromotionState.ACTIVE,
            activated_by=deprecated_by,
            metadata={"deprecated": True, **(metadata or {})},
        )

    def rollback_skill(
        self,
        skill_id: str,
        from_version: str,
        to_version: str,
        performed_by: str,
        reason: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SkillRollback:
        """Create a rollback record for a prior activation."""

        return SkillRollback(
            skill_id=skill_id,
            from_version=from_version,
            to_version=to_version,
            performed_by=performed_by,
            reason=reason,
            metadata=metadata or {},
        )


__all__ = [
    "LearningArtifactType",
    "LearningEvidence",
    "SkillActivation",
    "SkillDraft",
    "SkillPromotionPolicy",
    "SkillPromotionState",
    "SkillRollback",
    "SkillReview",
    "SkillReviewDecision",
]
