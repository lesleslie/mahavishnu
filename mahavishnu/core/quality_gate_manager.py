"""Quality Gate Manager for Mahavishnu.

Integrates with Crackerjack MCP server for quality validation:
- Configurable quality gate rules
- Pre-completion validation
- Multiple check types (lint, test, security, etc.)
- Severity-based enforcement (required, warning, optional)

Usage:
    from mahavishnu.core.quality_gate_manager import QualityGateManager

    manager = QualityGateManager(task_store, crackerjack_client)

    # Add rules
    manager.add_rule(QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED))

    # Validate before task completion
    result = await manager.validate_for_completion("/path/to/repo")
    if not result.passed:
        print(f"Quality gate failed: {result.message}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import TaskStore

logger = logging.getLogger(__name__)


class CheckSeverity(str, Enum):
    """Severity level for quality checks."""

    REQUIRED = "required"  # Must pass for gate to pass
    WARNING = "warning"  # Failure is noted but doesn't fail gate
    OPTIONAL = "optional"  # Informational only


class CheckType(str, Enum):
    """Types of quality checks."""

    LINT = "lint"
    TYPE_CHECK = "type_check"
    TEST = "test"
    SECURITY = "security"
    COMPLEXITY = "complexity"
    FORMAT = "format"
    COVERAGE = "coverage"


@dataclass
class QualityGateRule:
    """A quality gate rule to be checked.

    Attributes:
        name: Unique name for this rule
        check_type: Type of check to run
        severity: How failures are treated
        description: Human-readable description
        threshold: Optional threshold value (e.g., coverage percentage)
        enabled: Whether this rule is active
    """

    name: str
    check_type: CheckType
    severity: CheckSeverity
    description: str = ""
    threshold: float | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "check_type": self.check_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "threshold": self.threshold,
            "enabled": self.enabled,
        }


@dataclass
class QualityCheckResult:
    """Result of a single quality check.

    Attributes:
        check_name: Name of the check
        check_type: Type of check
        passed: Whether the check passed
        score: Score for this check (0-100)
        message: Human-readable result message
        threshold: Threshold that was checked against
        details: Additional details about the check
        duration_ms: How long the check took
        severity: Severity level of this check
    """

    check_name: str
    check_type: CheckType
    passed: bool
    score: float
    message: str = ""
    threshold: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None
    severity: CheckSeverity = CheckSeverity.REQUIRED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "check_name": self.check_name,
            "check_type": self.check_type.value,
            "passed": self.passed,
            "score": self.score,
            "message": self.message,
            "threshold": self.threshold,
            "details": self.details,
            "duration_ms": self.duration_ms,
            "severity": self.severity.value,
        }


@dataclass
class QualityGateResult:
    """Result of running all quality gates.

    Attributes:
        passed: Whether all required checks passed
        overall_score: Weighted average of all check scores
        checks: Individual check results
        message: Summary message
        failed_required_checks: Names of failed required checks
        warnings: Names of checks that failed with warning severity
        duration_ms: Total duration of all checks
    """

    passed: bool
    overall_score: float
    checks: list[QualityCheckResult] = field(default_factory=list)
    message: str = ""
    failed_required_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "overall_score": self.overall_score,
            "checks": [c.to_dict() for c in self.checks],
            "message": self.message,
            "failed_required_checks": self.failed_required_checks,
            "warnings": self.warnings,
            "duration_ms": self.duration_ms,
        }


class QualityGateError(Exception):
    """Exception raised for quality gate errors."""

    def __init__(self, message: str, result: QualityGateResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class QualityGateManager:
    """Manages quality gates for task completion validation.

    Features:
    - Configurable quality gate rules
    - Integration with Crackerjack MCP client
    - Severity-based enforcement
    - Pre-completion validation
    - Detailed results and scoring

    Example:
        manager = QualityGateManager(
            task_store,
            crackerjack_client,
            rules=[
                QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED),
                QualityGateRule("test", CheckType.TEST, CheckSeverity.REQUIRED, threshold=80.0),
            ]
        )

        # Validate before completing task
        result = await manager.validate_for_completion("/path/to/repo")
        if result.passed:
            print("Quality gates passed!")
    """

    def __init__(
        self,
        task_store: TaskStore,
        crackerjack_client: Any = None,  # CrackerjackMCPClient
        rules: list[QualityGateRule] | None = None,
    ) -> None:
        """Initialize the quality gate manager.

        Args:
            task_store: TaskStore for task operations
            crackerjack_client: Optional Crackerjack MCP client
            rules: Optional list of quality gate rules
        """
        self.task_store = task_store
        self._crackerjack = crackerjack_client
        self.rules: list[QualityGateRule] = rules or []
        self._last_result: QualityGateResult | None = None

    def add_rule(self, rule: QualityGateRule) -> None:
        """Add a quality gate rule.

        Args:
            rule: Rule to add
        """
        self.rules.append(rule)
        logger.info(f"Added quality gate rule: {rule.name}")

    def remove_rule(self, name: str) -> bool:
        """Remove a quality gate rule.

        Args:
            name: Name of rule to remove

        Returns:
            True if rule was removed, False if not found
        """
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                logger.info(f"Removed quality gate rule: {name}")
                return True
        return False

    def get_rule(self, name: str) -> QualityGateRule | None:
        """Get a rule by name.

        Args:
            name: Name of rule to get

        Returns:
            Rule if found, None otherwise
        """
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def enable_rule(self, name: str) -> bool:
        """Enable a rule.

        Args:
            name: Name of rule to enable

        Returns:
            True if rule was enabled, False if not found
        """
        rule = self.get_rule(name)
        if rule:
            rule.enabled = True
            logger.info(f"Enabled quality gate rule: {name}")
            return True
        return False

    def disable_rule(self, name: str) -> bool:
        """Disable a rule.

        Args:
            name: Name of rule to disable

        Returns:
            True if rule was disabled, False if not found
        """
        rule = self.get_rule(name)
        if rule:
            rule.enabled = False
            logger.info(f"Disabled quality gate rule: {name}")
            return True
        return False

    def get_enabled_rules(self) -> list[QualityGateRule]:
        """Get all enabled rules.

        Returns:
            List of enabled rules
        """
        return [r for r in self.rules if r.enabled]

    async def run_check(
        self,
        rule: QualityGateRule,
        repo_path: str,
    ) -> QualityCheckResult:
        """Run a single quality check.

        Args:
            rule: Rule to check
            repo_path: Path to repository

        Returns:
            QualityCheckResult with check outcome
        """
        if not self._crackerjack:
            return QualityCheckResult(
                check_name=rule.name,
                check_type=rule.check_type,
                passed=True,
                score=100.0,
                message=f"Check skipped (no Crackerjack client)",
                severity=rule.severity,
            )

        try:
            # Call Crackerjack MCP client
            start_time = datetime.now(UTC)

            result = await self._crackerjack.run_quality_checks(
                repo_path=repo_path,
                check_types=[rule.check_type.value],
            )

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            passed = result.get("passed", True)
            score = float(result.get("score", 100))
            issues = result.get("issues", [])

            # Check threshold if specified
            if rule.threshold is not None and score < rule.threshold:
                passed = False
                message = f"Score {score}% below threshold {rule.threshold}%"
            elif passed:
                message = f"Check passed (score: {score}%)"
            else:
                message = f"Check failed: {', '.join(issues) if issues else 'Unknown error'}"

            return QualityCheckResult(
                check_name=rule.name,
                check_type=rule.check_type,
                passed=passed,
                score=score,
                message=message,
                threshold=rule.threshold,
                details={"issues": issues, "repo_path": repo_path},
                duration_ms=duration_ms,
                severity=rule.severity,
            )

        except Exception as e:
            logger.error(f"Quality check {rule.name} failed with error: {e}")
            return QualityCheckResult(
                check_name=rule.name,
                check_type=rule.check_type,
                passed=False,
                score=0.0,
                message=f"Check failed with error: {e}",
                threshold=rule.threshold,
                severity=rule.severity,
            )

    async def run_all_checks(
        self,
        repo_path: str,
    ) -> QualityGateResult:
        """Run all enabled quality checks.

        Args:
            repo_path: Path to repository

        Returns:
            QualityGateResult with overall outcome
        """
        if not self._crackerjack:
            self._last_result = QualityGateResult(
                passed=True,
                overall_score=100.0,
                message="Quality gates skipped (disabled mode)",
            )
            return self._last_result

        start_time = datetime.now(UTC)
        checks: list[QualityCheckResult] = []
        failed_required: list[str] = []
        warnings: list[str] = []
        total_score = 0.0

        enabled_rules = self.get_enabled_rules()

        if not enabled_rules:
            self._last_result = QualityGateResult(
                passed=True,
                overall_score=100.0,
                message="No quality gate rules configured",
            )
            return self._last_result

        for rule in enabled_rules:
            result = await self.run_check(rule, repo_path)
            checks.append(result)
            total_score += result.score

            if not result.passed:
                if rule.severity == CheckSeverity.REQUIRED:
                    failed_required.append(rule.name)
                elif rule.severity == CheckSeverity.WARNING:
                    warnings.append(rule.name)

        # Calculate overall score
        overall_score = total_score / len(enabled_rules) if enabled_rules else 100.0

        # Determine if passed
        passed = len(failed_required) == 0

        # Generate message
        if passed and not warnings:
            message = f"All quality gates passed (score: {overall_score:.1f}%)"
        elif passed:
            message = f"Quality gates passed with warnings (score: {overall_score:.1f}%)"
        else:
            message = f"Quality gates failed: {', '.join(failed_required)}"

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        self._last_result = QualityGateResult(
            passed=passed,
            overall_score=overall_score,
            checks=checks,
            message=message,
            failed_required_checks=failed_required,
            warnings=warnings,
            duration_ms=duration_ms,
        )

        logger.info(f"Quality gate result: {message}")
        return self._last_result

    async def validate_for_completion(
        self,
        repo_path: str,
    ) -> QualityGateResult:
        """Validate repository is ready for task completion.

        This is the main entry point for pre-completion validation.

        Args:
            repo_path: Path to repository

        Returns:
            QualityGateResult with validation outcome
        """
        result = await self.run_all_checks(repo_path)

        if not result.passed:
            logger.warning(
                f"Quality gate validation failed for {repo_path}: "
                f"{result.failed_required_checks}"
            )

        return result

    async def run_checks_for_repos(
        self,
        repo_paths: list[str],
    ) -> dict[str, QualityGateResult]:
        """Run quality checks for multiple repositories.

        Args:
            repo_paths: List of repository paths

        Returns:
            Dictionary mapping repo path to result
        """
        results: dict[str, QualityGateResult] = {}

        for repo_path in repo_paths:
            results[repo_path] = await self.run_all_checks(repo_path)

        return results

    def get_quality_summary(self) -> dict[str, Any]:
        """Get summary of last quality check run.

        Returns:
            Dictionary with quality statistics
        """
        if not self._last_result:
            return {
                "total_checks": len(self.rules),
                "passed_checks": 0,
                "failed_checks": 0,
                "warnings": 0,
                "last_run": None,
            }

        passed = sum(1 for c in self._last_result.checks if c.passed)
        failed = len(self._last_result.checks) - passed

        return {
            "total_checks": len(self._last_result.checks),
            "passed_checks": passed,
            "failed_checks": failed,
            "warnings": len(self._last_result.warnings),
            "overall_score": self._last_result.overall_score,
            "last_run": datetime.now(UTC).isoformat(),
        }


__all__ = [
    "QualityGateManager",
    "QualityGateRule",
    "QualityGateResult",
    "QualityCheckResult",
    "CheckSeverity",
    "CheckType",
    "QualityGateError",
]
