"""
Metrics commands for Mahavishnu CLI.

Provides commands for collecting and reporting on test coverage
and other quality metrics across the Mahavishnu ecosystem.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
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


# ---------------------------------------------------------------------------
# `mahavishnu metrics bodai` — Bodai EventBridge subscriber health
# ---------------------------------------------------------------------------


DEFAULT_BODAI_STATE_PATH = Path("~/.mahavishnu/bodai-subscriber-state.json").expanduser()
DEFAULT_BODAI_QUEUE_CAP = 100
STALE_THRESHOLD_SECONDS = 5 * 60  # 5 minutes
_KNOWN_BODAI_COMPONENTS = ("mahavishnu", "akosha", "crackerjack")


def _resolve_bodai_queue_path(explicit: str | None) -> Path:
    """Resolve the queue path with explicit > env > default precedence.

    Mirrors :func:`mahavishnu.core.events.bodai_subscriber._default_queue_path`
    so the CLI reads exactly what the subscriber writes.
    """
    if explicit:
        return Path(explicit).expanduser()
    env_override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".mahavishnu" / "bodai-event-queue.json"


def _resolve_bodai_state_path(explicit: str | None) -> Path:
    """Resolve the subscriber state-file path."""
    if explicit:
        return Path(explicit).expanduser()
    env_override = os.environ.get("MAHAVISHNU_BODAI_STATE_PATH")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".mahavishnu" / "bodai-subscriber-state.json"


def _load_bodai_queue(path: Path) -> list[dict[str, Any]]:
    """Read and JSON-parse the queue file. Returns ``[]`` on any failure."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _load_bodai_state(path: Path) -> dict[str, Any] | None:
    """Read the subscriber state file. Returns ``None`` when missing or unreadable."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_bodai_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp from an envelope header or queue field.

    Accepts ISO-8601 strings and Unix epoch floats/ints. Returns ``None`` for
    unparsable or missing values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _headers_of(event: dict[str, Any]) -> dict[str, Any]:
    """Return event headers when they are a dictionary."""
    headers = event.get("headers")
    return headers if isinstance(headers, dict) else {}


def _filter_bodai_events(
    events: list[dict[str, Any]],
    *,
    scope_days: int | None,
    component: str | None,
) -> list[dict[str, Any]]:
    """Apply ``--scope`` (drop events older than N days) and ``--component`` filters."""
    filtered = events
    if component:
        target = component.strip().lower()
        filtered = [
            ev for ev in filtered if str(_headers_of(ev).get("source") or "").lower() == target
        ]
    if scope_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=scope_days)
        filtered = [ev for ev in filtered if (_event_timestamp(ev) or cutoff) >= cutoff]
    return filtered


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    """Return the most useful timestamp for *event* (header first, received_at fallback)."""
    headers = _headers_of(event)
    parsed = _parse_bodai_timestamp(headers.get("timestamp"))
    if parsed is not None:
        return parsed
    return _parse_bodai_timestamp(event.get("received_at"))


def _component_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    """Tally events per component (source header)."""
    counts: dict[str, int] = dict.fromkeys(_KNOWN_BODAI_COMPONENTS, 0)
    for event in events:
        source = _headers_of(event).get("source")
        if not isinstance(source, str) or not source:
            continue
        counts[source] = counts.get(source, 0) + 1
    return counts


def _component_last_seen(events: list[dict[str, Any]]) -> dict[str, datetime | None]:
    """Return the most recent event timestamp per component (None if no events)."""
    last_seen: dict[str, datetime | None] = dict.fromkeys(_KNOWN_BODAI_COMPONENTS)
    for event in events:
        source = _headers_of(event).get("source")
        if not isinstance(source, str) or not source:
            continue
        ts = _event_timestamp(event)
        if ts is None:
            continue
        existing = last_seen.get(source)
        if existing is None or ts > existing:
            last_seen[source] = ts
    return last_seen


def _format_bodai_timestamp(value: datetime | None) -> str:
    """Render a timestamp as ISO-8601 (UTC) or 'n/a' when missing."""
    if value is None:
        return "n/a"
    return value.astimezone(UTC).isoformat()


def _render_subscriber_state(state_path: Path, state: dict[str, Any] | None) -> None:
    """Render the Subscriber State table for the bodai metrics command."""
    state_table = Table(title="Subscriber State", show_header=True, header_style="bold magenta")
    state_table.add_column("Field", style="cyan")
    state_table.add_column("Value", style="white")
    if state is None:
        state_table.add_row("State file", f"[yellow]missing[/yellow] ({state_path})")
        state_table.add_row("Running", "[red]no[/red]")
        state_table.add_row("PID", "n/a")
        state_table.add_row("Last seen", "n/a")
    else:
        pid = state.get("pid")
        pid_str = str(pid) if pid is not None else "n/a"
        last_seen_raw = state.get("last_seen") or state.get("started_at")
        last_seen_dt = _parse_bodai_timestamp(last_seen_raw)
        last_seen_str = _format_bodai_timestamp(last_seen_dt)
        uptime_raw = state.get("uptime_seconds")
        uptime_str = (
            f"{uptime_raw:.1f}s"
            if isinstance(uptime_raw, (int, float))
            else (str(uptime_raw) if uptime_raw is not None else "n/a")
        )
        state_table.add_row("State file", str(state_path))
        state_table.add_row("Running", "[green]yes[/green]")
        state_table.add_row("PID", pid_str)
        state_table.add_row("Last seen", last_seen_str)
        state_table.add_row("Uptime (s)", uptime_str)
    console.print(state_table)


def _render_queue_state(
    queue_path: Path, events: list[dict[str, Any]], queue_cap: int
) -> None:
    """Render the Queue State table for the bodai metrics command."""
    queue_size = len(events)
    drop_count = max(0, queue_cap - queue_size) if queue_cap <= queue_size else 0
    oldest = min(
        (_event_timestamp(ev) for ev in events if _event_timestamp(ev) is not None),
        default=None,
    )
    newest = max(
        (_event_timestamp(ev) for ev in events if _event_timestamp(ev) is not None),
        default=None,
    )
    queue_table = Table(title="Queue State", show_header=True, header_style="bold magenta")
    queue_table.add_column("Field", style="cyan")
    queue_table.add_column("Value", style="white")
    queue_table.add_row("Queue file", str(queue_path))
    queue_table.add_row("Queue size", str(queue_size))
    queue_table.add_row("Queue cap", str(queue_cap))
    queue_table.add_row("Drop count (over cap)", str(drop_count))
    queue_table.add_row("Oldest event", _format_bodai_timestamp(oldest))
    queue_table.add_row("Newest event", _format_bodai_timestamp(newest))
    console.print(queue_table)


def _render_component_health(
    *,
    events: list[dict[str, Any]],
    components: list[str],
    counts: dict[str, int],
    last_seen_map: dict[str, datetime | None],
    now: datetime,
) -> None:
    """Render the Per-Component Health table for the bodai metrics command."""
    detail_table = Table(
        title="Per-Component Health", show_header=True, header_style="bold magenta"
    )
    detail_table.add_column("Component", style="cyan")
    detail_table.add_column("Events", justify="right")
    detail_table.add_column("Last Event", style="white")
    detail_table.add_column("Status", style="white")

    if not events:
        console.print(
            "[yellow]No events in queue.[/yellow] "
            "[dim]Check subscriber state and MAHAVISHNU_BODAI_QUEUE_PATH.[/dim]"
        )
    else:
        for component in components:
            count = counts.get(component, 0)
            last_event_dt = last_seen_map.get(component)
            age_seconds: float | None = None
            if last_event_dt is not None:
                age_seconds = (now - last_event_dt).total_seconds()
            if (
                count == 0
                or last_event_dt is None
                or age_seconds is not None
                and age_seconds > STALE_THRESHOLD_SECONDS
            ):
                status = "stale"
            else:
                status = "fresh"

            age_str = f" (age {age_seconds:.0f}s)" if age_seconds is not None else ""
            last_str = _format_bodai_timestamp(last_event_dt)
            if status == "stale":
                detail_table.add_row(
                    component,
                    str(count),
                    f"{last_str}{age_str}",
                    "[red]stale[/red]",
                )
            else:
                detail_table.add_row(
                    component,
                    str(count),
                    f"{last_str}{age_str}",
                    "[green]fresh[/green]",
                )

    console.print(detail_table)


def _render_recent_event(events: list[dict[str, Any]]) -> None:
    """Render the Most Recent Event table for the bodai metrics command.

    Surfaces topic + payload-derived identifiers (e.g. workflow_id) from the
    most recent event so callers can confirm payload contents reached the
    queue end-to-end. This is the "queue-derived identifiers" surface the
    Oneiric EventEnvelope wire-standardization plan's e2e proof asserts.
    """
    if not events:
        return

    recent_table = Table(
        title="Most Recent Event (queue-derived)",
        show_header=True,
        header_style="bold magenta",
    )
    recent_table.add_column("Field", style="cyan")
    recent_table.add_column("Value", style="white")

    dated_pairs: list[tuple[datetime, dict[str, Any]]] = [
        (ts, ev) for ev in events for ts in [_event_timestamp(ev)] if ts is not None
    ]
    if dated_pairs:
        recent: dict[str, Any] = max(dated_pairs, key=lambda pair: pair[0])[1]
    else:
        recent = events[-1]
    recent_topic = recent.get("topic") or ""
    recent_payload_raw = recent.get("payload")
    recent_payload: dict[str, Any] = (
        recent_payload_raw if isinstance(recent_payload_raw, dict) else {}
    )
    recent_headers_raw = recent.get("headers")
    recent_headers: dict[str, Any] = (
        recent_headers_raw if isinstance(recent_headers_raw, dict) else {}
    )

    recent_table.add_row("topic", str(recent_topic))

    recent_wire_format = recent_headers.get("wire_format") or recent.get("wire_format")
    if recent_wire_format is not None:
        recent_table.add_row("wire_format", str(recent_wire_format))

    # Surface every payload field whose key contains "id" — these are the
    # "queue-derived identifiers" the e2e proof expects to see.
    rendered_identifier_rows = False
    for key, value in recent_payload.items():
        key_str = str(key)
        if "id" not in key_str.lower():
            continue
        recent_table.add_row(f"payload.{key_str}", str(value))
        rendered_identifier_rows = True

    # Fallback: if no id-shaped key was found, surface the topic so the
    # table is never empty.
    if not rendered_identifier_rows:
        if recent_payload:
            recent_table.add_row("payload", str(recent_payload))
        else:
            recent_table.add_row("payload", "(empty)")

    console.print(recent_table)


def _render_filter_note(scope_days: int | None, component_filter: str | None) -> None:
    """Render the trailing filter-note line for the bodai metrics command."""
    filter_note_parts: list[str] = []
    if scope_days is not None:
        filter_note_parts.append(f"scope={scope_days}d")
    if component_filter:
        filter_note_parts.append(f"component={component_filter}")
    if filter_note_parts:
        console.print(f"\n[dim]Filters: {', '.join(filter_note_parts)}[/dim]")


def _render_bodai_output(
    *,
    queue_path: Path,
    state_path: Path,
    state: dict[str, Any] | None,
    events: list[dict[str, Any]],
    queue_cap: int,
    component_filter: str | None,
    scope_days: int | None,
    now: datetime,
) -> None:
    """Render the `mahavishnu metrics bodai` markdown-table output."""
    console.print("[cyan]Bodai EventBridge Subscriber Status[/cyan]\n")

    _render_subscriber_state(state_path, state)
    _render_queue_state(queue_path, events, queue_cap)

    counts = _component_counts(events)
    last_seen_map = _component_last_seen(events)

    components = list(_KNOWN_BODAI_COMPONENTS)
    if component_filter:
        components = [c for c in components if c == component_filter]

    _render_component_health(
        events=events,
        components=components,
        counts=counts,
        last_seen_map=last_seen_map,
        now=now,
    )
    _render_recent_event(events)
    _render_filter_note(scope_days, component_filter)


@metrics_app.command("bodai")
def bodai_metrics(
    scope: str = typer.Option(
        "24h",
        "--scope",
        help="Time scope filter: e.g. '24h', '7d', or 'all' (no time filter).",
    ),
    component: str | None = typer.Option(
        None,
        "--component",
        "-c",
        help="Filter to a single component source (e.g. mahavishnu, akosha, crackerjack).",
    ),
    queue_path: str | None = typer.Option(
        None,
        "--queue-path",
        help="Override the Bodai queue file path (default: ~/.mahavishnu/bodai-event-queue.json).",
    ),
    state_path: str | None = typer.Option(
        None,
        "--state-path",
        help="Override the Bodai subscriber state file path.",
    ),
    queue_cap: int = typer.Option(
        DEFAULT_BODAI_QUEUE_CAP,
        "--queue-cap",
        help="Maximum queue capacity (used to compute drop count).",
    ),
) -> None:
    """Show Bodai EventBridge subscriber health, queue state, and per-component health.

    Reads the local Bodai queue file (``~/.mahavishnu/bodai-event-queue.json``,
    overridable via ``MAHAVISHNU_BODAI_QUEUE_PATH``) and the subscriber state
    file (``~/.mahavishnu/bodai-subscriber-state.json``) and renders a
    multi-section markdown table covering:

    1. Subscriber state (running/stopped, pid, last seen)
    2. Event counts per component for events currently in the queue
    3. Queue state (current size, drop count, oldest/newest timestamps)
    4. Per-component health (last event timestamp; stale if >5min old)

    Examples:
        mahavishnu metrics bodai
        mahavishnu metrics bodai --scope 7d --component akosha
        mahavishnu metrics bodai --scope all --component crackerjack
    """
    effective_queue_path = _resolve_bodai_queue_path(queue_path)
    effective_state_path = _resolve_bodai_state_path(state_path)

    state = _load_bodai_state(effective_state_path)
    events = _load_bodai_queue(effective_queue_path)

    scope_normalized = scope.strip().lower() if scope else "24h"
    scope_days: int | None
    if scope_normalized in {"all", "none", "0"}:
        scope_days = None
    else:
        match = re.match(r"^(\d+)\s*([hd])$", scope_normalized)
        if match is None:
            console.print(f"[red]Invalid --scope {scope!r}. Use '24h', '7d', or 'all'.[/red]")
            raise typer.Exit(2)
        magnitude = int(match.group(1))
        unit = match.group(2)
        scope_days = magnitude if unit == "d" else max(1, magnitude // 24)

    component_normalized = component.strip().lower() if component else None
    if component_normalized and component_normalized not in _KNOWN_BODAI_COMPONENTS:
        console.print(
            "[red]Unknown --component "
            f"{component!r}. Known: {', '.join(_KNOWN_BODAI_COMPONENTS)}.[/red]"
        )
        raise typer.Exit(2)

    filtered = _filter_bodai_events(
        events,
        scope_days=scope_days,
        component=component_normalized,
    )

    _render_bodai_output(
        queue_path=effective_queue_path,
        state_path=effective_state_path,
        state=state,
        events=filtered,
        queue_cap=queue_cap,
        component_filter=component_normalized,
        scope_days=scope_days,
        now=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# `mahavishnu metrics verification` — Ultracode Phase 1 verification verdicts
# ---------------------------------------------------------------------------

VERIFICATION_KEY_PREFIX = "verification/"
ROUTING_DECISIONS_KEY_PREFIX = "routing-decisions/"


def _resolve_dhara_url(explicit_url: str | None) -> str:
    """Resolve the Dhara HTTP URL with explicit > env > config precedence.

    Mirrors :func:`mahavishnu.core.bootstrap.resolve_dhara_url` but uses the
    *health.dependencies.dhara* host:port pair rather than the legacy MCP URL.
    Falls back to ``http://localhost:8683`` when no configuration is present.
    """
    if explicit_url:
        return explicit_url.rstrip("/")

    env_url = os.environ.get("MAHAVISHNU_DHARA_URL")
    if env_url:
        return env_url.rstrip("/")

    settings_path = Path("settings/mahavishnu.yaml")
    if settings_path.exists():
        try:
            import yaml

            with settings_path.open() as f:
                data = yaml.safe_load(f) or {}  # type: ignore[var-annotated]
            health = data.get("health", {}) if isinstance(data, dict) else {}  # type: ignore[var-annotated]
            deps = health.get("dependencies", {}) if isinstance(health, dict) else {}  # type: ignore[var-annotated]
            dhara = deps.get("dhara") if isinstance(deps, dict) else None  # type: ignore[var-annotated]
            if isinstance(dhara, dict):
                host = dhara.get("host", "localhost")
                port = dhara.get("port", 8683)
                scheme = "https" if dhara.get("use_tls") else "http"
                return f"{scheme}://{host}:{port}".rstrip("/")
        except Exception:
            pass

    return "http://localhost:8683"


async def _fetch_dhara_entries(
    dhara_url: str,
    prefix: str,
) -> list[dict[str, Any]]:
    """Fetch all key/value entries under *prefix* via Dhara's MCP HTTP API.

    Returns an empty list when Dhara is unreachable so the CLI degrades
    gracefully (mirrors :class:`DharaStateBackend` semantics).
    """
    try:
        from mahavishnu.core.dhara_adapter import DharaClient
    except ImportError as exc:
        raise RuntimeError("DharaClient not importable; cannot query Dhara") from exc

    client = DharaClient(base_url=dhara_url, timeout=10.0)
    try:
        result = await client.call_tool("list_prefix", {"prefix": prefix})
    except Exception as exc:
        console.print(f"[red]Dhara unreachable at {dhara_url}:[/red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        await client.aclose()

    entries: list[dict[str, Any]] = []
    if isinstance(result, list):
        for item in result:
            if not isinstance(item, dict) or "key" not in item:
                continue
            value_raw = item.get("value", {})
            entries.append({"key": str(item["key"]), "value": value_raw if isinstance(value_raw, dict) else {}})
    return entries


def _parse_since(value: str) -> datetime | None:
    """Parse a `--since` window string into a UTC cutoff datetime.

    Accepted formats: ``24h``, ``7d``, ``30m``. ``all`` / empty -> ``None``
    (no time filter applied).
    """
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"all", "none", "0"}:
        return None
    match = re.match(r"^(\d+)\s*([mhd])$", normalized)
    if match is None:
        console.print(f"[red]Invalid --since {value!r}. Use '24h', '7d', '30m', or 'all'.[/red]")
        raise typer.Exit(2)
    magnitude = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        delta = timedelta(minutes=magnitude)
    elif unit == "h":
        delta = timedelta(hours=magnitude)
    else:
        delta = timedelta(days=magnitude)
    return datetime.now(UTC) - delta


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    """Return the most useful timestamp for a Dhara entry value."""
    value = entry.get("value", {})
    if not isinstance(value, dict):
        return None
    for key in ("timestamp", "created_at", "ts"):
        raw = value.get(key)
        if not isinstance(raw, str):
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _filter_by_window(
    entries: list[dict[str, Any]],
    cutoff: datetime | None,
) -> list[dict[str, Any]]:
    """Drop entries whose value-timestamp predates *cutoff*."""
    if cutoff is None:
        return entries
    return [e for e in entries if (ts := _entry_timestamp(e)) is None or ts >= cutoff]


def _verification_consensus(value: dict[str, Any]) -> str:
    """Extract the consensus verdict from a verification entry value."""
    for key in ("consensus", "verdict", "decision"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return "unknown"


def _verification_persisted(value: dict[str, Any]) -> bool:
    """Was the proposal persisted to its target after verification?"""
    raw = value.get("persisted", value.get("persisted_to_target"))
    return isinstance(raw, bool) and raw


def _routing_caller_kind(value: dict[str, Any]) -> str:
    """Extract caller_kind from a routing-decision entry value."""
    raw = value.get("caller_kind", value.get("source"))
    return raw if isinstance(raw, str) and raw else "unknown"


def _routing_async_callback(value: dict[str, Any]) -> bool:
    """Was the dispatch invoked with async_callback=True?"""
    raw = value.get("async_callback")
    return isinstance(raw, bool) and raw


def _render_verification_output(
    entries: list[dict[str, Any]],
    *,
    cutoff: datetime | None,
    output_format: str,
    dhara_url: str,
) -> None:
    """Render the `mahavishnu metrics verification` output."""
    filtered = _filter_by_window(entries, cutoff)

    consensus_counts: dict[str, int] = defaultdict(int)
    persist_failures = 0
    total = len(filtered)
    recent: list[dict[str, Any]] = []

    for entry in filtered[-20:]:
        value = entry["value"]
        recent.append(
            {
                "key": entry["key"],
                "consensus": _verification_consensus(value),
                "persisted": _verification_persisted(value),
                "timestamp": _entry_timestamp(entry).isoformat()
                if _entry_timestamp(entry)
                else None,
            }
        )

    for entry in filtered:
        value = entry["value"]
        consensus_counts[_verification_consensus(value)] += 1
        if not _verification_persisted(value):
            persist_failures += 1

    persist_failure_rate = (persist_failures / total) if total > 0 else 0.0
    reject_rate = (consensus_counts.get("reject", 0) / total) if total > 0 else 0.0

    if output_format == "json":
        console.print_json(
            json.dumps(
                {
                    "source": "dhara",
                    "dhara_url": dhara_url,
                    "prefix": VERIFICATION_KEY_PREFIX,
                    "since": cutoff.isoformat() if cutoff else None,
                    "total": total,
                    "consensus_distribution": dict(consensus_counts),
                    "reject_rate": round(reject_rate, 4),
                    "persist_failure_rate": round(persist_failure_rate, 4),
                    "recent": recent,
                },
                default=str,
            )
        )
        return

    if output_format != "table":
        console.print("[red]Invalid --output. Use: table or json[/red]")
        raise typer.Exit(2)

    console.print("[cyan]Ultracode Phase 1 — Verification Verdicts[/cyan]\n")
    console.print(f"[dim]Dhara URL: {dhara_url}[/dim]")
    console.print(f"[dim]Key prefix: {VERIFICATION_KEY_PREFIX}[/dim]")
    console.print(f"[dim]Window: since {cutoff.isoformat() if cutoff else 'all'}[/dim]\n")

    summary = Table(title="Summary", show_header=True, header_style="bold magenta")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Total verdicts", str(total))
    summary.add_row(
        "Reject rate",
        f"{reject_rate * 100:.1f}%",
    )
    summary.add_row(
        "Persist-failure rate",
        f"{persist_failure_rate * 100:.1f}%",
    )
    for consensus_name in sorted(consensus_counts.keys()):
        summary.add_row(f"Consensus={consensus_name}", str(consensus_counts[consensus_name]))
    console.print(summary)

    if recent:
        console.print()
        recent_table = Table(
            title="Most Recent Verdicts (last 20)",
            show_header=True,
            header_style="bold magenta",
        )
        recent_table.add_column("Timestamp", style="dim", width=19)
        recent_table.add_column("Consensus", style="cyan")
        recent_table.add_column("Persisted", style="white")
        recent_table.add_column("Proposal Key", style="dim")
        for row in recent:
            ts_display = row["timestamp"] or "n/a"
            if ts_display != "n/a":
                ts_display = ts_display[:19]
            persisted_display = "[green]yes[/green]" if row["persisted"] else "[red]no[/red]"
            recent_table.add_row(ts_display, row["consensus"], persisted_display, row["key"])
        console.print(recent_table)
    else:
        console.print("\n[yellow]No verification records in window.[/yellow]")


@metrics_app.command("verification")
def verification_metrics(
    since: str = typer.Option(
        "24h",
        "--since",
        help="Time window filter: '24h', '7d', '30m', or 'all' (no filter).",
    ),
    dhara_url: str | None = typer.Option(
        None,
        "--dhara-url",
        help="Override Dhara HTTP URL (also: MAHAVISHNU_DHARA_URL).",
    ),
    output_format: str = typer.Option(
        "table",
        "--output",
        help="Output format: table or json",
    ),
) -> None:
    """Show ultracode Phase 1 verification verdicts from Dhara.

    Reads Dhara under the ``verification/`` key prefix and renders a summary
    of consensus distribution, reject rate, persist-failure rate, and the
    most recent 20 verdicts.

    Precedence for the Dhara URL: ``--dhara-url`` > ``MAHAVISHNU_DHARA_URL`` >
    ``settings/mahavishnu.yaml -> health.dependencies.dhara`` > ``localhost:8683``.

    Examples:
        mahavishnu metrics verification
        mahavishnu metrics verification --since 7d --output json
        mahavishnu metrics verification --dhara-url http://dhara.internal:8683
    """
    effective_url = _resolve_dhara_url(dhara_url)
    cutoff = _parse_since(since)
    entries = asyncio.run(_fetch_dhara_entries(effective_url, VERIFICATION_KEY_PREFIX))
    _render_verification_output(
        entries,
        cutoff=cutoff,
        output_format=output_format,
        dhara_url=effective_url,
    )


# ---------------------------------------------------------------------------
# `mahavishnu metrics dispatch` — Ultracode Phase 3 routing-decision metrics
# ---------------------------------------------------------------------------
# (Lands in a follow-up commit.)


def add_metrics_commands(app: typer.Typer) -> None:
    """Add metrics commands to the Mahavishnu CLI app.

    Args:
        app: The main Typer application
    """
    app.add_typer(metrics_app, name="metrics")
