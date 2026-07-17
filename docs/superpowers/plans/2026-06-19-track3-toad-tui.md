---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: track3-toad-tui
---

# Track 3 — Toad TUI (Textual + Rich) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stub `quality_check` CLI command and plain-text `monitoring_cli.py` output with Rich-formatted tables and a live Textual monitor dashboard, gated behind `TUI_AVAILABLE`.

**Architecture:** `mahavishnu/tui/__init__.py` exports a `TUI_AVAILABLE: bool` constant (evaluated at module load by checking `textual` availability) and a `FallbackRichFormatter` for non-TUI environments. A `MonitorApp(App)` Textual widget provides the live `mahavishnu monitor watch` dashboard. The `quality_cli.py` stub becomes a real Rich-formatted summary. Toad (the TUI framework) is Python 3.14+ only — this wave uses **Textual + Rich** only. `TUI_AVAILABLE` is the feature flag for both.

**Scope:** No modifications to pool/worker orchestration. Only CLI output and the new `watch` subcommand.

**Tech Stack:** `textual>=8.2.7` (already in `[tui]` dep group), `rich` (already a transitive dep), Python 3.13.

## Global Constraints

- `from __future__ import annotations` as first non-comment line of every new file
- `TUI_AVAILABLE` is evaluated at module load time and is a module-level `bool` — tests must patch `mahavishnu.tui.TUI_AVAILABLE`, NOT `importlib.util.find_spec`
- Oneiric logger (`from oneiric.logging import get_logger`) not stdlib logging or print
- No `assert` in production code
- `textual` import is guarded by `if TUI_AVAILABLE:` at every usage site
- `rich` is always available (it's a transitive dep of many packages) — use it freely for formatted output
- Line length 100 chars max
- All new CLI commands follow typer conventions (typer.echo + Rich console, not print)

______________________________________________________________________

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `mahavishnu/tui/__init__.py` | Create | `TUI_AVAILABLE: bool`, `FallbackRichFormatter`, `get_console()` |
| `mahavishnu/tui/widgets.py` | Create | `PoolStatusWidget`, `WorkerStatusWidget` Textual widgets |
| `mahavishnu/tui/monitor_app.py` | Create | `MonitorApp(App)` — live dashboard |
| `mahavishnu/quality_cli.py` | Modify | Replace stub with Rich table output |
| `mahavishnu/cli/monitoring_cli.py` | Modify | Replace `typer.echo()` with Rich-formatted `watch` subcommand |
| `tests/unit/tui/test_tui_availability.py` | Create | 4 unit tests for TUI_AVAILABLE + fallback + patch |

______________________________________________________________________

## Task 1: `mahavishnu/tui/` Module

**Files:**

- Create: `mahavishnu/tui/__init__.py`
- Create: `tests/unit/tui/test_tui_availability.py`

**Interfaces:**

- Produces: `TUI_AVAILABLE: bool` — patched directly in tests as `mahavishnu.tui.TUI_AVAILABLE`

- Produces: `get_console() -> Console` — returns a Rich `Console` instance

- Produces: `FallbackRichFormatter` — plain Rich fallback when TUI_AVAILABLE is False

- [ ] **Step 1: Create test directory and write failing tests**

```bash
mkdir -p /Users/les/Projects/mahavishnu/tests/unit/tui
touch /Users/les/Projects/mahavishnu/tests/unit/tui/__init__.py
```

Create `tests/unit/tui/test_tui_availability.py`:

```python
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_tui_available_is_bool() -> None:
    import mahavishnu.tui as tui

    assert isinstance(tui.TUI_AVAILABLE, bool)


@pytest.mark.unit
def test_get_console_returns_rich_console() -> None:
    from rich.console import Console

    from mahavishnu.tui import get_console

    console = get_console()
    assert isinstance(console, Console)


@pytest.mark.unit
def test_tui_available_can_be_patched_as_boolean() -> None:
    """Confirm tests can override TUI_AVAILABLE by patching the bool attribute."""
    import mahavishnu.tui as tui

    original = tui.TUI_AVAILABLE
    tui.TUI_AVAILABLE = False
    assert tui.TUI_AVAILABLE is False
    tui.TUI_AVAILABLE = original  # restore


@pytest.mark.unit
def test_fallback_formatter_formats_dict_as_table() -> None:
    from io import StringIO

    from rich.console import Console

    from mahavishnu.tui import FallbackRichFormatter

    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)
    formatter.format_dict({"status": "ok", "workers": 3})
    output = buf.getvalue()
    assert "status" in output
    assert "ok" in output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/tui/test_tui_availability.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'mahavishnu.tui'`

- [ ] **Step 3: Create `mahavishnu/tui/__init__.py`**

```bash
mkdir -p /Users/les/Projects/mahavishnu/mahavishnu/tui
```

Create `mahavishnu/tui/__init__.py`:

```python
from __future__ import annotations

import importlib.util
from typing import Any

from oneiric.logging import get_logger
from rich.console import Console
from rich.table import Table

logger = get_logger(__name__)

# Evaluated once at module load — patch this bool in tests, not find_spec.
TUI_AVAILABLE: bool = importlib.util.find_spec("textual") is not None

_console: Console | None = None


def get_console() -> Console:
    """Return a shared Rich Console instance."""
    global _console
    if _console is None:
        _console = Console()
    return _console


class FallbackRichFormatter:
    """Plain Rich-formatted output for environments without Textual."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or get_console()

    def format_dict(self, data: dict[str, Any], title: str = "") -> None:
        """Render a dict as a two-column Rich table."""
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        self._console.print(table)

    def format_list(self, items: list[dict[str, Any]], columns: list[str], title: str = "") -> None:
        """Render a list of dicts as a Rich table with specified columns."""
        table = Table(title=title, show_header=True, header_style="bold cyan")
        for col in columns:
            table.add_column(col.title(), style="bold" if col == "name" else "")
        for item in items:
            table.add_row(*[str(item.get(col, "—")) for col in columns])
        self._console.print(table)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/tui/test_tui_availability.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/tui/__init__.py \
        tests/unit/tui/__init__.py tests/unit/tui/test_tui_availability.py
git commit -m "feat(tui): add mahavishnu.tui module with TUI_AVAILABLE, FallbackRichFormatter, get_console"
```

______________________________________________________________________

## Task 2: Textual Widgets + MonitorApp

**Files:**

- Create: `mahavishnu/tui/widgets.py`
- Create: `mahavishnu/tui/monitor_app.py`

**Interfaces:**

- Consumes: `TUI_AVAILABLE` from `mahavishnu/tui/__init__.py` (Task 1)
- Produces: `PoolStatusWidget`, `WorkerStatusWidget` — Textual `Static` widgets
- Produces: `MonitorApp` — Textual `App` with auto-refresh and pool/worker tables

Note: These files do NOT have unit tests in this task (Textual apps require async runner). Visual testing is manual — start the app and verify the dashboard renders.

- [ ] **Step 1: Create `mahavishnu/tui/widgets.py`**

```python
from __future__ import annotations

from typing import Any

from mahavishnu.tui import TUI_AVAILABLE

if TUI_AVAILABLE:
    from textual.widgets import Static

    class PoolStatusWidget(Static):
        """Displays pool name, type, worker count, and health status."""

        DEFAULT_CSS = """
        PoolStatusWidget {
            border: solid $accent;
            padding: 0 1;
            margin: 0 0 1 0;
        }
        """

        def __init__(self, pool_data: dict[str, Any]) -> None:
            label = (
                f"[bold]{pool_data.get('name', '—')}[/bold]  "
                f"type={pool_data.get('type', '?')}  "
                f"workers={pool_data.get('worker_count', 0)}  "
                f"health=[{'green' if pool_data.get('healthy') else 'red'}]"
                f"{'OK' if pool_data.get('healthy') else 'DOWN'}[/]"
            )
            super().__init__(label)

    class WorkerStatusWidget(Static):
        """Displays worker ID, type, and current status."""

        DEFAULT_CSS = """
        WorkerStatusWidget {
            padding: 0 1;
        }
        """

        def __init__(self, worker_data: dict[str, Any]) -> None:
            status = worker_data.get("status", "unknown")
            color = {"running": "green", "idle": "cyan", "failed": "red"}.get(status, "white")
            label = (
                f"[{color}]{worker_data.get('id', '—')}[/]  "
                f"type={worker_data.get('type', '?')}  "
                f"status=[{color}]{status}[/]"
            )
            super().__init__(label)

else:

    class PoolStatusWidget:  # type: ignore[no-redef]
        def __init__(self, pool_data: dict[str, Any]) -> None:
            self._data = pool_data

    class WorkerStatusWidget:  # type: ignore[no-redef]
        def __init__(self, worker_data: dict[str, Any]) -> None:
            self._data = worker_data
```

- [ ] **Step 2: Create `mahavishnu/tui/monitor_app.py`**

```python
from __future__ import annotations

from typing import Any

from mahavishnu.tui import TUI_AVAILABLE, get_console

if TUI_AVAILABLE:
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header, ScrollableContainer

    from .widgets import PoolStatusWidget, WorkerStatusWidget

    class MonitorApp(App):
        """Live Mahavishnu monitor TUI dashboard.

        Refreshes pool and worker status every 5 seconds.
        """

        CSS = """
        Screen {
            layout: vertical;
        }
        ScrollableContainer {
            height: 1fr;
            border: solid $primary;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh now"),
        ]

        def __init__(self, data_provider: Any | None = None) -> None:
            super().__init__()
            self._data_provider = data_provider
            self._pool_data: list[dict[str, Any]] = []
            self._worker_data: list[dict[str, Any]] = []

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield ScrollableContainer(id="pool-container")
            yield ScrollableContainer(id="worker-container")
            yield Footer()

        def on_mount(self) -> None:
            self.set_interval(5, self.action_refresh)
            self.action_refresh()

        async def action_refresh(self) -> None:
            if self._data_provider:
                try:
                    self._pool_data = await self._data_provider.get_pools()
                    self._worker_data = await self._data_provider.get_workers()
                except Exception:
                    pass
            self._render_pools()
            self._render_workers()

        def _render_pools(self) -> None:
            container = self.query_one("#pool-container", ScrollableContainer)
            container.remove_children()
            for pool in self._pool_data:
                container.mount(PoolStatusWidget(pool))

        def _render_workers(self) -> None:
            container = self.query_one("#worker-container", ScrollableContainer)
            container.remove_children()
            for worker in self._worker_data:
                container.mount(WorkerStatusWidget(worker))

else:

    class MonitorApp:  # type: ignore[no-redef]
        """Fallback for environments without Textual."""

        def __init__(self, data_provider: Any | None = None) -> None:
            self._data_provider = data_provider

        def run(self) -> None:
            console = get_console()
            console.print(
                "[yellow]Textual not installed. Install with: uv add --optional tui textual[/yellow]"
            )
```

- [ ] **Step 3: Verify imports work**

```bash
cd /Users/les/Projects/mahavishnu && python -c "
from mahavishnu.tui.monitor_app import MonitorApp
from mahavishnu.tui.widgets import PoolStatusWidget
print('MonitorApp:', MonitorApp)
print('PoolStatusWidget:', PoolStatusWidget)
"
```

Expected: no error (imports succeed regardless of whether Textual is installed)

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/tui/widgets.py mahavishnu/tui/monitor_app.py
git commit -m "feat(tui): add MonitorApp Textual dashboard and Pool/Worker status widgets"
```

______________________________________________________________________

## Task 3: `monitor watch` CLI Command

**Files:**

- Modify: `mahavishnu/cli/monitoring_cli.py`

**Interfaces:**

- Consumes: `MonitorApp` from `mahavishnu/tui/monitor_app.py` (Task 2)

- Consumes: `TUI_AVAILABLE` from `mahavishnu/tui/__init__.py` (Task 1)

- Consumes: `FallbackRichFormatter` from `mahavishnu/tui/__init__.py` (Task 1)

- Produces: `mahavishnu monitor watch` CLI command — launches `MonitorApp` or prints Rich fallback

- [ ] **Step 1: Read current monitoring_cli.py structure**

```bash
head -50 /Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py
```

Look for: the main app object name (typically `app` or `monitor_app`), the existing `get-dashboard` command, and the import pattern used.

- [ ] **Step 2: Add `watch` subcommand and upgrade `get-dashboard` output**

In `mahavishnu/cli/monitoring_cli.py`, after the existing imports, add:

```python
from mahavishnu.tui import TUI_AVAILABLE, FallbackRichFormatter, get_console
```

Then add the new `watch` command. If the file uses `@app.command()` pattern:

```python
@app.command(name="watch")
def watch_dashboard(
    refresh: int = typer.Option(5, help="Refresh interval in seconds"),
) -> None:
    """Launch a live Textual monitor dashboard (requires tui extra)."""
    if TUI_AVAILABLE:
        from mahavishnu.tui.monitor_app import MonitorApp  # noqa: PLC0415

        monitor = MonitorApp()
        monitor.run()
    else:
        console = get_console()
        console.print(
            "[yellow]Textual not installed.[/yellow] "
            "Install: [bold]uv add --optional tui textual[/bold]\n"
            "Falling back to one-shot Rich output...\n"
        )
        _print_rich_dashboard()


def _print_rich_dashboard() -> None:
    """Print a one-shot Rich-formatted system status to the terminal."""
    import asyncio  # noqa: PLC0415

    from mahavishnu.core.app import MahavishnuApp  # noqa: PLC0415

    formatter = FallbackRichFormatter()

    try:
        app_instance = MahavishnuApp()
        metrics = asyncio.run(app_instance.get_metrics())
    except Exception as e:
        formatter.format_dict({"error": str(e)}, title="Monitor Error")
        return

    formatter.format_dict(
        {
            "workflows_active": metrics.get("workflows_active", 0),
            "workflows_completed": metrics.get("workflows_completed", 0),
            "pools_active": metrics.get("pools_active", 0),
            "workers_running": metrics.get("workers_running", 0),
            "adapter_health": metrics.get("adapter_health", "unknown"),
        },
        title="Mahavishnu System Status",
    )
```

Also upgrade `get-dashboard` to use Rich Console for output (find the existing `get_dashboard` function and replace `typer.echo(...)` calls with `console.print(...)`):

```python
console = get_console()
console.print(...)  # replace typer.echo
```

- [ ] **Step 3: Verify the command is registered**

```bash
cd /Users/les/Projects/mahavishnu && python -m mahavishnu._main_cli monitor --help 2>&1 | head -20
```

Expected: output includes `watch` in the command list.

- [ ] **Step 4: Test the fallback path (Textual not available)**

```python
# Manual verification test (run this in the REPL):
import mahavishnu.tui as tui
tui.TUI_AVAILABLE = False
from mahavishnu.cli.monitoring_cli import watch_dashboard
# watch_dashboard() should print the Textual-not-installed message and fall back to Rich
```

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/monitoring_cli.py
git commit -m "feat(cli): add 'monitor watch' Textual dashboard command with Rich fallback"
```

______________________________________________________________________

## Task 4: Rich Quality CLI

**Files:**

- Modify: `mahavishnu/quality_cli.py`

**Interfaces:**

- Consumes: `FallbackRichFormatter`, `get_console` from `mahavishnu/tui/__init__.py` (Task 1)
- Produces: `mahavishnu quality check` — Rich table output (replaces the stub)

Note: `run_quality_check(output: str) -> int | None` is used by Track 2's `openhands_tools.py`. Make sure that function signature remains unchanged.

- [ ] **Step 1: Read current quality_cli.py**

```bash
cat /Users/les/Projects/mahavishnu/mahavishnu/quality_cli.py
```

Identify: the stub line `typer.echo("Quality check complete (stub)")` and the structure of the CLI app.

- [ ] **Step 2: Replace stub with Rich implementation**

Replace `mahavishnu/quality_cli.py` content. Keep the existing typer app/command structure. Replace the stub body:

```python
from __future__ import annotations

from pathlib import Path

import typer
from oneiric.logging import get_logger

from mahavishnu.tui import FallbackRichFormatter, get_console

logger = get_logger(__name__)
app = typer.Typer(help="Quality evaluation and reporting")


async def run_quality_check(output: str) -> int | None:
    """Run Crackerjack quality check on a string output. Returns score or None.

    Used by openhands_tools.py and the 'quality check' CLI command.
    """
    try:
        import crackerjack  # noqa: PLC0415

        score = await crackerjack.evaluate(output)
        return score
    except Exception as e:
        logger.warning(f"Crackerjack quality check failed: {e}")
        return None


@app.command(name="check")
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
        logger.exception(f"Quality check failed: {e}")
        console.print(f"[red]Quality check error:[/red] {e}")
        raise typer.Exit(code=1)


@app.command(name="report")
def quality_report(
    path: Path = typer.Argument(Path("."), help="Path to evaluate"),
    output_format: str = typer.Option("table", help="Output format: table or json"),
) -> None:
    """Generate a detailed quality report for a repository path."""
    console = get_console()
    console.print(f"[bold]Quality Report[/bold] for [cyan]{path}[/cyan]")
    console.print("[dim]Run 'quality check' for a quick gate check.[/dim]")
```

- [ ] **Step 3: Verify `run_quality_check` is callable (used by Track 2)**

```bash
cd /Users/les/Projects/mahavishnu && python -c "
import asyncio
from mahavishnu.quality_cli import run_quality_check
result = asyncio.run(run_quality_check('test output'))
print('result:', result)  # None expected (crackerjack may not be connected)
"
```

Expected: prints `result: None` (graceful failure when crackerjack not available)

- [ ] **Step 4: Verify CLI help**

```bash
cd /Users/les/Projects/mahavishnu && python -m mahavishnu._main_cli quality --help 2>&1
```

Expected: shows `check` and `report` subcommands.

- [ ] **Step 5: Full Track 3 regression run**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/tui/ -v
```

Expected: all TUI unit tests PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/quality_cli.py
git commit -m "feat(cli): replace quality_check stub with Rich-formatted Crackerjack integration"
```
