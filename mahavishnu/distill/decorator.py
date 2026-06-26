"""Workflow decorator for distilled workflows (Plan 5 Phase A.0).

The ``@mahavishnu_workflow(...)`` decorator marks an async function as a
Mahavishnu workflow entry point. The attached ``WorkflowSpec`` carries the
deployment metadata (intent, schedule, work pool, tags, repo_filter,
description) inline with the function — no sidecar YAML.

Used by:
- ``mahavishnu.distill.discovery`` to enumerate workflows from the
  filesystem (Phase A.0.2).
- The future ``mahavishnu workflow publish`` CLI (Phase C.2) to extract
  deployment metadata directly from the decorated function.
- The future ``prefect_adapter.create_deployment(flow_path=...)`` extension
  (Phase A.0.3) to import and register the function by dotted path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class WorkflowSpec:
    """Deployment metadata for a @mahavishnu_workflow-decorated function.

    Frozen so the spec cannot be mutated after attach; a workflow's
    declared intent, schedule, and tags must be stable for the audit
    trail.
    """

    intent: str
    schedule: str | None = None
    work_pool: str = "default"
    tags: tuple[str, ...] = ()
    repo_filter: str = "*"
    description: str = ""


def mahavishnu_workflow(
    *,
    intent: str,
    schedule: str | None = None,
    work_pool: str = "default",
    tags: tuple[str, ...] | list[str] = (),
    repo_filter: str = "*",
    description: str = "",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that marks an async function as a Mahavishnu workflow.

    Args:
        intent: Human-readable description of what the workflow does.
            Required — no default, no empty string. Used as the
            ``problem_pattern`` seed in the distilled_workflows row.
        schedule: Optional schedule expression (cron, interval, rrule).
        work_pool: Prefect work pool name (default ``"default"``).
        tags: Tags for organization/filtering. Accepted as tuple or list;
            stored as tuple for immutability.
        repo_filter: Glob restricting which repos this workflow applies to.
        description: Optional longer description (separate from intent).

    Returns:
        Decorator that attaches ``__mahavishnu_workflow_spec__`` to the
        wrapped function and returns it unchanged.
    """
    if not intent or not intent.strip():
        raise ValueError("mahavishnu_workflow: 'intent' is required and must be non-empty")

    normalized_tags = tuple(tags) if not isinstance(tags, tuple) else tags

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        spec = WorkflowSpec(
            intent=intent,
            schedule=schedule,
            work_pool=work_pool,
            tags=normalized_tags,
            repo_filter=repo_filter,
            description=description,
        )
        # Attribute assignment on a function is the standard Python hook
        # pattern (used by functools.wraps, pytest fixtures, etc.).
        fn.__mahavishnu_workflow_spec__ = spec  # type: ignore[attr-defined]
        return fn

    return decorator