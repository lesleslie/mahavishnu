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
    "WebSocketBroadcaster",
    "create_broadcaster",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BasePool": (".base", "BasePool"),
    "PoolConfig": (".base", "PoolConfig"),
    "PoolMetrics": (".base", "PoolMetrics"),
    "PoolStatus": (".base", "PoolStatus"),
    "PoolManager": (".manager", "PoolManager"),
    "PoolSelector": (".manager", "PoolSelector"),
    "MemoryAggregator": (".memory_aggregator", "MemoryAggregator"),
    "WebSocketBroadcaster": (".websocket", "WebSocketBroadcaster"),
    "create_broadcaster": (".websocket", "create_broadcaster"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
