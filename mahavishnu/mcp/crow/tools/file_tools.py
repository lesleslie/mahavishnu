"""Native file tools for the Bodai crow HTTP MCP server.

Five tools, each gated by ``resolve_workspace_path``:

- ``read_file(path, settings, offset, limit, encoding)`` — paginated read with binary detection.
- ``write_file(path, content, settings, dry_run)`` — atomic write preserving mode.
- ``list_directory(path, settings, include_hidden, max_entries)`` — directory listing with hidden/skip-dir filtering.
- ``stat(path, settings)`` — file metadata (size, mtime, type).
- ``delete_file(path, settings, recursive)`` — file deletion with directory guard.

All paths are validated through ``resolve_workspace_path`` before any
syscall. Binary detection uses an 8 KiB header sniff (any NUL byte marks
the file as binary). Writes use ``tempfile.mkstemp`` + ``os.replace`` for
crash-safety; the original file is left untouched if anything raises.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypedDict

import aiofiles

from mahavishnu.mcp.crow.path_security import resolve_workspace_path
from mahavishnu.mcp.crow.settings import CrowSettings

_ALWAYS_SKIP = frozenset(
    {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}
)


class ReadResult(TypedDict):
    content: str
    line_start: int
    line_end: int
    total_lines: int
    truncated: bool


class WriteResult(TypedDict):
    written: bool
    path: str
    bytes: int
    lines: int


class DirectoryEntry(TypedDict):
    name: str
    path: str
    type: str
    size_bytes: int


class ListDirectoryResult(TypedDict):
    path: str
    entries: list[DirectoryEntry]
    count: int
    truncated: bool


class StatResult(TypedDict):
    path: str
    is_file: bool
    is_dir: bool
    size_bytes: int
    modified_epoch: float
    mode: int


class DeleteResult(TypedDict):
    deleted: bool
    path: str


async def read_file(
    file_path: str,
    settings: CrowSettings,
    offset: int = 0,
    limit: int | None = None,
    encoding: str = "utf-8",
) -> ReadResult:
    """Read file content with optional line-range pagination."""
    path = resolve_workspace_path(file_path, settings.workspace_root)
    # Binary detection: any NUL byte in the first 8 KiB marks file as binary.
    async with aiofiles.open(path, mode="rb") as fb:
        header = await fb.read(8192)
    if b"\x00" in header:
        raise ValueError(f"binary file: {path}")
    async with aiofiles.open(path, encoding=encoding, errors="replace") as f:
        text = await f.read()
    all_lines = text.splitlines(keepends=True)
    total = len(all_lines)
    start = offset
    end = total if limit is None else min(offset + limit, total)
    selected = all_lines[start:end]
    return ReadResult(
        content="".join(selected),
        line_start=start + 1,
        line_end=end,
        total_lines=total,
        truncated=(end < total),
    )


async def write_file(
    file_path: str,
    content: str,
    settings: CrowSettings,
    dry_run: bool = False,
) -> WriteResult:
    """Write content to ``file_path`` atomically, preserving mode.

    The original file is left intact if any step raises (tempfile creation,
    write, chmod, or replace). Returns ``written=False`` when ``dry_run``.
    """
    path = resolve_workspace_path(file_path, settings.workspace_root)
    lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    byte_count = len(content.encode("utf-8"))
    if dry_run:
        return WriteResult(
            written=False, path=str(path), bytes=byte_count, lines=lines
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode if path.exists() else None
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".crow.", suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        async with aiofiles.open(tmp_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        if existing_mode is not None:
            os.chmod(tmp_path, existing_mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return WriteResult(
        written=True, path=str(path), bytes=byte_count, lines=lines
    )


async def list_directory(
    path: str,
    settings: CrowSettings,
    include_hidden: bool = False,
    max_entries: int | None = None,
) -> ListDirectoryResult:
    """List a directory's immediate children, skipping noise dirs."""
    root = resolve_workspace_path(path, settings.workspace_root)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    limit = max_entries if max_entries is not None else settings.max_glob_results
    entries: list[DirectoryEntry] = []
    truncated = False
    try:
        children = list(root.iterdir())
    except PermissionError as exc:
        raise PermissionError(f"cannot list directory {root}: {exc}") from exc
    for child in children:
        name = child.name
        if not include_hidden and name.startswith("."):
            continue
        if name in _ALWAYS_SKIP:
            continue
        try:
            stat_result = child.stat()
        except OSError:
            continue
        entry_type = "dir" if child.is_dir() else "file"
        entries.append(
            DirectoryEntry(
                name=name,
                path=str(child),
                type=entry_type,
                size_bytes=stat_result.st_size if entry_type == "file" else 0,
            )
        )
        if len(entries) >= limit:
            truncated = True
            break
    return ListDirectoryResult(
        path=str(root),
        entries=sorted(entries, key=lambda e: e["name"]),
        count=len(entries),
        truncated=truncated,
    )


async def stat(file_path: str, settings: CrowSettings) -> StatResult:
    """Return metadata for a file or directory."""
    path = resolve_workspace_path(file_path, settings.workspace_root)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")
    s = path.stat()
    return StatResult(
        path=str(path),
        is_file=path.is_file(),
        is_dir=path.is_dir(),
        size_bytes=s.st_size,
        modified_epoch=s.st_mtime,
        mode=s.st_mode,
    )


async def delete_file(
    file_path: str,
    settings: CrowSettings,
    recursive: bool = False,
) -> DeleteResult:
    """Delete a file. Refuses to delete directories unless ``recursive``."""
    path = resolve_workspace_path(file_path, settings.workspace_root)
    if not path.exists():
        return DeleteResult(deleted=False, path=str(path))
    if path.is_dir() and not recursive:
        raise ValueError(
            f"refusing to delete directory without recursive=True: {path}"
        )
    if path.is_dir() and recursive:
        import shutil as _shutil

        _shutil.rmtree(path)
        return DeleteResult(deleted=True, path=str(path))
    path.unlink()
    return DeleteResult(deleted=True, path=str(path))


def _tool_decorator(server):
    return server.fastmcp.tool if hasattr(server, "fastmcp") else server.tool


def register(server, settings: CrowSettings) -> None:
    """Register the five file tools on ``server``."""
    deco = _tool_decorator(server)

    @deco()
    async def read_file(
        file_path: str,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """(HTTP, for pool workers and CLI) - Read file with pagination."""
        return await _read_impl(file_path, settings, offset, limit, encoding)

    @deco()
    async def write_file(
        file_path: str, content: str, dry_run: bool = False
    ) -> WriteResult:
        """(HTTP, for pool workers and CLI) - Atomic write preserving mode."""
        return await _write_impl(file_path, content, settings, dry_run)

    @deco()
    async def list_directory(
        path: str,
        include_hidden: bool = False,
        max_entries: int | None = None,
    ) -> ListDirectoryResult:
        """(HTTP, for pool workers and CLI) - List directory contents."""
        return await _list_directory_impl(
            path, settings, include_hidden, max_entries
        )

    @deco()
    async def stat(file_path: str) -> StatResult:
        """(HTTP, for pool workers and CLI) - File metadata."""
        return await _stat_impl(file_path, settings)

    @deco()
    async def delete_file(
        file_path: str, recursive: bool = False
    ) -> DeleteResult:
        """(HTTP, for pool workers and CLI) - Delete file or directory."""
        return await _delete_file_impl(file_path, settings, recursive)


# Underscore-prefixed aliases used by register() above. They mirror the
# public functions; the public names are the canonical exports for
# direct (non-MCP) callers.
_read_impl = read_file
_write_impl = write_file
_list_directory_impl = list_directory
_stat_impl = stat
_delete_file_impl = delete_file


__all__ = [
    "read_file",
    "write_file",
    "list_directory",
    "stat",
    "delete_file",
    "ReadResult",
    "WriteResult",
    "ListDirectoryResult",
    "StatResult",
    "DeleteResult",
    "register",
]