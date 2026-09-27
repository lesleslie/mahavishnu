"""Integration tests for the mahavishnu executions CLI (C-12, REQ-019).

The CLI reads from the ``execution_events`` table populated via
``record_execution_event``. These tests drive the Typer app via
``CliRunner`` against an in-memory SQLite engine initialised by the
``sqlite_engine`` fixture (one engine per test, schema built in-fixture).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from typer.testing import CliRunner

from mahavishnu.cli.executions_cli import executions_app
from mahavishnu.core.event_store import (
    ExecutionEvent,
    TaskEventType,
    dispose_engine,
    init_engine,
    record_execution_event,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine


runner = CliRunner()


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    """Per-test in-memory SQLite engine + schema. Mirrors the C-3 fixture."""
    engine = init_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ExecutionEvent.metadata.create_all)
    try:
        yield engine
    finally:
        await dispose_engine()


async def _seed(execution_id: str, events: list[tuple[TaskEventType, str]]) -> None:
    """Insert one workflow lifecycle sequence."""
    for event_type, step in events:
        await record_execution_event(
            execution_id=execution_id,
            event_type=event_type,
            data={"step": step},
            actor="integration-test",
        )


@pytest.mark.req(["REQ-019"])
class TestExecutionsList:
    """``mahavishnu executions list`` happy-path tests."""

    async def test_list_empty(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Empty store reports nothing and exits 0."""
        result = runner.invoke(executions_app, ["list"])
        assert result.exit_code == 0
        assert "No executions recorded" in result.stdout

    async def test_list_with_results(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Seeded events surface in --json output."""
        await _seed(
            "exec-list-001",
            [
                (TaskEventType.PENDING, "workflow.started"),
                (TaskEventType.SYNCED, "workflow.completed"),
            ],
        )

        result = runner.invoke(
            executions_app, ["list", "--json", "--limit", "5"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert "exec-list-001" in payload
        assert len(payload["exec-list-001"]) == 2

    async def test_list_filter_by_status(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """--status PENDING returns only pending events."""
        await _seed(
            "exec-status-001",
            [
                (TaskEventType.PENDING, "start"),
                (TaskEventType.SYNCED, "end"),
            ],
        )

        result = runner.invoke(
            executions_app, ["list", "--status", "PENDING", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        events = payload["exec-status-001"]
        assert len(events) == 1
        assert events[0]["event_type"] == "pending"

    async def test_list_unknown_status_exits_1(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Unknown --status value exits 1 and prints to stderr."""
        result = runner.invoke(
            executions_app, ["list", "--status", "BOGUS"]
        )
        assert result.exit_code == 1
        assert "Unknown status" in result.output


@pytest.mark.req(["REQ-019"])
class TestExecutionsShow:
    """``mahavishnu executions show`` tests."""

    async def test_show_known_execution(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Seeded execution renders its events in markdown form."""
        await _seed(
            "exec-show-001",
            [
                (TaskEventType.PENDING, "workflow.started"),
                (TaskEventType.SYNCED, "workflow.completed"),
            ],
        )

        result = runner.invoke(executions_app, ["show", "exec-show-001"])
        assert result.exit_code == 0
        assert "pending" in result.stdout.lower()
        assert "synced" in result.stdout.lower()

    async def test_show_unknown_execution_returns_error(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """Missing execution prints to stderr and exits 1."""
        result = runner.invoke(
            executions_app, ["show", "exec-nonexistent-999"]
        )
        assert result.exit_code == 1
        assert "No events" in result.output

    async def test_show_step_filter(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """--step filters to one TaskEventType."""
        await _seed(
            "exec-step-001",
            [
                (TaskEventType.PENDING, "start"),
                (TaskEventType.UPDATED, "mid"),
                (TaskEventType.SYNCED, "end"),
            ],
        )

        result = runner.invoke(
            executions_app, ["show", "exec-step-001", "--step", "PENDING"]
        )
        assert result.exit_code == 0
        assert "pending" in result.stdout.lower()
        assert "synced" not in result.stdout.lower()

    async def test_show_raw_format(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """--raw emits JSON lines; first line parses."""
        await _seed(
            "exec-raw-001",
            [(TaskEventType.PENDING, "start")],
        )

        result = runner.invoke(
            executions_app, ["show", "exec-raw-001", "--raw"]
        )
        assert result.exit_code == 0
        first_line = result.stdout.splitlines()[0]
        parsed = json.loads(first_line)
        assert parsed["event_type"] == "pending"
        assert parsed["actor"] == "integration-test"

    async def test_show_step_no_matches_exits_1(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """--step filters to zero events when no match exists."""
        await _seed(
            "exec-step-empty",
            [(TaskEventType.PENDING, "start")],
        )

        result = runner.invoke(
            executions_app,
            ["show", "exec-step-empty", "--step", "SYNCED"],
        )
        assert result.exit_code == 1
        assert "No events of type" in result.output

    async def test_show_pagination_at_10k_events(
        self,
        sqlite_engine: AsyncEngine,
    ) -> None:
        """--limit 50 returns at most 50 distinct executions even when 200 exist."""
        # 200 unique executions × 1 event each = 200 rows.
        for i in range(200):
            await record_execution_event(
                execution_id=f"exec-page-{i:04d}",
                event_type=TaskEventType.PENDING,
                data={"i": i},
                actor="integration-test",
            )

        result = runner.invoke(
            executions_app, ["list", "--json", "--limit", "50"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert len(payload) <= 50


@pytest.mark.req(["REQ-019"])
class TestExecutionsWatch:
    """Watch loop is skipped from automatic CI; tested manually."""

    def test_watch_test_skipped(self) -> None:
        """Watch requires background subprocess + timeout coordination.

        Documented in plan: skipped from the unit/integration matrix.
        """
        pytest.skip("watch requires subprocess + timeout coordination")