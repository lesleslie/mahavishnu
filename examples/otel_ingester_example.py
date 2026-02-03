"""Example usage of OTel Ingester.

This example demonstrates how to use the OtelIngester to:
1. Ingest OpenTelemetry trace data
2. Search traces by semantic similarity
3. Retrieve specific traces by ID
"""

import asyncio
from typing import Any

# NOTE: This requires sentence-transformers to be installed:
# pip install sentence-transformers


def sample_trace_data() -> dict[str, Any]:
    """Create sample OTel trace data for demonstration."""
    return {
        "trace_id": "trace-abc-123",
        "spans": [
            {
                "name": "HTTP GET /api/users",
                "start_time": "2024-01-15T10:30:00Z",
                "attributes": {
                    "service.name": "claude",
                    "http.method": "GET",
                    "http.status_code": 200,
                    "http.url": "/api/users",
                },
            },
            {
                "name": "database query: SELECT * FROM users",
                "start_time": "2024-01-15T10:30:01Z",
                "attributes": {
                    "service.name": "claude",
                    "db.system": "postgresql",
                    "db.name": "production",
                    "db.statement": "SELECT * FROM users WHERE active = true",
                },
            },
            {
                "name": "response serialization",
                "start_time": "2024-01-15T10:30:02Z",
                "attributes": {"service.name": "claude", "response.size": 2048},
            },
        ],
    }


async def example_basic_usage():
    """Example 1: Basic usage with explicit initialization."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Usage")
    print("=" * 60)

    from mahavishnu.ingesters import OtelIngester

    # Create ingester
    ingester = OtelIngester()
    await ingester.initialize()

    # Ingest a trace
    trace = sample_trace_data()
    await ingester.ingest_trace(trace)
    print(f"✓ Ingested trace: {trace['trace_id']}")

    # Search traces
    results = await ingester.search_traces("database query", limit=5)
    print(f"\n✓ Search results for 'database query': {len(results)} found")
    for result in results:
        print(f"  - {result['conversation_id']}: {result['content'][:60]}...")
        print(f"    Similarity: {result['similarity']:.2f}")

    # Get specific trace
    retrieved = await ingester.get_trace_by_id("trace-abc-123")
    if retrieved:
        print(f"\n✓ Retrieved trace: {retrieved['conversation_id']}")
        print(f"  Content: {retrieved['content']}")

    # Cleanup
    await ingester.close()
    print("\n✓ Ingester closed")


async def example_context_manager():
    """Example 2: Using context manager for automatic cleanup."""
    print("\n" + "=" * 60)
    print("Example 2: Context Manager")
    print("=" * 60)

    from mahavishnu.ingesters import OtelIngester

    # Context manager automatically handles initialization and cleanup
    async with OtelIngester() as ingester:
        # Ingest multiple traces
        traces = [sample_trace_data()]

        # Modify trace IDs for uniqueness
        for i, trace in enumerate(traces):
            trace["trace_id"] = f"trace-{i}"

        result = await ingester.ingest_batch(traces)
        print(
            f"✓ Batch ingestion: {result['success_count']} success, {result['error_count']} errors"
        )

        # Search with system filter
        results = await ingester.search_traces("API calls", system_id="claude", limit=10)
        print(f"\n✓ System-filtered search: {len(results)} results")


async def example_factory_function():
    """Example 3: Using factory function with custom configuration."""
    print("\n" + "=" * 60)
    print("Example 3: Factory Function")
    print("=" * 60)

    from mahavishnu.ingesters import create_otel_ingester

    # Create ingester with custom configuration
    ingester = await create_otel_ingester(
        hot_store_path=":memory:",  # In-memory database
        embedding_model="all-MiniLM-L6-v2",
        cache_size=2000,  # Larger cache
    )

    print("✓ Ingester created with custom configuration")
    print("  - HotStore path: :memory:")
    print("  - Embedding model: all-MiniLM-L6-v2")
    print("  - Cache size: 2000")

    # Use the ingester
    await ingester.ingest_trace(sample_trace_data())

    # Search with low threshold (more results)
    results = await ingester.search_traces(
        "HTTP requests",
        threshold=0.5,  # Lower threshold
        limit=10,
    )
    print(f"\n✓ Search with low threshold (0.5): {len(results)} results")

    await ingester.close()


async def example_error_handling():
    """Example 4: Error handling and validation."""
    print("\n" + "=" * 60)
    print("Example 4: Error Handling")
    print("=" * 60)

    from mahavishnu.core.errors import ValidationError
    from mahavishnu.ingesters import OtelIngester

    async with OtelIngester() as ingester:
        # Try to ingest invalid trace (missing trace_id)
        invalid_trace = {
            "spans": []  # Missing trace_id
        }

        try:
            await ingester.ingest_trace(invalid_trace)
            print("✗ Should have raised ValidationError")
        except ValidationError as e:
            print(f"✓ Caught expected ValidationError: {e.message}")

        # Ingest valid trace
        valid_trace = sample_trace_data()
        await ingester.ingest_trace(valid_trace)
        print("✓ Valid trace ingested successfully")

        # Batch ingestion with some errors
        mixed_batch = [
            sample_trace_data(),  # Valid
            invalid_trace,  # Invalid
            sample_trace_data(),  # Valid
        ]

        # Modify trace IDs for uniqueness
        for i, trace in enumerate(mixed_batch):
            if "trace_id" in trace:
                trace["trace_id"] = f"trace-batch-{i}"

        result = await ingester.ingest_batch(mixed_batch)
        print("\n✓ Batch ingestion with mixed data:")
        print(f"  - Success: {result['success_count']}")
        print(f"  - Errors: {result['error_count']}")


async def example_advanced_search():
    """Example 5: Advanced search techniques."""
    print("\n" + "=" * 60)
    print("Example 5: Advanced Search")
    print("=" * 60)

    from mahavishnu.ingesters import OtelIngester

    async with OtelIngester() as ingester:
        # Ingest sample traces with different content
        traces = [
            {
                "trace_id": "http-trace-1",
                "spans": [
                    {
                        "name": "HTTP POST /api/auth/login",
                        "start_time": "2024-01-15T10:00:00Z",
                        "attributes": {"service.name": "claude"},
                    },
                    {
                        "name": "authentication validation",
                        "start_time": "2024-01-15T10:00:01Z",
                        "attributes": {"service.name": "claude"},
                    },
                ],
            },
            {
                "trace_id": "db-trace-1",
                "spans": [
                    {
                        "name": "database connection pool",
                        "start_time": "2024-01-15T10:05:00Z",
                        "attributes": {"service.name": "qwen"},
                    },
                    {
                        "name": "SQL query execution",
                        "start_time": "2024-01-15T10:05:01Z",
                        "attributes": {"service.name": "qwen"},
                    },
                ],
            },
        ]

        await ingester.ingest_batch(traces)
        print("✓ Ingested sample traces")

        # Search 1: High precision (fewer results, more relevant)
        print("\n1. High precision search (threshold=0.9):")
        results = await ingester.search_traces("authentication", threshold=0.9, limit=10)
        print(f"   Found {len(results)} results")

        # Search 2: High recall (more results, less strict)
        print("\n2. High recall search (threshold=0.5):")
        results = await ingester.search_traces("database", threshold=0.5, limit=10)
        print(f"   Found {len(results)} results")

        # Search 3: System-specific search
        print("\n3. System-specific search (system_id=qwen):")
        results = await ingester.search_traces("query execution", system_id="qwen", limit=10)
        print(f"   Found {len(results)} results")
        for result in results:
            print(f"   - {result['system_id']}: {result['content'][:50]}...")


async def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("OTEL INGESTER USAGE EXAMPLES")
    print("=" * 70)

    try:
        await example_basic_usage()
        await example_context_manager()
        await example_factory_function()
        await example_error_handling()
        await example_advanced_search()

        print("\n" + "=" * 70)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("=" * 70)

    except ImportError as e:
        print(f"\n✗ Missing dependency: {e}")
        print("\nTo run these examples, install required dependencies:")
        print("  pip install sentence-transformers")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
