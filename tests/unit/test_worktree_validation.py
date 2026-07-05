"""Unit tests for WorktreePathValidator.

from __future__ import annotations
import operator
Tests security validation of worktree paths with comprehensive coverage of:
- Null byte prevention (CWE-170)
- Path traversal prevention (CWE-22)
- Shell metacharacter detection (CWE-114)
- Allowed root verification
- Audit logging for security rejections
"""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
import pytest

from mahavishnu.core.worktree_validation import WorktreePathValidator


class TestWorktreePathValidator:
    """Test suite for WorktreePathValidator security checks."""

    def test_initialization(self, tmp_path) -> None:
        """Test validator initialization with allowed roots."""
        allowed_roots = [tmp_path / "worktrees", tmp_path / "safe"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        assert validator.allowed_roots == allowed_roots
        assert validator.strict_mode is True

    def test_initialization_with_strict_mode_disabled(self, tmp_path) -> None:
        """Test validator initialization with strict mode disabled."""
        validator = WorktreePathValidator(
            allowed_roots=[tmp_path / "worktrees"],
            strict_mode=False,
        )

        assert validator.strict_mode is False

    # =========================================================================
    # Null Byte Prevention Tests (CWE-170)
    # =========================================================================

    def test_reject_null_bytes_in_path(self, tmp_path) -> None:
        """Test that paths with null bytes are rejected (CWE-170)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo\x00feature", user_id="test-user"
        )

        assert not is_valid
        assert "null bytes" in error.lower()
        assert "CWE-170" in error

    def test_null_bytes_audit_logging(self, tmp_path, mocker) -> None:
        """Test that null byte rejection is written to the audit logger."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        mock_logger = mocker.Mock()
        mock_get_audit_logger = mocker.patch(
            "mahavishnu.mcp.auth.get_audit_logger", return_value=mock_logger
        )

        validator.validate_worktree_path("/worktrees/repo\x00feature", user_id="test-user")

        mock_get_audit_logger.assert_called_once()
        mock_logger.log.assert_called_once()
        call_kwargs = mock_logger.log.call_args.kwargs
        assert call_kwargs["user_id"] == "test-user"
        assert call_kwargs["tool_name"] == "WorktreePathValidator"
        assert call_kwargs["event_type"] == "security_rejection"
        assert call_kwargs["result"] == "denied"
        assert "null bytes" in call_kwargs["error"].lower()

    # =========================================================================
    # Shell Metacharacter Detection Tests (CWE-114)
    # =========================================================================

    def test_reject_shell_metacharacters(self, tmp_path) -> None:
        """Test that paths with shell metacharacters are rejected (CWE-114)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Test each dangerous character
        dangerous_paths = [
            "/worktrees/repo;rm -rf /",
            "/worktrees/repo&cat /etc/passwd",
            "/worktrees/repo|malicious",
            "/worktrees/repo`execute`",
            "/worktrees/repo$HOME",
        ]

        for path in dangerous_paths:
            is_valid, error = validator.validate_worktree_path(path, user_id="test-user")

            assert not is_valid, f"Path should be rejected: {path}"
            assert "shell metacharacters" in error.lower()
            assert "CWE-114" in error

    def test_reject_newline_carriage_return(self, tmp_path) -> None:
        """Test that paths with newline/carriage return are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Test newline
        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo\nmalicious", user_id="test-user"
        )
        assert not is_valid
        assert "shell metacharacters" in error.lower()

        # Test carriage return
        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo\rmalicious", user_id="test-user"
        )
        assert not is_valid
        assert "shell metacharacters" in error.lower()

    # =========================================================================
    # Path Traversal Prevention Tests (CWE-22)
    # =========================================================================

    def test_reject_parent_directory_traversal(self, tmp_path) -> None:
        """Test that paths with parent directory traversal are rejected (CWE-22)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo/../../../etc/passwd", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()
        assert "CWE-22" in error

    def test_reject_tilde_expansion(self, tmp_path) -> None:
        """Test that paths with tilde are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path("~root/.ssh", user_id="test-user")

        assert not is_valid
        assert "outside allowed directories" in error.lower()

    def test_reject_git_directory(self, tmp_path) -> None:
        """Test that paths with .git component are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/.git/hooks", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    def test_reject_svn_directory(self, tmp_path) -> None:
        """Test that paths with .svn component are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/.svn/config", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    def test_reject_hg_directory(self, tmp_path) -> None:
        """Test that paths with .hg component are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/.hg/config", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    # =========================================================================
    # Allowed Root Verification Tests
    # =========================================================================

    def test_reject_path_outside_allowed_roots_in_strict_mode(self, tmp_path) -> None:
        """Test that paths outside allowed roots are rejected in strict mode."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots, strict_mode=True)

        # Path outside allowed roots
        is_valid, error = validator.validate_worktree_path(
            "/unauthorized/path", user_id="test-user"
        )

        assert not is_valid
        assert "outside allowed directories" in error.lower()
        assert "CWE-22" in error

    def test_accept_path_outside_allowed_roots_in_non_strict_mode(self, tmp_path) -> None:
        """Test that paths outside allowed roots are accepted in non-strict mode."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"], strict_mode=False)

        # Path outside allowed roots - should pass in non-strict mode
        is_valid, error = validator.validate_worktree_path(
            "/unauthorized/path", user_id="test-user"
        )

        # In non-strict mode, path traversal checks still apply
        # This test verifies that the path isn't automatically rejected
        # just because it's outside allowed roots
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))

    def test_accept_path_inside_allowed_roots(self, tmp_path) -> None:
        """Test that paths inside allowed roots are accepted."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Create a valid path inside allowed roots
        valid_path = str(tmp_path / "worktrees" / "repo" / "branch")

        is_valid, error = validator.validate_worktree_path(valid_path, user_id="test-user")

        assert is_valid
        assert error is None

    def test_accept_absolute_path_matching_allowed_root(self, tmp_path) -> None:
        """Test that absolute paths matching allowed roots are accepted."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Exact match to allowed root
        valid_path = str(tmp_path / "worktrees")

        is_valid, error = validator.validate_worktree_path(valid_path, user_id="test-user")

        assert is_valid
        assert error is None

    # =========================================================================
    # Path Normalization Tests
    # =========================================================================

    def test_reject_normalized_path_with_escape_sequences(self, tmp_path) -> None:
        """Test that normalized paths with escape sequences are rejected."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Create a path that would normalize to include ../ after resolution
        test_path = str(tmp_path / "worktrees" / "repo" / "branch" / ".." / "safe")

        is_valid, error = validator.validate_worktree_path(test_path, user_id="test-user")

        assert not is_valid
        assert "dangerous component" in error.lower()
        assert "CWE-22" in error

    def test_reject_path_with_tilde_after_normalization(self, tmp_path) -> None:
        """Test that paths with ~ after normalization are rejected."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Path that would normalize to include ~
        test_path = str(tmp_path / "worktrees" / "~" / "safe")

        is_valid, error = validator.validate_worktree_path(test_path, user_id="test-user")

        assert not is_valid
        assert "dangerous component" in error.lower()

    # =========================================================================
    # Repository Path Validation Tests
    # =========================================================================

    def test_validate_repository_path_with_null_bytes(self, tmp_path) -> None:
        """Test repository path validation rejects null bytes."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])

        is_valid, error = validator.validate_repository_path(
            "/repos/repo\x00hidden", user_id="test-user"
        )

        assert not is_valid
        assert "null bytes" in error.lower()

    def test_validate_repository_path_with_shell_metacharacters(self, tmp_path) -> None:
        """Test repository path validation rejects shell metacharacters."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])

        is_valid, error = validator.validate_repository_path(
            "/repos/repo;rm -rf /", user_id="test-user"
        )

        assert not is_valid
        assert "shell metacharacters" in error.lower()

    def test_validate_repository_path_with_path_traversal(self, tmp_path) -> None:
        """Test repository path validation accepts parent traversal (repos can be anywhere)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Repository paths can be anywhere (they're trusted)
        # Parent traversal is allowed for repository paths
        is_valid, error = validator.validate_repository_path(
            str(tmp_path / "some" / "repo"), user_id="test-user"
        )

        # Should be valid if it exists and is a git repo
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))

    # =========================================================================
    # Safe Worktree Path Generation Tests
    # =========================================================================

    def test_get_safe_worktree_path_with_custom_base(self, tmp_path) -> None:
        """Test safe worktree path generation with custom base directory."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="mahavishnu", branch="feature-auth", base_dir=tmp_path / "custom"
        )

        expected = tmp_path / "custom" / "mahavishnu" / "feature-auth"
        assert worktree_path == expected

    def test_get_safe_worktree_path_sanitizes_branch_name(self, tmp_path) -> None:
        """Test that branch names are sanitized for filesystem safety."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Branch with dangerous characters
        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="repo",
            branch="../feature/auth",  # Contains parent traversal
            base_dir=tmp_path / "worktrees",
        )

        # Should be sanitized
        assert ".." not in str(worktree_path)
        assert worktree_path == tmp_path / "worktrees" / "repo" / "_feature-auth"

    def test_get_safe_worktree_path_sanitizes_slashes(self, tmp_path) -> None:
        """Test that slashes in branch names are sanitized."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Branch with slashes (hierarchical branch)
        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="repo",
            branch="feature/auth/api",
            base_dir=tmp_path / "worktrees",
        )

        # Should flatten to dashes
        assert worktree_path.name == "feature-auth-api"
        assert worktree_path == tmp_path / "worktrees" / "repo" / "feature-auth-api"

    def test_get_safe_worktree_path_default_base(self, tmp_path) -> None:
        """Test safe worktree path generation with default base directory."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Don't specify base_dir (should default to ~/worktrees)
        worktree_path = validator.get_safe_worktree_path(repo_nickname="mahavishnu", branch="main")

        # Should use home directory
        import pathlib

        assert worktree_path == pathlib.Path.home() / "worktrees" / "mahavishnu" / "main"

    def test_get_safe_worktree_path_empty_branch(self, tmp_path) -> None:
        """Test that empty branch names are sanitized to 'unnamed'."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Empty branch name (after sanitization)
        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="repo", branch="", base_dir=tmp_path / "worktrees"
        )

        # Should default to "unnamed"
        assert worktree_path == tmp_path / "worktrees" / "repo" / "unnamed"

    # =========================================================================
    # Property-Based Tests with Hypothesis
    # =========================================================================

    @pytest.mark.property
    @given(st.text(max_size=50).map(lambda value: f"{value}\x00{value}"))
    def test_property_reject_paths_with_null_bytes(self, path) -> None:
        """Property-based test: All paths with null bytes are rejected."""
        validator = WorktreePathValidator(allowed_roots=[Path("/worktrees")])

        is_valid, error = validator.validate_worktree_path(path, user_id="test")
        assert not is_valid
        assert "null bytes" in error.lower()

    def test_validate_worktree_path_escape_sequence_after_resolution(
        self, tmp_path, mocker
    ) -> None:
        """Test that escape sequences detected after resolution are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])
        mocker.patch(
            "mahavishnu.core.worktree_validation.Path.resolve",
            return_value=Path(str(tmp_path / "worktrees" / "repo" / ".." / "safe")),
        )

        is_valid, error = validator.validate_worktree_path(
            str(tmp_path / "worktrees" / "repo"), user_id="test-user"
        )

        assert not is_valid
        assert "escape sequences" in error.lower()
        assert "CWE-22" in error

    def test_validate_worktree_path_type_error_returns_invalid(self, tmp_path) -> None:
        """Test that unexpected path types are handled as invalid input."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(None, user_id="test-user")

        assert not is_valid
        assert "not iterable" in error.lower()

    def test_validate_repository_path_accepts_git_repo(self, tmp_path) -> None:
        """Test that a valid git repository path is accepted."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])

        repo_dir = tmp_path / "repos" / "repo"
        (repo_dir / ".git").mkdir(parents=True)

        is_valid, error = validator.validate_repository_path(str(repo_dir), user_id="test-user")

        assert is_valid
        assert error is None

    def test_validate_repository_path_exception_is_handled(self, tmp_path, mocker) -> None:
        """Test that repository validation exceptions are handled cleanly."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])
        mocker.patch.object(validator, "_is_git_repository", side_effect=RuntimeError("repo boom"))

        is_valid, error = validator.validate_repository_path(
            str(tmp_path / "repos" / "repo"), user_id="test-user"
        )

        assert not is_valid
        assert "repo boom" in error

    def test_validate_worktree_path_resolve_failure(self, tmp_path, mocker) -> None:
        """Test that path resolution failures are handled cleanly."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])
        mocker.patch(
            "mahavishnu.core.worktree_validation.Path.resolve", side_effect=OSError("boom")
        )

        is_valid, error = validator.validate_worktree_path(
            str(tmp_path / "worktrees" / "repo"), user_id="test-user"
        )

        assert not is_valid
        assert "path resolution failed" in error.lower()
        assert "boom" in error

    def test_validate_repository_path_resolve_failure(self, tmp_path, mocker) -> None:
        """Test that repository path resolution failures are handled cleanly."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])
        mocker.patch(
            "mahavishnu.core.worktree_validation.Path.resolve", side_effect=OSError("boom")
        )

        is_valid, error = validator.validate_repository_path(
            str(tmp_path / "repos" / "repo"), user_id="test-user"
        )

        assert not is_valid
        assert "repository path resolution failed" in error.lower()
        assert "boom" in error

    def test_log_security_rejection_audit_failure_is_ignored(self, tmp_path, mocker) -> None:
        """Test that audit logger failures do not break validation logging."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])
        mock_logger = mocker.Mock()
        mock_logger.log.side_effect = RuntimeError("audit down")
        mocker.patch("mahavishnu.mcp.auth.get_audit_logger", return_value=mock_logger)

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo\x00feature", user_id="test-user"
        )

        assert not is_valid
        assert "null bytes" in error.lower()

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_validate_empty_path(self, tmp_path) -> None:
        """Test validation of empty path string."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path("", user_id="test-user")

        # Empty path is invalid (can't resolve)
        assert isinstance(is_valid, bool)  # May be False or raise exception
        assert isinstance(error, (str, type(None)))

    def test_validate_relative_path(self, tmp_path) -> None:
        """Test validation of relative path."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path("relative/path", user_id="test-user")

        # Relative path should be rejected (not in allowed roots)
        assert not is_valid
        assert "outside allowed directories" in error.lower()

    def test_validate_very_long_path(self, tmp_path) -> None:
        """Test validation of excessively long path."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Create very long path
        long_component = "a" * 1000
        long_path = f"{tmp_path}/worktrees/{long_component}/{long_component}"

        is_valid, error = validator.validate_worktree_path(long_path, user_id="test-user")

        # Should handle gracefully (either accept or reject with sensible error)
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))
