"""Real-time workflow monitoring demo with progress tracking.

This demo connects to the Mahavishnu WebSocket server and displays
real-time updates for workflow execution, including:
- Workflow started events
- Stage completion progress
- Worker status changes
- Workflow completion/failure

Usage:
    python workflow_monitor.py --workflow-id wf_123
    python workflow_monitor.py --workflow-id wf_123 --host localhost --port 8690
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
from rich.progress import Progress, BarColumn, TaskID, TextColumn, TimeRemainingColumn


class ConnectionStatus(Enum):
    """Connection status indicators."""

    DISCONNECTED = ("disconnected", "[red]●[/red]")
    CONNECTING = ("connecting", "[yellow]●[/yellow]")
    CONNECTED = ("connected", "[green]●[/green]")
    ERROR = ("error", "[red]●[/red]")

    def __init__(self, status: str, indicator: str):
        self.status = status
        self.indicator = indicator


class WorkflowStatus(Enum):
    """Workflow status types."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowMonitor:
    """Real-time workflow monitor with progress tracking.

    Attributes:
        workflow_id: Workflow identifier to monitor
        host: WebSocket server host
        port: WebSocket server port
        max_events: Maximum events to keep in history
    """

    def __init__(
        self,
        workflow_id: str,
        host: str = "127.0.0.1",
        port: int = 8690,
        max_events: int = 100,
    ):
        """Initialize workflow monitor.

        Args:
            workflow_id: Workflow identifier to monitor
            host: WebSocket server host
            port: WebSocket server port
            max_events: Maximum events to keep in history
        """
        self.workflow_id = workflow_id
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

        # Workflow state
        self.workflow_status = WorkflowStatus.PENDING
        self.workflow_metadata: dict[str, Any] = {}
        self.stages: list[dict[str, Any]] = []
        self.completed_stages = 0
        self.total_stages = 0
        self.current_stage = ""
        self.recent_events: list[dict[str, Any]] = []

        # Progress tracking
        self.progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            expand=True,
        )

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
            Layout(name="progress", size=5),
            Layout(name="status", ratio=1),
            Layout(name="stages", ratio=1),
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

        # Workflow status color
        wf_status_color = "yellow"
        if self.workflow_status == WorkflowStatus.COMPLETED:
            wf_status_color = "green"
        elif self.workflow_status == WorkflowStatus.FAILED:
            wf_status_color = "red"

        header_text = Text.assemble(
            ("Workflow Monitor", "bold cyan"),
            f" | Workflow: {self.workflow_id}",
            f" | Status: [{wf_status_color}]{self.workflow_status.value}[/{wf_status_color}]",
            f" | Server: {self.host}:{self.port}",
            f" | Messages: {self.message_count}",
            uptime_text,
            " | ",
            status_text,
        )

        return Panel(header_text, style="on black")

    def _render_progress(self) -> Panel:
        """Render progress panel."""
        if self.total_stages > 0:
            progress_value = self.completed_stages / self.total_stages
        else:
            progress_value = 0.0

        # Create custom progress display
        progress_text = Text.assemble(
            ("Stage Progress: ", "cyan"),
            (f"{self.completed_stages}/{self.total_stages}", "bold yellow"),
            (f" ({progress_value * 100:.1f}%)", "dim"),
        )

        # Add current stage info
        if self.current_stage:
            progress_text.append("\nCurrent: ", "dim")
            progress_text.append(self.current_stage, "green")

        # Create progress bar
        bar_length = 50
        filled = int(bar_length * progress_value)
        bar = "█" * filled + "░" * (bar_length - filled)
        bar_colored = f"[green]{bar[:filled]}[/green][dim]{bar[filled:]}[/dim]"

        progress_text.append("\n")
        progress_text.append(bar_colored)

        return Panel(progress_text, title="Progress", border_style="green")

    def _render_status(self) -> Panel:
        """Render workflow status panel."""
        table = Table(title="Workflow Status", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Workflow ID", self.workflow_id)
        table.add_row("Status", self.workflow_status.value)
        table.add_row("Completed Stages", str(self.completed_stages))
        table.add_row("Total Stages", str(self.total_stages))

        # Add metadata
        if self.workflow_metadata:
            for key, value in self.workflow_metadata.items():
                if key not in ("workflow_id", "timestamp"):
                    table.add_row(key.replace("_", " ").title(), str(value))

        if self.last_event_time:
            elapsed = (datetime.now(UTC) - self.last_event_time).total_seconds()
            table.add_row("Last Event", f"{elapsed:.1f}s ago")

        return Panel(table, title="Workflow Status", border_style="magenta")

    def _render_stages(self) -> Panel:
        """Render stages panel."""
        table = Table(title="Stages", show_header=True, header_style="bold yellow")
        table.add_column("Stage", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("Time", style="dim")

        for stage in self.stages[-10:]:  # Show last 10 stages
            stage_name = stage.get("name", "unknown")
            status = stage.get("status", "unknown")
            timestamp = stage.get("timestamp", "")

            # Parse timestamp
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = "???"

            # Color-code status
            status_color = "yellow"
            if status == "completed":
                status_color = "green"
            elif status == "failed":
                status_color = "red"
            elif status == "running":
                status_color = "blue"

            table.add_row(
                stage_name,
                f"[{status_color}]{status}[/{status_color}]",
                time_str,
            )

        if not self.stages:
            table.add_row("[dim]No stages yet[/dim]", "", "")

        return Panel(table, title="Stage Progress", border_style="yellow")

    def _render_events(self) -> Panel:
        """Render recent events panel."""
        table = Table(title="Recent Events", show_header=True, header_style="bold blue")
        table.add_column("Time", style="dim", width=8)
        table.add_column("Type", style="cyan")
        table.add_column("Details", style="white")

        # Show most recent events first
        for event in reversed(self.recent_events[-8:]):
            timestamp = event.get("timestamp", "")
            if timestamp:
                # Parse ISO timestamp
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
            if "started" in event_type.lower():
                type_color = "green"
            elif "completed" in event_type.lower():
                type_color = "green"
            elif "failed" in event_type.lower():
                type_color = "red"
            elif "error" in event_type.lower():
                type_color = "red"
            elif "stage" in event_type.lower():
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
            (f"Events: {len(self.recent_events)}", "cyan"),
            " | ",
            (f"Stages: {len(self.stages)}", "yellow"),
        )

        return Panel(footer_text, style="on black")

    def _update_layout(self) -> None:
        """Update all layout panels."""
        self.layout["header"].update(self._render_header())
        self.layout["progress"].update(self._render_progress())
        self.layout["status"].update(self._render_status())
        self.layout["stages"].update(self._render_stages())
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

            # Subscribe to workflow channel
            await self._subscribe_to_workflow()

        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.console.print(f"[red]Connection failed: {e}[/red]")
            raise

    async def _subscribe_to_workflow(self) -> None:
        """Subscribe to workflow channel."""
        if not self.websocket:
            return

        message = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": f"workflow:{self.workflow_id}"},
            "id": f"sub_{self.workflow_id}",
        }

        await self.websocket.send(json.dumps(message))
        self.console.print(f"[cyan]Subscribed to workflow: {self.workflow_id}[/cyan]")

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
        if event == "workflow.started":
            self._handle_workflow_started(event_data)
        elif event == "workflow.stage_completed":
            self._handle_stage_completed(event_data)
        elif event == "workflow.completed":
            self._handle_workflow_completed(event_data)
        elif event == "workflow.failed":
            self._handle_workflow_failed(event_data)
        elif event == "worker.status_changed":
            self._handle_worker_status_changed(event_data)
        else:
            self._add_event(event, str(event_data))

    def _handle_workflow_started(self, data: dict[str, Any]) -> None:
        """Handle workflow started event.

        Args:
            data: Event data
        """
        self.workflow_status = WorkflowStatus.RUNNING
        self.workflow_metadata = data.copy()
        self.workflow_metadata.pop("timestamp", None)
        self._add_event("workflow.started", f"Workflow {self.workflow_id} started")

    def _handle_stage_completed(self, data: dict[str, Any]) -> None:
        """Handle stage completed event.

        Args:
            data: Event data
        """
        stage_name = data.get("stage_name", "unknown")
        result = data.get("result", {})

        # Add stage to history
        self.stages.append({
            "name": stage_name,
            "status": "completed",
            "timestamp": datetime.now(UTC).isoformat(),
            **result,
        })

        self.completed_stages += 1
        self.current_stage = stage_name
        self._add_event("stage.completed", f"Stage {stage_name} completed")

    def _handle_workflow_completed(self, data: dict[str, Any]) -> None:
        """Handle workflow completed event.

        Args:
            data: Event data
        """
        self.workflow_status = WorkflowStatus.COMPLETED
        self._add_event("workflow.completed", f"Workflow {self.workflow_id} completed")
        self.console.print("\n[green]✓ Workflow completed successfully![/green]")

    def _handle_workflow_failed(self, data: dict[str, Any]) -> None:
        """Handle workflow failed event.

        Args:
            data: Event data
        """
        self.workflow_status = WorkflowStatus.FAILED
        error = data.get("error", "Unknown error")
        self._add_event("workflow.failed", f"Error: {error}")
        self.console.print(f"\n[red]✗ Workflow failed: {error}[/red]")

    def _handle_worker_status_changed(self, data: dict[str, Any]) -> None:
        """Handle worker status changed event.

        Args:
            data: Event data
        """
        worker_id = data.get("worker_id", "unknown")
        status = data.get("status", "unknown")
        self._add_event("worker.status_changed", f"Worker {worker_id}: {status}")

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
        """Run the workflow monitor."""
        try:
            await self.connect()
            await self.listen()
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
        finally:
            await self.disconnect()


async def main(
    workflow_id: str,
    host: str = "127.0.0.1",
    port: int = 8690,
) -> None:
    """Main entry point.

    Args:
        workflow_id: Workflow identifier to monitor
        host: WebSocket server host
        port: WebSocket server port
    """
    monitor = WorkflowMonitor(workflow_id=workflow_id, host=host, port=port)

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

    app = typer.Typer(help="Real-time workflow monitoring demo")

    @app.command()
    def run(
        workflow_id: str = typer.Argument(..., help="Workflow ID to monitor"),
        host: str = typer.Option("127.0.0.1", "--host", help="WebSocket server host"),
        port: int = typer.Option(8690, "--port", help="WebSocket server port"),
    ):
        """Run workflow monitor.

        Example:
            workflow-monitor run wf_123 --host localhost --port 8690
        """
        asyncio.run(main(workflow_id=workflow_id, host=host, port=port))

    app()
