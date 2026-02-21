"""File operation tools for Agno agents.

These tools provide safe file system operations that can be used by
Agno agents for reading, writing, and exploring code repositories.

All tools use Agno's native @tool decorator for seamless integration.
The actual implementations are separate functions for testing.
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


def _validate_path(path: str) -> Path:
    """Validate file path for security.

    Args:
        path: File path to validate

    Returns:
        Resolved Path object

    Raises:
        AgnoError: If path is invalid or unsafe
    """
    try:
        resolved = Path(path).resolve()

        # Check for blocked paths
        for blocked in BLOCKED_PATHS:
            if blocked in str(resolved):
                raise AgnoError(
                    f"Access denied: path contains blocked directory '{blocked}'",
                    error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                    details={"path": path, "blocked": blocked},
                )

        return resolved

    except Exception as e:
        if isinstance(e, AgnoError):
            raise
        raise AgnoError(
            f"Invalid path: {path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"path": path, "error": str(e)},
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
]
