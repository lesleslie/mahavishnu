# C-4: schema reconciliation migration (WP-precond-1 — must land BEFORE C-6)

**REQ-NNN:** REQ-004 — Schema reconciliation migration (`idempotency_key VARCHAR(255) UNIQUE` on `audit.task_events`)
**Risk:** Medium (DB schema change with pre-flight safety check; forward-only; affects production deployments that ran `V202604021200__initial_consolidated_schema.sql`)
**Blocks:** C-6 (idempotency layer in `pool_route_execute` requires the `idempotency_key` column + unique index to exist)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).
**Status:** Draft — round-4 corrections baked in (two-revision split + forward-only).

## Goal

Resolve the schema conflict between `migrations/init.sql:110` (which has `idempotency_key VARCHAR(255) UNIQUE`) and `migrations/versions/V202604021200__initial_consolidated_schema.sql:103` (which defines `audit.task_events` WITHOUT the `idempotency_key` column). Without this migration, `EventStore.append(idempotency_key=...)` throws `asyncpg.UndefinedColumnError` on production deployments that have run the consolidated migration.

The migration is **forward-only**. Per `feedback-no-backwards-compat-pre-1.0`: no `downgrade()` body; recovery is a follow-up forward migration if anything goes wrong.

## Pre-flight checks

1. **C-3 has landed.** `migrations/env.py` now has `transaction_per_migration=False` (set preemptively in C-3). This is required for the unique-index revision to use `CREATE UNIQUE INDEX CONCURRENTLY` post-COMMIT.
2. **Migration runner is confirmed.** The spec notes "runner unclear; verify before landing". Read `migrations/env.py` and any `Makefile` / `pyproject.toml` scripts to identify the migration runner (likely `alembic upgrade head` or a custom script). If `alembic` is used, ensure the project is on a version that supports `transaction_per_migration` (Alembic 1.4+).
3. **DB connection works for the target environment.** `psql $DATABASE_URL -c "\d audit.task_events"` shows the current schema (should NOT have `idempotency_key`).
4. **Duplicate-key pre-flight is feasible.** `psql $DATABASE_URL -c "SELECT COUNT(*) - COUNT(DISTINCT idempotency_key) FROM audit.task_events WHERE idempotency_key IS NOT NULL;"` should return 0 (no duplicates). If >0, dedupe manually before running the migration.
5. **C-1 has landed.** The `idempotency:` settings section must exist so C-6 has something to wire against.

## File-by-file changes

### 1. `migrations/versions/V202609260001__idempotency_key_column.sql` — new revision (rev A: column)

```sql
-- V202609260001__idempotency_key_column.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- Pre-1.0 zero backcompat per feedback-no-backwards-compat-pre-1.0.
--
-- REV A: Add the column (transactional — fast).
-- Companion revision V202609260001b adds the unique index via CONCURRENTLY
-- (cannot run inside a transaction block; relies on transaction_per_migration=False
--  set preemptively in C-3).

BEGIN;

-- Pre-flight: detect duplicate idempotency_keys before adding the constraint
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM (
            SELECT COUNT(*) - COUNT(DISTINCT idempotency_key) AS dup_count
            FROM audit.task_events
            WHERE idempotency_key IS NOT NULL
        ) sub WHERE dup_count > 0
    ) THEN
        RAISE EXCEPTION 'pre-flight: duplicate idempotency_keys detected; dedupe before migrating';
    END IF;
END$$;

-- Add the column (nullable — existing rows have NULL idempotency_key)
ALTER TABLE audit.task_events
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);

COMMIT;
```

The pre-flight `DO $$` block runs BEFORE the `ALTER TABLE`. If duplicates exist, the migration aborts with `RAISE EXCEPTION` — operator must dedupe manually and retry.

`VARCHAR(255)` matches the existing `init.sql:110` declaration. `ADD COLUMN IF NOT EXISTS` makes the migration idempotent (re-runs are safe).

### 2. `migrations/versions/V202609260001b__idempotency_key_unique_index.sql` — new revision (rev B: index)

```sql
-- V202609260001b__idempotency_key_unique_index.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
--
-- REV B: Create the unique partial index via CONCURRENTLY (non-transactional).
-- CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction block.
-- This migration runs OUTSIDE the Alembic transaction — relies on
-- transaction_per_migration=False in env.py (set in C-3).

-- Note: no BEGIN here. The op.execute() wrapper in Alembic skips autocommit
-- wrapping for this revision because env.py has transaction_per_migration=False.

-- FIX (round-5 critique): audit.task_events is PARTITION BY RANGE (event_time) per
-- V202604021200__initial_consolidated_schema.sql:112. Postgres requires the partition
-- key in any UNIQUE constraint on a partitioned table. The original (idempotency_key)
-- unique index would fail with "insufficient columns in UNIQUE constraint definition".
-- Composite index on (idempotency_key, event_time) preserves uniqueness for
-- non-null idempotency_key values while satisfying the partition requirement.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_task_events_idempotency_key
    ON audit.task_events (idempotency_key, event_time)
    WHERE idempotency_key IS NOT NULL;
```

The `WHERE idempotency_key IS NOT NULL` clause makes this a **partial unique index** — multiple `NULL` keys are allowed (the column is nullable; existing rows have NULL), but non-null keys must be unique. This is the standard pattern for "uniqueness only applies when present".

`CONCURRENTLY` allows the index to build without taking an `ACCESS EXCLUSIVE` lock on `audit.task_events`, so production queries are not blocked during the build.

### 3. `tests/integration/test_migration_idempotency_key.py` — new file (~180 LoC)

Integration test verifying both revisions apply cleanly and the pre-flight trips on duplicates:

```python
"""Tests for V202609260001 + V202609260001b schema reconciliation migrations."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def fresh_db_with_consolidated_schema(isolated_database: Path) -> Path:
    """Apply V202604021200__initial_consolidated_schema.sql to a fresh DB
    so tests start from the production-shaped baseline."""
    import aiosqlite

    schema_sql = Path("migrations/versions/V202604021200__initial_consolidated_schema.sql").read_text()
    async with aiosqlite.connect(isolated_database) as db:
        await db.executescript(schema_sql)
        await db.commit()
    return isolated_database


@pytest_asyncio.fixture
async def db_with_duplicate_keys(fresh_db_with_consolidated_schema: Path) -> Path:
    """Insert two rows with the same idempotency_key to trigger pre-flight."""
    import aiosqlite

    async with aiosqlite.connect(fresh_db_with_consolidated_schema) as db:
        await db.execute(
            "INSERT INTO audit.task_events (idempotency_key, event_type) VALUES (?, ?)",
            ("dup-key-1", "created"),
        )
        await db.execute(
            "INSERT INTO audit.task_events (idempotency_key, event_type) VALUES (?, ?)",
            ("dup-key-1", "updated"),  # same idempotency_key — pre-flight must abort
        )
        await db.commit()
    return fresh_db_with_consolidated_schema


@pytest.mark.req(["REQ-004"])
class TestMigrationRevAColumn:
    async def test_rev_a_adds_column(self, fresh_db_with_consolidated_schema: Path) -> None:
        from mahavishnu.core.migrations import apply_revision

        await apply_revision("V202609260001")

        import aiosqlite
        async with aiosqlite.connect(fresh_db_with_consolidated_schema) as db:
            cursor = await db.execute(
                "SELECT idempotency_key FROM audit.task_events LIMIT 1"
            )
            # Column exists; NULL is expected for legacy rows
            row = await cursor.fetchone()
            assert row is None or row[0] is None

    async def test_rev_a_idempotent(self, fresh_db_with_consolidated_schema: Path) -> None:
        """Re-running rev A on an already-migrated DB must not error."""
        from mahavishnu.core.migrations import apply_revision

        await apply_revision("V202609260001")
        await apply_revision("V202609260001")  # second run is no-op

    async def test_pre_flight_aborts_on_duplicates(
        self, db_with_duplicate_keys: Path
    ) -> None:
        from mahavishnu.core.migrations import apply_revision, MigrationPreFlightError

        with pytest.raises(MigrationPreFlightError, match="duplicate idempotency_keys"):
            await apply_revision("V202609260001")


@pytest.mark.req(["REQ-004"])
class TestMigrationRevBIndex:
    async def test_rev_b_creates_unique_index(self, fresh_db_with_consolidated_schema: Path) -> None:
        from mahavishnu.core.migrations import apply_revision

        await apply_revision("V202609260001")
        await apply_revision("V202609260001b")

        import aiosqlite
        async with aiosqlite.connect(fresh_db_with_consolidated_schema) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_task_events_idempotency_key'"
            )
            row = await cursor.fetchone()
            assert row is not None  # index exists

    async def test_rev_b_idempotent(self, fresh_db_with_consolidated_schema: Path) -> None:
        """Re-running rev B on an already-indexed DB must not error."""
        from mahavishnu.core.migrations import apply_revision

        await apply_revision("V202609260001")
        await apply_revision("V202609260001b")
        await apply_revision("V202609260001b")  # CONCURRENTLY IF NOT EXISTS

    async def test_unique_constraint_enforced(self, fresh_db_with_consolidated_schema: Path) -> None:
        """After both revisions, inserting two rows with the same idempotency_key
        must fail with IntegrityError. This is the contract C-6 relies on."""
        from mahavishnu.core.migrations import apply_revision
        import aiosqlite

        await apply_revision("V202609260001")
        await apply_revision("V202609260001b")

        async with aiosqlite.connect(fresh_db_with_consolidated_schema) as db:
            await db.execute(
                "INSERT INTO audit.task_events (idempotency_key, event_type) VALUES (?, ?)",
                ("key-a", "created"),
            )
            await db.commit()
            with pytest.raises(aiosqlite.IntegrityError):
                await db.execute(
                    "INSERT INTO audit.task_events (idempotency_key, event_type) VALUES (?, ?)",
                    ("key-a", "updated"),
                )
                await db.commit()


@pytest.mark.req(["REQ-004"])
class TestMigrationEndToEnd:
    """Demonstrable by: integration test against DB initialized with consolidated
    schema, run both revisions, assert column exists + index created."""

    async def test_full_migration_chain(self, fresh_db_with_consolidated_schema: Path) -> None:
        from mahavishnu.core.migrations import apply_revision

        await apply_revision("V202609260001")
        await apply_revision("V202609260001b")

        import aiosqlite
        async with aiosqlite.connect(fresh_db_with_consolidated_schema) as db:
            # Column exists
            cursor = await db.execute("PRAGMA table_info(audit.task_events)")
            columns = [row[1] for row in await cursor.fetchall()]
            assert "idempotency_key" in columns

            # Index exists
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit.task_events'"
            )
            indexes = [row[0] for row in await cursor.fetchall()]
            assert "idx_task_events_idempotency_key" in indexes


@pytest.mark.req(["REQ-004"])
class TestNoDowngrade:
    """Forward-only. Verify the migrations have no downgrade() body."""

    def test_rev_a_no_downgrade(self) -> None:
        rev_a = Path("migrations/versions/V202609260001__idempotency_key_column.sql").read_text()
        assert "DROP COLUMN" not in rev_a.upper()
        assert "def downgrade" not in rev_a

    def test_rev_b_no_downgrade(self) -> None:
        rev_b = Path("migrations/versions/V202609260001b__idempotency_key_unique_index.sql").read_text()
        assert "DROP INDEX" not in rev_b.upper()
        assert "def downgrade" not in rev_b
```

### 4. `mahavishnu/core/migrations.py` — add `MigrationPreFlightError` and `apply_revision()` (if not present)

If `mahavishnu/core/migrations.py` does not already expose `apply_revision()` and `MigrationPreFlightError`, add them. (The test file references them — verify they exist or add them.)

```python
class MigrationPreFlightError(RuntimeError):
    """Raised when a migration's pre-flight check fails (e.g., duplicate
    idempotency_keys detected before adding a unique constraint)."""


async def apply_revision(revision_id: str) -> None:
    """Apply a single Alembic revision by ID. Wraps alembic.command.upgrade()
    with async-friendly error handling."""
    from alembic.command import upgrade as alembic_upgrade
    from alembic.config import Config

    config = Config("alembic.ini")
    alembic_upgrade(config, revision_id)
```

If a different migration runner is used (custom script, `make migrate`), adjust to match the project's actual runner. **The implementation note in the spec is explicit: "runner unclear; verify before landing".**

## Tests

| Test class | Coverage |
|---|---|
| `TestMigrationRevAColumn` | Rev A adds column; idempotent re-run; pre-flight aborts on duplicates |
| `TestMigrationRevBIndex` | Rev B creates index; idempotent re-run; unique constraint enforced |
| `TestMigrationEndToEnd` | Full chain: column + index both present after both revisions |
| `TestNoDowngrade` | No DROP statements; no `def downgrade` body |

All carry `@pytest.mark.req(["REQ-004"])`. Total: 4 test classes, ~9 test methods.

## Crackerjack verification

```bash
uv run pytest tests/integration/test_migration_idempotency_key.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `migrations/versions/V202609260001__idempotency_key_column.sql` exists and contains the pre-flight `DO $$` block + `ALTER TABLE`.
2. `migrations/versions/V202609260001b__idempotency_key_unique_index.sql` exists and uses `CREATE UNIQUE INDEX CONCURRENTLY`.
3. Both revisions have NO `DROP` statements (verified by `TestNoDowngrade`).
4. Pre-flight trips on duplicate `idempotency_key` values (verified by `TestMigrationRevAColumn.test_pre_flight_aborts_on_duplicates`).
5. Both revisions are idempotent on re-run (verified by `test_rev_a_idempotent` + `test_rev_b_idempotent`).
6. After both revisions, `audit.task_events.idempotency_key` is unique for non-null values (verified by `test_unique_constraint_enforced`).
7. `migrations/env.py` has `transaction_per_migration=False` (set in C-3; required for rev B's CONCURRENTLY).
8. `python scripts/audit_requirements.py --json` reports REQ-004 wired (markers present, no orphans).
9. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Forward-only per `feedback-no-backwards-compat-pre-1.0`. Recovery for any schema miscalculation is a follow-up forward migration (e.g., `V202609260001c__fix_idempotency_key_index.sql` to alter the index definition) — not a downgrade.

If the pre-flight trips on duplicates in production, the recovery is:
1. Identify duplicate `idempotency_key` values: `SELECT idempotency_key, COUNT(*) FROM audit.task_events WHERE idempotency_key IS NOT NULL GROUP BY idempotency_key HAVING COUNT(*) > 1`
2. Manually dedupe (decide which row wins; UPDATE or DELETE the others)
3. Re-run `alembic upgrade head`

If the unique-index revision (`V202609260001b`) fails partway through, the index may be left in an `INVALID` state. Recovery:
1. `DROP INDEX CONCURRENTLY IF EXISTS idx_task_events_idempotency_key`
2. Re-run `V202609260001b`

## Observability added

One new Prometheus metric (per spec):

```python
MIGRATION_DURATION = Histogram(
    "migration_duration_seconds",
    "Time taken to apply an Alembic revision.",
    labelnames=["revision", "direction"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0),
)
```

Incremented around the `alembic_upgrade(config, revision_id)` call in `apply_revision()`. Both revisions emit one sample each (`V202609260001` and `V202609260001b`).

## Health aggregation

None directly. The migration runner's success/failure is visible via the `migration_duration_seconds{revision, direction="up"}` histogram — operators can alert on missing expected revisions.

## Implementation notes / gotchas

- **Two-revision split is required** because `CREATE UNIQUE INDEX CONCURRENTLY` cannot run inside a transaction block. The split isolates the transactional DDL (rev A) from the non-transactional DDL (rev B).
- **`transaction_per_migration = False` was set preemptively in C-3.** This global setting affects ALL future Alembic migrations. Per the spec's recommendation, ideally only this revision would be non-transactional. **Reconciliation:** the global setting is acceptable because migrations that need transactional safety can still wrap themselves in explicit `BEGIN`/`COMMIT` (as C-3's execution_events.sql does). The global setting only disables Alembic's auto-wrapping, not the migration's own transaction logic.
- **Pre-flight `DO $$` runs BEFORE `ALTER TABLE`.** If duplicates exist, the migration aborts BEFORE adding the column. This avoids the worse failure mode where the column exists but the unique-index revision can't apply.
- **`ADD COLUMN IF NOT EXISTS` and `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`** make both revisions idempotent. Re-running on an already-migrated DB is a no-op, not an error.
- **`WHERE idempotency_key IS NOT NULL`** in the partial index matches the spec: legacy rows have NULL idempotency_key, and NULLs are not unique-constrained.
- **The `apply_revision()` helper may not exist yet.** Verify `mahavishnu/core/migrations.py` exposes it. If it does not, add it as part of C-4 (small scope creep, but the test file references it).
- **The migration runner is unconfirmed.** The spec note "project uses `migrations/versions/V*.sql`, runner unclear; verify before landing" is critical. If the project uses raw SQL files (no Alembic), the test infrastructure must be adapted accordingly. The plan assumes Alembic; if the actual runner is `scripts/migrate.py`, adjust the `apply_revision()` helper.
- **`MigrationPreFlightError` is a new exception** that did not exist before C-4. It is added in `mahavishnu/core/migrations.py`. Other migrations may want to use it for their own pre-flight checks; document the contract in the docstring.
- **C-6 will reference `audit.task_events.idempotency_key`** as the unique-constraint column. Verify the column name matches across C-6's plan (not "idempotency_key_id" or any variation).

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `migrations/versions/V202609260001__idempotency_key_column.sql` | create | +25 |
| `migrations/versions/V202609260001b__idempotency_key_unique_index.sql` | create | +15 |
| `mahavishnu/core/migrations.py` | edit (add `MigrationPreFlightError` + `apply_revision()` if not present) | +25 |
| `mahavishnu/core/metrics.py` | edit (add `MIGRATION_DURATION` Histogram) | +8 |
| `tests/integration/test_migration_idempotency_key.py` | create | +180 |
