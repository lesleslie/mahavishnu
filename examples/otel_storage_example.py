"""
Example usage of Oneiric OTelStorageAdapter for semantic trace search.

This example demonstrates:
1. Setting up the adapter with configuration
2. Storing OpenTelemetry traces with semantic embeddings
3. Performing semantic search queries
4. Retrieving traces by ID
5. Health checks and monitoring
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings


async def example_basic_usage():
    """Basic usage example."""
    print("\n" + "="*60)
    print("Example 1: Basic Usage")
    print("="*60 + "\n")

    # Load Mahavishnu configuration
    settings = MahavishnuSettings()

    # Create OTel storage settings
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
        embedding_model=settings.otel_storage_embedding_model,
        embedding_dimension=settings.otel_storage_embedding_dimension,
        cache_size=settings.otel_storage_cache_size,
        similarity_threshold=settings.otel_storage_similarity_threshold,
    )

    # Initialize adapter
    adapter = OTelStorageAdapter(otel_settings)

    print(f"Adapter initialized with:")
    print(f"  - Connection: {otel_settings.connection_string[:30]}...")
    print(f"  - Model: {otel_settings.embedding_model}")
    print(f"  - Dimensions: {otel_settings.embedding_dimension}")
    print(f"  - Cache size: {otel_settings.cache_size}")
    print(f"  - Similarity threshold: {otel_settings.similarity_threshold}")


async def example_health_check():
    """Health check example."""
    print("\n" + "="*60)
    print("Example 2: Health Check")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Perform health check
    health = await adapter.health_check()

    if health["healthy"]:
        print("Database Status: HEALTHY")
        print(f"  Total traces: {health.get('total_traces', 0)}")
        print(f"  Cache size: {health.get('cache_size', 0)}")
        print(f"  Connection pool: {health.get('pool_size', 'N/A')}")
    else:
        print("Database Status: UNHEALTHY")
        print(f"  Error: {health.get('error', 'Unknown error')}")


async def example_store_traces():
    """Store traces example."""
    print("\n" + "="*60)
    print("Example 3: Store Traces")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
        embedding_model=settings.otel_storage_embedding_model,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Store a sample trace
    trace_id = "example-trace-001"
    span_id = "example-span-001"

    await adapter.store_trace(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        trace_state="",
        name="database.query.execute",
        kind="CLIENT",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        status="OK",
        attributes={
            "db.system": "postgresql",
            "db.name": "otel_traces",
            "db.operation": "SELECT",
            "db.statement": "SELECT * FROM traces LIMIT 10",
        },
        events=[],
        links=[],
        summary="PostgreSQL database query execution with SELECT statement",
    )

    print(f"Stored trace: {trace_id}")
    print(f"  Span: {span_id}")
    print(f"  Name: database.query.execute")
    print(f"  Status: OK")


async def example_semantic_search():
    """Semantic search example."""
    print("\n" + "="*60)
    print("Example 4: Semantic Search")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
        similarity_threshold=0.70,  # Lower threshold for more results
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Perform semantic search
    queries = [
        "database connection timeout",
        "HTTP request failed",
        "authentication error",
        "slow query performance",
    ]

    for query in queries:
        print(f"Query: '{query}'")
        results = await adapter.search_traces(
            query=query,
            limit=3,
        )

        if results:
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result['name']}")
                print(f"     Similarity: {result['similarity']:.3f}")
                print(f"     Summary: {result['summary'][:80]}...")
        else:
            print("  No results found")
        print()


async def example_retrieve_trace():
    """Retrieve trace by ID example."""
    print("\n" + "="*60)
    print("Example 5: Retrieve Trace by ID")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Retrieve specific trace
    trace_id = "example-trace-001"
    trace_data = await adapter.get_trace(trace_id)

    if trace_data:
        print(f"Retrieved trace: {trace_data['trace_id']}")
        print(f"  Name: {trace_data['name']}")
        print(f"  Kind: {trace_data['kind']}")
        print(f"  Status: {trace_data['status']}")
        print(f"  Duration: {trace_data['duration_ms']}ms")
        print(f"  Attributes: {len(trace_data['attributes'])} attributes")
        print(f"  Summary: {trace_data['summary']}")
    else:
        print(f"Trace not found: {trace_id}")


async def example_batch_operations():
    """Batch operations example."""
    print("\n" + "="*60)
    print("Example 6: Batch Operations")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
        batch_size=50,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Create sample traces for batch insert
    traces = []
    for i in range(10):
        traces.append({
            "trace_id": f"batch-trace-{i:03d}",
            "span_id": f"batch-span-{i:03d}",
            "parent_span_id": None,
            "trace_state": "",
            "name": f"batch.operation.{i}",
            "kind": "INTERNAL",
            "start_time": datetime.now(timezone.utc),
            "end_time": datetime.now(timezone.utc),
            "status": "OK",
            "attributes": {
                "batch.index": i,
                "batch.size": 10,
            },
            "events": [],
            "links": [],
            "summary": f"Batch operation number {i} for processing data",
        })

    # Store in batch
    await adapter.batch_store(traces)
    await adapter.flush()  # Force flush

    print(f"Stored {len(traces)} traces in batch")
    print(f"Batch size: {otel_settings.batch_size}")


async def example_search_with_filters():
    """Search with filters example."""
    print("\n" + "="*60)
    print("Example 7: Search with Filters")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Search with filters
    results = await adapter.search_traces(
        query="database operations",
        limit=5,
        filters={
            "kind": "CLIENT",
            "status": "OK",
        },
    )

    print(f"Search results with filters:")
    print(f"  Query: 'database operations'")
    print(f"  Filters: kind=CLIENT, status=OK")
    print(f"  Results: {len(results)} traces")

    for i, result in enumerate(results, 1):
        print(f"    {i}. {result['name']} (similarity: {result['similarity']:.3f})")


async def example_statistics():
    """Statistics example."""
    print("\n" + "="*60)
    print("Example 8: Statistics")
    print("="*60 + "\n")

    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string,
    )

    adapter = OTelStorageAdapter(otel_settings)

    # Get statistics
    stats = await adapter.get_statistics()

    print("Database Statistics:")
    print(f"  Total traces: {stats.get('total_traces', 0)}")
    print(f"  Total spans: {stats.get('total_spans', 0)}")
    print(f"  Unique trace names: {stats.get('unique_names', 0)}")
    print(f"  Average duration: {stats.get('avg_duration_ms', 0):.2f}ms")
    print(f"  Traces by status:")
    for status, count in stats.get('by_status', {}).items():
        print(f"    {status}: {count}")


async def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("Oneiric OTelStorageAdapter Examples")
    print("="*60)

    try:
        # Check if OTel storage is enabled
        settings = MahavishnuSettings()

        if not settings.otel_storage_enabled:
            print("\nWARNING: OTel storage is not enabled!")
            print("Set 'otel_storage.enabled: true' in settings/mahavishnu.yaml")
            print("And ensure PostgreSQL + pgvector are set up.")
            return

        # Run examples
        await example_basic_usage()
        await example_health_check()
        await example_store_traces()
        await example_semantic_search()
        await example_retrieve_trace()
        await example_batch_operations()
        await example_search_with_filters()
        await example_statistics()

        print("\n" + "="*60)
        print("All examples completed successfully!")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\nERROR: {e}")
        print("\nTroubleshooting:")
        print("  1. Ensure PostgreSQL is running")
        print("  2. Verify pgvector extension is installed")
        print("  3. Check database connection string in config")
        print("  4. Run setup script: ./scripts/setup_otel_storage.sh")
        raise


if __name__ == "__main__":
    asyncio.run(main())
