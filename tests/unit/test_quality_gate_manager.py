"""Tests for QualityGateManager - Crackerjack integration for quality gates."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from mahavishnu.core.quality_gate_manager import (
    QualityGateManager,
    QualityGateRule,
    QualityGateResult,
    QualityCheckResult,
    CheckSeverity,
    CheckType,
    QualityGateError,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    return AsyncMock()


@pytest.fixture
def mock_crackerjack_client() -> MagicMock:
    """Create a mock Crackerjack MCP client."""
    client = MagicMock()
    client.run_quality_checks = AsyncMock()
    client.get_quality_status = AsyncMock()
    return client


@pytest.fixture
def sample_gate_rules() -> list[QualityGateRule]:
    """Create sample quality gate rules."""
    return [
        QualityGateRule(
            name="lint_pass",
            check_type=CheckType.LINT,
            severity=CheckSeverity.REQUIRED,
            description="Code must pass linting checks",
        ),
        QualityGateRule(
            name="typecheck_pass",
            check_type=CheckType.TYPE_CHECK,
            severity=CheckSeverity.REQUIRED,
            description="Code must pass type checking",
        ),
        QualityGateRule(
            name="test_coverage",
            check_type=CheckType.TEST,
            severity=CheckSeverity.REQUIRED,
            description="Test coverage must be >= 80%",
            threshold=80.0,
        ),
        QualityGateRule(
            name="security_scan",
            check_type=CheckType.SECURITY,
            severity=CheckSeverity.WARNING,
            description="No high-severity security issues",
        ),
    ]


class TestCheckSeverity:
    """Tests for CheckSeverity enum."""

    def test_check_severities(self) -> None:
        """Test available check severities."""
        assert CheckSeverity.REQUIRED.value == "required"
        assert CheckSeverity.WARNING.value == "warning"
        assert CheckSeverity.OPTIONAL.value == "optional"


class TestCheckType:
    """Tests for CheckType enum."""

    def test_check_types(self) -> None:
        """Test available check types."""
        assert CheckType.LINT.value == "lint"
        assert CheckType.TYPE_CHECK.value == "type_check"
        assert CheckType.TEST.value == "test"
        assert CheckType.SECURITY.value == "security"
        assert CheckType.COMPLEXITY.value == "complexity"
        assert CheckType.FORMAT.value == "format"


class TestQualityGateRule:
    """Tests for QualityGateRule dataclass."""

    def test_create_quality_gate_rule(self) -> None:
        """Create a quality gate rule."""
        rule = QualityGateRule(
            name="lint_pass",
            check_type=CheckType.LINT,
            severity=CheckSeverity.REQUIRED,
            description="Code must pass linting",
        )

        assert rule.name == "lint_pass"
        assert rule.check_type == CheckType.LINT
        assert rule.severity == CheckSeverity.REQUIRED
        assert rule.enabled is True

    def test_quality_gate_rule_with_threshold(self) -> None:
        """Create a rule with threshold."""
        rule = QualityGateRule(
            name="coverage",
            check_type=CheckType.TEST,
            severity=CheckSeverity.REQUIRED,
            description="Coverage >= 80%",
            threshold=80.0,
        )

        assert rule.threshold == 80.0

    def test_quality_gate_rule_to_dict(self) -> None:
        """Convert rule to dictionary."""
        rule = QualityGateRule(
            name="security",
            check_type=CheckType.SECURITY,
            severity=CheckSeverity.WARNING,
            description="No high severity issues",
        )

        d = rule.to_dict()
        assert d["name"] == "security"
        assert d["check_type"] == "security"
        assert d["severity"] == "warning"


class TestQualityCheckResult:
    """Tests for QualityCheckResult dataclass."""

    def test_create_passed_check_result(self) -> None:
        """Create a passed check result."""
        result = QualityCheckResult(
            check_name="lint_pass",
            check_type=CheckType.LINT,
            passed=True,
            score=100.0,
            message="No linting issues found",
        )

        assert result.passed is True
        assert result.score == 100.0
        assert result.check_name == "lint_pass"

    def test_create_failed_check_result(self) -> None:
        """Create a failed check result."""
        result = QualityCheckResult(
            check_name="test_coverage",
            check_type=CheckType.TEST,
            passed=False,
            score=65.0,
            message="Coverage 65% is below threshold 80%",
            threshold=80.0,
            details={"files_not_covered": ["module.py"]},
        )

        assert result.passed is False
        assert result.score == 65.0
        assert result.threshold == 80.0

    def test_check_result_to_dict(self) -> None:
        """Convert check result to dictionary."""
        result = QualityCheckResult(
            check_name="typecheck",
            check_type=CheckType.TYPE_CHECK,
            passed=True,
            score=100.0,
            message="All types valid",
        )

        d = result.to_dict()
        assert d["check_name"] == "typecheck"
        assert d["passed"] is True
        assert d["score"] == 100.0


class TestQualityGateResult:
    """Tests for QualityGateResult dataclass."""

    def test_create_passed_gate_result(self) -> None:
        """Create a passed gate result."""
        result = QualityGateResult(
            passed=True,
            overall_score=95.0,
            checks=[
                QualityCheckResult("lint", CheckType.LINT, True, 100.0, "OK"),
                QualityCheckResult("test", CheckType.TEST, True, 90.0, "OK"),
            ],
            message="All quality gates passed",
        )

        assert result.passed is True
        assert result.overall_score == 95.0
        assert len(result.checks) == 2

    def test_create_failed_gate_result(self) -> None:
        """Create a failed gate result."""
        result = QualityGateResult(
            passed=False,
            overall_score=60.0,
            checks=[
                QualityCheckResult("lint", CheckType.LINT, True, 100.0, "OK"),
                QualityCheckResult("test", CheckType.TEST, False, 50.0, "Failed"),
            ],
            message="Quality gate failed: test coverage below threshold",
            failed_required_checks=["test"],
        )

        assert result.passed is False
        assert result.overall_score == 60.0
        assert len(result.failed_required_checks) == 1

    def test_gate_result_to_dict(self) -> None:
        """Convert gate result to dictionary."""
        result = QualityGateResult(
            passed=True,
            overall_score=100.0,
            checks=[],
            message="OK",
        )

        d = result.to_dict()
        assert d["passed"] is True
        assert d["overall_score"] == 100.0


class TestQualityGateManager:
    """Tests for QualityGateManager class."""

    def test_create_manager_with_rules(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Create manager with custom rules."""
        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
        )

        assert len(manager.rules) == 4
        assert manager.rules[0].name == "lint_pass"

    def test_get_enabled_rules(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Get only enabled rules."""
        # Disable one rule
        sample_gate_rules[2].enabled = False

        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
        )

        enabled = manager.get_enabled_rules()
        assert len(enabled) == 3

    @pytest.mark.asyncio
    async def test_run_single_check(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Run a single quality check."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 100,
            "issues": [],
        }

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
        )

        rule = QualityGateRule(
            name="lint",
            check_type=CheckType.LINT,
            severity=CheckSeverity.REQUIRED,
            description="Lint check",
        )

        result = await manager.run_check(rule, "/path/to/repo")

        assert result.check_name == "lint"
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_run_all_checks(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Run all quality checks."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 95,
            "issues": [],
        }

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=sample_gate_rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        assert result.passed is True
        assert len(result.checks) == 4

    @pytest.mark.asyncio
    async def test_run_checks_fails_required(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Quality gate fails when required check fails."""
        # Setup: first call passes, second fails
        mock_crackerjack_client.run_quality_checks.side_effect = [
            {"passed": True, "score": 100, "issues": []},
            {"passed": False, "score": 50, "issues": ["type error"]},
            {"passed": True, "score": 100, "issues": []},
            {"passed": True, "score": 100, "issues": []},
        ]

        rules = [
            QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED, "Lint"),
            QualityGateRule("type", CheckType.TYPE_CHECK, CheckSeverity.REQUIRED, "Type"),
            QualityGateRule("test", CheckType.TEST, CheckSeverity.REQUIRED, "Test"),
            QualityGateRule("security", CheckType.SECURITY, CheckSeverity.WARNING, "Sec"),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        assert result.passed is False
        assert "type" in result.failed_required_checks

    @pytest.mark.asyncio
    async def test_run_checks_warning_does_not_fail(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Warning severity check failure does not fail gate."""
        mock_crackerjack_client.run_quality_checks.side_effect = [
            {"passed": True, "score": 100, "issues": []},
            {"passed": False, "score": 80, "issues": ["warning issue"]},
        ]

        rules = [
            QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED, "Lint"),
            QualityGateRule("security", CheckType.SECURITY, CheckSeverity.WARNING, "Sec"),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        # Gate passes because security is only a warning
        assert result.passed is True
        assert len(result.warnings) >= 1

    @pytest.mark.asyncio
    async def test_pre_completion_validation(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Pre-completion validation for task."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 95,
            "issues": [],
        }

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=sample_gate_rules,
        )

        result = await manager.validate_for_completion("/path/to/repo")

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_pre_completion_validation_fails(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Pre-completion validation fails task."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": False,
            "score": 50,
            "issues": ["critical issue"],
        }

        rules = [
            QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED, "Lint"),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.validate_for_completion("/path/to/repo")

        assert result.passed is False
        assert "lint" in result.failed_required_checks

    @pytest.mark.asyncio
    async def test_threshold_check(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Check with threshold requirement."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 75,  # Below threshold
            "issues": [],
        }

        rules = [
            QualityGateRule(
                "coverage",
                CheckType.TEST,
                CheckSeverity.REQUIRED,
                "Coverage >= 80%",
                threshold=80.0,
            ),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        assert result.passed is False
        # The threshold check should fail

    @pytest.mark.asyncio
    async def test_add_rule(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Add a new quality gate rule."""
        manager = QualityGateManager(task_store=mock_task_store)

        rule = QualityGateRule(
            "new_check",
            CheckType.COMPLEXITY,
            CheckSeverity.WARNING,
            "Complexity check",
        )

        manager.add_rule(rule)

        assert len(manager.rules) == 1
        assert manager.rules[0].name == "new_check"

    @pytest.mark.asyncio
    async def test_remove_rule(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Remove a quality gate rule."""
        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
        )

        manager.remove_rule("lint_pass")

        assert len(manager.rules) == 3
        assert all(r.name != "lint_pass" for r in manager.rules)

    @pytest.mark.asyncio
    async def test_enable_disable_rule(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Enable and disable a rule."""
        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
        )

        manager.disable_rule("lint_pass")
        assert manager.get_rule("lint_pass").enabled is False

        manager.enable_rule("lint_pass")
        assert manager.get_rule("lint_pass").enabled is True

    def test_get_rule(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Get a rule by name."""
        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
        )

        rule = manager.get_rule("lint_pass")

        assert rule is not None
        assert rule.name == "lint_pass"

    def test_get_nonexistent_rule(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get a rule that doesn't exist."""
        manager = QualityGateManager(task_store=mock_task_store)

        rule = manager.get_rule("nonexistent")

        assert rule is None

    @pytest.mark.asyncio
    async def test_run_checks_with_exception(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Handle exception during check execution."""
        mock_crackerjack_client.run_quality_checks.side_effect = Exception("MCP error")

        rules = [
            QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED, "Lint"),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        # Exception should be caught and check marked as failed
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_calculate_overall_score(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
    ) -> None:
        """Calculate overall score from check results."""
        mock_crackerjack_client.run_quality_checks.side_effect = [
            {"passed": True, "score": 100, "issues": []},
            {"passed": True, "score": 90, "issues": []},
            {"passed": True, "score": 80, "issues": []},
            {"passed": True, "score": 95, "issues": []},
        ]

        rules = [
            QualityGateRule("lint", CheckType.LINT, CheckSeverity.REQUIRED, "Lint"),
            QualityGateRule("type", CheckType.TYPE_CHECK, CheckSeverity.REQUIRED, "Type"),
            QualityGateRule("test", CheckType.TEST, CheckSeverity.REQUIRED, "Test"),
            QualityGateRule("security", CheckType.SECURITY, CheckSeverity.WARNING, "Sec"),
        ]

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=rules,
        )

        result = await manager.run_all_checks("/path/to/repo")

        # Overall score should be average: (100 + 90 + 80 + 95) / 4 = 91.25
        assert result.overall_score == pytest.approx(91.25, rel=0.1)

    @pytest.mark.asyncio
    async def test_get_quality_summary(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Get quality summary statistics."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 95,
            "issues": [],
        }

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=sample_gate_rules,
        )

        await manager.run_all_checks("/path/to/repo")
        summary = manager.get_quality_summary()

        assert summary["total_checks"] == 4
        assert summary["passed_checks"] >= 0
        assert summary["failed_checks"] >= 0

    @pytest.mark.asyncio
    async def test_run_checks_without_crackerjack_client(
        self,
        mock_task_store: AsyncMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Run checks without Crackerjack client (disabled mode)."""
        manager = QualityGateManager(
            task_store=mock_task_store,
            rules=sample_gate_rules,
            # No crackerjack_client
        )

        result = await manager.run_all_checks("/path/to/repo")

        # Without Crackerjack client, should return pass (disabled mode)
        assert result.passed is True
        assert "disabled" in result.message.lower() or "skipped" in result.message.lower()

    @pytest.mark.asyncio
    async def test_run_checks_for_multiple_repos(
        self,
        mock_task_store: AsyncMock,
        mock_crackerjack_client: MagicMock,
        sample_gate_rules: list[QualityGateRule],
    ) -> None:
        """Run checks for multiple repositories."""
        mock_crackerjack_client.run_quality_checks.return_value = {
            "passed": True,
            "score": 95,
            "issues": [],
        }

        manager = QualityGateManager(
            task_store=mock_task_store,
            crackerjack_client=mock_crackerjack_client,
            rules=sample_gate_rules,
        )

        repos = ["/path/to/repo1", "/path/to/repo2"]
        results = await manager.run_checks_for_repos(repos)

        assert len(results) == 2
        assert all(r.passed for r in results.values())
