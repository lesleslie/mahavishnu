"""Multi-service real-time dashboard for Mahavishnu ecosystem.

This demo creates a unified terminal UI showing real-time updates from:
- Mahavishnu workflows (left panel)
- Pool status (center panel)
- Akosha insights (right panel)

All panels update asynchronously from their respective WebSocket services.

Usage:
    python multi_service_dashboard.py
    python multi_service_dashboard.py --mahavishnu-host localhost --mahavishnu-port 8690
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
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.columns import Columns


class ConnectionStatus(Enum):
    """Connection status indicators."""

    DISCONNECTED = ("disconnected", "[red]●[/red]")
    CONNECTING = ("connecting", "[yellow]●[/yellow]")
    CONNECTED = ("connected", "[green]●[/green]")
    ERROR = ("error", "[red]●[/red]")

    def __init__(self, status: str, indicator: str):
        self.status = status
        self.indicator = indicator


class ServiceClient:
    """Base class for service WebSocket clients.

    Attributes:
        name: Service name
        host: WebSocket server host
        port: WebSocket server port
        uri: WebSocket URI
    """

    def __init__(self, name: str, host: str, port: int):
        """Initialize service client.

        Args:
            name: Service name
            host: WebSocket server host
            port: WebSocket server port
        """
        self.name = name
        self.host = host
        self.port = port
        self.uri = f"ws://{host}:{port}"

        # State
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.websocket = None
        self.connected = False
        self.message_count = 0
        self.last_event_time = None
        self.events: list[dict[str, Any]] = []

    async def connect(self) -> bool:
        """Connect to WebSocket server.

        Returns:
            True if connection successful
        """
        self.connection_status = ConnectionStatus.CONNECTING

        try:
            self.websocket = await websockets.connect(
                self.uri,
                close_timeout=10,
                ping_timeout=20,
            )
            self.connection_status = ConnectionStatus.CONNECTED
            self.connected = True

            # Receive welcome message
            welcome = await self.websocket.recv()
            data = json.loads(welcome)

            return True

        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        if self.websocket:
            await self.websocket.close()
            self.connection_status = ConnectionStatus.DISCONNECTED
            self.connected = False

    async def subscribe(self, channel: str) -> None:
        """Subscribe to a channel.

        Args:
            channel: Channel name
        """
        if not self.websocket:
            return

        message = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": channel},
            "id": f"sub_{channel}",
        }

        await self.websocket.send(json.dumps(message))

    def add_event(self, event_type: str, details: str) -> None:
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
        self.events.append(event)
        self.last_event_time = datetime.now(UTC)
        self.message_count += 1

        # Keep only last 20 events
        if len(self.events) > 20:
            self.events = self.events[-20:]

    async def listen(self) -> None:
        """Listen for WebSocket events."""
        if not self.websocket:
            return

        try:
            message = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
            data = json.loads(message)

            if data.get("type") == "event":
                self.handle_event(data)

        except asyncio.TimeoutError:
            pass
        except ConnectionClosed:
            self.connected = False
            self.connection_status = ConnectionStatus.DISCONNECTED
        except Exception:
            pass

    def handle_event(self, data: dict[str, Any]) -> None:
        """Handle event message.

        Args:
            data: Event data
        """
        event = data.get("event", "")
        event_data = data.get("data", {})
        self.add_event(event, str(event_data)[:100])


class MahavishnuClient(ServiceClient):
    """Mahavishnu service client."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8690):
        """Initialize Mahavishnu client.

        Args:
            host: WebSocket server host
            port: WebSocket server port
        """
        super().__init__("Mahavishnu", host, port)

        # Mahavishnu state
        self.workflows: dict[str, dict[str, Any]] = {}
        self.active_workflows = 0
        self.completed_workflows = 0

    async def initialize(self) -> None:
        """Initialize subscriptions."""
        await self.subscribe("global")

    def handle_event(self, data: dict[str, Any]) -> None:
        """Handle Mahavishnu events.

        Args:
            data: Event data
        """
        event = data.get("event", "")
        event_data = data.get("data", {})

        if event == "workflow.started":
            workflow_id = event_data.get("workflow_id", "unknown")
            self.workflows[workflow_id] = {
                "status": "running",
                "started": event_data.get("timestamp"),
            }
            self.active_workflows += 1
            self.add_event("workflow.started", workflow_id)

        elif event == "workflow.completed":
            workflow_id = event_data.get("workflow_id", "unknown")
            if workflow_id in self.workflows:
                self.workflows[workflow_id]["status"] = "completed"
                self.active_workflows -= 1
                self.completed_workflows += 1
            self.add_event("workflow.completed", workflow_id)

        elif event == "workflow.failed":
            workflow_id = event_data.get("workflow_id", "unknown")
            if workflow_id in self.workflows:
                self.workflows[workflow_id]["status"] = "failed"
                self.active_workflows -= 1
            self.add_event("workflow.failed", workflow_id)

        else:
            self.add_event(event, str(event_data)[:100])


class PoolClient(ServiceClient):
    """Pool service client."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8690):
        """Initialize pool client.

        Args:
            host: WebSocket server host
            port: WebSocket server port
        """
        super().__init__("Pool", host, port)

        # Pool state
        self.pool_id = "local"
        self.worker_count = 0
        self.queue_size = 0
        self.pool_status = "unknown"

    async def initialize(self) -> None:
        """Initialize subscriptions."""
        await self.subscribe(f"pool:{self.pool_id}")

    def handle_event(self, data: dict[str, Any]) -> None:
        """Handle pool events.

        Args:
            data: Event data
        """
        event = data.get("event", "")
        event_data = data.get("data", {})

        if event == "pool.status_changed":
            self.worker_count = event_data.get("worker_count", self.worker_count)
            self.queue_size = event_data.get("queue_size", self.queue_size)
            self.pool_status = event_data.get("status", self.pool_status)
            self.add_event("pool.status_changed", f"Workers: {self.worker_count}")

        elif event == "worker.status_changed":
            worker_id = event_data.get("worker_id", "unknown")
            status = event_data.get("status", "unknown")
            self.add_event("worker.status_changed", f"{worker_id}: {status}")

        elif event == "pool.scaling":
            event_type = event_data.get("event_type", "unknown")
            self.add_event("pool.scaling", event_type)

        else:
            self.add_event(event, str(event_data)[:100])


class AkoshaClient(ServiceClient):
    """Akosha insights service client.

    Note: This is a placeholder client for Akosha integration.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8682):
        """Initialize Akosha client.

        Args:
            host: WebSocket server host
            port: WebSocket server port
        """
        super().__init__("Akosha", host, port)

        # Akosha state
        self.insights_count = 0
        self.patterns_detected = 0

    async def initialize(self) -> None:
        """Initialize subscriptions."""
        await self.subscribe("insights")

    def handle_event(self, data: dict[str, Any]) -> None:
        """Handle Akosha events.

        Args:
            data: Event data
        """
        event = data.get("event", "")
        event_data = data.get("data", {})

        if event == "insight.generated":
            self.insights_count += 1
            insight_type = event_data.get("type", "unknown")
            self.add_event("insight.generated", insight_type)

        elif event == "pattern.detected":
            self.patterns_detected += 1
            pattern = event_data.get("pattern", "unknown")
            self.add_event("pattern.detected", pattern)

        else:
            self.add_event(event, str(event_data)[:100])


class MultiServiceDashboard:
    """Multi-service dashboard with real-time updates.

    Attributes:
        mahavishnu_client: Mahavishnu service client
        pool_client: Pool service client
        akosha_client: Akosha service client
        refresh_rate: Dashboard refresh rate in seconds
    """

    def __init__(
        self,
        mahavishnu_host: str = "127.0.0.1",
        mahavishnu_port: int = 8690,
        pool_host: str = "127.0.0.1",
        pool_port: int = 8690,
        akosha_host: str = "127.0.0.1",
        akosha_port: int = 8682,
        refresh_rate: float = 0.1,
    ):
        """Initialize multi-service dashboard.

        Args:
            mahavishnu_host: Mahavishnu WebSocket host
            mahavishnu_port: Mahavishnu WebSocket port
            pool_host: Pool WebSocket host
            pool_port: Pool WebSocket port
            akosha_host: Akosha WebSocket host
            akosha_port: Akosha WebSocket port
            refresh_rate: Dashboard refresh rate in seconds
        """
        self.mahavishnu_client = MahavishnuClient(mahavishnu_host, mahavishnu_port)
        self.pool_client = PoolClient(pool_host, pool_port)
        self.akosha_client = AkoshaClient(akosha_host, akosha_port)
        self.refresh_rate = refresh_rate

        # State
        self.running = False
        self.start_time = None

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
        self.layout["body"].split_row(
            Layout(name="mahavishnu", ratio=1),
            Layout(name="pool", ratio=1),
            Layout(name="akosha", ratio=1),
        )

    def _render_header(self) -> Panel:
        """Render header panel."""
        uptime_text = ""
        if self.start_time:
            uptime = datetime.now(UTC) - self.start_time
            uptime_text = f" | Uptime: {uptime.total_seconds():.0f}s"

        header_text = Text.assemble(
            ("Multi-Service Dashboard", "bold cyan"),
            uptime_text,
            " | ",
            self.mahavishnu_client.connection_status.indicator,
            " Mahavishnu ",
            self.pool_client.connection_status.indicator,
            " Pool ",
            self.akosha_client.connection_status.indicator,
            " Akosha",
        )

        return Panel(header_text, style="on black")

    def _render_mahavishnu(self) -> Panel:
        """Render Mahavishnu panel."""
        # Stats
        stats = Text.assemble(
            ("Active Workflows: ", "cyan"),
            (str(self.mahavishnu_client.active_workflows), "bold yellow"),
            (" | Completed: ", "cyan"),
            (str(self.mahavishnu_client.completed_workflows), "bold green"),
            (" | Messages: ", "cyan"),
            (str(self.mahavishnu_client.message_count), "dim"),
        )

        # Events table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Time", style="dim", width=8)
        table.add_column("Event", style="cyan")

        for event in reversed(self.mahavishnu_client.events[-10:]):
            timestamp = event.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = "???"

            event_type = event.get("type", "unknown")
            details = event.get("details", "")[:30]

            table.add_row(time_str, f"{event_type}: {details}")

        content = Group(stats, table)

        return Panel(
            content,
            title="Mahavishnu Workflows",
            title_align="left",
            border_style="cyan",
        )

    def _render_pool(self) -> Panel:
        """Render Pool panel."""
        # Stats
        stats = Text.assemble(
            ("Workers: ", "cyan"),
            (str(self.pool_client.worker_count), "bold yellow"),
            (" | Queue: ", "cyan"),
            (str(self.pool_client.queue_size), "bold green"),
            (" | Messages: ", "cyan"),
            (str(self.pool_client.message_count), "dim"),
        )

        # Events table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Time", style="dim", width=8)
        table.add_column("Event", style="cyan")

        for event in reversed(self.pool_client.events[-10:]):
            timestamp = event.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = "???"

            event_type = event.get("type", "unknown")
            details = event.get("details", "")[:30]

            table.add_row(time_str, f"{event_type}: {details}")

        content = Group(stats, table)

        return Panel(
            content,
            title="Pool Status",
            title_align="left",
            border_style="yellow",
        )

    def _render_akosha(self) -> Panel:
        """Render Akosha panel."""
        # Stats
        stats = Text.assemble(
            ("Insights: ", "cyan"),
            (str(self.akosha_client.insights_count), "bold yellow"),
            (" | Patterns: ", "cyan"),
            (str(self.akosha_client.patterns_detected), "bold green"),
            (" | Messages: ", "cyan"),
            (str(self.akosha_client.message_count), "dim"),
        )

        # Events table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Time", style="dim", width=8)
        table.add_column("Event", style="cyan")

        for event in reversed(self.akosha_client.events[-10:]):
            timestamp = event.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = "???"

            event_type = event.get("type", "unknown")
            details = event.get("details", "")[:30]

            table.add_row(time_str, f"{event_type}: {details}")

        content = Group(stats, table)

        return Panel(
            content,
            title="Akosha Insights",
            title_align="left",
            border_style="magenta",
        )

    def _render_footer(self) -> Panel:
        """Render footer panel."""
        total_messages = (
            self.mahavishnu_client.message_count
            + self.pool_client.message_count
            + self.akosha_client.message_count
        )

        footer_text = Text.assemble(
            ("Press Ctrl+C to exit", "dim"),
            " | ",
            (f"Total Messages: {total_messages}", "cyan"),
            " | Refresh: 100ms",
        )

        return Panel(footer_text, style="on black")

    def _update_layout(self) -> None:
        """Update all layout panels."""
        self.layout["header"].update(self._render_header())
        self.layout["mahavishnu"].update(self._render_mahavishnu())
        self.layout["pool"].update(self._render_pool())
        self.layout["akosha"].update(self._render_akosha())
        self.layout["footer"].update(self._render_footer())

    async def connect(self) -> None:
        """Connect to all services."""
        self.console.print("[yellow]Connecting to services...[/yellow]")

        # Connect to Mahavishnu
        self.console.print(f"  Mahavishnu at {self.mahavishnu_client.uri}...", end="")
        if await self.mahavishnu_client.connect():
            await self.mahavishnu_client.initialize()
            self.console.print(" [green]✓[/green]")
        else:
            self.console.print(" [red]✗[/red]")

        # Connect to Pool (same server as Mahavishnu)
        self.console.print(f"  Pool at {self.pool_client.uri}...", end="")
        if await self.pool_client.connect():
            await self.pool_client.initialize()
            self.console.print(" [green]✓[/green]")
        else:
            self.console.print(" [red]✗[/red]")

        # Connect to Akosha
        self.console.print(f"  Akosha at {self.akosha_client.uri}...", end="")
        if await self.akosha_client.connect():
            await self.akosha_client.initialize()
            self.console.print(" [green]✓[/green]")
        else:
            self.console.print(" [dim]⊘ (not available)[/dim]")

        self.start_time = datetime.now(UTC)
        self.console.print("[green]Services connected[/green]")

    async def listen(self) -> None:
        """Listen for events from all services."""
        self.running = True

        try:
            with Live(
                self.layout,
                console=self.console,
                refresh_per_second=10,
                screen=False,
            ):
                while self.running:
                    # Listen from all services concurrently
                    await asyncio.gather(
                        self.mahavishnu_client.listen(),
                        self.pool_client.listen(),
                        self.akosha_client.listen(),
                        return_exceptions=True,
                    )

                    # Update layout
                    self._update_layout()

                    # Sleep for refresh rate
                    await asyncio.sleep(self.refresh_rate)

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Interrupted by user[/yellow]")
        finally:
            self.running = False

    async def disconnect(self) -> None:
        """Disconnect from all services."""
        await self.mahavishnu_client.disconnect()
        await self.pool_client.disconnect()
        await self.akosha_client.disconnect()
        self.console.print("[dim]Disconnected from all services[/dim]")

    async def run(self) -> None:
        """Run the multi-service dashboard."""
        try:
            await self.connect()
            await self.listen()
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
        finally:
            await self.disconnect()


async def main(
    mahavishnu_host: str = "127.0.0.1",
    mahavishnu_port: int = 8690,
    pool_host: str = "127.0.0.1",
    pool_port: int = 8690,
    akosha_host: str = "127.0.0.1",
    akosha_port: int = 8682,
) -> None:
    """Main entry point.

    Args:
        mahavishnu_host: Mahavishnu WebSocket host
        mahavishnu_port: Mahavishnu WebSocket port
        pool_host: Pool WebSocket host
        pool_port: Pool WebSocket port
        akosha_host: Akosha WebSocket host
        akosha_port: Akosha WebSocket port
    """
    dashboard = MultiServiceDashboard(
        mahavishnu_host=mahavishnu_host,
        mahavishnu_port=mahavishnu_port,
        pool_host=pool_host,
        pool_port=pool_port,
        akosha_host=akosha_host,
        akosha_port=akosha_port,
    )

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler():
        dashboard.console.print("\n[yellow]Shutting down...[/yellow]")
        dashboard.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await dashboard.run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import typer

    app = typer.Typer(help="Multi-service real-time dashboard")

    @app.command()
    def run(
        mahavishnu_host: str = typer.Option(
            "127.0.0.1",
            "--mahavishnu-host",
            help="Mahavishnu WebSocket host",
        ),
        mahavishnu_port: int = typer.Option(
            8690,
            "--mahavishnu-port",
            help="Mahavishnu WebSocket port",
        ),
        pool_host: str = typer.Option(
            "127.0.0.1",
            "--pool-host",
            help="Pool WebSocket host",
        ),
        pool_port: int = typer.Option(
            8690,
            "--pool-port",
            help="Pool WebSocket port",
        ),
        akosha_host: str = typer.Option(
            "127.0.0.1",
            "--akosha-host",
            help="Akosha WebSocket host",
        ),
        akosha_port: int = typer.Option(
            8682,
            "--akosha-port",
            help="Akosha WebSocket port",
        ),
    ):
        """Run multi-service dashboard.

        Example:
            dashboard run --mahavishnu-host localhost --mahavishnu-port 8690
        """
        asyncio.run(
            main(
                mahavishnu_host=mahavishnu_host,
                mahavishnu_port=mahavishnu_port,
                pool_host=pool_host,
                pool_port=pool_port,
                akosha_host=akosha_host,
                akosha_port=akosha_port,
            )
        )

    app()
