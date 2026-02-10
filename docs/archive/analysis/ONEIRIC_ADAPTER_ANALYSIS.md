# Oneiric PostgreSQL Adapter Analysis

## Executive Summary

**Finding: Oneiric has comprehensive PostgreSQL and pgvector support built-in.**

Oneiric version 0.3.12 includes production-ready adapters for:
- **PostgreSQL database operations** (`oneiric.adapters.database.postgres`)
- **pgvector vector operations** (`oneiric.adapters.vector.pgvector`)

**Recommendation: USE Oneiric adapters instead of creating custom implementations.**

## Available Adapters

### 1. PostgreSQL Database Adapter

**Location:** `oneiric.adapters.database.postgres`

**Class:** `PostgresDatabaseAdapter`

**Settings:** `PostgresDatabaseSettings`

**Capabilities:**
- `sql` - Execute raw SQL queries
- `pool` - Connection pooling via asyncpg
- `transactions` - ACID transaction support

**Configuration:**
```python
from oneiric.adapters.database.postgres import PostgresDatabaseAdapter, PostgresDatabaseSettings

settings = PostgresDatabaseSettings(
    host="localhost",
    port=5432,
    user="postgres",
    password="secret",
    database="mydb",
    min_size=1,           # Minimum pool size
    max_size=10,          # Maximum pool size
    statement_timeout_ms=30000,
    ssl=False
)

adapter = PostgresDatabaseAdapter(settings)
await adapter.init()

# Execute queries
result = await adapter.execute("CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT)")
rows = await adapter.fetch_all("SELECT * FROM users")
row = await adapter.fetch_one("SELECT * FROM users WHERE id = $1", 1)

await adapter.cleanup()
```

**Key Features:**
- Async/await support via asyncpg
- Connection pooling with configurable min/max sizes
- SSL/TLS support
- Statement timeout configuration
- Lifecycle hooks (`init`, `health`, `cleanup`)

### 2. pgvector Adapter

**Location:** `oneiric.adapters.vector.pgvector`

**Class:** `PgvectorAdapter`

**Settings:** `PgvectorSettings`

**Capabilities:**
- `vector_search` - Vector similarity search
- `batch_operations` - Bulk insert/upsert operations
- `metadata_filtering` - JSONB metadata filtering
- `collections` - Multi-collection support
- `sql` - Direct SQL access when needed

**Configuration:**
```python
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument

settings = PgvectorSettings(
    host="localhost",
    port=5432,
    user="postgres",
    password="secret",
    database="mydb",
    db_schema="public",
    collection_prefix="vectors_",  # Prefix for collection tables
    ensure_extension=True,          # Auto-create pgvector extension
    default_dimension=1536,         # OpenAI ada-002 default
    default_distance_metric="cosine",  # cosine, euclidean, dot_product
    ivfflat_lists=100,             # IVFFlat index parameter
    max_connections=10,
    statement_timeout_ms=30000,
    ssl=False
)

adapter = PgvectorAdapter(settings)
await adapter.init()

# Create a collection
await adapter.create_collection(
    name="embeddings",
    dimension=1536,
    distance_metric="cosine"
)

# Insert documents
documents = [
    VectorDocument(
        id="doc1",
        vector=[0.1, 0.2, 0.3, ...],
        metadata={"category": "tech", "title": "AI Article"}
    ),
    VectorDocument(
        id="doc2",
        vector=[0.4, 0.5, 0.6, ...],
        metadata={"category": "tech", "title": "ML Tutorial"}
    )
]
ids = await adapter.insert("embeddings", documents)

# Vector similarity search
results = await adapter.search(
    collection="embeddings",
    query_vector=[0.1, 0.2, 0.3, ...],
    limit=10,
    filter_expr={"category": "tech"},  # Optional metadata filter
    include_vectors=False
)

# Upsert (insert or update)
await adapter.upsert("embeddings", documents)

# Get documents by IDs
docs = await adapter.get("embeddings", ["doc1", "doc2"], include_vectors=True)

# Count documents
count = await adapter.count("embeddings", filter_expr={"category": "tech"})

# Delete documents
await adapter.delete("embeddings", ["doc1"])

# Delete collection
await adapter.delete_collection("embeddings")

# List collections
collections = await adapter.list_collections()

await adapter.cleanup()
```

**Key Features:**

1. **Automatic Extension Management**
   - `ensure_extension=True` automatically creates pgvector extension
   - Registers vector codec with asyncpg

2. **Collection Management**
   - Collections = PostgreSQL tables with naming convention
   - Default prefix: `vectors_` (configurable)
   - Schema: `id TEXT PRIMARY KEY, embedding vector(N), metadata JSONB`

3. **Indexing**
   - Automatic IVFFlat index creation
   - Configurable `ivfflat_lists` parameter (default: 100)
   - Distance metric operators:
     - `cosine` → `<=>` operator (default)
     - `euclidean`/`l2` → `<->` operator
     - `dot_product`/`inner_product` → `<#>` operator

4. **Metadata Filtering**
   - JSONB metadata support
   - PostgreSQL `@>` operator for containment queries
   - Example: `filter_expr={"category": "tech"}` → `WHERE metadata @> '{"category": "tech"}'::jsonb`

5. **Batch Operations**
   - Configurable `batch_size` (default: 100)
   - Bulk insert/upsert with automatic ID generation (UUID4)

6. **Connection Pooling**
   - Uses asyncpg connection pool
   - Configurable `max_connections` (default: 10)
   - Automatic connection lifecycle management

7. **Safety Features**
   - Identifier sanitization (SQL injection prevention)
   - Safe identifier pattern validation
   - Automatic name normalization for collections

## Collection Usage Patterns

### Dynamic Collection Access

```python
# Access collections dynamically (like attributes)
collection = adapter.embeddings  # Access collection named "embeddings"

# Search via collection
results = await collection.search(
    query_vector=[...],
    limit=5
)

# Insert via collection
await collection.insert([
    VectorDocument(vector=[...], metadata={...})
])
```

### Transaction Support

```python
# Transaction context manager
async with adapter.transaction() as client:
    # Perform multiple operations in a transaction
    await adapter.insert("coll1", docs1)
    await adapter.insert("coll2", docs2)
    # Commit on success, rollback on error
```

## Architecture Comparison

### Oneiric pgvector Adapter vs Custom Implementation

| Feature | Oneiric pgvector | Custom Implementation |
|---------|------------------|----------------------|
| **Connection Pooling** | ✅ Built-in (asyncpg) | ❌ Must implement |
| **Lifecycle Management** | ✅ `init()`, `health()`, `cleanup()` | ❌ Must implement |
| **Error Handling** | ✅ Structured with LifecycleError | ❌ Must implement |
| **Metadata Filtering** | ✅ JSONB with `@>` operator | ❌ Must implement |
| **Collection Management** | ✅ Automatic table creation/indexing | ❌ Must implement |
| **Extension Management** | ✅ Auto-creates pgvector extension | ❌ Must implement |
| **Batch Operations** | ✅ Built-in batch insert/upsert | ❌ Must implement |
| **Transaction Support** | ✅ Context manager | ❌ Must implement |
| **Type Safety** | ✅ Pydantic models | ❌ Must implement |
| **Logging** | ✅ Structured logging via structlog | ❌ Must implement |
| **Health Checks** | ✅ Built-in health monitoring | ❌ Must implement |
| **Testing** | ✅ Production-tested in Oneiric | ❌ Must test yourself |
| **Maintenance** | ✅ Oneiric team updates | 🔴 You maintain it |

## Mahavishnu Integration Recommendations

### Option 1: Direct Use (Recommended)

**Best for:** Quick integration, standard vector operations

```python
# In mahavishnu/core/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument, VectorSearchResult

class VectorStore:
    def __init__(self, settings: PgvectorSettings):
        self.adapter = PgvectorAdapter(settings)

    async def initialize(self):
        await self.adapter.init()

    async def health_check(self) -> bool:
        return await self.adapter.health()

    async def cleanup(self):
        await self.adapter.cleanup()

    # Delegate to Oneiric adapter
    async def search_embeddings(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict | None = None
    ) -> list[VectorSearchResult]:
        return await self.adapter.search(
            collection="embeddings",
            query_vector=query_vector,
            limit=limit,
            filter_expr=filter_expr
        )
```

### Option 2: Wrapper with Mahavishnu-Specific Logic

**Best for:** Adding Mahavishnu-specific business logic, validation, or caching

```python
# In mahavishnu/core/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument, VectorSearchResult
from mahavishnu.core.config import MahavishnuSettings

class MahavishnuVectorStore:
    """Mahavishnu-specific vector store wrapper."""

    def __init__(self, app_settings: MahavishnuSettings):
        # Map Mahavishnu config to Oneiric settings
        self.settings = PgvectorSettings(
            host=app_settings.vector_db_host,
            port=app_settings.vector_db_port,
            user=app_settings.vector_db_user,
            password=app_settings.vector_db_password,
            database=app_settings.vector_db_name,
            collection_prefix="mahavishnu_",
            ensure_extension=True,
            default_dimension=1536
        )
        self.adapter = PgvectorAdapter(self.settings)
        self._cache = {}  # Optional caching layer

    async def initialize(self):
        await self.adapter.init()
        await self.adapter.create_collection(
            name="workflows",
            dimension=1536,
            distance_metric="cosine"
        )

    async def search_similar_workflows(
        self,
        query_embedding: list[float],
        limit: int = 10,
        tags: list[str] | None = None
    ) -> list[dict]:
        """Mahavishnu-specific workflow search with tag filtering."""
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

    async def index_workflow(self, workflow_id: str, embedding: list[float], metadata: dict):
        """Index a workflow with its embedding."""
        doc = VectorDocument(
            id=workflow_id,
            vector=embedding,
            metadata=metadata
        )
        await self.adapter.upsert("workflows", [doc])

    async def health_check(self) -> bool:
        return await self.adapter.health()

    async def cleanup(self):
        await self.adapter.cleanup()
```

### Configuration Integration

**Add to MahavishnuSettings:**

```python
# In mahavishnu/core/config.py
from pydantic import Field, SecretStr
from oneiric.adapters.vector.pgvector import PgvectorSettings

class MahavishnuSettings(MCPServerSettings):
    # Existing fields...

    # Vector database configuration (Oneiric-compatible)
    vector_db_enabled: bool = True
    vector_db_host: str = "localhost"
    vector_db_port: int = 5432
    vector_db_user: str = "postgres"
    vector_db_password: SecretStr | None = None
    vector_db_name: str = "mahavishnu"
    vector_db_schema: str = "public"
    vector_db_dimension: int = 1536
    vector_db_distance_metric: str = "cosine"

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
            collection_prefix="mahavishnu_",
            ensure_extension=True
        )
```

**Load from Oneiric config:**

```yaml
# In settings/mahavishnu.yaml
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
```

## Benefits of Using Oneiric Adapters

### 1. **Production-Ready**
- Battle-tested in Oneiric ecosystem
- Handles edge cases and error scenarios
- Proper connection lifecycle management

### 2. **Zero Maintenance**
- Oneiric team maintains and updates adapters
- Security patches and bug fixes included
- Feature additions benefit all users

### 3. **Consistent API**
- Same patterns across all adapters (vector, database, cache, etc.)
- Easy to swap implementations (e.g., pgvector → Pinecone)
- Unified lifecycle hooks (`init`, `health`, `cleanup`)

### 4. **Type Safety**
- Pydantic models for configuration
- Runtime validation
- IDE autocomplete support

### 5. **Observability**
- Structured logging via structlog
- Health check endpoints
- Metrics integration (via Oneiric observability)

### 6. **Resilience**
- Connection pooling
- Automatic retries (configurable)
- Graceful degradation

### 7. **Security**
- SecretStr for passwords
- SQL injection prevention (identifier sanitization)
- SSL/TLS support

## Migration Path from Custom Implementation

If you already have custom PostgreSQL/vector code:

### Step 1: Install Dependencies

```bash
# Already installed if you have oneiric
pip install oneiric[vector-pgvector]

# Or manually
pip install asyncpg pgvector
```

### Step 2: Update Configuration

```yaml
# settings/mahavishnu.yaml
adapters:
  vector_db:
    provider: pgvector
    settings:
      host: localhost
      port: 5432
      user: postgres
      password: ${VECTOR_DB_PASSWORD}
      database: mahavishnu
      schema: public
```

### Step 3: Replace Custom Implementation

```python
# OLD: Custom implementation
class CustomVectorStore:
    def __init__(self, connection_string: str):
        self.pool = await asyncpg.create_pool(connection_string)

    async def search(self, vector: list[float], limit: int):
        async with self.pool.acquire() as conn:
            await conn.fetch("SELECT ...")

# NEW: Oneiric adapter
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings

class VectorStore:
    def __init__(self, settings: PgvectorSettings):
        self.adapter = PgvectorAdapter(settings)

    async def search(self, vector: list[float], limit: int):
        return await self.adapter.search("embeddings", vector, limit)
```

### Step 4: Update Tests

```python
# OLD: Mock custom pool
@pytest.fixture
async def mock_pool():
    pool = Mock(asyncpg.create_pool)
    # ... complex setup

# NEW: Use Oneiric adapter directly
@pytest.fixture
async def vector_adapter():
    settings = PgvectorSettings(
        host="localhost",
        database="test_db"
    )
    adapter = PgvectorAdapter(settings)
    await adapter.init()
    yield adapter
    await adapter.cleanup()
```

## Dependencies

The Oneiric pgvector adapter requires:

```toml
# In pyproject.toml
[project.dependencies]
oneiric = "~0.3.12"  # Already installed
asyncpg = "~0.29.0"  # PostgreSQL async driver
pgvector = "~0.2.5"  # pgvector Python client

# Or install as extras
oneiric = {version = "~0.3.12", extras = ["vector-pgvector"]}
```

**Current installation status:**
- ✅ `oneiric` 0.3.12 already installed
- ✅ `asyncpg` available via Oneiric
- ❓ `pgvector` Python package needs verification

## Next Steps

### Immediate Actions

1. **Verify pgvector installation:**
   ```bash
   pip show pgvector
   pip install 'pgvector>=0.2.0'
   ```

2. **Test Oneiric adapter:**
   ```bash
   cd /Users/les/Projects/mahavishnu
   python -c "
   from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
   print('Oneiric pgvector adapter available!')
   "
   ```

3. **Create proof-of-concept:**
   - Write integration test using Oneiric adapter
   - Test connection, health check, CRUD operations
   - Verify vector search and metadata filtering

4. **Update implementation plan:**
   - Remove "Create custom pgvector adapter" task
   - Add "Integrate Oneiric pgvector adapter" task
   - Update configuration to use Oneiric patterns

### Recommended Architecture

```
mahavishnu/
├── core/
│   ├── vector_store.py          # Oneiric PgvectorAdapter wrapper
│   ├── config.py                # Add vector_db config fields
│   └── adapters/
│       └── vector_store.py      # Mahavishnu-specific business logic
└── tests/
    ├── integration/
    │   └── test_vector_store.py # Oneiric adapter tests
    └── unit/
        └── test_adapters.py     # Mock tests
```

## Conclusion

**USE Oneiric adapters - do NOT create custom implementations.**

Oneiric provides production-ready, well-maintained PostgreSQL and pgvector adapters that cover all requirements and more. The adapters include:

✅ Connection pooling
✅ Async/await support
✅ Lifecycle management
✅ Error handling
✅ Health checks
✅ Metadata filtering
✅ Batch operations
✅ Transaction support
✅ Type safety (Pydantic)
✅ Structured logging
✅ Security features

**Adopting Oneiric adapters will:**
- Save development time
- Reduce maintenance burden
- Improve reliability
- Leverage Oneiric ecosystem updates
- Maintain consistency with other adapters

The only reason to build a custom adapter would be if Oneiric lacks a specific feature you need. In that case, consider contributing to Oneiric instead of maintaining a fork.
