
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from ulid import ULID

from mahavishnu.distill.reviewer import ReviewerIdentity

logger = logging.getLogger(__name__)


IMPORTANCE_FLOOR: float = 0.7


DEFAULT_EVIDENCE_THRESHOLD: int = 3


HEURISTIC_MODEL: str = "heuristic"


def _importance_from_evidence_workflows(evidence_count: int, project_count: int) -> float:
    import math


    score = math.log2(1 + max(0, int(evidence_count))) / 4.0


    project_count = max(0, int(project_count))
    if project_count == 1:
        score = min(score + 0.1, 1.0)
    elif project_count > 4:
        score = max(score - 0.05, IMPORTANCE_FLOOR)
    return max(IMPORTANCE_FLOOR, min(score, 1.0))


class _ConnLike(Protocol):
    def execute(self, sql: str, params: list[Any] | None = ...) -> Any: ...


def _find_candidate_sessions(
    conn: _ConnLike,
    *,
    evidence_threshold: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.session_id AS session_id,
            COUNT(DISTINCT c.id) AS tool_call_count,
            COUNT(DISTINCT w.workflow_id) AS successful_workflow_runs,
            MIN(c.project) AS project
        FROM conversations_v2 c
        LEFT JOIN mahavishnu_workflow_runs w
               ON w.session_id = c.session_id
        WHERE c.source_type = 'mahavishnu_workflow'
        GROUP BY c.session_id
        HAVING COUNT(DISTINCT c.id) >= ?
        ORDER BY tool_call_count DESC, successful_workflow_runs DESC
        LIMIT ?
        """,
        [int(evidence_threshold), int(limit)],
    ).fetchall()

    columns = ["session_id", "tool_call_count", "successful_workflow_runs", "project"]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _synthesize_candidate(conn: _ConnLike, session_id: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT COUNT(*) AS n, MIN(project) AS project
        FROM conversations_v2
        WHERE session_id = ? AND source_type = 'mahavishnu_workflow'
        """,
        [session_id],
    ).fetchall()
    if not rows:

        raise ValueError(f"no conversations_v2 rows for session_id={session_id!r}")
    n = int(rows[0][0])
    project = rows[0][1] or "unknown"
    project_count = 1 if project and project != "unknown" else 0
    importance = _importance_from_evidence_workflows(n, project_count)
    return {
        "evidence_count": n,
        "project": project,
        "project_count": project_count,
        "importance_score": importance,
        "problem_pattern": (
            f"Session {session_id}: {n} workflow tool calls in project "
            f"{project} — heuristic pattern"
        ),
    }


def _insert_distilled_row(
    conn: _ConnLike,
    *,
    workflow_id: str,
    session_id: str,
    payload: dict[str, Any],
    model: str,
    distill_run_id: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO distilled_workflows
            (id, problem_pattern, suggested_dag_json, python_module_path,
             evidence_count, source_session_ids, importance_score, model,
             distill_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            workflow_id,
            payload["problem_pattern"],
            "{}",
            f"mahavishnu/workflows/distilled/{workflow_id}.py",
            int(payload["evidence_count"]),
            json.dumps([session_id]),
            float(payload["importance_score"]),
            model,
            distill_run_id,
        ],
    )


def distill_workflows(
    conn: _ConnLike,
    *,
    evidence_threshold: int = DEFAULT_EVIDENCE_THRESHOLD,
    model: str = HEURISTIC_MODEL,
    reviewer: ReviewerIdentity | None = None,
) -> list[str]:
    """Run a single distillation pass.

    Pre-distill gate (Plan 5 audit H6): when a ``reviewer`` is supplied
    we enforce the trust root BEFORE any SQL runs. If the gate is
    omitted the call still works — ``reviewer=None`` is the v0 default
    for back-compat with the test suite — but production callers MUST
    pass a real :class:`ReviewerIdentity` (typically via
    ``ReviewerIdentity.from_env()``).
    """
    if reviewer is not None:
        decision = reviewer.enforce()
        reviewer.emit_audit_log(decision)

    candidates = _find_candidate_sessions(conn, evidence_threshold=int(evidence_threshold))
    if not candidates:
        return []


    distill_run_id = str(ULID())
    inserted_ids: list[str] = []

    for cand in candidates:
        session_id = cand["session_id"]
        try:
            payload = _synthesize_candidate(conn, session_id)
        except Exception as exc:


            logger.warning(
                "distill_workflows: skipping candidate due to error",
                extra={"session_id": session_id, "error": str(exc)},
            )
            continue

        workflow_id = str(ULID())
        try:
            _insert_distilled_row(
                conn,
                workflow_id=workflow_id,
                session_id=session_id,
                payload=payload,
                model=model,
                distill_run_id=distill_run_id,
            )
            inserted_ids.append(workflow_id)
        except Exception as exc:


            logger.warning(
                "distill_workflows: INSERT failed for candidate",
                extra={"session_id": session_id, "error": str(exc)},
            )
            continue

    return inserted_ids


__all__ = [
    "DEFAULT_EVIDENCE_THRESHOLD",
    "HEURISTIC_MODEL",
    "IMPORTANCE_FLOOR",
    "_importance_from_evidence_workflows",
    "distill_workflows",
]
