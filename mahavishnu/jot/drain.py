"""Drain sub-plan (3): state machine, dispatch orchestration, retry, surfacing.

Single write path for all drain events. See spec §3.2, §4.2, §4.6, §6.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from oneiric.core.logging import get_logger

from mahavishnu.jot.errors import JotLogUnwritableError, JotValidationError
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.fold import DispatchState  # re-export target
from mahavishnu.jot.hlc import get_node, hlc_now, read_tail_hlc
from mahavishnu.jot.paths import log_path, node_path

log = get_logger(__name__)

# Re-export DispatchState (canonical location is fold.py to avoid cycle)
__all__ = ["DispatchState", "_append_event"]


# =============================================================================
# Per-op TypedDict schemas (spec §4.2 — exact values)
# =============================================================================


class DispatchCtx(TypedDict, total=False):
    workflow_id: str
    attempt: int
    pool_selector: str
    triggered_by: Literal["first", "auto", "manual"]
    dispatched_from: Literal["cli", "mcp", "slash"]
    started_at_ms: int


class DispatchDoneCtx(TypedDict, total=False):
    workflow_id: str
    summary: str
    commit_sha: str


class DispatchFailedCtx(TypedDict, total=False):
    workflow_id: str
    attempt: int
    error: str
    error_id: str
    retry_budget_exhausted: bool
    retry_after_seconds: int | None


class DeferCtx(TypedDict, total=False):
    until: int


class DeferExpiredCtx(TypedDict, total=False):
    defer_event_id: str | None


class DeleteCtx(TypedDict, total=False):
    reason: str | None


# Required keys per op. TypedDict total=False doesn't enforce required;
# we validate manually with a hard-fail list (spec §4.2 + R10 contract).
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "dispatch": ("workflow_id", "attempt", "pool_selector", "dispatched_from"),
    "dispatch_done": ("workflow_id", "summary"),
    "dispatch_failed": (
        "workflow_id", "attempt", "error", "error_id", "retry_budget_exhausted",
    ),
    "defer": ("until",),
    "defer_expired": (),
    "delete": (),
}

_INT_KEYS = ("attempt",)
_BOOL_KEYS = ("retry_budget_exhausted",)
_STR_KEYS = (
    "workflow_id", "summary", "commit_sha", "error", "error_id",
    "pool_selector", "dispatched_from", "triggered_by", "reason",
)
_LITERAL_KEYS = {
    "triggered_by": ("first", "auto", "manual"),
    "dispatched_from": ("cli", "mcp", "slash"),
}


# =============================================================================
# Helpers
# =============================================================================


def _now_ms() -> int:
    """Wall-clock in epoch ms. Project-utility; replaceable via clock fixture."""
    return int(time.time() * 1000)


def _validate_ctx(op: str, ctx: dict[str, object]) -> None:
    """Hard-fail validation against per-op TypedDict + required keys.

    Raises JotValidationError on missing required keys, wrong types,
    or unknown Literal values. Does NOT write to the log.
    """
    if op not in _REQUIRED_KEYS:
        raise JotValidationError(
            f"unknown op: {op!r}",
            field="op",
            error_id="ERROR_JOT_VALIDATION",
        )

    required = _REQUIRED_KEYS[op]
    missing = [k for k in required if k not in ctx]
    if missing:
        raise JotValidationError(
            f"missing required keys for op={op!r}: {missing}",
            field=f"ctx.{missing[0]}",
            error_id="ERROR_JOT_VALIDATION",
        )

    for k in _INT_KEYS:
        if k in ctx and (not isinstance(ctx[k], int) or isinstance(ctx[k], bool)):
            raise JotValidationError(
                f"{op}.{k} must be int, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k in _BOOL_KEYS:
        if k in ctx and not isinstance(ctx[k], bool):
            raise JotValidationError(
                f"{op}.{k} must be bool, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k in _STR_KEYS:
        if k in ctx and not isinstance(ctx[k], str):
            raise JotValidationError(
                f"{op}.{k} must be str, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k, allowed in _LITERAL_KEYS.items():
        if k in ctx and ctx[k] not in allowed:
            raise JotValidationError(
                f"{op}.{k} must be one of {allowed}, got {ctx[k]!r}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )


# Shared in-process asyncio lock. Both capture (sub-plan 1) and drain
# acquire this lock before writing to log.jsonl. Single-process assumption
# per spec §4.6 (cross-process atomicity is out of scope).
_append_lock = asyncio.Lock()


# =============================================================================
# Surfaces + Result types for MCP return shapes (TypedDicts, no Any)
# =============================================================================


class DrainPlanDict(TypedDict):
    query: str | None
    candidates: list[dict[str, Any]]    # JotSummaryDict-shaped items
    action_proposals: list["ActionProposalDict"]


class ActionProposalDict(TypedDict):
    handle: str
    suggested_action: Literal["dispatch", "defer", "done", "delete", "skip"]
    reason: str


class DispatchResultDict(TypedDict):
    handle: str
    workflow_id: str
    attempt: int
    status: Literal["in_flight", "queued"]
    dispatched_from: Literal["cli", "mcp", "slash"]


# =============================================================================
# Single write path
# =============================================================================


async def _append_event(op: str, ctx: dict[str, object]) -> None:
    """Validate ctx, auto-fill started_at_ms on dispatch, append to log.

    Single write path for all drain events. Validation happens BEFORE
    the lock is acquired, so malformed ctx cannot tie up the lock.
    Raises JotValidationError for malformed ctx (NOT written); raises
    JotLogUnwritableError on disk failure (also NOT written).

    On `op == "dispatch"`, if the caller did not pass `started_at_ms`,
    the wrapper stamps the current wall-clock so Tier-2 reconcilers can
    compute elapsed time without re-scanning events. The field is also
    validated against `DispatchCtx` after the fill, so a caller-provided
    invalid value still raises JotValidationError.
    """
    if op == "dispatch" and "started_at_ms" not in ctx:
        ctx = {**ctx, "started_at_ms": _now_ms()}

    _validate_ctx(op, ctx)

    node = get_node(node_path())
    last_hlc = read_tail_hlc(log_path())
    hlc = hlc_now(node, last_hlc)
    event = JotEvent(
        id="",  # filled by serialize from HLC + node
        op=op,  # type: ignore[arg-type]
        text="",  # drain events have no user-text payload
        ctx=ctx,
        hlc=hlc,
        created_ms=hlc.wall_ms,
    )

    path = log_path()
    line = serialize(event)

    async with _append_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(line)
        except OSError as exc:
            raise JotLogUnwritableError(
                f"cannot append to {path}: {exc}",
                path=str(path),
            ) from exc


# Re-export TypedDicts so callers can import from drain.py
__all__ = [
    "DispatchState", "_append_event",
    "DispatchCtx", "DispatchDoneCtx", "DispatchFailedCtx",
    "DeferCtx", "DeferExpiredCtx", "DeleteCtx",
    "DrainPlanDict", "ActionProposalDict", "DispatchResultDict",
]


@dataclass(frozen=True, slots=True)
class _Placeholder:
    """Marker for future modules to import. Will be removed in later tasks."""
    pass
