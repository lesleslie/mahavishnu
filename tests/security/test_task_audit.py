"""Tests for task audit logging.

This module tests the TaskAuditLogger class to ensure:
1. All task events are logged correctly
2. Sensitive fields are properly redacted
3. User attribution is tracked
4. Timestamps are in UTC
5. Structured logging works correctly
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.task_audit import TaskAuditLogger, get_task_audit_logger


@pytest.fixture
def audit_logger():
    """Create task audit logger for testing."""
    return TaskAuditLogger()


@pytest.fixture
def mock_logger():
    """Create mock logger for testing."""
    with patch("mahavishnu.core.task_audit.logger") as mock:
        yield mock


class TestSensitiveFieldRedaction:
    """Tests for sensitive field redaction."""

    def test_redact_description(self, audit_logger):
        """Test that description field is redacted."""
        data = {
            "title": "Fix bug",
            "description": "Secret information here",
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        assert redacted["title"] == "Fix bug"
        assert "Secret" not in redacted["description"]
        assert "[REDACTED" in redacted["description"]
        assert "(23 characters)" in redacted["description"]

    def test_redact_metadata(self, audit_logger):
        """Test that metadata field is recursively redacted."""
        data = {
            "title": "Fix bug",
            "metadata": {"api_key": "secret123", "safe_field": "value"},
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        assert redacted["title"] == "Fix bug"
        # Metadata is recursively redacted - sensitive keys within are redacted
        assert redacted["metadata"]["api_key"].startswith("[REDACTED")
        assert "secret" not in redacted["metadata"]["api_key"]
        assert redacted["metadata"]["safe_field"] == "value"

    def test_redact_nested_dict(self, audit_logger):
        """Test that nested dicts in sensitive fields are recursively redacted."""
        data = {
            "metadata": {
                "nested": {
                    "description": "sensitive description",
                    "safe": "public",
                },
            },
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        # Nested dicts are recursively redacted - description is a sensitive field
        assert redacted["metadata"]["nested"]["description"].startswith("[REDACTED")
        assert "sensitive" not in redacted["metadata"]["nested"]["description"]
        assert redacted["metadata"]["nested"]["safe"] == "public"

    def test_redact_list(self, audit_logger):
        """Test that lists in sensitive fields are redacted."""
        data = {
            "tags": ["sensitive", "tags", "here"],
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        assert "[REDACTED (3 items)]" == redacted["tags"]

    def test_safe_fields_not_redacted(self, audit_logger):
        """Test that safe fields are not redacted."""
        data = {
            "id": 123,
            "title": "Fix bug",
            "repository": "session-buddy",
            "status": "in_progress",
            "priority": "high",
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        assert redacted["id"] == 123
        assert redacted["title"] == "Fix bug"
        assert redacted["repository"] == "session-buddy"
        assert redacted["status"] == "in_progress"
        assert redacted["priority"] == "high"

    def test_null_values_preserved(self, audit_logger):
        """Test that null values are preserved."""
        data = {
            "description": None,
            "metadata": None,
        }
        redacted = audit_logger._redact_sensitive_fields(data)

        assert redacted["description"] is None
        assert redacted["metadata"] is None

    def test_empty_dict(self, audit_logger):
        """Test handling of empty dictionary."""
        redacted = audit_logger._redact_sensitive_fields({})
        assert redacted == {}


class TestTaskLifecycleEvents:
    """Tests for task lifecycle event logging."""

    async def test_log_task_created(self, audit_logger, mock_logger):
        """Test task creation logging."""
        await audit_logger.log_task_created(
            task_id=123,
            user_id="user-456",
            task_data={
                "title": "Fix authentication bug",
                "repository": "session-buddy",
                "description": "Secret details",
                "priority": "high",
            },
        )

        # Check that info log was called
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_created" in call_args
        assert "user-456" in call_args

    async def test_log_task_updated(self, audit_logger, mock_logger):
        """Test task update logging."""
        await audit_logger.log_task_updated(
            task_id=123,
            user_id="user-456",
            changes={
                "status": "in_progress",
                "description": "Updated description",
            },
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_updated" in call_args

    async def test_log_task_deleted(self, audit_logger, mock_logger):
        """Test task deletion logging."""
        await audit_logger.log_task_deleted(
            task_id=123,
            user_id="user-456",
            reason="Completed elsewhere",
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_deleted" in call_args

    async def test_log_task_assigned(self, audit_logger, mock_logger):
        """Test task assignment logging."""
        await audit_logger.log_task_assigned(
            task_id=123,
            user_id="user-456",
            assigned_to="user-789",
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_assigned" in call_args

    async def test_log_task_reassignment(self, audit_logger, mock_logger):
        """Test task reassignment logging."""
        await audit_logger.log_task_assigned(
            task_id=123,
            user_id="user-456",
            assigned_to="user-789",
            previous_assignee="user-100",
        )

        mock_logger.info.assert_called_once()

    async def test_log_task_started(self, audit_logger, mock_logger):
        """Test task start logging."""
        await audit_logger.log_task_started(
            task_id=123,
            user_id="user-456",
            worktree_path="/worktrees/session-buddy/feature-auth",
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_started" in call_args

    async def test_log_task_completed(self, audit_logger, mock_logger):
        """Test task completion logging."""
        await audit_logger.log_task_completed(
            task_id=123,
            user_id="user-456",
            quality_gate_result={
                "passed": True,
                "checks": [
                    {"type": "lint", "passed": True},
                    {"type": "test", "passed": True},
                ],
            },
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_completed" in call_args

    async def test_log_task_cancelled(self, audit_logger, mock_logger):
        """Test task cancellation logging."""
        await audit_logger.log_task_cancelled(
            task_id=123,
            user_id="user-456",
            reason="Requirements changed",
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_cancelled" in call_args

    async def test_log_task_blocked(self, audit_logger, mock_logger):
        """Test task blocked logging."""
        await audit_logger.log_task_blocked(
            task_id=123,
            user_id="system",
            blocked_by_task_id=456,
            dependency_reason="Requires API changes first",
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_blocked" in call_args

    async def test_log_task_unblocked(self, audit_logger, mock_logger):
        """Test task unblocked logging."""
        await audit_logger.log_task_unblocked(
            task_id=123,
            user_id="system",
            unblocked_by_task_id=456,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "task_unblocked" in call_args


class TestQualityGateEvents:
    """Tests for quality gate event logging."""

    async def test_log_quality_gate_passed(self, audit_logger, mock_logger):
        """Test quality gate passed logging."""
        await audit_logger.log_quality_gate_passed(
            task_id=123,
            user_id="user-456",
            checks=[
                {"type": "lint", "passed": True},
                {"type": "test", "passed": True},
                {"type": "typecheck", "passed": True},
            ],
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "quality_gate_passed" in call_args

    async def test_log_quality_gate_failed(self, audit_logger, mock_logger):
        """Test quality gate failed logging."""
        await audit_logger.log_quality_gate_failed(
            task_id=123,
            user_id="user-456",
            checks=[
                {"type": "lint", "passed": True},
                {"type": "test", "passed": False},
            ],
            failure_reasons=["Test suite failed: 3 failures"],
        )

        # Failed quality gates should log as error
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "quality_gate_failed" in call_args


class TestSecurityEvents:
    """Tests for security event logging."""

    async def test_log_access_denied(self, audit_logger, mock_logger):
        """Test access denied logging."""
        await audit_logger.log_access_denied(
            task_id=123,
            user_id="user-456",
            action="delete",
            reason="Not task owner",
        )

        # Access denied should log as warning
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert "task_access_denied" in call_args
        assert "denied" in call_args

    async def test_log_validation_failure(self, audit_logger, mock_logger):
        """Test validation failure logging."""
        await audit_logger.log_validation_failure(
            user_id="user-456",
            action="create",
            validation_errors=["Title too long", "Invalid repository"],
            task_data={"title": "a" * 300, "repository": "../../../etc"},
        )

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "task_validation_failure" in call_args


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_task_audit_logger_returns_singleton(self):
        """Test that get_task_audit_logger returns same instance."""
        import mahavishnu.core.task_audit as module
        module._audit_logger = None  # Reset singleton

        logger1 = get_task_audit_logger()
        logger2 = get_task_audit_logger()

        assert logger1 is logger2


class TestEdgeCases:
    """Tests for edge cases."""

    async def test_log_task_created_minimal(self, audit_logger, mock_logger):
        """Test task creation with minimal data."""
        await audit_logger.log_task_created(
            task_id=123,
            user_id="user-456",
            task_data={"title": "Test"},
        )

        mock_logger.info.assert_called_once()

    async def test_log_task_completed_no_quality_gate(self, audit_logger, mock_logger):
        """Test task completion without quality gate."""
        await audit_logger.log_task_completed(
            task_id=123,
            user_id="user-456",
            quality_gate_result=None,
        )

        mock_logger.info.assert_called_once()

    async def test_log_access_denied_no_task_id(self, audit_logger, mock_logger):
        """Test access denied without specific task."""
        await audit_logger.log_access_denied(
            task_id=None,
            user_id="user-456",
            action="list_all",
            reason="Insufficient permissions",
        )

        mock_logger.warning.assert_called_once()
