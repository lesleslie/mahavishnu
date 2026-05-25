"""Phase 1.4: End-to-end pgvector test for OTel ingester.

This script tests:
1. DuckDB backend (sanity baseline)
2. PostgreSQL + pgvector backend (production)

Usage:
    python examples/otel_pgvector_test.py

Environment variables:
    MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql
    MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=postgresql://les:mahavishnu@localhost:5432/mahavishnu
"""

import asyncio
import os
import sys

# Ensure mahavishnu is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def sample_trace(system_id: str, trace_id: str, task_class: str | None = None) -> dict:
    """Create sample OTel trace data."""
    attrs = {
        "service.name": system_id,
        "http.method": "GET",
        "http.status_code": 200,
    }
    if task_class:
        attrs["task.class"] = task_class
    return {
        "trace_id": trace_id,
        "spans": [
            {
                "name": f"span-1-{trace_id}",
                "start_time": "2024-01-15T10:30:00Z",
                "attributes": attrs,
            },
            {
                "name": f"span-2-{trace_id}",
                "start_time": "2024-01-15T10:30:01Z",
                "attributes": {"service.name": system_id, "db.system": "postgresql"},
            },
        ],
    }


async def test_duckdb() -> bool:
    """Test DuckDB backend (baseline sanity check)."""
    print("\n" + "=" * 60)
    print("Test: DuckDB Backend (baseline)")
    print("=" * 60)

    from mahavishnu.ingesters.otel_ingester import create_otel_ingester

    ingester = await create_otel_ingester(
        hot_store_path=":memory:",
        storage_type="duckdb",
    )

    traces = [
        sample_trace("mahavishnu", "dd-trace-1", "CODE_GENERATION"),
        sample_trace("mahavishnu", "dd-trace-2", "REASONING"),
        sample_trace("akosha", "dd-trace-3", "SEARCH"),
    ]

    result = await ingester.ingest_batch(traces)
    print(f"  Ingested: {result['success_count']} success, {result['error_count']} errors")

    # Search
    results = await ingester.search_traces("span", limit=10)
    print(f"  Search: {len(results)} results")

    # Get by ID
    trace = await ingester.get_trace_by_id("dd-trace-1")
    print(f"  Get by ID: {'found' if trace else 'not found'}")

    await ingester.close()
    return result["success_count"] == 3


async def test_pgvector() -> bool:
    """Test PostgreSQL + pgvector backend."""
    print("\n" + "=" * 60)
    print("Test: PostgreSQL + pgvector Backend")
    print("=" * 60)

    pg_url = os.getenv(
        "MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL",
        "postgresql://les:mahavishnu@localhost:5432/mahavishnu",
    )
    storage_type = os.getenv("MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE", "postgresql")

    print(f"  Storage type: {storage_type}")
    print(f"  PG URL: {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")  # hidecreds

    from mahavishnu.ingesters.otel_ingester import create_otel_ingester

    try:
        ingester = await create_otel_ingester(
            hot_store_path=":memory:",
            storage_type=storage_type,
            pgvector_dsn=pg_url,
        )
    except Exception as e:
        print(f"  FAILED to create ingester: {e}")
        return False

    # Clear any existing test data first
    print("  Clearing old test data...")
    try:
        if ingester._pgvector_adapter:
            await ingester._pgvector_adapter.delete(
                collection="otel_traces",
                ids=["pg-trace-1", "pg-trace-2", "pg-trace-3"],
            )
    except Exception:
        pass

    traces = [
        sample_trace("mahavishnu", "pg-trace-1", "CODE_GENERATION"),
        sample_trace("mahavishnu", "pg-trace-2", "REASONING"),
        sample_trace("akosha", "pg-trace-3", "SEARCH"),
    ]

    print(f"  Ingesting {len(traces)} traces...")
    result = await ingester.ingest_batch(traces)
    print(f"  Ingested: {result['success_count']} success, {result['error_count']} errors")

    if result["errors"]:
        for err in result["errors"]:
            print(f"    ERROR: {err}")

    # Search
    results = await ingester.search_traces("span", limit=10)
    print(f"  Search: {len(results)} results")

    # Get by ID
    trace = await ingester.get_trace_by_id("pg-trace-1")
    print(f"  Get by ID: {'found' if trace else 'not found'}")
    if trace:
        print(f"    system_id={trace.get('metadata', {}).get('attributes', {}).get('service.name')}")

    await ingester.close()
    return result["success_count"] == 3


async def main():
    print("=" * 60)
    print("OTel Ingester pgvector End-to-End Test (Phase 1.4)")
    print("=" * 60)

    duckdb_ok = await test_duckdb()
    print(f"\nDuckDB: {'PASS' if duckdb_ok else 'FAIL'}")

    pgvector_ok = await test_pgvector()
    print(f"pgvector: {'PASS' if pgvector_ok else 'FAIL'}")

    print("\n" + "=" * 60)
    if duckdb_ok and pgvector_ok:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())