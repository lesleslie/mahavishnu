"""WebSocket client examples for Mahavishnu.

This module provides example clients for connecting to and interacting
with the Mahavishnu WebSocket server.
"""

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MahavishnuWebSocketClient:
    """WebSocket client for Mahavishnu orchestration updates.

    Example:
        >>> client = MahavishnuWebSocketClient("ws://127.0.0.1:8690")
        >>> await client.connect()
        >>> await client.subscribe_to_workflow("wf_abc123")
        >>> # Receive updates...
        >>> await client.disconnect()
    """

    def __init__(self, uri: str = "ws://127.0.0.1:8690"):
        """Initialize WebSocket client.

        Args:
            uri: WebSocket server URI
        """
        self.uri = uri
        self.websocket = None
        self.connected = False

    async def connect(self) -> None:
        """Connect to the WebSocket server."""
        try:
            logger.info(f"Connecting to {self.uri}...")
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            logger.info("Connected successfully")

            # Receive welcome message
            welcome = await self.websocket.recv()
            data = json.loads(welcome)
            logger.info(f"Server message: {data.get('message', 'Welcome')}")

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info("Disconnected")

    async def subscribe_to_channel(self, channel: str) -> None:
        """Subscribe to a specific channel.

        Args:
            channel: Channel name (e.g., "workflow:abc123", "pool:local", "global")
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        message = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": channel},
            "id": f"sub_{channel}",
        }

        await self.websocket.send(json.dumps(message))
        logger.info(f"Subscribed to channel: {channel}")

        # Wait for confirmation
        response = await self.websocket.recv()
        data = json.loads(response)
        if data.get("status") == "subscribed":
            logger.info(f"Subscription confirmed: {channel}")
        else:
            logger.warning(f"Subscription failed: {data}")

    async def unsubscribe_from_channel(self, channel: str) -> None:
        """Unsubscribe from a channel.

        Args:
            channel: Channel name
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        message = {
            "type": "request",
            "event": "unsubscribe",
            "data": {"channel": channel},
            "id": f"unsub_{channel}",
        }

        await self.websocket.send(json.dumps(message))
        logger.info(f"Unsubscribed from channel: {channel}")

    async def get_workflow_status(self, workflow_id: str) -> dict:
        """Get workflow status from server.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow status dictionary
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        message = {
            "type": "request",
            "event": "get_workflow_status",
            "data": {"workflow_id": workflow_id},
            "id": f"get_status_{workflow_id}",
        }

        await self.websocket.send(json.dumps(message))

        # Wait for response
        response = await self.websocket.recv()
        data = json.loads(response)

        if data.get("type") == "response":
            return data.get("data", {})
        else:
            logger.error(f"Error getting workflow status: {data}")
            return {}

    async def listen_to_events(self, callback=None, timeout: float = 60.0) -> None:
        """Listen for WebSocket events.

        Args:
            callback: Optional async callback function for handling events
            timeout: Timeout in seconds (default: 60)
        """
        if not self.connected:
            raise ConnectionError("Not connected to WebSocket server")

        logger.info("Listening for events...")

        try:
            while self.connected:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=timeout,
                    )
                    data = json.loads(message)

                    logger.info(f"Received event: {data.get('type', 'unknown')}")

                    if callback:
                        await callback(data)

                except asyncio.TimeoutError:
                    logger.debug("No events received within timeout")
                    continue
                except ConnectionClosed:
                    logger.info("Server closed connection")
                    self.connected = False
                    break

        except Exception as e:
            logger.error(f"Error listening to events: {e}")
            self.connected = False


# Example usage functions

async def example_workflow_monitoring():
    """Example: Monitor workflow execution in real-time."""
    client = MahavishnuWebSocketClient()

    try:
        await client.connect()

        # Subscribe to workflow channel
        workflow_id = "wf_example_123"
        await client.subscribe_to_channel(f"workflow:{workflow_id}")

        # Define event handler
        async def handle_event(data: dict):
            event_type = data.get("event")
            if event_type == "workflow.started":
                logger.info(f"🚀 Workflow started: {data['data']['workflow_id']}")
            elif event_type == "workflow.stage_completed":
                logger.info(
                    f"✓ Stage completed: {data['data']['stage_name']}"
                )
            elif event_type == "workflow.completed":
                logger.info(
                    f"✅ Workflow completed: {data['data']['workflow_id']}"
                )
            elif event_type == "workflow.failed":
                logger.error(
                    f"❌ Workflow failed: {data['data']['error']}"
                )

        # Listen for events
        await client.listen_to_events(callback=handle_event, timeout=120)

    finally:
        await client.disconnect()


async def example_pool_monitoring():
    """Example: Monitor pool status changes."""
    client = MahavishnuWebSocketClient()

    try:
        await client.connect()

        # Subscribe to pool channel
        pool_id = "pool_local"
        await client.subscribe_to_channel(f"pool:{pool_id}")

        # Define event handler
        async def handle_pool_event(data: dict):
            event_type = data.get("event")
            if event_type == "worker.status_changed":
                worker_data = data["data"]
                logger.info(
                    f"Worker {worker_data['worker_id']} status: "
                    f"{worker_data['status']}"
                )
            elif event_type == "pool.status_changed":
                pool_data = data["data"]
                logger.info(
                    f"Pool {pool_data['pool_id']} status updated"
                )

        await client.listen_to_events(callback=handle_pool_event, timeout=120)

    finally:
        await client.disconnect()


async def example_multi_channel():
    """Example: Subscribe to multiple channels."""
    client = MahavishnuWebSocketClient()

    try:
        await client.connect()

        # Subscribe to multiple channels
        await client.subscribe_to_channel("global")
        await client.subscribe_to_channel("pool:local")

        # Listen for events from all channels
        await client.listen_to_events(timeout=120)

    finally:
        await client.disconnect()


async def example_query_status():
    """Example: Query workflow status on demand."""
    client = MahavishnuWebSocketClient()

    try:
        await client.connect()

        # Query workflow status
        status = await client.get_workflow_status("wf_example_123")
        logger.info(f"Workflow status: {status}")

        # Disconnect after query
        await client.disconnect()

    except Exception as e:
        logger.error(f"Error: {e}")
        await client.disconnect()


# Main entry point

async def main():
    """Run example client."""
    import sys

    if len(sys.argv) > 1:
        example = sys.argv[1]

        if example == "workflow":
            await example_workflow_monitoring()
        elif example == "pool":
            await example_pool_monitoring()
        elif example == "multi":
            await example_multi_channel()
        elif example == "query":
            await example_query_status()
        else:
            logger.error(f"Unknown example: {example}")
            logger.info("Available examples: workflow, pool, multi, query")
    else:
        # Default to workflow monitoring
        await example_workflow_monitoring()


if __name__ == "__main__":
    asyncio.run(main())
