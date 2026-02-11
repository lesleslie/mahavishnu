"""Real-time pool monitoring demo with rich terminal UI.

This demo connects to the Mahavishnu WebSocket server and displays
real-time updates for a specific pool, including:
- Pool spawn/scale/close events
- Worker add/remove/status changes
- Task assignment/completion
- Connection status indicator

Usage:
    python pool_monitor.py --pool-id pool_local
    python pool_monitor.py --pool-id pool_local --host localhost --port 8690
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from datetime import datetime, UTC
from enum import Enum
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout


class ConnectionStatus(Enum):
    """Connection status indicators."""

    DISCONNECTED = ("disconnected", "[red]●[/red]")
    CONNECTING = ("connecting", "[yellow]●[/yellow]")
    CONNECTED = ("connected", "[green]●[/green]")
    ERROR = ("error", "[red]●[/red]")

    def __init__(self, status: str, indicator: str):
        self.status = status
        self.indicator = indicator


class PoolEventTypes(Enum):
    """Pool event types for categorization."""

    POOL_SPAWNED = "pool.spawned"
    POOL_CLOSED = "pool.closed"
    POOL_SCALED = "pool.scaling"
    WORKER_ADDED = "worker_added"
    WORKER_REMOVED = "worker_removed"
    WORKER_STATUS = "worker.status_changed"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    POOL_STATUS = "pool.status_changed"
    UNKNOWN = "unknown"


class PoolMonitor:
    """Real-time pool monitor with rich terminal UI.

    Attributes:
        pool_id: Pool identifier to monitor
        host: WebSocket server host
        port: WebSocket server port
        max_events: Maximum events to keep in history
    """

    def __init__(
        self,
        pool_id: str,
        host: str = "127.0.0.1",
        port: int = 8690,
        max_events: int = 50,
    ):
        """Initialize pool monitor.

        Args:
            pool_id: Pool identifier to monitor
            host: WebSocket server host
            port: WebSocket server port
            max_events: Maximum events to keep in history
        """
        self.pool_id = pool_id
        self.host = host
        self.port = port
        self.uri = f"ws://{host}:{port}"
        self.max_events = max_events

        # State
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.websocket = None
        self.running = False
        self.start_time = None
        self.message_count = 0
        self.last_event_time = None

        # Pool state
        self.pool_status = {
            "worker_count": 0,
            "queue_size": 0,
            "status": "unknown",
        }
        self.workers: dict[str, dict[str, Any]] = {}
        self.recent_events: list[dict[str, Any]] = []

        # Terminal UI
        self.console = Console()
        self.layout = Layout()
        self._setup_layout()

    def _setup_layout(self) -> None:
        """Setup rich layout for dashboard."""
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3),
        )
        self.layout["body"].split(
            Layout(name="status", ratio=1),
            Layout(name="workers", ratio=1),
            Layout(name="events", ratio=1),
        )

    def _render_header(self) -> Panel:
        """Render header panel."""
        status_text = Text.assemble(
            self.connection_status.indicator,
            f" {self.connection_status.status.upper()}",
        )
        uptime_text = ""
        if self.start_time:
            uptime = datetime.now(UTC) - self.start_time
            uptime_text = f" | Uptime: {uptime.total_seconds():.0f}s"

        header_text = Text.assemble(
            ("Pool Monitor", "bold cyan"),
            f" | Pool: {self.pool_id}",
            f" | Server: {self.host}:{self.port}",
            f" | Messages: {self.message_count}",
            uptime_text,
            " | ",
            status_text,
        )

        return Panel(header_text, style="on black")

    def _render_status(self) -> Panel:
        """Render pool status panel."""
        table = Table(title="Pool Status", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Pool ID", self.pool_id)
        table.add_row("Status", self.pool_status.get("status", "unknown"))
        table.add_row("Worker Count", str(self.pool_status.get("worker_count", 0)))
        table.add_row("Queue Size", str(self.pool_status.get("queue_size", 0)))

        if self.last_event_time:
            elapsed = (datetime.now(UTC) - self.last_event_time).total_seconds()
            table.add_row("Last Event", f"{elapsed:.1f}s ago")

        return Panel(table, title="Pool Status", border_style="cyan")

    def _render_workers(self) -> Panel:
        """Render workers panel."""
        table = Table(title="Workers", show_header=True, header_style="bold yellow")
        table.add_column("Worker ID", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Pool", style="blue")

        for worker_id, worker_data in self.workers.items():
            status = worker_data.get("status", "unknown")
            pool_id = worker_data.get("pool_id", self.pool_id)

            # Color-code status
            status_color = "green"
            if status == "busy":
                status_color = "yellow"
            elif status == "error":
                status_color = "red"
            elif status == "offline":
                status_color = "grey"

            table.add_row(worker_id, f"[{status_color}]{status}[/{status_color}]", pool_id)

        if not self.workers:
            table.add_row("[dim]No workers[/dim]", "", "")

        return Panel(table, title="Workers", border_style="yellow")

    def _render_events(self) -> Panel:
        """Render recent events panel."""
        table = Table(title="Recent Events", show_header=True, header_style="bold blue")
        table.add_column("Time", style="dim", width=8)
        table.add_column("Type", style="cyan")
        table.add_column("Details", style="white")

        # Show most recent events first
        for event in reversed(self.recent_events[-10:]):
            timestamp = event.get("timestamp", "")
            if timestamp:
                # Parse ISO timestamp and show relative time
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = "???"

            event_type = event.get("type", "unknown")
            details = event.get("details", "")

            # Color-code event types
            type_color = "white"
            if "spawned" in event_type.lower() or "added" in event_type.lower():
                type_color = "green"
            elif "closed" in event_type.lower() or "removed" in event_type.lower():
                type_color = "red"
            elif "error" in event_type.lower() or "failed" in event_type.lower():
                type_color = "red"
            elif "status" in event_type.lower():
                type_color = "yellow"

            table.add_row(time_str, f"[{type_color}]{event_type}[/{type_color}]", details)

        if not self.recent_events:
            table.add_row("[dim]--[/dim]", "[dim]No events yet[/dim]", "")

        return Panel(table, title="Recent Events", border_style="blue")

    def _render_footer(self) -> Panel:
        """Render footer panel."""
        footer_text = Text.assemble(
            ("Press Ctrl+C to exit", "dim"),
            " | ",
            (f"Events in history: {len(self.recent_events)}", "cyan"),
            " | ",
            (f"Active workers: {len(self.workers)}", "yellow"),
        )

        return Panel(footer_text, style="on black")

    def _update_layout(self) -> None:
        """Update all layout panels."""
        self.layout["header"].update(self._render_header())
        self.layout["status"].update(self._render_status())
        self.layout["workers"].update(self._render_workers())
        self.layout["events"].update(self._render_events())
        self.layout["footer"].update(self._render_footer())

    async def connect(self) -> None:
        """Connect to WebSocket server."""
        self.connection_status = ConnectionStatus.CONNECTING
        self.console.print(f"[yellow]Connecting to {self.uri}...[/yellow]")

        try:
            self.websocket = await websockets.connect(
                self.uri,
                close_timeout=10,
                ping_timeout=20,
            )
            self.connection_status = ConnectionStatus.CONNECTED
            self.start_time = datetime.now(UTC)
            self.console.print("[green]Connected successfully![/green]")

            # Receive welcome message
            welcome = await self.websocket.recv()
            data = json.loads(welcome)
            self.console.print(f"[dim]Server: {data.get('message', 'Welcome')}[/dim]")

            # Subscribe to pool channel
            await self._subscribe_to_pool()

        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.console.print(f"[red]Connection failed: {e}[/red]")
            raise

    async def _subscribe_to_pool(self) -> None:
        """Subscribe to pool channel."""
        if not self.websocket:
            return

        message = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": f"pool:{self.pool_id}"},
            "id": f"sub_{self.pool_id}",
        }

        await self.websocket.send(json.dumps(message))
        self.console.print(f"[cyan]Subscribed to pool: {self.pool_id}[/cyan]")

        # Wait for confirmation
        try:
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            data = json.loads(response)
            if data.get("status") == "subscribed":
                self.console.print(f"[green]Subscription confirmed[/green]")
            else:
                self.console.print(f"[yellow]Subscription response: {data}[/yellow]")
        except asyncio.TimeoutError:
            self.console.print("[yellow]No subscription confirmation received[/yellow]")

    def _add_event(self, event_type: str, details: str) -> None:
        """Add event to history.

        Args:
            event_type: Type of event
            details: Event details
        """
        event = {
            "type": event_type,
            "details": details,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.recent_events.append(event)
        self.last_event_time = datetime.now(UTC)

        # Trim old events
        if len(self.recent_events) > self.max_events:
            self.recent_events = self.recent_events[-self.max_events:]

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: JSON message string
        """
        try:
            data = json.loads(message)
            self.message_count += 1

            message_type = data.get("type", "unknown")

            if message_type == "event":
                await self._handle_event(data)
            elif message_type == "response":
                # Handle response messages
                self._add_event("response", f"Request ID: {data.get('id', 'unknown')}")
            else:
                self._add_event("unknown", f"Unknown message type: {message_type}")

        except json.JSONDecodeError as e:
            self.console.print(f"[red]JSON decode error: {e}[/red]")
        except Exception as e:
            self.console.print(f"[red]Error handling message: {e}[/red]")

    async def _handle_event(self, data: dict[str, Any]) -> None:
        """Handle event message.

        Args:
            data: Event data dictionary
        """
        event = data.get("event", "")
        event_data = data.get("data", {})

        # Handle different event types
        if event == "pool.status_changed":
            self._handle_pool_status_changed(event_data)
        elif event == "worker.status_changed":
            self._handle_worker_status_changed(event_data)
        elif event == "pool.scaling":
            self._handle_pool_scaling(event_data)
        elif event == "task.assigned":
            self._handle_task_assigned(event_data)
        elif event == "task.completed":
            self._handle_task_completed(event_data)
        else:
            self._add_event(event, str(event_data))

    def _handle_pool_status_changed(self, data: dict[str, Any]) -> None:
        """Handle pool status changed event.

        Args:
            data: Event data
        """
        self.pool_status.update(data)
        self._add_event(
            "pool.status_changed",
            f"Workers: {data.get('worker_count', '?')}, Queue: {data.get('queue_size', '?')}",
        )

    def _handle_worker_status_changed(self, data: dict[str, Any]) -> None:
        """Handle worker status changed event.

        Args:
            data: Event data
        """
        worker_id = data.get("worker_id", "unknown")
        status = data.get("status", "unknown")
        pool_id = data.get("pool_id", self.pool_id)

        self.workers[worker_id] = {
            "status": status,
            "pool_id": pool_id,
        }

        self._add_event(
            "worker.status_changed",
            f"Worker {worker_id}: {status}",
        )

    def _handle_pool_scaling(self, data: dict[str, Any]) -> None:
        """Handle pool scaling event.

        Args:
            data: Event data
        """
        event_type = data.get("event_type", "unknown")
        self._add_event("pool.scaling", f"{event_type}")

    def _handle_task_assigned(self, data: dict[str, Any]) -> None:
        """Handle task assigned event.

        Args:
            data: Event data
        """
        task_id = data.get("task_id", "unknown")
        worker_id = data.get("worker_id", "unknown")
        self._add_event("task.assigned", f"{task_id} -> {worker_id}")

    def _handle_task_completed(self, data: dict[str, Any]) -> None:
        """Handle task completed event.

        Args:
            data: Event data
        """
        task_id = data.get("task_id", "unknown")
        self._add_event("task.completed", f"{task_id}")

    async def listen(self) -> None:
        """Listen for WebSocket events."""
        if not self.websocket:
            self.console.print("[red]Not connected[/red]")
            return

        self.running = True

        try:
            with Live(
                self.layout,
                console=self.console,
                refresh_per_second=10,
                screen=False,
            ) as live:
                while self.running:
                    try:
                        message = await asyncio.wait_for(
                            self.websocket.recv(),
                            timeout=0.1,
                        )
                        await self._handle_message(message)
                        self._update_layout()

                    except asyncio.TimeoutError:
                        # Update layout periodically
                        self._update_layout()
                        continue
                    except ConnectionClosed:
                        self.console.print("[red]Connection closed by server[/red]")
                        self.connection_status = ConnectionStatus.DISCONNECTED
                        break

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Interrupted by user[/yellow]")
        finally:
            self.running = False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        if self.websocket:
            await self.websocket.close()
            self.connection_status = ConnectionStatus.DISCONNECTED
            self.console.print("[dim]Disconnected[/dim]")

    async def run(self) -> None:
        """Run the pool monitor."""
        try:
            await self.connect()
            await self.listen()
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
        finally:
            await self.disconnect()


async def main(
    pool_id: str,
    host: str = "127.0.0.1",
    port: int = 8690,
) -> None:
    """Main entry point.

    Args:
        pool_id: Pool identifier to monitor
        host: WebSocket server host
        port: WebSocket server port
    """
    monitor = PoolMonitor(pool_id=pool_id, host=host, port=port)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler():
        monitor.console.print("\n[yellow]Shutting down...[/yellow]")
        monitor.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await monitor.run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import typer

    app = typer.Typer(help="Real-time pool monitoring demo")

    @app.command()
    def run(
        pool_id: str = typer.Argument(..., help="Pool ID to monitor"),
        host: str = typer.Option("127.0.0.1", "--host", help="WebSocket server host"),
        port: int = typer.Option(8690, "--port", help="WebSocket server port"),
    ):
        """Run pool monitor.

        Example:
            pool-monitor run pool_local --host localhost --port 8690
        """
        asyncio.run(main(pool_id=pool_id, host=host, port=port))

    app()
