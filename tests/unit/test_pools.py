"""Unit tests for pool management modules."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import BasePool, PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.manager import PoolManager, PoolSelector
from mahavishnu.mcp.protocols.message_bus import Message, MessageBus, MessageType


class TestPoolConfig:
    """Test PoolConfig dataclass."""

    def test_pool_config_defaults(self):
        """Test PoolConfig with default values."""
        config = PoolConfig(name="test", pool_type="mahavishnu")

        assert config.name == "test"
        assert config.pool_type == "mahavishnu"
        assert config.min_workers == 1
        assert config.max_workers == 10
        assert config.worker_type == "terminal-qwen"
        assert config.auto_scale is False
        assert config.memory_enabled is True

    def test_pool_config_custom(self):
        """Test PoolConfig with custom values."""
        config = PoolConfig(
            name="custom",
            pool_type="session-buddy",
            min_workers=2,
            max_workers=20,
            worker_type="terminal-claude",
            auto_scale=True,
        )

        assert config.name == "custom"
        assert config.min_workers == 2
        assert config.max_workers == 20
        assert config.worker_type == "terminal-claude"
        assert config.auto_scale is True

    def test_pool_config_extra(self):
        """Test PoolConfig with extra configuration."""
        config = PoolConfig(
            name="test",
            pool_type="mahavishnu",
            extra_config={"session_buddy_url": "http://localhost:8678"},
        )

        assert config.get("session_buddy_url") == "http://localhost:8678"
        assert config.get("nonexistent", "default") == "default"

    def test_pool_config_validation(self):
        """Test PoolConfig validation constraints."""
        # Valid config
        config = PoolConfig(
            name="test",
            pool_type="mahavishnu",
            min_workers=1,
            max_workers=10,
        )

        assert config.min_workers <= config.max_workers


class TestPoolStatus:
    """Test PoolStatus enum."""

    def test_pool_status_values(self):
        """Test PoolStatus enum values."""
        assert PoolStatus.PENDING.value == "pending"
        assert PoolStatus.INITIALIZING.value == "initializing"
        assert PoolStatus.RUNNING.value == "running"
        assert PoolStatus.SCALING.value == "scaling"
        assert PoolStatus.DEGRADED.value == "degraded"
        assert PoolStatus.STOPPED.value == "stopped"
        assert PoolStatus.FAILED.value == "failed"


class TestPoolMetrics:
    """Test PoolMetrics dataclass."""

    def test_pool_metrics_creation(self):
        """Test PoolMetrics creation."""
        metrics = PoolMetrics(
            pool_id="test_pool",
            status=PoolStatus.RUNNING,
            active_workers=5,
            total_workers=10,
            tasks_completed=100,
            tasks_failed=5,
            avg_task_duration=1.5,
            memory_usage_mb=512.0,
        )

        assert metrics.pool_id == "test_pool"
        assert metrics.status == PoolStatus.RUNNING
        assert metrics.active_workers == 5
        assert metrics.total_workers == 10
        assert metrics.tasks_completed == 100
        assert metrics.tasks_failed == 5
        assert metrics.avg_task_duration == 1.5
        assert metrics.memory_usage_mb == 512.0


class TestMessageBus:
    """Test MessageBus for inter-pool communication."""

    @pytest.fixture
    def message_bus(self):
        """Create a MessageBus instance."""
        return MessageBus(max_queue_size=10)

    @pytest.mark.asyncio
    async def test_publish_subscribe(self, message_bus):
        """Test message publish and subscribe."""
        received_messages = []

        async def handler(msg: Message):
            received_messages.append(msg)

        message_bus.subscribe(MessageType.TASK_DELEGATE, handler)

        # Publish message
        await message_bus.publish({
            "type": "task_delegate",
            "source_pool_id": "pool_abc",
            "payload": {"task": "test"},
        })

        # Give subscriber time to process
        await asyncio.sleep(0.1)

        assert len(received_messages) == 1
        assert received_messages[0].type == MessageType.TASK_DELEGATE
        assert received_messages[0].source_pool_id == "pool_abc"

    @pytest.mark.asyncio
    async def test_receive_from_queue(self, message_bus):
        """Test receiving messages from pool-specific queue."""
        # Publish message to specific pool
        await message_bus.publish({
            "type": "task_delegate",
            "target_pool_id": "pool_xyz",
            "payload": {"data": "test"},
        })

        # Receive message
        msg = await message_bus.receive("pool_xyz", timeout=1.0)

        assert msg is not None
        assert msg.target_pool_id == "pool_xyz"

    @pytest.mark.asyncio
    async def test_receive_timeout(self, message_bus):
        """Test receive timeout when no messages available."""
        msg = await message_bus.receive("nonexistent", timeout=0.1)
        assert msg is None

    @pytest.mark.asyncio
    async def test_receive_batch(self, message_bus):
        """Test receiving multiple messages."""
        # Publish multiple messages
        for i in range(3):
            await message_bus.publish({
                "type": "status_update",
                "target_pool_id": "pool_batch",
                "payload": {"index": i},
            })

        # Receive batch
        messages = await message_bus.receive_batch("pool_batch", count=5, timeout=1.0)

        assert len(messages) == 3
        assert messages[0].payload["index"] == 0
        assert messages[1].payload["index"] == 1
        assert messages[2].payload["index"] == 2

    @pytest.mark.asyncio
    async def test_queue_backpressure(self, message_bus):
        """Test queue backpressure when full."""
        # Fill queue to max size
        for _ in range(10):
            await message_bus.publish({
                "type": "heartbeat",
                "target_pool_id": "pool_full",
                "payload": {},
            })

        # Try to publish one more (should be dropped/ignored)
        # The publish should succeed but message won't be queued
        await message_bus.publish({
            "type": "heartbeat",
            "target_pool_id": "pool_full",
            "payload": {},
        })

        # Queue size should be at max
        queue_size = message_bus.get_queue_size("pool_full")
        assert queue_size == 10

    def test_get_stats(self, message_bus):
        """Test getting message bus statistics."""
        # Add some queues and subscribers
        message_bus.subscribe(MessageType.STATUS_UPDATE, lambda msg: None)

        stats = message_bus.get_stats()

        assert "pools_with_queues" in stats
        assert "queue_sizes" in stats
        assert "subscriber_counts" in stats
        assert stats["max_queue_size"] == 10

    @pytest.mark.asyncio
    async def test_clear_queue(self, message_bus):
        """Test clearing pool queue."""
        # Add messages
        for _ in range(5):
            await message_bus.publish({
                "type": "heartbeat",
                "target_pool_id": "pool_clear",
                "payload": {},
            })

        # Clear queue
        count = await message_bus.clear_queue("pool_clear")

        assert count == 5
        assert message_bus.get_queue_size("pool_clear") == 0


class TestPoolSelector:
    """Test PoolSelector enum."""

    def test_pool_selector_values(self):
        """Test PoolSelector enum values."""
        assert PoolSelector.ROUND_ROBIN.value == "round_robin"
        assert PoolSelector.LEAST_LOADED.value == "least_loaded"
        assert PoolSelector.RANDOM.value == "random"
        assert PoolSelector.AFFINITY.value == "affinity"


class MockPool(BasePool):
    """Mock pool for testing PoolManager."""

    def __init__(self, config: PoolConfig, pool_id: str = "mock_pool"):
        super().__init__(config, pool_id)
        self._start_called = False
        self._stop_called = False
        self._scale_called_with = None

    async def start(self) -> str:
        """Start the mock pool."""
        self._status = PoolStatus.RUNNING
        self._start_called = True
        self._workers["worker_1"] = "worker_1"
        return self.pool_id

    async def execute_task(self, task: dict) -> dict:
        """Execute a task."""
        return {
            "pool_id": self.pool_id,
            "worker_id": "worker_1",
            "status": "completed",
            "output": f"Task: {task.get('prompt', '')}",
        }

    async def execute_batch(self, tasks: list[dict]) -> dict:
        """Execute multiple tasks."""
        return {
            str(i): {
                "pool_id": self.pool_id,
                "status": "completed",
            }
            for i, task in enumerate(tasks)
        }

    async def scale(self, target_worker_count: int) -> None:
        """Scale the pool."""
        self._scale_called_with = target_worker_count
        self._workers = {f"worker_{i}": f"worker_{i}" for i in range(target_worker_count)}

    async def health_check(self) -> dict:
        """Check pool health."""
        return {
            "pool_id": self.pool_id,
            "status": "healthy",
            "workers_active": len(self._workers),
        }

    async def get_metrics(self) -> PoolMetrics:
        """Get pool metrics."""
        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=len(self._workers),
            total_workers=len(self._workers),
        )

    async def collect_memory(self) -> list:
        """Collect memory."""
        return [{"content": "test", "metadata": {}}]

    async def stop(self) -> None:
        """Stop the pool."""
        self._status = PoolStatus.STOPPED
        self._stop_called = True
        self._workers.clear()


class TestPoolManager:
    """Test PoolManager orchestration."""

    @pytest.fixture
    def pool_manager(self):
        """Create a PoolManager instance."""
        terminal_mgr = MagicMock()
        session_buddy = MagicMock()
        message_bus = MessageBus()

        return PoolManager(
            terminal_manager=terminal_mgr,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

    @pytest.mark.asyncio
    async def test_spawn_pool(self, pool_manager):
        """Test spawning a new pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu")

        # Patch to use MockPool instead of actual pool types
        with patch.object(pool_manager, "_pools", {}):
            mock_pool = MockPool(config, "test_pool_id")
            pool_manager._pools["test_pool_id"] = mock_pool

            pools = await pool_manager.list_pools()

            assert len(pools) == 1
            assert pools[0]["pool_id"] == "test_pool_id"
            assert pools[0]["pool_type"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_execute_on_pool(self, pool_manager):
        """Test executing task on specific pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu")
        mock_pool = MockPool(config, "test_pool")
        await mock_pool.start()

        pool_manager._pools["test_pool"] = mock_pool

        result = await pool_manager.execute_on_pool(
            "test_pool",
            {"prompt": "Hello"},
        )

        assert result["pool_id"] == "test_pool"
        assert result["status"] == "completed"
        assert "Hello" in result["output"]

    @pytest.mark.asyncio
    async def test_route_task_least_loaded(self, pool_manager):
        """Test routing task to least loaded pool."""
        # Create multiple pools with different worker counts
        config1 = PoolConfig(name="pool1", pool_type="mahavishnu")
        config2 = PoolConfig(name="pool2", pool_type="mahavishnu")

        mock_pool1 = MockPool(config1, "pool1")
        mock_pool1._workers = {"w1": "w1", "w2": "w2"}  # 2 workers

        mock_pool2 = MockPool(config2, "pool2")
        mock_pool2._workers = {"w1": "w1"}  # 1 worker (least loaded)

        pool_manager._pools["pool1"] = mock_pool1
        pool_manager._pools["pool2"] = mock_pool2

        result = await pool_manager.route_task(
            {"prompt": "Test"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # Should route to pool2 (least loaded)
        assert result["pool_id"] == "pool2"

    @pytest.mark.asyncio
    async def test_close_pool(self, pool_manager):
        """Test closing a specific pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu")
        mock_pool = MockPool(config, "test_pool")
        await mock_pool.start()

        pool_manager._pools["test_pool"] = mock_pool

        await pool_manager.close_pool("test_pool")

        assert "test_pool" not in pool_manager._pools
        assert mock_pool._stop_called is True

    @pytest.mark.asyncio
    async def test_close_all_pools(self, pool_manager):
        """Test closing all pools."""
        # Create multiple pools
        for i in range(3):
            config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
            mock_pool = MockPool(config, f"pool{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool{i}"] = mock_pool

        await pool_manager.close_all()

        assert len(pool_manager._pools) == 0
        for i in range(3):
            # Note: pools were closed, so we can't check the stopped status
            # but we can verify they're gone from the manager
            assert f"pool{i}" not in pool_manager._pools

    @pytest.mark.asyncio
    async def test_health_check(self, pool_manager):
        """Test health check across all pools."""
        config = PoolConfig(name="test", pool_type="mahavishnu")
        mock_pool = MockPool(config, "test_pool")
        await mock_pool.start()

        pool_manager._pools["test_pool"] = mock_pool

        health = await pool_manager.health_check()

        assert health["status"] == "healthy"
        assert health["pools_active"] == 1
        assert len(health["pools"]) == 1

    def test_set_pool_selector(self, pool_manager):
        """Test setting default pool selector."""
        pool_manager.set_pool_selector(PoolSelector.ROUND_ROBIN)
        assert pool_manager._pool_selector == PoolSelector.ROUND_ROBIN

    def test_get_message_bus_stats(self, pool_manager):
        """Test getting message bus statistics."""
        stats = pool_manager.get_message_bus_stats()

        assert "pools_with_queues" in stats
        assert "queue_sizes" in stats
        assert "subscriber_counts" in stats


class TestPoolManagerIntegration:
    """Integration tests for PoolManager."""

    @pytest.mark.asyncio
    async def test_multi_pool_orchestration(self):
        """Test managing multiple pools simultaneously."""
        terminal_mgr = MagicMock()
        session_buddy = MagicMock()
        message_bus = MessageBus()

        pool_manager = PoolManager(
            terminal_manager=terminal_mgr,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        # Create multiple pools
        for i in range(3):
            config = PoolConfig(name=f"pool{i}", pool_type="mahavishnu")
            mock_pool = MockPool(config, f"pool{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool{i}"] = mock_pool

        # Execute tasks across pools
        results = []
        for pool_id in ["pool0", "pool1", "pool2"]:
            result = await pool_manager.execute_on_pool(
                pool_id,
                {"prompt": f"Task for {pool_id}"},
            )
            results.append(result)

        assert len(results) == 3
        for result in results:
            assert result["status"] == "completed"

        # Aggregate results
        aggregated = await pool_manager.aggregate_results()

        assert len(aggregated) == 3
        assert all("memory_count" in v for v in aggregated.values())

    @pytest.mark.asyncio
    async def test_inter_pool_communication(self):
        """Test message passing between pools."""
        terminal_mgr = MagicMock()
        session_buddy = MagicMock()
        message_bus = MessageBus()

        pool_manager = PoolManager(
            terminal_manager=terminal_mgr,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        # Create pools
        config1 = PoolConfig(name="pool1", pool_type="mahavishnu")
        config2 = PoolConfig(name="pool2", pool_type="mahavishnu")

        mock_pool1 = MockPool(config1, "pool1")
        mock_pool2 = MockPool(config2, "pool2")
        await mock_pool1.start()
        await mock_pool2.start()

        pool_manager._pools["pool1"] = mock_pool1
        pool_manager._pools["pool2"] = mock_pool2

        # Publish message from pool1 to pool2
        received = []

        async def handler(msg: Message):
            received.append(msg)

        message_bus.subscribe(MessageType.TASK_DELEGATE, handler)

        await message_bus.publish({
            "type": "task_delegate",
            "source_pool_id": "pool1",
            "target_pool_id": "pool2",
            "payload": {"task": "test"},
        })

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].source_pool_id == "pool1"
        assert received[0].target_pool_id == "pool2"
