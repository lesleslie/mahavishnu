"""TypedDicts for the plan_index MCP surface.

All public TypedDicts are TypedDict (not dict[str, Any]) per the
CLAUDE.md "no Any" hard rule. Conditional fields use NotRequired[T].
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

# 4 distinct tripwire states. v0 had "ok" duplicated; fixed.
TripwireState = Literal[
    "ok", "no_recent_edits", "no_recent_reads", "review_cadence_lagging"
]


class RebuildErrorCtx(TypedDict, total=False):
    """Structured context for PlanRebuildErrorDict.

    NEVER carries raw path or repo. Use path_hash = sha256(path).hexdigest()[:12].
    """
    plan_id: NotRequired[str]
    path_hash: NotRequired[str]
    op: NotRequired[str]
    attempt: NotRequired[int]


class PlanRecordDict(TypedDict):
    plan_id: str
    path: str
    title: str
    status: str
    role: str
    topic: str
    date: str
    last_reviewed: str
    superseded_by: NotRequired[str]
    blocks_on: list[str]
    sha: str
    repo: str
    lifecycle_state: NotRequired[str]
    updated_at_ms: int


class PlanVitalsDict(TypedDict):
    total: int
    by_status: dict[str, int]
    by_role: dict[str, int]
    by_topic_top10: list[tuple[str, int]]
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    oldest_active_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    tripwire: TripwireState


class PlanRebuildStatusDict(TypedDict):
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    lock_held_by: NotRequired[str]
    lock_age_ms: NotRequired[int]
    stale: bool


class PlanRebuildErrorDict(TypedDict):
    ts_ms: int
    op: str
    err: str
    ctx: RebuildErrorCtx


class PlanListResultDict(TypedDict):
    plans: list[PlanRecordDict]
    total: int
    cached_at_ms: NotRequired[int]
    status: Literal["ok", "degraded"]


class PlanDegradedDict(TypedDict):
    """Discriminated by absence of the 'plans' field. No 'status' literal."""

    reason: str
    cached_at_ms: NotRequired[int]


__all__ = [
    "PlanDegradedDict",
    "PlanListResultDict",
    "PlanRebuildErrorDict",
    "PlanRebuildStatusDict",
    "PlanRecordDict",
    "PlanVitalsDict",
    "RebuildErrorCtx",
    "TripwireState",
]
