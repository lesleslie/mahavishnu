"""Repository and runtime status helpers for Mahavishnu.

This module keeps repo/role lookup and a few app-level health/status helpers
out of the composition root so `MahavishnuApp` can stay focused on wiring.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from monitoring.metrics import (
    mahavishnu_active_workflows,
    mahavishnu_workflow_concurrency_utilization,
    mahavishnu_workflow_queue_depth,
)

from .errors import ValidationError
from .permissions import Permission
from .repo_nicknames import get_repo_nicknames


def validate_path(path_str: str, allowed_base_paths: list[str] | None = None) -> Path:
    """Validate a path to prevent directory traversal attacks."""
    path = Path(path_str)
    normalized_path = str(path_str).replace("\\", "/")

    if (
        ".." in path.parts
        or normalized_path.startswith("../")
        or "/../" in normalized_path
        or normalized_path.endswith("/..")
        or "..\\" in path_str
        or "\\.." in path_str
    ):
        raise ValidationError(
            message=f"Invalid path contains directory traversal: {path_str}",
            details={"path": path_str, "suggestion": "Remove any '..' sequences from path"},
        )

    abs_path = path.expanduser().resolve()
    allowed_paths = allowed_base_paths or [str(Path.cwd()), Path().home().as_posix()]
    is_allowed = False
    for allowed_base in allowed_paths:
        try:
            abs_path.relative_to(Path(allowed_base).expanduser().resolve())
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        raise ValidationError(
            message=f"Path is outside allowed directory: {path_str}",
            details={
                "path": path_str,
                "allowed_paths": allowed_paths,
                "suggestion": "Ensure path is within allowed boundaries",
            },
        )

    return abs_path


def persist_workflow_start(app: Any, execution_id: str, workflow_name: str, metadata: dict) -> None:
    """Fire-and-forget: record workflow start in Dhara."""
    if app._dhara_state is None:
        return
    app._dhara_state.schedule_put(
        f"workflow/v1/{execution_id}",
        {
            "execution_id": execution_id,
            "workflow_name": workflow_name,
            "status": "running",
            "metadata": metadata,
        },
    )


def persist_workflow_end(
    app: Any, execution_id: str, workflow_name: str, status: str, error: str | None = None
) -> None:
    """Fire-and-forget: record workflow completion/failure in Dhara."""
    if app._dhara_state is None:
        return
    app._dhara_state.schedule_put(
        f"workflow/v1/{execution_id}",
        {
            "execution_id": execution_id,
            "workflow_name": workflow_name,
            "status": status,
            "end_time": datetime.now(UTC).isoformat(),
            "error": error,
        },
    )


def _filter_repos_by_criteria(
    repos: list[dict], tag: str | None, role: str | None
) -> list[str]:
    if tag:
        return [r["path"] for r in repos if tag in r.get("tags", [])]
    if role:
        return [r["path"] for r in repos if r.get("role") == role]
    return [r["path"] for r in repos]


def _collect_valid_repo(
    app: Any, repo_path: str, user_id: str | None, logger: Any
) -> str | None:
    try:
        validated_path = validate_path(repo_path, app.config.allowed_repo_paths)
        if not validated_path.exists():
            logger.warning("Repository path does not exist: %s", validated_path)
            return None
        if user_id and not check_user_repo_permission(app, user_id, str(validated_path)):
            return None
        return str(validated_path)
    except ValidationError as e:
        logger.warning("Invalid repository path: %s - %s", repo_path, e.message)
        return None


def get_repos(
    app: Any, tag: str | None = None, role: str | None = None, user_id: str | None = None
) -> list[str]:
    """Get repository paths based on tag, role, or return all."""
    logger = __import__("logging").getLogger(__name__)

    if tag and not tag.replace("-", "").replace("_", "").isalnum():
        raise ValidationError(
            message=f"Invalid tag: {tag}",
            details={"tag": tag, "suggestion": "Tags must be alphanumeric with hyphens/underscores"},
        )

    if role:
        valid_roles = [r["name"] for r in get_roles(app)]
        if role not in valid_roles:
            raise ValidationError(
                message=f"Invalid role: {role}",
                details={"role": role, "valid_roles": valid_roles,
                         "suggestion": f"Use one of: {', '.join(valid_roles)}"},
            )

    repos = app.repos_config.get("repos", [])
    filtered_repos = _filter_repos_by_criteria(repos, tag, role)
    return [
        path for repo_path in filtered_repos
        if (path := _collect_valid_repo(app, repo_path, user_id, logger)) is not None
    ]


def check_user_repo_permission(app: Any, user_id: str, repo_path: str) -> bool:
    """Check if user has read permission for repository."""
    try:
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    app.rbac_manager.check_permission(user_id, repo_path, Permission.READ_REPO),
                )
                return future.result(timeout=5.0)
        except RuntimeError:
            return asyncio.run(
                app.rbac_manager.check_permission(user_id, repo_path, Permission.READ_REPO)
            )
    except Exception:
        return True


def get_all_repos(app: Any) -> list[dict[str, Any]]:
    return app.repos_config.get("repos", [])


def get_all_repo_paths(app: Any) -> list[str]:
    return [repo["path"] for repo in app.repos_config.get("repos", [])]


def get_roles(app: Any) -> list[dict[str, Any]]:
    return getattr(app, "roles_config", app.repos_config.get("roles", []))


def get_role_by_name(app: Any, role_name: str) -> dict[str, Any] | None:
    for role in get_roles(app):
        if role.get("name") == role_name:
            return role
    return None


def get_repos_by_role(app: Any, role_name: str) -> list[dict[str, Any]]:
    valid_roles = [r["name"] for r in get_roles(app)]
    if role_name not in valid_roles:
        raise ValidationError(
            message=f"Invalid role: {role_name}",
            details={
                "role": role_name,
                "valid_roles": valid_roles,
                "suggestion": f"Use one of: {', '.join(valid_roles)}",
            },
        )
    return [repo for repo in app.repos_config.get("repos", []) if repo.get("role") == role_name]


def get_all_nicknames(app: Any) -> dict[str, str]:
    nicknames: dict[str, str] = {}
    for repo in app.repos_config.get("repos", []):
        for nickname in get_repo_nicknames(repo):
            nicknames[nickname] = repo.get("name", repo.get("path", ""))
    return nicknames


async def is_healthy(app: Any) -> bool:
    if not app.adapters:
        return False

    for adapter in app.adapters.values():
        try:
            health = await adapter.get_health()
            if health.get("status") != "healthy":
                return False
        except Exception:
            return False

    return True


async def get_active_workflows(app: Any) -> list[str]:
    from .workflow_state import WorkflowStatus

    workflows = await app.workflow_state_manager.list_workflows(
        status=WorkflowStatus.RUNNING,
        limit=1000,
    )
    return [w.get("id", "") for w in workflows if w.get("id")]


def update_workflow_runtime_gauges(app: Any) -> None:
    active_count = len(app.active_workflows)
    max_concurrency = max(app.config.max_concurrent_workflows, 1)

    mahavishnu_active_workflows.labels(service="mahavishnu").set(active_count)
    mahavishnu_workflow_queue_depth.labels(service="mahavishnu").set(app.workflow_queue.qsize())
    mahavishnu_workflow_concurrency_utilization.labels(service="mahavishnu").set(
        active_count / max_concurrency
    )
