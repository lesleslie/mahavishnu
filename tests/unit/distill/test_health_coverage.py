"""Coverage-push tests for the 6 missed lines in mahavishnu/distill/health.py"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from mahavishnu.distill.health import _as_aware, distilled_workflow_health


class _RaisingCursor:
    """Cursor whose execute() raises — exercises the except branch."""

    def execute(self, sql: str, params: list | None = None):  # noqa: ARG002
        raise RuntimeError("synthetic information_schema failure")


class _MissingTableCursor:
    """Cursor whose execute() succeeds but reports no distilled_workflows table."""

    class _Result:
        def fetchone(self) -> None:
            return None

    def execute(self, sql: str, params: list | None = None):  # noqa: ARG002
        return self._Result()


class TestExceptBranch:
    """Lines 51-56: conn.execute raising an exception."""

    def test_exception_with_require_table_exists_raises(self) -> None:
        """Line 51-55: except handler re-raises as RuntimeError when
        require_table_exists=True."""
        conn = _RaisingCursor()
        with pytest.raises(RuntimeError, match="distilled_workflows table not found"):
            distilled_workflow_health(conn, require_table_exists=True)

    def test_exception_without_require_table_exists_returns_empty(self) -> None:
        """Line 56: except handler swallows the exception and returns [].  """
        conn = _RaisingCursor()
        assert distilled_workflow_health(conn) == []
        assert distilled_workflow_health(conn, require_table_exists=False) == []


class TestMissingTableBranch:
    """Line 63: not-present branch with require_table_exists=False."""

    def test_missing_table_without_require_returns_empty(self) -> None:
        """A fresh DuckDB (no schema applied) reports the table absent; with
        require_table_exists=False the function must return [] instead of
        raising.  Uses the real DuckDB driver so the information_schema
        query is exercised."""
        c = duckdb.connect(":memory:")
        # Sanity check: distilled_workflows truly absent in fresh conn.
        assert c.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'distilled_workflows' LIMIT 1"
        ).fetchone() is None
        assert distilled_workflow_health(c) == []
        assert distilled_workflow_health(c, require_table_exists=False) == []


class TestAsAwareHelper:
    """Line 114: _as_aware returns its argument unchanged when tzinfo is set."""

    def test_aware_datetime_returned_unchanged(self) -> None:
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert _as_aware(aware) is aware

    def test_naive_datetime_gets_utc_tzinfo(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = _as_aware(naive)
        assert result.tzinfo is UTC
