
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

DEFAULT_STALENESS_DAYS: int = 90


UNDER_UTILIZED_FLOOR: float = 0.9


class _ConnLike(Protocol):
    def execute(self, sql: str, params: list[Any] | None = ...) -> Any: ...


def _classify(
    *,
    importance_score: float,
    evidence_count: int,
    last_reinforced_at: datetime,
    threshold_days: int,
    now: datetime,
    approved_at: datetime | None,
) -> str:
    if importance_score >= UNDER_UTILIZED_FLOOR and approved_at is None:
        return "under_utilized"
    if last_reinforced_at < now - timedelta(days=int(threshold_days)):
        return "stale"
    if int(evidence_count) == 0:
        return "cold"
    return "fresh"


def distilled_workflow_health(
    conn: _ConnLike,
    *,
    threshold_days: int = DEFAULT_STALENESS_DAYS,
    require_table_exists: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now(tz=UTC)


    try:
        present = conn.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'distilled_workflows'
            LIMIT 1
            """
        ).fetchone()
    except Exception as exc:
        if require_table_exists:
            raise RuntimeError(
                "distilled_workflows table not found; call apply_distill_schema() first"
            ) from exc
        return []

    if not present:
        if require_table_exists:
            raise RuntimeError(
                "distilled_workflows table not found; call apply_distill_schema() first"
            )
        return []

    rows = conn.execute(
        """
        SELECT id, problem_pattern, evidence_count, importance_score,
               python_module_path, last_reinforced_at, approved_at
        FROM distilled_workflows
        """
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        (
            rid,
            pattern,
            evidence,
            importance,
            mod_path,
            last_reinforced,
            approved_at,
        ) = row
        status = _classify(
            importance_score=float(importance),
            evidence_count=int(evidence),
            last_reinforced_at=_as_aware(last_reinforced),
            threshold_days=int(threshold_days),
            now=current,
            approved_at=_as_aware(approved_at) if approved_at is not None else None,
        )
        results.append(
            {
                "id": rid,
                "problem_pattern": pattern,
                "evidence_count": int(evidence),
                "importance_score": float(importance),
                "python_module_path": mod_path,
                "last_reinforced_at": last_reinforced,
                "approved_at": approved_at,
                "status": status,
            }
        )


    bucket_order = {"stale": 0, "under_utilized": 1, "fresh": 2, "cold": 3}
    results.sort(key=lambda r: (bucket_order.get(r["status"], 99), -float(r["importance_score"])))

    return results


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


__all__ = [
    "DEFAULT_STALENESS_DAYS",
    "UNDER_UTILIZED_FLOOR",
    "distilled_workflow_health",
]
