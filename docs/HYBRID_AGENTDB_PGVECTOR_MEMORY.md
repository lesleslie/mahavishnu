# Hybrid Memory System: AgentDB + pgvector + Oneiric

**Architecture**: Hot data (AgentDB) + Warm/cold data (pgvector) + GCS backup

**Date**: 2025-01-23
**Status**: ✅ AgentDB adapter created for Oneiric

---

## 🎯 Why Hybrid?

**AgentDB = Hot Cache**:
- ⚡ **Sub-1ms latency** for active agent memory
- 🧠 **Purpose-built for AI agents** with cognitive patterns
- 🔄 **QUIC synchronization** across nodes
- 📍 **In-memory** for blazing-fast access

**pgvector + PostgreSQL = Persistent Archive**:
- 💾 **30+ years of production reliability**
- 🔒 **Battle-tested backups** (pg_dump + WAL archiving)
- ☁️ **Well-documented GCS integration**
- 📊 **Mature ecosystem** (ORMs, monitoring, GUIs)

**Best of Both Worlds**:
```
┌─────────────────────────────────────────────────┐
│  Your Application (Mahavishnu)                  │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │  Oneiric Lifecycle Manager               │   │
│  │  ├─ vector: agentdb (primary, hot)      │   │
│  │  └─ vector: pgvector (backup, cold)     │   │
│  └──────────────────────────────────────────┘   │
│           │                      │               │
│           ▼                      ▼               │
│  ┌──────────────┐      ┌─────────────┐          │
│  │  AgentDB     │      │  pgvector   │          │
│  │  (Hot data)  │◀────▶│  (Archive)  │          │
│  │  - Active    │ Sync │  - History  │          │
│  │  - Recent    │      │  - Backups  │          │
│  └──────────────┘      └──────┬──────┘          │
│                                  │               │
│                                  ▼               │
│                     Google Cloud Storage          │
│                     (pg_dump + gsutil)           │
└─────────────────────────────────────────────────┘
```

---

## ✅ Oneiric AgentDB Adapter Created!

**File**: `/Users/les/Projects/oneiric/oneiric/adapters/vector/agentdb.py`

**Features**:
- ✅ Full `VectorBase` implementation
- ✅ MCP client integration (AgentDB runs as MCP server)
- ✅ Lifecycle hooks (`init()`, `health()`, `cleanup()`)
- ✅ All vector operations (search, insert, upsert, delete, get, count)
- ✅ Collection management
- ✅ Configurable settings (Pydantic V2)
- ✅ Structured logging with Oneiric patterns
- ✅ Registered in `bootstrap.py`

**Capabilities**:
- `vector_search` - Semantic similarity search
- `batch_operations` - Bulk inserts/updates
- `metadata_filtering` - Filter by metadata fields
- `real_time` - Sub-1ms latency
- `quic_sync` - Multi-node synchronization
- `agent_optimized` - Purpose-built for AI agents

---

## 🚀 Setup & Installation

### Step 1: Install AgentDB

```bash
# Install AgentDB via npm (Node.js required)
npm install -g agentdb

# Or use npx (runs without installation)
npx agentdb@latest

# Verify installation
agentdb --version
```

### Step 2: Start AgentDB MCP Server

```bash
# Start AgentDB as MCP server
agentdb mcp start

# Or via npx
npx agentdb@latest mcp start

# Default: stdio://agentdb
# Optional: HTTP server on specific port
agentdb mcp start --port 3000 --transport http
```

### Step 3: Install pgvector + PostgreSQL

```bash
# Install PostgreSQL + pgvector via Homebrew
brew install postgresql@16 pgvector
brew services start postgresql@16

# Initialize database
psql postgres -c "CREATE DATABASE memory_db;"
psql memory_db -c "CREATE EXTENSION vector;"
```

### Step 4: Configure Oneiric

Create `settings/mahavishnu.yaml`:

```yaml
# Mahavishnu configuration with hybrid memory
adapters:
  vector:
    # Primary: AgentDB for hot data
    provider: agentdb
    settings:
      mcp_server_url: "stdio://agentdb"
      in_memory: true
      cache_size_mb: 256
      default_collection: "agent_memory"

    # Backup: pgvector for persistent storage
    backup:
      provider: pgvector
      settings:
        host: "localhost"
        port: 5432
        user: "postgres"
        password: "${POSTGRES_PASSWORD}"
        database: "memory_db"
        default_collection: "agent_archive"

# Storage for GCS backups
storage:
  type: "gcs"
  bucket: "mahavishnu-memory-backup"
  prefix: "agent-memory/"
  credentials:
    type: "service-account"
    path: "/path/to/service-account.json"
```

---

## 🐍 Python Implementation

### Basic Usage

```python
"""Hybrid memory system with AgentDB + pgvector via Oneiric."""
import asyncio
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.adapters.vector import VectorDocument


async def hybrid_memory_demo():
    """Demonstrate hybrid AgentDB + pgvector setup."""

    # Initialize Oneiric
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)

    # Activate AgentDB (primary, hot data)
    agentdb = await lifecycle.activate("adapter", "vector", provider="agentdb")

    # Activate pgvector (backup, cold data)
    pgvector = await lifecycle.activate(
        "adapter", "vector", provider="pgvector"
    )

    # Create collection
    await agentdb.create_collection(
        name="agent_memories",
        dimension=1536,
        distance_metric="cosine",
    )

    # Insert into AgentDB (hot)
    hot_doc = VectorDocument(
        id="mem_1",
        vector=[0.1, 0.2, 0.3, ...],  # Your embedding
        metadata={
            "type": "decision",
            "content": "Chose PostgreSQL for ACID compliance",
            "timestamp": "2025-01-23T10:00:00Z",
        },
    )

    doc_id = await agentdb.insert("agent_memories", [hot_doc])
    print(f"✅ Inserted into AgentDB: {doc_id}")

    # Search from AgentDB (sub-1ms)
    query = [0.15, 0.25, 0.35, ...]
    results = await agentdb.search(
        collection="agent_memories",
        query_vector=query,
        limit=5,
    )
    print(f"✅ Search results from AgentDB: {len(results)} hits")

    # Backup to pgvector (persistent)
    await pgvector.create_collection(
        name="agent_memories",
        dimension=1536,
        distance_metric="cosine",
    )
    await pgvector.insert("agent_memories", [hot_doc])
    print("✅ Backed up to pgvector")

    # Cleanup
    await lifecycle.cleanup_all()


if __name__ == "__main__":
    asyncio.run(hybrid_memory_demo())
```

---

## 🔄 Auto-Sync Strategy

### Option 1: Periodic Sync (Cron/Launchd)

```python
"""Periodic sync from AgentDB to pgvector."""
import asyncio
from datetime import datetime


async def sync_agentdb_to_pgvector():
    """Sync recent memories from AgentDB to pgvector."""

    # Get recent documents from AgentDB
    agentdb = await lifecycle.activate("adapter", "vector", provider="agentdb")
    pgvector = await lifecycle.activate("adapter", "vector", provider="pgvector")

    # Fetch recent docs (last hour)
    recent_docs = await agentdb.get(
        collection="agent_memories",
        ids=[],  # Get all (or use timestamp filter)
        include_vectors=True,
    )

    # Backup to pgvector
    if recent_docs:
        await pgvector.upsert("agent_memories", recent_docs)
        print(f"✅ Synced {len(recent_docs)} memories to pgvector")

    # Backup pgvector to GCS
    await backup_pgvector_to_gcs()


async def backup_pgvector_to_gcs():
    """Backup pgvector database to GCS."""
    import subprocess
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"memory_backup_{timestamp}.sql.gz"

    # pg_dump + gzip
    subprocess.run(
        f"pg_dump -U postgres memory_db | gzip > /tmp/{backup_file}",
        shell=True,
        check=True,
    )

    # Upload to GCS via gsutil
    subprocess.run(
        f"gsutil cp /tmp/{backup_file} gs://mahavishnu-memory-backup/",
        shell=True,
        check=True,
    )

    print(f"✅ Backed up to GCS: {backup_file}")


# Schedule with macOS launchd
# Load: ~/Library/LaunchAgents/com.mahavishnu.memory_sync.plist
# Run: Hourly (3600 seconds)
```

### Option 2: Write-Through Cache

```python
"""Write-through cache: Write to both AgentDB and pgvector."""
async def store_memory_with_backup(
    content: str,
    embedding: list[float],
    metadata: dict,
):
    """Store memory in AgentDB + pgvector simultaneously."""

    agentdb = await lifecycle.activate("adapter", "vector", provider="agentdb")
    pgvector = await lifecycle.activate("adapter", "vector", provider="pgvector")

    doc = VectorDocument(
        vector=embedding,
        metadata={**metadata, "content": content},
    )

    # Write to both (parallel)
    await asyncio.gather(
        agentdb.insert("agent_memories", [doc]),
        pgvector.insert("agent_memories", [doc]),
    )

    print("✅ Stored in AgentDB + pgvector")
```

---

## 📊 Configuration Examples

### Development (Local)

```yaml
# settings/local.yaml
adapters:
  vector:
    provider: agentdb
    settings:
      mcp_server_url: "stdio://agentdb"
      in_memory: true  # No persistence
      cache_size_mb: 128

storage:
  type: "local"  # No cloud backup in dev
  path: "./data/memory"
```

### Production (Hybrid + GCS)

```yaml
# settings/production.yaml
adapters:
  vector:
    provider: agentdb
    settings:
      mcp_server_url: "http://agentdb:3000"  # Docker network
      in_memory: true
      cache_size_mb: 512
      sync_enabled: true
      sync_nodes:
        - "agentdb-node2:3000"
        - "agentdb-node3:3000"

    backup:
      provider: pgvector
      settings:
        host: "${POSTGRES_HOST}"
        port: 5432
        user: "${POSTGRES_USER}"
        password: "${POSTGRES_PASSWORD}"
        database: "memory_db"

storage:
  type: "gcs"
  bucket: "mahavishnu-memory-prod"
  prefix: "agent-memory/"
  credentials:
    type: "service-account"
    path: "${GCS_CREDENTIALS_PATH}"
```

---

## 🔍 Monitoring & Observability

### Health Checks

```python
"""Monitor hybrid memory system health."""
async def check_memory_system_health():
    """Check health of AgentDB + pgvector."""

    lifecycle = LifecycleManager(resolver)

    # Check AgentDB
    agentdb_healthy = await lifecycle.probe_instance_health(
        "adapter", "vector", provider="agentdb"
    )
    print(f"AgentDB: {'✅ Healthy' if agentdb_healthy else '❌ Unhealthy'}")

    # Check pgvector
    pgvector_healthy = await lifecycle.probe_instance_health(
        "adapter", "vector", provider="pgvector"
    )
    print(f"pgvector: {'✅ Healthy' if pgvector_healthy else '❌ Unhealthy'}")

    return agentdb_healthy and pgvector_healthy
```

### Metrics

```python
"""Track memory system metrics."""
from oneiric.adapters.monitoring import OTLPObservabilityAdapter


async def track_memory_metrics():
    """Export metrics to OpenTelemetry."""

    # Get adapter stats
    agentdb = await lifecycle.activate("adapter", "vector", provider="agentdb")
    pgvector = await lifecycle.activate("adapter", "vector", provider="pgvector")

    # Count documents
    agentdb_count = await agentdb.count("agent_memories")
    pgvector_count = await pgvector.count("agent_memories")

    # Export to OTLP
    otlp = await lifecycle.activate("monitoring", "otlp")
    await otlp.export_metrics(
        {
            "agentdb_document_count": agentdb_count,
            "pgvector_document_count": pgvector_count,
            "sync_lag_seconds": ...,
        }
    )
```

---

## 🧪 Testing

```python
"""Test hybrid memory system."""
import pytest
from oneiric.adapters.vector import VectorDocument


@pytest.mark.asyncio
async def test_hybrid_memory_insert_and_search():
    """Test inserting into AgentDB and searching from both."""

    # Insert into AgentDB
    doc = VectorDocument(
        id="test_1",
        vector=[0.1] * 1536,
        metadata={"test": True},
    )

    doc_id = await agentdb.insert("test_collection", [doc])
    assert len(doc_id) == 1

    # Sync to pgvector
    await pgvector.insert("test_collection", [doc])

    # Search from AgentDB (hot)
    agentdb_results = await agentdb.search(
        "test_collection",
        query_vector=[0.1] * 1536,
        limit=1,
    )
    assert len(agentdb_results) == 1
    assert agentdb_results[0].id == "test_1"

    # Search from pgvector (backup)
    pgvector_results = await pgvector.search(
        "test_collection",
        query_vector=[0.1] * 1536,
        limit=1,
    )
    assert len(pgvector_results) == 1
    assert pgvector_results[0].id == "test_1"
```

---

## 💡 Best Practices

### 1. When to Use AgentDB (Hot)
- ✅ **Active agent memory** (current session, recent decisions)
- ✅ **Frequently accessed data** (user preferences, active tasks)
- ✅ **Real-time coordination** (multi-agent sync)
- ✅ **Sub-ms latency required**

### 2. When to Use pgvector (Cold)
- ✅ **Long-term storage** (historical decisions, audit trail)
- ✅ **Backup/disaster recovery** (GCS integration)
- ✅ **Analytics and reporting** (SQL queries on metadata)
- ✅ **Compliance and retention** (WAL archiving)

### 3. Sync Strategy
- **Write-through**: Write to both immediately (consistency over latency)
- **Write-back**: Write to AgentDB, async sync to pgvector (latency over consistency)
- **Periodic**: Cron job syncs every N minutes (simple, eventual consistency)

### 4. Data Lifecycle
```
New Memory
    ↓
AgentDB (hot, in-memory)
    ↓ (after 1 hour or session end)
pgvector (warm, PostgreSQL)
    ↓ (daily backup)
GCS (cold, archived)
```

---

## 🔗 Resources

- **Oneiric Vector Adapters**: `/Users/les/Projects/oneiric/docs/analysis/VECTOR_ADAPTERS.md`
- **AgentDB Documentation**: [agentdb.ruv.io](https://agentdb.ruv.io/)
- **AgentDB NPM**: [npmjs.com/package/agentdb](https://www.npmjs.com/package/agentdb)
- **Claude Flow (AgentDB integration)**: [github.com/ruvnet/claude-flow](https://github.com/ruvnet/claude-flow)
- **pgvector GitHub**: [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)

---

## Summary

**✅ AgentDB adapter added to Oneiric!**

**Hybrid Architecture**:
- **AgentDB**: Hot data, sub-1ms access, agent-optimized
- **pgvector**: Persistent archive, GCS backups, SQL queries
- **Oneiric**: Unified lifecycle management for both
- **GCS**: Long-term cloud storage via pg_dump + gsutil

**Benefits**:
- ⚡ **Blazing fast** active memory (AgentDB)
- 💾 **Production backups** (pgvector + GCS)
- 🔄 **Flexible sync** strategies
- 🛠️ **Oneiric integration** (lifecycle, health checks, hot-swapping)

**Next Steps**:
1. Install AgentDB (`npm install -g agentdb`)
2. Start AgentDB MCP server
3. Test Oneiric AgentDB adapter
4. Implement sync strategy (write-through or periodic)
5. Set up GCS backups for pgvector

The hybrid approach gives you the **best of both worlds**! 🚀
