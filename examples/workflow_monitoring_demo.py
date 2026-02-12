"""Workflow monitoring demo for Mahavishnu WebSocket server.

This example demonstrates real-time workflow monitoring using WebSocket connections.
Shows how to:
- Connect to Mahavishnu WebSocket server
- Subscribe to workflow-specific channels
- Handle workflow lifecycle events
- Monitor workflow progress
- Query workflow status on demand

Usage:
    # Run the demo
    python examples/workflow_monitoring_demo.py

    # Or use as a module
    python -m examples.workflow_monitoring_demo
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class WorkflowMonitorClient:
    """WebSocket client for monitoring workflow execution in real-time.

    This client provides a high-level interface for subscribing to workflow
    events and receiving updates as workflows progress through their stages.

    Features:
    - Automatic connection management with reconnection
    - Event handler decorators for clean event handling
    - Multi-workflow monitoring support
    - Query workflow status on demand
    - Emoji-formatted console output

    Example:
        >>> monitor = WorkflowMonitorClient("ws://localhost:8690")
        >>> await monitor.connect()
        >>>
        >>> @monitor.on("workflow.started")
        >>> async def handle_started(data):
        ...     print(f"Workflow started: {data['workflow_id']}")
        >>>
        >>> await monitor.subscribe_to_workflow("wf_abc123")
        >>> await monitor.listen()
    """

    def __init__(
        self,
        uri: str = "ws://127.0.0.1:8690",
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
    ):
        """Initialize workflow monitor client.

        Args:
            uri: WebSocket server URI (default: ws://127.0.0.1:8690)
            auto_reconnect: Automatically reconnect on connection loss
            max_reconnect_attempts: Maximum reconnection attempts
        """
        self.uri = uri
        self.auto_reconnect = auto_reconnect
        self.max_reconnect_attempts = max_reconnect_attempts

        self.websocket: Any = None
        self.connected = False
        self._event_handlers: dict[str, list[Callable]] = {}
        self._reconnect_attempts = 0
        self._should_stop = False

    # Connection management

    async def connect(self) -> bool:
        """Connect to the WebSocket server.

        Returns:
            True if connection successful, False otherwise

        Raises:
            ConnectionError: If connection fails after retries
        """
        try:
            logger.info(f"🔌 Connecting to {self.uri}...")

            self.websocket = await websockets.connect(
                self.uri,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            )

            self.connected = True
            self._reconnect_attempts = 0

            # Receive and display welcome message
            welcome_msg = await self.websocket.recv()
            welcome_data = json.loads(welcome_msg)

            logger.info(
                f"✅ Connected to Mahavishnu WebSocket server "
                f"v{welcome_data.get('version', 'unknown')}"
            )

            if "capabilities" in welcome_data:
                caps = welcome_data["capabilities"]
                logger.info(f"📋 Server capabilities: {', '.join(caps)}")

            return True

        except ConnectionRefusedError:
            logger.error(f"❌ Connection refused - is Mahavishnu WebSocket server running at {self.uri}?")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to connect: {e}")
            if self.auto_reconnect and self._reconnect_attempts < self.max_reconnect_attempts:
                self._reconnect_attempts += 1
                wait_time = min(2**self._reconnect_attempts, 30)
                logger.info(f"⏳ Reconnecting in {wait_time}s (attempt {self._reconnect_attempts})...")
                await asyncio.sleep(wait_time)
                return await self.connect()
            return False

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        self._should_stop = True

        if self.websocket and not self.websocket.closed:
            try:
                await self.websocket.close()
                logger.info("👋 Disconnected from WebSocket server")
            except Exception as e:
                logger.warning(f"⚠️  Error during disconnect: {e}")

        self.connected = False

    # Event handling with decorators

    def on(self, event_type: str) -> Callable:
        """Decorator to register event handler.

        Args:
            event_type: Event type to handle (e.g., "workflow.started")

        Returns:
            Decorator function

        Example:
            >>> @monitor.on("workflow.started")
            ... async def handle_started(data):
            ...     print(f"Started: {data}")
        """
        def decorator(func: Callable) -> Callable:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(func)
            return func
        return decorator

    async def _handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Execute all handlers for an event type.

        Args:
            event_type: Event type
            data: Event data
        """
        handlers = self._event_handlers.get(event_type, [])

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"❌ Error in event handler for {event_type}: {e}")

    # Channel subscription

    async def subscribe_to_workflow(self, workflow_id: str) -> bool:
        """Subscribe to events for a specific workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if subscription successful

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        channel = f"workflow:{workflow_id}"
        return await self._subscribe(channel)

    async def subscribe_to_global(self) -> bool:
        """Subscribe to global workflow events (all workflows).

        Returns:
            True if subscription successful

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        return await self._subscribe("global")

    async def unsubscribe_from_workflow(self, workflow_id: str) -> bool:
        """Unsubscribe from a workflow channel.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if unsubscription successful
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        channel = f"workflow:{workflow_id}"
        return await self._unsubscribe(channel)

    async def _subscribe(self, channel: str) -> bool:
        """Internal subscription method.

        Args:
            channel: Channel name

        Returns:
            True if successful
        """
        try:
            message = {
                "type": "request",
                "event": "subscribe",
                "data": {"channel": channel},
                "id": f"sub_{channel}_{asyncio.get_event_loop().time()}",
            }

            await self.websocket.send(json.dumps(message))
            logger.info(f"📡 Subscribing to channel: {channel}")

            # Wait for subscription confirmation
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            data = json.loads(response)

            if data.get("status") == "subscribed":
                logger.info(f"✅ Subscription confirmed: {channel}")
                return True
            else:
                logger.warning(f"⚠️  Subscription failed: {data}")
                return False

        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout waiting for subscription confirmation")
            return False
        except Exception as e:
            logger.error(f"❌ Subscription error: {e}")
            return False

    async def _unsubscribe(self, channel: str) -> bool:
        """Internal unsubscription method.

        Args:
            channel: Channel name

        Returns:
            True if successful
        """
        try:
            message = {
                "type": "request",
                "event": "unsubscribe",
                "data": {"channel": channel},
                "id": f"unsub_{channel}_{asyncio.get_event_loop().time()}",
            }

            await self.websocket.send(json.dumps(message))
            logger.info(f"📡 Unsubscribing from channel: {channel}")

            return True

        except Exception as e:
            logger.error(f"❌ Unsubscription error: {e}")
            return False

    # Query methods

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """Query current status of a workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow status dictionary with keys:
            - workflow_id: str
            - status: str (pending, running, completed, failed)
            - current_stage: str | None
            - stages_completed: list[str]
            - stages_remaining: list[str]
            - progress: float (0-100)
            - started_at: str | None
            - completed_at: str | None
            - error: str | None

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        try:
            message = {
                "type": "request",
                "event": "get_workflow_status",
                "data": {"workflow_id": workflow_id},
                "id": f"status_{workflow_id}_{asyncio.get_event_loop().time()}",
            }

            await self.websocket.send(json.dumps(message))

            # Wait for response
            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            data = json.loads(response)

            if data.get("type") == "response":
                return data.get("data", {})
            elif data.get("type") == "error":
                logger.error(f"❌ Error querying status: {data.get('error_message')}")
                return {}
            else:
                logger.warning(f"⚠️  Unexpected response: {data}")
                return {}

        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout querying workflow status")
            return {}
        except Exception as e:
            logger.error(f"❌ Error querying workflow status: {e}")
            return {}

    # Event listening

    async def listen(self, timeout: float = 60.0) -> None:
        """Listen for workflow events.

        Runs until disconnect() is called or connection is lost.

        Args:
            timeout: Timeout for receiving messages (default: 60s)

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        logger.info("🎧 Listening for workflow events...")
        logger.info("Press Ctrl+C to stop")

        try:
            while self.connected and not self._should_stop:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=timeout,
                    )

                    data = json.loads(message)
                    await self._process_message(data)

                except asyncio.TimeoutError:
                    # Send periodic ping
                    if self.connected:
                        await self._send_ping()
                    continue
                except ConnectionClosed:
                    logger.warning("⚠️  Connection closed by server")
                    self.connected = False
                    if self.auto_reconnect:
                        logger.info("🔄 Attempting to reconnect...")
                        if await self.connect():
                            logger.info("✅ Reconnected successfully")
                            continue
                    break
                except Exception as e:
                    logger.error(f"❌ Error receiving message: {e}")
                    break

        except asyncio.CancelledError:
            logger.info("🛑 Listening cancelled")
            self.connected = False

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process incoming WebSocket message.

        Args:
            data: Message data
        """
        msg_type = data.get("type")
        event = data.get("event")
        payload = data.get("data", {})

        if msg_type == "event":
            # Handle event
            await self._handle_event(event, payload)
            await self._log_event(event, payload)

        elif msg_type == "response":
            # Response to request (already handled by request methods)
            pass

        elif msg_type == "error":
            logger.error(f"❌ Server error: {data.get('error_message')}")
            logger.error(f"   Error code: {data.get('error_code')}")

        elif msg_type == "pong":
            logger.debug("💓 Pong received")

        else:
            logger.warning(f"⚠️  Unknown message type: {msg_type}")

    async def _log_event(self, event: str, data: dict[str, Any]) -> None:
        """Log event with emoji formatting.

        Args:
            event: Event type
            data: Event data
        """
        timestamp = datetime.now(UTC).strftime("%H:%M:%S")

        # Workflow lifecycle events
        if event == "workflow.started":
            wf_id = data.get("workflow_id", "unknown")
            logger.info(f"🚀 [{timestamp}] Workflow started: {wf_id}")

        elif event == "workflow.stage_completed":
            wf_id = data.get("workflow_id", "unknown")
            stage = data.get("stage_name", "unknown")
            progress = data.get("progress", 0)
            logger.info(
                f"✅ [{timestamp}] Stage completed: {stage} "
                f"({progress:.0f}%)"
            )

        elif event == "workflow.completed":
            wf_id = data.get("workflow_id", "unknown")
            duration = data.get("duration_seconds", 0)
            logger.info(
                f"🎉 [{timestamp}] Workflow completed: {wf_id} "
                f"in {duration:.1f}s"
            )

        elif event == "workflow.failed":
            wf_id = data.get("workflow_id", "unknown")
            error = data.get("error", "Unknown error")
            logger.error(f"❌ [{timestamp}] Workflow failed: {wf_id}")
            logger.error(f"   Error: {error}")

        # Worker events
        elif event == "worker.status_changed":
            worker = data.get("worker_id", "unknown")
            status = data.get("status", "unknown")
            emoji = {"idle": "💤", "busy": "⚙️", "error": "🔥"}.get(status, "📊")
            logger.info(f"{emoji} [{timestamp}] Worker {worker}: {status}")

        # Pool events
        elif event == "pool.status_changed":
            pool = data.get("pool_id", "unknown")
            logger.info(f"🏊 [{timestamp}] Pool {pool} status changed")

        else:
            # Generic event logging
            logger.info(f"📨 [{timestamp}] Event: {event}")

    async def _send_ping(self) -> None:
        """Send ping to server to keep connection alive."""
        try:
            ping_msg = {
                "type": "ping",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.websocket.send(json.dumps(ping_msg))
        except Exception as e:
            logger.debug(f"Failed to send ping: {e}")


# Demo functions

async def demo_basic_monitoring():
    """Demo: Basic workflow monitoring with event handlers."""
    print("\n" + "="*70)
    print("🎯 Demo: Basic Workflow Monitoring")
    print("="*70 + "\n")

    monitor = WorkflowMonitorClient()

    try:
        # Connect to server
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Register event handlers
        @monitor.on("workflow.started")
        async def on_workflow_started(data: dict):
            wf_id = data.get("workflow_id", "unknown")
            logger.info(f"🚀 Workflow {wf_id} has started!")

        @monitor.on("workflow.stage_completed")
        async def on_stage_completed(data: dict):
            stage = data.get("stage_name", "unknown")
            progress = data.get("progress", 0)
            print(f"   ▶ Stage '{stage}' completed ({progress:.0f}%)")

        @monitor.on("workflow.completed")
        async def on_workflow_completed(data: dict):
            wf_id = data.get("workflow_id", "unknown")
            duration = data.get("duration_seconds", 0)
            logger.info(f"✅ Workflow {wf_id} completed in {duration:.1f}s")

        @monitor.on("workflow.failed")
        async def on_workflow_failed(data: dict):
            wf_id = data.get("workflow_id", "unknown")
            error = data.get("error", "Unknown error")
            logger.error(f"❌ Workflow {wf_id} failed: {error}")

        # Subscribe to example workflow
        workflow_id = "wf_example_123"
        await monitor.subscribe_to_workflow(workflow_id)
        logger.info(f"✅ Subscribed to workflow: {workflow_id}")

        # Listen for events
        logger.info("\n🎧 Listening for events (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=120)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_multi_workflow_monitoring():
    """Demo: Monitor multiple workflows simultaneously."""
    print("\n" + "="*70)
    print("🎯 Demo: Multi-Workflow Monitoring")
    print("="*70 + "\n")

    monitor = WorkflowMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Track multiple workflows
        workflows = ["wf_example_123", "wf_example_456", "wf_example_789"]

        # Subscribe to all workflows
        for wf_id in workflows:
            await monitor.subscribe_to_workflow(wf_id)
            logger.info(f"✅ Subscribed to workflow: {wf_id}")

        # Also subscribe to global events
        await monitor.subscribe_to_global()
        logger.info("✅ Subscribed to global events")

        # Register handlers
        @monitor.on("workflow.started")
        async def on_any_started(data: dict):
            wf_id = data.get("workflow_id", "unknown")
            logger.info(f"🚀 [MULTI] Workflow started: {wf_id}")

        @monitor.on("workflow.completed")
        async def on_any_completed(data: dict):
            wf_id = data.get("workflow_id", "unknown")
            logger.info(f"✅ [MULTI] Workflow completed: {wf_id}")

        logger.info("\n🎧 Monitoring multiple workflows (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=120)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_query_workflow_status():
    """Demo: Query workflow status on demand."""
    print("\n" + "="*70)
    print("🎯 Demo: Query Workflow Status")
    print("="*70 + "\n")

    monitor = WorkflowMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Query workflow status
        workflow_id = "wf_example_123"

        logger.info(f"📊 Querying status for workflow: {workflow_id}")
        status = await monitor.get_workflow_status(workflow_id)

        if status:
            print("\n" + "-"*70)
            print("Workflow Status:")
            print("-"*70)
            print(f"  ID:         {status.get('workflow_id', 'N/A')}")
            print(f"  Status:     {status.get('status', 'N/A')}")
            print(f"  Stage:      {status.get('current_stage', 'N/A')}")
            print(f"  Progress:   {status.get('progress', 0):.1f}%")
            print(f"  Completed:  {status.get('stages_completed', [])}")
            print(f"  Remaining:  {status.get('stages_remaining', [])}")
            print(f"  Started:    {status.get('started_at', 'N/A')}")
            print(f"  Completed:  {status.get('completed_at', 'N/A')}")
            if status.get('error'):
                print(f"  Error:      {status.get('error')}")
            print("-"*70 + "\n")
        else:
            logger.warning("⚠️  No status data received")

    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_all_workflow_events():
    """Demo: Monitor all workflow events with detailed logging."""
    print("\n" + "="*70)
    print("🎯 Demo: All Workflow Events Monitor")
    print("="*70 + "\n")

    monitor = WorkflowMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Subscribe to all workflow events
        await monitor.subscribe_to_global()
        logger.info("✅ Subscribed to global events")

        # Comprehensive event handlers
        @monitor.on("workflow.started")
        async def on_started(data: dict):
            print(f"\n🚀 WORKFLOW STARTED")
            print(f"   ID: {data.get('workflow_id')}")
            print(f"   Stages: {', '.join(data.get('stages', []))}")

        @monitor.on("workflow.stage_started")
        async def on_stage_started(data: dict):
            print(f"\n▶️  STAGE STARTED")
            print(f"   Stage: {data.get('stage_name')}")
            print(f"   Workflow: {data.get('workflow_id')}")

        @monitor.on("workflow.stage_completed")
        async def on_stage_completed(data: dict):
            print(f"\n✅ STAGE COMPLETED")
            print(f"   Stage: {data.get('stage_name')}")
            print(f"   Progress: {data.get('progress', 0):.1f}%")
            print(f"   Duration: {data.get('duration_seconds', 0):.2f}s")

        @monitor.on("workflow.completed")
        async def on_completed(data: dict):
            print(f"\n🎉 WORKFLOW COMPLETED")
            print(f"   ID: {data.get('workflow_id')}")
            print(f"   Duration: {data.get('duration_seconds', 0):.2f}s")
            print(f"   Stages: {len(data.get('stages_completed', []))}")

        @monitor.on("workflow.failed")
        async def on_failed(data: dict):
            print(f"\n❌ WORKFLOW FAILED")
            print(f"   ID: {data.get('workflow_id')}")
            print(f"   Stage: {data.get('failed_stage', 'unknown')}")
            print(f"   Error: {data.get('error', 'Unknown error')}")

        @monitor.on("worker.status_changed")
        async def on_worker_status(data: dict):
            status = data.get('status', 'unknown')
            emoji = {"idle": "💤", "busy": "⚙️", "error": "🔥"}.get(status, "📊")
            print(f"{emoji} Worker {data.get('worker_id')}: {status}")

        logger.info("\n🎧 Monitoring all workflow events (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=180)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


# Main entry point

async def main():
    """Run workflow monitoring demo."""
    import sys

    demos = {
        "basic": demo_basic_monitoring,
        "multi": demo_multi_workflow_monitoring,
        "query": demo_query_workflow_status,
        "all": demo_all_workflow_events,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name in demos:
            await demos[demo_name]()
        else:
            logger.error(f"❌ Unknown demo: {demo_name}")
            logger.info(f"Available demos: {', '.join(demos.keys())}")
    else:
        # Default demo
        await demo_basic_monitoring()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Goodbye!")
