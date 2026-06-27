"""Workflow progress snapshots — Spec #10 (live-observe-presence-over-gate).

Workflows publish live progress snapshots instead of waiting at the gate.

This module owns two layers:

- ``ProgressSnapshot``: a frozen dataclass representing one observation
  of a workflow's progress (workflow_id, step, percent, message, ts).
- ``WorkflowProgressRecorder``: per-workflow buffer that records snapshots
  in-process so operators can poll via ``list_progress_snapshots``.

Substrate status: ``http_blocked (/workflows/<id>/progress-snapshots)``.
Until Workstream C ships the Dhara HTTP CRUD endpoint, ``_persister`` is
a TODO stub that always fails-soft — the in-process recorder remains
the source of truth and the substrate call degrades to a no-op. When
the endpoint ships, swap the stub for ``httpx.AsyncClient.post(...)``
to ``{dhara_base_url}/workflows/{workflow_id}/progress-snapshots``.

Architectural property (per the spec):
- Serverless-native: stateless MCP server, all state in Dhara.
- Snapshots are periodic state (cheap to query "what is this workflow
  doing right now?").
- Events (separate, in ``mahavishnu.core.events``) are facts; they live
  in a different table and are not handled here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressSnapshot:
    """One observation of a workflow's live progress.

    Attributes:
        workflow_id: The workflow this snapshot belongs to.
        step: Free-form step label (e.g. ``load_data``, ``transform``).
        percent: Integer 0-100 indicating completion of this step's
            containing phase. Strictly validated; out-of-range values
            raise ``ValueError`` at construction time.
        message: Human-readable status text.
        ts: Timestamp of the observation. Defaults to ``datetime.now(UTC)``.
            Must be timezone-aware (UTC).
    """

    workflow_id: str
    step: str
    percent: int
    message: str
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError(f"percent must be in 0..100, got {self.percent}")

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict for the substrate wire format."""
        return {
            "workflow_id": self.workflow_id,
            "step": self.step,
            "percent": self.percent,
            "message": self.message,
            "ts": self.ts.isoformat(),
        }


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class WorkflowProgressRecorder:
    """Per-workflow buffer of in-process progress snapshots.

    Thread-safe enough for asyncio: snapshots are appended under the caller's
    coroutine context; no locking is required when used from a single event
    loop, which is the only supported usage.
    """

    __slots__ = ("workflow_id", "_snapshots")

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self._snapshots: list[ProgressSnapshot] = []

    @property
    def snapshots(self) -> list[ProgressSnapshot]:
        """Return a copy of the recorded snapshots in insertion order."""
        return list(self._snapshots)

    def record(
        self,
        *,
        step: str,
        percent: int,
        message: str,
        ts: datetime | None = None,
    ) -> ProgressSnapshot:
        """Append a snapshot and return it.

        Args:
            step: Free-form step label.
            percent: 0-100; out-of-range raises ``ValueError``.
            message: Human-readable status text.
            ts: Optional explicit timestamp; defaults to ``datetime.now(UTC)``.

        Returns:
            The freshly recorded ``ProgressSnapshot`` instance.
        """
        snap = ProgressSnapshot(
            workflow_id=self.workflow_id,
            step=step,
            percent=percent,
            message=message,
            ts=ts if ts is not None else datetime.now(UTC),
        )
        self._snapshots.append(snap)
        return snap

    def latest(self) -> ProgressSnapshot | None:
        """Return the most recently recorded snapshot, or ``None``."""
        return self._snapshots[-1] if self._snapshots else None

    def clear(self) -> None:
        """Empty the buffer. ``workflow_id`` is preserved."""
        self._snapshots.clear()


# ---------------------------------------------------------------------------
# Module-level registry + substrate persister (TODO Workstream C)
# ---------------------------------------------------------------------------


_recorders: dict[str, WorkflowProgressRecorder] = {}
_recorders_lock = asyncio.Lock()


async def _persister(snapshot: ProgressSnapshot) -> None:
    """Stub for the Dhara HTTP CRUD call.

    TODO(Workstream C): when substrate endpoint
    ``/workflows/<id>/progress-snapshots`` is unblocked, replace this
    body with a real ``httpx.AsyncClient.post(...)`` call. Until then,
    it logs at DEBUG and returns — the in-process recorder remains the
    authoritative store for operator queries.
    """
    logger.debug(
        "progress snapshot substrate call skipped (http_blocked)",
        extra={"workflow_id": snapshot.workflow_id, "step": snapshot.step},
    )


def _get_or_create_recorder(workflow_id: str) -> WorkflowProgressRecorder:
    """Return the recorder for ``workflow_id``, creating it if needed.

    Not thread-safe across processes — module-level state only. Acceptable
    because all recorder access happens inside the asyncio event loop.
    """
    recorder = _recorders.get(workflow_id)
    if recorder is None:
        recorder = WorkflowProgressRecorder(workflow_id=workflow_id)
        _recorders[workflow_id] = recorder
    return recorder


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def record_progress_snapshot(
    *,
    workflow_id: str,
    step: str,
    percent: int,
    message: str,
    ts: datetime | None = None,
) -> ProgressSnapshot:
    """Record a snapshot in-process and (best-effort) persist to substrate.

    Args:
        workflow_id: The workflow this snapshot belongs to.
        step: Free-form step label.
        percent: 0-100; out-of-range raises ``ValueError``.
        message: Human-readable status text.
        ts: Optional explicit timestamp; defaults to ``datetime.now(UTC)``.

    Returns:
        The freshly recorded ``ProgressSnapshot`` instance.

    Note:
        Substrate failures are swallowed (logged at WARNING). The
        in-process recorder is the source of truth for operator queries;
        the substrate is observational, not blocking (per spec §Error
        Handling).
    """
    recorder = _get_or_create_recorder(workflow_id)
    snap = recorder.record(step=step, percent=percent, message=message, ts=ts)
    try:
        await _persister(snap)
    except Exception as exc:  # substrate is observational, not blocking
        logger.warning(
            "progress snapshot substrate persister failed",
            extra={
                "workflow_id": workflow_id,
                "step": step,
                "error": str(exc),
            },
        )
    return snap


async def list_progress_snapshots(workflow_id: str) -> list[ProgressSnapshot]:
    """Return all recorded snapshots for ``workflow_id`` in insertion order.

    Returns an empty list if the workflow has never recorded a snapshot.
    """
    recorder = _recorders.get(workflow_id)
    if recorder is None:
        return []
    return recorder.snapshots


__all__ = [
    "ProgressSnapshot",
    "WorkflowProgressRecorder",
    "record_progress_snapshot",
    "list_progress_snapshots",
]
