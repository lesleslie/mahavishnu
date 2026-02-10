# Native OTel Documentation - Summary

This document provides an overview of the native OpenTelemetry trace storage documentation for Mahavishnu using Akosha HotStore (DuckDB).

---

## Documentation Files

### 1. Setup Guide
**File:** `/Users/les/Projects/mahavishnu/docs/NATIVE_OTEL_SETUP_GUIDE.md` (24 KB)

**Contents:**
- Quick start guide (5 minutes to get running)
- Architecture overview with ASCII diagrams
- Detailed comparison: DuckDB vs PostgreSQL + pgvector
- Installation instructions (3 methods)
- Configuration examples (basic, production, development, testing)
- Usage examples (6 practical scenarios)
- MCP tool reference (4 tools with examples)
- Performance characteristics and benchmarks
- Troubleshooting guide (10+ common issues)

**Audience:** Users getting started with OTel storage

### 2. API Reference
**File:** `/Users/les/Projects/mahavishnu/docs/NATIVE_OTEL_API.md` (23 KB)

**Contents:**
- Complete `OtelIngester` class reference
- Method signatures with type hints
- Parameter descriptions and defaults
- Return value specifications
- Usage examples for each method
- Error conditions and handling
- Type definitions (TraceData, SearchResult, etc.)
- Best practices (5 patterns)
- Performance considerations
- Advanced usage patterns

**Audience:** Developers integrating OTel storage

### 3. Working Examples
**File:** `/Users/les/Projects/mahavishnu/examples/native_otel_example.py` (27 KB)

**Contents:**
- 8 runnable examples demonstrating:
  1. Ingest Claude session logs
  2. Ingest Qwen session logs
  3. Semantic search queries
  4. Retrieve trace by ID
  5. Batch ingestion
  6. MCP tool usage (simulated)
  7. Health check
  8. Real-world workflow

**Features:**
- All examples are runnable (when implementation exists)
- Expected output shown in comments
- Covers common use cases
- Error handling patterns
- Async/await patterns

**Audience:** Developers learning by example

### 4. MCP Tools Specification (Updated)
**File:** `/Users/les/Projects/mahavishnu/docs/MCP_TOOLS_SPECIFICATION.md`

**Added Section:** OpenTelemetry Tools

**Contents:**
- 4 MCP tools documented:
  1. `ingest_otel_traces` - Ingest log files
  2. `search_otel_traces` - Semantic search
  3. `get_trace_by_id` - Retrieve specific trace
  4. `get_otel_statistics` - Query statistics

**Features:**
- Complete parameter specifications
- Return value examples
- Error conditions
- Usage examples
- Consistent with existing MCP tool documentation

---

## Key Architecture Points

### Why DuckDB Over PostgreSQL?

| Feature | DuckDB | PostgreSQL |
|---------|--------|------------|
| Setup | `pip install duckdb` | Docker + pgvector |
| Startup | <100ms | ~5 seconds |
| Vector Search | Built-in HNSW | Requires extension |
| In-Memory Mode | Yes | No |
| Dependencies | 1 package | 3+ packages |

### Architecture Flow

```
Claude/Qwen Logs → OTel Collector → OtelIngester → DuckDB HotStore → Semantic Search
```

### Key Benefits

- **Zero Docker** - No containers required
- **Instant Startup** - <100ms initialization
- **Built-in Vector Search** - HNSW index with cosine similarity
- **File Persistence Optional** - In-memory or file-backed
- **No External Database** - PostgreSQL not required
- **Simpler Architecture** - 1 component vs 3

---

## Quick Start Path

1. **Read Setup Guide** (5 minutes)
   - Follow "Quick Start (5 Minutes)" section
   - Install dependencies: `pip install duckdb sentence-transformers`
   - Configure `settings/mahavishnu.yaml`

2. **Run Examples** (10 minutes)
   - `python examples/native_otel_example.py`
   - See 8 working examples
   - Understand patterns

3. **Reference API** (as needed)
   - Look up specific methods
   - Check parameter types
   - Follow best practices

4. **Integrate** (ongoing)
   - Use MCP tools for integration
   - Customize configuration
   - Monitor performance

---

## Implementation Status

**Note:** This documentation describes a **proposed architecture**. The implementation does not yet exist in the codebase.

**What exists:**
- Architecture design document (`docs/NATIVE_OTEL_ARCHITECTURE.md`)
- OTel adapter stub (`oneiric/adapters/observability/otel.py`)
- OTel example using PostgreSQL (`examples/otel_storage_example.py`)

**What needs to be implemented:**
1. `mahavishnu/otel/ingester.py` - OtelIngester class
2. `mahavishnu/otel/hotstore.py` - HotStore integration
3. `mahavishnu/mcp/tools/otel_tools.py` - MCP tools
4. Configuration integration with MahavishnuSettings

**Implementation tasks:**
- Integrate with Akosha HotStore (separate repository)
- Implement DuckDB-based storage
- Add sentence-transformers embedding generation
- Create HNSW vector index
- Implement 4 MCP tools
- Add unit tests
- Update configuration schema

---

## Performance Benchmarks

From the architecture document:

| Operation | DuckDB HotStore | PostgreSQL + pgvector | Speedup |
|-----------|----------------|----------------------|---------|
| Startup | 89ms | 4.8s | **54x faster** |
| Ingest 1000 traces | 0.52s | 1.2s | **2.3x faster** |
| Semantic search | 48ms | 82ms | **1.7x faster** |
| Memory usage | 48MB | 198MB | **4.1x less** |

---

## Configuration Examples

### Basic (Development)
```yaml
otel_storage:
  enabled: true
  backend: "akosha_hotstore"
  database_path: ":memory:"  # In-memory
  embedding_model: "all-MiniLM-L6-v2"
  embedding_dimension: 384
```

### Production
```yaml
otel_storage:
  enabled: true
  backend: "akosha_hotstore"
  database_path: "/var/lib/mahavishnu/otel.db"  # Persistent
  embedding_model: "all-mpnet-base-v2"
  embedding_dimension: 768
  cache_size: 10000
  similarity_threshold: 0.80
```

---

## MCP Tools

### 1. ingest_otel_traces
Ingest OTel log files into HotStore.

```python
await mcp.call_tool("ingest_otel_traces", {
    "log_files": ["/path/to/session.json"],
    "batch_size": 200,
})
```

### 2. search_otel_traces
Semantic search over traces.

```python
results = await mcp.call_tool("search_otel_traces", {
    "query": "authentication error",
    "limit": 5,
    "threshold": 0.80,
})
```

### 3. get_trace_by_id
Retrieve specific trace.

```python
trace = await mcp.call_tool("get_trace_by_id", {
    "trace_id": "abc123",
})
```

### 4. get_otel_statistics
Query database statistics.

```python
stats = await mcp.call_tool("get_otel_statistics", {})
```

---

## Next Steps

1. **Implement OtelIngester** - Core ingestion logic
2. **Integrate Akosha HotStore** - DuckDB storage layer
3. **Create MCP tools** - Expose functionality via MCP
4. **Write tests** - Unit and integration tests
5. **Update examples** - Make examples runnable
6. **Benchmark** - Validate performance claims

---

## Related Documentation

- **Architecture:** `docs/NATIVE_OTEL_ARCHITECTURE.md`
- **Setup Guide:** `docs/NATIVE_OTEL_SETUP_GUIDE.md`
- **API Reference:** `docs/NATIVE_OTEL_API.md`
- **Examples:** `examples/native_otel_example.py`
- **MCP Tools:** `docs/MCP_TOOLS_SPECIFICATION.md` (OTel section)
- **Pool Architecture:** `docs/POOL_ARCHITECTURE.md`
- **Session Buddy:** `docs/SESSION_BUDDY_WORKER_PROPOSALS.md`

---

## Support

For questions or issues:
1. Check troubleshooting guide in setup guide
2. Review API reference for method details
3. Run examples to understand patterns
4. Check architecture document for design decisions

---

**Documentation Version:** 1.0
**Last Updated:** 2025-02-01
**Status:** Design Document (Implementation Pending)
