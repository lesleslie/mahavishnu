"""Example workflows demonstrating in-process oneiric adapter resolution in Mahavishnu.

These examples show how to programmatically use the oneiric ``Resolver``
to discover, register, and resolve adapter candidates from within a
Mahavishnu workflow — without any external service roundtrip.

The resolver lives in the oneiric core package (``oneiric.core.resolution``)
and is the canonical in-process substrate for adapter selection. Each
example demonstrates one resolver capability:

    1. List active adapter candidates for a domain.
    2. Resolve with a preferred provider and graceful degradation.
    3. Inspect shadowed candidates (those displaced by higher priority).
    5. Wire resolver discovery into a workflow (select + log).
    6. Discover across multiple categories concurrently.

The health-check and circuit-breaker demonstrations are intentionally
omitted here — the resolver itself does not implement those concerns;
they live in the ``mahavishnu.adapters.*`` modules that own each
adapter type. See ``examples/routing_monitoring_example.py`` for
monitoring / alerting demos.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from oneiric.core.resolution import Candidate, Resolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared demo fixtures — register a small set of storage candidates so every
# example has something to list / resolve. In real code, candidates come
# from auto-discovery via oneiric adapters; here we hand-build a few for
# determinism and to keep the example self-contained (no external deps).
# ---------------------------------------------------------------------------

def _build_demo_resolver() -> Resolver:
    """Construct a Resolver pre-populated with three storage candidates."""
    resolver = Resolver()

    s3 = Candidate(
        domain="adapter",
        key="storage",
        provider="s3",
        factory="mahavishnu.adapters.storage.s3:S3Adapter",
        priority=10,
        metadata={"region": "us-east-1", "capabilities": ["read", "write", "object"]},
    )
    sqlite = Candidate(
        domain="adapter",
        key="storage",
        provider="sqlite",
        factory="mahavishnu.adapters.storage.sqlite:SQLiteAdapter",
        priority=5,
        metadata={"path": "/tmp/mahavishnu-demo.sqlite", "capabilities": ["read", "write"]},
    )
    in_mem = Candidate(
        domain="adapter",
        key="storage",
        provider="in_memory",
        factory="mahavishnu.adapters.storage.in_memory:InMemoryAdapter",
        priority=1,
        metadata={"capabilities": ["read", "write"]},
    )
    resolver.register(s3)
    resolver.register(sqlite)
    resolver.register(in_mem)

    # Also register one in each non-storage domain so the parallel-discovery
    # example has something to find.
    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory="mahavishnu.adapters.cache.redis:RedisAdapter",
            priority=10,
            metadata={"capabilities": ["read", "write", "ttl"]},
        )
    )
    resolver.register(
        Candidate(
            domain="adapter",
            key="orchestration",
            provider="prefect",
            factory="mahavishnu.adapters.orchestration.prefect:PrefectAdapter",
            priority=10,
            metadata={"capabilities": ["workflow", "scheduling"]},
        )
    )

    return resolver


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------

@dataclass
class DemoRunResult:
    """Per-example return value so each step can be inspected separately."""
    name: str
    candidates: list[Candidate] = field(default_factory=list)
    selected: Candidate | None = None


async def example_1_list_storage_adapters() -> DemoRunResult:
    """List all active storage adapter candidates for the storage domain."""
    logger.info("Example 1: Listing storage adapters")
    resolver = _build_demo_resolver()
    all_active = resolver.list_active("adapter")
    storage = [c for c in all_active if c.key == "storage"]
    logger.info(f"Found {len(storage)} storage adapters:")
    for c in storage:
        logger.info(f"  - {c.provider}/{c.key}  factory={c.factory}")
        logger.info(f"    priority={c.priority}  metadata={c.metadata}")
    return DemoRunResult(name="list", candidates=storage)


async def example_2_resolve_with_fallback() -> DemoRunResult:
    """Resolve a storage candidate, preferring S3, falling back to SQLite."""
    logger.info("Example 2: Resolving storage adapter (prefer S3 → SQLite)")
    resolver = _build_demo_resolver()

    selected = resolver.resolve("adapter", key="storage", provider="s3")
    if selected is None:
        logger.warning("S3 adapter not registered, falling back to SQLite")
        selected = resolver.resolve("adapter", key="storage", provider="sqlite")
    if selected is None:
        logger.error("No storage adapter available")
        return DemoRunResult(name="resolve_fallback")

    logger.info(f"Selected: {selected.provider}/{selected.key}  factory={selected.factory}")
    return DemoRunResult(name="resolve_fallback", selected=selected)


async def example_3_shadowed_candidates() -> DemoRunResult:
    """Show candidates that were registered but displaced by higher-priority ones."""
    logger.info("Example 3: Inspect shadowed candidates (displaced by higher priority)")
    resolver = _build_demo_resolver()
    # Resolve once so the registry promotes the highest-priority candidate
    # and shadows the others.
    winner = resolver.resolve("adapter", key="storage")

    active = [c for c in resolver.list_active("adapter") if c.key == "storage"]
    shadowed = [c for c in resolver.list_shadowed("adapter") if c.key == "storage"]

    logger.info(f"Winner (active):   {winner.provider}  (priority={winner.priority})")
    logger.info(f"Shadowed candidates: {len(shadowed)}")
    for c in shadowed:
        logger.info(f"  - {c.provider} (priority={c.priority})  factory={c.factory_path if hasattr(c, 'factory_path') else c.factory}")

    return DemoRunResult(name="shadowed", candidates=active, selected=winner)


async def example_5_workflow_integration() -> DemoRunResult:
    """Wire resolver discovery into a workflow: discover → select → log."""
    logger.info("Example 5: Workflow integration (discover → select → log)")
    resolver = _build_demo_resolver()

    storage = [c for c in resolver.list_active("adapter") if c.key == "storage"]
    if not storage:
        logger.error("No storage adapters available")
        return DemoRunResult(name="workflow")

    # Prefer S3, fallback to first available
    selected = next((c for c in storage if c.provider == "s3"), storage[0])
    logger.info(f"Selected: {selected.provider}/{selected.key}")
    logger.info(f"Factory:  {selected.factory}")
    logger.info(f"Priority: {selected.priority}")
    logger.info(f"Metadata: {selected.metadata}")
    logger.info("Workflow executed successfully (demo)")
    return DemoRunResult(name="workflow", candidates=storage, selected=selected)


async def example_6_parallel_discovery() -> list[DemoRunResult]:
    """Discover across multiple categories concurrently."""
    logger.info("Example 6: Parallel discovery (storage, cache, orchestration)")
    resolver = _build_demo_resolver()

    categories = ["storage", "cache", "orchestration"]
    # list_active is synchronous; use asyncio.to_thread to demonstrate the
    # async parallel-discovery pattern even when underlying calls are cheap.
    results = await asyncio.gather(*(
        asyncio.to_thread(resolver.list_active, "adapter") for _ in categories
    ))

    summary: list[DemoRunResult] = []
    for category, adapters in zip(categories, results, strict=True):
        matches = [c for c in adapters if c.key == category]
        logger.info(f"  {category}: {len(matches)} candidate(s)")
        for c in matches:
            logger.info(f"    - {c.provider}  factory={c.factory}")
        summary.append(DemoRunResult(name=f"parallel_{category}", candidates=matches))
    return summary


async def main() -> None:
    logger.info("=" * 60)
    logger.info("In-process oneiric adapter resolution examples")
    logger.info("=" * 60)

    steps = [
        ("List storage adapters", example_1_list_storage_adapters),
        ("Resolve with fallback", example_2_resolve_with_fallback),
        ("Shadowed candidates", example_3_shadowed_candidates),
        ("Workflow integration", example_5_workflow_integration),
        ("Parallel discovery", example_6_parallel_discovery),
    ]

    failures = 0
    for name, func in steps:
        logger.info("")
        logger.info("-" * 60)
        logger.info(f"Running: {name}")
        logger.info("-" * 60)
        try:
            result = await func()
            logger.info(f"✓ {name} completed")
        except Exception as e:  # each example is wrapped so one failure doesn't halt the sweep
            failures += 1
            logger.error(f"✗ {name} failed: {e}")

    logger.info("")
    logger.info("=" * 60)
    if failures:
        logger.info(f"Examples completed with {failures} failure(s)")
    else:
        logger.info("All examples completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())