from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, Protocol

from mahavishnu.distill.schema import WORKFLOW_RUN_STATUSES

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class _ConnLike(Protocol):
    def execute(self, sql: str, params: list[Any] | None = ...) -> Any: ...


@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str
    repo_path: str
    adapter: str
    task_type: str
    started_at: datetime
    session_id: str | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "completed"
    error_summary: str | None = field(default=None)

    def __post_init__(self) -> None:
        if self.status not in WORKFLOW_RUN_STATUSES:
            raise ValueError(
                f"WorkflowRun.status={self.status!r} is not one of {sorted(WORKFLOW_RUN_STATUSES)}"
            )


def report_run(conn: _ConnLike, run: WorkflowRun) -> bool:

    started_at_str = _isoformat(run.started_at)
    completed_at_str = _isoformat(run.completed_at) if run.completed_at is not None else None

    conn.execute(
        """
        DELETE FROM mahavishnu_workflow_runs
        WHERE workflow_id = ? AND started_at = ?
        """,
        [run.workflow_id, started_at_str],
    )
    conn.execute(
        """
        INSERT INTO mahavishnu_workflow_runs
            (workflow_id, session_id, repo_path, status, started_at,
             completed_at, duration_ms, adapter, task_type, error_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run.workflow_id,
            run.session_id,
            run.repo_path,
            run.status,
            started_at_str,
            completed_at_str,
            run.duration_ms,
            run.adapter,
            run.task_type,
            run.error_summary,
        ],
    )
    return True


def safe_report_run(conn: _ConnLike, run: WorkflowRun) -> bool:
    try:
        return report_run(conn, run)
    except Exception as exc:  # noqa: BLE001 — telemetry is best-effort
        logger.warning(
            "mahavishnu.distill.reporter: telemetry failed; workflow run NOT blocked",
            extra={
                "workflow_id": run.workflow_id,
                "session_id": run.session_id,
                "error": str(exc),
            },
        )
        return False


def _isoformat(dt: datetime) -> str:
    return dt.isoformat()


__all__ = [
    "WorkflowRun",
    "report_run",
    "safe_report_run",
]
