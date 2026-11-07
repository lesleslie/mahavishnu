"""Schema migration tests for distilled_workflows + mahavishnu_workflow_runs.

Plan 5 Phase A.1 Task 1 — TDD RED: write failing schema test first.

The schema lives in ``mahavishnu/distill/schema.py``. Two new tables:

- ``distilled_workflows`` — stores candidate workflows mined from session
  history. Core columns mirror ``distilled_skills`` (id, problem_pattern,
  evidence_count, importance_score, model, created_at,
  last_reinforced_at) plus workflow-specific columns
  (suggested_dag_json, python_module_path, prefect_deployment_id,
  distill_run_id, distilled_sha256, reviewer_edits_json,
  approved_at, approved_by).
- ``mahavishnu_workflow_runs`` — workflow run telemetry written by
  ``mahavishnu/distill/reporter.py``. Joins against
  ``conversations_v2.session_id`` for the heuristic filter in
  Phase B.2.

If a column is dropped, renamed, or has the wrong type, these tests
fail loudly.
"""

from __future__ import annotations

import duckdb
import pytest

from mahavishnu.distill.schema import (
    DISTILLED_WORKFLOWS_DDL,
    MAHAVISHNU_WORKFLOW_RUNS_DDL,
    apply_distill_schema,
)


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection with apply_distill_schema applied."""
    c = duckdb.connect(":memory:")
    apply_distill_schema(c)
    return c


class TestDistilledWorkflowsTable:
    """Columns, types, and CHECK constraints on distilled_workflows."""

    def test_table_exists(self, conn: duckdb.DuckDBPyConnection) -> None:
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'distilled_workflows'
            """
        ).fetchall()
        assert rows, "distilled_workflows table must exist after apply_distill_schema"

    def test_core_columns_present(self, conn: duckdb.DuckDBPyConnection) -> None:
        cols = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = 'distilled_workflows'
                """
            ).fetchall()
        }
        for col in (
            "id",
            "problem_pattern",
            "evidence_count",
            "importance_score",
            "model",
            "created_at",
            "last_reinforced_at",
        ):
            assert col in cols, f"missing column: {col}"

    def test_workflow_specific_columns_present(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        cols = {
            row[0]
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'distilled_workflows'
                """
            ).fetchall()
        }
        for col in (
            "suggested_dag_json",
            "python_module_path",
            "prefect_deployment_id",
            "distill_run_id",
            "distilled_sha256",
            "reviewer_edits_json",
            "approved_at",
            "approved_by",
            "source_session_ids",
        ):
            assert col in cols, f"missing workflow-specific column: {col}"

    def test_id_is_text_primary_key(self, conn: duckdb.DuckDBPyConnection) -> None:
        rows = conn.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'distilled_workflows' AND column_name = 'id'
            """
        ).fetchall()
        assert rows
        assert rows[0][0].upper() in {"VARCHAR", "TEXT"}

    def test_importance_score_has_check_constraint(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        # Insert a below-floor row and expect the CHECK constraint to reject.
        with pytest.raises(duckdb.Error):
            conn.execute(
                """
                INSERT INTO distilled_workflows
                    (id, problem_pattern, suggested_dag_json, python_module_path,
                     evidence_count, importance_score, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    "01J00000000000000000000000",
                    "test",
                    "{}",
                    "mahavishnu/workflows/distilled/x.py",
                    0,
                    0.5,  # below IMPORTANCE_FLOOR (0.7)
                    "heuristic",
                ],
            )


class TestMahavishnuWorkflowRunsTable:
    """Columns and types on mahavishnu_workflow_runs."""

    def test_table_exists(self, conn: duckdb.DuckDBPyConnection) -> None:
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'mahavishnu_workflow_runs'
            """
        ).fetchall()
        assert rows, "mahavishnu_workflow_runs table must exist"

    def test_required_columns_present(self, conn: duckdb.DuckDBPyConnection) -> None:
        cols = {
            row[0]
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'mahavishnu_workflow_runs'
                """
            ).fetchall()
        }
        for col in (
            "workflow_id",
            "session_id",
            "repo_path",
            "status",
            "started_at",
            "completed_at",
            "duration_ms",
            "adapter",
            "task_type",
            "error_summary",
        ):
            assert col in cols, f"missing column: {col}"

    def test_status_check_constraint_rejects_invalid(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        with pytest.raises(duckdb.Error):
            conn.execute(
                """
                INSERT INTO mahavishnu_workflow_runs
                    (workflow_id, repo_path, status, started_at,
                     adapter, task_type)
                VALUES (?, ?, ?, now(), ?, ?)
                """,
                ["wf1", "/tmp/repo", "BOGUS_STATUS", "prefect", "code_review"],
            )


class TestDdlStrings:
    """The exported DDL constants must be non-empty SQL strings."""

    def test_ddl_strings_non_empty(self) -> None:
        assert isinstance(DISTILLED_WORKFLOWS_DDL, str)
        assert "CREATE TABLE" in DISTILLED_WORKFLOWS_DDL.upper()
        assert isinstance(MAHAVISHNU_WORKFLOW_RUNS_DDL, str)
        assert "CREATE TABLE" in MAHAVISHNU_WORKFLOW_RUNS_DDL.upper()


class TestApplyDistillSchemaIdempotent:
    """Calling apply_distill_schema twice must not raise."""

    def test_apply_twice(self) -> None:
        c = duckdb.connect(":memory:")
        apply_distill_schema(c)
        apply_distill_schema(c)  # second call must be a no-op
        rows = c.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN "
            "('distilled_workflows', 'mahavishnu_workflow_runs')"
        ).fetchone()
        assert rows is not None
        assert rows[0] == 2
