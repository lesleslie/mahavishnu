"""Tests for core/task_audit.py — audit logging with field redaction."""
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.task_audit import (
    TaskAuditLogger,
    TaskEventType,
    get_task_audit_logger,
)


# ---------------------------------------------------------------------------
# TaskEventType enum
# ---------------------------------------------------------------------------


class TestTaskEventType:
    def test_all_members_exist(self):
        members = list(TaskEventType)
        assert TaskEventType.TASK_CREATED in members
        assert TaskEventType.TASK_UPDATED in members
        assert TaskEventType.TASK_DELETED in members
        assert TaskEventType.TASK_ASSIGNED in members
        assert TaskEventType.WORKTREE_CREATED in members
        assert TaskEventType.QUALITY_GATE_PASSED in members

    def test_string_values(self):
        for member in TaskEventType:
            assert isinstance(member.value, str)

    def test_enum_comparison(self):
        assert TaskEventType.TASK_CREATED != TaskEventType.TASK_UPDATED


# ---------------------------------------------------------------------------
# _redact_sensitive_fields
# ---------------------------------------------------------------------------


class TestRedaction:
    def setup_method(self):
        self.logger = TaskAuditLogger(db=None)

    def test_plain_string_passthrough(self):
        result = self.logger._redact_sensitive_fields({"title": "Hello"})
        assert result["title"] == "Hello"

    def test_sensitive_field_redacted(self):
        result = self.logger._redact_sensitive_fields({"description": "secret info"})
        assert result["description"] == "[REDACTED (11 characters)]"

    def test_metadata_dict_redacted(self):
        # metadata is in SENSITIVE_FIELDS, so dict value gets recursively redacted
        result = self.logger._redact_sensitive_fields({"metadata": {"k": "v"}})
        assert result["metadata"] == {"k": "v"}  # no sensitive keys inside

    def test_nested_sensitive_key(self):
        result = self.logger._redact_sensitive_fields(
            {"config": {"api_key": "s123", "password": "pwd", "token": "abc"}}
        )
        assert result["config"]["api_key"] == "[REDACTED (4 characters)]"
        assert result["config"]["password"] == "[REDACTED (3 characters)]"

    def test_list_value_redacted(self):
        result = self.logger._redact_sensitive_fields({"tags": ["a", "b"]})
        assert result["tags"] == "[REDACTED (2 items)]"

    def test_none_value_preserved(self):
        result = self.logger._redact_sensitive_fields({"title": "Hello", "count": None})
        assert result["title"] == "Hello"
        assert result["count"] is None

    def test_non_sensitive_fields_pass_through(self):
        result = self.logger._redact_sensitive_fields(
            {"title": "Hello", "status": "in_progress", "priority": "high", "repository": "repo"}
        )
        assert result["title"] == "Hello"
        assert result["status"] == "in_progress"
        assert result["priority"] == "high"

    def test_recursive_nested_dict(self):
        result = self.logger._redact_sensitive_fields(
            {"config": {"nested": {"api_key": "s123"}}}
        )
        assert result["config"]["nested"]["api_key"] == "[REDACTED (4 characters)]"

    def test_non_sensitive_nested_preserved(self):
        result = self.logger._redact_sensitive_fields(
            {"config": {"db_host": "localhost", "port": 5432}}
        )
        assert result["config"]["db_host"] == "localhost"
        assert result["config"]["port"] == 5432

    def test_empty_dict(self):
        result = self.logger._redact_sensitive_fields({})
        assert result == {}


# ---------------------------------------------------------------------------
# log_event and convenience methods (no db)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLogEventNoDb:
    async def test_log_event_returns_zero(self):
        logger = TaskAuditLogger()
        result = await logger.log_event(
            TaskEventType.TASK_CREATED, 123, "user-abc", {"title": "Fix bug"}
        )
        assert result == 0

    async def test_log_event_with_db(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = "INSERT 42"
        logger = TaskAuditLogger(mock_db)
        result = await logger.log_event(
            TaskEventType.TASK_CREATED, 45, "user-1", {"title": "Test"}
        )
        mock_db.execute.assert_called_once()
        assert result == 42

    async def test_log_task_created(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_created(1, "u1", {"title": "Bug"})
        assert result == 0

    async def test_log_task_updated(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_updated(1, "u1", {"status": "done"})
        assert result == 0

    async def test_log_task_deleted_with_reason(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_deleted(1, "u1", reason="deprecated")
        assert result == 0

    async def test_log_task_deleted_without_reason(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_deleted(1, "u1")
        assert result == 0

    async def test_log_task_assigned(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_assigned(1, "u1", "u2")
        assert result == 0

    async def test_log_task_assigned_with_previous(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_assigned(1, "u1", "u2", previous_assignee="u0")
        assert result == 0

    async def test_log_task_started_with_worktree(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_started(1, "u1", worktree_path="/tmp/wt")
        assert result == 0

    async def test_log_task_started_without_worktree(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_started(1, "u1")
        assert result == 0

    async def test_log_task_completed_with_qg(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_completed(
            1, "u1", quality_gate_result={"passed": True, "checks": [], "score": 0.95}
        )
        assert result == 0

    async def test_log_task_completed_without_qg(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_completed(1, "u1")
        assert result == 0

    async def test_log_task_cancelled(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_cancelled(1, "u1", reason="duplicate")
        assert result == 0

    async def test_log_task_blocked(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_blocked(1, "u1", blocked_by_task_id=2)
        assert result == 0

    async def test_log_task_blocked_with_reason(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_blocked(1, "u1", reason="waiting for fix")
        assert result == 0

    async def test_log_task_unblocked(self):
        logger = TaskAuditLogger()
        result = await logger.log_task_unblocked(1, "u1", 2)
        assert result == 0

    async def test_log_quality_gate_result_passed(self):
        logger = TaskAuditLogger()
        result = await logger.log_quality_gate_result(1, "u1", True, [{"name": "lint", "passed": True}], 0.95)
        assert result == 0

    async def test_log_quality_gate_result_failed(self):
        logger = TaskAuditLogger()
        result = await logger.log_quality_gate_result(1, "u1", False, [{"name": "lint", "passed": False}])
        assert result == 0

    async def test_log_worktree_created(self):
        logger = TaskAuditLogger()
        result = await logger.log_worktree_created(1, "u1", "/tmp/wt", "fix")
        assert result == 0

    async def test_log_worktree_removed(self):
        logger = TaskAuditLogger()
        result = await logger.log_worktree_removed(1, "u1", "/tmp/wt")
        assert result == 0

    async def test_log_quality_gate_passed(self):
        logger = TaskAuditLogger()
        result = await logger.log_quality_gate_passed(1, "u1", [{"name": "lint", "passed": True}])
        assert result == 0

    async def test_log_quality_gate_failed(self):
        logger = TaskAuditLogger()
        result = await logger.log_quality_gate_failed(
            1, "u1", [{"name": "lint", "passed": False}], failure_reasons=["timeout"]
        )
        assert result == 0

    async def test_log_access_denied(self):
        logger = TaskAuditLogger()
        result = await logger.log_access_denied(1, "u1", "delete", "unauthorized")
        assert result == 0

    async def test_log_access_denied_no_task(self):
        logger = TaskAuditLogger()
        result = await logger.log_access_denied(None, "u1", "delete", "unauthorized")
        assert result == 0

    async def test_log_validation_failure(self):
        logger = TaskAuditLogger()
        result = await logger.log_validation_failure("u1", "create", ["title required"])
        assert result == 0

    async def test_log_validation_failure_with_task_data(self):
        logger = TaskAuditLogger()
        result = await logger.log_validation_failure(
            "u1", "create", ["title required"], task_data={"foo": "bar"}
        )
        assert result == 0


# ---------------------------------------------------------------------------
# get_task_history / get_user_activity (mock db)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDbQueries:
    async def test_get_task_history(self):
        mock_db = AsyncMock()
        mock_db.fetch_all.return_value = []
        logger = TaskAuditLogger(mock_db)
        result = await logger.get_task_history(1)
        assert result == []
        mock_db.fetch_all.assert_called_once()

    async def test_get_user_activity(self):
        mock_db = AsyncMock()
        mock_db.fetch_all.return_value = []
        logger = TaskAuditLogger(mock_db)
        result = await logger.get_user_activity("u1")
        assert result == []
        mock_db.fetch_all.assert_called_once()


# ---------------------------------------------------------------------------
# Singleton / factory
# ---------------------------------------------------------------------------


class TestGetTaskAuditLogger:
    def test_singleton(self):
        logger1 = get_task_audit_logger()
        logger2 = get_task_audit_logger()
        assert logger1 is logger2
        assert isinstance(logger1, TaskAuditLogger)

    def test_with_db(self):
        import mahavishnu.core.task_audit as mod
        # Reset singleton so we can test db injection
        original = mod._audit_logger
        try:
            mod._audit_logger = None
            mock_db = object()
            logger = get_task_audit_logger(mock_db)
            assert logger.db is mock_db
        finally:
            mod._audit_logger = original


# ---------------------------------------------------------------------------
# Sensitive field constants
# ---------------------------------------------------------------------------


class TestSensitiveConstants:
    def test_sensitive_fields(self):
        assert "description" in TaskAuditLogger.SENSITIVE_FIELDS
        assert "metadata" in TaskAuditLogger.SENSITIVE_FIELDS
        assert "tags" in TaskAuditLogger.SENSITIVE_FIELDS

    def test_sensitive_keys(self):
        for key in ("api_key", "password", "secret", "token", "auth"):
            assert key in TaskAuditLogger.SENSITIVE_KEYS

    def test_always_include(self):
        for field in ("title", "repository", "priority", "status"):
            assert field in TaskAuditLogger.ALWAYS_INCLUDE
