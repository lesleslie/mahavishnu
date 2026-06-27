
from __future__ import annotations

if False:
    pass


IMPORTANCE_FLOOR: float = 0.7


WORKFLOW_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


DISTILLED_WORKFLOWS_DDL: str = f"""
CREATE TABLE IF NOT EXISTS distilled_workflows (
    id TEXT PRIMARY KEY, -- ULID
    problem_pattern TEXT NOT NULL, -- "Python repos: code_sweep + ruff strict"
    suggested_dag_json TEXT NOT NULL, -- serialized _DagSchema (Phase B)
    python_module_path TEXT NOT NULL, -- "mahavishnu/workflows/distilled/{{id}}.py"
    prefect_deployment_id TEXT, -- NULL until approved+published
    evidence_count INTEGER NOT NULL DEFAULT 0,
    source_session_ids VARCHAR, -- JSON array of session_ids
    importance_score REAL NOT NULL CHECK (importance_score >= {IMPORTANCE_FLOOR} AND importance_score <= 1.0),
    model TEXT NOT NULL, -- 'heuristic' | 'MiniMax-M3' | free-form LLM name
    distill_run_id TEXT, -- groups candidates from one distillation pass
    distilled_sha256 TEXT, -- SHA of python_module_path at distillation time
    reviewer_edits_json TEXT, -- JSON diff vs distilled_sha256 (Phase C)
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    last_reinforced_at TIMESTAMP NOT NULL DEFAULT now(),
    approved_at TIMESTAMP,
    approved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_distilled_workflows_importance
    ON distilled_workflows(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_distilled_workflows_last_reinforced
    ON distilled_workflows(last_reinforced_at DESC);
CREATE INDEX IF NOT EXISTS idx_distilled_workflows_distill_run
    ON distilled_workflows(distill_run_id);
"""


_MWF_RUN_STATUS_LIST: str = ", ".join(f"'{s}'" for s in sorted(WORKFLOW_RUN_STATUSES))

MAHAVISHNU_WORKFLOW_RUNS_DDL: str = f"""
CREATE TABLE IF NOT EXISTS mahavishnu_workflow_runs (
    workflow_id TEXT NOT NULL, -- matches distilled_workflows.id when distilled
    session_id TEXT, -- session-buddy session that triggered it
    repo_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_MWF_RUN_STATUS_LIST})),
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    adapter TEXT NOT NULL, -- 'prefect', 'llamaindex', 'agno'
    task_type TEXT NOT NULL,
    error_summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_mwf_runs_session
    ON mahavishnu_workflow_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_mwf_runs_status
    ON mahavishnu_workflow_runs(status);
"""


_ALL_DDL: tuple[str, ...] = (
    DISTILLED_WORKFLOWS_DDL,
    MAHAVISHNU_WORKFLOW_RUNS_DDL,
)


def apply_distill_schema(conn: object) -> None:
    for ddl in _ALL_DDL:
        conn.execute(ddl) # type: ignore[attr-defined]


__all__ = [
    "DISTILLED_WORKFLOWS_DDL",
    "IMPORTANCE_FLOOR",
    "MAHAVISHNU_WORKFLOW_RUNS_DDL",
    "WORKFLOW_RUN_STATUSES",
    "apply_distill_schema",
]
