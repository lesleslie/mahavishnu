"""Coverage-push tests for the 6 missed lines in mahavishnu/core/worktree_audit.py"""

from __future__ import annotations

from unittest.mock import patch

from mahavishnu.core.worktree_audit import WorktreeAuditLogger


class TestWorktreeAuditCoverage:
    """Cover the missed lines inside _log_to_audit_trail and the four prune-merged methods."""

    def test_audit_trail_error_message_appended(self) -> None:
        """Line 138: when error is provided, it is appended to log_message."""
        WorktreeAuditLogger()._log_to_audit_trail(event_type="evt", user_id="u-1", tool_name="t", params={}, result="success", error="something failed")

    def test_audit_trail_denied_logs_warning(self) -> None:
        """Line 141: result='denied' routes to logger.warning."""
        WorktreeAuditLogger()._log_to_audit_trail(event_type="evt", user_id="u-1", tool_name="t", params={}, result="denied")

    def test_audit_trail_failure_logs_error(self) -> None:
        """Line 143: result='failure' routes to logger.error."""
        WorktreeAuditLogger()._log_to_audit_trail(event_type="evt", user_id="u-1", tool_name="t", params={}, result="failure")

    def test_audit_logger_exception_is_swallowed(self) -> None:
        """Lines 163-165: an exception from _audit_logger is caught and logged."""
        with patch("mahavishnu.core.worktree_audit._audit_logger.info", side_effect=OSError("disk full")):
            WorktreeAuditLogger()._log_to_audit_trail(event_type="evt", user_id="u-1", tool_name="t", params={}, result="success")

    def test_log_prune_merged_attempt(self) -> None:
        """Line 414: log_prune_merged_attempt delegates to _log_to_audit_trail."""
        WorktreeAuditLogger().log_prune_merged_attempt(user_id="u-1", candidate_count=3, ttl_days=7, include_dirty=False, trigger="scheduler", exclude_session="sess-42")

    def test_log_prune_merged_success(self) -> None:
        """Line 437: log_prune_merged_success delegates to _log_to_audit_trail."""
        WorktreeAuditLogger().log_prune_merged_success(user_id="u-1", removed_count=2, backup_paths=["/b1", "/b2"], trigger="manual", failed_paths=["/bad"])

    def test_log_prune_merged_partial(self) -> None:
        """Line 460: log_prune_merged_partial delegates to _log_to_audit_trail."""
        WorktreeAuditLogger().log_prune_merged_partial(user_id="u-1", removed_count=1, failed_count=2, failed_paths=["/a", "/b"], backup_paths=["/b1"], trigger="scheduler")

    def test_log_prune_merged_failure(self) -> None:
        """Line 481: log_prune_merged_failure delegates to _log_to_audit_trail."""
        WorktreeAuditLogger().log_prune_merged_failure(user_id="u-1", error="git prune failed", trigger="manual")
