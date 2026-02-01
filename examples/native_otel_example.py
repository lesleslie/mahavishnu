"""
Native OTel Example - Mahavishnu with Akosha HotStore

This example demonstrates the native OpenTelemetry trace storage
implementation using DuckDB (no Docker or PostgreSQL required).

Run this example:
    python examples/native_otel_example.py

Requirements:
    pip install duckdb sentence-transformers
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# =============================================================================
# Example 1: Ingest Claude Session Logs
# =============================================================================

async def example_ingest_claude_sessions():
    """Example 1: Ingest Claude session logs into HotStore."""
    print("\n" + "=" * 70)
    print("Example 1: Ingest Claude Session Logs")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize ingester with in-memory database
        print("Initializing OTel Ingester (in-memory mode)...")
        ingester = OtelIngester(
            database_path=":memory:",
            embedding_model="all-MiniLM-L6-v2",
            cache_size=1000,
        )
        await ingester.initialize()
        print("✅ Ingester initialized\n")

        # Create sample Claude session data
        print("Creating sample Claude session data...")
        claude_traces = [
            {
                "trace_id": "claude-session-001",
                "span_id": "span-001",
                "name": "claude.completion",
                "summary": "Claude helped implement a REST API using FastAPI with proper error handling and validation",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "ai.model": "claude-3.5-sonnet",
                    "ai.provider": "anthropic",
                    "session.type": "code_generation",
                    "language": "python",
                    "framework": "fastapi",
                },
            },
            {
                "trace_id": "claude-session-002",
                "span_id": "span-002",
                "name": "claude.completion",
                "summary": "User asked about exploiting a vulnerability. Claude refused due to safety guidelines and suggested responsible disclosure",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "ai.model": "claude-3.5-sonnet",
                    "ai.provider": "anthropic",
                    "session.type": "refusal",
                    "reason": "safety_guidelines",
                    "topic": "security_exploitation",
                },
            },
            {
                "trace_id": "claude-session-003",
                "span_id": "span-003",
                "name": "claude.completion",
                "summary": "Claude explained the difference between PostgreSQL and DuckDB for vector search use cases",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "ai.model": "claude-3.5-sonnet",
                    "ai.provider": "anthropic",
                    "session.type": "explanation",
                    "topic": "database_comparison",
                },
            },
        ]

        # Ingest traces
        print(f"Ingesting {len(claude_traces)} Claude session traces...")
        result = await ingester.batch_store(claude_traces)
        print(f"✅ Ingested {result['traces_stored']} traces\n")

        # Get statistics
        stats = await ingester.get_statistics()
        print("Database Statistics:")
        print(f"  Total traces: {stats['total_traces']}")
        print(f"  Unique names: {stats['unique_names']}")
        print(f"  Storage backend: {stats['storage_backend']}\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 1 completed successfully\n")

        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure Mahavishnu is installed: pip install -e .")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 2: Ingest Qwen Session Logs
# =============================================================================

async def example_ingest_qwen_sessions():
    """Example 2: Ingest Qwen session logs into HotStore."""
    print("\n" + "=" * 70)
    print("Example 2: Ingest Qwen Session Logs")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize ingester
        print("Initializing OTel Ingester...")
        ingester = OtelIngester()
        await ingester.initialize()
        print("✅ Ingester initialized\n")

        # Create sample Qwen session data
        print("Creating sample Qwen session data...")
        qwen_traces = [
            {
                "trace_id": "qwen-session-001",
                "span_id": "span-001",
                "name": "qwen.completion",
                "summary": "Qwen generated Python code for data processing using pandas with groupby operations",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "ai.model": "qwen-2.5-coder",
                    "ai.provider": "alibaba",
                    "session.type": "code_generation",
                    "language": "python",
                    "library": "pandas",
                },
            },
            {
                "trace_id": "qwen-session-002",
                "span_id": "span-002",
                "name": "qwen.completion",
                "summary": "Qwen helped debug a SQL query with JOIN operations that was returning duplicate rows",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "ai.model": "qwen-2.5-coder",
                    "ai.provider": "alibaba",
                    "session.type": "debugging",
                    "language": "sql",
                },
            },
            {
                "trace_id": "qwen-session-003",
                "span_id": "span-003",
                "name": "qwen.completion",
                "summary": "Authentication token expired during API call. Qwen suggested implementing token refresh logic",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "ERROR",
                "attributes": {
                    "ai.model": "qwen-2.5",
                    "ai.provider": "alibaba",
                    "session.type": "error_analysis",
                    "error_type": "authentication_error",
                },
            },
        ]

        # Ingest traces
        print(f"Ingesting {len(qwen_traces)} Qwen session traces...")
        result = await ingester.batch_store(qwen_traces)
        print(f"✅ Ingested {result['traces_stored']} traces\n")

        # Get statistics
        stats = await ingester.get_statistics()
        print("Database Statistics:")
        print(f"  Total traces: {stats['total_traces']}")
        print(f"  By status: {stats['by_status']}\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 2 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 3: Semantic Search Queries
# =============================================================================

async def example_semantic_search():
    """Example 3: Perform semantic search over traces."""
    print("\n" + "=" * 70)
    print("Example 3: Semantic Search Queries")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize and populate
        print("Setting up database with sample data...")
        ingester = OtelIngester()
        await ingester.initialize()

        # Add sample data
        sample_traces = [
            {
                "trace_id": "trace-001",
                "span_id": "span-001",
                "name": "http.request",
                "summary": "HTTP POST request to authenticate user with JWT token",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "CLIENT",
                "status": "OK",
                "attributes": {"http.method": "POST", "http.status_code": 200},
            },
            {
                "trace_id": "trace-002",
                "span_id": "span-002",
                "name": "database.query",
                "summary": "Database query timeout when connecting to PostgreSQL server",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "CLIENT",
                "status": "ERROR",
                "attributes": {"db.system": "postgresql", "error.type": "timeout"},
            },
            {
                "trace_id": "trace-003",
                "span_id": "span-003",
                "name": "ai.completion",
                "summary": "AI assistant refused to provide code for exploiting security vulnerabilities",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {"ai.model": "claude-3.5", "session.type": "refusal"},
            },
            {
                "trace_id": "trace-004",
                "span_id": "span-004",
                "name": "python.execution",
                "summary": "Python script executed successfully with pandas data processing",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {"language": "python", "library": "pandas"},
            },
        ]

        await ingester.batch_store(sample_traces)
        print(f"✅ Added {len(sample_traces)} sample traces\n")

        # Perform searches
        queries = [
            "authentication error",
            "database connection problem",
            "security vulnerability refusal",
            "data processing with pandas",
        ]

        print("Performing semantic searches:\n")
        for query in queries:
            print(f"Query: '{query}'")
            print("-" * 70)

            results = await ingester.search_traces(
                query=query,
                limit=2,
                threshold=0.60,
            )

            if results:
                for i, result in enumerate(results, 1):
                    print(f"\n  {i}. {result['trace_id']}")
                    print(f"     Similarity: {result['similarity']:.3f}")
                    print(f"     Summary: {result['summary'][:80]}...")
                    print(f"     Status: {result['status']}")
            else:
                print("  No results found")
            print()

        # Cleanup
        await ingester.close()
        print("✅ Example 3 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 4: Retrieve Trace by ID
# =============================================================================

async def example_retrieve_trace():
    """Example 4: Retrieve a specific trace by ID."""
    print("\n" + "=" * 70)
    print("Example 4: Retrieve Trace by ID")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize and populate
        print("Setting up database...")
        ingester = OtelIngester()
        await ingester.initialize()

        # Add a known trace
        trace_data = {
            "trace_id": "target-trace-123",
            "span_id": "span-123",
            "name": "api.request",
            "summary": "REST API request to retrieve user profile with JWT authentication",
            "start_time": datetime.now(timezone.utc),
            "end_time": datetime.now(timezone.utc),
            "kind": "SERVER",
            "status": "OK",
            "attributes": {
                "http.method": "GET",
                "http.url": "/api/users/123",
                "http.status_code": 200,
                "authentication": "jwt",
            },
        }

        await ingester.ingest_trace(**trace_data)
        print("✅ Added sample trace\n")

        # Retrieve by ID
        print("Retrieving trace by ID: 'target-trace-123'")
        trace = await ingester.get_trace("target-trace-123")

        if trace:
            print("\n✅ Trace found:")
            print(f"  Trace ID: {trace['trace_id']}")
            print(f"  Name: {trace['name']}")
            print(f"  Kind: {trace['kind']}")
            print(f"  Status: {trace['status']}")
            print(f"  Duration: {trace['duration_ms']:.2f}ms")
            print(f"\n  Attributes:")
            for key, value in trace['attributes'].items():
                print(f"    {key}: {value}")
            print(f"\n  Summary: {trace['summary']}\n")
        else:
            print("❌ Trace not found\n")

        # Try to retrieve non-existent trace
        print("Retrieving non-existent trace: 'missing-trace-456'")
        trace = await ingester.get_trace("missing-trace-456")
        if trace is None:
            print("✅ Correctly returned None for missing trace\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 4 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 5: Batch Ingestion
# =============================================================================

async def example_batch_ingestion():
    """Example 5: Batch ingestion of multiple traces."""
    print("\n" + "=" * 70)
    print("Example 5: Batch Ingestion")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize with batch configuration
        print("Initializing ingester with batch size 100...")
        ingester = OtelIngester(batch_size=100)
        await ingester.initialize()
        print("✅ Ingester initialized\n")

        # Create batch of traces
        print("Creating batch of 50 traces...")
        traces = []
        for i in range(50):
            traces.append({
                "trace_id": f"batch-trace-{i:03d}",
                "span_id": f"batch-span-{i:03d}",
                "name": f"batch.operation.{i}",
                "summary": f"Batch operation {i} processing data with ID {i}",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "batch.index": i,
                    "batch.size": 50,
                    "processing.type": "batch",
                },
            })

        # Ingest in batch
        print(f"Ingesting {len(traces)} traces...")
        start_time = datetime.now(timezone.utc)
        result = await ingester.batch_store(traces)
        end_time = datetime.now(timezone.utc)

        duration = (end_time - start_time).total_seconds()
        print(f"\n✅ Batch ingestion completed:")
        print(f"  Traces stored: {result['traces_stored']}")
        print(f"  Batch size: {result['batch_size']}")
        print(f"  Time: {duration:.3f}s")
        print(f"  Throughput: {result['traces_stored'] / duration:.0f} traces/s\n")

        # Get statistics
        stats = await ingester.get_statistics()
        print(f"Database now contains {stats['total_traces']} total traces\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 5 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 6: MCP Tool Usage
# =============================================================================

async def example_mcp_tool_usage():
    """Example 6: Use OTel tools via MCP protocol."""
    print("\n" + "=" * 70)
    print("Example 6: MCP Tool Usage")
    print("=" * 70 + "\n")

    print("This example demonstrates how to use OTel tools via MCP.")
    print("In a real scenario, you would connect to the Mahavishnu MCP server.\n")

    # Simulated MCP tool calls
    print("Simulated MCP tool usage:\n")

    print("1. Ingest OTel traces:")
    print("   await mcp.call_tool('ingest_otel_traces', {")
    print("       'log_files': ['/path/to/claude/session.json']")
    print("   })")
    print("   → Response: {'status': 'success', 'traces_ingested': 127}\n")

    print("2. Search traces:")
    print("   await mcp.call_tool('search_otel_traces', {")
    print("       'query': 'authentication error',")
    print("       'limit': 5")
    print("   })")
    print("   → Response: [{'trace_id': 'abc123', 'similarity': 0.892, ...}]\n")

    print("3. Get trace by ID:")
    print("   await mcp.call_tool('get_trace_by_id', {")
    print("       'trace_id': 'abc123'")
    print("   })")
    print("   → Response: {'trace_id': 'abc123', 'name': 'http.request', ...}\n")

    print("4. Get statistics:")
    print("   await mcp.call_tool('get_otel_statistics', {})")
    print("   → Response: {'total_traces': 12458, 'avg_duration_ms': 234.5, ...}\n")

    print("✅ Example 6 completed (simulation)\n")
    return True


# =============================================================================
# Example 7: Health Check
# =============================================================================

async def example_health_check():
    """Example 7: Perform health check on HotStore."""
    print("\n" + "=" * 70)
    print("Example 7: Health Check")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Initialize
        print("Initializing ingester...")
        ingester = OtelIngester()
        await ingester.initialize()

        # Perform health check
        print("\nPerforming health check...\n")
        health = await ingester.health_check()

        if health['healthy']:
            print("✅ HotStore is HEALTHY\n")
            print(f"  Storage Backend: {health['storage_backend']}")
            print(f"  Database Path: {health['database_path']}")
            print(f"  Total Traces: {health['total_traces']}")
            print(f"  Cache: {health['cache_entries']}/{health['cache_size']}")
            print(f"  Index Built: {health['index_built']}")
            print(f"  Index Type: {health['index_type']}")
            print(f"  Embedding Model: {health['embedding_model']}")
            print(f"  Embedding Dimension: {health['embedding_dimension']}")
            print(f"  Database Size: {health['database_size_mb']:.2f} MB\n")
        else:
            print("❌ HotStore is UNHEALTHY\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 7 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Example 8: Real-World Workflow
# =============================================================================

async def example_real_world_workflow():
    """Example 8: Real-world workflow with ingestion and search."""
    print("\n" + "=" * 70)
    print("Example 8: Real-World Workflow")
    print("=" * 70 + "\n")

    try:
        from mahavishnu.otel import OtelIngester

        # Scenario: Monitor AI assistant sessions for issues
        print("Scenario: Monitor AI assistant sessions and detect issues\n")

        # Step 1: Initialize
        print("Step 1: Initialize monitoring system...")
        ingester = OtelIngester(
            database_path=":memory:",
            cache_size=1000,
            similarity_threshold=0.75,
        )
        await ingester.initialize()
        print("✅ Monitoring system initialized\n")

        # Step 2: Ingest session data (simulating log file ingestion)
        print("Step 2: Ingest session logs...")
        sessions = [
            {
                "trace_id": "session-001",
                "span_id": "span-001",
                "name": "assistant.session",
                "summary": "User requested help with Python async/await. Assistant provided clear explanation with code examples",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "user_id": "user123",
                    "session_length": "5:23",
                    "topic": "python_async",
                    "satisfaction": "high",
                },
            },
            {
                "trace_id": "session-002",
                "span_id": "span-002",
                "name": "assistant.session",
                "summary": "User experienced authentication failure. Assistant helped troubleshoot token refresh issue",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "ERROR",
                "attributes": {
                    "user_id": "user456",
                    "session_length": "3:12",
                    "topic": "authentication",
                    "error_type": "token_expired",
                },
            },
            {
                "trace_id": "session-003",
                "span_id": "span-003",
                "name": "assistant.session",
                "summary": "User asked for SQL query optimization. Assistant suggested adding indexes and rewriting JOIN",
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc),
                "kind": "INTERNAL",
                "status": "OK",
                "attributes": {
                    "user_id": "user789",
                    "session_length": "7:45",
                    "topic": "sql_optimization",
                    "satisfaction": "high",
                },
            },
        ]

        await ingester.batch_store(sessions)
        print(f"✅ Ingested {len(sessions)} session logs\n")

        # Step 3: Search for problematic sessions
        print("Step 3: Search for problematic sessions...")
        problem_queries = [
            "authentication failure",
            "token expired",
            "permission denied",
        ]

        total_issues = 0
        for query in problem_queries:
            results = await ingester.search_traces(
                query=query,
                limit=5,
                threshold=0.70,
            )
            if results:
                total_issues += len(results)
                print(f"  Found {len(results)} sessions matching: '{query}'")

        print(f"\n✅ Total issues detected: {total_issues}\n")

        # Step 4: Generate summary report
        print("Step 4: Generate summary report...")
        stats = await ingester.get_statistics()

        print("\nSession Monitoring Report:")
        print(f"  Total sessions analyzed: {stats['total_traces']}")
        print(f"  Successful sessions: {stats['by_status']['OK']}")
        print(f"  Failed sessions: {stats['by_status']['ERROR']}")
        print(f"  Average duration: {stats['avg_duration_ms']:.2f}ms")
        print(f"  Success rate: {stats['by_status']['OK'] / stats['total_traces'] * 100:.1f}%\n")

        # Step 5: Recommendations
        print("Step 5: Recommendations")
        if stats['by_status']['ERROR'] > 0:
            print("  ⚠️  Authentication issues detected - review token refresh logic")
        else:
            print("  ✅ No critical issues detected")

        if stats['avg_duration_ms'] > 10000:
            print("  ⚠️  High average session duration - consider optimizing responses")
        else:
            print("  ✅ Session duration within acceptable range")

        print("\n")

        # Cleanup
        await ingester.close()
        print("✅ Example 8 completed successfully\n")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("Native OTel Examples - Mahavishnu with Akosha HotStore")
    print("=" * 70)

    # Check dependencies
    print("\nChecking dependencies...")
    try:
        import duckdb
        print("  ✅ duckdb")
    except ImportError:
        print("  ❌ duckdb (install with: pip install duckdb)")
        return

    try:
        import sentence_transformers
        print("  ✅ sentence-transformers")
    except ImportError:
        print("  ❌ sentence-transformers (install with: pip install sentence-transformers)")
        return

    # Run examples
    examples = [
        ("Ingest Claude Sessions", example_ingest_claude_sessions),
        ("Ingest Qwen Sessions", example_ingest_qwen_sessions),
        ("Semantic Search", example_semantic_search),
        ("Retrieve Trace by ID", example_retrieve_trace),
        ("Batch Ingestion", example_batch_ingestion),
        ("MCP Tool Usage", example_mcp_tool_usage),
        ("Health Check", example_health_check),
        ("Real-World Workflow", example_real_world_workflow),
    ]

    results = {}
    for name, example_func in examples:
        try:
            result = await example_func()
            results[name] = result
        except Exception as e:
            print(f"❌ Example '{name}' failed with error: {e}")
            results[name] = False

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70 + "\n")

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    total = len(results)
    passed = sum(1 for r in results.values() if r)

    print(f"\nTotal: {passed}/{total} examples passed\n")

    if passed == total:
        print("🎉 All examples completed successfully!")
    else:
        print(f"⚠️  {total - passed} example(s) failed")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
