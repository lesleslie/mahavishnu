# Semantic Memory Search

Natural language queries over ecosystem events using vector embeddings and semantic search.

## Overview

The Semantic Search integration enables powerful natural language queries over ecosystem events from Mahavishnu, Crackerjack, Session-Buddy, Akosha, and Oneiric. Using vector embeddings and FAISS similarity search, you can find relevant events using plain English queries.

## Features

- **Vector Embeddings**: Cross-platform embeddings using fastembed (ONNX Runtime)
- **FAISS Index**: High-performance similarity search (1M events in <100ms)
- **Natural Language Understanding**: Parse queries like "errors from yesterday"
- **Hybrid Search**: Combine semantic and keyword matching
- **Contextual Ranking**: Re-rank results based on recency, severity, preferences
- **Safe Serialization**: JSON-based storage (no pickle security issues)
- **Async/Await**: Non-blocking operations throughout

## Installation

### Basic Installation

```bash
# Install semantic search dependencies
pip install -e ".[semantic-search]"

# For GPU acceleration (optional)
pip install faiss-gpu
```

### Dependencies

- **fastembed** >= 0.2.0: Vector embeddings (ONNX Runtime, works on Intel Macs)
- **faiss-cpu** >= 1.7.4: Fast similarity search (CPU version)
- **numpy**: Array operations

## Quick Start

### Basic Usage

```python
import asyncio
from mahavishnu.integrations.semantic_search import SemanticSearchEngine
from mahavishnu.integrations.event_collector import EcosystemEvent


async def main():
    # Create search engine
    engine = await SemanticSearchEngine.create()

    # Index events
    event = EcosystemEvent(
        source_system="mahavishnu",
        event_type="workflow_complete",
        severity="info",
        data={"workflow_id": "wf-001", "duration": 5.2},
        tags=["workflow", "success"],
    )
    await engine.index_event(event)

    # Natural language search
    results = await engine.semantic_search("workflow errors from yesterday", limit=10)

    for result in results:
        print(f"{result.event.event_type}: {result.score:.3f}")
        print(f"  {result.highlight}")

    # Cleanup
    await engine.close()


asyncio.run(main())
```

### Batch Indexing

```python
# Index multiple events efficiently
events = [event1, event2, event3, ...]
await engine.index_batch(events)

# Check statistics
stats = await engine.get_stats()
print(f"Indexed {stats['indexed_events']} events")
```

## Natural Language Queries

The search engine understands natural language queries:

### Time Ranges

- "errors from yesterday"
- "events from past 24 hours"
- "incidents from last week"
- "workflow failures from past 3 days"

### Severity Levels

- "show me critical incidents"
- "all errors and warnings"
- "debug events from today"

### System-Specific

- "errors in mahavishnu"
- "quality issues from crackerjack"
- "session creation events in session_buddy"

### Event Types

- "workflow failures"
- "quality issues"
- "test failures"
- "security vulnerabilities"

## Advanced Features

### Filtered Search

```python
results = await engine.semantic_search(
    query="workflow",
    filters={
        "severity": "error",
        "source_system": "mahavishnu",
        "tags": ["timeout"],
    },
    limit=20,
)
```

### Contextual Ranking

```python
# Boost recent events
results = await engine.semantic_search(
    "incidents",
    context={"prefer_recent": True},
)

# Boost critical severity
results = await engine.semantic_search(
    "events",
    context={"boost_severity": "critical"},
)

# Prefer specific systems
results = await engine.semantic_search(
    "quality issues",
    context={"preferred_systems": ["mahavishnu", "crackerjack"]},
)
```

### Hybrid Search

```python
# Combine semantic and keyword matching
results = await engine.hybrid_search(
    query="timeout error",
    semantic_weight=0.7,  # 70% semantic, 30% keyword
    limit=10,
)
```

### Find Similar Events

```python
# Find events similar to a reference event
reference_event = events[0]
similar = await engine.find_similar_events(reference_event, limit=5)

for result in similar:
    print(f"{result.event.event_type}: {result.score:.3f}")
```

### Streaming Results

```python
# Stream results as they're found
async for result in engine.stream_search("errors", limit=10):
    print(f"Found: {result.event.event_type}")
    # Process result immediately
```

## Architecture

### Components

#### EventEmbedder

Converts events and queries to vector embeddings:

```python
embedder = await EventEmbedder.create()
embedding = await embedder.embed_event(event)
query_embedding = await embedder.embed_query("search query")
```

**Supported Models:**

- `BAAI/bge-small-en-v1.5` (default): 384 dimensions, fastest
- `BAAI/bge-base-en-v1.5`: 768 dimensions, balanced
- `BAAI/bge-large-en-v1.5`: 1024 dimensions, best quality
- Multilingual models available

#### VectorStore

FAISS-based vector storage:

```python
store = VectorStore(index_dimension=384)
await store.add_vector(embedding, event)
results = await store.search_similar(query_embedding, k=10)
```

**Features:**

- Exact L2 distance search (IndexFlatL2)
- Thread-safe concurrent operations
- JSON persistence (safe serialization)
- Batch operations for performance

#### NaturalLanguageProcessor

Parses natural language queries:

```python
processor = NaturalLanguageProcessor()
intent = await processor.parse_query("errors from yesterday")

print(intent.severity)  # "error"
print(intent.time_range)  # SearchTimeRange(relative_duration="24h")
```

**Recognized Patterns:**

- Time ranges: "yesterday", "past 24 hours", "last week"
- Severities: "errors", "warnings", "critical"
- Systems: "mahavishnu", "crackerjack", etc.
- Event types: "workflow", "incident", "quality"

#### ContextualRanker

Re-ranks results based on context:

```python
ranker = ContextualRanker()
reranked = await ranker.rank_results(
    results,
    context={"prefer_recent": True, "boost_severity": "error"},
)
```

**Ranking Factors:**

- Recency boost (configurable decay)
- Severity boost (error/critical prioritized)
- System preference
- User preferences (stored per-user)

### Performance

| Operation | Target |
|-----------|--------|
| Embed event | <10ms |
| Batch embed (100) | <1s |
| Search 1M events | <100ms |
| Index persistence | <1s |

## Index Persistence

### Save Index

```python
# Save index to disk
await engine.save_index("/path/to/index")

# Creates:
#   /path/to/index/faiss.index    # FAISS vectors
#   /path/to/index/events.json    # Event data (JSON, not pickle!)
#   /path/to/index/metadata.json  # Index metadata
```

### Load Index

```python
# Load existing index
engine = await SemanticSearchEngine.create()
await engine.load_index("/path/to/index")

# Search immediately
results = await engine.semantic_search("query")
```

**Security Note**: Events are stored as JSON using Pydantic's `.model_dump()` - no pickle serialization, safe from arbitrary code execution.

## Configuration

### Embedding Model Selection

```python
# Use faster model (lower quality)
engine = await SemanticSearchEngine.create(
    embedding_model="BAAI/bge-small-en-v1.5"
)

# Use balanced model
engine = await SemanticSearchEngine.create(
    embedding_model="BAAI/bge-base-en-v1.5"
)

# Use best quality model
engine = await SemanticSearchEngine.create(
    embedding_model="BAAI/bge-large-en-v1.5"
)
```

### Index Dimension

Auto-detected from model, but can be specified:

```python
engine = SemanticSearchEngine(
    embedding_model="BAAI/bge-small-en-v1.5",
    index_dimension=384,  # Optional, auto-detected
)
```

## Integration with Event Collector

```python
from mahavishnu.integrations.event_collector import EventCollector
from mahavishnu.integrations.semantic_search import SemanticSearchEngine


async def setup_integration():
    # Create event collector and search engine
    collector = EventCollector()
    engine = await SemanticSearchEngine.create()

    # Auto-index collected events
    async for event in collector.stream_events():
        await engine.index_event(event)

    # Search across all collected events
    results = await engine.semantic_search("quality issues")
```

## Testing

### Run Tests

```bash
# Unit tests
pytest tests/unit/test_integrations/test_semantic_search.py -v

# With coverage
pytest tests/unit/test_integrations/test_semantic_search.py --cov=mahavishnu/integrations/semantic_search

# Integration tests (requires FAISS)
pytest tests/unit/test_integrations/test_semantic_search.py -m integration
```

### Demo

```bash
# Run comprehensive demo
python examples/semantic_search/demo.py
```

## API Reference

### SemanticSearchEngine

Main search engine class.

#### Methods

- `await create(embedding_model: str)` - Create and initialize engine
- `await initialize()` - Initialize components
- `await index_event(event: EcosystemEvent)` - Index single event
- `await index_batch(events: list[EcosystemEvent])` - Batch index
- `await semantic_search(query, limit, filters, context)` - Semantic search
- `await hybrid_search(query, limit, semantic_weight, filters)` - Hybrid search
- `await find_similar_events(event, limit)` - Find similar events
- `await stream_search(query, limit, filters)` - Stream results
- `await get_stats()` - Get statistics
- `await save_index(path)` - Save to disk
- `await load_index(path)` - Load from disk
- `await close()` - Cleanup resources

### SearchIntent

Parsed search intent from natural language.

#### Fields

- `query: str` - Original query
- `keywords: list[str]` - Extracted keywords
- `event_types: list[str]` - Target event types
- `source_systems: list[str]` - Target systems
- `severity: str | None` - Target severity
- `time_range: SearchTimeRange | None` - Time filter
- `tags: list[str]` - Tag filters

### SemanticSearchResult

Search result with relevance score.

#### Fields

- `event: EcosystemEvent` - Matched event
- `score: float` - Similarity score (0-1)
- `rank: int` - Result rank
- `highlight: str | None` - Highlighted snippet
- `relevance_reason: str | None` - Match explanation

#### Methods

- `to_dict() -> dict` - Convert to dictionary

## Best Practices

### Indexing

1. **Batch index** when possible: `await engine.index_batch(events)`
2. **Index incrementally** for real-time: `await engine.index_event(new_event)`
3. **Save periodically** for persistence: `await engine.save_index(path)`

### Searching

1. **Use natural language** for best results: "workflow errors from yesterday"
2. **Add filters** for precision: `filters={"severity": "error"}`
3. **Use context** for ranking: `context={"prefer_recent": True}`

### Performance

1. **Batch operations** reduce overhead
2. **Stream results** for large result sets
3. **Tune semantic_weight** for hybrid search (0.5-0.9 typical)

### Security

1. **JSON serialization** is safe (no pickle)
2. **Validate inputs** with Pydantic models
3. **Use filters** to limit result access

## Troubleshooting

### FAISS Import Error

```bash
# Install FAISS
pip install faiss-cpu

# For GPU support
pip install faiss-gpu
```

### fastembed Import Error

```bash
# Install fastembed
pip install fastembed>=0.2.0
```

### Slow First Query

First query is slower due to model loading. Subsequent queries are fast.

### Poor Search Results

- Try more specific queries
- Use hybrid search: `await engine.hybrid_search()`
- Add filters to narrow results
- Check event data quality

## Performance Tuning

### Embedding Model

| Model | Dimension | Speed | Quality |
|-------|-----------|-------|---------|
| bge-small | 384 | Fastest | Good |
| bge-base | 768 | Balanced | Better |
| bge-large | 1024 | Slower | Best |

### Search Performance

- **Batch size**: 100-1000 events per batch
- **Index size**: FAISS handles millions efficiently
- **Query latency**: <100ms for 1M events

### Memory Usage

- **Per event**: ~1KB (event + 384-dim embedding)
- **1M events**: ~1GB RAM
- **Disk**: Similar to RAM (JSON + FAISS index)

## Examples

See `examples/semantic_search/demo.py` for comprehensive examples including:

- Basic search
- Natural language queries
- Filtered search
- Similar events
- Hybrid search
- Contextual ranking
- Streaming results
- Statistics

## Contributing

When contributing to semantic search:

1. **Add tests** for new features
2. **Update documentation** with examples
3. **Benchmark performance** for changes
4. **Security review** for serialization
5. **Type hints** required

## License

MIT License - See LICENSE file for details
