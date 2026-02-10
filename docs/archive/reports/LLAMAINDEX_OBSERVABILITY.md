# LlamaIndex Adapter OpenTelemetry Instrumentation

## Overview

The LlamaIndex adapter at `/Users/les/Projects/mahavishnu/mahavishnu/engines/llamaindex_adapter.py` has been enhanced with comprehensive OpenTelemetry instrumentation for distributed tracing and metrics collection.

## Features

### Graceful Degradation

The adapter uses a try/except import pattern to detect OpenTelemetry availability. When OTel is not available or disabled in configuration, it falls back to no-op mock implementations, ensuring the adapter continues to function without instrumentation overhead.

### Tracing

#### Span Hierarchy

```
llamaindex.execute (top-level)
├── llamaindex.ingest (per repository)
│   ├── llamaindex.enhance_documents
│   ├── llamaindex.parse_nodes
│   └── llamaindex.create_index
└── llamaindex.query (per repository)
    ├── llamaindex.find_index
    └── llamaindex.execute_query
```

#### Span Attributes

**`llamaindex.execute` span:**

- `task.type`: Operation type (ingest, query, ingest_and_query)
- `task.id`: Task identifier
- `repos.count`: Number of repositories being processed
- `llamaindex.operation`: Always "execute"
- `execute.success_count`: Number of successful operations
- `execute.failure_count`: Number of failed operations
- `execute.status`: "success" or "partial_failure"

**`llamaindex.ingest` span:**

- `repo.path`: Full repository path
- `repo.name`: Repository name (basename)
- `llamaindex.operation`: Always "ingest"
- `vector.backend`: "opensearch" or "memory"
- `code_graph.nodes`: Number of code graph nodes
- `code_graph.functions`: Number of functions found
- `code_graph.classes`: Number of classes found
- `ingest.file_types`: Comma-separated list of file types included
- `ingest.exclude_patterns`: Comma-separated list of exclusion patterns
- `ingest.documents_count`: Number of documents loaded
- `ingest.nodes_count`: Number of nodes created
- `ingest.duration_seconds`: Total operation duration
- `ingest.index_id`: ID of created index
- `ingest.status`: "success", "no_documents", or error status

**`llamaindex.query` span:**

- `repo.path`: Full repository path
- `repo.name`: Repository name (basename)
- `query.text`: Truncated query text (max 100 chars)
- `query.top_k`: Number of results requested
- `vector.backend`: "opensearch" or "memory"
- `query.duration_seconds`: Query execution time
- `query.sources_count`: Number of sources returned
- `query.status`: "success" or error status

**Error attributes (when errors occur):**

- `error.message`: Error message
- `error.type`: Exception type name
- Span status set to "ERROR"
- Exception recorded in span

### Metrics

All metrics are created with appropriate attributes for filtering and aggregation:

#### Histograms (Duration Metrics)

**`llamaindex.ingest.duration`** (seconds)

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name
  - `vector.backend`: "opensearch" or "memory"

**`llamaindex.query.duration`** (seconds)

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name
  - `vector.backend`: "opensearch" or "memory"
  - `query.top_k`: Number of results requested

#### Counters (Cumulative Metrics)

**`llamaindex.documents.count`**

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name

**`llamaindex.nodes.count`**

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name

**`llamaindex.queries.count`**

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name
  - `vector.backend`: "opensearch" or "memory"

**`llamaindex.indexes.count`**

- Attributes:
  - `repo.path`: Repository path
  - `repo.name`: Repository name
  - `vector.backend`: "opensearch" or "memory"

**`llamaindex.errors.count`**

- Attributes:
  - `operation`: "ingest" or "query"
  - `error_type`: Exception type name
  - `repo.path`: Repository path

## Usage Examples

### Viewing Traces

When OpenTelemetry is configured with an OTLP exporter (e.g., Jaeger, Tempo), traces will automatically be exported. You can view the distributed traces to understand:

1. End-to-end request flow through the RAG pipeline
1. Performance bottlenecks in document ingestion or querying
1. Error propagation across operations
1. Relationship between parent and child operations

### Analyzing Metrics

Metrics can be queried in your observability platform (Prometheus, Grafana, etc.):

**Average ingestion time by repository:**

```promql
rate(llamaindex_ingest_duration_sum[5m]) / rate(llamaindex_ingest_duration_count[5m])
```

**Error rate by operation type:**

```promql
rate(llamaindex_errors_count[5m]) by (operation)
```

**Query performance percentiles:**

```promql
histogram_quantile(0.95, rate(llamaindex_query_duration_bucket[5m]))
```

**Document ingestion throughput:**

```promql
rate(llamaindex_documents_count[5m])
```

## Configuration

OpenTelemetry instrumentation is enabled/disabled via the `metrics_enabled` configuration field in `MahavishnuSettings`:

```yaml
# In settings/mahavishnu.yaml
metrics_enabled: true  # Enable OpenTelemetry instrumentation
otlp_endpoint: "http://localhost:4317"  # OTLP gRPC endpoint
```

When `metrics_enabled` is `false` or OpenTelemetry is not installed, the adapter uses no-op mock implementations, adding zero overhead.

## Implementation Details

### Fallback Pattern

The adapter uses the same graceful degradation pattern as `mahavishnu/core/observability.py`:

1. Try to import OpenTelemetry modules
1. If successful, initialize real tracers and meters
1. If unavailable or disabled, use mock implementations
1. All instrumentation code paths work identically regardless of availability

### Resource Metadata

The adapter creates a dedicated resource for service identification:

```python
resource = Resource.create({"service.name": "mahavishnu-llamaindex"})
```

This allows traces and metrics to be attributed specifically to the LlamaIndex adapter.

### Tracer and Meter Names

- **Tracer**: `mahavishnu.llamaindex` (version 1.0.0)
- **Meter**: `mahavishnu.llamaindex` (version 1.0.0)

These names follow OpenTelemetry naming conventions and enable proper instrumentation library identification.

## Health Check

The `get_health()` method now returns telemetry status:

```python
{
    "status": "healthy",
    "details": {
        "telemetry_enabled": true,  # Whether OTel is active
        "opentelemetry_available": true,  # Whether OTel is installed
        "vector_backend": "opensearch",  # or "memory"
        # ... other health details
    }
}
```

## Best Practices

1. **Always use span attributes** for contextual information (repo path, operation type, etc.)
1. **Record exceptions** in spans using `span.record_exception(e)` for full error context
1. **Set span status** to ERROR when operations fail
1. **Use histogram units** (e.g., "s" for seconds) for metric clarity
1. **Include attributes on metrics** for filtering and aggregation
1. **Truncate long text** (like query text) to avoid excessive span size
1. **Use child spans** for logical sub-operations (enhance_documents, parse_nodes, etc.)

## Testing

The instrumentation is designed to be transparent to existing functionality:

- All existing tests should pass without modification
- When OTel is unavailable, the adapter functions normally without telemetry
- When OTel is available, traces and metrics are automatically collected

## Integration with Mahavishnu Observability

The LlamaIndex adapter integrates with Mahavishnu's central observability system from `mahavishnu/core/observability.py`:

1. Uses the same OTLP endpoint configuration
1. Shares the same metrics_enabled flag
1. Follows the same graceful degradation pattern
1. Uses compatible span and metric naming conventions

This ensures unified observability across the entire Mahavishnu orchestration platform.
