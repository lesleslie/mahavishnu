"""Shared helpers for chaos and failure-injection scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mcp_common.websocket import WebSocketProtocol

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from mahavishnu.core.status import PoolStatus
from mahavishnu.core.task_router import AdapterManager, StateManager, TaskRouter
from mahavishnu.pools.base import PoolConfig
from mahavishnu.websocket.server import MahavishnuWebSocketServer


@dataclass
class ChaosAdapter(OrchestratorAdapter):
    """Adapter double that can simulate worker failure and recovery."""

    adapter_type_value: AdapterType
    fail_attempts: int = 0
    failure_message: str = "chaos failure"

    def __post_init__(self) -> None:
        self.attempt_count = 0
        self.initialized = False
        self.cleaned_up = False
        self._capabilities = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
        )

    async def initialize(self) -> None:
        self.initialized = True

    @property
    def adapter_type(self) -> AdapterType:
        return self.adapter_type_value

    @property
    def name(self) -> str:
        return self.adapter_type_value.value

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def execute(self, task: dict[str, Any], repos: list[str] | None = None) -> dict[str, Any]:
        self.attempt_count += 1
        if self.attempt_count <= self.fail_attempts:
            raise RuntimeError(self.failure_message)

        return {
            "success": True,
            "execution_id": f"01{self.adapter_type_value.value.upper()}CHAOS{self.attempt_count:02d}",
            "latency_ms": self.attempt_count,
            "task": task,
            "repos": repos or [],
        }

    async def get_health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self.attempt_count > self.fail_attempts else "degraded",
            "attempts": self.attempt_count,
        }

    async def cleanup(self) -> None:
        self.cleaned_up = True


def build_task_router(
    primary_failures: int = 0,
    secondary_failures: int = 0,
) -> tuple[TaskRouter, ChaosAdapter, ChaosAdapter]:
    """Create a task router with primary and fallback adapters."""
    manager = AdapterManager()
    primary = ChaosAdapter(AdapterType.PREFECT, fail_attempts=primary_failures)
    secondary = ChaosAdapter(AdapterType.AGNO, fail_attempts=secondary_failures)

    manager.adapters[primary.adapter_type] = primary
    manager.adapters[secondary.adapter_type] = secondary

    router = TaskRouter(adapter_registry=manager, state_manager=StateManager())
    return router, primary, secondary


def build_websocket_server() -> MahavishnuWebSocketServer:
    """Create a lightweight websocket server for partition tests."""
    mock_pool_manager = MagicMock()
    mock_pool_manager.pools = {}

    server = MahavishnuWebSocketServer(
        pool_manager=mock_pool_manager,
        host="127.0.0.1",
        port=8690,
    )
    server.is_running = True
    server.metrics = None
    return server


def create_mock_websocket(
    event_recorder: dict[str, list[dict[str, Any]]],
    connection_id: str,
    rooms: list[str],
) -> MagicMock:
    """Create a websocket double that records decoded events by room."""
    mock_ws = MagicMock()

    async def send_mock(message: str) -> None:
        decoded = WebSocketProtocol.decode(message)
        event_dict = {
            "event": decoded.event,
            "data": decoded.data if hasattr(decoded, "data") else {},
            "type": decoded.type,
        }
        for room in rooms:
            event_recorder.setdefault(room, []).append(event_dict)

    mock_ws.send = AsyncMock(side_effect=send_mock)
    mock_ws.id = connection_id
    return mock_ws


def partition_connections(server: MahavishnuWebSocketServer, partitioned_ids: list[str]) -> None:
    """Remove the provided connection IDs from the websocket server."""
    for connection_id in partitioned_ids:
        server.connections.pop(connection_id, None)
        for room_connections in server.connection_rooms.values():
            room_connections.discard(connection_id)


def build_failing_pool_manager(
    pool_id: str,
    memory_items: list[dict[str, Any]],
    pool_type: str = "mahavishnu",
) -> SimpleNamespace:
    """Create a minimal pool manager for memory-aggregation tests."""
    pool = MagicMock()
    pool.pool_id = pool_id
    pool.config = PoolConfig(name=pool_id, pool_type=pool_type)
    pool._workers = {"worker_1": "worker_1"}
    pool.collect_memory = AsyncMock(return_value=memory_items)
    pool.status = AsyncMock(return_value=PoolStatus.RUNNING)

    pool_manager = SimpleNamespace()
    pool_manager._pools = {pool_id: pool}
    pool_manager.list_pools = AsyncMock(
        return_value=[
            {
                "pool_id": pool_id,
                "pool_type": pool_type,
                "name": pool_id,
                "status": PoolStatus.RUNNING.value,
                "workers": 1,
                "min_workers": 1,
                "max_workers": 1,
            }
        ]
    )
    return pool_manager


def build_http_failure_response(
    status_code: int = 500,
    text: str = "service unavailable",
) -> SimpleNamespace:
    """Create a minimal HTTP response object for failure injection."""
    return SimpleNamespace(status_code=status_code, text=text, json=lambda: {})
