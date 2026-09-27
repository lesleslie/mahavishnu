"""Apply Alembic revisions from Python with pre-flight checks.

This module provides a Python wrapper around Alembic migrations so they can be
exercised from tests without spinning up a real Postgres instance. It also
enforces a Python-level pre-flight check for the C-4 idempotency-key migration
so the same code path is testable against SQLite.

Forward-only per ``feedback-no-backwards-compat-pre-1.0``. Recovery from a bad
migration is a follow-up forward migration, not a downgrade.

Implements: REQ-004 (Schema reconciliation — idempotency_key column + unique
index on audit.task_events, blocked-by C-6).
"""

from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

try:
    from oneiric.core.logging import get_logger

    logger = get_logger(__name__)
except ImportError:  # pragma: no cover - oneiric unavailable in some envs
    import logging

    logger = logging.getLogger(__name__)


# Optional Prometheus metric. Mirrors the lazy-import pattern in
# mahavishnu.core.routing_metrics so the module is safe to import even when
# prometheus_client is not installed (e.g. minimal test env).
try:
    from prometheus_client import Histogram as _PromHistogram

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - graceful degradation
    _PROM_AVAILABLE = False

    class _PromHistogram:  # type: ignore[no-redef]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def labels(self, **_kwargs: Any) -> _PromHistogram:
            return self

        def observe(self, _amount: float) -> None:
            pass


MIGRATION_DURATION: _PromHistogram = _PromHistogram(
    "migration_duration_seconds",
    "Time taken to apply an Alembic revision.",
    labelnames=["revision", "direction"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0),
)


# Path: <repo>/migrations/versions. Resolved at import time.
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations" / "versions"


class MigrationPreFlightError(RuntimeError):
    """Raised when a migration's pre-flight check fails.

    Example: V202609260001 detects duplicate idempotency_key values before
    adding the unique-index constraint. If duplicates exist, the migration
    must abort BEFORE adding the column, otherwise the column would exist
    but the unique-index revision could not apply.
    """


def find_revision_file(revision_id: str) -> Path:
    """Locate the SQL file for a given revision ID.

    Args:
        revision_id: Migration ID like ``V202609260001`` or ``V202609260001b``.

    Returns:
        Absolute path to the matching ``.sql`` file.

    Raises:
        FileNotFoundError: When no file matches the ID.
        ValueError: When multiple files match the ID.
    """
    matches = sorted(_MIGRATIONS_DIR.glob(f"{revision_id}__*.sql"))
    if not matches:
        raise FileNotFoundError(
            f"No migration file found for revision {revision_id!r} in {_MIGRATIONS_DIR}"
        )
    if len(matches) > 1:
        raise ValueError(f"Multiple migration files found for revision {revision_id!r}: {matches}")
    return matches[0]


def _strip_pg_for_sqlite(sql: str) -> str:
    """Adapt PostgreSQL-only DDL for SQLite (test environment only).

    - Strips ``DO $$ ... $$`` blocks (PL/pgSQL — not supported by SQLite).
    - Strips the ``CONCURRENTLY`` keyword (SQLite indexes are non-blocking
      by default).
    - Drops ``BEGIN``/``COMMIT`` markers (SQLite handles DDL outside of
      transactions implicitly).

    This is a *test-only* translation. Production runs use the raw files
    via ``alembic upgrade head`` against PostgreSQL.
    """
    sql = re.sub(r"DO\s*\$\$.*?\$\$\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE)
    sql = re.sub(r"\bCONCURRENTLY\b", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^\s*BEGIN\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    sql = re.sub(r"^\s*COMMIT\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    return sql


def _is_sqlite_connection(conn: Any) -> bool:
    """Detect a sqlite3 / aiosqlite connection.

    Asyncpg connections use ``.execute(sql)`` with parameter binding;
    sqlite3 / aiosqlite use ``.executescript(sql)`` for multi-statement DDL.
    """
    module = type(conn).__module__
    return module.startswith("sqlite") or hasattr(conn, "executescript")


async def _preflight_idempotency_duplicates(conn: Any) -> None:
    """Run the duplicate-key pre-flight check before V202609260001 applies.

    Mirrors the SQL ``DO $$`` block in the migration file but executes in
    Python so the same contract holds against SQLite in the test suite.
    Raises MigrationPreFlightError when duplicates are detected.
    """
    # Use the schema-qualified table name that the migration file targets.
    # For SQLite (test path), apply_revision strips the schema prefix
    # elsewhere; here we keep the PG-style reference because the SQL adapter
    # also rewrites the query for SQLite below when needed.
    base_query = (
        "SELECT (COUNT(*) - COUNT(DISTINCT idempotency_key)) AS dup_count "
        "FROM audit.task_events WHERE idempotency_key IS NOT NULL"
    )
    query = (
        base_query.replace("audit.task_events", "task_events")
        if _is_sqlite_connection(conn)
        else base_query
    )
    if _is_sqlite_connection(conn):
        if hasattr(conn, "execute"):
            cursor = await conn.execute(query)
            row = await cursor.fetchone()
        else:
            cursor = conn.execute(query)
            row = cursor.fetchone()
        dup_count = int(row[0]) if row and row[0] is not None else 0
    else:
        row = await conn.fetchrow(query)
        dup_count = int(row["dup_count"]) if row else 0

    if dup_count > 0:
        raise MigrationPreFlightError(
            f"pre-flight: duplicate idempotency_keys detected "
            f"({dup_count} duplicates); dedupe before migrating"
        )


async def apply_revision(
    revision_id: str,
    conn: Any,
    *,
    direction: str = "up",
) -> None:
    """Apply a single Alembic revision by ID against an open connection.

    Args:
        revision_id: Migration ID, e.g. ``V202609260001`` or ``V202609260001b``.
        conn: An open async DB connection — ``aiosqlite.Connection`` for
            SQLite tests, ``asyncpg.Connection`` for production.
        direction: ``up`` (default) applies the migration; ``down`` is
            not implemented (forward-only per project policy).

    Raises:
        MigrationPreFlightError: When a pre-flight check fails.
        FileNotFoundError: When no migration file matches ``revision_id``.
        ValueError: When ``direction != "up"`` (downgrade is rejected).
    """
    if direction != "up":
        raise ValueError(
            f"downgrade not supported (forward-only per project policy); direction={direction!r}"
        )

    rev_file = find_revision_file(revision_id)
    sql = rev_file.read_text()

    start_time = time.time()
    try:
        # Python-level pre-flight before any DDL runs.
        if revision_id == "V202609260001":
            await _preflight_idempotency_duplicates(conn)

        if _is_sqlite_connection(conn):
            adapted = _strip_pg_for_sqlite(sql)
            if hasattr(conn, "executescript"):
                await conn.executescript(adapted)
            else:
                conn.executescript(adapted)
        else:
            # asyncpg: single statement per exec.
            await conn.execute(sql)
    finally:
        duration = time.time() - start_time
        MIGRATION_DURATION.labels(revision=revision_id, direction=direction).observe(duration)
        logger.debug(
            "apply_revision",
            extra={"revision": revision_id, "direction": direction, "seconds": duration},
        )


__all__ = [
    "MIGRATION_DURATION",
    "MigrationPreFlightError",
    "apply_revision",
    "find_revision_file",
]
