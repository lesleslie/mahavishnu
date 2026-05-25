# tests/unit/test_pools_base.py
"""Unit tests for mahavishnu.pools.base module."""

from __future__ import annotations

import pytest

from mahavishnu.core.status import PoolStatus, WorkerStatus
from mahavishnu.pools.base import BasePool, PoolConfig, PoolMetrics


class TestPoolConfig:
    """Unit tests for PoolConfig dataclass."""

    def test_pool_config_creation(self):
        """Test basic PoolConfig creation with required fields."""
        config = PoolConfig(name="test-pool", pool_type="mahavishnu")

        assert config.name == "test-pool"
        assert config.pool_type == "mahavishnu"
        assert config.min_workers == 1
        assert config.max_workers == 10
        assert config.worker_type == "terminal-claude"
        assert config.auto_scale is False
        assert config.memory_enabled is True

    def test_pool_config_custom_workers(self):
        """Test PoolConfig with custom worker settings."""
        config = PoolConfig(
            name="custom-pool",
            pool_type="session-buddy",
            min_workers=3,
            max_workers=20,
        )

        assert config.min_workers == 3
        assert config.max_workers == 20

    def test_pool_config_extra_config(self):
        """Test PoolConfig with extra configuration."""
        config = PoolConfig(
            name="extra-pool",
            pool_type="kubernetes",
            extra_config={"image": "ubuntu:22.04", "cpu_limit": 4},
        )

        assert config.get("image") == "ubuntu:22.04"
        assert config.get("cpu_limit") == 4
        assert config.get("nonexistent") is None
        assert config.get("nonexistent", "default") == "default"

    def test_pool_config_auto_scale(self):
        """Test PoolConfig with auto_scale enabled."""
        config = PoolConfig(
            name="auto-pool",
            pool_type="mahavishnu",
            auto_scale=True,
        )

        assert config.auto_scale is True

    def test_pool_config_memory_disabled(self):
        """Test PoolConfig with memory aggregation disabled."""
        config = PoolConfig(
            name="no-memory-pool",
            pool_type="mahavishnu",
            memory_enabled=False,
        )

        assert config.memory_enabled is False


class TestPoolMetrics:
    """Unit tests for PoolMetrics dataclass."""

    def test_pool_metrics_creation(self):
        """Test basic PoolMetrics creation."""
        metrics = PoolMetrics(
            pool_id="pool-1",
            status=PoolStatus.RUNNING,
            active_workers=5,
            total_workers=10,
        )

        assert metrics.pool_id == "pool-1"
        assert metrics.status == PoolStatus.RUNNING
        assert metrics.active_workers == 5
        assert metrics.total_workers == 10
        assert metrics.tasks_completed == 0
        assert metrics.tasks_failed == 0
        assert metrics.avg_task_duration == 0.0
        assert metrics.memory_usage_mb == 0.0

    def test_pool_metrics_with_stats(self):
        """Test PoolMetrics with task statistics."""
        metrics = PoolMetrics(
            pool_id="pool-2",
            status=PoolStatus.RUNNING,
            active_workers=8,
            total_workers=10,
            tasks_completed=100,
            tasks_failed=2,
            avg_task_duration=1.5,
            memory_usage_mb=512.0,
        )

        assert metrics.pool_id == "pool-2"
        assert metrics.active_workers == 8
        assert metrics.tasks_completed == 100
        assert metrics.tasks_failed == 2
        assert metrics.avg_task_duration == 1.5
        assert metrics.memory_usage_mb == 512.0

    def test_pool_metrics_degraded_status(self):
        """Test PoolMetrics with DEGRADED status."""
        metrics = PoolMetrics(
            pool_id="pool-degraded",
            status=PoolStatus.DEGRADED,
            active_workers=3,
            total_workers=10,
        )

        assert metrics.status == PoolStatus.DEGRADED
        assert metrics.active_workers == 3

    def test_pool_metrics_stopped_status(self):
        """Test PoolMetrics with STOPPED status."""
        metrics = PoolMetrics(
            pool_id="pool-stopped",
            status=PoolStatus.STOPPED,
            active_workers=0,
            total_workers=5,
        )

        assert metrics.status == PoolStatus.STOPPED
        assert metrics.active_workers == 0


class TestBasePool:
    """Unit tests for BasePool abstract class."""

    def test_base_pool_is_abc(self):
        """Test that BasePool is an abstract base class."""
        assert issubclass(BasePool, __import__("abc").ABC)

    def test_base_pool_has_required_abstract_methods(self):
        """Test that BasePool defines required abstract methods."""
        from abc import abstractmethod

        required_methods = [
            "start",
            "stop",
            "scale",
            "execute_task",
            "execute_batch",
            "health_check",
            "get_metrics",
            "collect_memory",
        ]

        for method_name in required_methods:
            method = getattr(BasePool, method_name, None)
            assert method is not None, f"Missing method: {method_name}"
            # Check if it's marked as abstract
            assert getattr(method, "__isabstractmethod__", False), (
                f"Method {method_name} should be abstract"
            )

    def test_base_pool_instantiation_fails(self):
        """Test that BasePool cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            BasePool(config=PoolConfig(name="test", pool_type="mahavishnu"))