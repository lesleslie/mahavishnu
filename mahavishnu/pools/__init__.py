"""Pool management for Mahavishnu.

This package provides a multi-pool orchestration system that enables:
- Direct pool management by Mahavishnu (wrapping WorkerManager)
- Session-Buddy pool delegation (each SB instance manages 3 workers)
- RunPod pool support (cloud GPU worker deployment)
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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-check-only imports. Runtime stays lazy via the _LAZY_IMPORTERS
    # table below — these imports let the type-checker see the real classes
    # so each lazy helper and __getattr__ can declare a precise return type.
    from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus
    from .gpu_handler_pool import GpuHandlerPool
    from .manager import PoolManager, PoolSelector
    from .memory_aggregator import MemoryAggregator
    from .runpod_pool import RunPodPool
    from .websocket import WebSocketBroadcaster, create_broadcaster

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
def _lazy_base_pool() -> type[BasePool]:
    from .base import BasePool

    return BasePool


def _lazy_pool_config() -> type[PoolConfig]:
    from .base import PoolConfig

    return PoolConfig


def _lazy_pool_metrics() -> type[PoolMetrics]:
    from .base import PoolMetrics

    return PoolMetrics


def _lazy_pool_status() -> type[PoolStatus]:
    from .base import PoolStatus

    return PoolStatus


def _lazy_pool_manager() -> type[PoolManager]:
    from .manager import PoolManager

    return PoolManager


def _lazy_pool_selector() -> type[PoolSelector]:
    from .manager import PoolSelector

    return PoolSelector


def _lazy_memory_aggregator() -> type[MemoryAggregator]:
    from .memory_aggregator import MemoryAggregator

    return MemoryAggregator


def _lazy_gpu_handler_pool() -> type[GpuHandlerPool]:
    from .gpu_handler_pool import GpuHandlerPool

    return GpuHandlerPool


def _lazy_runpod_pool() -> type[RunPodPool]:
    from .runpod_pool import RunPodPool

    return RunPodPool


def _lazy_websocket_broadcaster() -> type[WebSocketBroadcaster]:
    from .websocket import WebSocketBroadcaster

    return WebSocketBroadcaster


def _lazy_create_broadcaster() -> create_broadcaster:  # type: ignore[valid-type]
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


def __getattr__(name: str) -> Any:
    """Lazy import to avoid heavy initialization on package import."""
    if importer := _LAZY_IMPORTERS.get(name):
        return importer()  # type: ignore[operator]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
