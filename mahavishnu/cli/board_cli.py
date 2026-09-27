"""``mahavishnu board {init,status,validate}`` — companion CLIs.

Manual management for the local ``.mahavishnu/board.md`` file. These
commands cover the case where operators want to bootstrap, inspect or
sanity-check a board without running the watcher daemon.
"""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003 - needed at runtime: typer eval's string annotations

from oneiric.core.logging import get_logger
import typer

from mahavishnu.core.errors import MahavishnuError, MarkdownParseError
from mahavishnu.jot.markdown_parser import parse_board

logger = get_logger(__name__)
board_app = typer.Typer(
    help="Manage the local .mahavishnu/board.md file (jot board)",
    no_args_is_help=True,
)


DEFAULT_BOARD_TEMPLATE = (
    "# Mahavishnu Jot Board\n\n## Backlog\n\n## Ready\n\n## In Progress\n\n## Done\n"
)


@board_app.command("init")
def init_cmd(
    path: Path = typer.Option(".mahavishnu/board.md", "--path", help="Path to the board file"),
) -> None:
    """Initialize an empty board file with default section headers."""
    if path.exists():
        typer.echo(f"Board already exists at {path}", err=True)
        raise typer.Exit(code=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_BOARD_TEMPLATE)
    typer.echo(f"Initialized board at {path}")


@board_app.command("status")
def status_cmd(
    path: Path = typer.Option(".mahavishnu/board.md", "--path", help="Path to the board file"),
) -> None:
    """Show per-section card counts parsed from the board."""
    if not path.exists():
        typer.echo(f"No board at {path}", err=True)
        raise typer.Exit(code=1)
    cards = asyncio.run(parse_board(path.read_text()))
    counts: dict[str, int] = {}
    for card in cards:
        section = str(card.get("status", "backlog"))
        counts[section] = counts.get(section, 0) + 1
    for section in ("backlog", "ready", "in_progress", "done"):
        typer.echo(f"{section}: {counts.get(section, 0)}")


@board_app.command("validate")
def validate_cmd(
    path: Path = typer.Option(".mahavishnu/board.md", "--path", help="Path to the board file"),
) -> None:
    """Validate board syntax against the Oneiric schema."""
    if not path.exists():
        typer.echo(f"No board at {path}", err=True)
        raise typer.Exit(code=1)
    try:
        cards = asyncio.run(parse_board(path.read_text()))
    except MarkdownParseError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"OK: {len(cards)} cards parsed and validated")
