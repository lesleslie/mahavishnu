"""Tests for ``mahavishnu.distill.reporter``.

Plan 5 Phase A.1 Task 3 — TDD RED. The reporter materializes
workflow run telemetry into the ``mahavishnu_workflow_runs`` table
so the Phase B heuristic filter has data to JOIN against.

Contract:

- ``WorkflowRun`` is the dataclass the reporter accepts.
- ``report_run(conn, run) -> bool`` returns True on INSERT, False
  on a duplicate (idempotent on ``(workflow_id, started_at)``).
- ``safe_report_run(...)`` wraps ``report_run`` in a logger.exception
  and NEVER raises — telemetry must never block workflow execution.

The tests pin:
1. Inserting a completed run produces the expected row.
2. Inserting a failed/cancelled run also works.
3. Best-effort: a connection error is logged, not raised.
4. Idempotency on (workflow_id, started_at) — duplicate is upserted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

import duckdb
import pytest

from mahavishnu.distill.reporter import (
    WorkflowRun,
    report_run,
    safe_report_run,
)
from mahavishnu.distill.schema import apply_distill_schema


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    apply_distill_schema(c)
    return c


def _row_count(c: duckdb.DuckDBPyConnection) -> int:
    r = c.execute("SELECT COUNT(*) FROM mahavishnu_workflow_runs").fetchone()
    assert r is not None
    return int(r[0])


class TestWorkflowRunDataclass:
    def test_construction_minimum(self) -> None:
        run = WorkflowRun(
            workflow_id="wf-1",
            repo_path="/tmp/r",
            adapter="prefect",
            task_type="code_review",
            started_at=datetime(2026, 6, 26, tzinfo=UTC),
        )
        assert run.status == "completed"
        assert run.session_id is None
        assert run.completed_at is None
        assert run.duration_ms is None
        assert run.error_summary is None

    def test_construction_full(self) -> None:
        run = WorkflowRun(
            workflow_id="wf-2",
            repo_path="/tmp/r",
            adapter="llamaindex",
            task_type="sweep",
            started_at=datetime(2026, 6, 26, tzinfo=UTC),
            completed_at=datetime(2026, 6, 26, 0, 1, tzinfo=UTC),
            duration_ms=60_000,
            status="failed",
            session_id="sb-123",
            error_summary="boom",
        )
        assert run.status == "failed"
        assert run.duration_ms == 60_000
        assert run.session_id == "sb-123"
        assert run.error_summary == "boom"


class TestReportRunInsert:
    def test_completed_run_inserts(self, conn: duckdb.DuckDBPyConnection) -> None:
        started = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
        completed = started + timedelta(seconds=42)
        run = WorkflowRun(
            workflow_id="wf-1",
            repo_path="/tmp/r",
            adapter="prefect",
            task_type="code_review",
            started_at=started,
            completed_at=completed,
            duration_ms=42_000,
        )
        result = report_run(conn, run)
        assert result is True
        assert _row_count(conn) == 1

        row = conn.execute(
            """
            SELECT workflow_id, repo_path, status, duration_ms, adapter, task_type
            FROM mahavishnu_workflow_runs
            """
        ).fetchone()
        assert row is not None
        assert row[0] == "wf-1"
        assert row[1] == "/tmp/r"
        assert row[2] == "completed"
        assert row[3] == 42_000
        assert row[4] == "prefect"
        assert row[5] == "code_review"

    def test_failed_run_inserts(self, conn: duckdb.DuckDBPyConnection) -> None:
        run = WorkflowRun(
            workflow_id="wf-fail",
            repo_path="/tmp/r",
            adapter="agno",
            task_type="ingest",
            started_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            status="failed",
            error_summary="boom",
        )
        assert report_run(conn, run) is True
        rows = conn.execute("SELECT status, error_summary FROM mahavishnu_workflow_runs").fetchall()
        assert rows == [("failed", "boom")]

    def test_cancelled_run_inserts(self, conn: duckdb.DuckDBPyConnection) -> None:
        run = WorkflowRun(
            workflow_id="wf-cancel",
            repo_path="/tmp/r",
            adapter="prefect",
            task_type="code_review",
            started_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            status="cancelled",
        )
        assert report_run(conn, run) is True
        rows = conn.execute("SELECT status FROM mahavishnu_workflow_runs").fetchall()
        assert rows == [("cancelled",)]

    def test_invalid_status_rejected_by_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        # Defense in depth: the dataclass also validates, but here we
        # bypass it to confirm the SCHEMA CHECK rejects bad statuses.
        # The contract is "this never lands in the table" — verified
        # at both layers.
        with pytest.raises(duckdb.Error):
            conn.execute(
                """
                INSERT INTO mahavishnu_workflow_runs
                    (workflow_id, repo_path, status, started_at,
                     adapter, task_type)
                VALUES (?, ?, ?, now(), ?, ?)
                """,
                ["wf-x", "/tmp/r", "UNKNOWN_STATUS", "prefect", "code_review"],
            )
        assert _row_count(conn) == 0


class TestReportRunIdempotent:
    def test_duplicate_workflow_id_started_at_upserts(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        """The (workflow_id, started_at) tuple is a UNIQUE-ish gate:
        a duplicate upserts the existing row rather than failing.
        """
        started = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
        run1 = WorkflowRun(
            workflow_id="wf-dup",
            repo_path="/tmp/r1",
            adapter="prefect",
            task_type="code_review",
            started_at=started,
            status="completed",
            duration_ms=10_000,
        )
        run2 = WorkflowRun(
            workflow_id="wf-dup",
            repo_path="/tmp/r1",
            adapter="prefect",
            task_type="code_review",
            started_at=started,
            status="completed",
            duration_ms=15_000,  # updated duration
        )
        assert report_run(conn, run1) is True
        assert report_run(conn, run2) is True  # upsert path
        # Exactly one row.
        assert _row_count(conn) == 1
        # The second call's duration won.
        row = conn.execute(
            "SELECT duration_ms FROM mahavishnu_workflow_runs WHERE workflow_id='wf-dup'"
        ).fetchone()
        assert row is not None
        assert row[0] == 15_000


class TestSafeReportRun:
    def test_does_not_raise_on_db_error(
        self,
        conn: duckdb.DuckDBPyConnection,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Telemetry must NEVER block workflow execution.

        Force an INSERT failure by passing a connection with a
        closed/invalid underlying cursor. ``safe_report_run`` must
        log + return False, not raise.
        """

        class BrokenConn:
            def execute(self, sql: str, params: list | None = None) -> None:
                raise RuntimeError("simulated DB failure")

        run = WorkflowRun(
            workflow_id="wf-broken",
            repo_path="/tmp/r",
            adapter="prefect",
            task_type="code_review",
            started_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        with caplog.at_level(logging.WARNING, logger="mahavishnu.distill.reporter"):
            result = safe_report_run(BrokenConn(), run)  # type: ignore[arg-type]
        # No exception bubbles up.
        assert result is False
        # Logged a warning so operators see the failure.
        assert any(
            "reporter" in rec.name or "reporter" in str(rec.message) for rec in caplog.records
        ) or any(
            "telemetry" in rec.message.lower() or "report" in rec.message.lower()
            for rec in caplog.records
        )

    def test_returns_true_on_success(self, conn: duckdb.DuckDBPyConnection) -> None:
        run = WorkflowRun(
            workflow_id="wf-ok",
            repo_path="/tmp/r",
            adapter="prefect",
            task_type="code_review",
            started_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        assert safe_report_run(conn, run) is True
        assert _row_count(conn) == 1
