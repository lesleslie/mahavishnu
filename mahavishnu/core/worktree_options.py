"""WorktreeOptions input model for ``pool_route_execute(worktree=...)``.

Per C-8 (worktree isolation, REQ-010):

Grouping 4 fields into one Pydantic model keeps ``pool_route_execute``'s
arg count under ``max-args=10`` (currently 9 positional args after C-6's
``idempotency`` + C-8's ``worktree``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorktreeOptions(BaseModel):
    """Pydantic input model for ``pool_route_execute(worktree=...)``.

    Attributes:
        isolation: ``"host"`` (default — execute in the host's checkout)
            or ``"worktree"`` (create an isolated ``git worktree`` first).
        base_branch: Branch to fork from when ``isolation="worktree"``.
        ttl_seconds: Worktree lifetime cap (cleanup grace window).
        on_completion: What to do once the dispatch completes —
            ``"auto_merge"``, ``"discard"``, or ``"return_diff"`` (default).
    """

    model_config = ConfigDict(extra="forbid")

    isolation: Literal["host", "worktree"] = "host"
    base_branch: str = Field(default="main", min_length=1, max_length=255)
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    on_completion: Literal["auto_merge", "discard", "return_diff"] = "return_diff"


__all__ = ["WorktreeOptions"]