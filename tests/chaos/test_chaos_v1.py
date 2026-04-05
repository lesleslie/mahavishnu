"""Chaos tests for controlled failure-injection scenarios."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mcp_common.websocket import WebSocketProtocol
import pytest

from tests.fixtures.chaos_harness import (
    build_failing_pool_manager,
    build_http_failure_response,
    build_task_router,
    build_websocket_server,
    create_mock_websocket,
    partition_connections,
)

pytestmark = [pytest.mark.integration, pytest.mark.chaos]


@pytest.mark.asyncio
async def test_worker_kill_triggers_adapter_fallback() -> None:
    """A failed primary worker should fall back to the next adapter."""
    router, primary, secondary = build_task_router(primary_failures=1)

    task = {"task_type": "workflow", "prompt": "deploy chaos-safe workflow"}
    result = await router.execute_with_fallback(task, max_retries=1, retry_delay_base=0.0)

    assert result["success"] is True
    assert result["adapter"].value == "agno"
    assert result["fallback_chain"] == [primary.adapter_type, secondary.adapter_type]
    assert result["total_attempts"] == 2
    assert primary.attempt_count == 1
    assert secondary.attempt_count == 1


@pytest.mark.asyncio
async def test_network_partition_keeps_healthy_clients_connected() -> None:
    """Partitioned websocket clients should stop receiving room broadcasts."""
    server = build_websocket_server()
    event_recorder: dict[str, list[dict[str, object]]] = {}

    healthy_clients = []
    partitioned_clients = []
    for index in range(4):
        client = create_mock_websocket(event_recorder, f"conn{index}", ["chaos-room"])
        server.connections[f"conn{index}"] = client
        if index < 2:
            healthy_clients.append(client)
        else:
            partitioned_clients.append(client)

    server.connection_rooms["chaos-room"] = {f"conn{index}" for index in range(4)}

    first_event = WebSocketProtocol.create_event("chaos.partition", {"sequence": 1})
    await server.broadcast_to_room("chaos-room", first_event)

    partition_connections(server, ["conn2", "conn3"])

    second_event = WebSocketProtocol.create_event("chaos.partition", {"sequence": 2})
    await server.broadcast_to_room("chaos-room", second_event)

    for client in healthy_clients:
        assert client.send.call_count == 2
    for client in partitioned_clients:
        assert client.send.call_count == 1

    assert len(event_recorder["chaos-room"]) == 6
    server.connections.clear()
    server.connection_rooms.clear()


@pytest.mark.asyncio
async def test_resource_exhaustion_backs_pressure_into_local_buffer() -> None:
    """A saturated sync path should spill into the bounded local buffer."""
    from mahavishnu.pools.memory_aggregator import MemoryAggregator

    memory_items = [
        {"content": f"payload-{index}", "metadata": {"index": index}}
        for index in range(505)
    ]
    pool_manager = build_failing_pool_manager("pool-chaos", memory_items)

    aggregator = MemoryAggregator(sync_interval=1.0)
    failed_response = build_http_failure_response()
    aggregator._mcp_client.post = AsyncMock(return_value=failed_response)

    try:
        first_result = await aggregator.collect_and_sync(pool_manager)
        first_call_count = aggregator._mcp_client.post.await_count

        assert first_result["memory_items_synced"] == 505
        stats = aggregator.get_circuit_breaker_stats()
        assert stats["session_buddy"]["circuit_open"] is True
        assert stats["local_buffer"]["size"] == 500
        assert stats["local_buffer"]["drops"] == 5

        smaller_pool_manager = build_failing_pool_manager(
            "pool-chaos",
            [{"content": "payload-extra", "metadata": {"index": 999}}],
        )
        second_result = await aggregator.collect_and_sync(smaller_pool_manager)

        assert second_result["memory_items_synced"] == 1
        assert aggregator._mcp_client.post.await_count == first_call_count + 1

        stats = aggregator.get_circuit_breaker_stats()
        assert stats["session_buddy"]["circuit_open"] is True
        assert stats["local_buffer"]["size"] == 500
        assert stats["local_buffer"]["drops"] == 6
    finally:
        await aggregator.stop()
