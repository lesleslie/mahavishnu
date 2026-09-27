"""Unit tests for C-3 event-store additions.

Covers:
- TaskEventType.PENDING enum value (REQ-003)
- IdempotencyStoreUnavailable exception (REQ-003)
- ExecutionEvent SQLAlchemy model round-trip via in-memory SQLite
- record_execution_event / get_execution_events module-level functions

These tests are unit-scoped: they do not require the isolated_database
fixture (which depends on a Database → Path contract that is not part of
C-3). They exercise the SQLAlchemy model directly against an in-memory
aiosqlite engine created via the public ``init_engine`` entry point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.core.errors import (
    IdempotencyStoreUnavailable,
    MahavishnuError,
)
from mahavishnu.core.event_store import (
    ExecutionEvent,
    TaskEventType,
    dispose_engine,
    get_execution_events,
    init_engine,
    record_execution_event,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

# ---------------------------------------------------------------------------
# TaskEventType.PENDING
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-003"])
class TestTaskEventTypePending:
    """REQ-003 acceptance: PENDING enum value works for C-6 + C-10."""

    def test_pending_value(self) -> None:
        """The PENDING enum member must serialize to the string 'pending'."""
        assert TaskEventType.PENDING.value == "pending"

    def test_pending_in_iteration(self) -> None:
        """PENDING must be discoverable via ``TaskEventType`` iteration."""
        assert TaskEventType.PENDING in list(TaskEventType)

    def test_pending_is_strenum_member(self) -> None:
        """StrEnum members are str subclasses — needed for JSON serialization."""
        assert isinstance(TaskEventType.PENDING, str)

    def test_pending_is_last_value(self) -> None:
        """PENDING must be the LAST enum value, not alphabetical.

        C-6 and C-10 plans assume stable iteration order so the enum
        value can be referenced by ordinal in hot-path comparisons.
        """
        members = list(TaskEventType)
        assert members[-1] is TaskEventType.PENDING


# ---------------------------------------------------------------------------
# IdempotencyStoreUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-003"])
class TestIdempotencyStoreUnavailableException:
    """REQ-003 acceptance: IdempotencyStoreUnavailable is wired into the
    MahavishnuError hierarchy."""

    def test_inherits_mahavishnu_error(self) -> None:
        """IdempotencyStoreUnavailable must inherit from MahavishnuError."""
        assert issubclass(IdempotencyStoreUnavailable, MahavishnuError)

    def test_instantiable_with_default_message(self) -> None:
        """The exception can be raised with no args (uses default message)."""
        exc = IdempotencyStoreUnavailable()
        # MahavishnuError.__str__ prefixes with [MHV-XXX]; assert the
        # message portion matches the default.
        assert "Idempotency store unreachable" in str(exc)

    def test_instantiable_with_custom_message(self) -> None:
        """Custom message is preserved on the exception."""
        exc = IdempotencyStoreUnavailable("store down")
        assert "store down" in str(exc)


# ---------------------------------------------------------------------------
# ExecutionEvent model + record/get functions
# ---------------------------------------------------------------------------


@pytest.fixture
async def sqlite_engine() -> AsyncEngine:
    """Create an in-memory SQLite engine for the duration of one test."""
    engine = init_engine("sqlite+aiosqlite:///:memory:")
    # Create the schema explicitly (no Alembic in unit tests).
    async with engine.begin() as conn:
        from sqlalchemy import event

        @event.listens_for(conn.sync_engine, "connect")
        def _enable_fk(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        await conn.run_sync(ExecutionEvent.metadata.create_all)
    try:
        yield engine
    finally:
        await dispose_engine()


@pytest.mark.req(["REQ-003"])
class TestExecutionEventModel:
    """ExecutionEvent SQLAlchemy model: shape and column types."""

    def test_tablename(self) -> None:
        """The model maps to the ``execution_events`` table."""
        assert ExecutionEvent.__tablename__ == "execution_events"

    def test_columns_typed(self) -> None:
        """Mapped columns carry the documented types."""
        from sqlalchemy import JSON, DateTime, Integer, String

        execution_id_col = ExecutionEvent.__table__.c["execution_id"]
        assert isinstance(execution_id_col.type, String)
        assert execution_id_col.type.length == 255

        event_type_col = ExecutionEvent.__table__.c["event_type"]
        assert isinstance(event_type_col.type, String)
        assert event_type_col.type.length == 64

        data_col = ExecutionEvent.__table__.c["data"]
        assert isinstance(data_col.type, JSON)

        id_col = ExecutionEvent.__table__.c["id"]
        assert isinstance(id_col.type, Integer)

        occurred_at_col = ExecutionEvent.__table__.c["occurred_at"]
        assert isinstance(occurred_at_col.type, DateTime)


@pytest.mark.req(["REQ-003"])
class TestRecordExecutionEventRoundTrip:
    """record_execution_event + get_execution_events round-trip."""

    async def test_round_trip(self, sqlite_engine: AsyncEngine) -> None:
        """Insert one event, read it back, assert fields match."""
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

    async def test_ordered_by_occurred_at(self, sqlite_engine: AsyncEngine) -> None:
        """Three events at three distinct timestamps return in order."""
        base = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)
        for offset, etype in enumerate(
            [
                TaskEventType.PENDING,
                TaskEventType.UPDATED,
                TaskEventType.COMPLETED,
            ],
        ):
            await record_execution_event(
                execution_id="exec-002",
                event_type=etype,
                data={"offset": offset},
                actor="test-suite",
                occurred_at=base.replace(second=offset),
            )
        events = await get_execution_events("exec-002")
        assert [e.event_type for e in events] == ["pending", "updated", "completed"]

    async def test_correlation_id_optional(self, sqlite_engine: AsyncEngine) -> None:
        """Correlation ID round-trips when explicitly provided."""
        await record_execution_event(
            execution_id="exec-003",
            event_type=TaskEventType.PENDING,
            data={},
            actor="test",
            correlation_id="corr-abc",
        )
        events = await get_execution_events("exec-003")
        assert events[0].correlation_id == "corr-abc"

    async def test_correlation_id_defaults_to_none(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Correlation ID defaults to None when not provided."""
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
    """End-to-end: a 3-stage workflow persists ≥ 5 events with PENDING first."""

    async def test_workflow_emits_lifecycle_events(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Six lifecycle events round-trip; first=PENDING, last=COMPLETED."""
        exec_id = "exec-workflow-001"
        for etype, step in [
            (TaskEventType.PENDING, "workflow.started"),
            (TaskEventType.UPDATED, "workflow.stage_started"),
            (TaskEventType.UPDATED, "workflow.stage_completed"),
            (TaskEventType.UPDATED, "workflow.stage_started"),
            (TaskEventType.UPDATED, "workflow.stage_completed"),
            (TaskEventType.COMPLETED, "workflow.completed"),
        ]:
            await record_execution_event(
                execution_id=exec_id,
                event_type=etype,
                data={"step": step},
                actor="workflow-engine",
            )
        events = await get_execution_events(exec_id)
        assert len(events) >= 5
        assert events[0].event_type == "pending"
        assert events[-1].event_type == "completed"


@pytest.mark.req(["REQ-003"])
class TestEngineInit:
    """Engine init / dispose round-trip."""

    async def test_engine_required_before_record(self) -> None:
        """Calling record_execution_event without an initialised engine raises."""
        from mahavishnu.core.errors import DatabaseError

        await dispose_engine()
        with pytest.raises(DatabaseError):
            await record_execution_event(
                execution_id="exec-x",
                event_type=TaskEventType.PENDING,
                data={},
                actor="test",
            )


@pytest.mark.req(["REQ-003"])
class TestPrometheusMetrics:
    """Smoke-test the Prometheus metrics on a successful insert."""

    async def test_counter_increments(self, sqlite_engine: AsyncEngine) -> None:
        """The execution_events_total counter increments on insert."""
        from mahavishnu.core.event_store import EXECUTION_EVENTS_TOTAL

        before = EXECUTION_EVENTS_TOTAL.labels(event_type="pending")._value.get()
        await record_execution_event(
            execution_id="exec-metrics-001",
            event_type=TaskEventType.PENDING,
            data={"k": "v"},
            actor="test",
        )
        after = EXECUTION_EVENTS_TOTAL.labels(event_type="pending")._value.get()
        assert after == before + 1
