# Semantic Memory Search - Complete Guide

**Comprehensive documentation for semantic search, vector embeddings, and natural language querying in Mahavishnu.**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Embedding Models](#embedding-models)
4. [Search Engine](#search-engine)
5. [Natural Language Queries](#natural-language-queries)
6. [Vector Store](#vector-store)
7. [Performance Optimization](#performance-optimization)
8. [CLI Reference](#cli-reference)
9. [API Reference](#api-reference)
10. [Integration Guide](#integration-guide)
11. [Best Practices](#best-practices)
12. [Troubleshooting](#troubleshooting)

---

## Overview

Semantic Memory Search enables intelligent retrieval of events, documents, and knowledge using natural language understanding and vector similarity search.

### Key Features

- **Vector Embeddings**: Convert text to high-dimensional vectors for semantic similarity
- **Hybrid Search**: Combine vector similarity with graph traversal for enhanced relevance
- **Natural Language Queries**: Query using plain English ("show me errors from yesterday")
- **Multiple Ranking Strategies**: Weighted sum, reciprocal rank fusion, learning-to-rank
- **Flexible Storage**: Support for in-memory, SQLite, and Session-Buddy graph storage
- **CLI Integration**: Command-line interface for interactive searching
- **Multiple Output Formats**: Table, JSON, Markdown, HTML

### Use Cases

```python
# Find similar errors
"Show me all authentication failures from yesterday"

# Semantic similarity
"Find events similar to database connection timeout"

# Faceted search
"Critical production incidents from mahavishnu in the last week"

# Pattern discovery
"Cluster related error messages"
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Semantic Search Architecture                │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Natural    │─────▶│   Query      │─────▶│   Search     │
│  Language    │      │   Parser     │      │   Engine     │
│    Query     │      └──────────────┘      └──────┬───────┘
└──────────────┘                                    │
                                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Hybrid Search Engine                        │
│  ┌─────────────────┐         ┌─────────────────┐              │
│  │  Vector Search  │         │  Graph Search   │              │
│  │  (Embeddings)   │         │  (Knowledge)    │              │
│  └────────┬────────┘         └────────┬────────┘              │
│           │                           │                         │
│           └───────────┬───────────────┘                         │
│                       ▼                                         │
│              ┌───────────────┐                                  │
│              │ Rank Results  │                                  │
│              │ (Strategies)  │                                  │
│              └───────┬───────┘                                  │
└──────────────────────┼─────────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  Vector Store  │
              │  (Documents)   │
              └────────────────┘
```

### Components

1. **EmbeddingClient**: Converts text to vector embeddings
2. **GraphClient**: Provides knowledge graph traversal
3. **HybridSearchEngine**: Orchestrates search and ranking
4. **NLQueryParser**: Parses natural language queries
5. **VectorStore**: Stores and indexes embeddings

### Data Flow

```
Query → Parse → Embed → Search (Vector + Graph) → Rank → Return
  ↓        ↓        ↓              ↓                   ↓
 NL     Filters  Vectors    Similarity           Results
        & Time             Scores
```

---

## Embedding Models

### Overview

Embedding models convert text into high-dimensional vectors (e.g., 384 dimensions) where similar concepts are close together in vector space.

### MockEmbeddingClient

```python
from mahavishnu.search.embeddings import MockEmbeddingClient

# Initialize client
client = MockEmbeddingClient(embedding_dim=384)

# Embed text
embedding = await client.embed("authentication error")
# Returns: [0.23, 0.56, 0.12, ...] (384 floats)

# Index document
await client.index_document("doc1", "User authentication failed")

# Search similar documents
results = await client.search(query_embedding, limit=10)
# Returns: [("doc1", 0.89), ("doc2", 0.76), ...]
```

### EmbeddingClient Interface

```python
class EmbeddingClient(ABC):
    """Abstract base class for embedding clients."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to vector embedding."""
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Search for similar vectors."""
        pass

    @abstractmethod
    async def get_document_content(self, document_id: str) -> str:
        """Get document content by ID."""
        pass
```

### Similarity Metrics

The mock client uses **cosine similarity**:

```
similarity = (A · B) / (||A|| * ||B||)

Range: 0 to 1
- 1.0 = identical
- 0.8+ = very similar
- 0.5+ = somewhat similar
- <0.5 = not similar
```

### Batch Operations

```python
# Batch embedding
texts = ["error 1", "error 2", "error 3"]
embeddings = await client.embed_batch(texts)
# Returns: [[...], [...], [...]]
```

---

## Search Engine

### HybridSearchEngine

Combines vector similarity search with graph traversal for enhanced relevance.

### Initialization

```python
from mahavishnu.search.hybrid_search import HybridSearchEngine
from mahavishnu.search.embeddings import MockEmbeddingClient
from mahavishnu.search.graph import MockGraphClient

# Create clients
embedding_client = MockEmbeddingClient()
graph_client = MockGraphClient()

# Initialize engine
engine = HybridSearchEngine(
    embedding_client=embedding_client,
    graph_client=graph_client,
    cache_enabled=True,  # Enable result caching
)
```

### Search Parameters

```python
from mahavishnu.search.hybrid_search import HybridSearchParams, HybridRankingStrategy

params = HybridSearchParams(
    vector_weight=0.6,        # Weight for vector similarity (0-1)
    graph_weight=0.4,         # Weight for graph traversal (0-1)
    limit=20,                 # Maximum results
    strategy=HybridRankingStrategy.WEIGHTED_SUM,  # Ranking strategy
    graph_depth=3,            # Max graph traversal depth
    vector_threshold=0.3,     # Minimum vector similarity
    graph_threshold=0.2,      # Minimum graph score
    include_metadata=True,    # Include node metadata
)
```

### Ranking Strategies

#### 1. Weighted Sum (Default)

```python
strategy = HybridRankingStrategy.WEIGHTED_SUM

# Formula:
hybrid_score = (vector_score * vector_weight) + (graph_score * graph_weight)

# Example:
# vector_score = 0.8, graph_score = 0.6
# vector_weight = 0.6, graph_weight = 0.4
# hybrid_score = (0.8 * 0.6) + (0.6 * 0.4) = 0.48 + 0.24 = 0.72
```

#### 2. Reciprocal Rank Fusion

```python
strategy = HybridRankingStrategy.RECIPROCAL_RANK

# Combines rankings from both sources
# Better for handling heterogeneous scores
```

#### 3. RRF (Reciprocal Rank Fusion with constant)

```python
strategy = HybridRankingStrategy.RRF

# Uses constant k=60 for RRF formula
# Industry-standard for rank aggregation
```

### Search Execution

```python
# Simple search
results = await engine.search("authentication errors")

# With parameters
results = await engine.search(
    "database timeout",
    params=HybridSearchParams(
        vector_weight=0.7,
        graph_weight=0.3,
        limit=10,
    )
)
```

### Search Results

```python
from mahavishnu.search.hybrid_search import SearchResult

for result in results:
    print(f"Rank: {result.rank}")
    print(f"Node ID: {result.node_id}")
    print(f"Content: {result.content}")
    print(f"Hybrid Score: {result.hybrid_score:.3f}")
    print(f"Vector Score: {result.vector_score:.3f}")
    print(f"Graph Score: {result.graph_score:.3f}")
    print(f"Metadata: {result.metadata}")
    print()
```

### Result Structure

```python
SearchResult(
    node_id="doc1",                    # Unique identifier
    content="User authentication...",  # Document content
    vector_score=0.85,                 # Vector similarity (0-1)
    graph_score=0.62,                  # Graph relevance (0-1)
    hybrid_score=0.76,                 # Combined score (0-1)
    metadata={...},                    # Optional metadata
    rank=1,                            # Result rank
)
```

### Caching

```python
# Cache is enabled by default
engine = HybridSearchEngine(cache_enabled=True)

# First search - populates cache
results1 = await engine.search("error")

# Second search - returns cached results
results2 = await engine.search("error")

# Clear cache
await engine.clear_cache()

# Get cache stats
stats = engine.get_cache_stats()
print(f"Cached queries: {stats['cache_size']}")
```

---

## Natural Language Queries

### NLQueryParser

Converts natural language queries into structured search parameters.

### Supported Patterns

#### Time Expressions

```python
from mahavishnu.integrations.semantic_search_cli import NLQueryParser

parser = NLQueryParser()

# Relative time
query, filters = parser.parse("errors from yesterday")
# filters = {"start_time": datetime.now() - 1 day}

query, filters = parser.parse("incidents from last week")
# filters = {"start_time": datetime.now() - 7 days}

query, filters = parser.parse("events from last month")
# filters = {"start_time": datetime.now() - 30 days}
```

#### Severity Filters

```python
# Keywords: critical, error, warning, info, debug
query, filters = parser.parse("critical errors")
# filters = {"severity": "critical"}

query, filters = parser.parse("warning messages")
# filters = {"severity": "warning"}
```

#### System Filters

```python
# Keywords: mahavishnu, crackerjack, session_buddy, akosha, oneiric
query, filters = parser.parse("errors in mahavishnu")
# filters = {"source_system": "mahavishnu"}

query, filters = parser.parse("issues from crackerjack")
# filters = {"source_system": "crackerjack"}
```

#### Complex Queries

```python
# Combine multiple filters
query, filters = parser.parse(
    "Show me critical errors from mahavishnu from yesterday"
)
# filters = {
#     "severity": "critical",
#     "source_system": "mahavishnu",
#     "start_time": datetime.now() - 1 day,
#     "end_time": datetime.now(),
# }
# query = "show me"
```

### SemanticSearchBuilder

Fluent API for building complex queries.

```python
from mahavishnu.integrations.semantic_search_cli import SemanticSearchBuilder

builder = SemanticSearchBuilder(search_engine)

# Build query
results = await builder \
    .natural_language("database errors") \
    .system("mahavishnu") \
    .severity("error") \
    .in_last_days(7) \
    .limit(20) \
    .execute()
```

### Builder Methods

#### Query Methods

```python
# Natural language query
builder.natural_language("authentication failures")

# Semantic similarity query
builder.semantic_query("login problems")
```

#### Filter Methods

```python
# Filter by system
builder.system("mahavishnu")

# Filter by severity
builder.severity("critical")

# Filter by event type
builder.event_type("workflow_complete")

# Filter by time range
builder.in_last_hours(24)
builder.in_last_days(7)
builder.from_date("2025-02-01", "2025-02-07")

# Filter by tags
builder.with_tags("security", "production")

# Filter by correlation ID
builder.with_correlation_id("wf-123")
```

#### Weight Methods

```python
# Adjust search weights
builder.vector_weight(0.8)
builder.graph_weight(0.2)
```

#### Limit

```python
# Set result limit
builder.limit(50)
```

### Query Examples

#### Example 1: Recent Errors

```python
# Natural language: "Show me errors from the last 24 hours"
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("errors") \
    .in_last_hours(24) \
    .execute()
```

#### Example 2: System-Specific Critical Events

```python
# Natural language: "Critical incidents in mahavishnu from last week"
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("incidents") \
    .system("mahavishnu") \
    .severity("critical") \
    .in_last_days(7) \
    .execute()
```

#### Example 3: Correlated Events

```python
# Find all events related to a workflow
builder = SemanticSearchBuilder(engine)
results = await builder \
    .natural_language("workflow") \
    .with_correlation_id("wf-abc123") \
    .execute()
```

#### Example 4: Weighted Search

```python
# Prefer vector similarity over graph traversal
builder = SemanticSearchBuilder(engine)
results = await builder \
    .semantic_query("database timeout") \
    .vector_weight(0.8) \
    .graph_weight(0.2) \
    .limit(20) \
    .execute()
```

---

## Vector Store

### Storage Options

#### 1. In-Memory Storage (Default)

```python
from mahavishnu.search.embeddings import MockEmbeddingClient

client = MockEmbeddingClient()

# Fast but volatile
await client.index_document("doc1", "content")

# Lost on process exit
```

#### 2. SQLite Storage

For integration with EventCollector (see EventCollector documentation).

#### 3. Session-Buddy Graph Storage

Stores embeddings in Session-Buddy knowledge graph (requires Session-Buddy MCP server).

### Indexing Documents

```python
# Single document
await client.index_document(
    document_id="doc1",
    content="Authentication failed due to invalid credentials"
)

# Batch indexing
documents = [
    ("doc1", "Error message 1"),
    ("doc2", "Error message 2"),
    ("doc3", "Error message 3"),
]

for doc_id, content in documents:
    await client.index_document(doc_id, content)
```

### Retrieving Documents

```python
# By ID
content = await client.get_document_content("doc1")

# By similarity
query_embedding = await client.embed("login failure")
results = await client.search(query_embedding, limit=10)

for doc_id, score in results:
    content = await client.get_document_content(doc_id)
    print(f"{doc_id}: {score:.3f} - {content}")
```

### Index Management

```python
# Update document
await client.index_document("doc1", "updated content")

# Delete document (if supported by backend)
# Note: MockEmbeddingClient doesn't support deletion
```

---

## Performance Optimization

### Vector Store Optimization

#### Batch Operations

```python
# Batch embedding is more efficient
texts = [f"document {i}" for i in range(100)]

# Slower: sequential
for text in texts:
    await client.embed(text)

# Faster: batch (if supported)
embeddings = await client.embed_batch(texts)
```

#### Embedding Caching

```python
# Cache frequently used embeddings
embedding_cache = {}

async def get_embedding(text: str) -> list[float]:
    if text not in embedding_cache:
        embedding_cache[text] = await client.embed(text)
    return embedding_cache[text]
```

### Search Optimization

#### Result Caching

```python
# Enable caching for repeated queries
engine = HybridSearchEngine(
    embedding_client=client,
    graph_client=graph_client,
    cache_enabled=True,  # Enable cache
)

# Pre-warm cache
await engine.search("common query")
```

#### Threshold Filtering

```python
# Filter low-quality results early
params = HybridSearchParams(
    vector_threshold=0.5,  # Only return results with >50% similarity
    graph_threshold=0.3,
)

results = await engine.search("query", params)
```

#### Limit Results

```python
# Reduce computation by limiting results
params = HybridSearchParams(
    limit=20,  # Only need top 20
)
```

### Graph Traversal Optimization

```python
# Limit traversal depth
params = HybridSearchParams(
    graph_depth=2,  # Shallow traversal
)

# For large graphs, depth has significant performance impact
```

### Performance Benchmarks

#### Expected Performance

```
Indexing Throughput:
- Small docs (<100 chars): 100+ docs/sec
- Medium docs (100-1000 chars): 50+ docs/sec
- Large docs (>1000 chars): 20+ docs/sec

Search Latency:
- Small index (<100 docs): <50ms
- Medium index (100-1000 docs): <100ms
- Large index (>1000 docs): <200ms

Memory Usage:
- Per embedding (384 dims): ~3KB
- 1000 docs: ~3MB
- 10000 docs: ~30MB
```

#### Benchmarking

```python
import time

# Benchmark indexing
start = time.time()
for i in range(100):
    await client.index_document(f"doc{i}", f"content {i}")
elapsed = time.time() - start
throughput = 100 / elapsed
print(f"Indexing: {throughput:.1f} docs/sec")

# Benchmark search
start = time.time()
results = await engine.search("query")
latency = time.time() - start
print(f"Search: {latency*1000:.1f}ms")
```

---

## CLI Reference

### Search Command

```bash
# Basic natural language search
mahavishnu search "Show me errors from yesterday"

# With filters
mahavishnu search "database errors" \
  --system mahavishnu \
  --severity error \
  --last-hours 24 \
  --limit 20

# Export results
mahavishnu search "incidents" \
  --output markdown \
  --export report.md

# Adjust weights
mahavishnu search "authentication" \
  --vector-weight 0.8 \
  --graph-weight 0.2
```

### Command Options

```
Usage: mahavishnu search [OPTIONS] QUERY

Arguments:
  QUERY    Natural language search query

Options:
  -s, --system TEXT              Filter by source system
  --severity TEXT                Filter by severity level
  -t, --event-type TEXT          Filter by event type
  -h, --last-hours INTEGER       Last N hours
  -d, --last-days INTEGER        Last N days
  --from TEXT                    Start date (ISO format)
  --to TEXT                      End date (ISO format)
  -n, --limit INTEGER            Maximum results [default: 20]
  -o, --output [table|json|markdown|html]
                                Output format [default: table]
  -e, --export TEXT              Export to file
  --vector-weight FLOAT          Vector search weight (0-1) [default: 0.6]
  --graph-weight FLOAT           Graph search weight (0-1) [default: 0.4]
  --help                         Show help message
```

### Similar Events Command

```bash
# Find events similar to a specific event
mahavishnu search similar evt-001 --limit 20 --threshold 0.5
```

### Cluster Command

```bash
# Cluster similar results
mahavishnu search cluster "database errors" --threshold 0.8 --limit 50
```

### Timeline Command

```bash
# Search across timeline
mahavishnu search timeline "errors" \
  --from "2025-02-01" \
  --to "2025-02-07" \
  --interval 1d \
  --limit 100
```

### Output Formats

#### Table Output (Default)

```bash
mahavishnu search "errors" --output table
```

```
┏━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Rank ┃ Score  ┃ Vector ┃ Graph  ┃ Node ID              ┃ Content              ┃
┡━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│    1 │ 0.85   │ 0.90   │ 0.75   │ doc1                 │ User auth failed... │
│    2 │ 0.72   │ 0.80   │ 0.60   │ doc2                 │ Database timeout... │
└──────┴────────┴────────┴────────┴──────────────────────┴───────────────────────┘
```

#### JSON Output

```bash
mahavishnu search "errors" --output json --export results.json
```

```json
[
  {
    "rank": 1,
    "node_id": "doc1",
    "content": "User authentication failed",
    "scores": {
      "hybrid": 0.85,
      "vector": 0.90,
      "graph": 0.75
    },
    "metadata": {}
  }
]
```

#### Markdown Output

```bash
mahavishnu search "errors" --output markdown --export report.md
```

```markdown
# Semantic Search Results

**Query:** errors
**Results:** 10
**Timestamp:** 2025-02-05T12:00:00Z

---

## Result 1 (Score: 0.85)

**Node ID:** `doc1`

**Scores:**
- Hybrid: 0.850
- Vector: 0.900
- Graph: 0.750

**Content:**
```
User authentication failed due to invalid credentials
```
```

#### HTML Output

```bash
mahavishnu search "errors" --output html --export report.html
```

Generates an interactive HTML report with styling.

---

## API Reference

### Core Classes

#### EmbeddingClient

```python
class EmbeddingClient(ABC):
    """Abstract base class for embedding clients."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to vector embedding.

        Args:
            text: Input text

        Returns:
            Vector embedding as list of floats (typically 384 dimensions)
        """
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Search for similar vectors.

        Args:
            query_embedding: Query vector embedding
            limit: Maximum number of results

        Returns:
            List of (document_id, similarity_score) tuples
        """
        pass

    @abstractmethod
    async def get_document_content(self, document_id: str) -> str:
        """Get document content by ID.

        Args:
            document_id: Document identifier

        Returns:
            Document content text
        """
        pass

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Convert multiple texts to embeddings.

        Args:
            texts: List of input texts

        Returns:
            List of vector embeddings
        """
        pass

    async def index_document(
        self,
        document_id: str,
        content: str,
    ) -> list[float]:
        """Index document for search.

        Args:
            document_id: Document identifier
            content: Document content

        Returns:
            Document embedding
        """
        pass
```

#### GraphClient

```python
class GraphClient(ABC):
    """Abstract base class for graph clients."""

    @abstractmethod
    async def traverse(
        self,
        start_node: str,
        max_depth: int = 3,
        limit: int = 20,
    ) -> list[tuple[str, float]]:
        """Traverse graph from start node.

        Args:
            start_node: Starting node identifier
            max_depth: Maximum traversal depth
            limit: Maximum number of results

        Returns:
            List of (node_id, relevance_score) tuples
        """
        pass

    @abstractmethod
    async def extract_entities(self, text: str) -> list[str]:
        """Extract entity names from text.

        Args:
            text: Input text

        Returns:
            List of entity names found in graph
        """
        pass

    @abstractmethod
    async def get_node_content(self, node_id: str) -> str:
        """Get node content.

        Args:
            node_id: Node identifier

        Returns:
            Node content text
        """
        pass
```

#### HybridSearchEngine

```python
class HybridSearchEngine:
    """Hybrid search engine combining vector and graph search.

    Features:
    - Vector similarity search via embeddings
    - Graph traversal for relationship-based discovery
    - Hybrid ranking with multiple strategies
    - Configurable weights and thresholds
    - Efficient result caching
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
        graph_client: GraphClient | None = None,
        cache_enabled: bool = True,
    ):
        """Initialize hybrid search engine.

        Args:
            embedding_client: Vector embedding client
            graph_client: Knowledge graph client
            cache_enabled: Enable result caching
        """
        pass

    async def search(
        self,
        query: str,
        params: HybridSearchParams | None = None,
    ) -> list[SearchResult]:
        """Execute hybrid search.

        Args:
            query: Search query
            params: Search parameters (default: balanced weights)

        Returns:
            List of search results ranked by hybrid score
        """
        pass

    async def clear_cache(self) -> None:
        """Clear search result cache."""
        pass

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Cache stats dict
        """
        pass
```

#### SearchResult

```python
@dataclass
class SearchResult:
    """Single search result.

    Attributes:
        node_id: Unique node identifier
        content: Node content/text
        vector_score: Vector similarity score (0-1)
        graph_score: Graph traversal score (0-1)
        hybrid_score: Combined hybrid score (0-1)
        metadata: Additional metadata
        rank: Result rank
    """
    node_id: str
    content: str
    vector_score: float
    graph_score: float
    hybrid_score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    rank: int = 0
```

#### HybridSearchParams

```python
@dataclass
class HybridSearchParams:
    """Parameters for hybrid search.

    Attributes:
        vector_weight: Weight for vector similarity (0-1)
        graph_weight: Weight for graph traversal (0-1)
        limit: Maximum number of results
        strategy: Ranking strategy
        graph_depth: Maximum graph traversal depth
        vector_threshold: Minimum vector similarity
        graph_threshold: Minimum graph score
        include_metadata: Include node metadata
    """
    vector_weight: float = 0.6
    graph_weight: float = 0.4
    limit: int = 10
    strategy: HybridRankingStrategy = HybridRankingStrategy.WEIGHTED_SUM
    graph_depth: int = 3
    vector_threshold: float = 0.0
    graph_threshold: float = 0.0
    include_metadata: bool = True
```

#### HybridRankingStrategy

```python
class HybridRankingStrategy(str, Enum):
    """Hybrid ranking strategies."""
    WEIGHTED_SUM = "weighted_sum"
    RECIPROCAL_RANK = "reciprocal_rank"
    RRF = "rrf"
    LEARNING_TO_RANK = "learning_to_rank"
```

### Helper Functions

```python
async def create_hybrid_search(
    embedding_client: EmbeddingClient | None = None,
    graph_client: GraphClient | None = None,
    cache_enabled: bool = True,
) -> HybridSearchEngine:
    """Create hybrid search engine.

    Args:
        embedding_client: Vector embedding client
        graph_client: Knowledge graph client
        cache_enabled: Enable result caching

    Returns:
        HybridSearchEngine instance
    """
    pass
```

---

## Integration Guide

### Integration with EventCollector

```python
from mahavishnu.integrations.event_collector import EventCollector
from mahavishnu.search.hybrid_search import HybridSearchEngine
from mahavishnu.search.embeddings import MockEmbeddingClient

# Initialize event collector
collector = EventCollector(storage_backend="sqlite", db_path="events.db")
await collector.initialize()

# Initialize search engine
embedding_client = MockEmbeddingClient()
engine = HybridSearchEngine(embedding_client=embedding_client)

# Index events from collector
query = EventQuery(limit=100)
events = await collector.query_events(query)

for event in events:
    # Create searchable text from event
    searchable_text = f"{event.event_type} {event.severity} {event.data}"

    # Index for semantic search
    await embedding_client.index_document(
        document_id=event.event_id,
        content=searchable_text,
    )

# Search events
results = await engine.search("authentication failures")
```

### Integration with Session-Buddy

```python
from mahavishnu.search.embeddings import EmbeddingClient
from mahavishnu.search.graph import GraphClient

# Custom embedding client that uses Session-Buddy
class SessionBuddyEmbeddingClient(EmbeddingClient):
    """Session-Buddy backed embedding client."""

    def __init__(self, session_buddy_url: str):
        self.session_buddy_url = session_buddy_url

    async def embed(self, text: str) -> list[float]:
        # Call Session-Buddy MCP tool for embedding
        result = await self._call_mcp("embed_text", {"text": text})
        return result["embedding"]

    async def search(self, query_embedding, limit=10):
        # Search Session-Buddy vector index
        result = await self._call_mcp(
            "vector_search",
            {"embedding": query_embedding, "limit": limit}
        )
        return result["matches"]

    async def get_document_content(self, document_id: str) -> str:
        result = await self._call_mcp(
            "get_node",
            {"node_id": document_id}
        )
        return result["content"]

    async def _call_mcp(self, tool, params):
        # MCP client implementation
        pass
```

### Custom Embedding Backend

```python
import openai

class OpenAIEmbeddingClient(EmbeddingClient):
    """OpenAI embeddings client."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

    async def search(self, query_embedding, limit=10):
        # Implement with vector database (e.g., Pinecone, Weaviate)
        pass

    async def get_document_content(self, document_id: str) -> str:
        # Implement document retrieval
        pass
```

### Custom Ranking Strategy

```python
from mahavishnu.search.hybrid_search import HybridSearchEngine

class CustomRankingEngine(HybridSearchEngine):
    """Custom ranking strategy."""

    async def _rank_results(self, combined, params):
        """Custom ranking logic."""
        results = []

        for node_id, data in combined.items():
            # Custom scoring formula
            vector_score = data["vector_score"]
            graph_score = data["graph_score"]

            # Boost recent documents
            recency_boost = self._calculate_recency_boost(node_id)

            # Boost high-severity events
            severity_boost = self._calculate_severity_boost(node_id)

            # Combine scores
            custom_score = (
                (vector_score * 0.5) +
                (graph_score * 0.3) +
                (recency_boost * 0.1) +
                (severity_boost * 0.1)
            )

            results.append(SearchResult(
                node_id=node_id,
                content=await self._get_content(node_id),
                vector_score=vector_score,
                graph_score=graph_score,
                hybrid_score=custom_score,
            ))

        return sorted(results, key=lambda r: r.hybrid_score, reverse=True)

    def _calculate_recency_boost(self, node_id: str) -> float:
        # Calculate recency boost
        pass

    def _calculate_severity_boost(self, node_id: str) -> float:
        # Calculate severity boost
        pass
```

---

## Best Practices

### Query Design

1. **Use Specific Language**
   ```python
   # Good
   await engine.search("database connection timeout error")

   # Less specific
   await engine.search("problem")
   ```

2. **Include Context**
   ```python
   # Good
   await engine.search("user authentication failure due to expired token")

   # Less context
   await engine.search("auth error")
   ```

3. **Leverage Filters**
   ```python
   # Use filters instead of complex queries
   builder.natural_language("errors") \
       .system("mahavishnu") \
       .severity("critical") \
       .in_last_days(7)
   ```

### Indexing Strategy

1. **Batch Indexing**
   ```python
   # Good: Batch operations
   for batch in chunks(documents, 100):
       await asyncio.gather(*[
           client.index_document(doc_id, content)
           for doc_id, content in batch
       ])
   ```

2. **Pre-process Content**
   ```python
   # Clean and normalize before indexing
   def preprocess_text(text: str) -> str:
       text = text.lower()
       text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
       text = text.strip()
       return text

   await client.index_document(
       doc_id,
       preprocess_text(raw_content)
   )
   ```

3. **Include Metadata**
   ```python
   # Index with context
   searchable_text = f"""
   Event Type: {event.event_type}
   Severity: {event.severity}
   System: {event.source_system}
   Description: {event.data.get('description', '')}
   """.strip()
   ```

### Performance

1. **Enable Caching**
   ```python
   engine = HybridSearchEngine(
       embedding_client=client,
       cache_enabled=True,  # Always enable in production
   )
   ```

2. **Set Appropriate Limits**
   ```python
   # Only fetch what you need
   params = HybridSearchParams(limit=20)
   ```

3. **Use Thresholds**
   ```python
   # Filter low-quality results
   params = HybridSearchParams(
       vector_threshold=0.5,
       graph_threshold=0.3,
   )
   ```

### Error Handling

```python
from mahavishnu.core.errors import MahavishnuError

try:
    results = await engine.search("query")
except MahavishnuError as e:
    logger.error(f"Search failed: {e.message}")
    logger.error(f"Details: {e.details}")
    # Fallback to keyword search
    results = await fallback_keyword_search("query")
```

---

## Troubleshooting

### Common Issues

#### Issue 1: No Search Results

**Symptoms**: Search returns empty list

**Causes**:
- No documents indexed
- Query too specific
- Thresholds too high

**Solutions**:
```python
# Check if documents are indexed
content = await client.get_document_content("doc1")

# Lower thresholds
params = HybridSearchParams(
    vector_threshold=0.2,  # Lower from 0.5
    graph_threshold=0.1,
)

# Try broader query
results = await engine.search("error")  # Instead of "database connection timeout"
```

#### Issue 2: Slow Search Performance

**Symptoms**: Search takes >1 second

**Causes**:
- Large index size
- Deep graph traversal
- No caching

**Solutions**:
```python
# Enable caching
engine = HybridSearchEngine(cache_enabled=True)

# Reduce graph depth
params = HybridSearchParams(
    graph_depth=2,  # Reduce from 3
)

# Limit results
params = HybridSearchParams(
    limit=20,  # Instead of 100
)
```

#### Issue 3: Poor Relevance

**Symptoms**: Results don't match query intent

**Causes**:
- Wrong weight balance
- Inappropriate ranking strategy
- Poor document content

**Solutions**:
```python
# Adjust weights
params = HybridSearchParams(
    vector_weight=0.8,  # More weight to semantic similarity
    graph_weight=0.2,
)

# Try different strategy
params = HybridSearchParams(
    strategy=HybridRankingStrategy.RRF,
)

# Improve document indexing
searchable_text = f"{title}\n{description}\n{tags}"
```

#### Issue 4: Memory Issues

**Symptoms**: Out of memory errors

**Causes**:
- Too many embeddings in memory
- Large embedding dimension
- Memory leaks

**Solutions**:
```python
# Use persistent storage instead of in-memory
# (Use SQLite or Session-Buddy backend)

# Reduce embedding dimension
client = MockEmbeddingClient(embedding_dim=128)  # Instead of 384

# Clear cache periodically
await engine.clear_cache()

# Limit index size
# Only index recent/relevant documents
```

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("mahavishnu.search")

# Trace search execution
logger.debug(f"Search query: {query}")
logger.debug(f"Search params: {params}")
logger.debug(f"Results: {len(results)}")
```

### Performance Profiling

```python
import time
import cProfile

def profile_search():
    start = time.time()
    results = await engine.search("query")
    elapsed = time.time() - start

    print(f"Search took {elapsed*1000:.1f}ms")
    print(f"Found {len(results)} results")

# Profile with cProfile
cProfile.run('await engine.search("query")', sort='cumtime')
```

---

## Appendix

### Glossary

- **Embedding**: High-dimensional vector representation of text
- **Vector Similarity**: Measure of how close two vectors are in vector space
- **Cosine Similarity**: Similarity metric based on angle between vectors
- **Hybrid Search**: Combining multiple search strategies (vector + graph)
- **Graph Traversal**: Following edges in a knowledge graph
- **Reciprocal Rank Fusion (RRF)**: Method for combining ranked result lists
- **Semantic Search**: Search based on meaning, not keywords
- **Knowledge Graph**: Network of entities and relationships

### Resources

- [Vector Embeddings Guide](https://openai.com/blog/new-and-improved-embedding-model)
- [FAISS Documentation](https://faiss.ai/)
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Cosine Similarity](https://en.wikipedia.org/wiki/Cosine_similarity)

### Changelog

#### Version 1.0.0 (2025-02-05)

- Initial release
- HybridSearchEngine with multiple ranking strategies
- MockEmbeddingClient and MockGraphClient
- Natural language query parsing
- CLI with multiple output formats
- Result caching

### License

MIT License - See LICENSE file for details

### Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

---

**Document Version**: 1.0.0
**Last Updated**: 2025-02-05
**Maintainer**: Mahavishnu Team
