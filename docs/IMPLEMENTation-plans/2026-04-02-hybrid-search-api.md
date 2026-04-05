# Hybrid Search API Implementation Plan

**Date**: 2026-04-02
**Status**: Complete
**Related Plan**: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`

## Overview

This document describes the implementation of the Hybrid Search API as part of the Storage Consolidation plan (Phase 2, deliverable 5).

 The implementation follows the patterns established in the mahavishnu codebase:
- Uses existing repository layer (`DocumentRepository`, `EmbeddingRepository`)
- Follows Oneiric configuration patterns
- Implements async context managers for database connections
- Provides comprehensive logging for observability

## Deliverables

### Core Module
- **File**: `mahavishnu/core/search/__init__.py`
- **Purpose**: Module exports for hybrid search
- **Contents**: Exports `HybridSearchConfig`, `HybridSearchEngine`, `HybridSearchResult`

### Main Implementation
- **File**: `mahavishnu/core/search/hybrid_search.py`
- **Purpose**: Hybrid search engine implementation
- **Lines of Code**: ~400
- **Key Components**:
  1. **HybridSearchConfig** (dataclass)
     - Configuration for search weights and thresholds
     - Default: semantic_weight=0.7, lexical_weight=0.3, default_limit=20, min_score=0.5
     - Validation: Weights normalized to sum to 1.0
     - Validation: Score thresholds (0.0-1.0)

  2. **HybridSearchResult** (Pydantic model)
     - Result model with semantic, lexical, and combined scores
     - Fields: id, source_type, title, content, scores, metadata, timestamps
     - Pydantic validation for score ranges

  3. **HybridSearchEngine** (class)
     - Main search engine class
     - Methods:
       - `search()`: Execute hybrid search (semantic + lexical)
       - `index_document()`: Index a document for search
       - `delete_document()`: Remove document from search index
     - Private methods:
       - `_get_query_embedding()`: Generate query embedding
       - `_hybrid_search()`: Full hybrid search with SQL query from plan
       - `_lexical_only_search()`: Fallback when embeddings unavailable
     - Features:
       - Async context manager pattern for DB connections
       - Graceful fallback to lexical-only when embeddings fail
       - Repository filtering support
       - Comprehensive logging for all operations

       - SQL Query (lines 260-275 from plan):
         ```sql
         SELECT
             d.id, d.source_type, d.title, d.content,
             1 - (e.embedding <=> $1::vector) AS semantic_score,
             ts_rank(d.content_tsv, plainto_tsquery('english', $2)) AS lexical_score
         FROM search.documents d
         JOIN search.document_embeddings e ON e.document_id = d.id
         WHERE d.repository = COALESCE($3, d.repository)
         ORDER BY
             ($4::float * (1 - (e.embedding <=> $1::vector))) +
             ($5::float * ts_rank(d.content_tsv, plainto_tsquery('english', $2))) DESC
         LIMIT 20;
         ```

### MCP Tools
- **File**: `mahavishnu/mcp/tools/search_tools.py`
- **Purpose**: MCP tools for hybrid search
- **Lines of Code**: ~250
- **Tools**:
  1. **hybrid_search**: Main search tool with configurable weights
     - Parameters: query, repository (optional), limit, weights
     - Returns: List of search results with scores
  2. **index_document**: Index a document for search
     - Parameters: doc_id, title, content, metadata
     - Returns: Success status
  3. **delete_document**: Remove document from search index
     - Parameters: doc_id
     - Returns: Success status
  4. **search_by_repository**: Convenience tool for repository-scoped search
     - Parameters: repository (required), query (optional)
     - Returns: List of results from repository

- **Integration**: Registered in `mahavishnu/mcp/tools/__init__.py`

## Architecture Patterns

### Repository Layer Integration
- Uses `EmbeddingRepository` from `mahavishnu/core/repositories/embeddings.py`
- Uses `DocumentRepository` from `mahavishnu/core/repositories/documents.py`
- Uses `BaseRepository` pattern from `mahavishnu/core/repositories/base.py`

### Database Connection
- Uses `asyncpg.Pool` for connection management
- Async context managers for safe connection handling
- Transaction support for indexing operations
- Graceful fallback to lexical-only when embeddings fail

- Integrated with `Database` singleton from `mahavishnu.core.database.py`

### Embedding Service
- Uses `EmbeddingService` from `mahavishnu/core/embeddings.py`
- Supports FastEmbed, Ollama, and OpenAI providers
- Generates embeddings for search queries and document indexing

### Configuration
- Follows Oneiric patterns with layered loading:
- Supports environment variable overrides
- Configuration via `HybridSearchConfig` dataclass

### Error Handling
- Custom exception hierarchy from `mahavishnu.core.errors.py`
- Structured logging for all operations
- Graceful degradation when services unavailable

## Key Features
1. **Hybrid Search**: Combines semantic (pgvector) and lexical (PostgreSQL full-text) search
2. **Configurable Weights**: Adjustable semantic vs lexical weight balance (default 70/30)
3. **Graceful Fallback**: Falls back to lexical-only search when embeddings unavailable
4. **Repository Filtering**: Optional repository filter for all search operations
5. **Document Indexing**: Full document indexing with automatic embedding generation
6. **MCP Integration**: Exposes search functionality via MCP tools
7. **Observability**: Comprehensive logging for all operations
8. **Type Safety**: Full type annotations with Pydantic validation

## Testing
- Unit tests created at `tests/unit/test_hybrid_search.py`
- Tests cover:
  - Configuration validation
  - Search operations (mocked database)
  - Document indexing and deletion
  - Error handling

## Usage Examples

### Python API
```python
from mahavishnu.core.search import HybridSearchEngine, HybridSearchConfig
from asyncpg import create_pool

# Initialize
pool = await create_pool("postgresql://localhost/mahavishnu")
config = HybridSearchConfig(semantic_weight=0.7, lexical_weight=0.3)
engine = HybridSearchEngine(pool, config=config)

# Search
results = await engine.search(
    query="API authentication implementation",
    repository="mahavishnu",
    limit=20
)

for result in results:
    print(f"{result.title}: {result.combined_score:.3f}")
```

### MCP Tools
```python
# Via MCP client
results = await mcp.call_tool("hybrid_search", {
    "query": "WebSocket integration",
    "repository": "mahavishnu",
    "limit": 10
})
```

## Next Steps
1. Integration with existing document ingestion pipelines
2. Performance optimization for query tuning
3. Add caching layer for frequently accessed documents
4. Implement reindexing for bulk updates
5. Add search analytics and usage metrics
