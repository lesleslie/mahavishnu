"""
MCP tools for cross-repository worktree coordination.

Provides standardized worktree management across the entire ecosystem,
with safety mechanisms to prevent data loss.
"""

from typing import Any

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
    """
    Create a worktree with ecosystem-wide safety checks.

    Validates repository existence, checks for blocking dependencies,
    and coordinates with worktree providers for actual creation.

    Args:
        user_id: User ID for authentication
        repo_nickname: Repository nickname (from repos.yaml)
        branch: Branch name
        worktree_name: Optional custom worktree name
        create_branch: Create branch if doesn't exist

    Returns:
        Creation result with worktree info and safety checks performed
    """
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
    """
    Remove a worktree with comprehensive safety validation.

    Performs multiple safety checks:
    - Uncommitted changes detection
    - Dependency validation
    - Path verification
    - Audit logging

    Args:
        user_id: User ID for authentication
        repo_nickname: Repository nickname
        worktree_path: Path to worktree directory
        force: Force removal (skip safety checks)
        force_reason: Required reason when force=True with uncommitted changes

    Returns:
        Removal result with safety check details
    """
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
    """
    List worktrees across ecosystem.

    Shows all worktrees across all repositories, or filter by specific repo.
    Includes status, branch info, and dependency relationships.

    Args:
        user_id: User ID for authentication
        repo_nickname: Optional repository filter

    Returns:
        List of worktrees with metadata
    """
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
    """
    Prune stale worktree references.

    Removes worktree references for branches that no longer exist,
    with validation to prevent accidental data loss.

    Args:
        user_id: User ID for authentication
        repo_nickname: Repository nickname

    Returns:
        Prune results with count of pruned worktrees
    """
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
    """
    Get safety status for a worktree before removal.

    Reports on:
    - Uncommitted changes
    - Active dependencies from other repos
    - Branch status (merged, deleted, etc.)
    - Worktree validity

    Args:
        user_id: User ID for authentication
        repo_nickname: Repository nickname
        worktree_path: Path to worktree

    Returns:
        Safety status with recommendations
    """
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
    """
    Get health status of all worktree providers.

    Shows which providers are healthy and available for use.

    Args:
        user_id: User ID for authentication

    Returns:
        Health status for all providers
    """
    coordinator = _get_coordinator()

    if not coordinator:
        return {
            "success": False,
            "error": "WorktreeCoordinator not initialized",
        }

    return await coordinator.get_provider_health()
