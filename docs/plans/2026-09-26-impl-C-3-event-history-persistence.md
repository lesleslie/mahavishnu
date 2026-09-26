# C-3: event-history persistence (precondition for C-6 and C-12)

**REQ-NNN:** REQ-003 — Execution events persistence layer
**Risk:** Medium (DB schema change, new exception class, enum modification; no public API breakage)
**Blocks:** C-6 (`pool_route_execute` idempotency path requires `TaskEventType.PENDING`), C-12 (`mahavishnu executions show` needs `get_execution_events(execution_id)`)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator + multi-engine + harness-agnostic. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.
**Status:** Draft — round-4 corrections baked in.

## Goal

Persist workflow lifecycle events to a new `execution_events` table so `mahavishnu executions show` (C-12) has historical data and the idempotency layer in C-6 can atomically transition a task from PENDING → COMPLETED. **Also** add `TaskEventType.PENDING = "pending"` to the existing `StrEnum` — without this, C-6's idempotency path raises `AttributeError` when it sets a row to PENDING, and C-10's historical webhook path silently fails to recognize pending events.

The forward-only posture per `feedback-no-backwards-compat-pre-1.0` means: no `downgrade()` body on the Alembic revision; if the schema turns out wrong, write a follow-up forward migration. This is cheaper than maintaining dual-schema readers.

## Pre-flight checks

1. **C-2 has landed.** The integration test for `event_store.record_execution_event()` consumes `isolated_database` + `safe_publisher_monkeypatch`. Without C-2 fixtures, the test cannot be written.
2. **`TaskEventType` lives at `mahavishnu/core/event_store.py:49-81`.** Read the existing enum before editing — preserve the existing values (CREATED, UPDATED, ..., SYNCED) and append `PENDING` as the LAST value (preserves stable ordering for downstream comparisons).
3. **`IdempotencyStoreUnavailable` consumers exist.** Verify C-6 and C-10 plans reference this exception class. If the plans do not yet exist, the new exception is unused and the audit will flag it as orphan. **Mitigation:** Add the exception with a `__all__` export; C-6 and C-10 will import it explicitly so the audit treats it as wired.
4. **`alembic.ini` and `migrations/env.py` configured.** Confirm `transaction_per_migration = False` is set in env.py (per C-4 pattern) so forward-only Alembic revisions can use `op.execute()` post-COMMIT. **If absent, set it as part of C-3** — preemptive for both this migration's explicit `BEGIN`/`COMMIT` and the C-4 unique-concurrent-index case.
5. **Migration filename follows Bodai convention.** Existing migrations use `V<timestamp>__<name>.sql` (12-digit timestamp). Use `V202609260003__execution_events.sql` per the spec.
6. **`JSONB` column type is supported.** Postgres 12+ has JSONB. If running SQLite locally for tests, use `JSON` type — SQLAlchemy abstracts the difference.

## File-by-file changes

### 1. `mahavishnu/core/event_store.py` — add `PENDING`, `record_execution_event`, `get_execution_events`, `ExecutionEvent` model

Four edits, all in one file:

**Edit A: Add `PENDING = "pending"` to `TaskEventType` StrEnum at lines 49-81.**

Read the existing enum first. Append `PENDING` as the LAST value (do NOT insert alphabetically — C-6 and C-10 plans assume `PENDING` is at the tail):

```python
class TaskEventType(StrEnum):
    """Lifecycle event types for workflow tasks."""
    CREATED = "created"
    UPDATED = "updated"
    # ... existing values preserved unchanged ...
    SYNCED = "synced"
    PENDING = "pending"  # NEW per round-4 review (mahavishnu specialist).
                        # C-6 idempotency path sets PENDING before COMPLETED.
                        # C-10 historical webhook path reads PENDING from the row state column.
```

**Edit B: Add `ExecutionEvent` SQLAlchemy model.**

Below the existing `task_events` model, add (modeling after `task_events` for consistency):

```python
class ExecutionEvent(Base):
    """One row per workflow lifecycle event. Distinct from task_events (idempotency
    tracking in C-6) — this table is for workflow history consumed by C-12."""
    __tablename__ = "execution_events"
    __table_args__ = (
        Index(
            "ix_execution_events_execution_id_occurred_at",
            "execution_id", "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
```

The composite index `(execution_id, occurred_at)` supports `get_execution_events(execution_id)` ordered by `occurred_at ASC` — the most common read pattern.

**Edit C: Add `record_execution_event()` and `get_execution_events()` functions.**

Below the existing `EventStore.append()`:

```python
async def record_execution_event(
    execution_id: str,
    event_type: TaskEventType,
    data: dict[str, Any],
    actor: str,
    *,
    correlation_id: str | None = None,
    occurred_at: datetime | None = None,
) -> ExecutionEvent:
    """Persist one workflow lifecycle event.

    Autoincrement primary key prevents duplicate-row inserts. Duplicate
    (execution_id, event_type, occurred_at) tuples ARE allowed — e.g., two
    CREATED events for the same execution across retries are valid history.
    """
    event = ExecutionEvent(
        execution_id=execution_id,
        event_type=event_type.value,
        data=data,
        actor=actor,
        correlation_id=correlation_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    EXECUTION_EVENTS_TOTAL.labels(event_type=event_type.value).inc()
    return event


async def get_execution_events(execution_id: str) -> list[ExecutionEvent]:
    """Return all events for an execution, ordered by occurred_at ASC."""
    stmt = (
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id)
        .order_by(ExecutionEvent.occurred_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

### 2. `mahavishnu/core/errors.py` — add `IdempotencyStoreUnavailable` exception

Append after the existing `MahavishnuError` base class hierarchy (find the `class MahavishnuError` line and add after the last subclass):

```python
class IdempotencyStoreUnavailable(MahavishnuError):
    """Idempotency store unreachable; fail-CLOSED behavior expected.

    Raised by C-6 idempotency layer when EventStore cannot be reached.
    The C-6 default is to fail-CLOSED (reject the request) rather than fail-open
    (allow duplicates) — per the no-backcompat policy.
    """
```

### 3. `mahavishnu/core/metrics.py` — add 2 Prometheus metrics

Append after the existing task-event counter:

```python
EXECUTION_EVENTS_TOTAL = Counter(
    "execution_events_total",
    "Total execution events persisted, labeled by event_type.",
    labelnames=["event_type"],
)

EXECUTION_EVENT_LOG_LATENCY = Histogram(
    "execution_event_log_latency_seconds",
    "Latency of record_execution_event() from call to commit.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
```

Time `EXECUTION_EVENT_LOG_LATENCY` around the `await session.flush()` call in `record_execution_event()`. Both metrics surface via the existing `/metrics` endpoint on port 8690.

### 4. `mahavishnu/core/health.py` — add `check_event_store` and wire to aggregator

Add a new health check function:

```python
async def check_event_store() -> HealthCheck:
    """Round-4 ops gap-fix: without this, /health reports ok while
    record_execution_event() quietly fails."""
    try:
        await record_execution_event(
            execution_id="__healthcheck__",
            event_type=TaskEventType.PENDING,
            data={},
            actor="healthcheck",
        )
        return HealthCheck(status="ok", detail="event_store reachable")
    except Exception as e:  # ty: ignore[unresolved-attribute] — HealthCheck.detail is str
        return HealthCheck(status="degraded", detail=f"event_store unreachable: {e}")
```

Wire `check_event_store` into the `_register_health_tools` aggregator so `/health` reflects the new persistence path. The aggregator pattern is the same as for `check_event_store` siblings — read `mahavishnu/core/health.py` to find the existing `register()` calls and add `check_event_store` to the list.

### 5. `migrations/env.py` — set `transaction_per_migration = False` (preemptive)

Read `migrations/env.py`; find the `context.configure(...)` call inside `run_migrations_online()`. Add `transaction_per_migration=False` to the kwargs:

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    transaction_per_migration=False,  # NEW per C-3 / C-4 — required for forward-only DDL
)
```

This is preemptive — both C-3 (explicit BEGIN/COMMIT in this migration) and C-4 (`CREATE UNIQUE INDEX CONCURRENTLY`) require it. Doing it here means C-4 doesn't need a "update env.py" pre-flight step.

### 6. `migrations/versions/V202609260003__execution_events.sql` — new forward-only Alembic revision

```sql
-- V202609260003__execution_events.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- Pre-1.0 zero backcompat per feedback-no-backwards-compat-pre-1.0.
--
-- IMPORTANT: This revision uses CREATE INDEX (non-concurrent), which is safe inside
-- an Alembic transaction. The C-4 revision handles the unique-concurrent-index case.

BEGIN;

CREATE TABLE IF NOT EXISTS execution_events (
    id BIGSERIAL PRIMARY KEY,
    execution_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor VARCHAR(255) NOT NULL,
    correlation_id VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_execution_events_execution_id
    ON execution_events (execution_id);
CREATE INDEX IF NOT EXISTS ix_execution_events_execution_id_occurred_at
    ON execution_events (execution_id, occurred_at);

COMMIT;
```

`BIGSERIAL` (not `SERIAL`) supports >2B events per execution over the lifetime of an installation. `TIMESTAMPTZ` (not `TIMESTAMP`) prevents timezone arithmetic bugs when correlating events across pools in different regions.

**No `downgrade()` body.** Forward-only per `feedback-no-backwards-compat-pre-1.0`.

### 7. `tests/integration/test_event_store_execution_events.py` — new file (~200 LoC)

Integration test using C-2 fixtures:

```python
"""Tests for execution_events table + record_execution_event / get_execution_events
plus TaskEventType.PENDING enum value plus IdempotencyStoreUnavailable exception."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mahavishnu.core.event_store import (
    ExecutionEvent,
    TaskEventType,
    get_execution_events,
    record_execution_event,
)


@pytest.mark.req(["REQ-003"])
class TestTaskEventTypePending:
    """REQ-003 acceptance: PENDING enum value works for C-6 + C-10."""

    def test_pending_value(self) -> None:
        assert TaskEventType.PENDING.value == "pending"

    def test_pending_in_iteration(self) -> None:
        assert TaskEventType.PENDING in list(TaskEventType)

    def test_pending_is_strenum_member(self) -> None:
        # StrEnum members are str subclasses — needed for JSON serialization
        assert isinstance(TaskEventType.PENDING, str)

    def test_pending_is_last_value(self) -> None:
        # Per implementation notes: PENDING is appended LAST (not alphabetical)
        # so downstream plans (C-6, C-10) can rely on stable iteration order.
        members = list(TaskEventType)
        assert members[-1] is TaskEventType.PENDING


@pytest.mark.req(["REQ-003"])
class TestRecordExecutionEvent:
    async def test_round_trip(self, isolated_database: Path) -> None:
        await record_execution_event(
            execution_id="exec-001",
            event_type=TaskEventType.PENDING,
            data={"step": 1},
            actor="test-suite",
        )
        events = await get_execution_events("exec-001")
        assert len(events) == 1
        assert events[0].event_type == "pending"
        assert events[0].data == {"step": 1}
        assert events[0].actor == "test-suite"

    async def test_ordered_by_occurred_at(self, isolated_database: Path, frozen_clock) -> None:
        # Three events at three distinct timestamps
        base = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)
        for offset, etype in enumerate([
            TaskEventType.PENDING,
            TaskEventType.UPDATED,
            TaskEventType.SYNCED,
        ]):
            await record_execution_event(
                execution_id="exec-002",
                event_type=etype,
                data={"offset": offset},
                actor="test-suite",
                occurred_at=base.replace(second=offset),
            )
        events = await get_execution_events("exec-002")
        assert [e.event_type for e in events] == ["pending", "updated", "synced"]

    async def test_correlation_id_optional(self, isolated_database: Path) -> None:
        await record_execution_event(
            execution_id="exec-003",
            event_type=TaskEventType.PENDING,
            data={},
            actor="test",
            correlation_id="corr-abc",
        )
        events = await get_execution_events("exec-003")
        assert events[0].correlation_id == "corr-abc"

    async def test_correlation_id_defaults_to_none(self, isolated_database: Path) -> None:
        await record_execution_event(
            execution_id="exec-004",
            event_type=TaskEventType.PENDING,
            data={},
            actor="test",
        )
        events = await get_execution_events("exec-004")
        assert events[0].correlation_id is None


@pytest.mark.req(["REQ-003"])
class TestE2EWorkflowLifecycle:
    """Demonstrable by: e2e test runs a 3-stage workflow, asserts 5+ events returned."""

    async def test_workflow_emits_lifecycle_events(self, isolated_database: Path) -> None:
        exec_id = "exec-workflow-001"
        for etype, step in [
            (TaskEventType.PENDING, "workflow.started"),
            (TaskEventType.UPDATED, "workflow.stage_started"),
            (TaskEventType.UPDATED, "workflow.stage_completed"),
            (TaskEventType.UPDATED, "workflow.stage_started"),
            (TaskEventType.UPDATED, "workflow.stage_completed"),
            (TaskEventType.SYNCED, "workflow.completed"),
        ]:
            await record_execution_event(
                execution_id=exec_id,
                event_type=etype,
                data={"step": step},
                actor="workflow-engine",
            )
        events = await get_execution_events(exec_id)
        assert len(events) >= 5
        assert events[0].event_type == "pending"  # first event is PENDING per C-6 contract
        assert events[-1].event_type == "synced"  # last event is COMPLETED-style


@pytest.mark.req(["REQ-003"])
class TestIdempotencyStoreUnavailableException:
    def test_inherits_mahavishnu_error(self) -> None:
        from mahavishnu.core.errors import IdempotencyStoreUnavailable, MahavishnuError
        assert issubclass(IdempotencyStoreUnavailable, MahavishnuError)

    def test_instantiable(self) -> None:
        from mahavishnu.core.errors import IdempotencyStoreUnavailable
        exc = IdempotencyStoreUnavailable("store down")
        assert str(exc) == "store down"
```

## Tests

| Test class | Coverage |
|---|---|
| `TestTaskEventTypePending` | PENDING enum value, iteration order, str-subclass behavior, last-position |
| `TestRecordExecutionEvent` | round-trip, ordering by `occurred_at`, optional `correlation_id` |
| `TestE2EWorkflowLifecycle` | 3-stage workflow persists 6 events; first=PENDING, last=SYNCED |
| `TestIdempotencyStoreUnavailableException` | inherits MahavishnuError; instantiable; message preserved |

All carry `@pytest.mark.req(["REQ-003"])`. Total: 4 test classes, ~9 test methods.

## Crackerjack verification

```bash
uv run pytest tests/integration/test_event_store_execution_events.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `TaskEventType.PENDING.value == "pending"` (asserted in `TestTaskEventTypePending.test_pending_value`).
2. `execution_events` table exists in DB after `alembic upgrade head` (verified by `TestRecordExecutionEvent.test_round_trip` which reads back the inserted row).
3. `record_execution_event()` + `get_execution_events()` round-trip 6+ events for a 3-stage workflow.
4. `IdempotencyStoreUnavailable` is a subclass of `MahavishnuError`.
5. The Alembic revision has NO `downgrade()` function body (verified by `git grep "def downgrade" migrations/versions/V202609260003`).
6. `python scripts/audit_requirements.py --json` reports REQ-003 wired (markers present, no orphans).
7. The legacy `task_events` table and existing `EventStore.append()` are unchanged (verified by `git diff mahavishnu/core/event_store.py` showing only ADDED lines for the new symbols, no MODIFIED lines).
8. `migrations/env.py` has `transaction_per_migration=False` (verified by `git grep transaction_per_migration migrations/env.py`).
9. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Forward-only per `feedback-no-backwards-compat-pre-1.0`. Recovery for any schema miscalculation is a follow-up forward migration (e.g., `V202609260004__fix_execution_events_data_column.sql`) — not a downgrade. The `TaskEventType.PENDING` enum addition is a single-line change that downstream C-6 and C-10 plans depend on; reverting it would require reverting C-6 and C-10 too. **Treat this commit as a foundation stone — it does not get reverted in isolation.**

If a downstream plan discovers the enum value should have been named differently (e.g., `TaskEventType.QUEUED` instead of `PENDING`), the fix is a forward rename in a future commit + updates to C-6 and C-10 plans. This is more expensive than a single-line rename — getting the name right in this commit matters.

## Observability added

Two new Prometheus metrics (covered above in metrics.py):

- `execution_events_total{event_type}` — Counter; incremented per insert
- `execution_event_log_latency_seconds` — Histogram; flushed per insert

Both surface via the existing `/metrics` endpoint on port 8690 (per CLAUDE.md port table). No new dashboards needed — these metrics follow the same label conventions as existing `task_events_total`.

## Health aggregation

`mahavishnu/core/health.py` `check_event_store()` is wired to the aggregator. The `/health` endpoint surfaces `event_store: ok|degraded` alongside the existing health checks. If `record_execution_event` fails (DB unreachable, deadlock, etc.), `/health` returns 503 — per `mcp-backend-wiring-discipline.md` policy.

## Implementation notes / gotchas

- **Add `PENDING` as the LAST enum value, not alphabetically.** Existing comparisons in C-6 and C-10 plans assume `PENDING` is at the tail. Alphabetical insertion would silently break those references.
- **`ExecutionEvent` is a NEW model, not a sibling of `task_events`.** The `task_events` table is for idempotency tracking (C-6); `execution_events` is for workflow lifecycle history. They share the file but not the schema. Do NOT add foreign-key constraints between them — they are separate concerns.
- **`data JSON NOT NULL DEFAULT '{}'::jsonb`** prevents NULL handling bugs in downstream consumers. C-12's `mahavishnu executions show` reads `event.data` directly and assumes it's a dict.
- **`actor VARCHAR(255)`** matches the existing `task_events.actor` column length. Do not introduce new column lengths without auditing all related schemas.
- **`correlation_id` is optional** because early-emit events (before correlation is established) are valid lifecycle events.
- **`transaction_per_migration = False` in env.py is required** because the migration uses explicit `BEGIN`/`COMMIT`. Without this setting, Alembic wraps the migration in an outer transaction that breaks on `COMMIT`.
- **No `downgrade()` function.** Forward-only. The spec is explicit: "no downgrade body on the Alembic revision".
- **C-6 idempotency layer will reference `TaskEventType.PENDING.value`** as a string literal in some hot paths (DB-level unique constraint). Verify C-6 reads `.value` and not `.name` to keep parity with DB column.
- **`EXECUTION_EVENTS_TOTAL` is incremented AFTER successful flush** — failed inserts do not count. This matches Prometheus Counter semantics and prevents inflated counters from failed writes.
- **`frozen_clock.tick=True`** is required for the ordering test (`test_ordered_by_occurred_at`) because explicit `occurred_at` overrides are passed, but the test also verifies that `time.time()` and `datetime.now()` are consistent — without `tick=True`, the second assertion would fail.
- **`JSON` column type from SQLAlchemy** abstracts JSONB (Postgres) and JSON TEXT (SQLite). Local SQLite tests work; production Postgres uses JSONB. No per-backend branching needed.
- **`HealthCheck` is a TypedDict or dataclass** (verify in `mahavishnu/core/health.py` before writing the return statement). The `ty: ignore[unresolved-attribute]` is a defensive suppression — actual type is verified by `crackerjack run`.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/core/event_store.py` | edit (add PENDING enum + ExecutionEvent model + 2 functions) | +60 |
| `mahavishnu/core/errors.py` | edit (append IdempotencyStoreUnavailable) | +5 |
| `mahavishnu/core/metrics.py` | edit (add 2 Prometheus metrics) | +12 |
| `mahavishnu/core/health.py` | edit (add check_event_store + wire to aggregator) | +20 |
| `migrations/env.py` | edit (set `transaction_per_migration = False`) | +1 |
| `migrations/versions/V202609260003__execution_events.sql` | create | +20 |
| `tests/integration/test_event_store_execution_events.py` | create | +200 |
