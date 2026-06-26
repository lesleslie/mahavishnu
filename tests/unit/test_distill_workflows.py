"""Tests for ``mahavishnu.distill.distill_workflows()``.

Plan 5 Phase A.1 Task 2 — TDD RED: write failing tests first, then
implement minimal code to make them pass.

The function is a thin wrapper that, in Phase A.1, only needs:

1. Pull candidate ``session_id`` groups from
   ``conversations_v2 WHERE source_type = 'mahavishnu_workflow'``,
   joined to ``mahavishnu_workflow_runs``.
2. For each candidate, INSERT a row in ``distilled_workflows`` with
   the heuristic fields populated.
3. **Per-candidate isolation** — a bad LLM response (in Phase B.2)
   MUST NOT abort the whole pass. Phase A.1 establishes the
   structural isolation by NOT raising from the loop body.

Phase B.2 will replace the body with ``_DagHeuristicFilter`` +
``_LlmSynthesizer``. The shape — ``distill_workflows(conn, ...,
evidence_threshold, model) -> list[str]`` — is locked here so the
Phase B implementation slots in without an API change.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import duckdb
import pytest

from mahavishnu.distill.distiller import (
    DEFAULT_EVIDENCE_THRESHOLD,
    HEURISTIC_MODEL,
    _importance_from_evidence_workflows,
    distill_workflows,
)
from mahavishnu.distill.schema import apply_distill_schema

if TYPE_CHECKING:
    from collections.abc import Callable


def _seed_workflow_session(
    conn: duckdb.DuckDBPyConnection,
    *,
    session_id: str,
    source_type: str,
    n_rows: int,
    task_type: str = "code_review",
) -> None:
    """Insert N conversations_v2 rows for a session_id."""
    # Minimal schema needed for distill_workflows SQL JOIN.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations_v2 (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            project TEXT,
            category TEXT,
            timestamp TIMESTAMP NOT NULL DEFAULT now(),
            memory_tier TEXT NOT NULL DEFAULT 'long_term',
            embedding FLOAT[384],
            searchable_content TEXT NOT NULL DEFAULT '',
            namespace TEXT NOT NULL DEFAULT 'default'
        )
        """
    )
    for i in range(n_rows):
        conn.execute(
            """
            INSERT INTO conversations_v2
                (id, session_id, source_type, content, project, category,
                 timestamp, embedding, searchable_content)
            VALUES (?, ?, ?, ?, ?, ?, now(), NULL, '')
            """,
            [
                f"{session_id}-{i}",
                session_id,
                source_type,
                f"workflow tool call {i}",
                "mahavishnu",
                "workflow_runs",
            ],
        )
    # Seed matching run rows if this is a workflow session.
    if source_type == "mahavishnu_workflow":
        conn.execute(
            """
            INSERT INTO mahavishnu_workflow_runs
                (workflow_id, session_id, repo_path, status, started_at,
                 adapter, task_type)
            VALUES (?, ?, '/tmp/repo', 'completed', now(), 'prefect', ?)
            """,
            [f"wf-{session_id}", session_id, task_type],
        )


@pytest.fixture
def seeded_conn() -> Callable[..., duckdb.DuckDBPyConnection]:
    """Factory fixture: returns a function that builds a seeded conn."""

    def _factory(
        workflow_sessions: list[tuple[str, int]] | None = None,
        other_sessions: list[tuple[str, int]] | None = None,
    ) -> duckdb.DuckDBPyConnection:
        c = duckdb.connect(":memory:")
        apply_distill_schema(c)
        # conversations_v2 schema (minimal subset the SQL needs)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations_v2 (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                project TEXT,
                category TEXT,
                timestamp TIMESTAMP NOT NULL DEFAULT now(),
                memory_tier TEXT NOT NULL DEFAULT 'long_term',
                embedding FLOAT[384],
                searchable_content TEXT NOT NULL DEFAULT '',
                namespace TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        for sid, n in workflow_sessions or []:
            _seed_workflow_session(c, session_id=sid, source_type="mahavishnu_workflow", n_rows=n)
        for sid, n in other_sessions or []:
            _seed_workflow_session(c, session_id=sid, source_type="manual", n_rows=n)
        return c

    return _factory


class TestImportanceHelper:
    """The importance helper mirrors session-buddy's
    ``_importance_from_evidence`` shape (single-project boost,
    clamped to [IMPORTANCE_FLOOR, 1.0])."""

    def test_zero_evidence_returns_floor(self) -> None:
        score = _importance_from_evidence_workflows(0, 1)
        assert score >= 0.7

    def test_high_evidence_approaches_one(self) -> None:
        score = _importance_from_evidence_workflows(16, 1)
        assert score >= 0.95
        assert score <= 1.0

    def test_single_project_boost(self) -> None:
        multi = _importance_from_evidence_workflows(8, 4)
        single = _importance_from_evidence_workflows(8, 1)
        # Single-project gets the boost.
        assert single >= multi

    def test_never_below_floor(self) -> None:
        for ec in (0, 1, 2, 100):
            for pc in (1, 4, 8):
                score = _importance_from_evidence_workflows(ec, pc)
                assert score >= 0.7
                assert score <= 1.0


class TestDistillWorkflowsEmpty:
    """No candidates → returns empty list, no rows inserted."""

    def test_no_workflow_sessions_returns_empty(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn(workflow_sessions=[], other_sessions=[("s1", 5)])
        result = distill_workflows(c)
        assert result == []
        rows = c.execute("SELECT COUNT(*) FROM distilled_workflows").fetchone()
        assert rows is not None
        assert rows[0] == 0

    def test_below_evidence_threshold_excluded(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        # 2 rows < default threshold 3 → no row.
        c = seeded_conn(workflow_sessions=[("s1", 2)])
        result = distill_workflows(c, evidence_threshold=3)
        assert result == []
        rows = c.execute("SELECT COUNT(*) FROM distilled_workflows").fetchone()
        assert rows is not None
        assert rows[0] == 0


class TestDistillWorkflowsInserts:
    """Candidates above threshold → rows inserted with required fields."""

    def test_inserts_one_row_per_session(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn(
            workflow_sessions=[("s1", 5), ("s2", 4)],
            other_sessions=[("s_other", 10)],  # not a workflow session
        )
        ids = distill_workflows(c, evidence_threshold=3)
        assert len(ids) == 2
        # All returned ids must be present in the table.
        rows = c.execute(
            "SELECT COUNT(*) FROM distilled_workflows WHERE id = ANY(?)",
            [ids],
        ).fetchone()
        assert rows is not None
        assert rows[0] == 2

    def test_inserted_row_fields(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn(workflow_sessions=[("s1", 5)])
        ids = distill_workflows(c, evidence_threshold=3)
        assert len(ids) == 1
        row = c.execute(
            """
            SELECT id, problem_pattern, evidence_count, importance_score,
                   model, source_session_ids, python_module_path
            FROM distilled_workflows WHERE id = ?
            """,
            [ids[0]],
        ).fetchone()
        assert row is not None
        (rid, pattern, evidence, importance, model, sources_json, mod_path) = row
        # id is non-empty
        assert rid
        # problem_pattern references the session
        assert "s1" in pattern or "mahavishnu" in pattern
        assert evidence == 5
        assert 0.7 <= importance <= 1.0
        assert model == HEURISTIC_MODEL
        assert sources_json is not None
        # sources is JSON array
        sources = json.loads(sources_json)
        assert "s1" in sources
        # python_module_path lives under the quarantine dir
        assert "distilled" in mod_path
        assert mod_path.endswith(".py")

    def test_default_evidence_threshold_is_three(self) -> None:
        assert DEFAULT_EVIDENCE_THRESHOLD == 3

    def test_default_model_is_heuristic(self) -> None:
        assert HEURISTIC_MODEL == "heuristic"


class TestDistillWorkflowsPerCandidateIsolation:
    """A failing candidate must NOT abort the rest of the pass.

    Phase A.1 establishes the structural pattern: even when the inner
    synthesis step raises, the outer loop continues. Phase B.2 will
    exercise this with real LLM errors. For now, we test the
    pattern with a SQL injection that causes one INSERT to fail.
    """

    def test_one_bad_candidate_does_not_abort_pass(
        self,
        seeded_conn: Callable[..., duckdb.DuckDBPyConnection],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seed 3 candidates, then make the FIRST one fail by stubbing
        # the synthesize function.
        c = seeded_conn(workflow_sessions=[("s1", 5), ("s2", 5), ("s3", 5)])

        # Inject a failing first-call shim by monkeypatching the
        # default synth function used by the distiller. We use
        # ``monkeypatch.setattr`` on the module-level reference.
        from mahavishnu.distill import distiller

        original = distiller._synthesize_candidate
        call_log: list[str] = []

        def shim(conn: duckdb.DuckDBPyConnection, session_id: str) -> dict[str, Any]:
            call_log.append(session_id)
            if session_id == "s1":
                raise RuntimeError("simulated LLM failure")
            return original(conn, session_id)

        monkeypatch.setattr(distiller, "_synthesize_candidate", shim)

        ids = distill_workflows(c, evidence_threshold=3)

        # All three sessions were attempted.
        assert set(call_log) == {"s1", "s2", "s3"}
        # s1 failed → not inserted; s2 + s3 → inserted.
        assert len(ids) == 2
        # Verify rows in DB: exactly 2.
        rows = c.execute("SELECT COUNT(*) FROM distilled_workflows").fetchone()
        assert rows is not None
        assert rows[0] == 2
