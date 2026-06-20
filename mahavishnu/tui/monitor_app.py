from __future__ import annotations

from typing import Any

from mahavishnu.tui import TUI_AVAILABLE, get_console

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
                "[yellow]Textual not installed. Install with: uv add"
                " --optional tui textual[/yellow]"
            )
