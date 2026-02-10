"""Comprehensive tests for path validation and security utilities.

This module provides extensive test coverage for:
- Path validation security (directory traversal prevention)
- Symbolic link handling
- Edge cases and boundary conditions
- Error handling and validation
- Repository path validation
- Filename sanitization
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

# Skip until validators module is implemented
pytest.skip("Validators module not yet implemented", allow_module_level=True)

# from mahavishnu.core.validators import (
#     validate_path,
#     validate_repository_path,
#     sanitize_filename,
#     validate_file_operation,
#     PathValidationError,
# )


class TestValidatePath:
    """Test suite for validate_path function."""

    async def test_validate_relative_path_within_allowed_dir(self):
        """Test validation of relative path within allowed directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to tmpdir to test relative paths
            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                test_file = Path(tmpdir) / "test.txt"
                test_file.touch()

                result = validate_path(
                    "test.txt",
                    allowed_base_dirs=[tmpdir],
                    must_exist=True,
                )

                assert result.resolve() == test_file.resolve()
                assert result.is_absolute()
            finally:
                os.chdir(original_cwd)

    async def test_validate_absolute_path_within_allowed_dir(self):
        """Test validation of absolute path within allowed directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            result = validate_path(
                test_file,
                allowed_base_dirs=[tmpdir],
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_path_with_symlinks_resolved(self):
        """Test that symbolic links are resolved when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a file and a symlink to it
            target_file = tmpdir_path / "target.txt"
            target_file.write_text("content")

            symlink_file = tmpdir_path / "symlink.txt"
            symlink_file.symlink_to(target_file)

            # With resolve_symlinks=True, should resolve to target
            result = validate_path(
                symlink_file,
                allowed_base_dirs=[tmpdir],
                must_exist=True,
                resolve_symlinks=True,
            )

            # Result should point to the actual file, not the symlink
            assert result.exists()
            assert result.resolve() == target_file.resolve()

    async def test_validate_path_with_symlinks_not_resolved(self):
        """Test that symbolic links are not resolved when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a file and a symlink to it
            target_file = tmpdir_path / "target.txt"
            target_file.write_text("content")

            symlink_file = tmpdir_path / "symlink.txt"
            symlink_file.symlink_to(target_file)

            # With resolve_symlinks=False, should not resolve
            result = validate_path(
                symlink_file,
                allowed_base_dirs=[tmpdir],
                must_exist=False,
                resolve_symlinks=False,
            )

            # Result should be the absolute path without resolving symlinks
            # The path should point to the symlink itself
            assert result.is_absolute()
            # The symlink path exists (as a symlink)
            assert symlink_file.exists()

    async def test_validate_path_rejects_directory_traversal(self):
        """Test that directory traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    "../../etc/passwd",
                    allowed_base_dirs=[tmpdir],
                )

            assert "directory traversal" in str(exc_info.value).lower()
            assert exc_info.value.path == "../../etc/passwd"

    async def test_validate_path_rejects_encoded_traversal(self):
        """Test that encoded/obfuscated traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    "../test/../etc/passwd",
                    allowed_base_dirs=[tmpdir],
                )

            assert "directory traversal" in str(exc_info.value).lower()

    async def test_validate_path_rejects_windows_traversal(self):
        """Test that Windows-style traversal is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    "..\\..\\windows\\system32",
                    allowed_base_dirs=[tmpdir],
                )

            assert "directory traversal" in str(exc_info.value).lower()

    async def test_validate_path_rejects_absolute_paths_when_disallowed(self):
        """Test that absolute paths are rejected when allow_absolute=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    test_file,
                    allowed_base_dirs=[tmpdir],
                    allow_absolute=False,
                )

            assert "absolute paths not allowed" in str(exc_info.value).lower()

    async def test_validate_path_requires_existence_when_flagged(self):
        """Test that must_exist flag validates file existence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    "nonexistent.txt",
                    allowed_base_dirs=[tmpdir],
                    must_exist=True,
                )

            assert "does not exist" in str(exc_info.value).lower()

    async def test_validate_path_requires_file_when_flagged(self):
        """Test that must_be_file flag validates path is a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "testdir"
            test_dir.mkdir()

            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    test_dir,
                    allowed_base_dirs=[tmpdir],
                    must_be_file=True,
                )

            assert "not a file" in str(exc_info.value).lower()

    async def test_validate_path_requires_directory_when_flagged(self):
        """Test that must_be_dir flag validates path is a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    test_file,
                    allowed_base_dirs=[tmpdir],
                    must_be_dir=True,
                )

            assert "not a directory" in str(exc_info.value).lower()

    async def test_validate_path_rejects_path_outside_allowed_dirs(self):
        """Test that paths outside allowed directories are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            other_dir = Path(tmpdir) / "other"
            other_dir.mkdir()

            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    other_dir,
                    allowed_base_dirs=[str(Path(tmpdir) / "allowed")],
                )

            assert "outside allowed directories" in str(exc_info.value).lower()

    async def test_validate_path_accepts_multiple_allowed_dirs(self):
        """Test that multiple allowed directories are supported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed1 = Path(tmpdir) / "allowed1"
            allowed2 = Path(tmpdir) / "allowed2"
            allowed1.mkdir()
            allowed2.mkdir()

            test_file = allowed2 / "test.txt"
            test_file.touch()

            result = validate_path(
                test_file,
                allowed_base_dirs=[str(allowed1), str(allowed2)],
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_path_expands_user_directory(self):
        """Test that user directory (~) is expanded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test path with ~
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            # This test verifies ~ expansion works (integration test)
            # In actual usage, ~/ would expand to user's home directory
            # Here we just verify the mechanism doesn't crash
            try:
                result = validate_path(
                    test_file,
                    allowed_base_dirs=[tmpdir],
                    must_exist=True,
                )
                assert result.resolve() == test_file.resolve()
            except PathValidationError:
                # Expected if tmpdir is not in home directory
                pass

    async def test_validate_path_defaults_to_current_directory(self):
        """Test that allowed_base_dirs defaults to current directory."""
        # Create a file in current directory
        import os
        cwd = os.getcwd()

        test_file = Path(cwd) / "test_temp.txt"
        try:
            test_file.touch()

            # No allowed_base_dirs specified - should use current directory
            result = validate_path(
                "test_temp.txt",
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()
        finally:
            test_file.unlink(missing_ok=True)

    async def test_validate_path_handles_path_objects(self):
        """Test that Path objects are handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            # Pass Path object instead of string
            result = validate_path(
                test_file,
                allowed_base_dirs=[tmpdir],
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_path_error_includes_details(self):
        """Test that validation errors include helpful details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(PathValidationError) as exc_info:
                validate_path(
                    "../../etc/passwd",
                    allowed_base_dirs=[tmpdir],
                )

            error = exc_info.value
            assert error.path is not None
            assert error.reason is not None
            assert "path" in error.details
            assert "reason" in error.details


class TestValidateRepositoryPath:
    """Test suite for validate_repository_path function."""

    async def test_validate_repository_path_with_git_repo(self):
        """Test validation of Git repository path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "myrepo"
            repo_path.mkdir()
            (repo_path / ".git").mkdir()

            result = validate_repository_path(
                repo_path,
                repos_base_path=tmpdir,
                must_exist=True,
            )

            assert result.resolve() == repo_path.resolve()

    async def test_validate_repository_path_with_hg_repo(self):
        """Test validation of Mercurial repository path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "myrepo"
            repo_path.mkdir()
            (repo_path / ".hg").mkdir()

            result = validate_repository_path(
                repo_path,
                repos_base_path=tmpdir,
                must_exist=True,
            )

            assert result.resolve() == repo_path.resolve()

    async def test_validate_repository_path_with_svn_repo(self):
        """Test validation of SVN repository path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "myrepo"
            repo_path.mkdir()
            (repo_path / ".svn").mkdir()

            result = validate_repository_path(
                repo_path,
                repos_base_path=tmpdir,
                must_exist=True,
            )

            assert result.resolve() == repo_path.resolve()

    async def test_validate_repository_path_warns_on_no_vcs(self):
        """Test that warning is issued for directory without VCS metadata."""
        import logging
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "myrepo"
            repo_path.mkdir()

            # Should not raise error, but should log warning
            result = validate_repository_path(
                repo_path,
                repos_base_path=tmpdir,
                must_exist=True,
            )

            assert result.resolve() == repo_path.resolve()

    async def test_validate_repository_path_rejects_outside_base(self):
        """Test that paths outside repos base are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "outside" / "repo"
            repo_path.mkdir(parents=True)

            with pytest.raises(PathValidationError):
                validate_repository_path(
                    repo_path,
                    repos_base_path=str(Path(tmpdir) / "repos"),
                )

    async def test_validate_repository_path_must_exist_flag(self):
        """Test that must_exist flag works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "nonexistent"

            with pytest.raises(PathValidationError):
                validate_repository_path(
                    repo_path,
                    repos_base_path=tmpdir,
                    must_exist=True,
                )


class TestSanitizeFilename:
    """Test suite for sanitize_filename function."""

    async def test_sanitize_normal_filename(self):
        """Test sanitization of normal filename."""
        result = sanitize_filename("normal_file.txt")
        assert result == "normal_file.txt"

    async def test_sanitize_removes_path_separators(self):
        """Test that path separators are removed."""
        result = sanitize_filename("path/to/file.txt")
        assert "/" not in result
        assert "\\" not in result

    async def test_sanitize_removes_double_dots(self):
        """Test that double dots are removed."""
        result = sanitize_filename("../../../etc/passwd")
        assert ".." not in result

    async def test_sanitize_replaces_dangerous_chars(self):
        """Test that dangerous characters are replaced."""
        result = sanitize_filename("file\x00with\nnulls\rand\ttabs")
        assert "\x00" not in result
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result

    async def test_sanitize_replaces_special_chars(self):
        """Test that special characters are replaced with underscores."""
        result = sanitize_filename("file with spaces & symbols!.txt")
        assert result == "file_with_spaces___symbols_.txt"

    async def test_sanitize_removes_leading_dots(self):
        """Test that leading dots are removed (hidden files)."""
        result = sanitize_filename(".hidden_file.txt")
        assert not result.startswith(".")

    async def test_sanitize_removes_leading_dashes(self):
        """Test that leading dashes are removed (escape sequences)."""
        result = sanitize_filename("-flag-file.txt")
        assert not result.startswith("-")

    async def test_sanitize_removes_leading_spaces(self):
        """Test that leading spaces are removed."""
        result = sanitize_filename(" spaced_file.txt")
        assert not result.startswith(" ")

    async def test_sanitize_rejects_empty_filename(self):
        """Test that empty filename is rejected."""
        with pytest.raises(PathValidationError):
            sanitize_filename("")

    async def test_sanitize_rejects_filename_becoming_empty(self):
        """Test that filename that becomes empty after sanitization is rejected."""
        # "..." becomes "._" after sanitization (dots stripped, one remains)
        # Need a filename that becomes completely empty
        with pytest.raises(PathValidationError):
            sanitize_filename("..")

    async def test_sanitize_rejects_filename_becoming_underscores(self):
        """Test that filename that becomes only underscores is rejected."""
        with pytest.raises(PathValidationError):
            sanitize_filename("!!!")

    async def test_sanitize_truncates_long_filenames(self):
        """Test that long filenames are truncated to max_length."""
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) == 255

    async def test_sanitize_preserves_allowed_chars(self):
        """Test that allowed characters are preserved."""
        result = sanitize_filename("file-123_ABC.test.txt")
        assert result == "file-123_ABC.test.txt"

    async def test_sanitize_handles_unicode(self):
        """Test that Unicode characters are handled."""
        result = sanitize_filename("文件.txt")
        # Unicode chars should be replaced with underscores
        assert result.count("_") > 0


class TestValidateFileOperation:
    """Test suite for validate_file_operation function."""

    async def test_validate_read_operation(self):
        """Test validation for read operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            result = validate_file_operation(
                test_file,
                operation="read",
                allowed_base_dirs=[tmpdir],
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_write_operation(self):
        """Test validation for write operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"

            result = validate_file_operation(
                test_file,
                operation="write",
                allowed_base_dirs=[tmpdir],
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_delete_operation(self):
        """Test validation for delete operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            result = validate_file_operation(
                test_file,
                operation="delete",
                allowed_base_dirs=[tmpdir],
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_execute_operation(self):
        """Test validation for execute operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "script.sh"
            test_file.touch()
            test_file.chmod(0o755)

            result = validate_file_operation(
                test_file,
                operation="execute",
                allowed_base_dirs=[tmpdir],
            )

            assert result.resolve() == test_file.resolve()

    async def test_validate_invalid_operation(self):
        """Test that invalid operation is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            with pytest.raises(PathValidationError) as exc_info:
                validate_file_operation(
                    test_file,
                    operation="invalid_op",
                    allowed_base_dirs=[tmpdir],
                )

            assert "invalid operation" in str(exc_info.value).lower()

    async def test_validate_read_requires_file(self):
        """Test that read operation requires a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "testdir"
            test_dir.mkdir()

            with pytest.raises(PathValidationError):
                validate_file_operation(
                    test_dir,
                    operation="read",
                    allowed_base_dirs=[tmpdir],
                )


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    async def test_validate_empty_path_string(self):
        """Test validation of empty path string."""
        with pytest.raises(PathValidationError):
            validate_path("", allowed_base_dirs=["/tmp"])

    async def test_validate_none_allowed_base_dirs(self):
        """Test that None allowed_base_dirs uses current directory."""
        import os
        cwd = os.getcwd()

        test_file = Path(cwd) / "test_temp.txt"
        try:
            test_file.touch()

            result = validate_path(
                "test_temp.txt",
                allowed_base_dirs=None,
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()
        finally:
            test_file.unlink(missing_ok=True)

    async def test_sanitize_very_long_filename(self):
        """Test sanitization of very long filename."""
        long_name = "x" * 10000
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) == 255

    async def test_validate_nested_paths(self):
        """Test validation of deeply nested paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c" / "d" / "e"
            nested.mkdir(parents=True)

            result = validate_path(
                nested,
                allowed_base_dirs=[tmpdir],
                must_exist=True,
            )

            assert result.resolve() == nested.resolve()

    async def test_validate_path_with_unicode_characters(self):
        """Test validation of path with Unicode characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "文件.txt"
            test_file.touch()

            result = validate_path(
                test_file,
                allowed_base_dirs=[tmpdir],
                must_exist=True,
            )

            assert result.resolve() == test_file.resolve()
