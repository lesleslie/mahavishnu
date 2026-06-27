"""Integration tests for the H4 source provenance gate wired into the
distiller pre-filter pipeline.

Plan 5 audit finding H4: a compromised workflow run is the entry point
for poisoned distillation. The distiller MUST reject any candidate
session whose originating run record fails ``check_source_purity``
BEFORE it reaches the synthesizer.

These tests pin the wiring contract between
``mahavishnu.distill.distiller.distill_workflows`` and
``mahavishnu.distill.provenance.check_source_purity``. They do not
re-test the gate itself (covered in ``test_distill_provenance.py``);
they verify the distiller feeds run records into the gate and skips
rejected candidates.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.distill.distiller import distill_workflows


class _FakeRows:
    """Mimics a DuckDB result set: iterable + .fetchall()."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConn:
    """Minimal SQL stub.

    Records each execute() and returns canned rows keyed by a substring
    of the SQL. ``_queue`` lets a test pre-load multiple result sets
    consumed in order; ``_table`` maps SQL-keywords → rows.
    """

    def __init__(self) -> None:
        self.executions: list[tuple[str, list[Any] | None]] = []
        self._queue: list[_FakeRows] = []
        self._by_sql: dict[str, _FakeRows] = {}

    def queue(self, rows: list[tuple[Any, ...]]) -> None:
        self._queue.append(_FakeRows(rows))

    def stub(self, sql_marker: str, rows: list[tuple[Any, ...]]) -> None:
        self._by_sql[sql_marker] = _FakeRows(rows)

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeRows:
        self.executions.append((sql, params))
        if self._queue:
            return self._queue.pop(0)
        for marker, rows in self._by_sql.items():
            if marker in sql:
                return rows
        # Default: empty result set so the loop terminates cleanly.
        return _FakeRows([])


class TestDistillWorkflowsProvenanceGate:
    """The distiller MUST skip candidates whose run records fail H4."""

    def test_external_source_is_skipped(self) -> None:
        """A session whose originating run has source_type=external is skipped."""
        conn = _FakeConn()
        # _find_candidate_sessions returns one session
        conn.queue([("01HEXSESS01", 5, 1, "mahavishnu")])
        # _find_session_run_record returns external source
        conn.queue([("01HEXRUN01", "01HEXSESS01", "external", None)])

        inserted = distill_workflows(conn)
        assert inserted == []
        # INSERT must NOT have been called — no row reached distilled_workflows
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert insert_calls == []

    def test_unattributed_mahavishnu_workflow_is_skipped(self) -> None:
        """Trusted source but missing reviewer_id → skipped."""
        conn = _FakeConn()
        conn.queue([("01HEXSESS02", 5, 1, "mahavishnu")])
        conn.queue([("01HEXRUN02", "01HEXSESS02", "mahavishnu_workflow", None)])

        inserted = distill_workflows(conn)
        assert inserted == []
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert insert_calls == []

    def test_unlisted_reviewer_is_skipped_when_allowlist_configured(self) -> None:
        """Reviewer present but not in allowlist → skipped."""
        conn = _FakeConn()
        conn.queue([("01HEXSESS03", 5, 1, "mahavishnu")])
        conn.queue([("01HEXRUN03", "01HEXSESS03", "mahavishnu_workflow", "mallory")])

        inserted = distill_workflows(
            conn,
            reviewer_allowlist=frozenset({"alice", "bob"}),
        )
        assert inserted == []
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert insert_calls == []

    def test_allowlisted_reviewer_passes_through(self) -> None:
        """Happy path: gate clears and synthesis proceeds."""
        conn = _FakeConn()
        conn.queue([("01HEXSESS04", 5, 1, "mahavishnu")])
        conn.queue([("01HEXRUN04", "01HEXSESS04", "mahavishnu_workflow", "alice")])
        # _synthesize_candidate COUNT(*) → row of n=5, project="mahavishnu"
        conn.queue([(5, "mahavishnu")])

        inserted = distill_workflows(
            conn,
            reviewer_allowlist=frozenset({"alice"}),
        )
        assert len(inserted) == 1
        # An INSERT happened with workflow_id, session_id, etc.
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert len(insert_calls) == 1

    def test_bootstrap_mode_accepts_any_reviewer_for_trusted_source(self) -> None:
        """With allowlist=None, mahavishnu_workflow + any reviewer is PURE."""
        conn = _FakeConn()
        conn.queue([("01HEXSESS05", 5, 1, "mahavishnu")])
        conn.queue([("01HEXRUN05", "01HEXSESS05", "mahavishnu_workflow", "bob")])
        conn.queue([(5, "mahavishnu")])

        inserted = distill_workflows(conn)  # no allowlist → bootstrap
        assert len(inserted) == 1

    def test_mixed_candidates_only_pure_ones_reach_insert(self) -> None:
        """Three candidates: external / unlisted / allowlisted. Only one inserts."""
        conn = _FakeConn()
        conn.queue(
            [
                ("01HEXSESS06", 5, 1, "mahavishnu"),
                ("01HEXSESS07", 5, 1, "mahavishnu"),
                ("01HEXSESS08", 5, 1, "mahavishnu"),
            ],
        )
        # Per-candidate run records (queued in order)
        conn.queue([("r06", "01HEXSESS06", "external", None)])  # rejected
        conn.queue([("r07", "01HEXSESS07", "mahavishnu_workflow", "mallory")])  # rejected
        conn.queue([("r08", "01HEXSESS08", "mahavishnu_workflow", "alice")])  # accepted
        # _synthesize_candidate for the one accepted
        conn.queue([(5, "mahavishnu")])

        inserted = distill_workflows(
            conn,
            reviewer_allowlist=frozenset({"alice"}),
        )
        assert inserted == [pytest.approx(inserted[0])] or len(inserted) == 1
        assert len(inserted) == 1
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert len(insert_calls) == 1

    def test_missing_run_record_is_treated_as_unattributed(self) -> None:
        """If no row in mahavishnu_workflow_runs, the record has source_type=None.

        check_source_purity rejects records with no source_type — this
        protects against sessions that appear in conversations_v2 but
        never had a tracked run (e.g. unvetted scripts that wrote
        directly to conversations_v2).
        """
        conn = _FakeConn()
        conn.queue([("01HEXSESS09", 5, 1, "mahavishnu")])
        conn.queue([])  # no run row found

        inserted = distill_workflows(conn)
        assert inserted == []
        insert_calls = [e for e in conn.executions if "INSERT INTO distilled_workflows" in e[0]]
        assert insert_calls == []
