# Semantic Memory Search CLI

User-friendly natural language interface for searching events using semantic similarity, vector embeddings, and hybrid search capabilities.

## Overview

The Semantic Search CLI provides:

- **Natural Language Queries**: Search using plain English
- **Semantic Similarity**: Find conceptually similar events
- **Hybrid Search**: Combine semantic + keyword filtering
- **Faceted Search**: Filter by system, severity, event type
- **Timeline Search**: Date range queries
- **Clustering**: Group similar results
- **Multiple Output Formats**: Table, JSON, Markdown, HTML
- **Export Capabilities**: Save reports to files

## Installation

The semantic search CLI is included with Mahavishnu. No additional dependencies required.

```bash
# Verify installation
mahavishnu search --help
```

## Quick Start

### Natural Language Search

```bash
# Find errors from yesterday
mahavishnu search "Show me all errors from yesterday"

# Find critical incidents in mahavishnu from last week
mahavishnu search "Critical incidents in mahavishnu from last week"

# Find workflow failures related to database
mahavishnu search "Workflow failures related to database"

# Find quality issues in crackerjack
mahavishnu search "All quality issues in crackerjack"
```

### Hybrid Search (Semantic + Keyword)

```bash
# Combine semantic search with filters
mahavishnu search --query "database errors" --system mahavishnu --last-hours 24

# Find events with specific severity
mahavishnu search --query "authentication" --severity critical --last-days 7

# Filter by event type
mahavishnu search --query "workflow" --event-type workflow_failed --limit 20
```

### Vector Similarity Search

```bash
# Find events similar to a specific event
mahavishnu search similar INC-20250205-0001 --limit 20

# Find similar events with threshold
mahavishnu search similar "ERR-ABC-123" --threshold 0.7 --limit 10
```

### Faceted Search

```bash
# Search by system and severity
mahavishnu search --system mahavishnu --severity critical --last-days 7

# Search by event type
mahavishnu search --event-type workflow_failed --last-hours 24

# Combine multiple filters
mahavishnu search --system crackerjack --severity error --event-type quality_issue --last-days 30
```

### Timeline Search

```bash
# Search specific date range
mahavishnu search --query "errors" --from "2025-02-01" --to "2025-02-07"

# Search last N hours/days
mahavishnu search --query "incidents" --last-hours 48
mahavishnu search --query "failures" --last-days 14
```

### Clustering

```bash
# Cluster similar results
mahavishnu search cluster "database errors" --threshold 0.8

# View clusters with different similarity thresholds
mahavishnu search cluster "authentication issues" --threshold 0.7 --limit 50
```

### Export Results

```bash
# Export to JSON
mahavishnu search --query "incidents" --output json --export results.json

# Export to Markdown report
mahavishnu search --query "errors" --output markdown --export report.md

# Export to HTML with interactive results
mahavishnu search --query "workflow failures" --output html --export report.html
```

## CLI Commands

### `mahavishnu search search`

Main search command with natural language or semantic similarity.

```bash
mahavishnu search search [OPTIONS] QUERY
```

**Arguments:**

- `QUERY`: Natural language search query

**Options:**

- `-s, --system TEXT`: Filter by source system (mahavishnu, crackerjack, etc.)
- `--severity TEXT`: Filter by severity (debug, info, warning, error, critical)
- `-t, --event-type TEXT`: Filter by event type
- `-h, --last-hours INT`: Last N hours
- `-d, --last-days INT`: Last N days
- `--from ISO_DATE`: Start date (ISO format)
- `--to ISO_DATE`: End date (ISO format)
- `-n, --limit INT`: Maximum results (default: 20)
- `-o, --output FORMAT`: Output format (table, json, markdown, html)
- `-e, --export PATH`: Export to file
- `--vector-weight FLOAT`: Vector search weight 0-1 (default: 0.6)
- `--graph-weight FLOAT`: Graph search weight 0-1 (default: 0.4)

**Examples:**

```bash
# Natural language with filters
mahavishnu search search "errors" --system mahavishnu --last-hours 24

# Export to markdown
mahavishnu search search "critical incidents" --output markdown --export incidents.md

# Adjust search weights
mahavishnu search search "authentication" --vector-weight 0.8 --graph-weight 0.2
```

### `mahavishnu search similar`

Find events similar to a given event ID.

```bash
mahavishnu search similar [OPTIONS] EVENT_ID
```

**Arguments:**

- `EVENT_ID`: Event ID to find similar events for

**Options:**

- `-n, --limit INT`: Maximum results (default: 10)
- `-t, --threshold FLOAT`: Minimum similarity (default: 0.5)
- `-o, --output FORMAT`: Output format (table, json)

**Examples:**

```bash
# Find similar events
mahavishnu search similar INC-20250205-0001 --limit 20

# High similarity matches only
mahavishnu search similar "ERR-ABC-123" --threshold 0.8
```

### `mahavishnu search cluster`

Cluster and group similar search results.

```bash
mahavishnu search cluster [OPTIONS] QUERY
```

**Arguments:**

- `QUERY`: Search query

**Options:**

- `-t, --threshold FLOAT`: Similarity threshold for clustering (default: 0.7)
- `-n, --limit INT`: Results to cluster (default: 50)

**Examples:**

```bash
# Cluster database error results
mahavishnu search cluster "database errors" --threshold 0.8

# Cluster with more results
mahavishnu search cluster "authentication failures" --limit 100 --threshold 0.6
```

### `mahavishnu search timeline`

Search events across a timeline with interval buckets.

```bash
mahavishnu search timeline [OPTIONS] QUERY
```

**Arguments:**

- `QUERY`: Search query

**Options:**

- `-f, --from ISO_DATE`: Start date (required)
- `-t, --to ISO_DATE`: End date (required)
- `-i, --interval TEXT`: Time interval (1h, 1d, 1w) (default: 1d)
- `-n, --limit INT`: Results per interval (default: 100)

**Examples:**

```bash
# Daily timeline of errors
mahavishnu search timeline "errors" --from "2025-02-01" --to "2025-02-07" --interval 1d

# Hourly timeline for specific day
mahavishnu search timeline "incidents" --from "2025-02-05T00:00" --to "2025-02-05T23:59" --interval 1h
```

## Natural Language Understanding

The CLI parses natural language queries to extract filters automatically.

### Supported Patterns

**Severity Keywords:**

- "critical", "error", "errors", "warning", "warnings", "info", "debug"

**Time Expressions:**

- "today", "yesterday"
- "last hour", "last hours"
- "last day", "last days"
- "last week", "last weeks"
- "last month", "last months"

**System Names:**

- "mahavishnu" or "vishnu"
- "crackerjack" or "jack"
- "session" or "buddy" (for session_buddy)
- "akosha"
- "oneiric"

### Examples

```bash
# Automatically extracts: severity=error, time=yesterday
mahavishnu search "Show me errors from yesterday"

# Automatically extracts: severity=critical, system=mahavishnu, time=last week
mahavishnu search "Critical incidents in mahavishnu from last week"

# Automatically extracts: system=crackerjack
mahavishnu search "All quality issues in crackerjack"
```

## Output Formats

### Table (Default)

Rich formatted tables with color-coded similarity scores.

```bash
mahavishnu search "errors" --output table
```

**Output:**
```
┏━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Rank  ┃ Score   ┃ Vector  ┃ Graph   ┃ Node ID                      ┃ Content                         ┃
┡━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1     │ 0.92    │ 0.88    │ 0.95    │ evt_abc123                   │ Database connection failed...     │
│ 2     │ 0.85    │ 0.82    │ 0.89    │ evt_def456                   │ Query timeout exceeded           │
└───────┴────────┴────────┴────────┴──────────────────────────────┴─────────────────────────────────┘
```

### JSON

Machine-readable format with embeddings and metadata.

```bash
mahavishnu search "errors" --output json --export results.json
```

**Output:**
```json
[
  {
    "rank": 1,
    "node_id": "evt_abc123",
    "content": "Database connection failed...",
    "scores": {
      "hybrid": 0.92,
      "vector": 0.88,
      "graph": 0.95
    },
    "metadata": {
      "severity": "error",
      "source_system": "mahavishnu"
    }
  }
]
```

### Markdown

Human-readable reports for documentation.

```bash
mahavishnu search "incidents" --output markdown --export report.md
```

**Output:**
```markdown
# Semantic Search Results

**Query:** incidents
**Results:** 15
**Timestamp:** 2025-02-05T15:30:00Z

---

## Result 1 (Score: 0.92)

**Node ID:** `evt_abc123`

**Scores:**
- Hybrid: 0.920
- Vector: 0.880
- Graph: 0.950

**Content:**
```
Database connection failed
```
```

### HTML

Interactive reports with highlighting and charts.

```bash
mahavishnu search "failures" --output html --export report.html
```

**Features:**
- Responsive layout
- Color-coded scores
- Collapsible metadata
- Searchable content
- Printable format

## Python API

### SemanticSearchBuilder

Fluent query builder for programmatic access.

```python
from mahavishnu.integrations.semantic_search_cli import SemanticSearchBuilder
from mahavishnu.search.hybrid_search import HybridSearchEngine
from mahavishnu.search.embeddings import MockEmbeddingClient

# Create search engine
embedding_client = MockEmbeddingClient()
search_engine = HybridSearchEngine(embedding_client=embedding_client)

# Build query
builder = SemanticSearchBuilder(search_engine)
results = await builder \
    .natural_language("database errors from last week") \
    .system("mahavishnu") \
    .severity("error") \
    .set_limit(20) \
    .execute()

# Process results
for result in results:
    print(f"Rank {result.rank}: {result.content[:50]}...")
    print(f"  Score: {result.hybrid_score:.3f}")
    print(f"  Vector: {result.vector_score:.3f}, Graph: {result.graph_score:.3f}")
```

### semantic_search()

Convenience function for quick searches.

```python
from mahavishnu.integrations.semantic_search_cli import semantic_search

# Simple search
results = await semantic_search("authentication issues")

# With filters
results = await semantic_search(
    "workflow failures",
    system="mahavishnu",
    severity="error",
    last_days=7,
    limit=50,
)
```

### NLQueryParser

Parse natural language queries programmatically.

```python
from mahavishnu.integrations.semantic_search_cli import NLQueryParser

parser = NLQueryParser()

query = "Show me critical errors in mahavishnu from last week"
cleaned_query, filters = parser.parse(query)

print(f"Cleaned: {cleaned_query}")
print(f"Filters: {filters}")
# Output:
# Cleaned: show me critical errors in from
# Filters: {
#   'severity': 'critical',
#   'source_system': 'mahavishnu',
#   'start_time': datetime(2025, 1, 29),
#   'end_time': datetime(2025, 2, 5)
# }
```

## Architecture

### Integration Points

**HybridSearchEngine**: Combines vector similarity with graph traversal

**EmbeddingClient**: Vector embeddings for semantic search
- MockEmbeddingClient (default): Hash-based embeddings
- Can be replaced with OpenAI, Cohere, or local models

**GraphClient**: Knowledge graph traversal
- MockGraphClient (default): In-memory graph
- Can integrate with Session-Buddy knowledge graph

**EventCollector**: Event storage and retrieval
- Stores events with embeddings
- Provides faceted search capabilities

### Search Flow

1. **Query Parsing**: Extract filters from natural language
2. **Vector Search**: Find semantically similar events
3. **Graph Traversal**: Explore related events
4. **Hybrid Ranking**: Combine vector + graph scores
5. **Filtering**: Apply metadata filters
6. **Formatting**: Output in requested format

### Scoring

**Hybrid Score**: Weighted combination of vector and graph scores

```
hybrid_score = (vector_score * vector_weight) + (graph_score * graph_weight)
```

**Vector Score**: Cosine similarity of query and document embeddings

**Graph Score**: Relevance based on graph traversal distance

## Configuration

### Weights

Adjust the balance between semantic and graph search:

```bash
# Favor semantic similarity
mahavishnu search "authentication" --vector-weight 0.8 --graph-weight 0.2

# Favor graph relationships
mahavishnu search "database" --vector-weight 0.3 --graph-weight 0.7
```

### Thresholds

Control minimum similarity scores:

```bash
# Only high-confidence matches
mahavishnu search similar "EVENT-ID" --threshold 0.8

# Include more results
mahavishnu search similar "EVENT-ID" --threshold 0.3
```

## Tips and Tricks

### 1. Start with Natural Language

```bash
# Good - Natural language
mahavishnu search "database errors from yesterday"

# Also Good - More specific
mahavishnu search "PostgreSQL connection failures in production"
```

### 2. Use Filters for Precision

```bash
# Combine semantic + filters
mahavishnu search --query "workflow" --system mahavishnu --severity error --last-hours 24
```

### 3. Export for Analysis

```bash
# Export to JSON for further processing
mahavishnu search "incidents" --output json --export incidents.json

# Export to Markdown for documentation
mahavishnu search "errors" --output markdown --export errors.md
```

### 4. Cluster for Patterns

```bash
# Discover patterns
mahavishnu search cluster "authentication issues" --threshold 0.7
```

### 5. Adjust Weights by Use Case

```bash
# Semantic similarity (conceptual matching)
mahavishnu search "database" --vector-weight 0.9 --graph-weight 0.1

# Graph traversal (relationship discovery)
mahavishnu search "database" --vector-weight 0.2 --graph-weight 0.8

# Balanced (default)
mahavishnu search "database" --vector-weight 0.6 --graph-weight 0.4
```

## Troubleshooting

### No Results Found

**Problem**: Search returns empty results

**Solutions**:
- Lower the threshold: `--threshold 0.3`
- Increase limit: `--limit 100`
- Broaden query: Use more general terms
- Check time range: Ensure `--last-hours` or `--last-days` is appropriate

### Poor Relevance

**Problem**: Results don't match query intent

**Solutions**:
- Adjust weights: `--vector-weight 0.8` for semantic focus
- Be more specific: Use detailed natural language queries
- Add filters: `--system`, `--severity`, `--event-type`
- Try different query phrasing

### Slow Performance

**Problem**: Search takes too long

**Solutions**:
- Reduce limit: `--limit 20`
- Use time filters: `--last-hours 24`
- Disable graph search: `--graph-weight 0.0`
- Cache results: Subsequent searches are faster

## Examples by Use Case

### Incident Investigation

```bash
# Find similar past incidents
mahavishnu search similar "INC-20250205-0001" --limit 20 --threshold 0.7

# Timeline of related errors
mahavishnu search "authentication failures" --last-days 7 --output markdown --export incident-report.md
```

### Quality Analysis

```bash
# Find quality issues
mahavishnu search --query "quality issues" --system crackerjack --last-days 30

# Cluster by pattern
mahavishnu search cluster "test failures" --threshold 0.8 --limit 50
```

### Performance Debugging

```bash
# Find slow operations
mahavishnu search "slow queries" --event-type query_slow --last-hours 24

# Database issues
mahavishnu search "database" --system mahavishnu --severity error --last-days 7
```

### Security Audit

```bash
# Critical security events
mahavishnu search --query "authentication" --severity critical --last-days 30

# Export for reporting
mahavishnu search "security incidents" --output html --export security-report.html
```

## Integration with EventCollector

The semantic search CLI integrates with the EventCollector for comprehensive event indexing:

```python
from mahavishnu.integrations.event_collector import EventCollector
from mahavishnu.integrations.semantic_search_cli import semantic_search

# Events are automatically indexed with embeddings
collector = EventCollector()
await collector.start()

# Search across all indexed events
results = await semantic_search(
    "database errors",
    last_days=7,
    limit=50,
)
```

## Future Enhancements

Planned features for future releases:

- [ ] Multi-language support (Spanish, French, German)
- [ ] Query suggestions and autocomplete
- [ ] Saved searches and alerts
- [ ] Advanced aggregations and analytics
- [ ] Real-time search streaming
- [ ] Integration with external search engines (Elasticsearch, OpenSearch)
- [ ] Custom embedding model support
- [ ] Query explanation and debugging

## See Also

- [Event Query CLI](./EVENT_QUERY_GUIDE.md) - Structured event queries
- [Incident Management](./INCIDENT_MANAGEMENT_README.md) - Incident tracking
- [Hybrid Search Architecture](./HYBRID_SEARCH_ARCHITECTURE.md) - Technical details
