"""Quality management CLI commands for Mahavishnu."""

from __future__ import annotations

from pathlib import Path

import typer
from oneiric.core.logging import get_logger

from mahavishnu.tui import FallbackRichFormatter, get_console

logger = get_logger(__name__)
quality_app = typer.Typer(help="Quality evaluation and reporting")


def add_quality_commands(parent_app: typer.Typer) -> None:
    """Add quality commands to parent CLI app.

    Args:
        parent_app: Parent typer application to add commands to
    """
    parent_app.add_typer(quality_app, name="quality")


async def run_quality_check(output: str) -> int | None:
    """Run Crackerjack quality check on a string output.

    Returns score or None.

    Used by openhands_tools.py and the 'quality check' CLI command.
    """
    try:
        import crackerjack  # noqa: PLC0415

        score = await crackerjack.evaluate(output)
        return score
    except Exception as e:
        logger.warning("Crackerjack quality check failed: %s", e)
        return None


@quality_app.command(name="check")
def quality_check(
    path: Path = typer.Argument(
        Path("."), help="Path to check (file or directory)"
    ),
    min_score: int = typer.Option(80, help="Minimum acceptable quality score"),
) -> None:
    """Run Crackerjack quality checks and display results with Rich formatting."""
    import asyncio  # noqa: PLC0415

    console = get_console()
    formatter = FallbackRichFormatter(console=console)

    console.print(f"\n[bold cyan]Quality Check:[/bold cyan] {path}\n")

    try:
        import crackerjack  # noqa: PLC0415

        results = asyncio.run(crackerjack.run(str(path)))
        score = results.get("score", 0)
        issues = results.get("issues", [])

        color = "green" if score >= min_score else "red"
        formatter.format_dict(
            {
                "score": f"[{color}]{score}/100[/]",
                "status": f"[{color}]{'PASS' if score >= min_score else 'FAIL'}[/]",
                "issues": len(issues),
                "min_score": min_score,
            },
            title="Quality Results",
        )

        if issues:
            formatter.format_list(
                issues,
                columns=["rule", "message", "file"],
                title="Issues Found",
            )

        if score < min_score:
            raise typer.Exit(code=1)

    except ImportError:
        console.print(
            "[yellow]crackerjack not installed.[/yellow] "
            "Install: [bold]uv add --group ecosystem crackerjack[/bold]"
        )
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Quality check failed")
        console.print(f"[red]Quality check error:[/red] {e}")
        raise typer.Exit(code=1)


@quality_app.command(name="report")
def quality_report(
    path: Path = typer.Argument(Path("."), help="Path to evaluate"),
    output_format: str = typer.Option("table", help="Output format: table or json"),
) -> None:
    """Generate a detailed quality report for a repository path."""
    console = get_console()
    console.print(f"[bold]Quality Report[/bold] for [cyan]{path}[/cyan]")
    console.print("[dim]Run 'quality check' for a quick gate check.[/dim]")
