"""
MCP tools for cross-repository worktree coordination.

.. deprecated::
    This module is deprecated as of v0.5.0 and will be consolidated in v0.6.0.
    Individual tools will be replaced by a single `worktree_manage` tool with
    subcommand actions. See docs/reports/deprecation-migration.md for details.

Provides standardized worktree management across the entire ecosystem,
with safety mechanisms to prevent data loss.
"""

import warnings
from typing import Any

warnings.warn(
    "worktree_tools is deprecated since v0.5.0. Individual tools will be replaced "
    "by a consolidated worktree_manage tool in v0.6.0. See "
    "docs/reports/deprecation-migration.md for migration paths.",
    DeprecationWarning,
    stacklevel=2,
)

from fastmcp import FastMCP

from ...core.app import MahavishnuApp

mcp = FastMCP("Mahavishnu Worktree Management")


def _get_coordinator():
    """Get worktree coordinator instance."""
    app = MahavishnuApp.load()
    return app.worktree_coordinator


@mcp.tool()
async def create_ecosystem_worktree(
    user_id: str,
    repo_nickname: str,
    branch: str,
    worktree_name: str | None = None,
    create_branch: bool = False,
) -> dict[str, Any]:
    """Create a worktree with ecosystem-wide safety checks."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.create_worktree(
        repo_nickname=repo_nickname,
        branch=branch,
        worktree_name=worktree_name,
        create_branch=create_branch,
        user_id=user_id,
    )


@mcp.tool()
async def remove_ecosystem_worktree(
    user_id: str,
    repo_nickname: str,
    worktree_path: str,
    force: bool = False,
    force_reason: str | None = None,
) -> dict[str, Any]:
    """Remove a worktree with comprehensive safety validation."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.remove_worktree(
        repo_nickname=repo_nickname,
        worktree_path=worktree_path,
        force=force,
        force_reason=force_reason,
        user_id=user_id,
    )


@mcp.tool()
async def list_ecosystem_worktrees(
    user_id: str,
    repo_nickname: str | None = None,
) -> dict[str, Any]:
    """List worktrees across ecosystem."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.list_worktrees(repo_nickname=repo_nickname)


@mcp.tool()
async def prune_ecosystem_worktrees(
    user_id: str,
    repo_nickname: str,
) -> dict[str, Any]:
    """Prune stale worktree references."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.prune_worktrees(repo_nickname)


@mcp.tool()
async def get_worktree_safety_status(
    user_id: str,
    repo_nickname: str,
    worktree_path: str,
) -> dict[str, Any]:
    """Get safety status for a worktree before removal."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.get_worktree_safety_status(
        repo_nickname=repo_nickname,
        worktree_path=worktree_path,
    )


@mcp.tool()
async def get_worktree_provider_health(
    user_id: str,
) -> dict[str, Any]:
    """Get health status of all worktree providers."""
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.get_provider_health()
