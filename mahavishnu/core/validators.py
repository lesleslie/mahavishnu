"""
Path validation security functions for Mahavishnu.

This module provides secure path validation to prevent directory traversal
attacks and other filesystem-based security vulnerabilities.
"""

from functools import lru_cache
import os
from pathlib import Path
import stat
from typing import Literal


class PathValidationError(Exception):
    """Custom exception for path validation errors.

    Attributes:
        message: Human-readable error description
        path: The invalid path that caused the error
        details: Additional context about the validation failure

    Examples:
        >>> try:
        ...     validator.validate_path("../etc/passwd")
        ... except PathValidationError as e:
        ...     print(f"Error: {e.message}")
        ...     print(f"Path: {e.path}")
        Error: Path traversal attempt detected
        Path: ../etc/passwd
    """

    def __init__(self, message: str, path: str | Path, details: str | None = None):
        """Initialize path validation error.

        Args:
            message: Human-readable error description
            path: The invalid path that caused the error
            details: Additional context about the validation failure
        """
        self.message = message
        self.path = str(path)
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, str]:
        """Convert error to dictionary for API responses.

        Returns:
            Dictionary with error details
        """
        result = {"error": self.message, "path": self.path}
        if self.details:
            result["details"] = self.details
        return result


class PathValidator:
    """Validates file system paths for security.

    This validator prevents directory traversal attacks, ensures paths
    remain within allowed boundaries, and validates file operations.

    Attributes:
        allowed_base_dirs: List of allowed base directory paths
        strict_mode: Whether to enforce strict validation

    Examples:
        >>> validator = PathValidator(allowed_base_dirs=["/tmp", "/home/user"])
        >>> safe_path = validator.validate_path("/tmp/test.txt")
        >>> print(safe_path)
        /tmp/test.txt
    """

    def __init__(
        self,
        allowed_base_dirs: list[str] | None = None,
        strict_mode: bool = True,
    ):
        """Initialize path validator.

        Args:
            allowed_base_dirs: List of allowed base directory paths.
                If None, only prevents directory traversal.
            strict_mode: Whether to enforce strict validation (default: True)
        """
        self.allowed_base_dirs = (
            [Path(d).resolve() for d in allowed_base_dirs] if allowed_base_dirs else None
        )
        self.strict_mode = strict_mode

    def validate_path(
        self,
        path: str | Path,
        allowed_base_dirs: list[str] | None = None,
        must_exist: bool = False,
    ) -> Path:
        """Validate a path and return Path object.

        This method performs comprehensive security checks:
        1. Resolves the path to its absolute form
        2. Detects directory traversal attempts (.. sequences)
        3. Ensures path is within allowed base directories
        4. Optionally checks if the path exists

        Args:
            path: Path to validate (string or Path object)
            allowed_base_dirs: Optional override of allowed base directories.
                If provided, replaces instance-level allowed_base_dirs.
            must_exist: Whether the path must exist on the filesystem

        Returns:
            Resolved Path object if validation passes

        Raises:
            PathValidationError: If validation fails

        Examples:
            >>> validator = PathValidator(allowed_base_dirs=["/tmp"])
            >>> safe_path = validator.validate_path("/tmp/test.txt")
            >>> print(safe_path)
            /tmp/test.txt

            >>> # This raises PathValidationError
            >>> validator.validate_path("/etc/passwd")
        """
        try:
            # Convert to Path object
            path_obj = Path(path) if not isinstance(path, Path) else path

            # Check for path traversal in the original string
            path_str = str(path_obj)
            if ".." in path_str:
                raise PathValidationError(
                    message="Path traversal attempt detected",
                    path=path_str,
                    details="Path contains '..' sequences",
                )

            # Check for double slashes (potential path manipulation)
            if "//" in path_str:
                raise PathValidationError(
                    message="Invalid path format detected",
                    path=path_str,
                    details="Path contains '//' sequences",
                )

            # Resolve to absolute path (follows symlinks by default)
            try:
                resolved_path = path_obj.resolve(strict=must_exist)
            except FileNotFoundError as e:
                if must_exist:
                    raise PathValidationError(
                        message="Path does not exist",
                        path=str(path_obj),
                        details=f"Required path not found: {e}",
                    ) from e
                # For non-existent paths, resolve parent and append
                try:
                    resolved_parent = path_obj.parent.resolve(strict=True)
                    resolved_path = resolved_parent / path_obj.name
                except FileNotFoundError:
                    # Parent doesn't exist either, just resolve as much as possible
                    resolved_path = path_obj.resolve()

            # Check against allowed base directories
            base_dirs = (
                [Path(d).resolve() for d in allowed_base_dirs]
                if allowed_base_dirs
                else self.allowed_base_dirs
            )

            if base_dirs and not any(
                self._is_path_within_base(resolved_path, base_dir) for base_dir in base_dirs
            ):
                raise PathValidationError(
                    message="Path is outside allowed directories",
                    path=str(resolved_path),
                    details=f"Path must be within one of: {[str(d) for d in base_dirs]}",
                )

            # Final safety check for directory traversal in resolved path
            # (shouldn't happen if resolve() worked correctly, but be defensive)
            resolved_str = str(resolved_path)
            if ".." in resolved_str:
                raise PathValidationError(
                    message="Resolved path contains parent directory references",
                    path=resolved_str,
                    details="Resolved path still contains '..' after normalization",
                )

            return resolved_path

        except PathValidationError:
            raise
        except Exception as e:
            raise PathValidationError(
                message="Unexpected validation error",
                path=str(path),
                details=f"{type(e).__name__}: {e}",
            ) from e

    def _is_path_within_base(self, path: Path, base_dir: Path) -> bool:
        """Check if path is within base directory.

        Args:
            path: Path to check
            base_dir: Base directory path

        Returns:
            True if path is within base_dir, False otherwise
        """
        try:
            # Resolve both paths to absolute
            path_resolved = path.resolve()
            base_resolved = base_dir.resolve()

            # Check if path starts with base directory (with trailing separator)
            base_str = str(base_resolved)
            path_str = str(path_resolved)

            # Ensure base directory path ends with separator for proper matching
            if not base_str.endswith(os.sep):
                base_str = base_str + os.sep

            return path_str.startswith(base_str) or path_str == str(base_resolved)
        except (OSError, RuntimeError):
            return False

    def validate_repository_path(self, path: str | Path) -> Path:
        """Validate repository path with additional checks.

        Performs extra validation specific to repository paths:
        - Checks for .git directory (valid repository indicator)
        - Validates common repository files (README, etc.)
        - Ensures directory is readable

        Args:
            path: Repository path to validate

        Returns:
            Validated Path object

        Raises:
            PathValidationError: If validation fails

        Examples:
            >>> validator = PathValidator()
            >>> repo_path = validator.validate_repository_path("/path/to/repo")
            >>> print(repo_path)
            /path/to/repo
        """
        try:
            # First perform standard validation
            validated_path = self.validate_path(path, must_exist=True)

            # Must be a directory
            if not validated_path.is_dir():
                raise PathValidationError(
                    message="Repository path must be a directory",
                    path=str(validated_path),
                    details="Path is a file, not a directory",
                )

            # Check for .git directory (strong repository indicator)
            git_dir = validated_path / ".git"
            is_repo = git_dir.exists() and git_dir.is_dir()

            # Alternative: Check for common repository files
            if not is_repo:
                common_files = [
                    "README.md",
                    "README.rst",
                    "pyproject.toml",
                    "setup.py",
                    "package.json",
                    "Cargo.toml",
                    "go.mod",
                ]
                has_repo_files = any((validated_path / f).exists() for f in common_files)

                if not has_repo_files:
                    raise PathValidationError(
                        message="Path does not appear to be a repository",
                        path=str(validated_path),
                        details="No .git directory or common repository files found",
                    )

            # Check directory is readable
            if not os.access(validated_path, os.R_OK):
                raise PathValidationError(
                    message="Repository path is not readable",
                    path=str(validated_path),
                    details="Insufficient permissions to read directory",
                )

            return validated_path

        except PathValidationError:
            raise
        except Exception as e:
            raise PathValidationError(
                message="Repository validation failed",
                path=str(path),
                details=f"{type(e).__name__}: {e}",
            ) from e

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename to prevent path traversal.

        Removes or replaces dangerous characters and sequences:
        - Path separators (/, \\)
        - Directory traversal (..)
        - Control characters
        - Reserved filenames (Windows)

        Args:
            filename: Original filename

        Returns:
            Sanitized filename safe for filesystem use

        Examples:
            >>> PathValidator.sanitize_filename("../../../etc/passwd")
            '..._.._.._etc_passwd'

            >>> PathValidator.sanitize_filename("normal-file.txt")
            'normal-file.txt'
        """
        if not filename:
            return "unnamed"

        # Replace path separators with underscores
        sanitized = filename.replace("/", "_").replace("\\", "_")

        # Replace directory traversal sequences
        if ".." in sanitized:
            sanitized = sanitized.replace("..", "_.")

        # Remove control characters
        sanitized = "".join(char for char in sanitized if ord(char) >= 32)

        # Windows reserved filenames
        windows_reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }

        name_without_ext = sanitized.rsplit(".", 1)[0]
        if name_without_ext.upper() in windows_reserved:
            sanitized = f"_{sanitized}"

        # Remove leading/trailing spaces and dots (Windows issues)
        sanitized = sanitized.strip(". ")

        # Ensure filename is not empty after sanitization
        if not sanitized:
            return "unnamed"

        # Limit length (common filesystem limit is 255)
        max_length = 255
        if len(sanitized) > max_length:
            # Keep extension if present
            if "." in sanitized:
                name, ext = sanitized.rsplit(".", 1)
                sanitized = name[: max_length - len(ext) - 1] + "." + ext
            else:
                sanitized = sanitized[:max_length]

        return sanitized

    def validate_file_operation(
        self,
        path: Path,
        operation: Literal["read", "write", "delete", "execute"],
    ) -> bool:
        """Validate if file operation is permitted.

        Checks both file permissions and security policies:
        - Verifies operation is allowed for the file type
        - Checks filesystem permissions
        - Validates against allowed base directories

        Args:
            path: Path to the file
            operation: Type of operation to perform

        Returns:
            True if operation is permitted

        Raises:
            PathValidationError: If operation is not permitted

        Examples:
            >>> validator = PathValidator(allowed_base_dirs=["/tmp"])
            >>> path = Path("/tmp/test.txt")
            >>> validator.validate_file_operation(path, "read")
            True

            >>> # This raises if file is not readable
            >>> validator.validate_file_operation(path, "read")
        """
        try:
            # First validate the path itself
            validated_path = self.validate_path(path)

            # Check if path exists (for most operations)
            if operation != "write" and not validated_path.exists():
                raise PathValidationError(
                    message=f"Cannot {operation} non-existent path",
                    path=str(validated_path),
                    details=f"Path must exist for {operation} operation",
                )

            # Check permissions based on operation type
            if operation == "read":
                if not os.access(validated_path, os.R_OK):
                    raise PathValidationError(
                        message="Read permission denied",
                        path=str(validated_path),
                        details="File or directory is not readable",
                    )

            elif operation == "write":
                # Check parent directory is writable if file doesn't exist
                if not validated_path.exists():
                    parent = validated_path.parent
                    if not parent.exists():
                        raise PathValidationError(
                            message="Parent directory does not exist",
                            path=str(validated_path),
                            details=f"Cannot create file: {parent} does not exist",
                        )
                    if not os.access(parent, os.W_OK):
                        raise PathValidationError(
                            message="Write permission denied",
                            path=str(validated_path),
                            details="Parent directory is not writable",
                        )
                else:
                    if not os.access(validated_path, os.W_OK):
                        raise PathValidationError(
                            message="Write permission denied",
                            path=str(validated_path),
                            details="File or directory is not writable",
                        )

            elif operation == "delete":
                if not os.access(validated_path, os.W_OK):
                    raise PathValidationError(
                        message="Delete permission denied",
                        path=str(validated_path),
                        details="File or directory is not writable",
                    )

                # Prevent deletion of critical directories
                if validated_path.is_dir():
                    # Check for .git directory (prevent accidental repo deletion)
                    if (validated_path / ".git").exists():
                        raise PathValidationError(
                            message="Cannot delete repository directory",
                            path=str(validated_path),
                            details="Directory contains .git - likely a repository",
                        )

            elif operation == "execute":
                if not os.access(validated_path, os.X_OK):
                    raise PathValidationError(
                        message="Execute permission denied",
                        path=str(validated_path),
                        details="File is not executable",
                    )

                # Verify it's actually a file (not directory) for execution
                if not validated_path.is_file():
                    raise PathValidationError(
                        message="Cannot execute directory",
                        path=str(validated_path),
                        details="Only files can be executed",
                    )

                # Check for executable bit
                st_mode = validated_path.stat().st_mode
                if not (st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                    raise PathValidationError(
                        message="File is not marked as executable",
                        path=str(validated_path),
                        details="No execute permission bits set",
                    )

            else:
                raise PathValidationError(
                    message=f"Invalid operation type: {operation}",
                    path=str(validated_path),
                    details="Operation must be 'read', 'write', 'delete', or 'execute'",
                )

            return True

        except PathValidationError:
            raise
        except Exception as e:
            raise PathValidationError(
                message=f"File operation validation failed: {operation}",
                path=str(path),
                details=f"{type(e).__name__}: {e}",
            ) from e


@lru_cache(maxsize=128)
def resolve_safe_path(path: str | Path, base_dir: str | Path | None = None) -> Path:
    """Cacheable helper to safely resolve a path.

    This function is cached for performance when validating the same
    paths repeatedly. It's a convenience wrapper around PathValidator.

    Args:
        path: Path to resolve
        base_dir: Optional base directory to validate against

    Returns:
        Resolved and validated Path object

    Raises:
        PathValidationError: If path is invalid

    Examples:
        >>> resolve_safe_path("/tmp/test.txt")
        /tmp/test.txt

        >>> resolve_safe_path("../test", "/tmp")
        /tmp/test
    """
    validator = PathValidator(allowed_base_dirs=[str(base_dir)] if base_dir else None)
    return validator.validate_path(path)


def validate_repository_path(path: str | Path) -> Path:
    """Convenience function to validate repository path.

    Args:
        path: Repository path to validate

    Returns:
        Validated Path object

    Raises:
        PathValidationError: If validation fails

    Examples:
        >>> validate_repository_path("/path/to/repo")
        /path/to/repo
    """
    validator = PathValidator()
    return validator.validate_repository_path(path)


def sanitize_filename(filename: str) -> str:
    """Convenience function to sanitize filename.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename

    Examples:
        >>> sanitize_filename("../../../etc/passwd")
        '..._.._.._etc_passwd'
    """
    return PathValidator.sanitize_filename(filename)
