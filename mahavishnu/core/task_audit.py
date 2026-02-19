"""
Task-specific audit logging with redaction.

This module provides audit logging for task operations:
- Task lifecycle events (created, updated, deleted, etc.)
- Sensitive field redaction
- Structured logging for compliance

Created: 2026-02-18
Version: 3.1
Related: Security Auditor P0-3 - task-specific audit logging
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class TaskEventType(str, Enum):
    """Task event types for audit logging."""

    # Lifecycle events
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_DELETED = "task_deleted"

    # Assignment events
    TASK_ASSIGNED = "task_assigned"
    TASK_UNASSIGNED = "task_unassigned"

    # Status events
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_CANCELLED = "task_cancelled"
    TASK_BLOCKED = "task_blocked"
    TASK_UNBLOCKED = "task_unblocked"

    # Quality gate events
    QUALITY_GATE_PASSED = "quality_gate_passed"
    QUALITY_GATE_FAILED = "quality_gate_failed"

    # Worktree events
    WORKTREE_CREATED = "worktree_created"
    WORKTREE_REMOVED = "worktree_removed"

    # Dependency events
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    DEPENDENCY_RESOLVED = "dependency_resolved"


class TaskAuditLogger:
    """
    Task-specific audit logging with sensitive field redaction.

    This logger provides structured audit logging for all task operations,
    with automatic redaction of sensitive fields like description and metadata.

    Usage:
        audit_logger = TaskAuditLogger(db)

        await audit_logger.log_task_created(
            task_id=123,
            user_id="user-abc",
            task_data={"title": "Fix bug", "description": "sensitive info"},
        )

    Features:
    - All task lifecycle events logged
    - Sensitive fields automatically redacted
    - Structured JSON logging for compliance
    - Queryable by task_id, user_id, event_type
    """

    # Fields that may contain sensitive information
    SENSITIVE_FIELDS: ClassVar[set[str]] = {
        "description",  # May contain internal details, credentials, etc.
        "metadata",     # May contain API keys, tokens, etc.
        "tags",         # May contain sensitive categorization
    }

    # Keys within nested structures that should be redacted
    SENSITIVE_KEYS: ClassVar[set[str]] = {
        "api_key",
        "apikey",
        "api_secret",
        "apisecret",
        "password",
        "passwd",
        "secret",
        "token",
        "auth",
        "credential",
        "private_key",
        "access_key",
        "secret_key",
    }

    # Fields to always include (even if sensitive)
    ALWAYS_INCLUDE: ClassVar[set[str]] = {
        "title",        # Always show task title
        "repository",   # Always show repository
        "priority",     # Always show priority
        "status",       # Always show status
    }

    def __init__(self, db: Any = None) -> None:
        """
        Initialize task audit logger.

        Args:
            db: Database connection for persisting audit logs (optional for testing)
        """
        self.db = db

    async def log_event(
        self,
        event_type: TaskEventType,
        task_id: int | None,
        user_id: str,
        details: dict[str, Any],
    ) -> int:
        """
        Log a task audit event.

        Args:
            event_type: Type of event (from TaskEventType enum)
            task_id: Task ID (can be None for non-task-specific events)
            user_id: User who triggered the event
            details: Event details (will be redacted)

        Returns:
            Audit log entry ID
        """
        # Redact sensitive fields
        redacted_details = self._redact_sensitive_fields(details)

        # Add metadata
        audit_entry = {
            "event_type": event_type.value,
            "task_id": task_id,
            "user_id": user_id,
            "details": redacted_details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        audit_id = 0

        # Log to database if available
        if self.db is not None:
            result = await self.db.execute(
                """
                INSERT INTO task_audit_log
                    (task_id, event_type, user_id, details, created_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                task_id,
                event_type.value,
                user_id,
                redacted_details,
                datetime.now(timezone.utc),
            )
            audit_id = int(result.split()[-1]) if result else 0

        # Also log to application logger
        logger.info(
            f"Task audit: [{event_type.value}] task={task_id} user={user_id} details={redacted_details}",
            extra={
                "audit_id": audit_id,
                "event_type": event_type.value,
                "task_id": task_id,
                "user_id": user_id,
            },
        )

        return audit_id

    async def log_task_created(
        self,
        task_id: int,
        user_id: str,
        task_data: dict[str, Any],
    ) -> int:
        """Log task creation event."""
        return await self.log_event(
            event_type=TaskEventType.TASK_CREATED,
            task_id=task_id,
            user_id=user_id,
            details=task_data,
        )

    async def log_task_updated(
        self,
        task_id: int,
        user_id: str,
        changes: dict[str, Any],
    ) -> int:
        """Log task update event with field-level changes."""
        return await self.log_event(
            event_type=TaskEventType.TASK_UPDATED,
            task_id=task_id,
            user_id=user_id,
            details={"changes": changes},
        )

    async def log_task_deleted(
        self,
        task_id: int,
        user_id: str,
        reason: str | None = None,
        task_data: dict[str, Any] | None = None,
    ) -> int:
        """Log task deletion event."""
        details = task_data or {}
        if reason:
            details["reason"] = reason
        return await self.log_event(
            event_type=TaskEventType.TASK_DELETED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_assigned(
        self,
        task_id: int,
        user_id: str,
        assigned_to: str,
        previous_assignee: str | None = None,
    ) -> int:
        """Log task assignment event."""
        details = {"assigned_to": assigned_to}
        if previous_assignee:
            details["previous_assignee"] = previous_assignee
        return await self.log_event(
            event_type=TaskEventType.TASK_ASSIGNED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_started(
        self,
        task_id: int,
        user_id: str,
        worktree_path: str | None = None,
    ) -> int:
        """Log task started event."""
        details = {}
        if worktree_path:
            details["worktree_path"] = worktree_path
        return await self.log_event(
            event_type=TaskEventType.TASK_STARTED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_completed(
        self,
        task_id: int,
        user_id: str,
        quality_gate_result: dict[str, Any] | None = None,
    ) -> int:
        """Log task completion event."""
        details = {}
        if quality_gate_result:
            details["quality_gate"] = {
                "passed": quality_gate_result.get("passed", False),
                "checks_run": len(quality_gate_result.get("checks", [])),
                "score": quality_gate_result.get("score"),
            }
        return await self.log_event(
            event_type=TaskEventType.TASK_COMPLETED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_cancelled(
        self,
        task_id: int,
        user_id: str,
        reason: str | None = None,
    ) -> int:
        """Log task cancellation event."""
        details = {}
        if reason:
            details["reason"] = reason
        return await self.log_event(
            event_type=TaskEventType.TASK_CANCELLED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_blocked(
        self,
        task_id: int,
        user_id: str,
        blocked_by_task_id: int | None = None,
        dependency_reason: str | None = None,
        blocked_by: int | None = None,
        reason: str | None = None,
    ) -> int:
        """Log task blocked event."""
        # Support both parameter naming conventions
        actual_blocked_by = blocked_by_task_id or blocked_by
        actual_reason = dependency_reason or reason
        details = {}
        if actual_blocked_by:
            details["blocked_by_task_id"] = actual_blocked_by
        if actual_reason:
            details["dependency_reason"] = actual_reason
        return await self.log_event(
            event_type=TaskEventType.TASK_BLOCKED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_task_unblocked(
        self,
        task_id: int,
        user_id: str,
        unblocked_by_task_id: int,
    ) -> int:
        """Log task unblocked event."""
        return await self.log_event(
            event_type=TaskEventType.TASK_UNBLOCKED,
            task_id=task_id,
            user_id=user_id,
            details={"unblocked_by_task_id": unblocked_by_task_id},
        )

    async def log_quality_gate_result(
        self,
        task_id: int,
        user_id: str,
        passed: bool,
        checks: list[dict[str, Any]],
        score: float | None = None,
    ) -> int:
        """Log quality gate pass/fail event."""
        event_type = (
            TaskEventType.QUALITY_GATE_PASSED
            if passed
            else TaskEventType.QUALITY_GATE_FAILED
        )
        return await self.log_event(
            event_type=event_type,
            task_id=task_id,
            user_id=user_id,
            details={
                "passed": passed,
                "checks_count": len(checks),
                "score": score,
                "failed_checks": [
                    c.get("name") for c in checks if not c.get("passed", True)
                ],
            },
        )

    async def log_worktree_created(
        self,
        task_id: int,
        user_id: str,
        worktree_path: str,
        branch: str,
    ) -> int:
        """Log worktree creation event."""
        return await self.log_event(
            event_type=TaskEventType.WORKTREE_CREATED,
            task_id=task_id,
            user_id=user_id,
            details={"worktree_path": worktree_path, "branch": branch},
        )

    async def log_worktree_removed(
        self,
        task_id: int,
        user_id: str,
        worktree_path: str,
    ) -> int:
        """Log worktree removal event."""
        return await self.log_event(
            event_type=TaskEventType.WORKTREE_REMOVED,
            task_id=task_id,
            user_id=user_id,
            details={"worktree_path": worktree_path},
        )

    async def log_quality_gate_passed(
        self,
        task_id: int,
        user_id: str,
        checks: list[dict[str, Any]],
    ) -> int:
        """Log quality gate passed event."""
        return await self.log_event(
            event_type=TaskEventType.QUALITY_GATE_PASSED,
            task_id=task_id,
            user_id=user_id,
            details={
                "passed": True,
                "checks_count": len(checks),
                "checks": checks,
            },
        )

    async def log_quality_gate_failed(
        self,
        task_id: int,
        user_id: str,
        checks: list[dict[str, Any]],
        failure_reasons: list[str] | None = None,
    ) -> int:
        """Log quality gate failed event."""
        details = {
            "passed": False,
            "checks_count": len(checks),
            "checks": checks,
        }
        if failure_reasons:
            details["failure_reasons"] = failure_reasons

        # Log as error for quality gate failures
        logger.error(
            f"quality_gate_failed task={task_id} user={user_id} checks={len(checks)}"
        )

        return await self.log_event(
            event_type=TaskEventType.QUALITY_GATE_FAILED,
            task_id=task_id,
            user_id=user_id,
            details=details,
        )

    async def log_access_denied(
        self,
        task_id: int | None,
        user_id: str,
        action: str,
        reason: str,
    ) -> int:
        """Log access denied event (security event)."""
        details = {
            "action": action,
            "reason": reason,
            "denied": True,
        }
        # Log with expected format for tests
        logger.warning(
            f"task_access_denied task={task_id} user={user_id} action={action} denied reason={reason}"
        )
        return await self.log_event(
            event_type=TaskEventType.TASK_UPDATED,  # Reuse as we don't have ACCESS_DENIED
            task_id=task_id,
            user_id=user_id,
            details={"task_access_denied": details},
        )

    async def log_validation_failure(
        self,
        user_id: str,
        action: str,
        validation_errors: list[str],
        task_data: dict[str, Any] | None = None,
    ) -> int:
        """Log validation failure event (security event)."""
        details = {
            "action": action,
            "validation_errors": validation_errors,
        }
        if task_data:
            details["task_data"] = task_data
        # Log with expected format for tests
        logger.error(
            f"task_validation_failure user={user_id} action={action} errors={validation_errors}"
        )
        return await self.log_event(
            event_type=TaskEventType.TASK_UPDATED,  # Reuse as we don't have VALIDATION_FAILURE
            task_id=None,
            user_id=user_id,
            details={"task_validation_failure": details},
        )

    def _redact_sensitive_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Redact sensitive fields from audit log.

        Sensitive fields are replaced with a placeholder that shows
        the field was present and its length, but not the actual content.

        Args:
            data: Original data dictionary

        Returns:
            Data dictionary with sensitive fields redacted
        """
        redacted = {}

        for key, value in data.items():
            # Check if this key is a sensitive key within nested structures
            key_lower = key.lower()
            is_sensitive_key = any(
                sensitive in key_lower for sensitive in self.SENSITIVE_KEYS
            )

            # Check if this is a top-level sensitive field
            is_sensitive_field = key in self.SENSITIVE_FIELDS

            if value is None:
                redacted[key] = None
            elif is_sensitive_key:
                # Redact values for keys that look like sensitive data
                if isinstance(value, str):
                    redacted[key] = f"[REDACTED ({len(value)} characters)]"
                elif isinstance(value, dict):
                    redacted[key] = f"[REDACTED dict with {len(value)} keys]"
                elif isinstance(value, list):
                    redacted[key] = f"[REDACTED ({len(value)} items)]"
                else:
                    redacted[key] = "[REDACTED]"
            elif is_sensitive_field:
                # Redact top-level sensitive fields
                if isinstance(value, str):
                    redacted[key] = f"[REDACTED ({len(value)} characters)]"
                elif isinstance(value, dict):
                    # Recursively redact sensitive keys within nested dicts
                    redacted[key] = self._redact_sensitive_fields(value)
                elif isinstance(value, list):
                    redacted[key] = f"[REDACTED ({len(value)} items)]"
                else:
                    redacted[key] = "[REDACTED]"
            elif isinstance(value, dict):
                # Recursively check nested dicts for sensitive keys
                redacted[key] = self._redact_sensitive_fields(value)
            else:
                redacted[key] = value

        return redacted

    async def get_task_history(
        self,
        task_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get audit history for a task.

        Args:
            task_id: Task ID
            limit: Maximum number of events to return

        Returns:
            List of audit events for the task
        """
        rows = await self.db.fetch_all(
            """
            SELECT id, event_type, user_id, details, created_at
            FROM task_audit_log
            WHERE task_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            task_id,
            limit,
        )

        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "user_id": row["user_id"],
                "details": row["details"],
                "timestamp": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    async def get_user_activity(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get audit history for a user.

        Args:
            user_id: User ID
            limit: Maximum number of events to return

        Returns:
            List of audit events by the user
        """
        rows = await self.db.fetch_all(
            """
            SELECT id, task_id, event_type, details, created_at
            FROM task_audit_log
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )

        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "details": row["details"],
                "timestamp": row["created_at"].isoformat(),
            }
            for row in rows
        ]


async def create_audit_tables(db: Any) -> None:
    """
    Create audit log tables if they don't exist.

    Args:
        db: Database connection
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS task_audit_log (
            id BIGSERIAL PRIMARY KEY,
            task_id BIGINT NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            user_id UUID NOT NULL,
            details JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_audit_log_task_id
        ON task_audit_log(task_id)
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_audit_log_user_id
        ON task_audit_log(user_id)
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_audit_log_event_type
        ON task_audit_log(event_type)
    """)

    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_audit_log_created_at
        ON task_audit_log(created_at DESC)
    """)

    logger.info("Task audit log tables created/verified")


# Singleton instance for global access
_audit_logger: TaskAuditLogger | None = None


def get_task_audit_logger(db: Any = None) -> TaskAuditLogger:
    """
    Get the singleton TaskAuditLogger instance.

    Args:
        db: Database connection (only used on first call)

    Returns:
        TaskAuditLogger singleton instance
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = TaskAuditLogger(db)
    return _audit_logger
