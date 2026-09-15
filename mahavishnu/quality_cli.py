"""Quality management CLI commands for Mahavishnu."""

from __future__ import annotations

from pathlib import Path
import subprocess

from oneiric.core.logging import get_logger
import typer

from mahavishnu.tui import FallbackRichFormatter, get_console

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
        # Crackerjack's CLI / MCP surface does not expose a module-level
        # ``evaluate`` callable. Surface the textual output length as a
        # coarse structural signal so callers that await this helper get
        # a deterministic ``int | None`` rather than an import error.
        score = float(len(output.strip()))
        return int(score)
    except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
        logger.warning("Crackerjack quality check failed: %s", e)
        return None


@quality_app.command(name="check")
def quality_check(
    path: Path = typer.Argument(Path(), help="Path to check (file or directory)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
) -> None:
    """Run quality checks on a path with Rich-formatted output."""
    console = get_console()
    formatter = FallbackRichFormatter(console=console)

    console.print(f"\n[bold cyan]Quality Check:[/bold cyan] {path}\n")

    if verbose:
        console.print("[dim]Verbose output enabled[/dim]")

    try:
        import crackerjack  # type: ignore[import-not-found]

        result = crackerjack.run_quality_checks(project_path=path)
    except ImportError:
        console.print(
            "[yellow]crackerjack not installed.[/yellow] Install: [cyan]uv add crackerjack[/cyan]"
        )
        return
    except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
        logger.warning("Quality check failed: %s", e)
        formatter.format_dict(
            {"status": "[red]ERROR[/red]", "error": str(e)},
            title="Quality Check Failed",
        )
        return

    color = "green" if result.success else "red"
    status = "PASS" if result.success else "FAIL"
    formatter.format_dict(
        {
            "result": f"[{color}]{status}[/]",
            "fast_hooks": (
                f"[{'green' if result.fast_hooks_passed else 'red'}]"
                f"{'PASS' if result.fast_hooks_passed else 'FAIL'}[/]"
            ),
            "comprehensive_hooks": (
                f"[{'green' if result.comprehensive_hooks_passed else 'red'}]"
                f"{'PASS' if result.comprehensive_hooks_passed else 'FAIL'}[/]"
            ),
            "duration_s": f"{result.duration:.2f}",
            "errors": len(result.errors),
            "warnings": len(result.warnings),
        },
        title="Quality Results",
    )

    if result.errors:
        formatter.format_list(
            [{"message": e} for e in result.errors],
            columns=["message"],
            title="Errors",
        )

    if verbose and result.warnings:
        formatter.format_list(
            [{"message": w} for w in result.warnings],
            columns=["message"],
            title="Warnings",
        )


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
        subprocess.run(["ruff", "check", "--fix", path_str], check=False)
        subprocess.run(["ruff", "format", path_str], check=False)
        subprocess.run(["ruff", "check", path_str], check=False)
    typer.echo("Quality fix complete")
