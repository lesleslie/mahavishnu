"""Typer app for the `mahavishnu jot` CLI (R2)."""

from __future__ import annotations

import typer

from mahavishnu.jot.cli import (
    cmd_add,
    cmd_defer,
    cmd_delete,
    cmd_dispatch,
    cmd_done,
    cmd_drain,
    cmd_edit,
    cmd_list,
    cmd_reopen,
    cmd_resurface,
    cmd_retry,
    cmd_search,
    cmd_show,
    cmd_vitals,
)

app = typer.Typer(help="Jot inbox: quick-capture scratchpad for humans and AI agents.")


@app.command()
def list(
    status: str | None = typer.Option(None, "--status", help="Filter: open|done"),
    limit: int = typer.Option(50, "--limit", help="Max results"),
) -> None:
    """List jots, newest first."""
    cmd_list(status=status, limit=limit)


@app.command()
def show(
    handle: str = typer.Argument(..., help="Full ID, short_id, or unambiguous substring"),
) -> None:
    """Show one jot by handle."""
    cmd_show(handle=handle)


@app.command(name="add")
def add(text: str = typer.Argument(..., help="Jot text (quote for multi-word)")) -> None:
    """Manually create a jot."""
    cmd_add(text=text)


@app.command()
def edit(
    handle: str = typer.Argument(..., help="Jot handle"),
    new_text: str = typer.Argument(..., help="Replacement text"),
) -> None:
    """Edit a jot's text."""
    cmd_edit(handle=handle, new_text=new_text)


@app.command()
def done(handle: str = typer.Argument(..., help="Jot handle")) -> None:
    """Mark a jot as done."""
    cmd_done(handle=handle)


@app.command()
def reopen(handle: str = typer.Argument(..., help="Jot handle")) -> None:
    """Reopen a done jot."""
    cmd_reopen(handle=handle)


@app.command()
def vitals() -> None:
    """Print total/open/done counts."""
    cmd_vitals()


@app.command()
def search(
    query: str = typer.Argument(..., help="Substring to search for"),
    limit: int = typer.Option(20, "--limit", help="Max results"),
) -> None:
    """Lexical search across jots."""
    cmd_search(query=query, limit=limit)


@app.command()
def drain(
    query: str | None = typer.Option(None, "--query", help="Substring filter"),
    limit: int = typer.Option(20, "--limit", help="Max candidates to show"),
    include_in_flight: bool = typer.Option(
        False,
        "--include-in-flight/--no-include-in-flight",
        help="Include jots with an in-flight dispatch",
    ),
) -> None:
    """List drain candidates (dispatch / retry / skip)."""
    cmd_drain(query=query, limit=limit, include_in_flight=include_in_flight)


@app.command()
def dispatch(
    handle: str = typer.Argument(..., help="Jot handle"),
) -> None:
    """Dispatch a single jot to the workflow runtime."""
    cmd_dispatch(handle=handle)


@app.command()
def defer(
    handle: str = typer.Argument(..., help="Jot handle"),
    until_ms: int = typer.Option(
        ...,
        "--until-ms",
        help="Epoch ms timestamp to defer until",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Why deferred"),
) -> None:
    """Defer a jot until a specific timestamp (epoch ms)."""
    cmd_defer(handle=handle, until_ms=until_ms, reason=reason)


@app.command(name="delete")
def delete(
    handle: str = typer.Argument(..., help="Jot handle"),
    reason: str | None = typer.Option(None, "--reason", help="Why deleted"),
) -> None:
    """Soft-delete a jot (audit trail preserved in the JSONL log)."""
    cmd_delete(handle=handle, reason=reason)


@app.command()
def retry(
    handle: str = typer.Argument(..., help="Jot handle"),
) -> None:
    """Manually retry a FAILED-dispatched jot."""
    cmd_retry(handle=handle)


@app.command()
def resurface(
    trigger: str = typer.Option(
        "session_start",
        "--trigger",
        help="session_start | tool_result",
    ),
    context_text: str = typer.Option(
        "",
        "--context-text",
        help="Context text for tool_result trigger",
    ),
) -> None:
    """Surface relevant jots for the given context."""
    cmd_resurface(trigger=trigger, context_text=context_text)
