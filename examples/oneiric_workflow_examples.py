"""Example workflows demonstrating Oneiric MCP integration in Python.

These examples show how to programmatically use Oneiric MCP adapter discovery
within Mahavishnu workflows and applications.
"""

import asyncio
import logging
from typing import Any

from mahavishnu.core.oneiric_client import (
    OneiricMCPClient,
    OneiricMCPConfig,
    AdapterEntry,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def example_1_list_storage_adapters():
    """Example 1: List all available storage adapters.

    Demonstrates basic adapter discovery with filtering.
    """
    logger.info("Example 1: Listing storage adapters")

    # Configure client (insecure dev mode)
    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,  # Insecure dev port
        use_tls=False,
    )

    client = OneiricMCPClient(config)

    try:
        # List all storage adapters
        adapters = await client.list_adapters(
            domain="adapter",
            category="storage",
            healthy_only=True,  # Only healthy adapters
        )

        logger.info(f"Found {len(adapters)} storage adapters:")
        for adapter in adapters:
            logger.info(f"  - {adapter.adapter_id}")
            logger.info(f"    Provider: {adapter.provider}")
            logger.info(f"    Capabilities: {', '.join(adapter.capabilities)}")
            logger.info(f"    Factory: {adapter.factory_path}")

        return adapters

    finally:
        await client.close()


async def example_2_resolve_with_fallback():
    """Example 2: Resolve adapter with fallback chain.

    Demonstrates fallback strategy when preferred adapter unavailable.
    """
    logger.info("Example 2: Resolving adapter with fallback")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
    )

    client = OneiricMCPClient(config)

    try:
        # Try S3 first (preferred)
        s3_adapter = await client.resolve_adapter(
            domain="adapter",
            category="storage",
            provider="s3",
            healthy_only=True,
        )

        if s3_adapter:
            logger.info(f"Using S3 adapter: {s3_adapter.adapter_id}")
            selected_adapter = s3_adapter
        else:
            # Fallback to SQLite
            logger.warning("S3 adapter not available, trying SQLite")
            sqlite_adapter = await client.resolve_adapter(
                domain="adapter",
                category="storage",
                provider="sqlite",
                healthy_only=True,
            )

            if sqlite_adapter:
                logger.info(f"Using SQLite adapter: {sqlite_adapter.adapter_id}")
                selected_adapter = sqlite_adapter
            else:
                logger.error("No storage adapter available")
                return None

        # Use the selected adapter
        logger.info(f"Selected adapter: {selected_adapter.adapter_id}")
        logger.info(f"Factory path: {selected_adapter.factory_path}")

        return selected_adapter

    finally:
        await client.close()


async def example_3_health_monitoring():
    """Example 3: Monitor adapter health with alerts.

    Demonstrates health checking workflow.
    """
    logger.info("Example 3: Adapter health monitoring")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
    )

    client = OneiricMCPClient(config)

    try:
        # List all adapters
        all_adapters = await client.list_adapters()

        logger.info(f"Checking health for {len(all_adapters)} adapters")

        unhealthy_count = 0

        for adapter in all_adapters:
            # Check health
            is_healthy = await client.check_adapter_health(adapter.adapter_id)

            status_icon = "✓" if is_healthy else "✗"
            logger.info(f"  {status_icon} {adapter.adapter_id}: {adapter.health_status}")

            if not is_healthy:
                unhealthy_count += 1
                logger.warning(f"    Unhealthy adapter detected: {adapter.adapter_id}")

        # Summary
        if unhealthy_count > 0:
            logger.warning(f"Found {unhealthy_count} unhealthy adapters")
        else:
            logger.info("All adapters are healthy")

        return unhealthy_count == 0

    finally:
        await client.close()


async def example_4_cache_management():
    """Example 4: Cache management for performance.

    Demonstrates cache usage and invalidation.
    """
    logger.info("Example 4: Cache management")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
        cache_ttl_sec=300,  # 5 minute cache
    )

    client = OneiricMCPClient(config)

    try:
        # First query (cache miss)
        logger.info("Query 1: Cache miss (fetching from server)")
        adapters1 = await client.list_adapters(category="storage")
        logger.info(f"Found {len(adapters1)} adapters")

        # Second query (cache hit)
        logger.info("Query 2: Cache hit (using cached results)")
        adapters2 = await client.list_adapters(category="storage")
        logger.info(f"Found {len(adapters2)} adapters (from cache)")

        # Invalidate cache
        logger.info("Invalidating cache")
        await client.invalidate_cache()

        # Third query (cache miss again)
        logger.info("Query 3: Cache miss after invalidation")
        adapters3 = await client.list_adapters(category="storage")
        logger.info(f"Found {len(adapters3)} adapters (fresh from server)")

        return adapters1 == adapters2 == adapters3

    finally:
        await client.close()


async def example_5_workflow_integration():
    """Example 5: Integrate adapter discovery into workflow.

    Demonstrates complete workflow with dynamic adapter resolution.
    """
    logger.info("Example 5: Workflow integration")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
    )

    client = OneiricMCPClient(config)

    try:
        # Step 1: Discover available storage adapters
        logger.info("Step 1: Discovering storage adapters")
        storage_adapters = await client.list_adapters(
            domain="adapter",
            category="storage",
            healthy_only=True,
        )

        if not storage_adapters:
            logger.error("No storage adapters available")
            return False

        logger.info(f"Found {len(storage_adapters)} storage adapters")

        # Step 2: Select best adapter for workflow
        logger.info("Step 2: Selecting adapter")

        # Prefer S3, fallback to first available
        selected_adapter = None
        for adapter in storage_adapters:
            if adapter.provider == "s3":
                selected_adapter = adapter
                break

        if not selected_adapter:
            selected_adapter = storage_adapters[0]

        logger.info(f"Selected: {selected_adapter.adapter_id}")

        # Step 3: Verify adapter health before use
        logger.info("Step 3: Verifying adapter health")
        is_healthy = await client.check_adapter_health(selected_adapter.adapter_id)

        if not is_healthy:
            logger.error(f"Selected adapter is unhealthy: {selected_adapter.adapter_id}")
            return False

        logger.info(f"Adapter is healthy: {selected_adapter.adapter_id}")

        # Step 4: Execute workflow with adapter
        logger.info("Step 4: Executing workflow with adapter")
        logger.info(f"  Factory: {selected_adapter.factory_path}")
        logger.info(f"  Capabilities: {selected_adapter.capabilities}")

        # Simulate workflow execution
        logger.info("Workflow executed successfully")

        return True

    finally:
        await client.close()


async def example_6_parallel_discovery():
    """Example 6: Parallel adapter discovery for multiple categories.

    Demonstrates concurrent queries for better performance.
    """
    logger.info("Example 6: Parallel adapter discovery")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
    )

    client = OneiricMCPClient(config)

    try:
        # Query multiple categories in parallel
        categories = ["storage", "cache", "memory", "orchestration"]

        logger.info(f"Discovering adapters for {len(categories)} categories in parallel")

        # Create tasks
        tasks = [
            client.list_adapters(domain="adapter", category=cat)
            for cat in categories
        ]

        # Execute in parallel
        results = await asyncio.gather(*tasks)

        # Report results
        for category, adapters in zip(categories, results):
            logger.info(f"  {category}: {len(adapters)} adapters")

        return dict(zip(categories, results))

    finally:
        await client.close()


async def example_7_circuit_breaker():
    """Example 7: Circuit breaker pattern with failing adapter.

    Demonstrates circuit breaker behavior.
    """
    logger.info("Example 7: Circuit breaker pattern")

    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,
        use_tls=False,
        circuit_breaker_threshold=2,  # Block after 2 failures
        circuit_breaker_duration_sec=10,  # Block for 10 seconds
    )

    client = OneiricMCPClient(config)

    try:
        # Try to check health of non-existent adapter
        fake_adapter_id = "nonexistent.project.adapter.fake"

        logger.info(f"Testing circuit breaker with: {fake_adapter_id}")

        # First failure
        logger.info("Failure 1/2")
        is_healthy = await client.check_adapter_health(fake_adapter_id)
        logger.info(f"  Result: {is_healthy}")

        # Second failure
        logger.info("Failure 2/2")
        is_healthy = await client.check_adapter_health(fake_adapter_id)
        logger.info(f"  Result: {is_healthy}")

        # Third attempt (should be blocked by circuit breaker)
        logger.info("Attempt 3 (should be blocked)")
        is_healthy = await client.check_adapter_health(fake_adapter_id)
        logger.info(f"  Result: {is_healthy}")

        logger.info("Circuit breaker test complete")

        return True

    finally:
        await client.close()


async def main():
    """Run all examples."""
    examples = [
        ("List storage adapters", example_1_list_storage_adapters),
        ("Resolve with fallback", example_2_resolve_with_fallback),
        ("Health monitoring", example_3_health_monitoring),
        ("Cache management", example_4_cache_management),
        ("Workflow integration", example_5_workflow_integration),
        ("Parallel discovery", example_6_parallel_discovery),
        ("Circuit breaker", example_7_circuit_breaker),
    ]

    logger.info("=" * 60)
    logger.info("Oneiric MCP Integration Examples")
    logger.info("=" * 60)

    for name, example_func in examples:
        logger.info("\n" + "-" * 60)
        logger.info(f"Running: {name}")
        logger.info("-" * 60)

        try:
            await example_func()
            logger.info(f"✓ {name} completed")
        except Exception as e:
            logger.error(f"✗ {name} failed: {e}")

    logger.info("\n" + "=" * 60)
    logger.info("All examples completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    # Run examples
    asyncio.run(main())
