"""Unit tests for mahavishnu.pools.base module.

Tests PoolConfig, PoolMetrics, PoolStatus enum, and BasePool abstract class.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mahavishnu.core.status import PoolStatus
from mahavishnu.pools.base import BasePool, PoolConfig, PoolMetrics

# =============================================================================
# PoolConfig Tests
# =============================================================================


class TestPoolConfig:
    """Tests for PoolConfig dataclass."""

    def test_pool_config_basic_initialization(self) -> None:
        """Test PoolConfig initialization with required fields."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")

        assert config.name == "test-pool"
        assert config.pool_type == "mahavishnu"

    def test_pool_config_all_optional_fields(self) -> None:
        """Test PoolConfig with all optional fields specified."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=2,
            max_workers=8,
            worker_type="terminal-claude",
            auto_scale=True,
            memory_enabled=False,
            extra_config={"timeout": 30},
        )

        assert config.min_workers == 2
        assert config.max_workers == 8
        assert config.worker_type == "terminal-claude"
        assert config.auto_scale is True
        assert config.memory_enabled is False
        assert config.extra_config == {"timeout": 30}

    def test_pool_config_default_values(self) -> None:
        """Test PoolConfig default values for optional fields."""
        config = PoolConfig(name="test-pool", pool_type="session-buddy")

        assert config.min_workers == 1
        assert config.max_workers == 10
        assert config.worker_type == "terminal-claude"
        assert config.auto_scale is False
        assert config.memory_enabled is True
        assert config.extra_config == {}

    def test_pool_config_get_method_returns_value(self) -> None:
        """Test PoolConfig.get() returns configured value."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            extra_config={"key1": "value1", "key2": 42},
        )

        assert config.get("key1") == "value1"
        assert config.get("key2") == 42

    def test_pool_config_get_method_returns_default_when_missing(self) -> None:
        """Test PoolConfig.get() returns default for missing key."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")

        assert config.get("missing") is None
        assert config.get("missing", "default") == "default"

    @pytest.mark.parametrize(
        "min_workers,max_workers",
        [
            (1, 1),
            (1, 10),
            (5, 5),
            (5, 10),
            (10, 100),
        ],
    )
    def test_pool_config_accepts_valid_min_max(
        self,
        min_workers: int,
        max_workers: int,
    ) -> None:
        """Test PoolConfig accepts valid min_workers <= max_workers."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=min_workers,
            max_workers=max_workers,
        )
        assert config.min_workers == min_workers
        assert config.max_workers == max_workers

    @pytest.mark.parametrize(
        "min_workers,max_workers",
        [
            (5, 3),
            (10, 1),
            (100, 50),
        ],
    )
    def test_pool_config_allows_invalid_min_max(
        self,
        min_workers: int,
        max_workers: int,
    ) -> None:
        """Test PoolConfig currently allows min_workers > max_workers.

        Note: PoolConfig does not currently validate min <= max.
        This behavior may be added in future.
        """
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=min_workers,
            max_workers=max_workers,
        )
        # Currently no validation - values are accepted as-is
        assert config.min_workers == min_workers
        assert config.max_workers == max_workers


# =============================================================================
# PoolStatus Tests
# =============================================================================


class TestPoolStatusValues:
    """Tests for PoolStatus enum values."""

    def test_pool_status_has_expected_values(self) -> None:
        """Test PoolStatus enum has all expected values."""
        expected_values = {
            "pending",
            "initializing",
            "running",
            "scaling",
            "degraded",
            "stopped",
            "failed",
        }

        actual_values = {status.value for status in PoolStatus}

        assert actual_values == expected_values

    def test_pool_status_is_str_enum(self) -> None:
        """Test PoolStatus is a StrEnum with string values."""
        for status in PoolStatus:
            assert isinstance(status, str)
            assert isinstance(status, PoolStatus)


# =============================================================================
# PoolMetrics Tests
# =============================================================================


class TestPoolMetrics:
    """Tests for PoolMetrics dataclass."""

    def test_pool_metrics_required_fields(self) -> None:
        """Test PoolMetrics with only required fields."""
        metrics = PoolMetrics(
            pool_id="pool_123",
            status=PoolStatus.RUNNING,
            active_workers=5,
            total_workers=10,
        )

        assert metrics.pool_id == "pool_123"
        assert metrics.status == PoolStatus.RUNNING
        assert metrics.active_workers == 5
        assert metrics.total_workers == 10
        assert metrics.tasks_completed == 0
        assert metrics.tasks_failed == 0
        assert metrics.avg_task_duration == 0.0
        assert metrics.memory_usage_mb == 0.0

    def test_pool_metrics_all_fields(self) -> None:
        """Test PoolMetrics with all fields specified."""
        metrics = PoolMetrics(
            pool_id="pool_abc",
            status=PoolStatus.SCALING,
            active_workers=3,
            total_workers=5,
            tasks_completed=100,
            tasks_failed=5,
            avg_task_duration=1.5,
            memory_usage_mb=256.0,
        )

        assert metrics.pool_id == "pool_abc"
        assert metrics.status == PoolStatus.SCALING
        assert metrics.active_workers == 3
        assert metrics.total_workers == 5
        assert metrics.tasks_completed == 100
        assert metrics.tasks_failed == 5
        assert metrics.avg_task_duration == 1.5
        assert metrics.memory_usage_mb == 256.0

    def test_pool_metrics_default_values(self) -> None:
        """Test PoolMetrics default values."""
        metrics = PoolMetrics(
            pool_id="pool_xyz",
            status=PoolStatus.PENDING,
            active_workers=0,
            total_workers=0,
        )

        assert metrics.tasks_completed == 0
        assert metrics.tasks_failed == 0
        assert metrics.avg_task_duration == 0.0
        assert metrics.memory_usage_mb == 0.0


# =============================================================================
# BasePool Tests
# =============================================================================


class ConcreteTestPool(BasePool):
    """Concrete implementation of BasePool for testing."""

    async def start(self) -> str:
        return self.pool_id

    async def execute_task(self, task: dict) -> dict:
        return {"status": "completed", "pool_id": self.pool_id}

    async def execute_batch(self, tasks: list[dict]) -> dict:
        return {f"task_{i}": {"status": "completed"} for i, _ in enumerate(tasks)}

    async def scale(self, target_worker_count: int) -> None:
        if target_worker_count < self.config.min_workers:
            raise ValueError("Below minimum")
        if target_worker_count > self.config.max_workers:
            raise ValueError("Above maximum")

    async def health_check(self) -> dict:
        return {"pool_id": self.pool_id, "status": "healthy"}

    async def get_metrics(self) -> PoolMetrics:
        return PoolMetrics(
            pool_id=self.pool_id,
            status=PoolStatus.RUNNING,
            active_workers=1,
            total_workers=1,
        )

    async def collect_memory(self) -> list[dict]:
        return [{"content": "test", "metadata": {"pool_id": self.pool_id}}]

    async def stop(self) -> None:
        pass


class TestBasePool:
    """Tests for BasePool abstract class."""

    def test_base_pool_initialization(self) -> None:
        """Test BasePool initializes with config and generates pool_id."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        assert pool.config == config
        assert pool.pool_id is not None
        assert config.pool_type in pool.pool_id

    def test_base_pool_initialization_with_explicit_pool_id(self) -> None:
        """Test BasePool accepts explicit pool_id."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config, pool_id="my-custom-pool-id")

        assert pool.pool_id == "my-custom-pool-id"

    def test_base_pool_default_status_is_pending(self) -> None:
        """Test BasePool default status is PENDING."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        assert pool._status == PoolStatus.PENDING

    def test_base_pool_status_returns_current_status(self) -> None:
        """Test BasePool.status() returns current status."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        # Access the async status method
        import asyncio

        status = asyncio.run(pool.status())

        assert status == PoolStatus.PENDING

    def test_base_pool_config_property(self) -> None:
        """Test BasePool.config property returns configuration."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        assert pool.config == config
        assert pool.config.name == "test-pool"

    def test_base_pool_pool_id_property(self) -> None:
        """Test BasePool.pool_id property returns pool identifier."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config, pool_id="explicit-id")

        assert pool.pool_id == "explicit-id"

    def test_base_pool_is_abstract(self) -> None:
        """Test BasePool cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            BasePool(PoolConfig(name="test", pool_type="mahavishnu"))

    def test_base_pool_all_abstract_methods_must_be_implemented(self) -> None:
        """Test that all abstract methods must be implemented."""

        @dataclass
        class IncompletePoolConfig:
            name: str
            pool_type: str
            min_workers: int = 1
            max_workers: int = 10

        # Create a mock that doesn't implement all abstract methods
        class IncompletePool(BasePool):
            async def start(self) -> str:
                return "id"

            # Missing: execute_task, execute_batch, scale, health_check,
            #         get_metrics, collect_memory, stop

        config = PoolConfig(name="test", pool_type="mahavishnu")

        # Should fail because abstract methods aren't implemented
        with pytest.raises(TypeError, match="abstract"):
            IncompletePool(config)

    def test_base_pool_concrete_implementation_start(self) -> None:
        """Test BasePool.start() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        result = asyncio.run(pool.start())

        assert result == pool.pool_id

    def test_base_pool_concrete_implementation_execute_task(self) -> None:
        """Test BasePool.execute_task() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        result = asyncio.run(pool.execute_task({"prompt": "test"}))

        assert result["status"] == "completed"
        assert result["pool_id"] == pool.pool_id

    def test_base_pool_concrete_implementation_execute_batch(self) -> None:
        """Test BasePool.execute_batch() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        tasks = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = asyncio.run(pool.execute_batch(tasks))

        assert len(result) == 3
        for i in range(3):
            assert f"task_{i}" in result

    def test_base_pool_concrete_implementation_scale_valid(self) -> None:
        """Test BasePool.scale() with valid target."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=2,
            max_workers=8,
        )
        pool = ConcreteTestPool(config)

        import asyncio

        # Should not raise
        asyncio.run(pool.scale(5))

    def test_base_pool_concrete_implementation_scale_invalid(self) -> None:
        """Test BasePool.scale() with invalid target raises ValueError."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=2,
            max_workers=8,
        )
        pool = ConcreteTestPool(config)

        import asyncio

        with pytest.raises(ValueError):
            asyncio.run(pool.scale(1))  # Below min

        with pytest.raises(ValueError):
            asyncio.run(pool.scale(10))  # Above max

    def test_base_pool_concrete_implementation_health_check(self) -> None:
        """Test BasePool.health_check() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        result = asyncio.run(pool.health_check())

        assert result["pool_id"] == pool.pool_id
        assert result["status"] == "healthy"

    def test_base_pool_concrete_implementation_get_metrics(self) -> None:
        """Test BasePool.get_metrics() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        result = asyncio.run(pool.get_metrics())

        assert result.pool_id == pool.pool_id
        assert result.status == PoolStatus.RUNNING
        assert result.active_workers == 1
        assert result.total_workers == 1

    def test_base_pool_concrete_implementation_collect_memory(self) -> None:
        """Test BasePool.collect_memory() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        result = asyncio.run(pool.collect_memory())

        assert len(result) == 1
        assert result[0]["content"] == "test"
        assert result[0]["metadata"]["pool_id"] == pool.pool_id

    def test_base_pool_concrete_implementation_stop(self) -> None:
        """Test BasePool.stop() works in concrete implementation."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        import asyncio

        # Should not raise
        asyncio.run(pool.stop())


# =============================================================================
# Async Tests
# =============================================================================


@pytest.mark.asyncio
class TestBasePoolAsync:
    """Async tests for BasePool."""

    async def test_pool_status_async(self) -> None:
        """Test pool status method returns correct status."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        status = await pool.status()
        assert status == PoolStatus.PENDING

    async def test_pool_start_async(self) -> None:
        """Test pool start method returns pool_id."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        result = await pool.start()
        assert result == pool.pool_id

    async def test_pool_execute_task_async(self) -> None:
        """Test pool execute_task method returns result."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        result = await pool.execute_task({"prompt": "test"})
        assert result["status"] == "completed"
        assert result["pool_id"] == pool.pool_id

    async def test_pool_execute_batch_async(self) -> None:
        """Test pool execute_batch method returns results."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        tasks = [{"id": 1}, {"id": 2}]
        results = await pool.execute_batch(tasks)

        assert len(results) == 2
        assert all(r["status"] == "completed" for r in results.values())

    async def test_pool_scale_async(self) -> None:
        """Test pool scale method with valid target."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=1,
            max_workers=10,
        )
        pool = ConcreteTestPool(config)

        await pool.scale(5)  # Valid target

    async def test_pool_health_check_async(self) -> None:
        """Test pool health_check method returns health status."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        health = await pool.health_check()

        assert health["pool_id"] == pool.pool_id
        assert "status" in health

    async def test_pool_get_metrics_async(self) -> None:
        """Test pool get_metrics method returns PoolMetrics."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        metrics = await pool.get_metrics()

        assert metrics.pool_id == pool.pool_id
        assert isinstance(metrics, PoolMetrics)

    async def test_pool_collect_memory_async(self) -> None:
        """Test pool collect_memory method returns memory list."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        memories = await pool.collect_memory()

        assert isinstance(memories, list)
        assert len(memories) > 0

    async def test_pool_stop_async(self) -> None:
        """Test pool stop method completes without error."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")
        pool = ConcreteTestPool(config)

        await pool.stop()  # Should not raise
