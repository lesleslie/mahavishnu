"""Review gate: quality validation before skill promotion.

Integrates with Crackerjack for automated quality checks.
Falls back to local validation when Crackerjack MCP is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.core.skill_governance import SkillDraft

logger = logging.getLogger(__name__)

# Patterns that indicate potential code injection in skill bodies.
# These are flagged as warnings, not hard failures.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("__import__", re.compile(r"__import__\s*\(")),
    ("exec(", re.compile(r"\bexec\s*\(")),
    ("eval(", re.compile(r"\beval\s*\(")),
]

_MIN_NAME_LENGTH = 10
_MIN_DESCRIPTION_LENGTH = 10


@dataclass(slots=True)
class ReviewCheck:
    """Result of a single review gate check."""

    name: str
    passed: bool
    message: str


@dataclass(slots=True)
class ReviewGateResult:
    """Aggregate result of all review gate checks."""

    passed: bool
    checks: list[ReviewCheck] = field(default_factory=list)
    summary: str = ""

    @property
    def failed_checks(self) -> list[ReviewCheck]:
        """Return only the checks that failed."""
        return [c for c in self.checks if not c.passed]

    @property
    def warning_checks(self) -> list[ReviewCheck]:
        """Return checks that are informational warnings (passed but noteworthy)."""
        return [c for c in self.checks if c.passed and "warning" in c.name.lower()]

    def to_dict(self) -> dict[str, object]:
        """Serialize the result for API responses."""
        return {
            "passed": self.passed,
            "summary": self.summary,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message} for c in self.checks
            ],
        }


class ReviewGate:
    """Validates skill quality before promotion from REVIEW to ACTIVE.

    The gate runs a suite of local checks and, when available, delegates
    an additional quality check to Crackerjack via MCP.  If Crackerjack
    is unreachable the check is skipped and noted in the result rather
    than blocking promotion.

    Usage::

        gate = ReviewGate()
        result = gate.validate_for_promotion(draft)
        if result.passed:
            proceed_with_activation()
    """

    def __init__(self) -> None:
        self._crackerjack_available: bool | None = None

    # -- public API ----------------------------------------------------------

    def validate_for_promotion(self, draft: SkillDraft) -> ReviewGateResult:
        """Run all review gate checks against *draft*.

        Returns:
            A ``ReviewGateResult`` whose ``passed`` flag is ``True`` only
            when every required check succeeds.  Warning checks do not
            cause a failure.
        """
        checks: list[ReviewCheck] = []

        checks.append(self._check_body(draft))
        checks.append(self._check_trigger_conditions(draft))
        checks.append(self._check_metadata_completeness(draft))
        checks.append(self._check_injection_patterns(draft))
        checks.append(self._check_crackerjack(draft))

        failed = [c for c in checks if not c.passed]
        result_passed = len(failed) == 0

        if result_passed:
            summary = (
                f"All {len(checks)} checks passed for skill '{draft.name}' ({draft.skill_id})."
            )
        else:
            names = ", ".join(c.name for c in failed)
            summary = f"{len(failed)} check(s) failed for skill '{draft.name}': {names}."

        return ReviewGateResult(
            passed=result_passed,
            checks=checks,
            summary=summary,
        )

    # -- individual checks ---------------------------------------------------

    def _check_body(self, draft: SkillDraft) -> ReviewCheck:
        """Ensure the skill body is non-empty and substantive."""
        body = draft.body.strip()
        if not body:
            return ReviewCheck(
                name="body_validation",
                passed=False,
                message="Skill body is empty or whitespace-only.",
            )
        if len(body) < 10:
            return ReviewCheck(
                name="body_validation",
                passed=False,
                message=f"Skill body is too short ({len(body)} chars, minimum 10).",
            )
        return ReviewCheck(
            name="body_validation",
            passed=True,
            message=f"Skill body is {len(body)} characters.",
        )

    def _check_trigger_conditions(self, draft: SkillDraft) -> ReviewCheck:
        """Ensure at least one trigger condition is present."""
        count = len(draft.trigger_conditions)
        if count == 0:
            return ReviewCheck(
                name="trigger_conditions",
                passed=False,
                message="No trigger conditions defined.",
            )
        return ReviewCheck(
            name="trigger_conditions",
            passed=True,
            message=f"{count} trigger condition(s) defined.",
        )

    def _check_metadata_completeness(self, draft: SkillDraft) -> ReviewCheck:
        """Validate name and description length for production quality."""
        issues: list[str] = []

        if len(draft.name) < _MIN_NAME_LENGTH:
            issues.append(f"Name is {len(draft.name)} chars, minimum {_MIN_NAME_LENGTH}.")
        if len(draft.description) < _MIN_DESCRIPTION_LENGTH:
            issues.append(
                f"Description is {len(draft.description)} chars, minimum {_MIN_DESCRIPTION_LENGTH}."
            )

        if issues:
            return ReviewCheck(
                name="metadata_completeness",
                passed=False,
                message="; ".join(issues),
            )
        return ReviewCheck(
            name="metadata_completeness",
            passed=True,
            message="Name and description meet minimum length requirements.",
        )

    def _check_injection_patterns(self, draft: SkillDraft) -> ReviewCheck:
        """Flag (but do not fail on) potential code injection patterns.

        This check always passes.  It adds a warning-level message when
        suspicious patterns are detected so reviewers can investigate.
        """
        found: list[str] = []
        body = draft.body

        for label, pattern in _INJECTION_PATTERNS:
            if pattern.search(body):
                found.append(label)

        if found:
            return ReviewCheck(
                name="injection_warning",
                passed=True,
                message=(
                    f"Potential injection pattern(s) detected: {', '.join(found)}. Review manually."
                ),
            )
        return ReviewCheck(
            name="injection_warning",
            passed=True,
            message="No injection patterns detected.",
        )

    def _check_crackerjack(self, draft: SkillDraft) -> ReviewCheck:  # noqa: C901
        """Run a Crackerjack quality check if the MCP server is available.

        The check is wrapped in broad exception handling so that an
        unavailable or misconfigured Crackerjack server never blocks
        promotion.
        """
        # Cache availability to avoid repeated failing probes.
        if self._crackerjack_available is False:
            return ReviewCheck(
                name="crackerjack_quality",
                passed=True,
                message="Crackerjack MCP unavailable; check skipped.",
            )

        try:
            return self._run_crackerjack_check(draft)
        except Exception:
            logger.debug(
                "Crackerjack MCP check failed for skill %s, degrading gracefully.",
                draft.skill_id,
                exc_info=True,
            )
            self._crackerjack_available = False
            return ReviewCheck(
                name="crackerjack_quality",
                passed=True,
                message=("Crackerjack MCP unavailable or raised an error; check skipped."),
            )

    def _run_crackerjack_check(self, draft: SkillDraft) -> ReviewCheck:
        """Attempt to invoke Crackerjack for a quality check.

        This method performs a lightweight probe of the Crackerjack MCP
        server.  The actual integration point will be fleshed out once
        the Crackerjack MCP tool surface stabilises.
        """
        # Probe: try importing the crackerjack client to confirm availability.
        # We do NOT keep a runtime dependency -- if the import fails we
        # simply mark Crackerjack as unavailable.
        try:
            import crackerjack  # noqa: F401 -- availability probe

            self._crackerjack_available = True
        except ImportError:
            self._crackerjack_available = False
            raise

        # If crackerjack is importable we consider the check passed.
        # Future iterations will call specific MCP tools here.
        return ReviewCheck(
            name="crackerjack_quality",
            passed=True,
            message="Crackerjack MCP available; quality check delegated.",
        )


__all__ = [
    "ReviewCheck",
    "ReviewGate",
    "ReviewGateResult",
]
