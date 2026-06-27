"""Rollback CLI for Plan 1 (Bodai Crow) and Plan 5 (Distilled Workflows).

Audit finding H8 (2026-06-26): new plans lacked alert thresholds, SLOs, and
rollback CLIs. This module adds the surface and the dispatch for two
rollback subcommands. The actual rollback logic lands in a follow-up; the
handlers below are stubs that echo the target so operators have a stable
command line to script against.

Commands:
    mahavishnu rollback bodai-crow --to-version <sha>
    mahavishnu rollback distilled-workflow --id <ulid>
"""

from __future__ import annotations

import typer

rollback_app = typer.Typer(
    name="rollback",
    help="Roll back Bodai Crow and Distilled Workflows artifacts to a prior version.",
)


def rollback_bodai_crow(to_version: str) -> None:
    """Roll back the Bodai Crow HTTP MCP server to a prior git SHA.

    Args:
        to_version: Git SHA to roll back to (Plan 1 server artifact).
    """
    # Stub: actual implementation lands in a follow-up.
    # Echo target so callers can confirm dispatch in shell scripts.
    typer.echo(f"[stub] rollback bodai-crow -> {to_version}")
    typer.echo("not yet implemented")


def rollback_distilled_workflow(id: str) -> None:
    """Roll back a distilled workflow to the version identified by ULID.

    Args:
        id: ULID of the distilled workflow version to roll back to (Plan 5).
    """
    # Stub: actual implementation lands in a follow-up.
    # Echo target so callers can confirm dispatch in shell scripts.
    typer.echo(f"[stub] rollback distilled-workflow -> {id}")
    typer.echo("not yet implemented")


@rollback_app.command("bodai-crow")
def bodai_crow_cmd(
    to_version: str = typer.Option(
        ...,
        "--to-version",
        help="Git SHA to roll back the Bodai Crow server to.",
    ),
) -> None:
    """Roll back the Bodai Crow HTTP MCP server to a prior version."""
    rollback_bodai_crow(to_version=to_version)


@rollback_app.command("distilled-workflow")
def distilled_workflow_cmd(
    id: str = typer.Option(
        ...,
        "--id",
        help="ULID of the distilled workflow version to roll back to.",
    ),
) -> None:
    """Roll back a distilled workflow to the version identified by ULID."""
    rollback_distilled_workflow(id=id)


def add_rollback_commands(main_app: typer.Typer) -> None:
    """Register the rollback sub-app on the main CLI app.

    Args:
        main_app: The main Typer app to attach to.
    """
    main_app.add_typer(rollback_app, name="rollback")


__all__ = [
    "add_rollback_commands",
    "rollback_app",
    "rollback_bodai_crow",
    "rollback_distilled_workflow",
]
