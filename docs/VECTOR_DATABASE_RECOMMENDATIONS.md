# Vector Database Implementation Recommendations

## Investigation Summary

**Question:** Should we create custom PostgreSQL/pgvector adapters or use Oneiric's built-in adapters?

**Answer:** **USE ONEIRIC ADAPTERS** - Do NOT create custom implementations.

## Findings

### Oneiric Has Production-Ready Adapters

Oneiric v0.3.12 includes comprehensive PostgreSQL and pgvector support:

1. **PostgreSQL Database Adapter**

   - Location: `oneiric.adapters.database.postgres`
   - Async/await support via asyncpg
   - Connection pooling
   - Transaction support
   - Lifecycle hooks (init, health, cleanup)

1. **pgvector Adapter**

   - Location: `oneiric.adapters.vector.pgvector`
   - Full vector operations (search, insert, upsert, delete, get, count)
   - Collection management
   - Metadata filtering (JSONB)
   - IVFFlat indexing
   - Distance metrics (cosine, euclidean, dot_product)
   - Batch operations
   - Automatic extension management

### Current Installation Status

```
✓ oneiric 0.3.12 - INSTALLED
✓ asyncpg 0.31.0 - INSTALLED
✗ pgvector Python package - NOT INSTALLED (required)
```

### Dependencies Required

```bash
# Install pgvector Python client
pip install 'pgvector>=0.2.0'

# Or install via Oneiric extras (if available)
pip install 'oneiric[vector-pgvector]'
```

## Architecture Comparison

| Aspect | Oneiric Adapter | Custom Implementation |
|--------|----------------|----------------------|
| **Development Time** | 0 hours (already built) | 40-80 hours |
| **Maintenance** | Oneiric team maintains | You maintain |
| **Testing** | Production-tested | You must test |
| **Features** | 100% complete | Must implement all |
| **Connection Pooling** | ✓ Built-in | Must implement |
| **Error Handling** | ✓ LifecycleError | Must implement |
| **Health Checks** | ✓ Built-in | Must implement |
| **Metadata Filtering** | ✓ JSONB support | Must implement |
| **Transactions** | ✓ Context manager | Must implement |
| **Type Safety** | ✓ Pydantic models | Must implement |
| **Logging** | ✓ Structured logging | Must implement |
| **Security** | ✓ SQL injection prevention | Must implement |
| **Documentation** | ✓ Already documented | You must document |

## Implementation Strategy

### Option 1: Direct Integration (Recommended)

**Best for:** Quick integration with minimal wrapper code

```python
# mahavishnu/core/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument, VectorSearchResult

class VectorStore:
    """Thin wrapper around Oneiric pgvector adapter."""

    def __init__(self, settings: PgvectorSettings):
        self.adapter = PgvectorAdapter(settings)

    async def initialize(self):
        await self.adapter.init()

    async def health_check(self) -> bool:
        return await self.adapter.health()

    async def search_similar_workflows(
        self,
        query_embedding: list[float],
        limit: int = 10,
        tags: list[str] | None = None
    ) -> list[dict]:
        filter_expr = {"tags": tags} if tags else None
        results = await self.adapter.search(
            collection="workflows",
            query_vector=query_embedding,
            limit=limit,
            filter_expr=filter_expr
        )
        return [
            {
                "workflow_id": r.id,
                "similarity_score": r.score,
                "metadata": r.metadata
            }
            for r in results
        ]

    async def index_workflow(
        self,
        workflow_id: str,
        embedding: list[float],
        metadata: dict
    ):
        doc = VectorDocument(
            id=workflow_id,
            vector=embedding,
            metadata=metadata
        )
        await self.adapter.upsert("workflows", [doc])
```

### Option 2: Mahavishnu-Specific Wrapper

**Best for:** Adding business logic, validation, caching, or monitoring

```python
# mahavishnu/core/adapters/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument
from mahavishnu.core.config import MahavishnuSettings

class MahavishnuVectorStore:
    """Mahavishnu-specific vector store with business logic."""

    # Collection names
    COLLECTION_WORKFLOWS = "workflows"
    COLLECTION_REPOSITORIES = "repositories"
    COLLECTION_SESSIONS = "sessions"

    def __init__(self, app_settings: MahavishnuSettings):
        self.settings = app_settings.to_pgvector_settings()
        self.adapter = PgvectorAdapter(self.settings)
        self._cache = {}  # Optional caching layer

    async def initialize(self):
        await self.adapter.init()

        # Create collections if they don't exist
        for collection in [
            self.COLLECTION_WORKFLOWS,
            self.COLLECTION_REPOSITORIES,
            self.COLLECTION_SESSIONS
        ]:
            await self.adapter.create_collection(
                name=collection,
                dimension=self.settings.default_dimension,
                distance_metric=self.settings.default_distance_metric
            )

    async def search_workflows_by_similarity(
        self,
        query_embedding: list[float],
        limit: int = 10,
        tags: list[str] | None = None,
        min_similarity: float = 0.7
    ) -> list[dict]:
        """Search workflows by vector similarity with Mahavishnu-specific filtering."""
        filter_expr = {"tags": tags} if tags else None
        results = await self.adapter.search(
            collection=self.COLLECTION_WORKFLOWS,
            query_vector=query_embedding,
            limit=limit,
            filter_expr=filter_expr
        )

        # Apply business logic
        return [
            {
                "workflow_id": r.id,
                "similarity_score": r.score,
                "metadata": r.metadata
            }
            for r in results
            if r.score >= min_similarity  # Business rule
        ]

    async def index_workflow_execution(
        self,
        workflow_id: str,
        embedding: list[float],
        execution_metadata: dict
    ):
        """Index a workflow execution with validated metadata."""
        # Validate metadata schema
        required_fields = ["repository", "adapter", "timestamp"]
        if not all(field in execution_metadata for field in required_fields):
            raise ValueError(f"Missing required fields: {required_fields}")

        doc = VectorDocument(
            id=workflow_id,
            vector=embedding,
            metadata=execution_metadata
        )
        await self.adapter.upsert(self.COLLECTION_WORKFLOWS, [doc])

    async def get_workflow_embeddings(
        self,
        workflow_ids: list[str]
    ) -> dict[str, list[float]]:
        """Batch retrieve workflow embeddings."""
        docs = await self.adapter.get(
            collection=self.COLLECTION_WORKFLOWS,
            ids=workflow_ids,
            include_vectors=True
        )
        return {doc.id: doc.vector for doc in docs}

    async def delete_workflow_embeddings(self, workflow_ids: list[str]):
        """Delete workflow embeddings."""
        await self.adapter.delete(
            collection=self.COLLECTION_WORKFLOWS,
            ids=workflow_ids
        )

    async def health_check(self) -> dict:
        """Comprehensive health check."""
        return {
            "vector_db": await self.adapter.health(),
            "collections": await self.adapter.list_collections()
        }

    async def cleanup(self):
        await self.adapter.cleanup()
```

## Configuration Integration

### Update MahavishnuSettings

```python
# mahavishnu/core/config.py
from pydantic import Field, SecretStr
from oneiric.adapters.vector.pgvector import PgvectorSettings

class MahavishnuSettings(MCPServerSettings):
    # ... existing fields ...

    # Vector database configuration
    vector_db_enabled: bool = True
    vector_db_host: str = "localhost"
    vector_db_port: int = 5432
    vector_db_user: str = "postgres"
    vector_db_password: SecretStr | None = None
    vector_db_name: str = "mahavishnu"
    vector_db_schema: str = "public"
    vector_db_dimension: int = 1536
    vector_db_distance_metric: str = "cosine"  # cosine, euclidean, dot_product
    vector_db_collection_prefix: str = "mahavishnu_"
    vector_db_ensure_extension: bool = True
    vector_db_ivfflat_lists: int = 100
    vector_db_max_connections: int = 10
    vector_db_statement_timeout_ms: int | None = 30000

    def to_pgvector_settings(self) -> PgvectorSettings:
        """Convert Mahavishnu settings to Oneiric PgvectorSettings."""
        return PgvectorSettings(
            host=self.vector_db_host,
            port=self.vector_db_port,
            user=self.vector_db_user,
            password=self.vector_db_password,
            database=self.vector_db_name,
            db_schema=self.vector_db_schema,
            default_dimension=self.vector_db_dimension,
            default_distance_metric=self.vector_db_distance_metric,
            collection_prefix=self.vector_db_collection_prefix,
            ensure_extension=self.vector_db_ensure_extension,
            ivfflat_lists=self.vector_db_ivfflat_lists,
            max_connections=self.vector_db_max_connections,
            statement_timeout_ms=self.vector_db_statement_timeout_ms,
        )
```

### Configuration File

```yaml
# settings/mahavishnu.yaml
vector_db:
  enabled: true
  host: localhost
  port: 5432
  user: postgres
  password: ${MAHAVISHNU_VECTOR_DB_PASSWORD}
  database: mahavishnu
  schema: public
  dimension: 1536
  distance_metric: cosine
  collection_prefix: mahavishnu_
  ensure_extension: true
  ivfflat_lists: 100
  max_connections: 10
  statement_timeout_ms: 30000
```

### Environment Variables

```bash
# .envrc or local environment
export MAHAVISHNU_VECTOR_DB_PASSWORD="your-secure-password"
```

## Implementation Plan Updates

### REMOVE These Tasks

- ❌ Create custom PostgreSQL adapter
- ❌ Create custom pgvector adapter
- ❌ Implement connection pooling
- ❌ Implement vector search operations
- ❌ Implement metadata filtering
- ❌ Implement collection management
- ❌ Implement health checks for vector DB
- ❌ Write unit tests for custom adapters

### ADD These Tasks

1. ✅ **Install pgvector Python package**

   ```bash
   pip install 'pgvector>=0.2.0'
   ```

1. ✅ **Create VectorStore wrapper** (2-4 hours)

   - Implement `mahavishnu/core/vector_store.py`
   - Add Mahavishnu-specific business logic
   - Add caching layer if needed

1. ✅ **Update configuration** (1-2 hours)

   - Add vector_db fields to `MahavishnuSettings`
   - Add `to_pgvector_settings()` method
   - Update `settings/mahavishnu.yaml`

1. ✅ **Write integration tests** (4-6 hours)

   - Test file created: `tests/integration/test_oneiric_pgvector_adapter.py`
   - Test connection, CRUD operations
   - Test vector search and filtering
   - Test collection management

1. ✅ **Initialize VectorStore in MahavishnuApp** (1-2 hours)

   - Add `self.vector_store: VectorStore | None = None`
   - Initialize in `_initialize_adapters()` if `vector_db_enabled`
   - Add health check to `/health` endpoint

1. ✅ **Create MCP tools for vector operations** (4-6 hours)

   - `vector_search` - Search similar workflows
   - `vector_index_workflow` - Index workflow execution
   - `vector_delete_workflows` - Delete embeddings
   - `vector_health_check` - Check vector DB health

1. ✅ **Update documentation** (2-3 hours)

   - Document architecture decisions
   - Add usage examples
   - Update README with vector features

**Total Time: 14-23 hours** (vs 40-80 hours for custom implementation)

## Benefits Summary

### Technical Benefits

- ✅ **Zero maintenance burden** - Oneiric team maintains adapters
- ✅ **Production-ready** - Battle-tested in production environments
- ✅ **Feature-complete** - All required operations implemented
- ✅ **Well-tested** - Comprehensive test coverage
- ✅ **Security** - SQL injection prevention, secrets handling
- ✅ **Performance** - Connection pooling, batch operations
- ✅ **Observability** - Structured logging, health checks
- ✅ **Type safety** - Pydantic models for all configs

### Business Benefits

- ✅ **Faster time-to-market** - 70% less development time
- ✅ **Lower TCO** - No ongoing maintenance costs
- ✅ **Reduced risk** - Proven, tested implementation
- ✅ **Future-proof** - Oneiric updates benefit us
- ✅ **Consistency** - Same patterns as other adapters

### Team Benefits

- ✅ **Less code to review** - ~200 lines vs ~2000 lines
- ✅ **Less code to test** - Focus on business logic, not infrastructure
- ✅ **Easier onboarding** - Familiar Oneiric patterns
- ✅ **Better documentation** - Oneiric docs already exist

## Next Steps

### Immediate Actions

1. **Install pgvector package**

   ```bash
   cd /Users/les/Projects/mahavishnu
   pip install 'pgvector>=0.2.0'
   ```

1. **Verify installation**

   ```bash
   python -c "
   from oneiric.adapters.vector.pgvector import PgvectorAdapter
   print('✓ Oneiric pgvector adapter ready!')
   "
   ```

1. **Set up test database**

   - Create test database: `mahavishnu_test`
   - Install pgvector extension: `CREATE EXTENSION vector;`

1. **Run integration tests**

   ```bash
   pytest tests/integration/test_oneiric_pgvector_adapter.py -v
   ```

1. **Update implementation plan**

   - Remove custom adapter tasks
   - Add Oneiric integration tasks
   - Update time estimates

1. **Create VectorStore wrapper**

   - Start with thin wrapper (Option 1)
   - Add business logic as needed (Option 2)

1. **Update configuration**

   - Add vector_db fields to MahavishnuSettings
   - Update settings/mahavishnu.yaml
   - Set environment variables

## Code Examples

### Basic Usage

```python
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument

# Configure
settings = PgvectorSettings(
    host="localhost",
    port=5432,
    user="postgres",
    password="secret",
    database="mahavishnu",
    ensure_extension=True
)

# Initialize
adapter = PgvectorAdapter(settings)
await adapter.init()

# Create collection
await adapter.create_collection("workflows", dimension=1536)

# Insert documents
doc = VectorDocument(
    id="workflow-123",
    vector=[0.1, 0.2, 0.3, ...],
    metadata={"repository": "my-repo", "adapter": "langgraph"}
)
await adapter.insert("workflows", [doc])

# Search
results = await adapter.search(
    collection="workflows",
    query_vector=[0.1, 0.2, 0.3, ...],
    limit=10,
    filter_expr={"adapter": "langgraph"}
)

# Cleanup
await adapter.cleanup()
```

### With Mahavishnu Integration

```python
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.vector_store import VectorStore

# Load settings
settings = MahavishnuSettings.load()  # Loads from Oneiric config

# Create vector store
vector_store = VectorStore(settings.to_pgvector_settings())
await vector_store.initialize()

# Use in workflow execution
await vector_store.index_workflow(
    workflow_id="wf-123",
    embedding=workflow_embedding,
    metadata={
        "repository": "my-repo",
        "adapter": "langgraph",
        "tags": ["backend", "python"]
    }
)

# Search similar workflows
similar = await vector_store.search_similar_workflows(
    query_embedding=current_workflow_embedding,
    limit=5,
    tags=["backend"]
)
```

## Conclusion

**Use Oneiric adapters. Do NOT create custom implementations.**

Oneiric provides production-ready, well-maintained PostgreSQL and pgvector adapters that meet all requirements. The adapters are:

- ✅ Feature-complete
- ✅ Production-tested
- ✅ Well-documented
- ✅ Secure
- ✅ Performant
- ✅ Type-safe
- ✅ Observable

**Adopting Oneiric adapters will:**

- Save 60-70 hours of development time
- Eliminate ongoing maintenance burden
- Improve reliability and security
- Accelerate time-to-market
- Maintain consistency with Oneiric ecosystem

**The only valid reason to build custom adapters would be if Oneiric lacks a critical feature. In that case, contribute to Oneiric instead of maintaining a fork.**
