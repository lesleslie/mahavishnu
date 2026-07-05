"""Quality management CLI commands for Mahavishnu."""

from __future__ import annotations

from pathlib import Path
import subprocess

from oneiric.core.logging import get_logger
import typer

logger = get_logger(__name__)
quality_app = typer.Typer(help="Quality management commands")


def add_quality_commands(parent_app: typer.Typer) -> None:
    """Register quality sub-typer on a parent Typer application."""
    parent_app.add_typer(quality_app, name="quality")


async def run_quality_check(output: str) -> int | None:
    """Run Crackerjack quality check on a string output. Returns score or None.

    Used by openhands_tools.py for async MCP quality evaluation.
    """
    try:
        import crackerjack  # noqa: PLC0415

        score = await crackerjack.evaluate(output)
        return int(score) if score is not None else None
    except Exception as e:
        logger.warning("Crackerjack quality check failed: %s", e)
        return None


@quality_app.command(name="check")
def quality_check(
    path: Path = typer.Argument(Path(), help="Path to check (file or directory)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
) -> None:
    """Run quality checks on a path."""
    typer.echo(f"Quality check for {path}")
    if verbose:
        typer.echo("Verbose output enabled")
    typer.echo("Quality check complete (stub)")


@quality_app.command(name="fix")
def quality_fix(
    path: Path = typer.Argument(Path(), help="Path to fix (file or directory)"),
    auto: bool = typer.Option(False, "--auto", "-a", help="Automatically apply fixes"),
) -> None:
    """Fix quality issues in a path."""
    typer.echo(f"Quality fix for {path}")
    if auto:
        typer.echo("Auto-fixing issues")
        path_str = str(path)
        subprocess.run(["ruff", "check", "--fix", path_str], check=False)  # noqa: S603, S607
        subprocess.run(["ruff", "format", path_str], check=False)  # noqa: S603, S607
        subprocess.run(["ruff", "check", path_str], check=False)  # noqa: S603, S607
    typer.echo("Quality fix complete")
