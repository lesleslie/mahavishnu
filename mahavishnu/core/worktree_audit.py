"""
Audit logging for all worktree operations (SECURITY-003 fix).

Ensures SOC 2, ISO 27001, and PCI DSS compliance by logging all worktree
operations with complete context for forensic analysis.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorktreeAuditLogger:
    """Comprehensive audit logging for worktree operations.

    This class provides structured audit logging for all worktree operations,
    ensuring compliance with security standards (SOC 2, ISO 27001, PCI DSS).

    Audit Events:
    - worktree_create_attempt: Before creation
    - worktree_create_success: After successful creation
    - worktree_create_failure: When creation fails
    - worktree_remove_attempt: Before removal
    - worktree_remove_success: After successful removal
    - worktree_remove_forced: When force removal with reason
    - worktree_prune: Prune operations
    - worktree_list: List operations
    - security_rejection: When validation fails

    All events include:
    - Timestamp (UTC)
    - User ID
    - Tool name
    - Parameters (sensitive values redacted)
    - Result (success/failure/denied)
    - Error message (if applicable)

    Example:
        >>> audit_logger = WorktreeAuditLogger()
        >>> audit_logger.log_creation_attempt(
        ...     user_id="user-123",
        ...     repo_nickname="mahavishnu",
        ...     branch="feature-auth",
        ...     worktree_path="/worktrees/mahavishnu/feature-auth"
        ... )
    """

    def __init__(self) -> None:
        """Initialize audit logger."""
        logger.debug("WorktreeAuditLogger initialized")

    @staticmethod
    def _redact_secrets(params: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive parameter values.

        Args:
            params: Original parameters

        Returns:
            Parameters with sensitive values redacted
        """
        redacted = {}

        sensitive_keys = {
            "password",
            "token",
            "key",
            "secret",
            "credential",
            "api_key",
            "apikey",
            "auth_token",
            "access_token",
            "ssh_key",
            "private_key",
            "passphrase",
            "force_reason",  # Not actually secret but may contain sensitive info
        }

        for key, value in params.items():
            key_lower = key.lower()

            # Check if this is a sensitive key
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                # Show first 4 characters for debugging (but not the full value)
                if isinstance(value, str) and len(value) > 4:
                    preview = value[:4]
                    redacted[key] = f"{preview}***"
                elif isinstance(value, str):
                    redacted[key] = "***"
                else:
                    redacted[key] = "***"
            else:
                redacted[key] = value

        return redacted

    def _log_to_audit_trail(
        self,
        event_type: str,
        user_id: str | None,
        tool_name: str,
        params: dict[str, Any],
        result: str,
        error: str | None = None,
    ) -> None:
        """Log event to audit trail.

        Args:
            event_type: Type of event
            user_id: User ID
            tool_name: Name of the tool
            params: Event parameters (will be redacted)
            result: Result of operation (success/failure/denied)
            error: Error message if applicable
        """
        timestamp = datetime.now(tz=UTC).isoformat()

        # Redact sensitive parameters
        safe_params = self._redact_secrets(params)

        # Create log entry
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "user_id": user_id,
            "tool_name": tool_name,
            "params": safe_params,
            "result": result,
            "error": error,
        }

        # Log to application logger (for immediate visibility)
        log_message = (
            f"[AUDIT] {event_type}: user={user_id}, tool={tool_name}, "
            f"result={result}"
        )

        if error:
            log_message += f", error={error}"

        if result == "denied":
            logger.warning(log_message)
        elif result == "failure":
            logger.error(log_message)
        else:
            logger.info(log_message)

        # Log to persistent audit log (for forensic analysis)
        try:
            from ..mcp.auth import get_audit_logger

            get_audit_logger().log(
                event_type=event_type,
                user_id=user_id,
                tool_name=tool_name,
                params=safe_params,
                result=result,
                error=error,
            )
        except Exception as e:
            # Don't fail if audit logging fails
            logger.error(f"Failed to write to audit log: {e}")

    # =========================================================================
    # CREATION AUDIT LOGS
    # =========================================================================

    def log_creation_attempt(
        self,
        user_id: str | None,
        repo_nickname: str,
        branch: str,
        worktree_path: str,
        create_branch: bool = False,
    ) -> None:
        """Log worktree creation attempt (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            branch: Branch name
            worktree_path: Path to worktree
            create_branch: Whether branch will be created
        """
        self._log_to_audit_trail(
            event_type="worktree_create_attempt",
            user_id=user_id,
            tool_name="create_worktree",
            params={
                "repo_nickname": repo_nickname,
                "branch": branch,
                "worktree_path": worktree_path,
                "create_branch": create_branch,
            },
            result="pending",
        )

    def log_creation_success(
        self,
        user_id: str | None,
        repo_nickname: str,
        branch: str,
        worktree_path: str,
    ) -> None:
        """Log worktree creation success (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            branch: Branch name
            worktree_path: Path to created worktree
        """
        self._log_to_audit_trail(
            event_type="worktree_create_success",
            user_id=user_id,
            tool_name="create_worktree",
            params={
                "repo_nickname": repo_nickname,
                "branch": branch,
                "worktree_path": worktree_path,
            },
            result="success",
        )

    def log_creation_failure(
        self,
        user_id: str | None,
        repo_nickname: str,
        branch: str,
        worktree_path: str,
        error: str,
    ) -> None:
        """Log worktree creation failure (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            branch: Branch name
            worktree_path: Path to worktree
            error: Error message
        """
        self._log_to_audit_trail(
            event_type="worktree_create_failure",
            user_id=user_id,
            tool_name="create_worktree",
            params={
                "repo_nickname": repo_nickname,
                "branch": branch,
                "worktree_path": worktree_path,
            },
            result="failure",
            error=error,
        )

    # =========================================================================
    # REMOVAL AUDIT LOGS
    # =========================================================================

    def log_removal_attempt(
        self,
        user_id: str | None,
        repo_nickname: str,
        worktree_path: str,
        force: bool,
    ) -> None:
        """Log worktree removal attempt.

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            worktree_path: Path to worktree
            force: Whether force removal
        """
        self._log_to_audit_trail(
            event_type="worktree_remove_attempt",
            user_id=user_id,
            tool_name="remove_worktree",
            params={
                "repo_nickname": repo_nickname,
                "worktree_path": worktree_path,
                "force": force,
            },
            result="pending",
        )

    def log_removal_success(
        self,
        user_id: str | None,
        repo_nickname: str,
        worktree_path: str,
        force: bool,
    ) -> None:
        """Log worktree removal success.

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            worktree_path: Path to worktree
            force: Whether force was used
        """
        self._log_to_audit_trail(
            event_type="worktree_remove_success",
            user_id=user_id,
            tool_name="remove_worktree",
            params={
                "repo_nickname": repo_nickname,
                "worktree_path": worktree_path,
                "force": force,
            },
            result="success",
        )

    def log_forced_removal(
        self,
        user_id: str | None,
        repo_nickname: str,
        worktree_path: str,
        force_reason: str,
        has_uncommitted: bool,
        backup_path: str | None,
    ) -> None:
        """Log force worktree removal with reason (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            worktree_path: Path to worktree
            force_reason: Reason for force removal
            has_uncommitted: Whether worktree has uncommitted changes
            backup_path: Path to backup created before removal
        """
        self._log_to_audit_trail(
            event_type="worktree_remove_forced",
            user_id=user_id,
            tool_name="remove_worktree",
            params={
                "repo_nickname": repo_nickname,
                "worktree_path": worktree_path,
                "force_reason": force_reason,
                "has_uncommitted": has_uncommitted,
                "backup_path": backup_path,
            },
            result="success",
        )

    def log_removal_failure(
        self,
        user_id: str | None,
        repo_nickname: str,
        worktree_path: str,
        error: str,
    ) -> None:
        """Log worktree removal failure.

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            worktree_path: Path to worktree
            error: Error message
        """
        self._log_to_audit_trail(
            event_type="worktree_remove_failure",
            user_id=user_id,
            tool_name="remove_worktree",
            params={
                "repo_nickname": repo_nickname,
                "worktree_path": worktree_path,
            },
            result="failure",
            error=error,
        )

    # =========================================================================
    # OTHER OPERATIONS AUDIT LOGS
    # =========================================================================

    def log_prune_operation(
        self,
        user_id: str | None,
        repo_nickname: str,
        pruned_count: int,
    ) -> None:
        """Log worktree prune operation (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            pruned_count: Number of worktrees pruned
        """
        self._log_to_audit_trail(
            event_type="worktree_prune",
            user_id=user_id,
            tool_name="prune_worktrees",
            params={
                "repo_nickname": repo_nickname,
                "pruned_count": pruned_count,
            },
            result="success",
        )

    def log_list_operation(
        self,
        user_id: str | None,
        repo_nickname: str | None,
    ) -> None:
        """Log worktree list operation (SECURITY-003 fix).

        Args:
            user_id: User ID
            repo_nickname: Repository nickname (None = all repos)
        """
        self._log_to_audit_trail(
            event_type="worktree_list",
            user_id=user_id,
            tool_name="list_worktrees",
            params={"repo_nickname": repo_nickname},
            result="success",
        )

    def log_security_rejection(
        self,
        user_id: str | None,
        operation: str,
        rejection_reason: str,
        params: dict[str, Any],
    ) -> None:
        """Log security rejection event.

        Args:
            user_id: User ID
            operation: Operation being attempted
            rejection_reason: Why operation was rejected
            params: Operation parameters
        """
        self._log_to_audit_trail(
            event_type="security_rejection",
            user_id=user_id,
            tool_name="WorktreePathValidator",
            params={
                "operation": operation,
                "rejection_reason": rejection_reason,
                **params,
            },
            result="denied",
            error=rejection_reason,
        )

    def log_backup_created(
        self,
        user_id: str | None,
        repo_nickname: str,
        branch: str,
        worktree_path: str,
        backup_path: str,
    ) -> None:
        """Log backup creation event.

        Args:
            user_id: User ID
            repo_nickname: Repository nickname
            branch: Branch name
            worktree_path: Original worktree path
            backup_path: Path to backup
        """
        self._log_to_audit_trail(
            event_type="worktree_backup_created",
            user_id=user_id,
            tool_name="WorktreeBackupManager",
            params={
                "repo_nickname": repo_nickname,
                "branch": branch,
                "worktree_path": worktree_path,
                "backup_path": backup_path,
            },
            result="success",
        )
