"""Tests for the review gate and skill security modules."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mahavishnu.core.review_gate import ReviewCheck, ReviewGate, ReviewGateResult
from mahavishnu.core.skill_governance import SkillDraft, SkillPromotionState
from mahavishnu.core.skill_security import (
    DANGEROUS_PATTERNS,
    MAX_SKILL_BODY_LENGTH,
    is_draft_namespace,
    sanitize_skill_body,
    validate_draft_isolation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    *,
    name: str = "security-review-skill",
    version: str = "1.0.0",
    description: str = "Performs a thorough security review of code changes",
    trigger_conditions: list[str] | None = None,
    body: str = "Focus on authentication, secrets, and input validation.",
    state: SkillPromotionState = SkillPromotionState.REVIEW,
    skill_id: str | None = None,
) -> SkillDraft:
    """Create a well-formed SkillDraft for testing."""
    kwargs: dict = {
        "name": name,
        "version": version,
        "description": description,
        "trigger_conditions": trigger_conditions or ["security", "review"],
        "body": body,
        "state": state,
    }
    if skill_id is not None:
        kwargs["skill_id"] = skill_id
    return SkillDraft(**kwargs)


# ===========================================================================
# ReviewGateResult and ReviewCheck dataclass tests
# ===========================================================================


class TestReviewCheck:
    def test_creation(self) -> None:
        check = ReviewCheck(name="body_validation", passed=True, message="OK")
        assert check.name == "body_validation"
        assert check.passed is True
        assert check.message == "OK"

    def test_slots(self) -> None:
        check = ReviewCheck(name="x", passed=False, message="y")
        with pytest.raises(AttributeError):
            check.nonexistent = "val"  # type: ignore[attr-defined]


class TestReviewGateResult:
    def test_passed_with_no_checks(self) -> None:
        result = ReviewGateResult(passed=True, checks=[], summary="All clear.")
        assert result.passed is True
        assert result.failed_checks == []
        assert result.warning_checks == []

    def test_failed_checks_property(self) -> None:
        checks = [
            ReviewCheck(name="a", passed=True, message="ok"),
            ReviewCheck(name="b", passed=False, message="fail"),
            ReviewCheck(name="c", passed=False, message="also fail"),
        ]
        result = ReviewGateResult(passed=False, checks=checks, summary="2 failed")
        assert len(result.failed_checks) == 2
        assert {c.name for c in result.failed_checks} == {"b", "c"}

    def test_warning_checks_property(self) -> None:
        checks = [
            ReviewCheck(name="injection_warning", passed=True, message="flagged"),
            ReviewCheck(name="body_validation", passed=True, message="ok"),
            ReviewCheck(name="trigger_conditions", passed=False, message="nope"),
        ]
        result = ReviewGateResult(passed=False, checks=checks, summary="x")
        assert len(result.warning_checks) == 1
        assert result.warning_checks[0].name == "injection_warning"

    def test_to_dict(self) -> None:
        checks = [
            ReviewCheck(name="body_validation", passed=True, message="ok"),
        ]
        result = ReviewGateResult(passed=True, checks=checks, summary="good")
        d = result.to_dict()
        assert d["passed"] is True
        assert d["summary"] == "good"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "body_validation"


# ===========================================================================
# ReviewGate.checks
# ===========================================================================


class TestBodyValidation:
    def test_empty_body_fails(self) -> None:
        draft = _make_draft(body="   ")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        assert not result.passed
        body_check = next(c for c in result.checks if c.name == "body_validation")
        assert not body_check.passed
        assert "empty" in body_check.message.lower() or "whitespace" in body_check.message.lower()

    def test_short_body_fails(self) -> None:
        draft = _make_draft(body="hi")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        assert not result.passed
        body_check = next(c for c in result.checks if c.name == "body_validation")
        assert not body_check.passed
        assert "too short" in body_check.message.lower()

    def test_valid_body_passes(self) -> None:
        draft = _make_draft(body="Focus on authentication, secrets, and input validation.")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        body_check = next(c for c in result.checks if c.name == "body_validation")
        assert body_check.passed


class TestTriggerConditions:
    def test_no_trigger_conditions_fails(self) -> None:
        # SkillDraft validator enforces >= 1, so we must bypass it to test
        # the gate's own re-check.  We construct a draft that has triggers
        # set, then manually clear them (via model_copy) to simulate a draft
        # arriving with empty triggers.
        draft = _make_draft()
        draft = draft.model_copy(update={"trigger_conditions": []})
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        trigger_check = next(c for c in result.checks if c.name == "trigger_conditions")
        assert not trigger_check.passed

    def test_single_trigger_passes(self) -> None:
        draft = _make_draft(trigger_conditions=["security"])
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        trigger_check = next(c for c in result.checks if c.name == "trigger_conditions")
        assert trigger_check.passed


class TestMetadataCompleteness:
    def test_short_name_fails(self) -> None:
        draft = _make_draft(name="sec")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        meta_check = next(c for c in result.checks if c.name == "metadata_completeness")
        assert not meta_check.passed
        assert "Name" in meta_check.message

    def test_short_description_fails(self) -> None:
        draft = _make_draft(description="Brief")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        meta_check = next(c for c in result.checks if c.name == "metadata_completeness")
        assert not meta_check.passed
        assert "Description" in meta_check.message

    def test_both_short_fails(self) -> None:
        draft = _make_draft(name="x", description="y")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        meta_check = next(c for c in result.checks if c.name == "metadata_completeness")
        assert not meta_check.passed
        assert "Name" in meta_check.message and "Description" in meta_check.message

    def test_valid_metadata_passes(self) -> None:
        draft = _make_draft()
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        meta_check = next(c for c in result.checks if c.name == "metadata_completeness")
        assert meta_check.passed


class TestInjectionPatterns:
    def test_injection_flagged_as_warning_not_failure(self) -> None:
        body = "Use __import__('os') to access system tools."
        draft = _make_draft(body=body)
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        inj_check = next(c for c in result.checks if c.name == "injection_warning")
        # Warning check always passes (passed=True), but message flags it.
        assert inj_check.passed is True
        assert "detected" in inj_check.message.lower()

    def test_clean_body_no_warning(self) -> None:
        draft = _make_draft(body="A perfectly safe skill body with no dangerous calls.")
        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        inj_check = next(c for c in result.checks if c.name == "injection_warning")
        assert "No injection" in inj_check.message


class TestCrackerjackIntegration:
    def test_graceful_degradation_when_unavailable(self) -> None:
        """Crackerjack unavailability should not cause the gate to fail."""
        draft = _make_draft()
        gate = ReviewGate()

        # Force the import to fail.
        with patch.dict("sys.modules", {"crackerjack": None}):
            gate._crackerjack_available = None  # reset cache
            result = gate.validate_for_promotion(draft)

        cj_check = next(c for c in result.checks if c.name == "crackerjack_quality")
        # The check should pass (not block promotion) but note unavailability.
        assert cj_check.passed is True
        assert "unavailable" in cj_check.message.lower() or "skipped" in cj_check.message.lower()

    def test_available_crackerjack_passes(self) -> None:
        """When crackerjack is importable, the check should pass."""
        draft = _make_draft()
        gate = ReviewGate()

        mock_module = type("module", (), {})()

        with patch.dict("sys.modules", {"crackerjack": mock_module}):
            gate._crackerjack_available = None
            result = gate.validate_for_promotion(draft)

        cj_check = next(c for c in result.checks if c.name == "crackerjack_quality")
        assert cj_check.passed is True


class TestFullValidation:
    def test_well_formed_draft_passes_all_checks(self) -> None:
        draft = _make_draft(
            name="comprehensive-security-review-skill",
            description="Performs a thorough security review of all code changes in a PR",
            body=(
                "Review pull requests for common security vulnerabilities "
                "including injection, auth bypass, and secrets exposure."
            ),
            trigger_conditions=["security", "review", "pull_request"],
        )
        gate = ReviewGate()

        with patch.dict("sys.modules", {"crackerjack": None}):
            gate._crackerjack_available = None
            result = gate.validate_for_promotion(draft)

        assert result.passed is True
        assert all(c.passed for c in result.checks)
        assert "All" in result.summary

    def test_multiple_failures_produces_summary(self) -> None:
        draft = _make_draft(
            name="x",
            description="y",
            body="   ",
        )
        draft = draft.model_copy(update={"trigger_conditions": []})
        gate = ReviewGate()

        with patch.dict("sys.modules", {"crackerjack": None}):
            gate._crackerjack_available = None
            result = gate.validate_for_promotion(draft)

        assert not result.passed
        assert result.summary
        assert "failed" in result.summary.lower()


# ===========================================================================
# skill_security tests
# ===========================================================================


class TestSanitizeSkillBody:
    def test_strips_dangerous_patterns(self) -> None:
        body = "code = __import__('os'); some exec(payload); and eval(expr)"
        sanitized = sanitize_skill_body(body)
        # The dangerous *calls* should be replaced with redaction markers.
        # Note: the redaction comment itself contains the label text (e.g.
        # "[REDACTED: exec("]) so we check that the full original call is
        # gone, not just the function name substring.
        assert "__import__('os')" not in sanitized
        assert "exec(payload)" not in sanitized
        assert "eval(expr)" not in sanitized
        assert "[REDACTED:" in sanitized

    def test_collapses_excessive_whitespace(self) -> None:
        body = "line1\n\n\n\n\n\nline2"
        sanitized = sanitize_skill_body(body)
        assert "\n\n\n\n" not in sanitized
        assert "line2" in sanitized

    def test_truncates_at_max_length(self) -> None:
        body = "x" * (MAX_SKILL_BODY_LENGTH + 5000)
        sanitized = sanitize_skill_body(body)
        assert len(sanitized) <= MAX_SKILL_BODY_LENGTH

    def test_clean_body_unchanged(self) -> None:
        body = "This is a perfectly safe skill body."
        assert sanitize_skill_body(body) == body

    def test_strips_all_dangerous_patterns(self) -> None:
        """Every pattern in DANGEROUS_PATTERNS should be removed."""
        for label, _pattern in DANGEROUS_PATTERNS:
            # Construct a body that actually matches the regex.
            # Some labels already end with '(' (e.g. "exec("), others
            # don't (e.g. "__import__").  Ensure a '(' is present so the
            # regex (which requires '\(') can match.
            if label.endswith("("):
                sample = f"Some code with {label}arg) more text"
            else:
                sample = f"Some code with {label}(arg) more text"
            sanitized = sanitize_skill_body(sample)
            # The pattern itself should be redacted.
            assert f"[REDACTED: {label}]" in sanitized


class TestValidateDraftIsolation:
    def test_path_separator_in_name(self) -> None:
        for sep in ["/", "\\", ".."]:
            draft = _make_draft(name=f"my{sep}skill")
            issues = validate_draft_isolation(draft)
            assert any("path separator" in i.lower() for i in issues), (
                f"Expected path separator issue for name with '{sep}'"
            )

    def test_underscore_prefix_in_name(self) -> None:
        draft = _make_draft(name="_private_skill")
        issues = validate_draft_isolation(draft)
        assert any("underscore" in i.lower() for i in issues)

    def test_filesystem_access_pattern_in_body(self) -> None:
        draft = _make_draft(body='f = open("/etc/passwd")')
        issues = validate_draft_isolation(draft)
        assert any("filesystem" in i.lower() for i in issues)

    def test_network_access_pattern_in_body(self) -> None:
        draft = _make_draft(body='requests.get("https://evil.com")')
        issues = validate_draft_isolation(draft)
        assert any("network" in i.lower() for i in issues)

    def test_clean_draft_no_issues(self) -> None:
        draft = _make_draft(
            name="safe-review-skill",
            body="Review code for quality and correctness.",
        )
        issues = validate_draft_isolation(draft)
        assert issues == []

    def test_multiple_issues_reported(self) -> None:
        draft = _make_draft(
            name="../escape",
            body='open("/tmp/x")\nrequests.post("https://evil.com")',
        )
        issues = validate_draft_isolation(draft)
        assert len(issues) >= 3  # path sep, fs access, network access


class TestIsDraftNamespace:
    def test_draft_prefix_returns_true(self) -> None:
        assert is_draft_namespace("draft/abc123") is True

    def test_active_skill_returns_false(self) -> None:
        assert is_draft_namespace("skill_abc123") is False

    def test_empty_string_returns_false(self) -> None:
        assert is_draft_namespace("") is False

    def test_draft_in_middle_returns_false(self) -> None:
        assert is_draft_namespace("mydraft/skill") is False

    def test_case_sensitive(self) -> None:
        assert is_draft_namespace("Draft/abc") is False
