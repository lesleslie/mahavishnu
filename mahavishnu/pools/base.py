"""Base pool abstraction for all pool types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mahavishnu.core.status import PoolStatus


@dataclass
class PoolConfig:
    """Base configuration for all pool types.

    Attributes:
        name: Human-readable pool name
        pool_type: Type identifier ("mahavishnu", "session-buddy", "kubernetes")
        min_workers: Minimum number of workers (default: 1)
        max_workers: Maximum number of workers (default: 10)
        worker_type: Type of workers to spawn (default: "terminal-qwen")
        auto_scale: Enable automatic scaling (default: False)
        memory_enabled: Enable memory aggregation (default: True)
    """

    name: str
    pool_type: str
    min_workers: int = 1
    max_workers: int = 10
    worker_type: str = "terminal-qwen"
    auto_scale: bool = False
    memory_enabled: bool = True

    # Additional pool-specific configuration
    extra_config: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get extra configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.extra_config.get(key, default)


@dataclass
class PoolMetrics:
    """Real-time pool metrics.

    Attributes:
        pool_id: Unique pool identifier
        status: Current pool status
        active_workers: Number of currently active workers
        total_workers: Total number of workers in pool
        tasks_completed: Total tasks completed by pool
        tasks_failed: Total tasks failed by pool
        avg_task_duration: Average task duration in seconds
        memory_usage_mb: Memory usage in MB
    """

    pool_id: str
    status: PoolStatus
    active_workers: int
    total_workers: int
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_task_duration: float = 0.0
    memory_usage_mb: float = 0.0


class BasePool(ABC):
    """Abstract base class for all pool types.

    All pools must implement:
    - Pool lifecycle (start, stop, scale)
    - Task execution (execute_task, execute_batch)
    - Health monitoring (health_check, get_metrics)
    - Memory aggregation (collect_memory)

    Example:
        ```python
        class MyPool(BasePool):
            async def start(self) -> str:
                # Initialize pool
                return self.pool_id

            async def execute_task(self, task: dict) -> dict:
                # Execute task on pool
                return {"status": "completed", "output": "..."}
        ```
    """

    def __init__(self, config: PoolConfig, pool_id: str | None = None):
        """Initialize pool.

        Args:
            config: Pool configuration
            pool_id: Optional pool ID (auto-generated if not provided)
        """
        self.config = config
        self.pool_id = pool_id or f"{config.pool_type}_{id(self)}"
        self._status = PoolStatus.PENDING
        self._workers: dict[str, Any] = {}

    @abstractmethod
    async def start(self) -> str:
        """Initialize pool and spawn initial workers.

        Returns:
            pool_id: Unique pool identifier
        """
        pass

    @abstractmethod
    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task on pool (auto-selects worker).

        Args:
            task: Task specification with pool-specific parameters
                Common fields: prompt, timeout, command, etc.

        Returns:
            Execution result with keys:
                - pool_id: Pool identifier
                - worker_id: Worker that executed the task
                - status: Execution status ("completed", "failed", "timeout")
                - output: Task output (if successful)
                - error: Error message (if failed)
                - duration: Execution duration in seconds
        """
        pass

    @abstractmethod
    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Execute multiple tasks concurrently.

        Args:
            tasks: List of task specifications

        Returns:
            Dictionary mapping task_id -> execution result
        """
        pass

    @abstractmethod
    async def scale(self, target_worker_count: int) -> None:
        """Scale pool to target worker count.

        Args:
            target_worker_count: Desired number of workers

        Raises:
            ValueError: If target outside [min_workers, max_workers]
            NotImplementedError: If pool doesn't support scaling
        """
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check pool health and worker status.

        Returns:
            Health status dictionary:
                - pool_id: Pool identifier
                - pool_type: Type of pool
                - status: "healthy", "degraded", or "unhealthy"
                - workers_active: Number of active workers
                - worker_health: Detailed worker health info (optional)
        """
        pass

    @abstractmethod
    async def get_metrics(self) -> PoolMetrics:
        """Get real-time pool metrics.

        Returns:
            PoolMetrics with current statistics
        """
        pass

    @abstractmethod
    async def collect_memory(self) -> list[dict[str, Any]]:
        """Collect worker results and pool context.

        Returns:
            List of memory dictionaries for Session-Buddy storage.
            Each memory dict should have:
                - content: Text content to store
                - metadata: Dict with metadata including:
                    - type: "pool_worker_execution"
                    - pool_id: Pool identifier
                    - pool_type: Type of pool
                    - worker_id: Worker identifier
                    - status: Execution status
                    - timestamp: Execution timestamp
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shutdown pool and all workers."""
        pass

    async def status(self) -> PoolStatus:
        """Get current pool status.

        Returns:
            Current PoolStatus
        """
        return self._status
