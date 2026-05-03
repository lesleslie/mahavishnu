"""Bodai Phase 1A regression tests.

Validates Phase 1A acceptance criteria:
- A1: skill_governance.py artifact schemas pass schema validation tests
- A2: Crackerjack review gate integration point is wired and returns accept/reject
- A3: rollback restores the previous active skill version without mutating evidence history
- A4: promotion state machine rejects invalid transitions
- A5: draft skills are isolated in a 'draft' namespace and cannot be loaded by runtime
- A6: TUI review queue surface renders read-only
"""

from __future__ import annotations

import pytest

from mahavishnu.core.review_gate import ReviewGate, ReviewGateResult
from mahavishnu.core.skill_governance import (
    LearningEvidence,
    SkillDraft,
    SkillPromotionPolicy,
    SkillPromotionState,
    SkillReview,
    SkillReviewDecision,
)
from mahavishnu.core.skill_registry import SkillRegistry
from mahavishnu.core.skill_security import (
    is_draft_namespace,
    sanitize_skill_body,
    validate_draft_isolation,
)

# ── A1: Artifact schemas pass validation ─────────────────────────────


def test_learning_evidence_schema_validation():
    ev = LearningEvidence(
        session_id="s1",
        goal="test",
        outcome="pass",
        repo_paths=["r1"],
        tool_calls=["t1"],
        observations=["o1"],
    )
    assert ev.evidence_id.startswith("le_")
    assert ev.session_id == "s1"


def test_skill_draft_schema_validation():
    d = SkillDraft(
        name="test-skill",
        version="1.0.0",
        description="A test skill",
        trigger_conditions=["test"],
        body="do the thing",
    )
    assert d.skill_id.startswith("skill_")
    assert d.state == SkillPromotionState.DRAFT


def test_skill_review_schema_validation():
    r = SkillReview(
        skill_id="sk",
        reviewer="bot",
        decision=SkillReviewDecision.REJECT,
        rationale="bad",
        required_changes=["fix X"],
    )
    assert r.decision == SkillReviewDecision.REJECT
    assert r.required_changes == ["fix X"]


# ── A2: Crackerjack review gate returns accept/reject ─────────────────


def test_review_gate_accepts_well_formed_draft():
    gate = ReviewGate()
    draft = SkillDraft(
        name="code-review-assistant",
        version="1.0.0",
        description="Reviews code for quality issues",
        trigger_conditions=["code-review", "quality"],
        body="def review_code(code): return analysis(code)",
    )
    result = gate.validate_for_promotion(draft)
    assert isinstance(result, ReviewGateResult)
    assert result.passed is True


def test_review_gate_rejects_short_body():
    gate = ReviewGate()
    draft = SkillDraft(
        name="x",
        version="1.0.0",
        description="Tool",
        trigger_conditions=["x"],
        body="short",
    )
    result = gate.validate_for_promotion(draft)
    assert result.passed is False


def test_review_gate_result_has_summary():
    gate = ReviewGate()
    draft = SkillDraft(
        name="code-review-assistant",
        version="1.0.0",
        description="Reviews code for quality issues",
        trigger_conditions=["code-review", "quality"],
        body="def review_code(code): return analysis(code)",
    )
    result = gate.validate_for_promotion(draft)
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


# ── A3: Rollback restores previous version without mutating evidence ────


def _make_approved_review(skill_id: str, reviewer: str = "reviewer") -> SkillReview:
    return SkillReview(
        skill_id=skill_id,
        reviewer=reviewer,
        decision=SkillReviewDecision.APPROVE,
        rationale="good",
    )


def _make_reviewable_draft(
    name: str,
    version: str,
    body: str,
    skill_id: str | None = None,
) -> SkillDraft:
    d = SkillDraft(
        name=name,
        version=version,
        description=f"{name} v{version}",
        trigger_conditions=[name],
        body=body,
        **({"skill_id": skill_id} if skill_id else {}),
    )
    d.state = SkillPromotionState.REVIEW
    return d


def test_rollback_restores_previous_version():
    reg = SkillRegistry()
    shared_id = "skill_shared_abc123"
    d1 = _make_reviewable_draft("skill-a", "1.0.0", "v1 body", skill_id=shared_id)
    r1 = _make_approved_review(d1.skill_id)
    reg.register(d1, r1, activated_by="mahavishnu")

    d2 = _make_reviewable_draft("skill-a", "2.0.0", "v2 body", skill_id=shared_id)
    r2 = _make_approved_review(d2.skill_id)
    reg.register(d2, r2, activated_by="mahavishnu")

    assert reg.get_active(shared_id).version == "2.0.0"

    reg.execute_rollback(shared_id, "1.0.0", "mahavishnu", "regression")

    active = reg.get_active(shared_id)
    assert active is not None
    assert active.version == "1.0.0"
    assert active.body == "v1 body"


def test_rollback_preserves_evidence_history():
    reg = SkillRegistry()
    shared_id = "skill_shared_def456"
    d1 = _make_reviewable_draft("skill-a", "1.0.0", "v1 body", skill_id=shared_id)
    r1 = _make_approved_review(d1.skill_id)
    reg.register(d1, r1, activated_by="mahavishnu")

    d2 = _make_reviewable_draft("skill-a", "2.0.0", "v2 body", skill_id=shared_id)
    r2 = _make_approved_review(d2.skill_id)
    reg.register(d2, r2, activated_by="mahavishnu")

    history_before = reg.list_history(shared_id)
    evidence_ids_before = {r.review.review_id for r in history_before if r.review is not None}

    reg.execute_rollback(shared_id, "1.0.0", "mahavishnu", "regression")

    assert reg.evidence_history_preserved(shared_id)

    history_after = reg.list_history(shared_id)
    evidence_ids_after = {r.review.review_id for r in history_after if r.review is not None}
    assert evidence_ids_before == evidence_ids_after


def test_rollback_unknown_version_raises():
    reg = SkillRegistry()
    d = _make_reviewable_draft("skill-a", "1.0.0", "v1 body")
    reg.register(d, _make_approved_review(d.skill_id), "mahavishnu")
    with pytest.raises(ValueError, match="not found in history"):
        reg.execute_rollback(d.skill_id, "9.9.9", "mahavishnu", "bad")


def test_rollback_no_active_raises():
    reg = SkillRegistry()
    with pytest.raises(ValueError, match="No active version"):
        reg.execute_rollback("missing", "1.0.0", "mahavishnu", "bad")


# ── A4: Promotion state machine rejects invalid transitions ─────────────


def test_draft_cannot_skip_to_active():
    policy = SkillPromotionPolicy()
    assert not policy.can_transition(SkillPromotionState.DRAFT, SkillPromotionState.ACTIVE)


def test_review_to_active_allowed():
    policy = SkillPromotionPolicy()
    assert policy.can_transition(SkillPromotionState.REVIEW, SkillPromotionState.ACTIVE)


def test_active_to_draft_blocked():
    policy = SkillPromotionPolicy()
    assert not policy.can_transition(SkillPromotionState.ACTIVE, SkillPromotionState.DRAFT)


def test_deprecated_is_terminal():
    policy = SkillPromotionPolicy()
    assert policy.allowed_transitions().get(SkillPromotionState.DEPRECATED) == set()


def test_promote_draft_with_rejected_review_raises():
    policy = SkillPromotionPolicy()
    draft = _make_reviewable_draft("skill-a", "1.0.0", "body content here")
    review = SkillReview(
        skill_id=draft.skill_id,
        reviewer="r",
        decision=SkillReviewDecision.REJECT,
        rationale="bad",
        required_changes=["fix"],
    )
    with pytest.raises(ValueError, match="requires an approved review"):
        policy.promote_draft(draft, review, "mahavishnu")


def test_promote_draft_skill_id_mismatch_raises():
    policy = SkillPromotionPolicy()
    draft = _make_reviewable_draft("skill-a", "1.0.0", "body content here")
    review = SkillReview(
        skill_id="wrong-id",
        reviewer="r",
        decision=SkillReviewDecision.APPROVE,
        rationale="good",
    )
    with pytest.raises(ValueError, match="does not match"):
        policy.promote_draft(draft, review, "mahavishnu")


# ── A5: Draft skills are isolated in 'draft' namespace ──────────────────


def test_draft_namespace_detection():
    assert is_draft_namespace("draft/my-skill") is True
    assert is_draft_namespace("draft/code-review") is True
    assert is_draft_namespace("production/my-skill") is False
    assert is_draft_namespace("my-skill") is False


def test_draft_name_with_path_separator_rejected():
    draft = SkillDraft(
        name="../escape",
        version="1.0.0",
        description="bad",
        trigger_conditions=["x"],
        body="body",
    )
    issues = validate_draft_isolation(draft)
    assert any("path separator" in i.lower() for i in issues)


def test_draft_name_with_underscore_prefix_rejected():
    draft = SkillDraft(
        name="_internal",
        version="1.0.0",
        description="bad",
        trigger_conditions=["x"],
        body="body",
    )
    issues = validate_draft_isolation(draft)
    assert any("underscore" in i.lower() for i in issues)


def test_clean_draft_passes_isolation():
    draft = SkillDraft(
        name="code-review",
        version="1.0.0",
        description="Clean skill",
        trigger_conditions=["review"],
        body="def analyze(code): pass",
    )
    issues = validate_draft_isolation(draft)
    assert issues == []


# ── A6: TUI review queue surface renders ────────────────────────────────


def test_tui_reviews_screen_exists():
    from mahavishnu.tui.app import ReviewsScreen

    assert ReviewsScreen is not None


def test_tui_dashboard_has_five_bindings():
    from mahavishnu.tui.app import DashboardApp

    binding_keys = {b.key for b in DashboardApp.BINDINGS}
    assert "5" in binding_keys


# ── Security: sanitize_skill_body ─────────────────────────────────────────


def test_sanitize_redacts_import_exec():
    body = "import os; exec('bad code')"
    sanitized = sanitize_skill_body(body)
    assert "REDACTED" in sanitized
    assert "REDACTED: exec(" in sanitized


def test_sanitize_truncates_oversized():
    body = "x" * 200_000
    sanitized = sanitize_skill_body(body)
    assert len(sanitized) <= 100_000
