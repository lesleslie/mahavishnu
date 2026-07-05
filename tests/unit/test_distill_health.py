"""Tests for ``mahavishnu.distill.health``.

Plan 5 Phase A.1 Task 4 — TDD RED.

``distilled_workflow_health()`` mirrors the Session-Buddy
``_distilled_skill_health`` 4-bucket classifier (stale /
under_utilized / cold / fresh). The output is a list of dicts, one
per distilled_workflows row, each carrying a ``status`` key plus
the original fields.

Thresholds (mirror the skill system):
- ``stale`` — ``last_reinforced_at`` is older than
  ``threshold_days`` (default 90).
- ``under_utilized`` — ``importance_score >= 0.9`` AND no
  approved_at (never published — workflow has been proposed but
  no reviewer has approved it).
- ``cold`` — ``evidence_count == 0`` and not under-utilized.
- ``fresh`` — anything else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import duckdb
import pytest

from mahavishnu.distill.health import distilled_workflow_health
from mahavishnu.distill.schema import apply_distill_schema

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _insert_workflow(
    conn: duckdb.DuckDBPyConnection,
    *,
    id: str,
    importance: float,
    evidence: int,
    last_reinforced_offset_days: int,
    approved: bool = False,
) -> None:
    last = datetime(2026, 6, 26, tzinfo=UTC) - timedelta(days=last_reinforced_offset_days)
    created = last - timedelta(days=1)
    conn.execute(
        """
        INSERT INTO distilled_workflows
            (id, problem_pattern, suggested_dag_json, python_module_path,
             evidence_count, importance_score, model, created_at,
             last_reinforced_at, approved_at, approved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            id,
            f"pattern for {id}",
            "{}",
            f"mahavishnu/workflows/distilled/{id}.py",
            int(evidence),
            float(importance),
            "heuristic",
            created,
            last,
            datetime(2026, 6, 26, tzinfo=UTC) if approved else None,
            "reviewer@example.com" if approved else None,
        ],
    )


@pytest.fixture
def seeded_conn() -> Callable[..., duckdb.DuckDBPyConnection]:
    """Build a connection with the schema applied. Returns a factory
    that inserts a known fixture set per scenario."""

    def _factory(scenario: str) -> duckdb.DuckDBPyConnection:
        c = duckdb.connect(":memory:")
        apply_distill_schema(c)
        if scenario == "empty":
            return c
        if scenario == "mixed":
            # 1 fresh, 1 stale, 1 under_utilized (high importance, never approved)
            _insert_workflow(
                c,
                id="01J_FRESH",
                importance=0.8,
                evidence=3,
                last_reinforced_offset_days=10,
                approved=True,
            )
            _insert_workflow(
                c,
                id="01J_STALE",
                importance=0.8,
                evidence=3,
                last_reinforced_offset_days=120,
                approved=True,
            )
            _insert_workflow(
                c,
                id="01J_UNDER",
                importance=0.95,
                evidence=3,
                last_reinforced_offset_days=10,
                approved=False,
            )
            return c
        if scenario == "cold":
            _insert_workflow(
                c,
                id="01J_COLD",
                importance=0.75,
                evidence=0,
                last_reinforced_offset_days=5,
                approved=False,
            )
            return c
        raise ValueError(f"unknown scenario: {scenario}")

    return _factory


class TestHealthEmpty:
    def test_empty_database_returns_empty_list(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn("empty")
        result = distilled_workflow_health(c)
        assert result == []


class TestHealthFourBuckets:
    def test_classifies_each_row_correctly(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn("mixed")
        rows = distilled_workflow_health(c)
        assert len(rows) == 3

        by_id = {r["id"]: r for r in rows}
        assert by_id["01J_FRESH"]["status"] == "fresh"
        assert by_id["01J_STALE"]["status"] == "stale"
        # High importance + never approved → under_utilized.
        assert by_id["01J_UNDER"]["status"] == "under_utilized"

    def test_cold_evidence_zero(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn("cold")
        rows = distilled_workflow_health(c)
        assert len(rows) == 1
        assert rows[0]["status"] == "cold"
        assert rows[0]["id"] == "01J_COLD"


class TestHealthStalenessThreshold:
    def test_threshold_days_changes_stale_classification(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn("mixed")
        # 10-day-old row is fresh at threshold 90, stale at threshold 5.
        rows_90 = distilled_workflow_health(c, threshold_days=90)
        rows_5 = distilled_workflow_health(c, threshold_days=5)
        by_id_90 = {r["id"]: r for r in rows_90}
        by_id_5 = {r["id"]: r for r in rows_5}
        # FRESH at threshold 90 → stale at threshold 5.
        assert by_id_90["01J_FRESH"]["status"] == "fresh"
        assert by_id_5["01J_FRESH"]["status"] == "stale"


class TestHealthRowShape:
    def test_row_carries_original_fields(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        c = seeded_conn("cold")
        rows = distilled_workflow_health(c)
        row = rows[0]
        # Required fields per plan.
        for key in (
            "id",
            "problem_pattern",
            "importance_score",
            "evidence_count",
            "last_reinforced_at",
            "python_module_path",
            "status",
        ):
            assert key in row, f"missing key: {key}"

    def test_stale_rows_sorted_first(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        """Stale rows are the most actionable: they surface at the top."""
        c = seeded_conn("mixed")
        rows = distilled_workflow_health(c)
        # First row should be either stale or under_utilized.
        assert rows[0]["status"] in {"stale", "under_utilized"}


class TestHealthRequiresSchema:
    def test_missing_table_raises(self) -> None:
        # Fresh in-memory DuckDB → no schema → table genuinely missing.
        c = duckdb.connect(":memory:")
        with pytest.raises(RuntimeError):
            distilled_workflow_health(c, require_table_exists=True)

    def test_missing_table_returns_empty_by_default(
        self, seeded_conn: Callable[..., duckdb.DuckDBPyConnection]
    ) -> None:
        # Without require_table_exists=True, missing-table returns []
        # (matches the skill tool behavior).
        c = seeded_conn("empty")
        assert distilled_workflow_health(c) == []  # schema applied, no rows
