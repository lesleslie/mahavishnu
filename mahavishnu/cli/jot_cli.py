"""Typer app for the `mahavishnu jot` CLI (R2)."""
from __future__ import annotations

import typer

from mahavishnu.jot.cli import (
    cmd_add,
    cmd_done,
    cmd_edit,
    cmd_list,
    cmd_reopen,
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
def show(handle: str = typer.Argument(..., help="Full ID, short_id, or unambiguous substring")) -> None:
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