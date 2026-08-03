from __future__ import annotations

from typing import Any, ClassVar

from oneiric.core.logging import get_logger

from mahavishnu.tui import TUI_AVAILABLE, get_console

logger = get_logger(__name__)


class _DefaultMonitorDataProvider:
    """Default data provider for ``MonitorApp``.

    Bridges :meth:`MahavishnuApp.get_metrics` to the
    ``get_pools()`` / ``get_workers()`` shape expected by
    ``MonitorApp``. Returns one aggregate row per call on
    success; an empty list on any error so the TUI always
    renders (the existing ``try/except`` in ``action_refresh``
    catches additional failures).

    The aggregate row is a thin stand-in: ``MahavishnuApp`` does
    not currently expose per-pool or per-worker detail. A future
    v1.5+ change can replace this with a real per-pool/worker
    provider; for now, one labelled summary row is better than
    empty containers, and cheaper than a new API.
    """

    async def get_pools(self) -> list[dict[str, Any]]:
        try:
            from mahavishnu.core.app import MahavishnuApp

            app = MahavishnuApp()
            metrics = await app.get_metrics()
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return []
        return [
            {
                "name": "aggregate",
                "type": "summary",
                "worker_count": int(metrics.get("workers_running", 0) or 0),
                "healthy": metrics.get("adapter_health") != "unhealthy",
            }
        ]

    async def get_workers(self) -> list[dict[str, Any]]:
        try:
            from mahavishnu.core.app import MahavishnuApp

            app = MahavishnuApp()
            metrics = await app.get_metrics()
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return []
        running = int(metrics.get("workers_running", 0) or 0)
        return [
            {
                "id": "aggregate",
                "type": "summary",
                "status": "running" if running > 0 else "idle",
            }
        ]


if TUI_AVAILABLE:
    from textual.app import App, ComposeResult
    from textual.containers import ScrollableContainer
    from textual.widgets import Footer, Header

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

        BINDINGS: ClassVar[list] = [
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
            self.call_after_refresh(self.action_refresh)

        async def action_refresh(self) -> None:
            if self._data_provider:
                try:
                    self._pool_data = await self._data_provider.get_pools()
                    self._worker_data = await self._data_provider.get_workers()
                except Exception as e:  # noqa: BLE001 - event handler; logs and continues
                    logger.debug("Data provider fetch skipped: %s", e)
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
                "[yellow]Textual not installed. Install with: uv add --group tui textual[/yellow]"
            )
