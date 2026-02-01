# Native OTel API Reference

Complete API reference for the native OpenTelemetry storage implementation using Akosha HotStore and DuckDB.

---

## Table of Contents

- [OtelIngester](#otelingester)
  - [__init__](#init)
  - [initialize](#initialize)
  - [ingest_log_file](#ingest_log_file)
  - [ingest_trace](#ingest_trace)
  - [batch_store](#batch_store)
  - [search_traces](#search_traces)
  - [get_trace](#get_trace)
  - [get_statistics](#get_statistics)
  - [health_check](#health_check)
  - [flush](#flush)
  - [close](#close)

---

## OtelIngester

Main class for ingesting and searching OpenTelemetry traces using Akosha HotStore.

### Class Definition

```python
from mahavishnu.otel import OtelIngester

class OtelIngester:
    """Ingest OTel traces into Akosha HotStore with semantic search.

    This class provides a high-level interface for:
    - Ingesting OTel trace logs from files
    - Generating semantic embeddings for traces
    - Storing traces in DuckDB HotStore
    - Performing semantic search queries
    - Retrieving traces by ID
    - Gathering statistics

    Example:
        >>> ingester = OtelIngester()
        >>> await ingester.initialize()
        >>> await ingester.ingest_log_file("/path/to/session.json")
        >>> results = await ingester.search_traces("authentication error")
        >>> await ingester.close()
    """
```

---

### __init__

Initialize the OTel ingester with configuration.

**Signature:**

```python
def __init__(
    database_path: str = ":memory:",
    embedding_model: str = "all-MiniLM-L6-v2",
    embedding_dimension: int = 384,
    cache_size: int = 1000,
    similarity_threshold: float = 0.75,
    batch_size: int = 100,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `database_path` | `str` | `":memory:"` | DuckDB database path. Use `":memory:"` for in-memory, or file path for persistence |
| `embedding_model` | `str` | `"all-MiniLM-L6-v2"` | Name of sentence-transformers model to use for embeddings |
| `embedding_dimension` | `int` | `384` | Dimension of embedding vectors (must match model) |
| `cache_size` | `int` | `1000` | Number of embeddings to cache in memory |
| `similarity_threshold` | `float` | `0.75` | Minimum similarity score for search results (0.0-1.0) |
| `batch_size` | `int` | `100` | Number of traces to batch for bulk operations |

**Raises:**

- `ValueError`: If `embedding_dimension` doesn't match model output
- `ValueError`: If `similarity_threshold` not in range [0.0, 1.0]
- `ValueError`: If `cache_size` or `batch_size` <= 0

**Example:**

```python
# Default configuration (in-memory)
ingester = OtelIngester()

# Persistent storage
ingester = OtelIngester(
    database_path="/var/lib/mahavishnu/otel.db"
)

# High-quality embeddings
ingester = OtelIngester(
    embedding_model="all-mpnet-base-v2",
    embedding_dimension=768,
    similarity_threshold=0.80,
)

# Custom tuning
ingester = OtelIngester(
    cache_size=5000,
    batch_size=500,
    similarity_threshold=0.70,
)
```

---

### initialize

Initialize the HotStore database and embedding model.

**Signature:**

```python
async def initialize() -> None
```

**Description:**

Creates the DuckDB database schema, initializes the HNSW vector index, and loads the sentence-transformers model. This method must be called before any other operations.

**Raises:**

- `RuntimeError`: If database initialization fails
- `ConnectionError`: If DuckDB cannot connect to database file
- `OSError`: If database file path is not writable

**Example:**

```python
ingester = OtelIngester()
await ingester.initialize()

# Ready to ingest and search
```

---

### ingest_log_file

Ingest OTel traces from a log file.

**Signature:**

```python
async def ingest_log_file(
    file_path: str,
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | `str` | Yes | Path to OTel log file (JSON format) |

**Returns:**

```python
{
    "status": "success",  # "success" or "error"
    "file_path": "/path/to/file.json",
    "traces_ingested": 127,
    "spans_ingested": 542,
    "errors": [],  # List of parsing errors (if any)
    "ingestion_time_seconds": 0.45,
}
```

**Raises:**

- `FileNotFoundError`: If log file doesn't exist
- `json.JSONDecodeError`: If file is not valid JSON
- `ValueError`: If file is not in expected OTel format

**Description:**

Parses an OTel log file (JSON format), extracts traces and spans, generates embeddings, and stores them in HotStore. The file should contain OTel trace data in the standard OpenTelemetry JSON format.

**Supported File Formats:**

1. **OTel JSON Export Format:**
```json
{
  "resourceSpans": [
    {
      "resource": {...},
      "scopeSpans": [
        {
          "scope": {...},
          "spans": [
            {
              "traceId": "abc123...",
              "spanId": "def456...",
              "name": "span.name",
              "kind": "CLIENT",
              "startTimeUnixNano": 1234567890000000,
              "endTimeUnixNano": 1234567891000000,
              "status": {...},
              "attributes": {...},
              "events": [...],
              "links": [...]
            }
          ]
        }
      ]
    }
  ]
}
```

2. **Custom JSON Format:**
```json
{
  "traces": [
    {
      "trace_id": "abc123",
      "span_id": "def456",
      "name": "operation.name",
      "summary": "Human-readable summary",
      "attributes": {...}
    }
  ]
}
```

**Example:**

```python
# Ingest a single file
result = await ingester.ingest_log_file("/path/to/session.json")
print(f"Ingested {result['traces_ingested']} traces")

# Check for errors
if result['errors']:
    for error in result['errors']:
        print(f"Error: {error}")
```

---

### ingest_trace

Ingest a single trace into HotStore.

**Signature:**

```python
async def ingest_trace(
    trace_id: str,
    span_id: str,
    name: str,
    summary: str,
    start_time: datetime,
    end_time: datetime,
    kind: str = "INTERNAL",
    status: str = "UNSET",
    parent_span_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `trace_id` | `str` | Yes | Unique trace identifier (hex string) |
| `span_id` | `str` | Yes | Unique span identifier (hex string) |
| `name` | `str` | Yes | Span name (e.g., "http.request") |
| `summary` | `str` | Yes | Human-readable summary for semantic search |
| `start_time` | `datetime` | Yes | Span start time (UTC) |
| `end_time` | `datetime` | Yes | Span end time (UTC) |
| `kind` | `str` | No | Span kind. Default: "INTERNAL" |
| `status` | `str` | No | Span status. Default: "UNSET" |
| `parent_span_id` | `str \| None` | No | Parent span ID if nested |
| `attributes` | `dict \| None` | No | Span attributes (key-value pairs) |
| `events` | `list \| None` | No | Span events (timestamps + annotations) |
| `links` | `list \| None` | No | Links to other spans |

**Span Kind Values:**

- `INTERNAL`: Internal operation within service
- `SERVER`: Server-side handler (e.g., HTTP request)
- `CLIENT`: Client-side call (e.g., HTTP request)
- `PRODUCER`: Message producer
- `CONSUMER`: Message consumer

**Status Values:**

- `UNSET`: Status not set
- `OK`: Operation completed successfully
- `ERROR`: Operation failed with error

**Returns:**

```python
{
    "status": "success",
    "trace_id": "abc123...",
    "span_id": "def456...",
    "embedding_generated": True,
    "indexed": True,
}
```

**Raises:**

- `ValueError`: If required fields are missing or invalid
- `RuntimeError`: If embedding generation fails

**Example:**

```python
from datetime import datetime, timezone

# Ingest a trace
result = await ingester.ingest_trace(
    trace_id="abc123def456",
    span_id="789ghi012jkl",
    name="http.client.request",
    summary="HTTP POST request to /api/users endpoint",
    start_time=datetime.now(timezone.utc),
    end_time=datetime.now(timezone.utc),
    kind="CLIENT",
    status="OK",
    attributes={
        "http.method": "POST",
        "http.url": "https://api.example.com/users",
        "http.status_code": 201,
        "net.peer.name": "api.example.com",
    },
)
```

---

### batch_store

Store multiple traces in a single batch.

**Signature:**

```python
async def batch_store(
    traces: list[dict[str, Any]],
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `traces` | `list[dict]` | Yes | List of trace dictionaries (same format as `ingest_trace`) |

**Returns:**

```python
{
    "status": "success",
    "traces_stored": 100,
    "batch_size": 100,
    "embeddings_generated": 100,
    "time_seconds": 0.23,
}
```

**Raises:**

- `ValueError`: If traces list is empty
- `RuntimeError`: If batch insertion fails

**Description:**

More efficient than calling `ingest_trace` multiple times. Uses DuckDB's batch insert capability for better performance.

**Example:**

```python
from datetime import datetime, timezone

# Create batch of traces
traces = []
for i in range(100):
    traces.append({
        "trace_id": f"trace-{i}",
        "span_id": f"span-{i}",
        "name": f"operation.{i}",
        "summary": f"Operation number {i} processing data",
        "start_time": datetime.now(timezone.utc),
        "end_time": datetime.now(timezone.utc),
        "kind": "INTERNAL",
        "status": "OK",
        "attributes": {"index": i},
    })

# Store in batch
result = await ingester.batch_store(traces)
print(f"Stored {result['traces_stored']} traces in {result['time_seconds']:.2f}s")
```

---

### search_traces

Perform semantic search over ingested traces.

**Signature:**

```python
async def search_traces(
    query: str,
    limit: int = 10,
    threshold: float | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Natural language search query |
| `limit` | `int` | No | Maximum results to return. Default: 10 |
| `threshold` | `float \| None` | No | Minimum similarity score (0.0-1.0). Default: from config |
| `filters` | `dict \| None` | No | Attribute filters (e.g., `{"kind": "CLIENT"}`) |

**Returns:**

```python
[
    {
        "trace_id": "abc123...",
        "span_id": "def456...",
        "similarity": 0.892,  # Cosine similarity (0-1)
        "name": "http.client.request",
        "summary": "HTTP POST request to /api/users endpoint",
        "timestamp": "2025-01-31T14:23:45Z",
        "kind": "CLIENT",
        "status": "OK",
        "duration_ms": 1234,
        "attributes": {
            "http.method": "POST",
            "http.url": "https://api.example.com/users",
        },
    },
    # ... more results
]
```

**Raises:**

- `ValueError`: If `query` is empty or `limit` <= 0
- `ValueError`: If `threshold` not in range [0.0, 1.0]

**Description:**

Performs semantic search using cosine similarity between query embedding and stored trace embeddings. Results are sorted by similarity score (highest first).

**Search Algorithm:**

1. Generate embedding for query using same model as traces
2. Query HNSW index for nearest neighbors
3. Filter by similarity threshold
4. Apply attribute filters if provided
5. Sort by similarity and limit results

**Example:**

```python
# Basic search
results = await ingester.search_traces(
    query="authentication error when accessing API"
)

# Search with threshold
results = await ingester.search_traces(
    query="memory usage spike",
    threshold=0.80,  # Only high-quality matches
)

# Search with filters
results = await ingester.search_traces(
    query="database connection",
    filters={
        "kind": "CLIENT",
        "status": "ERROR",
    },
)

# Search with pagination
results = await ingester.search_traces(
    query="timeout during request",
    limit=50,
)
```

---

### get_trace

Retrieve a specific trace by ID.

**Signature:**

```python
async def get_trace(
    trace_id: str,
) -> dict[str, Any] | None
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `trace_id` | `str` | Yes | Trace identifier (hex string) |

**Returns:**

```python
{
    "trace_id": "abc123...",
    "span_id": "def456...",
    "parent_span_id": "ghi789...",  # If nested
    "name": "http.client.request",
    "kind": "CLIENT",
    "status": "OK",
    "start_time": "2025-01-31T14:23:45.123456Z",
    "end_time": "2025-01-31T14:23:46.567890Z",
    "duration_ms": 1444,
    "attributes": {
        "http.method": "POST",
        "http.url": "https://api.example.com/users",
        "http.status_code": 201,
        "net.peer.name": "api.example.com",
    },
    "events": [
        {
            "time": "2025-01-31T14:23:45.500000Z",
            "name": "connection.opened",
        },
    ],
    "links": [],
    "summary": "HTTP POST request to /api/users endpoint",
    "embedding": [0.123, -0.456, ...],  # 384-dim vector
    "created_at": "2025-01-31T14:23:45Z",
}
```

Returns `None` if trace not found.

**Example:**

```python
# Get specific trace
trace = await ingester.get_trace("abc123def456")

if trace:
    print(f"Trace: {trace['name']}")
    print(f"Duration: {trace['duration_ms']}ms")
    print(f"Status: {trace['status']}")
    print(f"Summary: {trace['summary']}")
else:
    print("Trace not found")
```

---

### get_statistics

Get statistics about ingested traces.

**Signature:**

```python
async def get_statistics() -> dict[str, Any]
```

**Parameters:** None

**Returns:**

```python
{
    "total_traces": 12458,
    "total_spans": 45623,
    "unique_names": 234,
    "avg_duration_ms": 234.5,
    "min_duration_ms": 1.2,
    "max_duration_ms": 15234.5,
    "by_status": {
        "OK": 11200,
        "ERROR": 892,
        "UNSET": 366,
    },
    "by_kind": {
        "INTERNAL": 5423,
        "SERVER": 3211,
        "CLIENT": 3456,
        "PRODUCER": 234,
        "CONSUMER": 134,
    },
    "storage_backend": "duckdb_hotstore",
    "database_size_mb": 48.2,
    "index_size_mb": 12.3,
    "cache_hit_rate": 0.85,
}
```

**Example:**

```python
# Get statistics
stats = await ingester.get_statistics()

print(f"Total traces: {stats['total_traces']}")
print(f"Average duration: {stats['avg_duration_ms']:.2f}ms")
print(f"Traces by status:")
for status, count in stats['by_status'].items():
    print(f"  {status}: {count}")
```

---

### health_check

Check the health of the HotStore database.

**Signature:**

```python
async def health_check() -> dict[str, Any]
```

**Parameters:** None

**Returns:**

```python
{
    "healthy": True,
    "database_path": ":memory:",
    "storage_backend": "duckdb_hotstore",
    "total_traces": 12458,
    "cache_size": 1000,
    "cache_entries": 850,
    "index_built": True,
    "index_type": "HNSW",
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_dimension": 384,
    "database_size_mb": 48.2,
    "last_ingestion_time": "2025-01-31T14:23:45Z",
}
```

**Example:**

```python
# Check health
health = await ingester.health_check()

if health['healthy']:
    print("✅ HotStore is healthy")
    print(f"   Traces: {health['total_traces']}")
    print(f"   Cache: {health['cache_entries']}/{health['cache_size']}")
else:
    print("❌ HotStore is unhealthy")
```

---

### flush

Force flush any pending traces to storage.

**Signature:**

```python
async def flush() -> dict[str, Any]
```

**Parameters:** None

**Returns:**

```python
{
    "status": "success",
    "traces_flushed": 47,
    "batches_flushed": 1,
    "time_seconds": 0.02,
}
```

**Description:**

Flushes any pending traces from the batch buffer to persistent storage. Normally called automatically during `close()`, but can be called manually to ensure persistence.

**Example:**

```python
# Ingest traces
await ingester.ingest_log_file("/path/to/file.json")

# Force flush (optional)
result = await ingester.flush()
print(f"Flushed {result['traces_flushed']} traces")
```

---

### close

Close the ingester and release resources.

**Signature:**

```python
async def close() -> None
```

**Parameters:** None

**Returns:** None

**Description:**

Flushes any pending traces, closes the DuckDB connection, and releases resources. Should be called when done using the ingester.

**Example:**

```python
try:
    ingester = OtelIngester()
    await ingester.initialize()

    # ... do work ...

finally:
    await ingester.close()
```

---

## Type Definitions

### TraceData

```python
type TraceData = {
    "trace_id": str,
    "span_id": str,
    "parent_span_id": str | None,
    "name": str,
    "kind": str,  # "INTERNAL" | "SERVER" | "CLIENT" | "PRODUCER" | "CONSUMER"
    "status": str,  # "UNSET" | "OK" | "ERROR"
    "start_time": datetime,
    "end_time": datetime,
    "duration_ms": float,
    "attributes": dict[str, Any],
    "events": list[dict[str, Any]],
    "links": list[dict[str, Any]],
    "summary": str,
}
```

### SearchResult

```python
type SearchResult = {
    "trace_id": str,
    "span_id": str,
    "similarity": float,  # 0.0 to 1.0
    "name": str,
    "summary": str,
    "timestamp": str,  # ISO 8601
    "kind": str,
    "status": str,
    "duration_ms": float,
    "attributes": dict[str, Any],
}
```

### IngestionResult

```python
type IngestionResult = {
    "status": str,  # "success" | "error"
    "traces_ingested": int,
    "spans_ingested": int,
    "errors": list[str],
    "ingestion_time_seconds": float,
}
```

---

## Error Handling

### Common Exceptions

| Exception | Cause | Solution |
|-----------|-------|----------|
| `FileNotFoundError` | Log file doesn't exist | Check file path |
| `json.JSONDecodeError` | Invalid JSON format | Validate file format |
| `ValueError` | Invalid parameter | Check parameter values |
| `RuntimeError` | Database operation failed | Check database path and permissions |
| `ConnectionError` | Cannot connect to database | Verify database file is accessible |
| `OSError` | File system error | Check file permissions |

### Error Handling Pattern

```python
from mahavishnu.otel import OtelIngester

async def safe_ingestion():
    ingester = OtelIngester()

    try:
        await ingester.initialize()
        result = await ingester.ingest_log_file("/path/to/file.json")
        return result

    except FileNotFoundError as e:
        print(f"File not found: {e}")
        # Handle missing file

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        # Handle parsing error

    except ValueError as e:
        print(f"Invalid parameter: {e}")
        # Handle validation error

    except RuntimeError as e:
        print(f"Database error: {e}")
        # Handle database error

    finally:
        await ingester.close()
```

---

## Best Practices

### 1. Resource Management

Always use `async with` or `try/finally` to ensure cleanup:

```python
# Pattern 1: try/finally
ingester = OtelIngester()
try:
    await ingester.initialize()
    # ... do work ...
finally:
    await ingester.close()

# Pattern 2: Use context manager (if available)
async with OtelIngester() as ingester:
    await ingester.initialize()
    # ... do work ...
```

### 2. Batch Ingestion

Use `batch_store` for multiple traces:

```python
# Good: Batch ingestion
traces = [parse_trace(line) for line in lines]
await ingester.batch_store(traces)

# Avoid: Individual ingestion
for trace in traces:
    await ingester.ingest_trace(**trace)  # Slower
```

### 3. Search Optimization

Start with broad queries, then refine:

```python
# Step 1: Broad search
results = await ingester.search_traces(
    query="database error",
    limit=100,
)

# Step 2: Filter results
error_results = [r for r in results if r['status'] == 'ERROR']

# Step 3: Analyze top results
for result in error_results[:10]:
    print(result['summary'])
```

### 4. Memory Management

Use in-memory mode for testing, file mode for production:

```python
# Development: In-memory (fast, no persistence)
ingester = OtelIngester(database_path=":memory:")

# Production: File-backed (persistent)
ingester = OtelIngester(database_path="/var/lib/mahavishnu/otel.db")
```

### 5. Error Handling

Always handle exceptions and provide context:

```python
try:
    result = await ingester.ingest_log_file(file_path)
    logger.info(f"Ingested {result['traces_ingested']} traces from {file_path}")
except Exception as e:
    logger.error(f"Failed to ingest {file_path}: {e}")
    raise
```

---

## Performance Considerations

### Embedding Generation

Embedding generation is the bottleneck (~80% of ingestion time). Optimize by:

1. **Choosing the right model:**
   - `all-MiniLM-L6-v2`: Fast, good quality (384 dims)
   - `all-mpnet-base-v2`: Slower, better quality (768 dims)

2. **Using batch ingestion:**
   ```python
   # Batch embedding generation
   await ingester.batch_store(traces)  # Faster
   ```

3. **Caching embeddings:**
   ```python
   # Larger cache for repeated queries
   ingester = OtelIngester(cache_size=5000)
   ```

### Search Performance

HNSW index provides O(log N) search complexity:

- **1,000 traces:** ~12ms
- **10,000 traces:** ~28ms
- **100,000 traces:** ~95ms
- **1,000,000 traces:** ~450ms

Optimize by:

1. **Adjusting similarity threshold:**
   ```python
   # Higher threshold = fewer results, faster
   results = await ingester.search_traces(query, threshold=0.85)
   ```

2. **Using attribute filters:**
   ```python
   # Pre-filter by attributes
   results = await ingester.search_traces(
       query,
       filters={"kind": "CLIENT"},  # Reduces search space
   )
   ```

3. **Limiting results:**
   ```python
   # Smaller limit = faster
   results = await ingester.search_traces(query, limit=10)
   ```

### Memory Usage

**In-Memory Mode:**
- Base: ~10MB (DuckDB overhead)
- Per trace: ~4KB (including embedding)
- Example: 10,000 traces ≈ 50MB

**File-Backed Mode:**
- Same memory footprint
- Disk usage: ~2x memory size
- Startup penalty: ~200ms

---

## Advanced Usage

### Custom Embedding Models

```python
# Use custom model
ingester = OtelIngester(
    embedding_model="sentence-transformers/all-roberta-large-v1",
    embedding_dimension=1024,
)
```

### Multi-Process Ingestion

```python
# Process multiple files in parallel
import asyncio

async def ingest_files(file_paths):
    tasks = [
        ingester.ingest_log_file(fp)
        for fp in file_paths
    ]
    results = await asyncio.gather(*tasks)
    return results
```

### Distributed Search

```python
# Search multiple HotStore instances
async def distributed_search(query, stores):
    tasks = [
        store.search_traces(query, limit=10)
        for store in stores
    ]
    all_results = await asyncio.gather(*tasks)

    # Merge and deduplicate results
    merged = []
    seen = set()
    for results in all_results:
        for result in results:
            if result['trace_id'] not in seen:
                merged.append(result)
                seen.add(result['trace_id'])

    # Sort by similarity
    merged.sort(key=lambda r: r['similarity'], reverse=True)
    return merged[:10]
```

---

## References

- **Setup Guide:** `docs/NATIVE_OTEL_SETUP_GUIDE.md`
- **Architecture:** `docs/NATIVE_OTEL_ARCHITECTURE.md`
- **MCP Tools:** `docs/MCP_TOOLS_SPECIFICATION.md`
- **DuckDB:** https://duckdb.org/docs/
- **sentence-transformers:** https://www.sbert.net/
