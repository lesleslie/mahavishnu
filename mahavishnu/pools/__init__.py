"""Pool management for Mahavishnu.

This package provides a multi-pool orchestration system that enables:
- Direct pool management by Mahavishnu (wrapping WorkerManager)
- Session-Buddy pool delegation (each SB instance manages 3 workers)
- Kubernetes pool support (K8s-native worker deployment)
- Inter-pool communication (async message passing between pools)
- Unified memory flow (Local pool → Session-Buddy → Akosha)
- Real-time WebSocket broadcasting of pool events

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

__all__ = [
    "BasePool",
    "PoolConfig",
    "PoolMetrics",
    "PoolStatus",
    "PoolManager",
    "PoolSelector",
    "MemoryAggregator",
    "GpuHandlerPool",
    "RunPodPool",
    "WebSocketBroadcaster",
    "create_broadcaster",
]


# Each value is a zero-arg callable that performs a hardcoded local import.
# No dynamic string ever reaches importlib — satisfies CWE-706 / semgrep N802.
def _lazy_base_pool():
    from .base import BasePool

    return BasePool


def _lazy_pool_config():
    from .base import PoolConfig

    return PoolConfig


def _lazy_pool_metrics():
    from .base import PoolMetrics

    return PoolMetrics


def _lazy_pool_status():
    from .base import PoolStatus

    return PoolStatus


def _lazy_pool_manager():
    from .manager import PoolManager

    return PoolManager


def _lazy_pool_selector():
    from .manager import PoolSelector

    return PoolSelector


def _lazy_memory_aggregator():
    from .memory_aggregator import MemoryAggregator

    return MemoryAggregator


def _lazy_gpu_handler_pool():
    from .gpu_handler_pool import GpuHandlerPool

    return GpuHandlerPool


def _lazy_runpod_pool():
    from .runpod_pool import RunPodPool

    return RunPodPool


def _lazy_websocket_broadcaster():
    from .websocket import WebSocketBroadcaster

    return WebSocketBroadcaster


def _lazy_create_broadcaster():
    from .websocket import create_broadcaster

    return create_broadcaster


_LAZY_IMPORTERS: dict[str, object] = {
    "BasePool": _lazy_base_pool,
    "PoolConfig": _lazy_pool_config,
    "PoolMetrics": _lazy_pool_metrics,
    "PoolStatus": _lazy_pool_status,
    "PoolManager": _lazy_pool_manager,
    "PoolSelector": _lazy_pool_selector,
    "MemoryAggregator": _lazy_memory_aggregator,
    "GpuHandlerPool": _lazy_gpu_handler_pool,
    "RunPodPool": _lazy_runpod_pool,
    "WebSocketBroadcaster": _lazy_websocket_broadcaster,
    "create_broadcaster": _lazy_create_broadcaster,
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if importer := _LAZY_IMPORTERS.get(name):
        return importer()  # type: ignore[operator]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
