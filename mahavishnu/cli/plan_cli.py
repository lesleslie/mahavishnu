"""`mahavishnu plan` CLI subcommand.

Mirrors mcp__mahavishnu__plan_* tools. Read commands (list, show, vitals,
search) use PlanIndexStore against a local Dhara. purge is an operator
escape hatch for explicit Dhara-record deletion (REQ-PLAN-... deferral
to follow-on CLI; placeholder returns "not yet implemented" until then).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

import typer

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara  # dev-time only; production uses real Dhara

if TYPE_CHECKING:
    from collections.abc import Coroutine

__all__ = ["plan_app"]

plan_app = typer.Typer(help="Plan index commands (mirror mcp__mahavishnu__plan_*)")


def _get_store() -> PlanIndexStore:
    """Return a PlanIndexStore.

    Production reads ``MAHAVISHNU_DHARA_URL`` to construct a real Dhara
    client; the dev/test fallback uses ``FakeDhara`` so the CLI works
    without a running Dhara.
    """
    if os.environ.get("MAHAVISHNU_DHARA_URL"):
        # Real-Dhara wiring deferred to follow-on PR. For now raise to
        # avoid silently masking operator intent.
        raise NotImplementedError(
            "MAHAVISHNU_DHARA_URL is set but real-Dhara CLI wiring is not yet implemented"
        )
    return PlanIndexStore(FakeDhara())


def _run_async[T](coro: Coroutine[object, object, T]) -> T:
    """Bridge for running async coroutines from sync CLI commands."""
    return asyncio.run(coro)


@plan_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
    topic: str | None = typer.Option(None, "--topic", help="Filter by topic"),
    limit: int = typer.Option(50, "--limit", help="Max records to return"),
) -> None:
    """List plans."""
    store = _get_store()
    if status:
        records = _run_async(store.list_by_status(status, limit=limit))
    elif topic:
        records = _run_async(store.list_by_topic(topic, limit=limit))
    else:
        records = _run_async(store.list_all(limit=limit))
    typer.echo(json.dumps(records, indent=2, default=str))


@plan_app.command("show")
def show_cmd(plan_id: str = typer.Argument(..., help="32-hex plan_id or 8-hex prefix")) -> None:
    """Show one plan by plan_id."""
    store = _get_store()
    record = _run_async(store.get(PlanId(plan_id)))
    if record is None:
        typer.echo(f"Plan not found: {plan_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(record, indent=2, default=str))


@plan_app.command("vitals")
def vitals_cmd() -> None:
    """Show plan index vitals."""
    store = _get_store()
    v = _run_async(store.vitals())
    typer.echo(json.dumps(v, indent=2, default=str))


@plan_app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Lexical query for title + topic"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Search plans by lexical match."""
    store = _get_store()
    results = _run_async(store.search(query, limit=limit))
    typer.echo(json.dumps(results, indent=2, default=str))


@plan_app.command("purge")
def purge_cmd(plan_id: str = typer.Argument(..., help="Plan to purge from Dhara")) -> None:
    """Operator escape hatch — explicit Dhara-record deletion.

    PLACEHOLDER: returns "not yet implemented" until the broader
    decommission story (Open Question #3) ships.
    """
    typer.echo(f"purge for {plan_id} not yet implemented (see Open Question #3)")
    raise typer.Exit(code=2)
