# Oneiric OpenTelemetry Storage with Semantic Search

## Overview

Oneiric's OTelStorageAdapter provides intelligent storage and semantic search capabilities for OpenTelemetry traces using PostgreSQL + pgvector. This enables natural language queries over distributed traces, making observability data more accessible and actionable.

### Key Features

- **Semantic Search**: Find traces by meaning, not just exact matches
- **Vector Embeddings**: Store trace summaries as dense vectors for similarity search
- **PostgreSQL + pgvector**: Battle-tested database with vector similarity search
- **Async Operations**: High-performance async I/O with asyncpg
- **Batch Writes**: Optimized batch insertion for high-throughput scenarios
- **Resilience**: Circuit breakers, retries, and connection pooling
- **Oneiric Integration**: Seamless configuration with Mahavishnu settings

### Architecture

```
┌─────────────────┐
│  OpenTelemetry  │
│     Traces      │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   OTelStorageAdapter            │
│   - Extract trace summaries     │
│   - Generate embeddings         │
│   - Store with metadata         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   PostgreSQL + pgvector         │
│   - traces table                │
│   - embedding vector column     │
│   - Similarity search index     │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   Semantic Search               │
│   - Natural language queries    │
│   - Cosine similarity           │
│   - Ranked results              │
└─────────────────────────────────┘
```

## Prerequisites

### 1. PostgreSQL Installation

**macOS (Homebrew)**:
```bash
brew install postgresql@16
brew services start postgresql@16
```

**Ubuntu/Debian**:
```bash
sudo apt update
sudo apt install postgresql-16 postgresql-contrib-16
sudo systemctl start postgresql
```

**Docker**:
```bash
docker run -d \
  --name postgres-otel \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=otel_traces \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 2. Install pgvector Extension

```bash
# Clone pgvector repository
git clone --branch v0.2.5 https://github.com/pgvector/pgvector.git
cd pgvector

# Build and install
make
sudo make install

# Enable extension in PostgreSQL
psql -U postgres -c "CREATE EXTENSION vector;"
```

**Docker (pgvector/pgvector image includes extension)**:
No additional setup needed.

### 3. Create Database

```bash
# Create database and user
psql -U postgres <<EOF
CREATE DATABASE otel_traces;
CREATE USER otel_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE otel_traces TO otel_user;
\c otel_traces
GRANT ALL ON SCHEMA public TO otel_user;
EOF
```

### 4. Python Dependencies

```bash
# Install Mahavishnu with OTel storage dependencies
cd /path/to/mahavishnu
uv sync

# Or install manually
pip install asyncpg>=0.29.0 pgvector>=0.2.5 sentence-transformers>=2.2.2
```

## Database Schema

Create the traces table with vector column:

```sql
-- Connect to your database
\c otel_traces

-- Create traces table
CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    trace_state TEXT,
    name TEXT NOT NULL,
    kind TEXT,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    status TEXT,
    attributes JSONB,
    events JSONB,
    links JSONB,
    summary TEXT,
    embedding vector(384),  -- Dimension matches embedding model
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_traces_trace_id ON traces(trace_id);
CREATE INDEX idx_traces_start_time ON traces(start_time DESC);
CREATE INDEX idx_traces_name ON traces(name);
CREATE INDEX idx_traces_embedding ON traces USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);  -- Adjust lists based on data size

-- Create indexes for common queries
CREATE INDEX idx_traces_status ON traces(status) WHERE status IS NOT NULL;
CREATE INDEX idx_traces_attributes ON traces USING GIN (attributes);
CREATE INDEX idx_traces_events ON traces USING GIN (events);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_traces_updated_at
    BEFORE UPDATE ON traces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

**Adjust IVFFlat `lists` parameter**:
- `lists = sqrt(num_rows)` is a good starting point
- For 1M rows: `lists = 1000`
- For 100K rows: `lists = 300`
- For 10K rows: `lists = 100`

## Configuration

### Mahavishnu Configuration

Update `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`:

```yaml
# OpenTelemetry trace storage with semantic search
otel_storage:
  enabled: true  # Set to true after PostgreSQL setup
  connection_string: "postgresql://otel_user:password@localhost:5432/otel_traces"
  embedding_model: "all-MiniLM-L6-v2"  # Sentence transformer model
  embedding_dimension: 384  # Vector dimension (must match model)
  cache_size: 1000  # Max embeddings in memory cache
  similarity_threshold: 0.85  # Min similarity for search (0.0-1.0)
  batch_size: 100  # Traces per batch write
  batch_interval_seconds: 5  # Seconds between batch flushes
  max_retries: 3  # Retry attempts for failed operations
  circuit_breaker_threshold: 5  # Failures before circuit breaker opens
```

### Local Configuration (Optional)

Create `/Users/les/Projects/mahavishnu/settings/local.yaml` (gitignored):

```yaml
otel_storage:
  connection_string: "postgresql://user:pass@localhost:5432/otel_traces"
  enabled: true
```

### Environment Variables

Override configuration with environment variables:

```bash
# Enable OTel storage
export MAHAVISHNU_OTEL_STORAGE__ENABLED=true

# PostgreSQL connection
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://user:pass@host:5432/db"

# Embedding settings
export MAHAVISHNU_OTEL_STORAGE__EMBEDDING_MODEL="all-MiniLM-L6-v2"
export MAHAVISHNU_OTEL_STORAGE__EMBEDDING_DIMENSION=384

# Performance tuning
export MAHAVISHNU_OTEL_STORAGE__BATCH_SIZE=100
export MAHAVISHNU_OTEL_STORAGE__CACHE_SIZE=1000
```

## Configuration Options

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `enabled` | bool | `false` | - | Enable OTel trace storage |
| `connection_string` | str | `postgresql://postgres:password@localhost:5432/otel_traces` | - | PostgreSQL connection string |
| `embedding_model` | str | `all-MiniLM-L6-v2` | - | Sentence transformer model name |
| `embedding_dimension` | int | `384` | 128-1024 | Vector dimension (must match model) |
| `cache_size` | int | `1000` | 100-10000 | Max embeddings in memory cache |
| `similarity_threshold` | float | `0.85` | 0.0-1.0 | Minimum similarity for search results |
| `batch_size` | int | `100` | 10-1000 | Traces per batch write |
| `batch_interval_seconds` | int | `5` | 1-60 | Seconds between batch flushes |
| `max_retries` | int | `3` | 1-10 | Retry attempts for failed operations |
| `circuit_breaker_threshold` | int | `5` | 3-20 | Failures before circuit breaker opens |

### Embedding Models

**Recommended Models**:

| Model | Dimensions | Speed | Accuracy | Use Case |
|-------|------------|-------|----------|----------|
| `all-MiniLM-L6-v2` | 384 | Fast | Good | Default, balanced |
| `all-mpnet-base-v2` | 768 | Medium | Excellent | High accuracy |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | Fast | Good | Multi-language |

**Model Selection**:
- **Speed matters**: Use `all-MiniLM-L6-v2` (384 dims)
- **Accuracy matters**: Use `all-mpnet-base-v2` (768 dims)
- **Multi-language**: Use `paraphrase-multilingual-MiniLM-L12-v2`

## Usage Examples

### Basic Usage

```python
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings

# Load configuration
settings = MahavishnuSettings()

# Create OTel storage settings
otel_settings = OTelStorageSettings(
    connection_string=settings.otel_storage_connection_string,
    embedding_model=settings.otel_storage_embedding_model,
    embedding_dimension=settings.otel_storage_embedding_dimension,
)

# Initialize adapter
adapter = OTelStorageAdapter(otel_settings)
```

### Store Traces

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from oneiric.adapters.observability import OTelStorageExporter

# Setup OpenTelemetry
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

# Create OTel storage exporter
exporter = OTelStorageAdapter(otel_settings)
trace.get_tracer_provider().add_span_processor(
    SimpleSpanProcessor(exporter)
)

# Create spans (automatically stored with semantic embeddings)
with tracer.start_as_current_span("example_operation") as span:
    span.set_attribute("user.id", "12345")
    span.set_attribute("operation.type", "query")
    # Trace is automatically stored with embedding
```

### Semantic Search

```python
# Search for traces by meaning
results = await adapter.search_traces(
    query="database connection timeout errors",
    limit=10,
    threshold=0.85
)

for result in results:
    print(f"Trace ID: {result['trace_id']}")
    print(f"Name: {result['name']}")
    print(f"Similarity: {result['similarity']:.3f}")
    print(f"Summary: {result['summary']}")
    print()
```

### Retrieve Trace by ID

```python
# Get specific trace
trace_data = await adapter.get_trace(trace_id="abc123")

print(f"Trace: {trace_data['name']}")
print(f"Duration: {trace_data['duration_ms']}ms")
print(f"Attributes: {trace_data['attributes']}")
```

### Batch Operations

```python
# Store multiple traces in batch
traces = [
    {"trace_id": "1", "name": "operation_a", "summary": "...", ...},
    {"trace_id": "2", "name": "operation_b", "summary": "...", ...},
]

await adapter.batch_store(traces)

# Force flush buffer
await adapter.flush()
```

### Health Check

```python
# Check adapter health
health = await adapter.health_check()

if health["healthy"]:
    print(f"Database connection: OK")
    print(f"Total traces: {health['total_traces']}")
    print(f"Embedding cache size: {health['cache_size']}")
else:
    print(f"Database connection: FAILED")
    print(f"Error: {health['error']}")
```

## Integration with OpenTelemetry SDK

### Automatic Trace Export

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from oneiric.adapters.observability import OTelStorageExporter

# Configure OTel to export traces to OTelStorageAdapter
provider = TracerProvider()
exporter = OTelStorageExporter(settings=otel_settings)
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)

trace.set_tracer_provider(provider)

# Use tracer normally - traces automatically stored with embeddings
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("my_operation"):
    # Your code here
    pass
```

### Manual Trace Storage

```python
from opentelemetry.trace import SpanContext
from opentelemetry.sdk.trace import ReadableSpan

# Create span manually
span_context = SpanContext(
    trace_id=0x1234567890abcdef,
    span_id=0xabcdef1234567890,
    is_remote=False
)

# Store trace with custom summary
await adapter.store_trace(
    trace_id=str(span_context.trace_id),
    span_id=str(span_context.span_id),
    name="custom_operation",
    start_time=datetime.now(timezone.utc),
    end_time=datetime.now(timezone.utc),
    attributes={"key": "value"},
    summary="Custom operation summary for semantic search"
)
```

## Migration from Other Backends

### From Jaeger

```python
# Export traces from Jaeger
import requests

jaeger_url = "http://localhost:16686"
traces = requests.get(f"{jaeger_url}/api/traces?service=my-service").json()

# Migrate to OTelStorageAdapter
for trace in traces["data"]:
    await adapter.store_trace(
        trace_id=trace["traceID"],
        spans=[convert_jaeger_span(span) for span in trace["spans"]],
        summary=generate_summary(trace)
    )
```

### From Tempo

```python
# Query Tempo API
import requests

tempo_url = "http://localhost:3100"
response = requests.get(f"{tempo_url}/api/search", params={
    "min": 0,
    "max": time.time(),
    "query": "{service.name='my-service'}"
})

# Migrate traces
for trace in response.json()["traces"]:
    await adapter.store_trace(
        trace_id=trace["traceID"],
        # ... convert Tempo trace format
    )
```

## Performance Tuning

### PostgreSQL Configuration

Update `postgresql.conf` for optimal performance:

```conf
# Memory settings (adjust based on available RAM)
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
work_mem = 16MB

# Query optimization
random_page_cost = 1.1  # For SSD storage
effective_io_concurrency = 200

# Connection settings
max_connections = 100
pool_size = 20

# WAL settings
wal_buffers = 16MB
checkpoint_completion_target = 0.9
```

### Batch Size Tuning

```yaml
otel_storage:
  # High-throughput scenario
  batch_size: 500  # Increase for bulk ingestion
  batch_interval_seconds: 10  # Longer interval for larger batches

  # Low-latency scenario
  batch_size: 50  # Smaller batches for faster writes
  batch_interval_seconds: 1  # Flush frequently
```

### Cache Configuration

```yaml
otel_storage:
  cache_size: 5000  # Increase for frequently accessed traces
```

## Testing and Validation

### Unit Tests

```bash
# Run OTel storage tests
pytest tests/unit/test_otel_storage.py -v
```

### Integration Tests

```bash
# Run integration tests (requires PostgreSQL)
pytest tests/integration/test_otel_storage.py -v -m integration
```

### Manual Testing

```python
# Test database connection
python -c "
from mahavishnu.core.config import MahavishnuSettings
from oneiric.adapters.observability import OTelStorageAdapter, OTelStorageSettings
import asyncio

async def test():
    settings = MahavishnuSettings()
    otel_settings = OTelStorageSettings(
        connection_string=settings.otel_storage_connection_string
    )
    adapter = OTelStorageAdapter(otel_settings)
    health = await adapter.health_check()
    print(f'Healthy: {health[\"healthy\"]}')

asyncio.run(test())
"
```

### Load Testing

```bash
# Install dependencies
pip install locust

# Run load test
locust -f tests/load/test_otel_storage.py --host=http://localhost:5432
```

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to PostgreSQL

**Solution**:
```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Check connection string
psql "postgresql://user:pass@localhost:5432/otel_traces"

# Check firewall rules
sudo ufw allow 5432/tcp
```

### pgvector Not Found

**Problem**: ERROR: type "vector" does not exist

**Solution**:
```sql
-- Install pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify installation
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### Embedding Dimension Mismatch

**Problem**: vector must have 384 dimensions

**Solution**:
```yaml
# Match embedding dimension to model
otel_storage:
  embedding_model: "all-MiniLM-L6-v2"  # 384 dimensions
  embedding_dimension: 384  # Must match model
```

### Slow Search Performance

**Problem**: Semantic search is slow

**Solution**:
```sql
-- Recreate index with optimized parameters
DROP INDEX idx_traces_embedding;
CREATE INDEX idx_traces_embedding ON traces USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 300);  -- Adjust based on row count

-- Analyze table for query optimization
ANALYZE traces;
```

## Best Practices

1. **Connection Pooling**: Use connection pools to avoid connection overhead
2. **Batch Writes**: Use batch operations for high-throughput scenarios
3. **Index Maintenance**: Rebuild IVFFlat indexes periodically for optimal performance
4. **Monitoring**: Track database metrics (connections, query times, storage)
5. **Security**: Use environment variables for sensitive credentials
6. **Backups**: Implement regular PostgreSQL backups
7. **Schema Validation**: Use Pydantic models to validate trace data
8. **Error Handling**: Implement proper error handling and retry logic

## References

- [Oneiric Documentation](https://github.com/oneiric/oneiric)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Sentence Transformers](https://www.sbert.net/)

## Contributing

To contribute improvements to OTelStorageAdapter:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - See LICENSE file for details
