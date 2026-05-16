"""MCP tools for PyCharm IDE integration.

Provides 8 MCP tools for PyCharm IDE automation via the JetBrains MCP server.
Falls back to subprocess-based diagnostics when MCP is unavailable.

Transport Note:
    The JetBrains MCP server currently uses SSE transport, which may not work
    with native Claude Code builds. Configure it JetBrains MCP server with
    stdio transport when available. See: https://github.com/JetBrains
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# --- Subprocess fallbacks ---


def _fallback_diagnostics(file_path: str, errors_only: bool = False) -> list[dict[str, Any]]:
    """Fallback diagnostics using ruff when PyCharm MCP is unavailable."""
    cmd = ["ruff", "check", "--output-format", "json", file_path]
    if errors_only:
        cmd.append("--select")
        cmd.append("E,F")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            import json

            try:
                ruff_output = json.loads(result.stdout)
            except json.JSONDecodeError:
                return [{"message": result.stdout, "severity": "error"}]
            diagnostics = []
            for error in ruff_output:
                diagnostics.append(
                    {
                        "message": error.get("message", ""),
                        "severity": error.get("severity", "error").lower(),
                        "file": error.get("filename", file_path),
                        "line": error.get("line", None),
                        "column": error.get("column", None),
                        "code": error.get("code", ""),
                    }
                )
            return diagnostics
        return []
    except FileNotFoundError:
        return [{"message": "ruff not installed", "severity": "warning"}]
    except subprocess.TimeoutExpired:
        return [{"message": "ruff check timed out", "severity": "warning"}]


def _fallback_search(pattern: str, file_pattern: str | None = None) -> list[dict[str, Any]]:
    """Fallback search using grep when PyCharm MCP is unavailable."""
    results = []
    try:
        cmd = ["grep", "-rn", "-E", pattern]
        if file_pattern:
            cmd.extend(["--include", file_pattern])
        cmd.append(".")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        for line in proc.stdout.split("\n")[:100]:
            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    results.append(
                        {
                            "file_path": parts[0],
                            "line_number": int(parts[1]),
                            "column": 0,
                            "match_text": parts[2],
                        }
                    )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return results


# --- Tool registration ---


def register_pycharm_tools(mcp: FastMCP, app: Any = None) -> None:
    """Register PyCharm IDE MCP tools with the FastMCP server.

    Args:
        mcp: FastMCP server instance
        app: Optional MahavishnuApp instance for dependency injection
    """

    @mcp.tool()
    async def pycharm_health() -> dict[str, Any]:
        """Check PyCharm MCP connectivity and health status.

        Returns connection status and fallback availability.
        """
        # Try to reach JetBrains MCP server
        mcp_available = False
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    # Try a simple health check tool
                    try:
                        await asyncio.wait_for(
                            mcp_client.call_tool("jetbrains__health_check", {}),
                            timeout=10,
                        )
                        mcp_available = True
                    except Exception:
                        mcp_available = False
        except Exception:
            pass

        return {
            "status": "healthy" if mcp_available else "degraded",
            "mcp_available": mcp_available,
            "fallback_active": not mcp_available,
            "tools": [
                "pycharm_health",
                "pycharm_run_diagnostics",
                "pycharm_open_file",
                "pycharm_search_in_project",
                "pycharm_replace_in_file",
                "pycharm_reformat_file",
                "pycharm_refactor_symbol",
                "pycharm_list_problems",
            ],
            "message": (
                "PyCharm MCP server connected"
                if mcp_available
                else "PyCharm MCP unavailable, using subprocess fallbacks"
            ),
        }

    @mcp.tool()
    async def pycharm_run_diagnostics(
        file_path: str,
        errors_only: bool = False,
    ) -> dict[str, Any]:
        """Run diagnostics on a file using PyCharm's code inspection."""
        # Try MCP first
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool(
                            "jetbrains__get_file_problems",
                            {
                                "file_path": file_path,
                                "errors_only": errors_only,
                            },
                        ),
                        timeout=30,
                    )
                    return {
                        "source": "pycharm_mcp",
                        "file_path": file_path,
                        "problems": _extract_problems(result),
                    }
        except Exception as e:
            logger.debug(f"PyCharm MCP unavailable, using fallback: {e}")

        # Fallback to ruff
        diagnostics = _fallback_diagnostics(file_path, errors_only)
        return {
            "source": "ruff_fallback",
            "file_path": file_path,
            "problems": diagnostics,
            "fallback_active": True,
        }

    @mcp.tool()
    async def pycharm_open_file(file_path: str, line: int | None = None) -> dict[str, Any]:  # type: ignore[return]
        """Open a file in PyCharm editor, optionally at a specific line."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    args: dict[str, Any] = {"file_path": file_path}
                    if line:
                        args["line"] = line
                    await asyncio.wait_for(
                        mcp_client.call_tool("jetbrains__open_file", args),
                        timeout=15,
                    )
                    return {"source": "pycharm_mcp", "opened": True, "file_path": file_path}
        except Exception as e:
            logger.warning(f"Failed to open file in PyCharm: {e}")
            return {
                "source": "fallback",
                "opened": False,
                "error": str(e),
                "fallback_active": True,
            }

    @mcp.tool()
    async def pycharm_search_in_project(
        pattern: str,
        file_pattern: str | None = None,
    ) -> dict[str, Any]:
        """Search files in project using PyCharm's search index."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    args: dict[str, Any] = {"pattern": pattern}
                    if file_pattern:
                        args["file_pattern"] = file_pattern
                    result = await asyncio.wait_for(
                        mcp_client.call_tool("jetbrains__search_regex", args),
                        timeout=30,
                    )
                    return {"source": "pycharm_mcp", "results": result}
        except Exception as e:
            logger.debug(f"PyCharm MCP unavailable, using fallback search: {e}")

        results = _fallback_search(pattern, file_pattern)
        return {
            "source": "grep_fallback",
            "results": results,
            "fallback_active": True,
        }

    @mcp.tool()
    async def pycharm_replace_in_file(  # type: ignore[return]
        file_path: str,
        search_text: str,
        replace_text: str,
    ) -> dict[str, Any]:
        """Find and replace text in a file via PyCharm."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool(
                            "jetbrains__replace_text_in_file",
                            {
                                "file_path": file_path,
                                "search_text": search_text,
                                "replace_text": replace_text,
                            },
                        ),
                        timeout=30,
                    )
                    return {"source": "pycharm_mcp", "replaced": bool(result)}
        except Exception as e:
            logger.warning(f"Failed to replace in PyCharm: {e}")
            return {
                "source": "fallback",
                "replaced": False,
                "error": str(e),
                "fallback_active": True,
            }

    @mcp.tool()
    async def pycharm_reformat_file(file_path: str) -> dict[str, Any]:  # type: ignore[return]
        """Reformat a file using PyCharm's code formatter."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool("jetbrains__reformat_file", {"file_path": file_path}),
                        timeout=30,
                    )
                    return {"source": "pycharm_mcp", "reformatted": bool(result)}
        except Exception as e:
            logger.warning(f"Failed to reformat in PyCharm: {e}")
            return {
                "source": "fallback",
                "reformatted": False,
                "error": str(e),
                "fallback_active": True,
            }

    @mcp.tool()
    async def pycharm_refactor_symbol(  # type: ignore[return]
        symbol_name: str,
        new_name: str,
        scope: str = "project",
    ) -> dict[str, Any]:
        """Rename/refactor a symbol across project files via PyCharm."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool(
                            "jetbrains__refactor_symbol",
                            {
                                "symbol_name": symbol_name,
                                "new_name": new_name,
                                "scope": scope,
                            },
                        ),
                        timeout=30,
                    )
                    return {
                        "source": "pycharm_mcp",
                        "refactored": bool(result),
                    }
        except Exception as e:
            logger.warning(f"Failed to refactor in PyCharm: {e}")
            return {
                "source": "fallback",
                "refactored": False,
                "error": str(e),
                "fallback_active": True,
            }

    @mcp.tool()
    async def pycharm_list_problems(
        file_path: str,
        severity: str | None = None,
    ) -> dict[str, Any]:
        """List code inspections and problems for a file via PyCharm."""
        try:
            if app and hasattr(app, "worker_manager") and app.worker_manager:
                mcp_client = getattr(app.worker_manager, "mcp_client", None)
                if mcp_client:
                    args: dict[str, Any] = {"file_path": file_path}
                    if severity:
                        args["severity"] = severity
                    result = await asyncio.wait_for(
                        mcp_client.call_tool("jetbrains__list_problems", args),
                        timeout=30,
                    )
                    return {
                        "source": "pycharm_mcp",
                        "file_path": file_path,
                        "problems": _extract_problems(result),
                    }
        except Exception as e:
            logger.debug(f"PyCharm MCP unavailable, using fallback: {e}")

        errors_only = severity == "error" if severity else False
        diagnostics = _fallback_diagnostics(file_path, errors_only)
        return {
            "source": "ruff_fallback",
            "file_path": file_path,
            "problems": diagnostics,
            "fallback_active": True,
        }


def _extract_problems(result: Any) -> list[dict[str, Any]]:
    """Extract problems list from MCP tool result."""
    if result is None:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        if "problems" in result:
            return result["problems"]  # type: ignore[no-any-return]
        if "content" in result:
            content = result["content"]
            if isinstance(content, list):
                return content
    return [result] if result else []
