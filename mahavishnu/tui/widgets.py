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
            color = {
                "running": "green",
                "idle": "cyan",
                "failed": "red",
            }.get(status, "white")
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
