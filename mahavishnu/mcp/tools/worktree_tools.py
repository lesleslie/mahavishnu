"""
MCP tools for cross-repository worktree coordination.

Provides standardized worktree management across the entire ecosystem,
with safety mechanisms to prevent data loss.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

from ...core.app import MahavishnuApp

_SUPPORTED_ACTIONS = (
    "create",
    "remove",
    "list",
    "prune",
    "safety_status",
    "provider_health",
)


def _get_coordinator():
    """Get worktree coordinator instance."""
    app = MahavishnuApp.load()
    return app.worktree_coordinator


def _missing_coordinator_payload(action: str) -> dict[str, Any]:
    return {
        "success": False,
        "action": action,
        "error": "WorktreeCoordinator not initialized",
    }


def _missing_fields_payload(action: str, missing_fields: list[str]) -> dict[str, Any]:
    return {
        "success": False,
        "action": action,
        "error": f"Missing required fields for worktree action '{action}'",
        "missing_fields": missing_fields,
    }


def _unsupported_action_payload(action: str) -> dict[str, Any]:
    return {
        "success": False,
        "action": action,
        "error": f"Unsupported worktree action: {action}",
        "supported_actions": list(_SUPPORTED_ACTIONS),
    }


async def worktree_manage(
    action: str,
    user_id: str,
    repo_nickname: str | None = None,
    branch: str | None = None,
    worktree_name: str | None = None,
    create_branch: bool = False,
    worktree_path: str | None = None,
    force: bool = False,
    force_reason: str | None = None,
) -> dict[str, Any]:
    """Manage worktrees through a consolidated action dispatcher."""
    normalized_action = action.strip().lower()
    coordinator = _get_coordinator()

    if not coordinator:
        return _missing_coordinator_payload(normalized_action)

    try:
        if normalized_action == "create":
            missing_fields = [
                field
                for field, value in (
                    ("repo_nickname", repo_nickname),
                    ("branch", branch),
                )
                if not value
            ]
            if missing_fields:
                return _missing_fields_payload(normalized_action, missing_fields)

            return await coordinator.create_worktree(
                repo_nickname=repo_nickname,
                branch=branch,
                worktree_name=worktree_name,
                create_branch=create_branch,
                user_id=user_id,
            )

        if normalized_action == "remove":
            missing_fields = [
                field
                for field, value in (
                    ("repo_nickname", repo_nickname),
                    ("worktree_path", worktree_path),
                )
                if not value
            ]
            if missing_fields:
                return _missing_fields_payload(normalized_action, missing_fields)

            return await coordinator.remove_worktree(
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                force=force,
                force_reason=force_reason,
                user_id=user_id,
            )

        if normalized_action == "list":
            return await coordinator.list_worktrees(repo_nickname=repo_nickname)

        if normalized_action == "prune":
            if not repo_nickname:
                return _missing_fields_payload(normalized_action, ["repo_nickname"])
            return await coordinator.prune_worktrees(repo_nickname)

        if normalized_action == "safety_status":
            missing_fields = [
                field
                for field, value in (
                    ("repo_nickname", repo_nickname),
                    ("worktree_path", worktree_path),
                )
                if not value
            ]
            if missing_fields:
                return _missing_fields_payload(normalized_action, missing_fields)

            return await coordinator.get_worktree_safety_status(
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
            )

        if normalized_action == "provider_health":
            return await coordinator.get_provider_health()

        return _unsupported_action_payload(normalized_action)
    except Exception as e:  # pragma: no cover - exercised by integration tests
        return {
            "success": False,
            "action": normalized_action,
            "error": str(e),
        }


def register_worktree_tools(mcp: FastMCP, app: Any = None) -> None:
    """Register consolidated and compatibility worktree tools with MCP."""
    del app

    mcp.tool()(worktree_manage)
