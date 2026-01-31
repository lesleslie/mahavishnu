"""Pool management for Mahavishnu.

This package provides a multi-pool orchestration system that enables:
- Direct pool management by Mahavishnu (wrapping WorkerManager)
- Session-Buddy pool delegation (each SB instance manages 3 workers)
- Kubernetes pool support (K8s-native worker deployment)
- Inter-pool communication (async message passing between pools)
- Unified memory flow (Local pool → Session-Buddy → Akosha)

Example:
    ```python
    from mahavishnu.pools import PoolManager, PoolConfig

    # Create pool manager
    pool_mgr = PoolManager(terminal_manager=tm)

    # Spawn a local pool
    config = PoolConfig(
        name="local-pool",
        pool_type="mahavishnu",
        min_workers=2,
        max_workers=5,
    )
    pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

    # Execute task
    result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Hello"})
    ```
"""

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus
from .manager import PoolManager, PoolSelector
from .memory_aggregator import MemoryAggregator

__all__ = [
    "BasePool",
    "PoolConfig",
    "PoolMetrics",
    "PoolStatus",
    "PoolManager",
    "PoolSelector",
    "MemoryAggregator",
]
