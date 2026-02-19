"""Tests for path traversal prevention across all inputs.

This module tests path traversal attack prevention to ensure:
1. Repository names cannot traverse directories
2. File paths are properly validated
3. Symlink attacks are prevented
4. Null byte path injection is blocked
5. URL encoding attacks are prevented
"""

import pytest

from mahavishnu.core.task_models import (
    TaskCreateRequest,
    TaskFilter,
)


class TestRepositoryPathTraversal:
    """Tests for path traversal prevention in repository names."""

    # Basic path traversal patterns
    def test_parent_directory_traversal_rejected(self):
        """Test that ../ is rejected in repository names."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="../etc")

    def test_multiple_parent_traversal_rejected(self):
        """Test that multiple ../ is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="../../../etc/passwd")

    def test_current_directory_prefix_rejected(self):
        """Test that ./ prefix is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="./repo")

    def test_directory_separator_rejected(self):
        """Test that / in repository names is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="path/to/repo")

    def test_backslash_separator_rejected(self):
        """Test that backslash in repository names is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="path\\to\\repo")

    def test_mixed_slashes_rejected(self):
        """Test that mixed slashes are rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="path/to\\repo")

    def test_traversal_in_middle_rejected(self):
        """Test that ../ in the middle is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo/../other")

    def test_traversal_at_end_rejected(self):
        """Test that ../ at the end is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo/../")

    # Null byte injection
    def test_null_byte_injection_rejected(self):
        """Test that null bytes in repository names are rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo\x00.txt")

    def test_null_byte_before_extension_rejected(self):
        """Test null byte before extension is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo\x00.py")

    # URL encoding attacks
    def test_url_encoded_slash_rejected(self):
        """Test that URL-encoded slash (%2F) is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo%2Fpath")

    def test_url_encoded_parent_rejected(self):
        """Test that URL-encoded ../ (%2E%2E%2F) is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="%2E%2E%2Fetc")

    def test_double_url_encoding_rejected(self):
        """Test that double URL encoding is rejected."""
        # %252F = %2F when double-decoded = /
        # Our pattern check rejects % anyway
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo%252Fpath")

    # Unicode attacks
    def test_unicode_slash_rejected(self):
        """Test that unicode slash variants are rejected."""
        # Unicode has various slash-like characters
        # Our pattern only allows ASCII alphanumeric, -, _
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="repo\u2215path")  # Division slash

    def test_unicode_parent_directory_rejected(self):
        """Test that unicode .. variants are rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="\uFF0E\uFF0E\u2215")  # Fullwidth . and slash

    # Valid names that should pass
    def test_valid_simple_name_accepted(self):
        """Test that simple valid names are accepted."""
        request = TaskCreateRequest(title="Test", repository="myrepo")
        assert request.repository == "myrepo"

    def test_valid_name_with_dash_accepted(self):
        """Test that names with dash are accepted."""
        request = TaskCreateRequest(title="Test", repository="my-repo")
        assert request.repository == "my-repo"

    def test_valid_name_with_underscore_accepted(self):
        """Test that names with underscore are accepted."""
        request = TaskCreateRequest(title="Test", repository="my_repo")
        assert request.repository == "my_repo"

    def test_valid_mixed_case_accepted(self):
        """Test that mixed case names are accepted."""
        request = TaskCreateRequest(title="Test", repository="MyRepo123")
        assert request.repository == "MyRepo123"

    # Edge cases
    def test_empty_repository_rejected(self):
        """Test that empty repository name is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="")

    def test_whitespace_only_rejected(self):
        """Test that whitespace-only name is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="   ")

    def test_leading_dash_accepted(self):
        """Test that leading dash is handled (may be rejected by model)."""
        # Our model rejects leading dash/underscore
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="-repo")

    def test_leading_underscore_rejected(self):
        """Test that leading underscore is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="_repo")

    def test_dot_prefix_rejected(self):
        """Test that dot prefix is rejected."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository=".repo")

    def test_long_name_accepted(self):
        """Test that reasonably long names are accepted."""
        long_name = "a" * 50
        request = TaskCreateRequest(title="Test", repository=long_name)
        assert request.repository == long_name

    def test_too_long_name_rejected(self):
        """Test that excessively long names are rejected."""
        too_long = "a" * 101
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository=too_long)


class TestTaskFilterPathTraversal:
    """Tests for path traversal prevention in task filters."""

    def test_filter_repository_traversal_rejected(self):
        """Test that path traversal in filter repository is rejected."""
        with pytest.raises(Exception):
            TaskFilter(repository="../../../etc")

    def test_filter_repository_slash_rejected(self):
        """Test that slash in filter repository is rejected."""
        with pytest.raises(Exception):
            TaskFilter(repository="path/to/repo")

    def test_filter_repository_valid_accepted(self):
        """Test that valid filter repository is accepted."""
        filter_obj = TaskFilter(repository="my-repo")
        assert filter_obj.repository == "my-repo"


class TestFilePathValidation:
    """Tests for file path validation patterns.

    Note: These tests validate the patterns we use for file path inputs.
    Actual file path validation would be done at the point of use.
    """

    def test_absolute_path_pattern_detection(self):
        """Test detection of absolute paths (should not be in repo names)."""
        # Absolute paths start with / or \
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="/etc/passwd")

    def test_windows_absolute_path_detection(self):
        """Test detection of Windows absolute paths."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="C:\\Windows\\System32")

    def test_unc_path_detection(self):
        """Test detection of UNC paths."""
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="\\\\server\\share")


class TestSymlinkAttackPrevention:
    """Tests for symlink attack prevention patterns.

    Note: Symlink validation would be done at the point of file access.
    These tests verify that the input validation prevents obvious attacks.
    """

    def test_symlink_escape_pattern_rejected(self):
        """Test that symlink escape patterns are rejected."""
        # Common symlink escape: link pointing to ../../
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="symlink/../../etc")

    def test_toctou_pattern_rejected(self):
        """Test that TOCTOU-vulnerable patterns are rejected."""
        # Time-of-check-time-of-use patterns often involve ..
        with pytest.raises(Exception):
            TaskCreateRequest(title="Test", repository="file/../file")
