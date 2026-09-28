"""mahavishnu executions {list,show} — inspect workflow execution history."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger
from sqlalchemy import select
import typer

from mahavishnu.core.errors import DatabaseError, ErrorCode, MahavishnuError
from mahavishnu.core.event_store import (
    ExecutionEvent,
    TaskEventType,
    _require_session_factory,
    get_execution_events,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine

logger = get_logger(__name__)
executions_app = typer.Typer(
    help="Inspect workflow executions (LLM dispatch history).",
)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an awaitable, reusing the active loop when one is running.

    ``asyncio.run`` raises ``RuntimeError`` when called inside an
    already-running event loop (e.g. inside ``pytest-asyncio`` tests).
    Detect the active loop and await the coroutine directly so the same
    CLI callable works in both sync CLI invocation and async test
    contexts.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Running loop: drive the coroutine to completion via a fresh loop
    # in a worker thread so we never block the caller's loop.
    import concurrent.futures

    def _driver() -> T:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_driver).result()


@asynccontextmanager
async def _event_session() -> AsyncIterator[Any]:
    """Yield a session bound to the module-level async engine.

    Mirrors the lifetime used by ``record_execution_event`` /
    ``get_execution_events`` so reads stay consistent with writers.
    """
    factory = _require_session_factory()
    async with factory() as session:
        yield session


def _format_event_markdown(event: dict[str, Any] | ExecutionEvent, idx: int) -> str:
    """One event as a markdown bullet.

    Accepts both shapes because there are two callers in this file:

    - ``_list_async`` (line 217) builds a display-form dict with
      ``id``, ``event_type``, ``actor``, ``data``, ``correlation_id``,
      and an ISO-formatted ``occurred_at`` string.
    - ``_watch_loop`` (line 294) passes the raw ``ExecutionEvent``
      ORM instance returned by ``get_execution_events``.
    """
    if isinstance(event, dict):
        return (
            f"{idx + 1}. **{event['event_type']}** "
            f"(@ {event['occurred_at']}, actor={event['actor']})\n"
            f"   - data: {json.dumps(event['data'])[:200]}"
        )
    ts = event.occurred_at.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{idx + 1}. **{event.event_type}** "
        f"(@ {ts}, actor={event.actor})\n"
        f"   - data: {json.dumps(event.data)[:200]}"
    )


def _format_event_raw(event: ExecutionEvent) -> str:
    """One event as a JSON line (newline-delimited)."""
    return json.dumps(
        {
            "id": event.id,
            "event_type": event.event_type,
            "actor": event.actor,
            "data": event.data,
            "correlation_id": event.correlation_id,
            "occurred_at": event.occurred_at.isoformat(),
        }
    )


def _validate_event_type(raw: str, *, flag: str) -> str:
    """Return the canonical enum value, or raise Typer exit on unknown.

    Accepts both the enum NAME (``PENDING``, ``SYNCED``) and the
    lower-case VALUE (``pending``, ``synced``) because
    :class:`TaskEventType` is a :class:`StrEnum` whose ``__call__``
    dispatches on value, not name.
    """
    upper = raw.upper()
    try:
        return TaskEventType[upper].value
    except KeyError:
        typer.echo(f"Unknown {flag}: {raw}", err=True)
        raise typer.Exit(code=1) from None


@executions_app.command("list")
def list_cmd(
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter by TaskEventType (e.g., PENDING, SYNCED).",
    ),
    workflow_id: str | None = typer.Option(
        None,
        "--workflow",
        help="Filter by execution_id prefix.",
    ),
    limit: int = typer.Option(50, "--limit", min=1, max=10_000),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit JSON instead of human-readable text.",
    ),
) -> None:
    """List recent executions."""
    try:
        executions = _run(_list_async(status=status, workflow_id=workflow_id, limit=limit))
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(executions, indent=2, default=str))
        return

    if not executions:
        typer.echo("No executions recorded.")
        return

    for exec_id, events in executions.items():
        typer.echo(f"\n{exec_id} ({len(events)} events)")
        for idx, event in enumerate(events):
            typer.echo(_format_event_markdown(event, idx))


@executions_app.command("show")
def show_cmd(
    execution_id: str = typer.Argument(..., help="Execution ID to inspect."),
    step: str | None = typer.Option(
        None,
        "--step",
        help="Filter to one TaskEventType.",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Stream new events as they arrive.",
    ),
    fmt: str = typer.Option(
        "markdown",
        "--format",
        help="Output format: markdown or raw.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Emit JSON lines (overrides --format).",
    ),
) -> None:
    """Show execution details for a given execution_id."""
    try:
        _run(_show_async(execution_id, step, watch, fmt, raw))
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc


async def _list_async(
    status: str | None,
    workflow_id: str | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Async helper for list command.

    Returns a dict of execution_id -> list of event dicts.
    """
    target_status: str | None = None
    if status is not None:
        target_status = _validate_event_type(status, flag="status")

    try:
        async with _event_session() as session:
            stmt = (
                select(ExecutionEvent).order_by(ExecutionEvent.occurred_at.desc()).limit(limit * 10)
            )
            if target_status is not None:
                stmt = stmt.where(ExecutionEvent.event_type == target_status)
            if workflow_id is not None:
                stmt = stmt.where(ExecutionEvent.execution_id.like(f"{workflow_id}%"))

            events = list((await session.execute(stmt)).scalars().all())
    except DatabaseError as exc:
        raise MahavishnuError(
            f"event store unavailable: {exc}",
            error_code=ErrorCode.DATABASE_CONNECTION_ERROR,
            details={"reason": str(exc)},
        ) from exc

    by_exec: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if len(by_exec) >= limit and event.execution_id not in by_exec:
            continue
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

    if step is not None:
        target_type = _validate_event_type(step, flag="step type")
        events = [e for e in events if e.event_type == target_type]
        if not events:
            typer.echo(f"No events of type {step} for {execution_id}", err=True)
            raise typer.Exit(code=1)

    output_format = "raw" if raw else fmt
    if output_format not in {"markdown", "raw"}:
        typer.echo(
            f"Unknown format: {fmt} (expected 'markdown' or 'raw')",
            err=True,
        )
        raise typer.Exit(code=1)

    for idx, event in enumerate(events):
        if output_format == "raw":
            typer.echo(_format_event_raw(event))
        else:
            typer.echo(_format_event_markdown(event, idx))

    if watch:
        await _watch_new_events(execution_id, events[-1].id, output_format)


async def _watch_new_events(
    execution_id: str,
    last_seen_id: int,
    output_format: str,
) -> None:
    """Poll for new events; print them as they appear."""
    typer.echo("\nWatching for new events (Ctrl-C to stop)...")
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
        except KeyboardInterrupt, SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — surface watch-loop failures
            consecutive_failures += 1
            logger.warning(
                "watch poll failed",
                extra={
                    "consecutive_failures": consecutive_failures,
                    "error": str(exc),
                },
            )
            if consecutive_failures >= max_consecutive_failures:
                typer.echo(
                    f"Watch lost connection after {max_consecutive_failures} retries; aborting",
                    err=True,
                )
                break
