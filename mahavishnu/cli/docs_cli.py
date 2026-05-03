"""Docs audit CLI commands for ecosystem-wide documentation health checks."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import typer

_ECOSYSTEM_DEFAULT = Path("settings/ecosystem.yaml")


def add_docs_commands(app: typer.Typer) -> None:
    """Register 'docs' subcommand group on *app*."""
    docs_app = typer.Typer(help="Ecosystem documentation health commands")
    app.add_typer(docs_app, name="docs")

    @docs_app.command("audit")
    def audit(
        ecosystem: Path = typer.Option(
            _ECOSYSTEM_DEFAULT,
            "--ecosystem",
            "-e",
            help="Path to ecosystem.yaml",
        ),
        output: str = typer.Option(
            "text",
            "--output",
            "-o",
            help="Output format: text | json | markdown",
        ),
        write: Path | None = typer.Option(
            None,
            "--write",
            "-w",
            help="Write report to file instead of stdout",
        ),
        include_files: bool = typer.Option(
            False,
            "--include-files",
            help="Include file-level cleanup candidates (markdown only)",
        ),
    ) -> None:
        """Audit docs directories across active Bodai ecosystem repos."""
        # Import from scripts/ (added to pythonpath in pyproject.toml)
        try:
            from audit_ecosystem_docs import (  # type: ignore[import]
                load_active_repos,
                render_markdown,
                render_text,
                summarize_repo,
            )
        except ImportError:
            typer.echo(
                "audit_ecosystem_docs module not found. Ensure scripts/ is on PYTHONPATH.",
                err=True,
            )
            raise typer.Exit(1)

        if not ecosystem.exists():
            typer.echo(f"Ecosystem file not found: {ecosystem}", err=True)
            raise typer.Exit(1)

        if output not in ("text", "json", "markdown"):
            typer.echo(f"Invalid output format: {output!r}. Use text, json, or markdown.", err=True)
            raise typer.Exit(1)

        repos = load_active_repos(ecosystem)
        summaries = [summarize_repo(repo) for repo in repos]

        if output == "json":
            rendered = json.dumps([asdict(s) for s in summaries], indent=2)
        elif output == "markdown":
            rendered = render_markdown(summaries, include_files=include_files)
        else:
            rendered = render_text(summaries)

        if write:
            write.parent.mkdir(parents=True, exist_ok=True)
            write.write_text(rendered)
            typer.echo(f"Report written to {write}")
        else:
            typer.echo(rendered)
