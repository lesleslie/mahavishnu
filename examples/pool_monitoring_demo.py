"""Pool monitoring demo for Mahavishnu WebSocket server.

This example demonstrates real-time pool and worker monitoring using WebSocket
connections. Shows how to:
- Connect to Mahavishnu WebSocket server
- Subscribe to pool-specific channels
- Monitor worker lifecycle events
- Track pool scaling and status changes
- Handle task assignments and completions

Usage:
    # Run the demo
    python examples/pool_monitoring_demo.py

    # Or use as a module
    python -m examples.pool_monitoring_demo
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


class PoolMonitorClient:
    """WebSocket client for monitoring pool and worker activity in real-time.

    This client provides a high-level interface for subscribing to pool
    events and receiving updates as workers are created, tasks are assigned,
    and pools scale up or down.

    Features:
    - Automatic connection management with reconnection
    - Event handler decorators for clean event handling
    - Multi-pool monitoring support
    - Query pool status on demand
    - Emoji-formatted console output
    - Worker lifecycle tracking
    - Task execution monitoring

    Example:
        >>> monitor = PoolMonitorClient("ws://localhost:8690")
        >>> await monitor.connect()
        >>>
        >>> @monitor.on("pool.spawned")
        >>> async def handle_pool_spawned(data):
        ...     print(f"Pool spawned: {data['pool_id']}")
        >>>
        >>> await monitor.subscribe_to_pool("pool_abc123")
        >>> await monitor.listen()
    """

    def __init__(
        self,
        uri: str = "ws://127.0.0.1:8690",
        auto_reconnect: bool = True,
        max_reconnect_attempts: int = 5,
    ):
        """Initialize pool monitor client.

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

        # Track worker states
        self._worker_states: dict[str, dict[str, Any]] = {}

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
            logger.error(
                f"❌ Connection refused - is Mahavishnu WebSocket server "
                f"running at {self.uri}?"
            )
            return False
        except Exception as e:
            logger.error(f"❌ Failed to connect: {e}")
            if self.auto_reconnect and self._reconnect_attempts < self.max_reconnect_attempts:
                self._reconnect_attempts += 1
                wait_time = min(2**self._reconnect_attempts, 30)
                logger.info(
                    f"⏳ Reconnecting in {wait_time}s "
                    f"(attempt {self._reconnect_attempts})..."
                )
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
            event_type: Event type to handle (e.g., "pool.spawned")

        Returns:
            Decorator function

        Example:
            >>> @monitor.on("pool.spawned")
            ... async def handle_spawned(data):
            ...     print(f"Pool spawned: {data['pool_id']}")
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

    async def subscribe_to_pool(self, pool_id: str) -> bool:
        """Subscribe to events for a specific pool.

        Args:
            pool_id: Pool identifier

        Returns:
            True if subscription successful

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        channel = f"pool:{pool_id}"
        return await self._subscribe(channel)

    async def subscribe_to_all_pools(self) -> bool:
        """Subscribe to events for all pools.

        Returns:
            True if subscription successful

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        return await self._subscribe("global")

    async def unsubscribe_from_pool(self, pool_id: str) -> bool:
        """Unsubscribe from a pool channel.

        Args:
            pool_id: Pool identifier

        Returns:
            True if unsubscription successful
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        channel = f"pool:{pool_id}"
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

    async def get_pool_status(self, pool_id: str) -> dict[str, Any]:
        """Query current status of a pool.

        Args:
            pool_id: Pool identifier

        Returns:
            Pool status dictionary with keys:
            - pool_id: str
            - status: str (running, stopped, error)
            - worker_count: int
            - active_workers: int
            - idle_workers: int
            - error_workers: int
            - pool_type: str (mahavishnu, session_buddy, kubernetes)
            - min_workers: int
            - max_workers: int
            - total_tasks_completed: int
            - average_task_duration: float

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        try:
            message = {
                "type": "request",
                "event": "get_pool_status",
                "data": {"pool_id": pool_id},
                "id": f"pool_status_{pool_id}_{asyncio.get_event_loop().time()}",
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
            logger.error(f"❌ Timeout querying pool status")
            return {}
        except Exception as e:
            logger.error(f"❌ Error querying pool status: {e}")
            return {}

    async def get_worker_status(self, worker_id: str) -> dict[str, Any]:
        """Query current status of a worker.

        Args:
            worker_id: Worker identifier

        Returns:
            Worker status dictionary

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        try:
            message = {
                "type": "request",
                "event": "get_worker_status",
                "data": {"worker_id": worker_id},
                "id": f"worker_status_{worker_id}_{asyncio.get_event_loop().time()}",
            }

            await self.websocket.send(json.dumps(message))

            response = await asyncio.wait_for(
                self.websocket.recv(),
                timeout=5.0
            )
            data = json.loads(response)

            if data.get("type") == "response":
                return data.get("data", {})
            else:
                return {}

        except Exception as e:
            logger.error(f"❌ Error querying worker status: {e}")
            return {}

    def get_all_workers(self) -> dict[str, dict[str, Any]]:
        """Get all tracked worker states.

        Returns:
            Dictionary mapping worker_id to worker state
        """
        return self._worker_states.copy()

    # Event listening

    async def listen(self, timeout: float = 60.0) -> None:
        """Listen for pool events.

        Runs until disconnect() is called or connection is lost.

        Args:
            timeout: Timeout for receiving messages (default: 60s)

        Raises:
            ConnectionError: If not connected to server
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        logger.info("🎧 Listening for pool events...")
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
            # Track worker state changes
            if event == "worker.status_changed":
                worker_id = payload.get("worker_id")
                if worker_id:
                    self._worker_states[worker_id] = payload

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

        # Pool lifecycle events
        if event == "pool.spawned":
            pool_id = data.get("pool_id", "unknown")
            pool_type = data.get("config", {}).get("pool_type", "unknown")
            logger.info(f"🏊 [{timestamp}] Pool spawned: {pool_id} ({pool_type})")

        elif event == "pool.scaled":
            pool_id = data.get("pool_id", "unknown")
            worker_count = data.get("worker_count", 0)
            logger.info(f"📈 [{timestamp}] Pool {pool_id} scaled to {worker_count} workers")

        elif event == "pool.status_changed":
            pool_id = data.get("pool_id", "unknown")
            status = data.get("status", {}).get("state", "unknown")
            emoji = {"running": "🟢", "stopped": "🔴", "error": "🔥"}.get(status, "📊")
            logger.info(f"{emoji} [{timestamp}] Pool {pool_id}: {status}")

        elif event == "pool.closed":
            pool_id = data.get("pool_id", "unknown")
            logger.info(f"🚪 [{timestamp}] Pool closed: {pool_id}")

        # Worker events
        elif event == "worker.added":
            pool_id = data.get("pool_id", "unknown")
            worker_id = data.get("worker_id", "unknown")
            logger.info(f"➕ [{timestamp}] Worker added: {worker_id} to {pool_id}")

        elif event == "worker.removed":
            pool_id = data.get("pool_id", "unknown")
            worker_id = data.get("worker_id", "unknown")
            logger.info(f"➖ [{timestamp}] Worker removed: {worker_id} from {pool_id}")

        elif event == "worker.status_changed":
            worker_id = data.get("worker_id", "unknown")
            status = data.get("status", "unknown")
            emoji = {
                "idle": "💤",
                "busy": "⚙️",
                "error": "🔥",
                "initializing": "🔄",
                "stopping": "🛑"
            }.get(status, "📊")
            logger.info(f"{emoji} [{timestamp}] Worker {worker_id}: {status}")

        # Task events
        elif event == "task.assigned":
            pool_id = data.get("pool_id", "unknown")
            worker_id = data.get("worker_id", "unknown")
            task = data.get("task", {})
            task_id = task.get("task_id", "unknown")
            logger.info(f"📋 [{timestamp}] Task {task_id} assigned to {worker_id}")

        elif event == "task.completed":
            pool_id = data.get("pool_id", "unknown")
            worker_id = data.get("worker_id", "unknown")
            result = data.get("result", {})
            success = result.get("success", False)
            emoji = "✅" if success else "❌"
            logger.info(f"{emoji} [{timestamp}] Task completed by {worker_id}")

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

async def demo_basic_pool_monitoring():
    """Demo: Basic pool monitoring with event handlers."""
    print("\n" + "="*70)
    print("🎯 Demo: Basic Pool Monitoring")
    print("="*70 + "\n")

    monitor = PoolMonitorClient()

    try:
        # Connect to server
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Register event handlers
        @monitor.on("pool.spawned")
        async def on_pool_spawned(data: dict):
            pool_id = data.get("pool_id", "unknown")
            config = data.get("config", {})
            pool_type = config.get("pool_type", "unknown")
            logger.info(f"🏊 New pool '{pool_id}' created (type: {pool_type})")

        @monitor.on("pool.scaled")
        async def on_pool_scaled(data: dict):
            pool_id = data.get("pool_id", "unknown")
            worker_count = data.get("worker_count", 0)
            logger.info(f"📈 Pool '{pool_id}' scaled to {worker_count} workers")

        @monitor.on("worker.added")
        async def on_worker_added(data: dict):
            worker_id = data.get("worker_id", "unknown")
            pool_id = data.get("pool_id", "unknown")
            logger.info(f"➕ Worker '{worker_id}' added to pool '{pool_id}'")

        @monitor.on("worker.status_changed")
        async def on_worker_status(data: dict):
            worker_id = data.get("worker_id", "unknown")
            status = data.get("status", "unknown")
            logger.debug(f"🔄 Worker '{worker_id}' status: {status}")

        @monitor.on("task.assigned")
        async def on_task_assigned(data: dict):
            worker_id = data.get("worker_id", "unknown")
            task = data.get("task", {})
            task_type = task.get("task_type", "unknown")
            logger.info(f"📋 Task '{task_type}' assigned to worker '{worker_id}'")

        @monitor.on("task.completed")
        async def on_task_completed(data: dict):
            worker_id = data.get("worker_id", "unknown")
            result = data.get("result", {})
            success = result.get("success", False)
            status = "✅ SUCCESS" if success else "❌ FAILED"
            logger.info(f"{status} - Task completed by worker '{worker_id}'")

        # Subscribe to example pool
        pool_id = "pool_local"
        await monitor.subscribe_to_pool(pool_id)
        logger.info(f"✅ Subscribed to pool: {pool_id}")

        # Listen for events
        logger.info("\n🎧 Listening for events (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=120)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_multi_pool_monitoring():
    """Demo: Monitor multiple pools simultaneously."""
    print("\n" + "="*70)
    print("🎯 Demo: Multi-Pool Monitoring")
    print("="*70 + "\n")

    monitor = PoolMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Subscribe to all pools
        await monitor.subscribe_to_all_pools()
        logger.info("✅ Subscribed to all pools")

        # Track pool statistics
        pool_stats = {}

        @monitor.on("pool.spawned")
        async def on_pool_spawned(data: dict):
            pool_id = data.get("pool_id", "unknown")
            pool_stats[pool_id] = {
                "spawned_at": datetime.now(UTC),
                "workers_added": 0,
                "tasks_completed": 0,
            }
            logger.info(f"🏊 Pool '{pool_id}' added to monitoring")

        @monitor.on("worker.added")
        async def on_worker_added(data: dict):
            pool_id = data.get("pool_id", "unknown")
            if pool_id in pool_stats:
                pool_stats[pool_id]["workers_added"] += 1

        @monitor.on("task.completed")
        async def on_task_completed(data: dict):
            pool_id = data.get("pool_id", "unknown")
            if pool_id in pool_stats:
                pool_stats[pool_id]["tasks_completed"] += 1

        # Print statistics every 30 seconds
        async def print_stats():
            while True:
                await asyncio.sleep(30)
                if pool_stats:
                    print("\n" + "="*70)
                    print("📊 Pool Statistics")
                    print("="*70)
                    for pool_id, stats in pool_stats.items():
                        print(f"\nPool: {pool_id}")
                        print(f"  Workers Added:    {stats['workers_added']}")
                        print(f"  Tasks Completed:  {stats['tasks_completed']}")
                    print("="*70 + "\n")

        # Start stats printer
        stats_task = asyncio.create_task(print_stats())

        logger.info("\n🎧 Monitoring all pools (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=180)

        # Cancel stats task
        stats_task.cancel()

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_query_pool_status():
    """Demo: Query pool and worker status on demand."""
    print("\n" + "="*70)
    print("🎯 Demo: Query Pool Status")
    print("="*70 + "\n")

    monitor = PoolMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Query pool status
        pool_id = "pool_local"

        logger.info(f"📊 Querying status for pool: {pool_id}")
        status = await monitor.get_pool_status(pool_id)

        if status:
            print("\n" + "-"*70)
            print("Pool Status:")
            print("-"*70)
            print(f"  ID:              {status.get('pool_id', 'N/A')}")
            print(f"  Status:          {status.get('status', 'N/A')}")
            print(f"  Type:            {status.get('pool_type', 'N/A')}")
            print(f"  Workers:         {status.get('worker_count', 0)}")
            print(f"    Active:        {status.get('active_workers', 0)}")
            print(f"    Idle:          {status.get('idle_workers', 0)}")
            print(f"    Error:         {status.get('error_workers', 0)}")
            print(f"  Range:           {status.get('min_workers', 0)} - "
                  f"{status.get('max_workers', 0)} workers")
            print(f"  Tasks Completed: {status.get('total_tasks_completed', 0)}")
            print(f"  Avg Duration:    {status.get('average_task_duration', 0):.2f}s")
            print("-"*70 + "\n")

            # Show individual worker status
            if status.get('workers'):
                print("Worker Details:")
                print("-"*70)
                for worker in status['workers']:
                    worker_id = worker.get('worker_id', 'N/A')
                    worker_status = worker.get('status', 'N/A')
                    tasks_completed = worker.get('tasks_completed', 0)
                    print(f"  {worker_id}:")
                    print(f"    Status:     {worker_status}")
                    print(f"    Completed:  {tasks_completed} tasks")
                print("-"*70 + "\n")
        else:
            logger.warning("⚠️  No status data received")

    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_worker_lifecycle_tracking():
    """Demo: Track worker lifecycle in detail."""
    print("\n" + "="*70)
    print("🎯 Demo: Worker Lifecycle Tracking")
    print("="*70 + "\n")

    monitor = PoolMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Subscribe to all pools
        await monitor.subscribe_to_all_pools()
        logger.info("✅ Subscribed to all pools")

        # Comprehensive worker tracking
        @monitor.on("worker.added")
        async def on_worker_added(data: dict):
            worker_id = data.get("worker_id", "unknown")
            pool_id = data.get("pool_id", "unknown")
            print(f"\n➕ WORKER ADDED")
            print(f"   Worker: {worker_id}")
            print(f"   Pool:   {pool_id}")
            print(f"   Time:   {datetime.now(UTC).strftime('%H:%M:%S')}")

        @monitor.on("worker.status_changed")
        async def on_worker_status(data: dict):
            worker_id = data.get("worker_id", "unknown")
            status = data.get("status", "unknown")
            prev_status = data.get("previous_status", "unknown")

            emoji = {
                "idle": "💤",
                "busy": "⚙️",
                "error": "🔥",
                "initializing": "🔄",
            }.get(status, "📊")

            print(f"{emoji} Worker {worker_id}: {prev_status} → {status}")

        @monitor.on("worker.removed")
        async def on_worker_removed(data: dict):
            worker_id = data.get("worker_id", "unknown")
            pool_id = data.get("pool_id", "unknown")
            print(f"\n➖ WORKER REMOVED")
            print(f"   Worker: {worker_id}")
            print(f"   Pool:   {pool_id}")

        @monitor.on("task.assigned")
        async def on_task_assigned(data: dict):
            worker_id = data.get("worker_id", "unknown")
            task = data.get("task", {})
            task_type = task.get("task_type", "unknown")
            priority = task.get("priority", "normal")
            print(f"📋 Task '{task_type}' (priority: {priority}) → {worker_id}")

        @monitor.on("task.completed")
        async def on_task_completed(data: dict):
            worker_id = data.get("worker_id", "unknown")
            result = data.get("result", {})
            success = result.get("success", False)
            duration = result.get("duration_seconds", 0)

            status = "✅" if success else "❌"
            print(f"{status} Task completed by {worker_id} ({duration:.2f}s)")

            if not success:
                error = result.get("error", "Unknown error")
                print(f"   Error: {error}")

        logger.info("\n🎧 Tracking worker lifecycle (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=180)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")
    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


async def demo_pool_scaling_events():
    """Demo: Monitor pool scaling events."""
    print("\n" + "="*70)
    print("🎯 Demo: Pool Scaling Events")
    print("="*70 + "\n")

    monitor = PoolMonitorClient()

    try:
        if not await monitor.connect():
            logger.error("❌ Failed to connect, exiting demo")
            return

        # Subscribe to all pools
        await monitor.subscribe_to_all_pools()
        logger.info("✅ Subscribed to all pools")

        # Track scaling events
        scaling_history = []

        @monitor.on("pool.spawned")
        async def on_pool_spawned(data: dict):
            pool_id = data.get("pool_id", "unknown")
            config = data.get("config", {})
            min_workers = config.get("min_workers", 0)
            max_workers = config.get("max_workers", 0)

            scaling_history.append({
                "event": "spawned",
                "pool_id": pool_id,
                "timestamp": datetime.now(UTC),
            })

            print(f"\n🏊 POOL SPAWNED")
            print(f"   Pool:      {pool_id}")
            print(f"   Range:     {min_workers} - {max_workers} workers")
            print(f"   Type:      {config.get('pool_type', 'unknown')}")

        @monitor.on("pool.scaled")
        async def on_pool_scaled(data: dict):
            pool_id = data.get("pool_id", "unknown")
            worker_count = data.get("worker_count", 0)

            scaling_history.append({
                "event": "scaled",
                "pool_id": pool_id,
                "worker_count": worker_count,
                "timestamp": datetime.now(UTC),
            })

            print(f"\n📈 POOL SCALED")
            print(f"   Pool:         {pool_id}")
            print(f"   Worker Count: {worker_count}")
            print(f"   Time:         {datetime.now(UTC).strftime('%H:%M:%S')}")

        @monitor.on("pool.status_changed")
        async def on_pool_status(data: dict):
            pool_id = data.get("pool_id", "unknown")
            status = data.get("status", {})
            state = status.get("state", "unknown")

            print(f"\n🔄 POOL STATUS CHANGED")
            print(f"   Pool:   {pool_id}")
            print(f"   Status: {state}")

        @monitor.on("pool.closed")
        async def on_pool_closed(data: dict):
            pool_id = data.get("pool_id", "unknown")

            scaling_history.append({
                "event": "closed",
                "pool_id": pool_id,
                "timestamp": datetime.now(UTC),
            })

            print(f"\n🚪 POOL CLOSED")
            print(f"   Pool: {pool_id}")

        logger.info("\n🎧 Monitoring pool scaling events (Ctrl+C to stop)...\n")
        await monitor.listen(timeout=180)

    except KeyboardInterrupt:
        logger.info("\n🛑 Demo stopped by user")

        # Print scaling summary
        if scaling_history:
            print("\n" + "="*70)
            print("📊 Scaling History Summary")
            print("="*70)
            for event in scaling_history:
                ts = event["timestamp"].strftime("%H:%M:%S")
                print(f"  [{ts}] {event['event'].upper()}: {event['pool_id']}")
            print("="*70 + "\n")

    except Exception as e:
        logger.error(f"❌ Demo error: {e}")
    finally:
        await monitor.disconnect()


# Main entry point

async def main():
    """Run pool monitoring demo."""
    import sys

    demos = {
        "basic": demo_basic_pool_monitoring,
        "multi": demo_multi_pool_monitoring,
        "query": demo_query_pool_status,
        "lifecycle": demo_worker_lifecycle_tracking,
        "scaling": demo_pool_scaling_events,
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
        await demo_basic_pool_monitoring()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Goodbye!")
