"""ripgrep-backed search tool for the Bodai crow HTTP server.

Exposes ``rg_search(pattern, settings, ...)`` returning matches with
``file``, ``line_number``, ``column``, and ``match`` fields. Format may be
``content`` (default — one entry per match line), ``files_with_matches``
(file paths only), or ``json`` (per-line raw JSON dict from rg).

All searches run inside the workspace — paths are validated through
``resolve_workspace_path`` before any subprocess is launched. When ripgrep
is unavailable (no ``rg`` on PATH), this module raises ``RuntimeError`` so
the orchestrator can route to a Python fallback (out of scope here).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import TYPE_CHECKING, Literal, TypedDict

from mahavishnu.mcp.crow.path_security import resolve_workspace_path

if TYPE_CHECKING:
    from pathlib import Path

    from mahavishnu.mcp.crow.settings import CrowSettings

Format = Literal["content", "files_with_matches", "json"]


class RgMatch(TypedDict):
    file: str
    line_number: int
    column: int
    match: str


class RgResult(TypedDict):
    engine: str
    pattern: str
    path: str
    format: str
    matches: list[RgMatch] | list[str] | list[dict[str, object]]
    total_found: int
    truncated: bool


def _build_args(
    pattern: str,
    root: Path,
    include: str | None,
    format: Format,
    case_sensitive: bool,
    fixed_string: bool,
    rg_path: Path,
    line_numbers: bool,
) -> list[str]:
    args: list[str] = [str(rg_path)]
    if not case_sensitive:
        args.append("-i")
    if fixed_string:
        args.append("-F")
    if include:
        args.extend(["-g", include])
    if format == "files_with_matches":
        args.append("-l")
    elif format == "json":
        args.append("--json")
    args.append("-n")
    if line_numbers:
        args.append("--column")
    args.extend(["--", pattern, str(root)])
    return args


async def rg_search(
    pattern: str,
    settings: CrowSettings,
    path: str = ".",
    include: str | None = None,
    format: Format = "content",
    max_matches: int | None = None,
    case_sensitive: bool = True,
    fixed_string: bool = False,
    line_numbers: bool = True,
) -> RgResult:
    """Search for ``pattern`` under ``path`` using ripgrep.

    Raises:
        PermissionError: ``path`` resolves outside the workspace root.
        RuntimeError: ripgrep is unavailable OR exited with status 2
            (malformed regex, unreadable file, permission denied).
    """
    if settings.rg_path is None:
        raise RuntimeError("ripgrep (rg) is not available on PATH")
    root = resolve_workspace_path(path, settings.workspace_root)
    limit = max_matches if max_matches is not None else settings.max_grep_matches
    args = _build_args(
        pattern=pattern,
        root=root,
        include=include,
        format=format,
        case_sensitive=case_sensitive,
        fixed_string=fixed_string,
        rg_path=settings.rg_path,
        line_numbers=line_numbers,
    )
    proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=30.0)
    # Exit codes: 0 = matches, 1 = no matches, 2 = real error.
    if proc.returncode not in (0, 1):
        stderr = proc.stderr.decode(errors="replace")[:500]
        raise RuntimeError(f"ripgrep failed (rc={proc.returncode}): {stderr}")
    stdout = proc.stdout.decode(errors="replace")
    if format == "files_with_matches":
        files = [line for line in stdout.splitlines() if line]
        truncated = len(files) > limit
        capped = files[:limit]
        return RgResult(
            engine="ripgrep",
            pattern=pattern,
            path=str(root),
            format=format,
            matches=capped,
            total_found=len(capped),
            truncated=truncated,
        )
    if format == "json":
        matches: list[dict[str, object]] = []
        for line in stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "match":
                continue
            matches.append(obj)
        truncated = len(matches) > limit
        capped = matches[:limit]
        return RgResult(
            engine="ripgrep",
            pattern=pattern,
            path=str(root),
            format=format,
            matches=capped,
            total_found=len(capped),
            truncated=truncated,
        )
    matches_list: list[RgMatch] = []
    for line in stdout.splitlines():
        # rg default: <file>:<line>:<col>:<text>  (col may be omitted with -F)
        parts = line.split(":", 3)
        if len(parts) < 3:
            continue
        try:
            ln = int(parts[1])
            col = int(parts[2]) if line_numbers and len(parts) >= 4 else 0
        except ValueError:
            continue
        match_text = parts[3] if len(parts) >= 4 else parts[-1]
        matches_list.append(RgMatch(file=parts[0], line_number=ln, column=col, match=match_text))
    truncated = len(matches_list) > limit
    capped = matches_list[:limit]
    return RgResult(
        engine="ripgrep",
        pattern=pattern,
        path=str(root),
        format=format,
        matches=capped,
        total_found=len(capped),
        truncated=truncated,
    )


def _tool_decorator(server):
    return server.fastmcp.tool if hasattr(server, "fastmcp") else server.tool


def register(server, settings: CrowSettings) -> None:
    """Register the rg_search tool on ``server``."""
    deco = _tool_decorator(server)

    @deco()
    async def rg_search(
        pattern: str,
        path: str = ".",
        include: str | None = None,
        format: str = "content",
        max_matches: int | None = None,
        case_sensitive: bool = True,
        fixed_string: bool = False,
        line_numbers: bool = True,
    ) -> RgResult:
        """(HTTP, for pool workers and CLI) - ripgrep-backed search."""
        return await _rg_search_impl(
            pattern,
            settings,
            path,
            include,
            format,
            max_matches,
            case_sensitive,
            fixed_string,
            line_numbers,
        )


_rg_search_impl = rg_search


__all__ = ["rg_search", "RgMatch", "RgResult", "Format", "register"]
