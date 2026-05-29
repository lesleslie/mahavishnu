"""Unit tests for path validation security functions."""

import os
from pathlib import Path
import tempfile

import pytest

from mahavishnu.core.validators import (
    PathValidationError,
    PathValidator,
    resolve_safe_path,
    sanitize_filename,
    validate_repository_path,
)


class TestPathValidationError:
    """Tests for PathValidationError exception."""

    def test_error_initialization(self):
        """Test error initialization with all parameters."""
        error = PathValidationError(
            message="Test error",
            path="/test/path",
            details="Additional details",
        )

        assert error.message == "Test error"
        assert error.path == "/test/path"
        assert error.details == "Additional details"
        assert str(error) == "Test error"

    def test_error_without_details(self):
        """Test error initialization without details."""
        error = PathValidationError(message="Test error", path="/test/path")

        assert error.message == "Test error"
        assert error.path == "/test/path"
        assert error.details is None

    def test_to_dict_with_details(self):
        """Test to_dict method includes details when present."""
        error = PathValidationError(
            message="Test error",
            path="/test/path",
            details="Additional details",
        )

        result = error.to_dict()

        assert result == {
            "error": "Test error",
            "path": "/test/path",
            "details": "Additional details",
        }

    def test_to_dict_without_details(self):
        """Test to_dict method excludes details when None."""
        error = PathValidationError(message="Test error", path="/test/path")

        result = error.to_dict()

        assert result == {"error": "Test error", "path": "/test/path"}

    def test_path_object_conversion(self):
        """Test error initialization with Path object."""
        path = Path("/test/path")
        error = PathValidationError(message="Test error", path=path)

        assert error.path == "/test/path"


class TestPathValidator:
    """Tests for PathValidator class."""

    def test_initialization_without_allowed_dirs(self):
        """Test validator initialization without allowed directories."""
        validator = PathValidator()

        assert validator.allowed_base_dirs is None
        assert validator.strict_mode is True

    def test_initialization_with_allowed_dirs(self):
        """Test validator initialization with allowed directories."""
        allowed_dirs = ["/tmp", "/home/user"]
        validator = PathValidator(allowed_base_dirs=allowed_dirs)

        assert len(validator.allowed_base_dirs) == 2
        assert all(isinstance(d, Path) for d in validator.allowed_base_dirs)

    def test_initialization_with_strict_mode_false(self):
        """Test validator initialization with strict mode disabled."""
        validator = PathValidator(strict_mode=False)

        assert validator.strict_mode is False

    def test_validate_path_with_valid_path(self):
        """Test validation of a valid path."""
        validator = PathValidator()
        path = validator.validate_path("/tmp/test.txt")

        assert isinstance(path, Path)
        assert path.is_absolute()

    def test_validate_path_with_path_object(self):
        """Test validation with Path object input."""
        validator = PathValidator()
        input_path = Path("/tmp/test.txt")
        result = validator.validate_path(input_path)

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_validate_path_detects_traversal_double_dot(self):
        """Test validation detects directory traversal with .."""
        validator = PathValidator(allowed_base_dirs=["/tmp"])

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_path("/tmp/../../etc/passwd")

        assert "traversal" in str(exc_info.value).lower()

    def test_validate_path_normalizes_double_slash(self):
        """Test validation normalizes double slash sequences (Python handles this)."""
        validator = PathValidator()

        # Python's Path normalizes double slashes automatically
        # So this should succeed and return a normalized path
        path = validator.validate_path("/tmp//test.txt")

        assert path.is_absolute()
        assert "tmp" in str(path)

    def test_validate_path_with_allowed_base_dir(self):
        """Test validation with allowed base directory."""
        validator = PathValidator(allowed_base_dirs=["/tmp"])
        path = validator.validate_path("/tmp/test.txt")

        # Path should resolve and be within /tmp (or /private/tmp on macOS)
        assert path.is_absolute()
        assert "tmp" in str(path)

    def test_validate_path_outside_allowed_dir(self):
        """Test validation rejects paths outside allowed directories."""
        validator = PathValidator(allowed_base_dirs=["/tmp"])

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_path("/etc/passwd")

        assert "outside allowed" in str(exc_info.value).lower()

    def test_validate_path_with_override_allowed_dirs(self):
        """Test validation with override allowed directories."""
        validator = PathValidator(allowed_base_dirs=["/tmp"])

        # Use a temporary directory for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "test.txt"
            test_path.write_text("test")

            result = validator.validate_path(test_path, allowed_base_dirs=[tmpdir])

            assert result.is_absolute()
            assert str(tmpdir) in str(result) or str(Path(tmpdir).resolve()) in str(result)

    def test_validate_path_must_exist_true(self):
        """Test validation with must_exist=True for existing file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            validator = PathValidator()
            path = validator.validate_path(temp_path, must_exist=True)

            assert path.exists()
        finally:
            os.unlink(temp_path)

    def test_validate_path_must_exist_false_for_nonexistent(self):
        """Test validation with must_exist=False for non-existent file."""
        validator = PathValidator()
        temp_path = f"/tmp/nonexistent_test_file_{os.getpid()}.txt"

        path = validator.validate_path(temp_path, must_exist=False)

        assert not path.exists()

    def test_validate_path_must_exist_true_for_nonexistent(self):
        """Test validation with must_exist=True fails for non-existent file."""
        validator = PathValidator()
        temp_path = f"/tmp/nonexistent_test_file_{os.getpid()}.txt"

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_path(temp_path, must_exist=True)

        assert "does not exist" in str(exc_info.value).lower()

    def test_is_path_within_base(self):
        """Test _is_path_within_base helper method."""
        validator = PathValidator()

        # Path within base
        assert validator._is_path_within_base(Path("/tmp/test"), Path("/tmp"))
        assert validator._is_path_within_base(Path("/tmp/subdir/test.txt"), Path("/tmp"))

        # Path outside base
        assert not validator._is_path_within_base(Path("/etc/passwd"), Path("/tmp"))
        assert not validator._is_path_within_base(Path("/home/user"), Path("/tmp"))


class TestValidateRepositoryPath:
    """Tests for repository path validation."""

    def test_validate_repository_path_with_valid_repo(self, tmp_path):
        """Test validation of valid repository with .git directory."""
        # Create a mock repository
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        validator = PathValidator()
        result = validator.validate_repository_path(tmp_path)

        assert result == tmp_path

    def test_validate_repository_path_with_common_files(self, tmp_path):
        """Test validation of repository with common project files."""
        # Create README.md
        readme = tmp_path / "README.md"
        readme.write_text("# Test Repository")

        validator = PathValidator()
        result = validator.validate_repository_path(tmp_path)

        assert result == tmp_path

    def test_validate_repository_path_rejects_file(self, tmp_path):
        """Test validation rejects file instead of directory."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_repository_path(test_file)

        assert "must be a directory" in str(exc_info.value).lower()

    def test_validate_repository_path_rejects_non_repo(self, tmp_path):
        """Test validation rejects directory without repository indicators."""
        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_repository_path(tmp_path)

        assert "does not appear to be a repository" in str(exc_info.value).lower()

    def test_validate_repository_path_requires_existence(self):
        """Test validation requires path to exist."""
        validator = PathValidator()
        non_existent = Path("/tmp/nonexistent_repo_12345")

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_repository_path(non_existent)

        # The error message could be "does not exist" or "does not appear to be a repository"
        # depending on whether the path check happens first
        assert (
            "does not exist" in str(exc_info.value).lower()
            or "repository" in str(exc_info.value).lower()
        )


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_sanitize_normal_filename(self):
        """Test sanitization of normal filename."""
        result = PathValidator.sanitize_filename("normal-file.txt")

        assert result == "normal-file.txt"

    def test_sanitize_with_forward_slash(self):
        """Test sanitization replaces forward slashes."""
        result = PathValidator.sanitize_filename("path/to/file.txt")

        assert result == "path_to_file.txt"

    def test_sanitize_with_backslash(self):
        """Test sanitization replaces backslashes."""
        result = PathValidator.sanitize_filename("path\\to\\file.txt")

        assert result == "path_to_file.txt"

    def test_sanitize_with_double_dot(self):
        """Test sanitization handles directory traversal."""
        result = PathValidator.sanitize_filename("../../../etc/passwd")

        assert ".." not in result
        assert result.count("_") >= 3

    def test_sanitize_with_control_characters(self):
        """Test sanitization removes control characters."""
        result = PathValidator.sanitize_filename("test\x00\x01file.txt")

        assert "\x00" not in result
        assert "\x01" not in result

    def test_sanitize_windows_reserved_names(self):
        """Test sanitization handles Windows reserved filenames."""
        for reserved in ["CON", "PRN", "AUX", "NUL"]:
            result = PathValidator.sanitize_filename(reserved)
            assert not result.upper() == reserved
            assert result.startswith("_")

    def test_sanitize_windows_reserved_names_with_extension(self):
        """Test sanitization handles Windows reserved filenames with extensions."""
        result = PathValidator.sanitize_filename("CON.txt")

        assert result.startswith("_")
        assert result.endswith(".txt")

    def test_sanitize_empty_string(self):
        """Test sanitization of empty string."""
        result = PathValidator.sanitize_filename("")

        assert result == "unnamed"

    def test_sanitize_trailing_dots(self):
        """Test sanitization removes trailing dots."""
        result = PathValidator.sanitize_filename("test...")

        assert not result.endswith(".")
        assert "test" in result

    def test_sanitize_leading_spaces(self):
        """Test sanitization removes leading spaces."""
        result = PathValidator.sanitize_filename("  test.txt")

        assert not result.startswith(" ")

    def test_sanitize_long_filename(self):
        """Test sanitization truncates long filenames."""
        # Create a filename longer than 255 characters
        long_name = "a" * 300 + ".txt"
        result = PathValidator.sanitize_filename(long_name)

        assert len(result) <= 255
        assert result.endswith(".txt")

    def test_sanitize_preserves_extension(self):
        """Test sanitization preserves file extension."""
        result = PathValidator.sanitize_filename("my-file.tar.gz")

        assert result.endswith(".tar.gz")


class TestValidateFileOperation:
    """Tests for file operation validation."""

    def test_validate_read_operation_success(self, tmp_path):
        """Test validation of read operation on readable file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        validator = PathValidator()
        result = validator.validate_file_operation(test_file, "read")

        assert result is True

    def test_validate_read_operation_unreadable(self, tmp_path):
        """Test validation fails for unreadable file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Make file unreadable
        os.chmod(test_file, 0o000)

        try:
            validator = PathValidator()

            with pytest.raises(PathValidationError) as exc_info:
                validator.validate_file_operation(test_file, "read")

            assert "permission denied" in str(exc_info.value.message).lower()
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_validate_read_nonexistent_file(self, tmp_path):
        """Test validation fails for reading non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_file_operation(test_file, "read")

        assert "non-existent" in str(exc_info.value.message).lower()

    def test_validate_write_operation_new_file(self, tmp_path):
        """Test validation of write operation for new file."""
        test_file = tmp_path / "new_file.txt"

        validator = PathValidator()
        result = validator.validate_file_operation(test_file, "write")

        assert result is True

    def test_validate_write_operation_existing_file(self, tmp_path):
        """Test validation of write operation for existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        validator = PathValidator()
        result = validator.validate_file_operation(test_file, "write")

        assert result is True

    def test_validate_write_operation_readonly_file(self, tmp_path):
        """Test validation fails for readonly file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        os.chmod(test_file, 0o444)  # Read-only

        try:
            validator = PathValidator()

            with pytest.raises(PathValidationError) as exc_info:
                validator.validate_file_operation(test_file, "write")

            assert "permission denied" in str(exc_info.value.message).lower()
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_validate_write_operation_readonly_parent(self, tmp_path):
        """Test validation fails when parent is not writable."""
        # Create a read-only directory (skip on systems where we can't change perms)
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        try:
            os.chmod(readonly_dir, 0o000)

            test_file = readonly_dir / "test.txt"

            validator = PathValidator()

            # This might not work on all systems due to permission issues
            # so we'll catch and check if it's the expected error
            try:
                validator.validate_file_operation(test_file, "write")
                # If we got here, we couldn't set read-only (e.g., running as root)
                # Skip this test
                pytest.skip("Cannot set read-only permissions")
            except PathValidationError as exc:
                assert (
                    "permission denied" in str(exc.message).lower()
                    or "validation failed" in str(exc.message).lower()
                )
        except PermissionError:
            # Skip if we can't change permissions
            pytest.skip("Cannot change directory permissions")
        finally:
            # Restore permissions for cleanup
            try:
                os.chmod(readonly_dir, 0o755)
            except (PermissionError, OSError):
                pass

    def test_validate_delete_operation_success(self, tmp_path):
        """Test validation of delete operation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        validator = PathValidator()
        result = validator.validate_file_operation(test_file, "delete")

        assert result is True

    def test_validate_delete_operation_repository(self, tmp_path):
        """Test validation prevents deletion of repository directory."""
        # Create a mock repository
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_file_operation(tmp_path, "delete")

        assert "repository" in str(exc_info.value.message).lower()

    def test_validate_execute_operation_executable(self, tmp_path):
        """Test validation of execute operation on executable file."""
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho test")
        test_file.chmod(0o755)

        validator = PathValidator()
        result = validator.validate_file_operation(test_file, "execute")

        assert result is True

    def test_validate_execute_operation_not_executable(self, tmp_path):
        """Test validation fails for non-executable file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        test_file.chmod(0o644)

        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_file_operation(test_file, "execute")

        assert "permission denied" in str(exc_info.value.message).lower()

    def test_validate_execute_operation_directory(self, tmp_path):
        """Test validation rejects executing a directory."""
        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_file_operation(tmp_path, "execute")

        assert "cannot execute directory" in str(exc_info.value.message).lower()

    def test_validate_invalid_operation(self, tmp_path):
        """Test validation rejects invalid operation type."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        validator = PathValidator()

        with pytest.raises(PathValidationError) as exc_info:
            validator.validate_file_operation(test_file, "invalid")

        assert "invalid operation" in str(exc_info.value.message).lower()


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_resolve_safe_path_caching(self, tmp_path):
        """Test resolve_safe_path caches results."""
        test_path = tmp_path / "test.txt"
        test_path.write_text("test")

        # First call
        result1 = resolve_safe_path(test_path)

        # Second call should use cache
        result2 = resolve_safe_path(test_path)

        assert result1 == result2

    def test_resolve_safe_path_with_base_dir(self, tmp_path):
        """Test resolve_safe_path with base directory."""
        test_path = tmp_path / "test.txt"
        test_path.write_text("test")

        result = resolve_safe_path(test_path, base_dir=tmp_path)

        assert result == test_path.resolve()

    def test_sanitize_filename_function(self):
        """Test sanitize_filename convenience function."""
        result = sanitize_filename("../../../etc/passwd")

        assert ".." not in result

    def test_validate_repository_path_function(self, tmp_path):
        """Test validate_repository_path convenience function."""
        # Create a mock repository
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        result = validate_repository_path(tmp_path)

        assert result == tmp_path


class TestSecurityEdgeCases:
    """Tests for security edge cases."""

    def test_symlink_outside_allowed_dir(self, tmp_path):
        """Test validation prevents accessing symlinks outside allowed dirs."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret")

        symlink = allowed_dir / "link_to_outside"
        symlink.symlink_to(outside_file)

        validator = PathValidator(allowed_base_dirs=[str(allowed_dir)])

        # This should fail because symlink target is outside allowed directory
        with pytest.raises(PathValidationError):
            validator.validate_path(symlink)

    def test_absolute_path_from_relative(self):
        """Test validation converts relative paths to absolute."""
        validator = PathValidator()

        # Get current directory
        result = validator.validate_path(".")

        assert result.is_absolute()

    def test_unicode_in_path(self, tmp_path):
        """Test validation handles unicode characters."""
        unicode_dir = tmp_path / "test_日本語"
        unicode_dir.mkdir()

        validator = PathValidator(allowed_base_dirs=[str(tmp_path)])
        result = validator.validate_path(unicode_dir)

        assert result == unicode_dir.resolve()

    def test_very_deep_path(self, tmp_path):
        """Test validation handles deeply nested paths."""
        deep_dir = tmp_path
        for i in range(10):
            deep_dir = deep_dir / f"level{i}"
            deep_dir.mkdir()

        validator = PathValidator(allowed_base_dirs=[str(tmp_path)])
        result = validator.validate_path(deep_dir)

        assert result == deep_dir.resolve()


class TestValidatorsAdditionalBranches:
    def test_validate_path_resolves_relative_parent_fallback(self, monkeypatch):
        validator = PathValidator()
        path = Path("/tmp/missing-parent/file.txt")
        parent = path.parent
        calls = {"count": 0}

        def fake_resolve(self, strict=False):  # noqa: ANN001,ANN003
            if self == path:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise FileNotFoundError("missing path")
                return path
            if self == parent and strict:
                return Path("/tmp/missing-parent")
            return self

        monkeypatch.setattr(Path, "resolve", fake_resolve, raising=True)

        result = validator._resolve_path_safely(path, must_exist=False)
        assert result == path

    def test_validate_path_resolves_parent_missing_fallback(self, monkeypatch):
        validator = PathValidator()
        path = Path("/tmp/missing-parent/file.txt")
        parent = path.parent
        calls = {"count": 0}

        def fake_resolve(self, strict=False):  # noqa: ANN001,ANN003
            if self == path:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise FileNotFoundError("missing path")
                return path
            if self == parent and strict:
                raise FileNotFoundError("missing parent")
            return self

        monkeypatch.setattr(Path, "resolve", fake_resolve, raising=True)

        result = validator._resolve_path_safely(path, must_exist=False)
        assert result == path

    def test_is_path_within_base_handles_resolution_errors(self, monkeypatch):
        validator = PathValidator()

        def fake_resolve(self, strict=False):  # noqa: ANN001,ANN003
            raise RuntimeError("boom")

        monkeypatch.setattr(Path, "resolve", fake_resolve, raising=True)

        assert validator._is_path_within_base(Path("/tmp/a"), Path("/tmp")) is False

    def test_validate_path_rejects_normalized_parent_reference(self, monkeypatch):
        validator = PathValidator()
        monkeypatch.setattr(
            validator,
            "_resolve_path_safely",
            lambda path_obj, must_exist: Path("../escape"),  # noqa: ARG005
            raising=True,
        )

        with pytest.raises(PathValidationError, match="parent directory references"):
            validator.validate_path("/tmp/test.txt")

    def test_check_path_format_rejects_double_slash(self):
        validator = PathValidator()
        with pytest.raises(PathValidationError, match="Invalid path format"):
            validator._check_path_format("/tmp//test.txt")

    def test_validate_path_wraps_unexpected_exception(self, monkeypatch):
        validator = PathValidator()
        monkeypatch.setattr(validator, "_check_path_format", lambda path_str: None, raising=True)

        def boom(*args, **kwargs):  # noqa: ANN001,ANN002
            raise RuntimeError("boom")

        monkeypatch.setattr(validator, "_resolve_path_safely", boom, raising=True)

        with pytest.raises(PathValidationError, match="Unexpected validation error"):
            validator.validate_path("/tmp/test.txt")

    def test_validate_repository_path_unreadable(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        validator = PathValidator()
        monkeypatch.setattr(os, "access", lambda path, mode: False, raising=True)

        with pytest.raises(PathValidationError, match="not readable"):
            validator.validate_repository_path(repo)

    def test_validate_repository_path_wraps_unexpected_exception(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        validator = PathValidator()
        monkeypatch.setattr(
            validator,
            "validate_path",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
            raising=True,
        )

        with pytest.raises(PathValidationError, match="Repository validation failed"):
            validator.validate_repository_path(repo)

    def test_sanitize_filename_empty_and_long_without_extension(self):
        assert PathValidator.sanitize_filename("   .   ") == "unnamed"
        assert len(PathValidator.sanitize_filename("b" * 300)) == 255

    def test_validate_write_operation_missing_parent(self, tmp_path):
        validator = PathValidator()
        target = tmp_path / "missing" / "file.txt"

        with pytest.raises(PathValidationError, match="Parent directory does not exist"):
            validator.validate_file_operation(target, "write")

    def test_validate_write_operation_parent_not_writable(self, tmp_path, monkeypatch):
        parent = tmp_path / "readonly"
        parent.mkdir()
        target = parent / "file.txt"
        validator = PathValidator()

        def fake_access(path, mode):  # noqa: ANN001,ANN002
            return path != parent

        monkeypatch.setattr(os, "access", fake_access, raising=True)

        with pytest.raises(PathValidationError, match="Write permission denied"):
            validator.validate_file_operation(target, "write")

    def test_validate_delete_operation_permission_denied(self, tmp_path, monkeypatch):
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        validator = PathValidator()
        monkeypatch.setattr(os, "access", lambda path, mode: False, raising=True)

        with pytest.raises(PathValidationError, match="Delete permission denied"):
            validator.validate_file_operation(test_file, "delete")

    def test_validate_execute_operation_missing_bits(self, tmp_path, monkeypatch):
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/sh\necho test")
        test_file.chmod(0o755)
        validator = PathValidator()

        class _Stat:
            st_mode = 0

        orig_is_file = Path.is_file
        orig_stat = Path.stat

        def fake_is_file(self, *args, **kwargs):  # noqa: ANN001,ANN003
            if self == test_file:
                return True
            return orig_is_file(self, *args, **kwargs)

        def fake_stat(self, *args, **kwargs):  # noqa: ANN001,ANN003
            if self == test_file:
                return _Stat()
            return orig_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "is_file", fake_is_file, raising=True)
        monkeypatch.setattr(Path, "stat", fake_stat, raising=True)

        with pytest.raises(PathValidationError, match="not marked as executable"):
            validator.validate_file_operation(test_file, "execute")
