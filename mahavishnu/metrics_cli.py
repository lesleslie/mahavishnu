"""
Metrics commands for Mahavishnu CLI.

Provides commands for collecting and reporting on test coverage
and other quality metrics across the Mahavishnu ecosystem.
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from urllib import error as urllib_error
from urllib import request as urllib_request

from rich.console import Console
from rich.table import Table
import typer

# Create metrics app
metrics_app = typer.Typer(help="Metrics collection and reporting for the Mahavishnu ecosystem")
console = Console()


def _resolve_postgres_dsn(explicit_dsn: str | None) -> str | None:
    """Resolve PostgreSQL DSN for routing metrics queries.

    Precedence:
    1. --dsn option
    2. MAHAVISHNU_PERSISTENCE__POSTGRES_URL
    3. MAHAVISHNU_POSTGRES_DSN
    4. settings/mahavishnu.yaml -> persistence.postgres_url
    """
    if explicit_dsn:
        return explicit_dsn

    env_dsn = os.getenv("MAHAVISHNU_PERSISTENCE__POSTGRES_URL") or os.getenv(
        "MAHAVISHNU_POSTGRES_DSN"
    )
    if env_dsn:
        return env_dsn

    settings_path = Path("settings/mahavishnu.yaml")
    if not settings_path.exists():
        return None

    try:
        import yaml

        with settings_path.open() as f:
            data = yaml.safe_load(f) or {}  # type: ignore[var-annotated]
        persistence = data.get("persistence", {}) if isinstance(data, dict) else {}  # type: ignore[var-annotated]
        dsn = persistence.get("postgres_url")
        if isinstance(dsn, str) and dsn.strip():
            return dsn.strip()
    except Exception:
        return None

    return None


async def _load_engine_metrics_from_postgres(
    dsn: str,
    days: int | None,
) -> dict[str, dict[str, int]]:
    """Load engine metrics from PostgreSQL metrics schema."""
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is not installed; cannot query PostgreSQL source") from exc

    cutoff: datetime | None = None
    if days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=days)

    conn = await asyncpg.connect(dsn)
    try:
        selected_rows = await conn.fetch(
            """
            SELECT selected_adapter AS adapter, COUNT(*)::BIGINT AS selected_count
            FROM metrics.routing_decisions
            WHERE ($1::timestamptz IS NULL OR timestamp >= $1)
            GROUP BY selected_adapter
            """,
            cutoff,
        )

        execution_rows = await conn.fetch(
            """
            SELECT
              adapter,
              COUNT(*)::BIGINT AS execution_count,
              COUNT(*) FILTER (
                WHERE status IN ('success', 'completed')
              )::BIGINT AS success_count,
              COUNT(*) FILTER (
                WHERE status IN ('failure', 'failed', 'timeout', 'cancelled')
              )::BIGINT AS failure_count
            FROM metrics.execution_records
            WHERE ($1::timestamptz IS NULL OR created_at >= $1)
            GROUP BY adapter
            """,
            cutoff,
        )
    finally:
        await conn.close()

    metrics: dict[str, dict[str, int]] = {
        "prefect": {"selected": 0, "executions": 0, "success": 0, "failure": 0},
        "agno": {"selected": 0, "executions": 0, "success": 0, "failure": 0},
        "llamaindex": {"selected": 0, "executions": 0, "success": 0, "failure": 0},
    }

    for row in selected_rows:
        adapter = row["adapter"]
        if adapter not in metrics:
            metrics[adapter] = {"selected": 0, "executions": 0, "success": 0, "failure": 0}
        metrics[adapter]["selected"] = int(row["selected_count"])

    for row in execution_rows:
        adapter = row["adapter"]
        if adapter not in metrics:
            metrics[adapter] = {"selected": 0, "executions": 0, "success": 0, "failure": 0}
        metrics[adapter]["executions"] = int(row["execution_count"])
        metrics[adapter]["success"] = int(row["success_count"])
        metrics[adapter]["failure"] = int(row["failure_count"])

    return metrics


_PROM_LINE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([0-9eE+.\-]+)$")

_SUCCESS_STATUSES = frozenset({"success", "completed"})
_FAILURE_STATUSES = frozenset({"failure", "failed", "timeout", "cancelled"})
_EXPECTED_ADAPTERS = ("prefect", "agno", "llamaindex")


def _fetch_prometheus_body(metrics_url: str) -> str:
    """Fetch the raw Prometheus exposition text body from ``metrics_url``.

    Raises:
        RuntimeError: If the URL cannot be reached (URLError).
    """
    try:
        with urllib_request.urlopen(  # nosec  # nosemgrep: dynamic-urllib-use-detected
            metrics_url, timeout=2.0
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib_error.URLError as exc:
        raise RuntimeError(f"failed to fetch Prometheus metrics from {metrics_url}: {exc}") from exc


def _parse_labels(raw: str) -> dict[str, str]:
    """Parse a Prometheus label set like ``a="1",b="2"`` into a dict."""
    labels: dict[str, str] = {}
    for chunk in raw.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        labels[key.strip()] = value.strip().strip('"')
    return labels


def _apply_status_counts(
    metrics: dict[str, dict[str, int]],
    adapter: str,
    status: str,
    value: int,
) -> None:
    """Increment ``metrics[adapter]`` counters based on the status label.

    Always bumps ``executions``; additionally bumps ``success`` or
    ``failure`` when the status matches one of the known sets.
    """
    metrics[adapter]["executions"] += value
    if status in _SUCCESS_STATUSES:
        metrics[adapter]["success"] += value
    elif status in _FAILURE_STATUSES:
        metrics[adapter]["failure"] += value


def _record_metric(
    metrics: dict[str, dict[str, int]],
    metric_name: str,
    adapter: str,
    labels: dict[str, str],
    value: int,
) -> None:
    """Increment the correct per-adapter counter for a single parsed line."""
    status = labels.get("status", "")
    if metric_name == "mahavishnu_routing_decisions_total":
        metrics[adapter]["selected"] += value
    elif metric_name in (
        "mahavishnu_adapter_executions_total",
        "mahavishnu_workflows_total",
    ):
        # workflows_total is a fallback when adapter_executions_total
        # is not populated by the engine.
        _apply_status_counts(metrics, adapter, status, value)


def _process_prometheus_line(
    line: str,
    metrics: dict[str, dict[str, int]],
) -> None:
    """Parse one Prometheus line and update ``metrics`` in place.

    Skips blank lines, comments, malformed lines, non-adapter metrics,
    and non-integer values. All failure modes are silent because
    Prometheus text format tolerates garbage gracefully.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return
    match = _PROM_LINE_RE.match(line)
    if not match:
        return

    metric_name, raw_labels, raw_value = match.groups()
    labels = _parse_labels(raw_labels)
    adapter = labels.get("adapter")
    if not adapter:
        return

    try:
        value = int(float(raw_value))
    except ValueError:
        return

    _record_metric(metrics, metric_name, adapter, labels, value)


def _ensure_expected_adapters(metrics: dict[str, dict[str, int]]) -> None:
    """Guarantee every expected adapter row exists with zeroed counters."""
    for adapter in _EXPECTED_ADAPTERS:
        metrics.setdefault(
            adapter,
            {"selected": 0, "executions": 0, "success": 0, "failure": 0},
        )


def _load_engine_metrics_from_prometheus(
    metrics_url: str,
) -> dict[str, dict[str, int]]:
    """Load engine metrics by parsing Prometheus exposition text."""
    body = _fetch_prometheus_body(metrics_url)

    metrics: dict[str, dict[str, int]] = defaultdict(
        lambda: {"selected": 0, "executions": 0, "success": 0, "failure": 0}
    )

    for line in body.splitlines():
        _process_prometheus_line(line, metrics)

    _ensure_expected_adapters(metrics)
    return dict(metrics)


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

    This command scans all repositories defined in settings/ecosystem.yaml,
    collects test coverage data, and generates a comprehensive report.

    Example:
        mahavishnu metrics collect --create-issues --min-coverage 80
    """
    # Import here to avoid circular dependency. Resolved at runtime via sys.path;
    # static analysis cannot see the empty-file script stubs at scripts/*.py.
    from scripts.collect_metrics import (
        main as collect_main,  # ty: ignore[unresolved-import]  # type: ignore[misc]  # noqa: E402
    )

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
    from scripts.collect_metrics import (
        main as collect_main,  # ty: ignore[unresolved-import]  # type: ignore[misc]  # noqa: E402
    )

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
    repos_path = Path("settings/ecosystem.yaml")
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

    # Collect coverage data. Resolved at runtime via sys.path; static analysis
    # cannot see the empty-file script stub at scripts/collect_metrics.py.
    from scripts.collect_metrics import (
        get_coverage_from_file,  # ty: ignore[unresolved-import]  # type: ignore[misc]  # noqa: E402
    )

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

    # Import dashboard generator. Resolved at runtime via sys.path; static analysis
    # cannot see the empty-file script stub at scripts/generate_metrics_dashboard.py.
    from scripts.generate_metrics_dashboard import (
        main as dashboard_main,  # ty: ignore[unresolved-import]  # type: ignore[misc]  # noqa: E402
    )

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


@metrics_app.command("verify-endpoints")
def verify_endpoints(
    inventory: Path = typer.Option(
        Path("monitoring/ecosystem_metrics_inventory.yml"),
        "--inventory",
        help="Path to the ecosystem metrics inventory YAML.",
    ),
    write_verified_file: Path | None = typer.Option(
        Path("monitoring/file_sd/verified_metrics_targets.yml"),
        "--write-verified-file",
        help="Write successful probes to a Prometheus file_sd YAML file.",
    ),
    output_format: str = typer.Option(
        "text",
        "--output",
        help="Output format: text or json",
    ),
    timeout: float = typer.Option(
        2.0,
        "--timeout",
        help="Per-endpoint timeout in seconds.",
    ),
    service: list[str] = typer.Option(
        [],
        "--service",
        help="Probe only the named service. Repeat for multiple services.",
    ),
):
    """Probe ecosystem metrics endpoints and refresh verified Prometheus targets."""
    from scripts.verify_ecosystem_metrics import main as verify_main

    sys.argv = ["verify_ecosystem_metrics", f"--inventory={inventory}", f"--output={output_format}"]

    if write_verified_file is not None:
        sys.argv.append(f"--write-verified-file={write_verified_file}")

    sys.argv.append(f"--timeout={timeout}")

    for service_name in service:
        sys.argv.extend(["--service", service_name])

    try:
        raise SystemExit(verify_main())
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 1) from None
    except Exception as e:
        console.print(f"[red]Error verifying metrics endpoints:[/red] {e}")
        raise typer.Exit(1) from e


def _fetch_engine_metrics(
    source_normalized: str,
    resolved_dsn: str | None,
    metrics_url: str,
    days: int | None,
) -> tuple[dict[str, dict[str, int]], str, list[str]]:
    """Fetch engine metrics from configured source, return (metrics, source, errors)."""
    metrics: dict[str, dict[str, int]] | None = None
    selected_source = ""
    errors: list[str] = []

    if source_normalized in {"auto", "postgres"}:
        if not resolved_dsn:
            if source_normalized == "postgres":
                console.print(
                    "[red]No PostgreSQL DSN found. Use --dsn or set "
                    "MAHAVISHNU_PERSISTENCE__POSTGRES_URL.[/red]"
                )
                raise typer.Exit(1)
            errors.append("postgres: no DSN configured")
        else:
            try:
                metrics = asyncio.run(_load_engine_metrics_from_postgres(resolved_dsn, days))
                selected_source = "postgres"
            except Exception as exc:
                errors.append(f"postgres: {exc}")
                if source_normalized == "postgres":
                    console.print(f"[red]PostgreSQL query failed:[/red] {exc}")
                    raise typer.Exit(1) from exc

    if metrics is None and source_normalized in {"auto", "prometheus"}:
        try:
            metrics = _load_engine_metrics_from_prometheus(metrics_url)
            selected_source = "prometheus"
        except Exception as exc:
            errors.append(f"prometheus: {exc}")
            if source_normalized == "prometheus":
                console.print(f"[red]Prometheus query failed:[/red] {exc}")
                raise typer.Exit(1) from exc

    if metrics is None:
        console.print("[yellow]No engine metrics source available.[/yellow]")
        for err in errors:
            console.print(f"[dim]- {err}[/dim]")
        raise typer.Exit(1)

    return metrics, selected_source, errors


def _build_engine_rows(metrics: dict[str, dict[str, int]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for engine in sorted(metrics.keys()):
        row = metrics[engine]
        executions = int(row.get("executions", 0))
        success = int(row.get("success", 0))
        success_rate = (success / executions * 100.0) if executions > 0 else 0.0
        rows.append(
            {
                "engine": engine,
                "selected": int(row.get("selected", 0)),
                "executions": executions,
                "success": success,
                "failure": int(row.get("failure", 0)),
                "success_rate_pct": round(success_rate, 2),
            }
        )
    return rows


def _render_engine_output(
    rows: list[dict[str, object]],
    output_format: str,
    selected_source: str,
    metrics_url: str,
    days: int | None,
    errors: list[str],
) -> None:
    if output_format == "json":
        console.print_json(
            json.dumps(
                {
                    "source": selected_source,
                    "days": days,
                    "metrics_url": metrics_url if selected_source == "prometheus" else None,
                    "engines": rows,
                    "warnings": errors if errors else [],
                }
            )
        )
        return

    if output_format != "table":
        console.print("[red]Invalid --output. Use: table or json[/red]")
        raise typer.Exit(2)

    table = Table(title=f"Engine Usage Metrics ({selected_source})")
    table.add_column("Engine", style="cyan")
    table.add_column("Selected", justify="right")
    table.add_column("Executions", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Failure", justify="right")
    table.add_column("Success Rate", justify="right")
    for row in rows:
        table.add_row(
            str(row["engine"]),
            str(row["selected"]),
            str(row["executions"]),
            str(row["success"]),
            str(row["failure"]),
            f"{row['success_rate_pct']:.2f}%",
        )
    console.print(table)
    if errors:
        console.print("[dim]Warnings:[/dim]")
        for err in errors:
            console.print(f"[dim]- {err}[/dim]")


@metrics_app.command("engines")
def engine_metrics(
    source: str = typer.Option(
        "auto",
        "--source",
        help="Data source: auto, postgres, or prometheus",
    ),
    dsn: str | None = typer.Option(
        None,
        "--dsn",
        help="PostgreSQL DSN for metrics schema (overrides env/settings)",
    ),
    metrics_url: str = typer.Option(
        "http://127.0.0.1:8680/metrics",
        "--metrics-url",
        help="Prometheus metrics endpoint URL (used for prometheus/auto fallback)",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help="Optional time window (days) for PostgreSQL queries",
    ),
    output_format: str = typer.Option(
        "table",
        "--output",
        help="Output format: table or json",
    ),
) -> None:
    """Show per-engine selection and execution outcomes.

    Displays per-engine selected, executions, success, and failure counts for:
    - prefect
    - agno
    - llamaindex
    """
    source_normalized = source.strip().lower()
    if source_normalized not in {"auto", "postgres", "prometheus"}:
        console.print("[red]Invalid --source. Use: auto, postgres, or prometheus[/red]")
        raise typer.Exit(2)

    resolved_dsn = _resolve_postgres_dsn(dsn)
    metrics, selected_source, errors = _fetch_engine_metrics(
        source_normalized, resolved_dsn, metrics_url, days
    )
    rows = _build_engine_rows(metrics)
    _render_engine_output(rows, output_format, selected_source, metrics_url, days, errors)


def add_metrics_commands(app: typer.Typer) -> None:
    """Add metrics commands to the Mahavishnu CLI app.

    Args:
        app: The main Typer application
    """
    app.add_typer(metrics_app, name="metrics")
