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


_ACTION_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "create": ("repo_nickname", "branch"),
    "remove": ("repo_nickname", "worktree_path"),
    "prune": ("repo_nickname",),
    "safety_status": ("repo_nickname", "worktree_path"),
}


def _check_required_fields(action: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    required = _ACTION_REQUIRED_FIELDS.get(action, ())
    missing = [f for f in required if not fields.get(f)]
    return _missing_fields_payload(action, missing) if missing else None


async def _dispatch_worktree_action(
    coordinator: Any,
    action: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if action == "create":
        return await coordinator.create_worktree(
            repo_nickname=fields["repo_nickname"],
            branch=fields["branch"],
            worktree_name=fields.get("worktree_name"),
            create_branch=fields.get("create_branch", False),
            user_id=fields["user_id"],
        )
    if action == "remove":
        return await coordinator.remove_worktree(
            repo_nickname=fields["repo_nickname"],
            worktree_path=fields["worktree_path"],
            force=fields.get("force", False),
            force_reason=fields.get("force_reason"),
            user_id=fields["user_id"],
        )
    if action == "list":
        return await coordinator.list_worktrees(repo_nickname=fields.get("repo_nickname"))
    if action == "prune":
        return await coordinator.prune_worktrees(fields["repo_nickname"])
    if action == "safety_status":
        return await coordinator.get_worktree_safety_status(
            repo_nickname=fields["repo_nickname"],
            worktree_path=fields["worktree_path"],
        )
    if action == "provider_health":
        return await coordinator.get_provider_health()
    return _unsupported_action_payload(action)


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

    fields = {
        "user_id": user_id,
        "repo_nickname": repo_nickname,
        "branch": branch,
        "worktree_name": worktree_name,
        "create_branch": create_branch,
        "worktree_path": worktree_path,
        "force": force,
        "force_reason": force_reason,
    }

    error = _check_required_fields(normalized_action, fields)
    if error:
        return error

    try:
        return await _dispatch_worktree_action(coordinator, normalized_action, fields)
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
