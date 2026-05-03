"""In-memory skill registry with rollback execution.

Tracks active skill versions and their promotion history.
Executes rollbacks without mutating evidence chains.
"""

from __future__ import annotations

from dataclasses import dataclass

from mahavishnu.core.skill_governance import (
    SkillActivation,
    SkillDraft,
    SkillPromotionPolicy,
    SkillPromotionState,
    SkillReview,
    SkillRollback,
)


@dataclass(slots=True)
class VersionRecord:
    skill_id: str
    version: str
    state: SkillPromotionState
    body: str
    activation: SkillActivation | None = None
    review: SkillReview | None = None
    rollback: SkillRollback | None = None


class SkillRegistry:
    """In-memory registry that tracks skill versions and executes rollbacks."""

    def __init__(self, policy: SkillPromotionPolicy | None = None) -> None:
        self._policy = policy or SkillPromotionPolicy()
        self._versions: dict[str, VersionRecord] = {}
        self._history: list[VersionRecord] = []

    @property
    def policy(self) -> SkillPromotionPolicy:
        return self._policy

    def register(
        self,
        draft: SkillDraft,
        review: SkillReview,
        activated_by: str,
    ) -> SkillActivation:
        activation = self._policy.promote_draft(draft, review, activated_by)
        record = VersionRecord(
            skill_id=draft.skill_id,
            version=draft.version,
            state=SkillPromotionState.ACTIVE,
            body=draft.body,
            activation=activation,
            review=review,
        )
        self._versions[draft.skill_id] = record
        self._history.append(record)
        return activation

    def get_active(self, skill_id: str) -> VersionRecord | None:
        record = self._versions.get(skill_id)
        if record and record.state == SkillPromotionState.ACTIVE:
            return record
        return None

    def get_version(self, skill_id: str, version: str) -> VersionRecord | None:
        for record in self._history:
            if record.skill_id == skill_id and record.version == version:
                return record
        return None

    def list_active(self) -> list[VersionRecord]:
        return [r for r in self._versions.values() if r.state == SkillPromotionState.ACTIVE]

    def list_history(self, skill_id: str) -> list[VersionRecord]:
        return [r for r in self._history if r.skill_id == skill_id]

    def execute_rollback(
        self,
        skill_id: str,
        to_version: str,
        performed_by: str,
        reason: str,
    ) -> SkillRollback:
        current = self.get_active(skill_id)
        if current is None:
            raise ValueError(f"No active version found for skill '{skill_id}'")

        target = self.get_version(skill_id, to_version)
        if target is None:
            raise ValueError(f"Version '{to_version}' not found in history for skill '{skill_id}'")

        rollback = self._policy.rollback_skill(
            skill_id=skill_id,
            from_version=current.version,
            to_version=to_version,
            performed_by=performed_by,
            reason=reason,
        )

        restored = VersionRecord(
            skill_id=skill_id,
            version=to_version,
            state=SkillPromotionState.ACTIVE,
            body=target.body,
            activation=target.activation,
            review=target.review,
            rollback=rollback,
        )
        self._versions[skill_id] = restored
        self._history.append(restored)
        return rollback

    def deprecate(self, skill_id: str, deprecated_by: str) -> SkillActivation:
        current = self.get_active(skill_id)
        if current is None:
            raise ValueError(f"No active version found for skill '{skill_id}'")

        deprecation = self._policy.deprecate_skill(
            skill_id=skill_id,
            version=current.version,
            deprecated_by=deprecated_by,
        )
        current.state = SkillPromotionState.DEPRECATED
        return deprecation

    def evidence_history_preserved(self, skill_id: str) -> bool:
        evidence_ids = {
            r.review.review_id for r in self.list_history(skill_id) if r.review is not None
        }
        if not evidence_ids:
            return True
        for record in self.list_history(skill_id):
            if record.rollback is not None:
                rb = record.rollback
                if rb.rollback_id in evidence_ids:
                    return False
        return True
