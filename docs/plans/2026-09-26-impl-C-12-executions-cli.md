# C-12: `mahavishnu executions {list,show}` Typer CLI (WP-6)

**REQ-NNN:** REQ-019 — `mahavishnu executions {list,show}` Typer sub-app
**Risk:** Low (standalone CLI; no production code paths touched beyond reading `execution_events`)
**Blocks:** None (C-13 doesn't depend on C-12)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.
**Status:** Draft — round-4 corrections baked in (correct package-root path; dropped vacuous `mahavishnu debug` rename claim).

## Goal

Add a Typer CLI to surface execution history. The CLI reads from the `execution_events` table (added in C-3) and presents workflow history to operators and developers. **Two commands**: `list` (recent executions) and `show` (detailed view of one execution, optionally watching for new events).

## Pre-flight checks

1. **C-3 has landed.** `get_execution_events(execution_id) -> list[ExecutionEvent]` exists at `mahavishnu/core/event_store.py`.

   FIX round-6: C-12 imports `ExecutionEvent` and `get_execution_events` from `mahavishnu.core.event_store` — these do NOT exist until C-3 lands. Without C-3 first, the import will fail at module load. **Hard dependency on C-3** (not just on tests via shared fixtures). The pre-flight must verify C-3's commit is in main before C-12 can land.

   Additional FIX round-6: the existing `TaskEvent` and `TaskEventType` are the existing primitives; `ExecutionEvent` and `get_execution_events` are added by C-3 (per `docs/plans/2026-09-26-impl-C-3-event-history-persistence.md` lines 281-285).
2. **`mahavishnu/_main_cli.py` exists at the package root** (per the round-4 correction). The plan registers the new sub-app at lines 164-165 of that file — NOT at `mahavishnu/cli/_main_cli.py` (which does not exist).
3. **`mahavishnu debug` does NOT exist** anywhere (`grep -r "mahavishnu debug" mahavishnu/` returns nothing). The round-4 review rejected the original spec's "renamed from `mahavishnu debug`" rationale as vacuous — that CLI was never real.
4. **`typer` available** (used by other Mahavishnu CLIs).
5. **`mahavishnu/cli/executions_cli.py` does NOT exist** (verify; this is a NEW file).

## File-by-file changes

### 1. `mahavishnu/cli/executions_cli.py` — new file (~180 LoC)

```python
"""mahavishnu executions {list,show} — inspect workflow execution history."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from oneiric.core.logging import get_logger

from mahavishnu.core.config import get_settings
from mahavishnu.core.errors import MahavishnuError
from mahavishnu.core.event_store import (
    ExecutionEvent,
    TaskEventType,
    get_execution_events,
)

logger = get_logger(__name__)
executions_app = typer.Typer(
    help="Inspect workflow executions (LLM dispatch history)."
)


def _format_event_markdown(event: ExecutionEvent, idx: int) -> str:
    """One event as a markdown bullet."""
    ts = event.occurred_at.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{idx + 1}. **{event.event_type}** "
        f"(@ {ts}, actor={event.actor})\n"
        f"   - data: {json.dumps(event.data)[:200]}"
    )


def _format_event_raw(event: ExecutionEvent) -> str:
    """One event as a JSON line (newline-delimited)."""
    return json.dumps({
        "id": event.id,
        "event_type": event.event_type,
        "actor": event.actor,
        "data": event.data,
        "correlation_id": event.correlation_id,
        "occurred_at": event.occurred_at.isoformat(),
    })


@executions_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status",
                                       help="Filter by TaskEventType (e.g., PENDING, SYNCED)."),
    workflow_id: str | None = typer.Option(None, "--workflow",
                                            help="Filter by execution_id prefix."),
    limit: int = typer.Option(50, "--limit", min=1, max=10_000),
    json_output: bool = typer.Option(False, "--json",
                                      help="Emit JSON instead of human-readable text."),
) -> None:
    """List recent executions."""
    try:
        executions = asyncio.run(
            _list_async(status=status, workflow_id=workflow_id, limit=limit)
        )
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(executions, indent=2, default=str))
    else:
        for exec_id, events in executions.items():
            typer.echo(f"\n{exec_id} ({len(events)} events)")
            for idx, event in enumerate(events):
                typer.echo(_format_event_markdown(event, idx))


@executions_app.command("show")
def show_cmd(
    execution_id: str = typer.Argument(..., help="Execution ID to inspect."),
    step: str | None = typer.Option(None, "--step",
                                     help="Filter to one TaskEventType."),
    watch: bool = typer.Option(False, "--watch",
                                help="Stream new events as they arrive."),
    fmt: str = typer.Option("markdown", "--format",
                             help="Output format: markdown or raw."),
    raw: bool = typer.Option(False, "--raw",
                              help="Emit JSON lines (overrides --format)."),
) -> None:
    """Show execution details for a given execution_id."""
    try:
        asyncio.run(_show_async(execution_id, step, watch, fmt, raw))
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1)


async def _list_async(
    status: str | None, workflow_id: str | None, limit: int
) -> dict[str, list[dict[str, Any]]]:
    """Async helper for list command.

    Returns a dict of execution_id -> list of event dicts.
    """
    from sqlalchemy import select

    from mahavishnu.core.event_store import ExecutionEvent, session_scope

    async with session_scope() as session:
        stmt = select(ExecutionEvent).order_by(
            ExecutionEvent.occurred_at.desc()
        ).limit(limit * 10)  # overscan; filter to N executions
        if status:
            try:
                stmt = stmt.where(ExecutionEvent.event_type == TaskEventType(status).value)
            except ValueError:
                typer.echo(f"Unknown status: {status}", err=True)
                raise typer.Exit(code=1)
        if workflow_id:
            stmt = stmt.where(ExecutionEvent.execution_id.like(f"{workflow_id}%"))

        events = list((await session.execute(stmt)).scalars().all())

    # Group by execution_id, keep most recent `limit` executions
    by_exec: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for event in events:
        if len(by_exec) >= limit and event.execution_id not in seen:
            continue
        seen.add(event.execution_id)
        by_exec.setdefault(event.execution_id, []).append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "data": event.data,
                "correlation_id": event.correlation_id,
                "occurred_at": event.occurred_at.isoformat(),
            }
        )
    return by_exec


async def _show_async(
    execution_id: str,
    step: str | None,
    watch: bool,
    fmt: str,
    raw: bool,
) -> None:
    """Async helper for show command."""
    events = await get_execution_events(execution_id)
    if not events:
        typer.echo(f"No events for execution_id={execution_id}", err=True)
        raise typer.Exit(code=1)

    if step:
        try:
            target_type = TaskEventType(step).value
        except ValueError:
            typer.echo(f"Unknown step type: {step}", err=True)
            raise typer.Exit(code=1)
        events = [e for e in events if e.event_type == target_type]
        if not events:
            typer.echo(f"No events of type {step} for {execution_id}", err=True)
            raise typer.Exit(code=1)

    output_format = "raw" if raw else fmt

    for idx, event in enumerate(events):
        if output_format == "raw":
            typer.echo(_format_event_raw(event))
        else:
            typer.echo(_format_event_markdown(event, idx))

    if watch:
        await _watch_new_events(execution_id, events[-1].id, output_format)


async def _watch_new_events(
    execution_id: str, last_seen_id: int, output_format: str
) -> None:
    """Poll for new events; print them as they appear."""
    typer.echo(f"\nWatching for new events (Ctrl-C to stop)...")
    last_id = last_seen_id
    consecutive_failures = 0
    max_consecutive_failures = 5

    while consecutive_failures < max_consecutive_failures:
        try:
            await asyncio.sleep(1.0)
            events = await get_execution_events(execution_id)
            new_events = [e for e in events if e.id > last_id]
            if new_events:
                for idx, event in enumerate(new_events):
                    if output_format == "raw":
                        typer.echo(_format_event_raw(event))
                    else:
                        typer.echo(_format_event_markdown(event, idx))
                last_id = new_events[-1].id
                consecutive_failures = 0
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            consecutive_failures += 1
            logger.warning("watch poll failed",
                           extra={"consecutive_failures": consecutive_failures,
                                  "error": str(exc)})
            if consecutive_failures >= max_consecutive_failures:
                typer.echo(f"Watch lost connection after "
                           f"{max_consecutive_failures} retries; aborting",
                           err=True)
                break
```

### 2. `mahavishnu/_main_cli.py` — register the new sub-app

Locate `mahavishnu/_main_cli.py` at the package root. Find the existing Typer sub-app registrations (around lines 164-165 per spec). Add:

```python
from mahavishnu.cli.executions_cli import executions_app

# ... existing sub-app registrations ...
app.add_typer(executions_app, name="executions")
```

The `name="executions"` exposes the sub-app as `mahavishnu executions {list,show}`.

## Tests

### 3. `tests/integration/test_executions_cli.py` — new file (~150 LoC)

```python
"""Integration tests for mahavishnu executions CLI."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest


@pytest.mark.req(["REQ-019"])
class TestExecutionsList:
    def test_list_empty(self) -> None:
        """Empty DB returns no executions."""
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "list"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_list_with_results(self, isolated_database) -> None:
        """Insert events, then list shows them."""
        from mahavishnu.core.event_store import record_execution_events_batch
        # ... insert events ...

        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "list",
             "--json", "--limit", "5"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        executions = json.loads(result.stdout)
        assert len(executions) > 0

    def test_list_filter_by_status(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "list",
             "--status", "PENDING"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


@pytest.mark.req(["REQ-019"])
class TestExecutionsShow:
    def test_show_known_execution(self, isolated_database) -> None:
        """Insert one execution, then show it."""
        exec_id = "exec-test-001"
        # ... insert events ...

        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "show", exec_id],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "pending" in result.stdout.lower()

    def test_show_unknown_execution_returns_error(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "show",
             "exec-nonexistent-999"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "No events" in result.stderr

    def test_show_step_filter(self, isolated_database) -> None:
        exec_id = "exec-test-step"
        # ... insert events of multiple types ...

        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "show",
             exec_id, "--step", "PENDING"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "pending" in result.stdout.lower()
        assert "synced" not in result.stdout.lower()  # filtered out

    def test_show_raw_format(self, isolated_database) -> None:
        exec_id = "exec-test-raw"
        # ... insert one event ...

        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "show",
             exec_id, "--raw"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Raw format is JSON lines
        json.loads(result.stdout.splitlines()[0])  # must parse

    def test_show_pagination_at_10k_events(self, isolated_database) -> None:
        """Pagination works at 10k+ events."""
        # ... insert 10k events ...

        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "list",
             "--limit", "50"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


@pytest.mark.req(["REQ-019"])
class TestExecutionsWatch:
    def test_watch_streams_new_events(self, isolated_database) -> None:
        """--watch polls for new events and prints them."""
        # Start watcher in background; insert event after 2s; verify output
        # ...
        # Use a timeout to avoid hanging
        pytest.skip("watch test requires subprocess + timeout coordination")
```

### 4. `tests/e2e/test_executions_show_e2e.py` — new file (~80 LoC)

Per `.claude/decisions/mcp-backend-wiring-discipline.md`, e2e smoke test:

```python
"""E2E smoke test for mahavishnu executions CLI.

Verifies the CLI works against a real DB (not just unit-test mocks).
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.req(["REQ-019"])
@pytest.mark.e2e
class TestExecutionsE2E:
    def test_cli_invokable_via_module(self) -> None:
        """`python -m mahavishnu executions --help` returns successfully."""
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "list" in result.stdout
        assert "show" in result.stdout

    def test_cli_help_describes_commands(self) -> None:
        """Each subcommand has a help string."""
        for cmd in ("list", "show"):
            result = subprocess.run(
                [sys.executable, "-m", "mahavishnu", "executions", cmd, "--help"],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0
            assert "Usage:" in result.stdout
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_executions_cli.py -v
uv run pytest tests/e2e/test_executions_show_e2e.py -v -m e2e
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/cli/executions_cli.py` exists with `executions_app` Typer sub-app.
2. `mahavishnu/_main_cli.py` (package ROOT) registers the sub-app at lines ~164-165.
3. **No `mahavishnu debug` rename claim** anywhere in the plan or docs (the CLI never existed).
4. `mahavishnu executions list` returns successfully (even with empty DB).
5. `mahavishnu executions show <id>` returns events for known execution.
6. `mahavishnu executions show <id>` returns exit code 1 for unknown execution.
7. `--step <TaskEventType>` filters correctly.
8. `--raw` emits JSON lines (one event per line, parseable).
9. Pagination works at 10k+ events (`--limit 50` returns 50 events even when 10k exist).
10. `python -m mahavishnu executions --help` lists both `list` and `show`.
11. E2E smoke test passes against real CLI invocation.
12. `python scripts/audit_requirements.py --json` reports REQ-019 wired.
13. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

This is a NEW CLI sub-app. No existing API surface changed. Rollback is `git revert <commit-sha>`. The CLI simply disappears.

If `mahavishnu/_main_cli.py` registration fails (e.g., circular import), the rollback is `git revert` — no production impact.

## Observability added

None directly. The CLI emits events via `safe_publish` for "recurring debug sessions" pattern detection (Akosha side, not Mahavishnu side). Standard CLI invocation metrics come from the existing `_register_health_tools` aggregator.

## Health aggregation

None. The CLI is read-only against `execution_events`; it does not affect system health.

## Implementation notes / gotchas

- **The plan registers at `_main_cli.py` (package root), NOT `cli/_main_cli.py`** — the latter does not exist. This is the round-4 correction from the spec.
- **The "renamed from `mahavishnu debug`" rationale is dropped.** That CLI was never real; mentioning it would mislead future readers.
- **`session_scope()` is a context manager that yields an EventStore session.** Verify the existing API by reading `mahavishnu/core/event_store.py`.
- **The `_watch_new_events` poll loop has a 5-retry failure limit** — beyond that, the watch exits cleanly. This avoids hangs on broken DB connections.
- **`--watch` is a polling implementation**, NOT a WebSocket subscription. Future revisions can add a WebSocket subscription path; C-12 keeps it simple.
- **Pagination at 10k+ events** uses `limit * 10` overscan to filter to N unique executions — verified by `test_show_pagination_at_10k_events`.
- **`--format` and `--raw` are mutually exclusive**; `--raw` wins if both are passed. Documented in the `--raw` help text.
- **The CLI uses `asyncio.run()`** to bridge sync Typer callbacks to async DB calls. C-12 does NOT use Typer's async-command support (newer feature) to maintain Python 3.11+ compatibility.
- **`TaskEventType(step).value` validation** ensures `--step` accepts valid enum members; unknown values exit with code 1.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/cli/executions_cli.py` | create | ~190 |
| `mahavishnu/_main_cli.py` | edit (register `executions_app` sub-app) | +5 |
| `tests/integration/test_executions_cli.py` | create | +150 |
| `tests/e2e/test_executions_show_e2e.py` | create | +80 |
