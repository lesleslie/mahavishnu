# Data Ingestion Pipelines

## Content Ingestion

Ingest web content, blogs, and books into the knowledge ecosystem.

**Ingester**: `mahavishnu/ingesters/content_ingester.py`

**Supported Types**:

- Webpages (delegated to `web_reader` MCP server on port 8699)
- Blogs (RSS/Atom feeds)
- Books (PDF via pypdf, EPUB via ebooklib)

**Quality Evaluation**: `mahavishnu/ingesters/quality_evaluator.py`

- Scores for readability, technical depth, completeness
- Configurable quality thresholds

### Usage

```bash
mahavishnu ingest web --url "https://example.com"
mahavishnu ingest blog --url "https://blog.example.com/post"
mahavishnu ingest book --path ~/Documents/book.pdf
mahavishnu quality evaluate --content-id <id>
```

Configuration in `settings/mahavishnu.yaml`:

```yaml
ingestion:
  enabled: true
  quality_threshold: 0.7
```

## OpenTelemetry Trace Ingestion

Ingest and semantically search OpenTelemetry traces.

**Ingester**: `mahavishnu/ingesters/otel_ingester.py`

**Storage Options**:

- **DuckDB** — Zero-dependency, in-memory or file-based
- **PostgreSQL + pgvector** — Production, persistent, vector similarity

Embeds trace spans with fastembed for semantic search.

### Usage

```python
from mahavishnu.ingesters import OtelIngester

otel = OtelIngester()
await otel.initialize(storage_type="duckdb")  # or "postgresql"
await otel.ingest_trace(trace_data)
results = await otel.search_traces("error handling")
await otel.close()
```

See `examples/otel_ingester_example.py` for runnable example.
