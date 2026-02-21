"""File operation tools for Agno agents.

These tools provide safe file system operations that can be used by
Agno agents for reading, writing, and exploring code repositories.

All tools use Agno's native @tool decorator for seamless integration.
The actual implementations are separate functions for testing.

SECURITY: All file operations include path traversal prevention (CVE-MHV-001).
Paths are validated to ensure they remain within allowed base directories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agno.tools import tool

from mahavishnu.core.errors import AgnoError, ErrorCode

logger = logging.getLogger(__name__)

# Security constraints
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {
    # Python
    ".py",
    ".pyw",
    ".pyi",
    # Web
    ".html",
    ".css",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
    # Data/Config
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".ini",
    ".cfg",
    # Documentation
    ".md",
    ".rst",
    ".txt",
    # Shell/Scripts
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    # Go
    ".go",
    ".mod",
    ".sum",
    # Rust
    ".rs",
    # Java/JVM
    ".java",
    ".kt",
    ".scala",
    ".groovy",
    # C/C++
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cc",
    # Other
    ".sql",
    ".graphql",
    ".proto",
    ".dockerfile",
    ".makefile",
    ".r",
    ".rb",
    ".php",
    ".lua",
    ".pl",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".clj",
    ".lisp",
    ".scm",
}
BLOCKED_PATHS = {
    ".env",
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

# Default allowed base directories - can be overridden via configuration
DEFAULT_ALLOWED_BASE_DIRS = [
    Path("/Users/les/Projects"),
    Path.cwd(),  # Current working directory
]


def _get_allowed_base_dirs() -> list[Path]:
    """Get list of allowed base directories from configuration.

    Returns:
        List of resolved Path objects for allowed base directories.
    """
    try:
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        if settings.allowed_repo_paths:
            return [Path(p).expanduser().resolve() for p in settings.allowed_repo_paths]
    except Exception:
        logger.debug("Could not load allowed_repo_paths from configuration, using defaults")

    return [p.resolve() for p in DEFAULT_ALLOWED_BASE_DIRS]


def _validate_path_within_allowed(resolved_path: Path, allowed_dirs: list[Path]) -> None:
    """Validate that a resolved path is within one of the allowed base directories.

    SECURITY: This is the core path traversal prevention check.
    It ensures that after resolving all symlinks and .. sequences,
    the path is still within an allowed directory.

    Args:
        resolved_path: The fully resolved absolute path to check.
        allowed_dirs: List of allowed base directories.

    Raises:
        AgnoError: If path escapes all allowed directories.
    """
    for allowed_dir in allowed_dirs:
        # Use is_relative_to for Python 3.9+, fallback to string comparison
        try:
            if resolved_path.is_relative_to(allowed_dir):
                return  # Path is within this allowed directory
        except AttributeError:
            # Python < 3.9 fallback
            try:
                resolved_path.relative_to(allowed_dir)
                return  # Path is within this allowed directory
            except ValueError:
                continue

    # Path is not within any allowed directory - security violation
    logger.warning(
        "SECURITY: Path traversal attempt blocked - path outside allowed directories",
        extra={
            "resolved_path": str(resolved_path),
            "allowed_dirs": [str(d) for d in allowed_dirs],
        },
    )
    raise AgnoError(
        "Access denied: path is outside allowed directories",
        error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
        details={
            "error_type": "path_traversal_blocked",
            # Don't reveal internal paths in error messages
        },
    )


def _detect_path_traversal_attempts(path: str) -> None:
    """Detect obvious path traversal attempts in the raw path string.

    This provides an additional layer of security by catching traversal
    attempts before resolution, which helps with logging and detection.

    Args:
        path: The raw path string to check.

    Raises:
        AgnoError: If obvious path traversal patterns are detected.
    """
    # Normalize path separators for detection
    normalized = path.replace("\\", "/")

    # Check for parent directory traversal
    # Match patterns like ../ or /.. or just ..
    traversal_patterns = [
        "../",  # Unix-style parent
        "/..",  # Parent at end or middle
        "\\..\\",  # Windows-style parent
        "..\\",  # Windows-style parent
    ]

    for pattern in traversal_patterns:
        if pattern in normalized:
            logger.warning(
                "SECURITY: Path traversal pattern detected in input path",
                extra={
                    "pattern_detected": pattern,
                    # Don't log the actual path to avoid leaking in logs
                },
            )
            raise AgnoError(
                "Access denied: path contains invalid traversal sequences",
                error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                details={
                    "error_type": "path_traversal_detected",
                    "pattern": pattern,
                },
            )

    # Check for null bytes (path injection)
    if "\x00" in path or "%00" in path:
        logger.warning("SECURITY: Null byte injection attempt detected")
        raise AgnoError(
            "Access denied: invalid characters in path",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"error_type": "null_byte_injection"},
        )


def _validate_path(path: str) -> Path:
    """Validate file path for security.

    SECURITY: Implements defense-in-depth path traversal prevention:
    1. Detects obvious traversal patterns in raw input
    2. Resolves path to absolute form (follows symlinks, normalizes ..)
    3. Validates resolved path is within allowed base directories
    4. Checks for blocked paths (sensitive directories)

    Args:
        path: File path to validate

    Returns:
        Resolved Path object that is safe to use

    Raises:
        AgnoError: If path is invalid, contains traversal attempts,
                   or is outside allowed directories
    """
    try:
        # Layer 1: Detect obvious traversal attempts in raw input
        _detect_path_traversal_attempts(path)

        # Layer 2: Resolve to absolute path (follows symlinks, normalizes ..)
        resolved = Path(path).resolve()

        # Layer 3: Validate path is within allowed base directories
        allowed_dirs = _get_allowed_base_dirs()
        _validate_path_within_allowed(resolved, allowed_dirs)

        # Layer 4: Check for blocked paths (existing security check)
        path_str = str(resolved)
        for blocked in BLOCKED_PATHS:
            # Check both as directory component and as exact match
            if f"/{blocked}/" in path_str or path_str.endswith(f"/{blocked}"):
                logger.warning(
                    "SECURITY: Access to blocked path denied",
                    extra={"blocked_directory": blocked},
                )
                raise AgnoError(
                    "Access denied: path contains blocked directory",
                    error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                    details={"error_type": "blocked_path", "blocked": blocked},
                )

        return resolved

    except AgnoError:
        # Re-raise our security errors
        raise
    except Exception as e:
        # Wrap other exceptions
        raise AgnoError(
            "Invalid path provided",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"error_type": "invalid_path", "error": str(e)},
        ) from e


def _validate_file_extension(path: Path) -> None:
    """Validate file extension is allowed.

    Args:
        path: Path to validate

    Raises:
        AgnoError: If extension is not allowed
    """
    # Allow files without extension (like Makefile, Dockerfile)
    if not path.suffix:
        return

    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AgnoError(
            f"File extension '{ext}' is not allowed",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": str(path), "extension": ext},
        )


def _check_file_size(path: Path) -> None:
    """Check file size is within limits.

    Args:
        path: Path to check

    Raises:
        AgnoError: If file is too large
    """
    if not path.exists():
        return

    size = path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        raise AgnoError(
            f"File too large: {size / (1024 * 1024):.2f}MB (max {MAX_FILE_SIZE_MB}MB)",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": str(path), "size_bytes": size, "max_bytes": MAX_FILE_SIZE_BYTES},
        )


# ============================================================================
# Implementation Functions (for direct testing)
# ============================================================================


def _read_file_impl(path: str) -> str:
    """Read file contents - implementation.

    Args:
        path: Absolute or relative path to the file

    Returns:
        File contents as a string

    Raises:
        AgnoError: If file cannot be read
    """
    validated_path = _validate_path(path)
    _validate_file_extension(validated_path)
    _check_file_size(validated_path)

    if not validated_path.exists():
        raise AgnoError(
            f"File not found: {path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": path},
        )

    if not validated_path.is_file():
        raise AgnoError(
            f"Not a file: {path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": path},
        )

    # Read with UTF-8 encoding, fallback to latin-1
    try:
        content = validated_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = validated_path.read_text(encoding="latin-1")

    logger.debug(f"Read file: {path} ({len(content)} chars)")
    return content


def _write_file_impl(path: str, content: str) -> dict[str, Any]:
    """Write content to a file - implementation.

    Args:
        path: Absolute or relative path to the file
        content: Content to write to the file

    Returns:
        Dict with success status and file info

    Raises:
        AgnoError: If file cannot be written
    """
    validated_path = _validate_path(path)
    _validate_file_extension(validated_path)

    # Check content size
    content_size = len(content.encode("utf-8"))
    if content_size > MAX_FILE_SIZE_BYTES:
        raise AgnoError(
            f"Content too large: {content_size / (1024 * 1024):.2f}MB (max {MAX_FILE_SIZE_MB}MB)",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"content_size_bytes": content_size},
        )

    # Create parent directories if needed
    validated_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    validated_path.write_text(content, encoding="utf-8")

    logger.info(f"Wrote file: {path} ({len(content)} chars)")
    return {
        "success": True,
        "path": str(validated_path),
        "bytes_written": content_size,
        "chars_written": len(content),
    }


def _list_directory_impl(path: str) -> list[str]:
    """List directory contents - implementation.

    Args:
        path: Absolute or relative path to the directory

    Returns:
        List of file and directory names

    Raises:
        AgnoError: If directory cannot be listed
    """
    validated_path = _validate_path(path)

    if not validated_path.exists():
        raise AgnoError(
            f"Directory not found: {path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": path},
        )

    if not validated_path.is_dir():
        raise AgnoError(
            f"Not a directory: {path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": path},
        )

    # List directory contents, filter blocked paths
    entries = []
    for entry in validated_path.iterdir():
        # Skip blocked paths
        if entry.name in BLOCKED_PATHS:
            continue

        # Mark directories with trailing slash
        if entry.is_dir():
            entries.append(f"{entry.name}/")
        else:
            entries.append(entry.name)

    # Sort entries: directories first, then files
    entries.sort(key=lambda x: (not x.endswith("/"), x.lower()))

    logger.debug(f"Listed directory: {path} ({len(entries)} entries)")
    return entries


def _search_files_impl(pattern: str, directory: str) -> list[str]:
    """Search for files matching a pattern - implementation.

    Args:
        pattern: Glob pattern to match (e.g., '*.py', 'test_*.txt')
        directory: Directory to search in

    Returns:
        List of matching file paths (relative to directory)

    Raises:
        AgnoError: If search fails
    """
    validated_path = _validate_path(directory)

    if not validated_path.exists():
        raise AgnoError(
            f"Directory not found: {directory}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"directory": directory},
        )

    if not validated_path.is_dir():
        raise AgnoError(
            f"Not a directory: {directory}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"directory": directory},
        )

    # Search for matching files recursively
    matches = []
    for match in validated_path.rglob(pattern):
        # Skip blocked paths
        if any(blocked in str(match) for blocked in BLOCKED_PATHS):
            continue

        # Only include files, not directories
        if match.is_file():
            # SECURITY: Verify each match is still within allowed directory
            # This prevents symlink attacks where rglob might escape
            try:
                match_resolved = match.resolve()
                allowed_dirs = _get_allowed_base_dirs()
                path_allowed = False
                for allowed_dir in allowed_dirs:
                    try:
                        if match_resolved.is_relative_to(allowed_dir):
                            path_allowed = True
                            break
                    except AttributeError:
                        try:
                            match_resolved.relative_to(allowed_dir)
                            path_allowed = True
                            break
                        except ValueError:
                            continue

                if not path_allowed:
                    logger.warning(
                        "SECURITY: Skipping search result outside allowed directory",
                        extra={"match": str(match)},
                    )
                    continue
            except Exception as e:
                logger.warning(f"Could not validate search result path: {e}")
                continue

            # Return relative path
            rel_path = match.relative_to(validated_path)
            matches.append(str(rel_path))

    # Sort results
    matches.sort()

    logger.debug(f"Found {len(matches)} files matching '{pattern}' in {directory}")
    return matches


# ============================================================================
# Agno Tool Definitions
# ============================================================================


@tool(
    name="read_file",
    description="Read the contents of a file from the filesystem",
    instructions="Use this tool to read file contents. Supports text files with allowed extensions only.",
)
def read_file(path: str) -> str:
    """Read file contents.

    Args:
        path: Absolute or relative path to the file

    Returns:
        File contents as a string
    """
    return _read_file_impl(path)


@tool(
    name="write_file",
    description="Write content to a file on the filesystem",
    instructions="Use this tool to create or overwrite files. Creates parent directories if needed.",
)
def write_file(path: str, content: str) -> dict[str, Any]:
    """Write content to a file.

    Args:
        path: Absolute or relative path to the file
        content: Content to write to the file

    Returns:
        Dict with success status and file info
    """
    return _write_file_impl(path, content)


@tool(
    name="list_directory",
    description="List the contents of a directory",
    instructions="Use this tool to explore directory structure. Returns list of files and subdirectories.",
)
def list_directory(path: str) -> list[str]:
    """List directory contents.

    Args:
        path: Absolute or relative path to the directory

    Returns:
        List of file and directory names
    """
    return _list_directory_impl(path)


@tool(
    name="search_files",
    description="Search for files matching a pattern in a directory",
    instructions="Use this tool to find files by name pattern. Supports glob patterns like '*.py'.",
)
def search_files(pattern: str, directory: str) -> list[str]:
    """Search for files matching a pattern.

    Args:
        pattern: Glob pattern to match (e.g., '*.py', 'test_*.txt')
        directory: Directory to search in

    Returns:
        List of matching file paths (relative to directory)
    """
    return _search_files_impl(pattern, directory)


__all__ = [
    # Agno tools (for agent use)
    "read_file",
    "write_file",
    "list_directory",
    "search_files",
    # Implementation functions (for testing)
    "_read_file_impl",
    "_write_file_impl",
    "_list_directory_impl",
    "_search_files_impl",
    # Security functions (for testing)
    "_validate_path",
    "_validate_path_within_allowed",
    "_detect_path_traversal_attempts",
    "_get_allowed_base_dirs",
]
