"""
Metrics commands for Mahavishnu CLI.

Provides commands for collecting and reporting on test coverage
and other quality metrics across the Mahavishnu ecosystem.
"""

from pathlib import Path
import sys

from rich.console import Console
from rich.table import Table
import typer

# Create metrics app
metrics_app = typer.Typer(help="Metrics collection and reporting for the Mahavishnu ecosystem")
console = Console()


@metrics_app.command("collect")
def collect_metrics(
    create_issues: bool = typer.Option(
        False,
        "--create-issues",
        help="Create coordination issues for repos below coverage threshold",
    ),
    min_coverage: float = typer.Option(
        80.0,
        "--min-coverage",
        help="Minimum coverage threshold (default: 80.0)",
    ),
    store_metrics: bool = typer.Option(
        False,
        "--store-metrics",
        help="Store metrics in Session-Buddy for historical tracking",
    ),
    output_format: str = typer.Option(
        "text",
        "--output",
        help="Output format: text or json",
    ),
):
    """Collect metrics across all repositories in the ecosystem.

    This command scans all repositories defined in settings/repos.yaml,
    collects test coverage data, and generates a comprehensive report.

    Example:
        mahavishnu metrics collect --create-issues --min-coverage 80
    """
    # Import here to avoid circular dependency
    from scripts.collect_metrics import main as collect_main

    # Set up sys.argv to pass arguments to the collect script
    sys.argv = [
        "collect_metrics",
    ]

    if create_issues:
        sys.argv.append("--create-issues")
        sys.argv.append(f"--min-coverage={min_coverage}")

    if store_metrics:
        sys.argv.append("--store-metrics")

    if output_format:
        sys.argv.append(f"--output={output_format}")

    # Run the collector
    try:
        exit_code = collect_main()
        sys.exit(exit_code)
    except Exception as e:
        console.print(f"[red]Error collecting metrics:[/red] {e}")
        sys.exit(1)


@metrics_app.command("report")
def generate_report(
    format: str = typer.Option(
        "text",
        "--format",
        help="Report format: text, json, or markdown",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: stdout)",
    ),
):
    """Generate a comprehensive metrics report.

    Creates a detailed report of test coverage and quality metrics
    across all repositories.

    Example:
        mahavishnu metrics report --format markdown --output metrics.md
    """
    console.print("[yellow]Generating metrics report...[/yellow]")

    # For now, delegate to collect_metrics
    # TODO: Generate more comprehensive reports with historical data
    from scripts.collect_metrics import main as collect_main

    sys.argv = ["collect_metrics", f"--output={format}"]

    try:
        exit_code = collect_main()

        if output:
            console.print(f"[green]Report saved to:[/green] {output}")

        sys.exit(exit_code)
    except Exception as e:
        console.print(f"[red]Error generating report:[/red] {e}")
        sys.exit(1)


@metrics_app.command("status")
def show_status(
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Show status for specific repository",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Filter by repository role",
    ),
):
    """Show current metrics status.

    Displays the current state of test coverage and quality metrics.
    Can filter by specific repository or role.

    Example:
        mahavishnu metrics status --repo mahavishnu
        mahavishnu metrics status --role tool
    """
    import yaml

    console.print("[cyan]📊 Mahavishnu Ecosystem Metrics Status[/cyan]\n")

    # Load repository catalog
    repos_path = Path("settings/repos.yaml")
    with open(repos_path) as f:
        data = yaml.safe_load(f)

    repos = data.get("repos", [])

    # Filter repos if requested
    if repo:
        repos = [r for r in repos if r.get("name") == repo]
    if role:
        repos = [r for r in repos if r.get("role") == role]

    if not repos:
        console.print("[yellow]No repositories found matching criteria[/yellow]")
        sys.exit(0)

    # Create table
    table = Table(title="Repository Coverage Status")
    table.add_column("Repository", style="cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Coverage", style="green")
    table.add_column("Files", style="blue")
    table.add_column("Status", style="yellow")

    # Collect coverage data
    from scripts.collect_metrics import get_coverage_from_file

    for repo_data in repos:
        repo_name = repo_data.get("name", "unknown")
        repo_path = Path(repo_data["path"])
        repo_role = repo_data.get("role", "unknown")

        coverage_file = repo_path / ".coverage"

        if coverage_file.exists():
            cov_data = get_coverage_from_file(repo_path)
            if "error" in cov_data:
                coverage = "Error"
                files = "N/A"
                status = "[red]✗[/red]"
            else:
                coverage_pct = cov_data.get("coverage", 0)
                files_tested = cov_data.get("files", 0)
                coverage = f"{coverage_pct:.1f}%"
                files = str(files_tested)

                if coverage_pct >= 80:
                    status = "[green]✓ Good[/green]"
                elif coverage_pct >= 60:
                    status = "[yellow]⚠ Fair[/yellow]"
                else:
                    status = "[red]✗ Poor[/red]"
        else:
            coverage = "N/A"
            files = "N/A"
            status = "[dim]○ No data[/dim]"

        table.add_row(repo_name, repo_role, coverage, files, status)

    console.print(table)
    console.print(f"\n[dim]Total repositories: {len(repos)}[/dim]")


@metrics_app.command("history")
def show_history(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of historical snapshots to show",
    ),
):
    """Show historical metrics snapshots.

    Displays past metrics snapshots for trend analysis.

    Example:
        mahavishnu metrics history --limit 20
    """
    from pathlib import Path

    console.print("[cyan]📈 Metrics History[/cyan]\n")

    # Find metrics directory
    metrics_dir = Path.cwd() / "data" / "metrics"

    if not metrics_dir.exists():
        console.print("[yellow]No metrics history found[/yellow]")
        console.print("[dim]Collect metrics with --store-metrics flag to enable history[/dim]")
        return

    # Get all snapshot files, sorted by modification time (newest first)
    snapshots = sorted(
        metrics_dir.glob("metrics_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )[:limit]

    if not snapshots:
        console.print("[yellow]No metrics snapshots found[/yellow]")
        console.print("[dim]Directory exists but contains no snapshots[/dim]")
        return

    # Display snapshots
    table = Table(
        title=f"Last {len(snapshots)} Metrics Snapshots",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Timestamp", style="dim", width=19)
    table.add_column("Avg Coverage", justify="right")
    table.add_column("Repos", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Trend", width=8)

    prev_coverage = None
    import json

    for snapshot_path in snapshots:
        try:
            with open(snapshot_path) as f:
                data = json.load(f)

            timestamp_str = data["timestamp"][:19]  # Extract YYYY-MM-DD HH:MM:SS
            avg_cov = data["summary"]["avg_coverage"]
            repos = data["summary"]["repos_count"]
            files = data["summary"]["total_files_tested"]

            # Calculate trend
            if prev_coverage is not None:
                diff = avg_cov - prev_coverage
                if diff > 0:
                    trend = f"[green]↑+{diff:.1f}%[/green]"
                elif diff < 0:
                    trend = f"[red]↓{diff:.1f}%[/red]"
                else:
                    trend = "[dim]=[/dim]"
            else:
                trend = ""

            table.add_row(timestamp_str, f"{avg_cov:.1f}%", str(repos), str(files), trend)

            prev_coverage = avg_cov

        except Exception as e:
            console.print(f"[red]Error reading {snapshot_path.name}: {e}[/red]")

    console.print(table)
    console.print(f"\n[dim]Total snapshots: {len(snapshots)}[/dim]")
    console.print(f"[dim]Metrics directory: {metrics_dir}[/dim]")


@metrics_app.command("dashboard")
def generate_dashboard(
    output: str = typer.Option(
        "metrics_dashboard.html",
        "--output",
        "-o",
        help="Output HTML file path (default: metrics_dashboard.html)",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open dashboard in browser after generation",
    ),
):
    """Generate an interactive HTML metrics dashboard.

    Creates a beautiful, interactive dashboard with charts and visualizations
    of test coverage across all repositories.

    Example:
        mahavishnu metrics dashboard --output metrics.html --open
    """
    import sys

    console.print("[cyan]📊 Generating Metrics Dashboard[/cyan]\n")

    # Import dashboard generator
    from scripts.generate_metrics_dashboard import main as dashboard_main

    # Set up sys.argv
    sys.argv = ["generate_metrics_dashboard", f"--output={output}"]

    # Generate dashboard
    try:
        exit_code = dashboard_main()

        if exit_code == 0 and open_browser:
            import webbrowser

            output_path = Path(output).absolute()
            console.print("\n[cyan]Opening dashboard in browser...[/cyan]")
            webbrowser.open(f"file://{output_path}")

        sys.exit(exit_code)
    except Exception as e:
        console.print(f"[red]Error generating dashboard:[/red] {e}")
        sys.exit(1)


def add_metrics_commands(app: typer.Typer) -> None:
    """Add metrics commands to the Mahavishnu CLI app.

    Args:
        app: The main Typer application
    """
    app.add_typer(metrics_app, name="metrics")
