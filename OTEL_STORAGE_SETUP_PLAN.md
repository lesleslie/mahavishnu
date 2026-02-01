# OpenTelemetry Storage Setup Plan

## Overview

Setting up Oneiric's OTelStorageAdapter for semantic search over OpenTelemetry traces with PostgreSQL + pgvector backend.

## Current State Analysis

### Existing Components

1. **OTelStorageAdapter** (`/Users/les/Projects/mahavishnu/oneiric/adapters/observability/otel.py`)
   - Stub implementation, needs full implementation
   - Uses OTelStorageSettings for configuration

2. **OTelStorageSettings** (`/Users/les/Projects/mahavishnu/oneiric/adapters/observability/settings.py`)
   - Complete Pydantic settings model
   - Environment variable prefix: `OTEL_STORAGE_`
   - Configuration options:
     - `connection_string`: PostgreSQL connection string
     - `embedding_model`: Sentence transformer model (default: all-MiniLM-L6-v2)
     - `embedding_dimension`: Vector dimension (default: 384)
     - `cache_size`: Embedding cache size (default: 1000)
     - `similarity_threshold`: Minimum similarity score (default: 0.85)
     - `batch_size`: Batch write size (default: 100)
     - `batch_interval_seconds`: Batch flush interval (default: 5s)
     - `max_retries`: Retry attempts (default: 3)
     - `circuit_breaker_threshold`: Failure threshold (default: 5)

3. **MahavishnuSettings** (`/Users/les/Projects/mahavishnu/mahavishnu/core/config.py`)
   - Already has OpenTelemetry configuration
   - No OTelStorage-specific configuration yet

### Dependencies

**Current Status:**
- No PostgreSQL/pgvector dependencies in pyproject.toml
- OpenTelemetry SDK is already installed
- Need to add:
  - `asyncpg` (async PostgreSQL driver)
  - `pgvector` (vector similarity search)
  - `sentence-transformers` (embeddings)

## Implementation Tasks

### Task 1: Update Configuration

1.1 Add `otel_storage` section to `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`
```yaml
# OpenTelemetry trace storage with semantic search
otel_storage:
  enabled: false  # Enable after PostgreSQL setup
  connection_string: "postgresql://postgres:password@localhost:5432/otel_traces"
  embedding_model: "all-MiniLM-L6-v2"
  embedding_dimension: 384
  cache_size: 1000
  similarity_threshold: 0.85
  batch_size: 100
  batch_interval_seconds: 5
  max_retries: 3
  circuit_breaker_threshold: 5
```

1.2 Add OTelStorageSettings fields to MahavishnuSettings
- Map YAML config to Pydantic model
- Support environment variable overrides: `MAHAVISHNU_OTEL_STORAGE__*`

### Task 2: Add Dependencies

Update `/Users/les/Projects/mahavishnu/pyproject.toml`:

```toml
dependencies = [
    # ... existing dependencies ...

    # OpenTelemetry trace storage
    "asyncpg>=0.29.0",  # Async PostgreSQL driver
    "pgvector>=0.2.5",  # Vector similarity search
    "sentence-transformers>=2.2.2",  # Semantic embeddings
]
```

### Task 3: Implement OTelStorageAdapter

Full implementation of `/Users/les/Projects/mahavishnu/oneiric/adapters/observability/otel.py`:

3.1 **Database Schema**
- Create traces table with pgvector column
- Index on embedding vector for similarity search
- Timestamp and metadata indexes

3.2 **Core Methods**
- `store_trace()`: Store trace with semantic embedding
- `search_traces()`: Semantic similarity search
- `get_trace()`: Retrieve trace by ID
- `batch_store()`: Batch write with buffering
- `health_check()`: Database connectivity check

3.3 **Resilience Features**
- Retry logic with exponential backoff
- Circuit breaker for database failures
- Connection pooling
- Batch writes for performance

### Task 4: Create Documentation

Create `/Users/les/Projects/mahavishnu/docs/ONEIRIC_OTEL_STORAGE.md`:

4.1 **Architecture Overview**
- How traces are stored and indexed
- Semantic search workflow
- Vector similarity scoring

4.2 **Setup Instructions**
- PostgreSQL + pgvector installation
- Database schema creation
- Configuration options

4.3 **Usage Examples**
- Storing traces
- Semantic search queries
- Integration with OpenTelemetry SDK

4.4 **Migration Guide**
- From other backends (Jaeger, Tempo, etc.)
- Data migration strategies

### Task 5: Testing and Validation

5.1 **Unit Tests**
- Test adapter initialization
- Test trace storage and retrieval
- Test semantic search
- Test error handling

5.2 **Integration Tests**
- Test PostgreSQL connectivity
- Test pgvector functionality
- Test batch writes

5.3 **Validation Procedure**
- Start PostgreSQL with pgvector
- Run database schema creation
- Configure Mahavishnu with OTel storage
- Run test traces
- Verify semantic search functionality

## Prerequisites

1. **PostgreSQL Installation**
   - PostgreSQL 14+ (pgvector requires 14+)
   - pgvector extension installation
   - Database and user setup

2. **Python Dependencies**
   - asyncpg for async database operations
   - pgvector for vector operations
   - sentence-transformers for embeddings

3. **Configuration**
   - PostgreSQL connection string
   - Embedding model selection
   - Performance tuning parameters

## Success Criteria

1. Configuration properly structured with Oneiric patterns
2. Dependencies added and installable
3. OTelStorageAdapter fully implemented with all methods
4. Documentation complete with examples
5. Tests pass with PostgreSQL + pgvector
6. Semantic search returns relevant traces

## File Changes Summary

### Files to Modify
1. `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml` - Add otel_storage config
2. `/Users/les/Projects/mahavishnu/mahavishnu/core/config.py` - Add OTelStorageSettings fields
3. `/Users/les/Projects/mahavishnu/pyproject.toml` - Add dependencies
4. `/Users/les/Projects/mahavishnu/oneiric/adapters/observability/otel.py` - Implement adapter

### Files to Create
1. `/Users/les/Projects/mahavishnu/docs/ONEIRIC_OTEL_STORAGE.md` - Documentation
2. `/Users/les/Projects/mahavishnu/scripts/setup_otel_storage.sh` - Database setup script

## Implementation Order

1. Configuration updates (Task 1)
2. Dependency additions (Task 2)
3. Documentation creation (Task 4)
4. Adapter implementation (Task 3)
5. Testing and validation (Task 5)

## Notes

- All configurations follow Oneiric layered loading pattern
- Environment variable override: `MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING`
- Use async operations throughout for performance
- Implement proper error handling and resilience patterns
- Semantic search uses cosine similarity via pgvector
- Embedding model runs locally (no external API calls)
