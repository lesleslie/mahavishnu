# Semantic Search - Quick Reference

## Installation

```bash
pip install -e ".[semantic-search]"
```

## Basic Usage

```python
from mahavishnu.integrations.semantic_search import SemanticSearchEngine

# Create engine
engine = await SemanticSearchEngine.create()

# Index event
await engine.index_event(event)

# Search
results = await engine.semantic_search("workflow errors", limit=10)

# Cleanup
await engine.close()
```

## Query Examples

| Natural Language | Parsed Intent |
|-----------------|---------------|
| "errors from yesterday" | severity=error, time=24h |
| "critical incidents" | severity=critical |
| "workflow failures in mahavishnu" | type=workflow, system=mahavishnu |
| "quality issues from last week" | type=quality, time=7d |

## API Methods

```python
# Indexing
await engine.index_event(event)
await engine.index_batch(events)

# Searching
await engine.semantic_search(query, limit, filters, context)
await engine.hybrid_search(query, semantic_weight=0.7)
await engine.find_similar_events(event, limit)

# Streaming
async for result in engine.stream_search(query):
    process(result)

# Persistence
await engine.save_index("/path/to/index")
await engine.load_index("/path/to/index")

# Stats
stats = await engine.get_stats()
```

## Filters

```python
filters = {
    "severity": "error",
    "source_system": "mahavishnu",
    "event_type": "workflow",
    "tags": ["timeout"],
}
```

## Context

```python
context = {
    "prefer_recent": True,
    "boost_severity": "critical",
    "preferred_systems": ["mahavishnu"],
}
```

## Result Object

```python
SemanticSearchResult(
    event=EcosystemEvent,
    score=float,           # 0-1, higher is better
    rank=int,             # 1 = best match
    highlight=str,        # Matched snippet
    relevance_reason=str  # Why matched
)
```

## Demo & Tests

```bash
# Run demo
python examples/semantic_search/demo.py

# Run tests
pytest tests/unit/test_integrations/test_semantic_search.py -v
```

## Performance

| Operation | Time |
|-----------|------|
| Embed event | <10ms |
| Search 1M | <100ms |
| Save/Load | <1s |

## Files

- `mahavishnu/integrations/semantic_search.py` - Implementation
- `docs/SEMANTIC_SEARCH.md` - Full docs
- `examples/semantic_search/demo.py` - Demo
- `tests/unit/test_integrations/test_semantic_search.py` - Tests
