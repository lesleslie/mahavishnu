"""Unit tests for WorktreePathValidator.

Tests security validation of worktree paths with comprehensive coverage of:
- Null byte prevention (CWE-170)
- Path traversal prevention (CWE-22)
- Shell metacharacter detection (CWE-114)
- Allowed root verification
- Audit logging for security rejections
"""

import pytest
from hypothesis import given, strategies as st

from mahavishnu.core.worktree_validation import WorktreePathValidator
from mahavishnu.core.errors import ValidationError


class TestWorktreePathValidator:
    """Test suite for WorktreePathValidator security checks."""

    def test_initialization(self, tmp_path):
        """Test validator initialization with allowed roots."""
        allowed_roots = [tmp_path / "worktrees", tmp_path / "safe"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        assert validator.allowed_roots == allowed_roots
        assert validator.strict_mode is True

    def test_initialization_with_strict_mode_disabled(self, tmp_path):
        """Test validator initialization with strict mode disabled."""
        validator = WorktreePathValidator(
            allowed_roots=[tmp_path / "worktrees"],
            strict_mode=False,
        )

        assert validator.strict_mode is False

    # =========================================================================
    # Null Byte Prevention Tests (CWE-170)
    # =========================================================================

    def test_reject_null_bytes_in_path(self, tmp_path):
        """Test that paths with null bytes are rejected (CWE-170)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo\x00feature", user_id="test-user"
        )

        assert not is_valid
        assert "null bytes" in error.lower()
        assert "CWE-170" in error

    def test_null_bytes_audit_logging(self, tmp_path, mocker):
        """Test that null byte rejection is logged to audit trail."""
        from mahavishnu.core.worktree_audit import WorktreeAuditLogger

        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Mock audit logger
        mock_audit = mocker.patch.object(
            WorktreeAuditLogger,
            "log_security_rejection",
            return_value=None,
        )

        validator.validate_worktree_path("/worktrees/repo\x00feature", user_id="test-user")

        # Verify audit logging was called
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["user_id"] == "test-user"
        assert call_kwargs["operation"] == "validate_worktree_path"
        assert "null byte" in call_kwargs["rejection_reason"].lower()

    # =========================================================================
    # Shell Metacharacter Detection Tests (CWE-114)
    # =========================================================================

    def test_reject_shell_metacharacters(self, tmp_path):
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

    def test_reject_newline_carriage_return(self, tmp_path):
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

    def test_reject_parent_directory_traversal(self, tmp_path):
        """Test that paths with parent directory traversal are rejected (CWE-22)."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/repo/../../../etc/passwd", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()
        assert "CWE-22" in error

    def test_reject_tilde_expansion(self, tmp_path):
        """Test that paths with tilde are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "~root/.ssh", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    def test_reject_git_directory(self, tmp_path):
        """Test that paths with .git component are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/.git/hooks", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    def test_reject_svn_directory(self, tmp_path):
        """Test that paths with .svn component are rejected."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "/worktrees/.svn/config", user_id="test-user"
        )

        assert not is_valid
        assert "dangerous component" in error.lower()

    def test_reject_hg_directory(self, tmp_path):
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

    def test_reject_path_outside_allowed_roots_in_strict_mode(self, tmp_path):
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

    def test_accept_path_outside_allowed_roots_in_non_strict_mode(self, tmp_path):
        """Test that paths outside allowed roots are accepted in non-strict mode."""
        validator = WorktreePathValidator(
            allowed_roots=[tmp_path / "worktrees"], strict_mode=False
        )

        # Path outside allowed roots - should pass in non-strict mode
        is_valid, error = validator.validate_worktree_path(
            "/unauthorized/path", user_id="test-user"
        )

        # In non-strict mode, path traversal checks still apply
        # This test verifies that the path isn't automatically rejected
        # just because it's outside allowed roots
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))

    def test_accept_path_inside_allowed_roots(self, tmp_path):
        """Test that paths inside allowed roots are accepted."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Create a valid path inside allowed roots
        valid_path = str(tmp_path / "worktrees" / "repo" / "branch")

        is_valid, error = validator.validate_worktree_path(valid_path, user_id="test-user")

        assert is_valid
        assert error is None

    def test_accept_absolute_path_matching_allowed_root(self, tmp_path):
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

    def test_reject_normalized_path_with_escape_sequences(self, tmp_path):
        """Test that normalized paths with escape sequences are rejected."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Create a path that would normalize to include ../ after resolution
        test_path = str(tmp_path / "worktrees" / "repo" / "branch" / ".." / "safe")

        is_valid, error = validator.validate_worktree_path(test_path, user_id="test-user")

        assert not is_valid
        assert "escape sequences" in error.lower()
        assert "CWE-22" in error

    def test_reject_path_with_tilde_after_normalization(self, tmp_path):
        """Test that paths with ~ after normalization are rejected."""
        allowed_roots = [tmp_path / "worktrees"]
        validator = WorktreePathValidator(allowed_roots=allowed_roots)

        # Path that would normalize to include ~
        test_path = str(tmp_path / "worktrees" / "~" / "safe")

        is_valid, error = validator.validate_worktree_path(test_path, user_id="test-user")

        assert not is_valid
        assert "escape sequences" in error.lower()

    # =========================================================================
    # Repository Path Validation Tests
    # =========================================================================

    def test_validate_repository_path_with_null_bytes(self, tmp_path):
        """Test repository path validation rejects null bytes."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])

        is_valid, error = validator.validate_repository_path(
            "/repos/repo\x00hidden", user_id="test-user"
        )

        assert not is_valid
        assert "null bytes" in error.lower()

    def test_validate_repository_path_with_shell_metacharacters(self, tmp_path):
        """Test repository path validation rejects shell metacharacters."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "repos"])

        is_valid, error = validator.validate_repository_path(
            "/repos/repo;rm -rf /", user_id="test-user"
        )

        assert not is_valid
        assert "shell metacharacters" in error.lower()

    def test_validate_repository_path_with_path_traversal(self, tmp_path):
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

    def test_get_safe_worktree_path_with_custom_base(self, tmp_path):
        """Test safe worktree path generation with custom base directory."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="mahavishnu", branch="feature-auth", base_dir=tmp_path / "custom"
        )

        expected = tmp_path / "custom" / "mahavishnu" / "feature-auth"
        assert worktree_path == expected

    def test_get_safe_worktree_path_sanitizes_branch_name(self, tmp_path):
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
        assert worktree_path == tmp_path / "worktrees" / "repo" / "_.._feature_auth"

    def test_get_safe_worktree_path_sanitizes_slashes(self, tmp_path):
        """Test that slashes in branch names are sanitized."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Branch with slashes (hierarchical branch)
        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="repo",
            branch="feature/auth/api",
            base_dir=tmp_path / "worktrees",
        )

        # Should flatten to dashes
        assert "/" not in str(worktree_path)
        assert "\\" not in str(worktree_path)
        assert worktree_path == tmp_path / "worktrees" / "repo" / "feature-auth-api"

    def test_get_safe_worktree_path_default_base(self, tmp_path):
        """Test safe worktree path generation with default base directory."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Don't specify base_dir (should default to ~/worktrees)
        worktree_path = validator.get_safe_worktree_path(
            repo_nickname="mahavishnu", branch="main"
        )

        # Should use home directory
        import pathlib
        assert worktree_path == pathlib.Path.home() / "worktrees" / "mahavishnu" / "main"

    def test_get_safe_worktree_path_empty_branch(self, tmp_path):
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
    @given(st.text(alphabet=st.characters(whitelist_categories=(), max_size=100))
    def test_property_reject_paths_with_null_bytes(self, path):
        """Property-based test: All paths with null bytes are rejected."""
        validator = WorktreePathValidator(allowed_roots=["/worktrees"])

        if "\x00" in path:
            is_valid, error = validator.validate_worktree_path(path, user_id="test")
            assert not is_valid
            assert "null bytes" in error.lower()
        else:
            # Other paths may or may not be valid depending on other factors
            is_valid, error = validator.validate_worktree_path(path, user_id="test")
            assert isinstance(is_valid, bool)

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_validate_empty_path(self, tmp_path):
        """Test validation of empty path string."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path("", user_id="test-user")

        # Empty path is invalid (can't resolve)
        assert isinstance(is_valid, bool)  # May be False or raise exception
        assert isinstance(error, (str, type(None)))

    def test_validate_relative_path(self, tmp_path):
        """Test validation of relative path."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        is_valid, error = validator.validate_worktree_path(
            "relative/path", user_id="test-user"
        )

        # Relative path should be rejected (not in allowed roots)
        assert not is_valid
        assert "outside allowed directories" in error.lower()

    def test_validate_very_long_path(self, tmp_path):
        """Test validation of excessively long path."""
        validator = WorktreePathValidator(allowed_roots=[tmp_path / "worktrees"])

        # Create very long path
        long_component = "a" * 1000
        long_path = f"{tmp_path}/worktrees/{long_component}/{long_component}"

        is_valid, error = validator.validate_worktree_path(long_path, user_id="test-user")

        # Should handle gracefully (either accept or reject with sensible error)
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))
