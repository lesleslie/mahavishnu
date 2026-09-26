"""Tests for V202609260001 + V202609260001b schema reconciliation migrations.

REQ-004 — Schema reconciliation. The migration files are forward-only
PostgreSQL DDL; this test file validates them against a SQLite test schema
(the test harness uses SQLite via per-test ``tmp_path`` files).

For the SQLite test path, ``mahavishnu.core.migrations.apply_revision``
adapts PostgreSQL-only syntax (DO $$ blocks, CONCURRENTLY, schema-qualified
table names) so the same migration files can be exercised in tests. The
production path runs the raw files via ``alembic upgrade head`` against
PostgreSQL.
"""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

import aiosqlite
import pytest
import pytest_asyncio

from mahavishnu.core.migrations import (
    MigrationPreFlightError,
    apply_revision,
    find_revision_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "versions"
REV_A = MIGRATIONS_DIR / "V202609260001__idempotency_key_column.sql"
REV_B = MIGRATIONS_DIR / "V202609260001b__idempotency_key_unique_index.sql"


def _adapt_sql_for_sqlite(sql: str) -> str:
    """Translate PG-only DDL to SQLite-compatible DDL for the test path.

    - audit.task_events → task_events (SQLite has no schemas)
    - DO $$ ... $$ blocks stripped (PL/pgSQL, not supported by SQLite)
    - CONCURRENTLY keyword stripped (SQLite indexes are non-blocking)
    - BEGIN/COMMIT stripped (SQLite handles DDL outside transactions)
    """
    sql = sql.replace("audit.task_events", "task_events")
    sql = re.sub(r"DO\s*\$\$.*?\$\$\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE)
    sql = re.sub(r"\bCONCURRENTLY\b", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^\s*BEGIN\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    sql = re.sub(r"^\s*COMMIT\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)
    return sql


def _sqlite_column_exists(db_path: Path, table: str, column: str) -> bool:
    """Return True if column exists in table (sync check for setup)."""
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cursor.fetchall())


def _sqlite_index_exists(db_path: Path, index_name: str) -> bool:
    """Return True if index exists in the DB (sync check for setup)."""
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        )
        return cursor.fetchone() is not None


async def _apply_rev_a_sqlite(db_path: Path) -> None:
    """SQLite-adapted apply for V202609260001.

    SQLite does not support ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``,
    so we check column existence via PRAGMA before applying.
    """
    if _sqlite_column_exists(db_path, "task_events", "idempotency_key"):
        return  # already applied
    adapted = _adapt_sql_for_sqlite(REV_A.read_text())
    adapted = re.sub(
        r"ADD COLUMN IF NOT EXISTS", "ADD COLUMN", adapted, flags=re.IGNORECASE
    )
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(adapted)
        await db.commit()


async def _apply_rev_b_sqlite(db_path: Path) -> None:
    """SQLite-adapted apply for V202609260001b.

    SQLite supports ``CREATE INDEX IF NOT EXISTS`` natively. The
    CONCURRENTLY keyword has already been stripped; we gate on existence
    to keep the apply path uniform with rev A.
    """
    if _sqlite_index_exists(db_path, "idx_task_events_idempotency_key"):
        return  # already applied
    adapted = _adapt_sql_for_sqlite(REV_B.read_text())
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(adapted)
        await db.commit()


def _make_sqlite_db(path: Path, with_idempotency_key: bool = False) -> None:
    """Create a fresh SQLite DB with a minimal task_events table.

    Args:
        path: Target SQLite file path. Will be created.
        with_idempotency_key: When True, include the column (used to seed
            duplicate rows for the pre-flight test). When False, omit it so
            the C-4 migration must add it.
    """
    cols = (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, "
        "event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
    if with_idempotency_key:
        cols += ", idempotency_key TEXT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(f"CREATE TABLE task_events ({cols})")
        conn.commit()


@pytest_asyncio.fixture
async def fresh_db_with_audit_schema(tmp_path: Path) -> Path:
    """Per-test fresh SQLite DB with a minimal task_events table.

    The schema deliberately omits the idempotency_key column so the C-4
    migration must add it. Without the column present at migration time,
    ``ADD COLUMN IF NOT EXISTS idempotency_key`` exercises the actual DDL.
    """
    db_path = tmp_path / "migration_test.db"
    _make_sqlite_db(db_path, with_idempotency_key=False)
    return db_path


@pytest_asyncio.fixture
async def db_with_duplicate_keys(tmp_path: Path) -> Path:
    """Two rows with the same idempotency_key to trigger pre-flight."""
    db_path = tmp_path / "migration_test.db"
    _make_sqlite_db(db_path, with_idempotency_key=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO task_events (idempotency_key, event_type) "
            "VALUES (?, ?)",
            ("dup-key-1", "created"),
        )
        conn.execute(
            "INSERT INTO task_events (idempotency_key, event_type) "
            "VALUES (?, ?)",
            ("dup-key-1", "updated"),
        )
        conn.commit()
    return db_path


@pytest.mark.req(["REQ-004"])
class TestMigrationRevAColumn:
    """V202609260001 — adds idempotency_key column with pre-flight check."""

    async def test_rev_a_adds_column(self, fresh_db_with_audit_schema: Path) -> None:
        """After applying rev A, the column exists."""
        # Verify column absent before
        assert not _sqlite_column_exists(
            fresh_db_with_audit_schema, "task_events", "idempotency_key"
        )

        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)

        assert _sqlite_column_exists(
            fresh_db_with_audit_schema, "task_events", "idempotency_key"
        )

    async def test_rev_a_idempotent(self, fresh_db_with_audit_schema: Path) -> None:
        """Re-running rev A on an already-migrated DB must not error."""
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)
        # Second run — IF NOT EXISTS / PRAGMA guard makes this a no-op
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)

    async def test_pre_flight_aborts_on_duplicates(
        self, db_with_duplicate_keys: Path
    ) -> None:
        """Pre-flight detects duplicate idempotency_keys and raises.

        This is the C-6-blocking safety net — if duplicates exist when
        the unique-index revision would apply, the migration must fail
        loudly rather than corrupt the constraint.
        """
        async with aiosqlite.connect(db_with_duplicate_keys) as db:
            with pytest.raises(MigrationPreFlightError, match="duplicate"):
                await apply_revision("V202609260001", db)


@pytest.mark.req(["REQ-004"])
class TestMigrationRevBIndex:
    """V202609260001b — creates unique partial index via CONCURRENTLY."""

    async def test_rev_b_creates_unique_index(
        self, fresh_db_with_audit_schema: Path
    ) -> None:
        """After applying rev B, the unique index exists."""
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)
        await _apply_rev_b_sqlite(fresh_db_with_audit_schema)

        assert _sqlite_index_exists(
            fresh_db_with_audit_schema, "idx_task_events_idempotency_key"
        )

    async def test_rev_b_idempotent(self, fresh_db_with_audit_schema: Path) -> None:
        """Re-running rev B on an already-indexed DB must not error."""
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)
        await _apply_rev_b_sqlite(fresh_db_with_audit_schema)
        await _apply_rev_b_sqlite(fresh_db_with_audit_schema)  # no-op

    async def test_unique_constraint_enforced(
        self, fresh_db_with_audit_schema: Path
    ) -> None:
        """After both revisions, two rows with the same idempotency_key fail.

        This is the contract C-6 (idempotency layer) relies on.
        """
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)
        await _apply_rev_b_sqlite(fresh_db_with_audit_schema)

        async with aiosqlite.connect(fresh_db_with_audit_schema) as db:
            await db.execute(
                "INSERT INTO task_events (idempotency_key, event_type) "
                "VALUES (?, ?)",
                ("key-a", "created"),
            )
            await db.commit()
            with pytest.raises(aiosqlite.IntegrityError):
                await db.execute(
                    "INSERT INTO task_events (idempotency_key, event_type) "
                    "VALUES (?, ?)",
                    ("key-a", "updated"),
                )
                await db.commit()


@pytest.mark.req(["REQ-004"])
class TestMigrationEndToEnd:
    """Full chain: column + index both present after both revisions."""

    async def test_full_migration_chain(self, fresh_db_with_audit_schema: Path) -> None:
        await _apply_rev_a_sqlite(fresh_db_with_audit_schema)
        await _apply_rev_b_sqlite(fresh_db_with_audit_schema)

        assert _sqlite_column_exists(
            fresh_db_with_audit_schema, "task_events", "idempotency_key"
        )
        assert _sqlite_index_exists(
            fresh_db_with_audit_schema, "idx_task_events_idempotency_key"
        )


@pytest.mark.req(["REQ-004"])
class TestNoDowngrade:
    """Forward-only. Verify the migrations have no DROP statements and no downgrade body."""

    def test_rev_a_no_downgrade(self) -> None:
        rev_a = REV_A.read_text()
        assert "DROP COLUMN" not in rev_a.upper()
        assert "DROP TABLE" not in rev_a.upper()
        assert "def downgrade" not in rev_a

    def test_rev_b_no_downgrade(self) -> None:
        rev_b = REV_B.read_text()
        assert "DROP INDEX" not in rev_b.upper()
        assert "DROP TABLE" not in rev_b.upper()
        assert "def downgrade" not in rev_b

    def test_find_revision_file_resolves(self) -> None:
        """find_revision_file resolves both revisions by ID."""
        assert find_revision_file("V202609260001") == REV_A
        assert find_revision_file("V202609260001b") == REV_B
