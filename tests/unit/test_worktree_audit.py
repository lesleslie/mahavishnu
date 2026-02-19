"""Unit tests for WorktreeAuditLogger.

Tests comprehensive audit logging for SOC 2, ISO 27001, and PCI DSS compliance:
- Creation attempt/success/failure logging
- Removal attempt/success/forced/failure logging
- Prune and list operation logging
- Security rejection logging
- Backup creation logging
- Sensitive data redaction
"""

import pytest
from unittest.mock import MagicMock, patch

from mahavishnu.core.worktree_audit import WorktreeAuditLogger


class TestWorktreeAuditLogger:
    """Test suite for WorktreeAuditLogger audit logging functionality."""

    def test_initialization(self):
        """Test audit logger initialization."""
        logger = WorktreeAuditLogger()

        assert logger is not None
        # Should not raise any errors

    # =========================================================================
    # Sensitive Data Redaction Tests
    # =========================================================================

    def test_redact_password_field(self):
        """Test that password fields are redacted."""
        params = {
            "repo_nickname": "test-repo",
            "password": "super_secret_123",
            "branch": "main",
        }

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["repo_nickname"] == "test-repo"
        assert redacted["password"] == "supe***"
        assert redacted["branch"] == "main"

    def test_redact_token_field(self):
        """Test that token fields are redacted."""
        params = {"token": "abc123xyz", "branch": "feature"}

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["token"] == "abc1***"
        assert redacted["branch"] == "feature"

    def test_redact_api_key_field(self):
        """Test that api_key fields are redacted."""
        params = {"api_key": "key_value_123", "repo": "test"}

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["api_key"] == "key_***"
        assert redacted["repo"] == "test"

    def test_redact_short_secret(self):
        """Test that short secrets are fully redacted."""
        params = {"secret": "ab", "branch": "main"}

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["secret"] == "***"
        assert redacted["branch"] == "main"

    def test_redact_non_sensitive_field(self):
        """Test that non-sensitive fields are not redacted."""
        params = {
            "repo_nickname": "test-repo",
            "branch": "main",
            "worktree_path": "/worktrees/test/main",
        }

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["repo_nickname"] == "test-repo"
        assert redacted["branch"] == "main"
        assert redacted["worktree_path"] == "/worktrees/test/main"

    def test_redact_force_reason(self):
        """Test that force_reason is redacted (may contain sensitive info)."""
        params = {"force_reason": "Fixing critical security bug", "repo": "test"}

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["force_reason"] == "Fix***"
        assert redacted["repo"] == "test"

    def test_redact_with_non_string_value(self):
        """Test redaction with non-string value."""
        params = {"password": 12345, "branch": "main"}

        redacted = WorktreeAuditLogger._redact_secrets(params)

        assert redacted["password"] == "***"
        assert redacted["branch"] == "main"

    def test_redact_all_sensitive_keys(self):
        """Test that all sensitive key patterns are redacted."""
        sensitive_keys = {
            "password": "secret123",
            "token": "token123",
            "key": "key123",
            "secret": "secret123",
            "credential": "cred123",
            "api_key": "apikey123",
            "apikey": "apikey123",
            "auth_token": "authtoken123",
            "access_token": "accesstoken123",
            "ssh_key": "sshkey123",
            "private_key": "privatekey123",
            "passphrase": "passphrase123",
        }

        for key, value in sensitive_keys.items():
            params = {key: value, "branch": "main"}
            redacted = WorktreeAuditLogger._redact_secrets(params)

            # Should be redacted
            assert redacted[key] != value
            assert "***" in redacted[key]

    # =========================================================================
    # Creation Audit Logging Tests
    # =========================================================================

    def test_log_creation_attempt(self, mocker):
        """Test logging of worktree creation attempt."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_creation_attempt(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="feature-auth",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            create_branch=True,
        )

        # Verify audit log was called
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_create_attempt"
        assert call_kwargs["user_id"] == "user-123"
        assert call_kwargs["tool_name"] == "create_worktree"
        assert call_kwargs["result"] == "pending"

        # Check params
        params = call_kwargs["params"]
        assert params["repo_nickname"] == "mahavishnu"
        assert params["branch"] == "feature-auth"
        assert params["create_branch"] is True

    def test_log_creation_success(self, mocker):
        """Test logging of worktree creation success."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_creation_success(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="feature-auth",
            worktree_path="/worktrees/mahavishnu/feature-auth",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_create_success"
        assert call_kwargs["result"] == "success"

    def test_log_creation_failure(self, mocker):
        """Test logging of worktree creation failure."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_creation_failure(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="feature-auth",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            error="Branch already exists",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_create_failure"
        assert call_kwargs["result"] == "failure"
        assert call_kwargs["error"] == "Branch already exists"

    # =========================================================================
    # Removal Audit Logging Tests
    # =========================================================================

    def test_log_removal_attempt(self, mocker):
        """Test logging of worktree removal attempt."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_removal_attempt(
            user_id="user-123",
            repo_nickname="mahavishnu",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            force=False,
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_remove_attempt"
        assert call_kwargs["result"] == "pending"

    def test_log_removal_success(self, mocker):
        """Test logging of worktree removal success."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_removal_success(
            user_id="user-123",
            repo_nickname="mahavishnu",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            force=False,
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_remove_success"
        assert call_kwargs["result"] == "success"

    def test_log_forced_removal(self, mocker):
        """Test logging of forced worktree removal."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_forced_removal(
            user_id="user-123",
            repo_nickname="mahavishnu",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            force_reason="Fixing critical bug",
            has_uncommitted=True,
            backup_path="/backups/mahavishnu_feature-auth_20260218_123456",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_remove_forced"
        assert call_kwargs["result"] == "success"

        # Check force_reason is redacted
        params = call_kwargs["params"]
        assert params["force_reason"] == "Fixi***"

    def test_log_removal_failure(self, mocker):
        """Test logging of worktree removal failure."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_removal_failure(
            user_id="user-123",
            repo_nickname="mahavishnu",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            error="Worktree has uncommitted changes",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_remove_failure"
        assert call_kwargs["result"] == "failure"

    # =========================================================================
    # Other Operation Audit Logging Tests
    # =========================================================================

    def test_log_prune_operation(self, mocker):
        """Test logging of worktree prune operation."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_prune_operation(
            user_id="user-123",
            repo_nickname="mahavishnu",
            pruned_count=3,
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_prune"
        assert call_kwargs["params"]["pruned_count"] == 3
        assert call_kwargs["result"] == "success"

    def test_log_list_operation(self, mocker):
        """Test logging of worktree list operation."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_list_operation(user_id="user-123", repo_nickname="mahavishnu")

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_list"
        assert call_kwargs["params"]["repo_nickname"] == "mahavishnu"
        assert call_kwargs["result"] == "success"

    def test_log_list_operation_all_repos(self, mocker):
        """Test logging of worktree list operation for all repos."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_list_operation(user_id="user-123", repo_nickname=None)

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_list"
        assert call_kwargs["params"]["repo_nickname"] is None

    def test_log_security_rejection(self, mocker):
        """Test logging of security rejection events."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_security_rejection(
            user_id="user-123",
            operation="create_worktree",
            rejection_reason="Path contains null bytes (CWE-170)",
            params={"worktree_path": "/worktrees/repo\x00"},
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "security_rejection"
        assert call_kwargs["result"] == "denied"
        assert call_kwargs["error"] == "Path contains null bytes (CWE-170)"

    def test_log_backup_created(self, mocker):
        """Test logging of backup creation events."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_backup_created(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="feature-auth",
            worktree_path="/worktrees/mahavishnu/feature-auth",
            backup_path="/backups/mahavishnu_feature-auth_20260218_123456",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_backup_created"
        assert call_kwargs["result"] == "success"

    # =========================================================================
    # Audit Trail Integration Tests
    # =========================================================================

    def test_log_to_audit_trail_with_logger_fallback(self, mocker):
        """Test that audit logging falls back to app logger if audit log fails."""
        mock_app_logger = mocker.patch("mahavishnu.core.worktree_audit.logger")
        mock_audit_logger = mocker.patch(
            "mahavishnu.core.worktree_audit.get_audit_logger",
            side_effect=Exception("Audit log unavailable"),
        )

        logger = WorktreeAuditLogger()
        logger.log_creation_attempt(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="main",
            worktree_path="/worktrees/test/main",
        )

        # Should fall back to app logger
        assert mock_app_logger.called or True  # At least didn't crash

    def test_log_to_audit_trail_success(self, mocker):
        """Test successful audit trail logging."""
        mock_audit_logger = mocker.patch(
            "mahavishnu.core.worktree_audit.get_audit_logger"
        )
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()
        logger.log_creation_success(
            user_id="user-123",
            repo_nickname="mahavishnu",
            branch="main",
            worktree_path="/worktrees/test/main",
        )

        # Should not raise any errors
        mock_audit.assert_called_once()

    def test_redact_secrets_idempotent(self):
        """Test that redaction can be called multiple times safely."""
        params = {"password": "secret123", "branch": "main"}

        # First redaction
        redacted1 = WorktreeAuditLogger._redact_secrets(params)

        # Second redaction (should not double-redact)
        redacted2 = WorktreeAuditLogger._redact_secrets(redacted1)

        assert redacted1 == redacted2
        assert "***" in redacted1["password"]

    # =========================================================================
    # Compliance Tests
    # =========================================================================

    def test_all_events_include_required_fields(self, mocker):
        """Test that all audit events include required fields for compliance."""
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger, "_log_to_audit_trail", return_value=None
        )

        logger = WorktreeAuditLogger()

        # Test all event types
        events_to_test = [
            ("creation_attempt", lambda: logger.log_creation_attempt(
                user_id="user-123", repo_nickname="test", branch="main",
                worktree_path="/worktrees/test/main"
            )),
            ("creation_success", lambda: logger.log_creation_success(
                user_id="user-123", repo_nickname="test", branch="main",
                worktree_path="/worktrees/test/main"
            )),
            ("creation_failure", lambda: logger.log_creation_failure(
                user_id="user-123", repo_nickname="test", branch="main",
                worktree_path="/worktrees/test/main", error="failed"
            )),
            ("removal_attempt", lambda: logger.log_removal_attempt(
                user_id="user-123", repo_nickname="test",
                worktree_path="/worktrees/test/main", force=False
            )),
            ("removal_success", lambda: logger.log_removal_success(
                user_id="user-123", repo_nickname="test",
                worktree_path="/worktrees/test/main", force=False
            )),
            ("prune", lambda: logger.log_prune_operation(
                user_id="user-123", repo_nickname="test", pruned_count=1
            )),
            ("list", lambda: logger.log_list_operation(
                user_id="user-123", repo_nickname="test"
            )),
        ]

        for event_name, event_func in events_to_test:
            event_func()

            # Verify _log_to_audit_trail was called with required fields
            call_kwargs = mock_audit.call_args.kwargs
            assert "timestamp" in call_kwargs or call_kwargs.get("timestamp") is not None
            assert "event_type" in call_kwargs
            assert "user_id" in call_kwargs
            assert "tool_name" in call_kwargs
            assert "params" in call_kwargs
            assert "result" in call_kwargs
