"""Example: Integrating Mahavishnu WebSocket server.

This example shows how to integrate the WebSocket server with
the Mahavishnu application for real-time orchestration updates.
"""

import asyncio
from pathlib import Path

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.websocket import MahavishnuWebSocketServer


async def main():
    """Run Mahavishnu with WebSocket server enabled."""

    # Initialize Mahavishnu app
    app = MahavishnuApp(config_path=Path("settings/mahavishnu.yaml"))

    # Start the app (initializes pool manager, etc.)
    await app.start()

    # Create WebSocket server
    websocket_server = MahavishnuWebSocketServer(
        pool_manager=app.pool_manager,
        host="127.0.0.1",
        port=8690,
    )

    # Start WebSocket server
    await websocket_server.start()
    print("WebSocket server started on ws://127.0.0.1:8690")

    # Example: Broadcast workflow event
    await websocket_server.broadcast_workflow_started(
        workflow_id="wf_abc123",
        metadata={
            "prompt": "Write a Python function",
            "adapter": "llamaindex",
        }
    )

    # Example: Broadcast worker status
    await websocket_server.broadcast_worker_status_changed(
        worker_id="worker_001",
        status="busy",
        pool_id="pool_local"
    )

    # Run forever
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        print("\\nShutting down...")
    finally:
        await websocket_server.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
