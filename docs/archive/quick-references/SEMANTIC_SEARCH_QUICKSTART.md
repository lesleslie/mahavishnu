# Semantic Memory Search - Quick Start Guide

**Get started with semantic search in 10 minutes.**

---

## Table of Contents

1. [Installation](#installation)
2. [5-Minute Setup](#5-minute-setup)
3. [Basic Usage](#basic-usage)
4. [Common Queries](#common-queries)
5. [CLI Examples](#cli-examples)
6. [Performance Tips](#performance-tips)
7. [Next Steps](#next-steps)

---

## Installation

### Requirements

```bash
# Python 3.10+
python --version

# Mahavishnu installed
pip install mahavishnu
```

### Verify Installation

```bash
# Check Mahavishnu is installed
mahavishnu --version

# Check search commands
mahavishnu search --help
```

---

## 5-Minute Setup

### Step 1: Initialize Search Engine (1 minute)

```python
from mahavishnu.search.hybrid_search import HybridSearchEngine
from mahavishnu.search.embeddings import MockEmbeddingClient
from mahavishnu.search.graph import MockGraphClient

# Create clients
embedding_client = MockEmbeddingClient()
graph_client = MockGraphClient()

# Initialize search engine
engine = HybridSearchEngine(
    embedding_client=embedding_client,
    graph_client=graph_client,
    cache_enabled=True,
)

print("✓ Search engine initialized")
```

### Step 2: Index Documents (2 minutes)

```python
# Index your documents
documents = {
    "doc1": "User authentication failed due to invalid credentials",
    "doc2": "Database connection timeout error in production",
    "doc3": "Security vulnerability detected in authentication module",
    "doc4": "Workflow completed successfully for user registration",
    "doc5": "API rate limiting exceeded for client IP address",
}

for doc_id, content in documents.items():
    await embedding_client.index_document(doc_id, content)

print(f"✓ Indexed {len(documents)} documents")
```

### Step 3: Search (1 minute)

```python
# Perform semantic search
results = await engine.search("authentication failures")

# Display results
for result in results[:5]:
    print(f"{result.rank}. [{result.hybrid_score:.2f}] {result.content[:60]}...")

print(f"✓ Found {len(results)} results")
```

### Step 4: Advanced Search (1 minute)

```python
from mahavishnu.integrations.semantic_search_cli import SemanticSearchBuilder

# Build complex query
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("database errors") \
    .in_last_days(7) \
    .limit(10) \
    .execute()

print(f"✓ Advanced search complete")
```

---

## Basic Usage

### Simple Search

```python
# Natural language query
results = await engine.search("Show me all authentication errors")

# Semantic similarity
results = await engine.search("database connection timeout")

# Find similar events
results = await engine.search("API rate limiting")
```

### With Parameters

```python
from mahavishnu.search.hybrid_search import HybridSearchParams

# Configure search
params = HybridSearchParams(
    vector_weight=0.7,      # 70% semantic similarity
    graph_weight=0.3,       # 30% graph relationships
    limit=20,               # Top 20 results
    vector_threshold=0.5,   # Minimum 50% similarity
)

results = await engine.search("critical errors", params)
```

### Understanding Results

```python
for result in results:
    print(f"Rank: {result.rank}")
    print(f"Score: {result.hybrid_score:.3f} (vector: {result.vector_score:.3f}, graph: {result.graph_score:.3f})")
    print(f"Content: {result.content}")
    print()
```

---

## Common Queries

### By Time

```python
from datetime import UTC, datetime, timedelta

# Recent errors
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("errors") \
    .in_last_hours(24) \
    .execute()

# Last week
results = await builder \
    .natural_language("incidents") \
    .in_last_days(7) \
    .execute()

# Date range
results = await builder \
    .natural_language("events") \
    .from_date("2025-02-01", "2025-02-07") \
    .execute()
```

### By Severity

```python
# Critical only
results = await builder \
    .natural_language("incidents") \
    .severity("critical") \
    .execute()

# Errors and warnings
results = await builder \
    .natural_language("issues") \
    .severity("error") \
    .execute()
```

### By System

```python
# Mahavishnu events
results = await builder \
    .natural_language("workflows") \
    .system("mahavishnu") \
    .execute()

# Crackerjack quality issues
results = await builder \
    .natural_language("code quality") \
    .system("crackerjack") \
    .execute()
```

### Combined Filters

```python
# Complex query
results = await builder \
    .natural_language("authentication failures") \
    .system("mahavishnu") \
    .severity("error") \
    .in_last_days(7) \
    .limit(20) \
    .execute()
```

---

## CLI Examples

### Basic Commands

```bash
# Natural language search
mahavishnu search "Show me errors from yesterday"

# With filters
mahavishnu search "database errors" \
  --system mahavishnu \
  --severity error \
  --last-hours 24

# Export results
mahavishnu search "incidents" \
  --output json \
  --export results.json
```

### Output Formats

```bash
# Table (default)
mahavishnu search "errors" --output table

# JSON
mahavishnu search "errors" --output json

# Markdown report
mahavishnu search "errors" --output markdown --export report.md

# HTML report
mahavishnu search "errors" --output html --export report.html
```

### Advanced CLI

```bash
# Adjust search weights
mahavishnu search "authentication" \
  --vector-weight 0.8 \
  --graph-weight 0.2

# Find similar events
mahavishnu search similar evt-001 --limit 20 --threshold 0.5

# Cluster results
mahavishnu search cluster "database errors" --threshold 0.8

# Timeline search
mahavishnu search timeline "errors" \
  --from "2025-02-01" \
  --to "2025-02-07" \
  --interval 1d
```

---

## Performance Tips

### 1. Enable Caching

```python
# Always enable cache in production
engine = HybridSearchEngine(
    embedding_client=client,
    cache_enabled=True,  # ✓ Important
)
```

### 2. Use Appropriate Limits

```python
# Only fetch what you need
params = HybridSearchParams(
    limit=20,  # ✓ Good default
)

# Avoid
params = HybridSearchParams(
    limit=1000,  # ✗ Too many
)
```

### 3. Batch Indexing

```python
import asyncio

# Batch for speed
for batch in chunks(documents, 100):
    await asyncio.gather(*[
        client.index_document(doc_id, content)
        for doc_id, content in batch
    ])
```

### 4. Set Thresholds

```python
# Filter low-quality results early
params = HybridSearchParams(
    vector_threshold=0.5,  # Only >50% similarity
    graph_threshold=0.3,
)
```

### 5. Pre-warm Cache

```python
# Warm up cache with common queries
common_queries = ["error", "warning", "critical"]
for query in common_queries:
    await engine.search(query)
```

---

## Next Steps

### Learn More

- [Full Documentation](SEMANTIC_MEMORY_SEARCH.md) - Complete guide
- [API Reference](SEMANTIC_MEMORY_SEARCH.md#api-reference) - Detailed API docs
- [Integration Guide](SEMANTIC_MEMORY_SEARCH.md#integration-guide) - Advanced integration

### Advanced Features

- Custom embedding backends (OpenAI, Cohere, local models)
- Integration with EventCollector
- Integration with Session-Buddy
- Custom ranking strategies
- Performance optimization

### Examples

```python
# Full working example
import asyncio
from mahavishnu.search.hybrid_search import HybridSearchEngine
from mahavishnu.search.embeddings import MockEmbeddingClient
from mahavishnu.search.graph import MockGraphClient

async def main():
    # 1. Initialize
    client = MockEmbeddingClient()
    engine = HybridSearchEngine(embedding_client=client)

    # 2. Index
    docs = {"doc1": "authentication error", "doc2": "database timeout"}
    for doc_id, content in docs.items():
        await client.index_document(doc_id, content)

    # 3. Search
    results = await engine.search("login failure")

    # 4. Display
    for r in results:
        print(f"{r.hybrid_score:.2f}: {r.content}")

asyncio.run(main())
```

### Troubleshooting

| Problem | Solution |
|---------|----------|
| No results | Lower thresholds, try broader query |
| Slow search | Enable cache, reduce limit, check index size |
| Poor relevance | Adjust weights, try different ranking strategy |
| Memory issues | Use persistent storage, clear cache |

### Getting Help

- GitHub Issues: [mahavishnu/issues](https://github.com/your-repo/mahavishnu/issues)
- Documentation: [docs/](./)
- Examples: [examples/](../examples/)

---

## Quick Reference

### Import Statements

```python
from mahavishnu.search.hybrid_search import (
    HybridSearchEngine,
    HybridSearchParams,
    HybridRankingStrategy,
    SearchResult,
    create_hybrid_search,
)

from mahavishnu.search.embeddings import (
    EmbeddingClient,
    MockEmbeddingClient,
)

from mahavishnu.integrations.semantic_search_cli import (
    SemanticSearchBuilder,
    NLQueryParser,
    SearchContext,
    SearchMode,
)
```

### Common Patterns

```python
# Initialize
engine = HybridSearchEngine(embedding_client=client)

# Index
await client.index_document(doc_id, content)

# Search
results = await engine.search("query")

# Filter
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("query") \
    .system("mahavishnu") \
    .severity("error") \
    .execute()
```

### Score Interpretation

| Score Range | Meaning |
|-------------|---------|
| 0.9 - 1.0 | Excellent match |
| 0.7 - 0.9 | Very good match |
| 0.5 - 0.7 | Good match |
| 0.3 - 0.5 | Fair match |
| < 0.3 | Poor match |

---

**Ready to dive deeper?** See [SEMANTIC_MEMORY_SEARCH.md](SEMANTIC_MEMORY_SEARCH.md) for complete documentation.

**Quick Tips:**
- ✓ Always enable caching in production
- ✓ Use appropriate limits (10-50 results)
- ✓ Batch indexing operations
- ✓ Set thresholds to filter noise
- ✓ Monitor performance metrics

**Happy Searching!** 🚀
