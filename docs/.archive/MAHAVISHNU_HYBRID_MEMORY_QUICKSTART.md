# Mahavishnu Hybrid Memory Quickstart

**AgentDB + pgvector + Oneiric integration for Mahavishnu**

______________________________________________________________________

## 🎯 What We Just Did

### ✅ Created Oneiric AgentDB Adapter

**Files Created/Modified**:

1. `/Users/les/Projects/oneiric/oneiric/adapters/vector/agentdb.py` (NEW)
1. `/Users/les/Projects/oneiric/oneiric/adapters/vector/__init__.py` (MODIFIED)
1. `/Users/les/Projects/oneiric/oneiric/adapters/bootstrap.py` (MODIFIED)

**Adapter Features**:

- ✅ Full `VectorBase` implementation
- ✅ MCP client integration (AgentDB runs as MCP server)
- ✅ Lifecycle hooks (`init()`, `health()`, `cleanup()`)
- ✅ All vector operations (search, insert, upsert, delete, get, count)
- ✅ Collection management
- ✅ Configurable via Pydantic V2 settings
- ✅ Structured logging with Oneiric patterns

### 📚 Documentation Created

1. **`docs/HYBRID_AGENTDB_PGVECTOR_MEMORY.md`**
   - Complete hybrid architecture guide
   - Setup instructions
   - Python implementation examples
   - Sync strategies (write-through, write-back, periodic)
   - Configuration examples (dev/prod)
   - Monitoring and testing patterns

______________________________________________________________________

## 🚀 Quick Start (5 Minutes)

### 1. Install AgentDB

```bash
npm install -g agentdb
agentdb --version
```

### 2. Start AgentDB MCP Server

```bash
agentdb mcp start
```

### 3. Configure Mahavishnu

Create `settings/local.yaml`:

```yaml
adapters:
  vector:
    # Primary: AgentDB (hot, fast)
    provider: agentdb
    settings:
      mcp_server_url: "stdio://agentdb"
      in_memory: true
      cache_size_mb: 256
      default_collection: "agent_memories"

storage:
  # Backup: GCS (persistent)
  type: "gcs"
  bucket: "mahavishnu-memory-backup"
  prefix: "memories/"
```

### 4. Test with Mahavishnu

```python
"""Mahavishnu memory integration test."""
from mahavishnu.core.app import MahavishnuApp
from oneiric.adapters.vector import VectorDocument


async def test_memory():
    """Test hybrid memory system."""

    app = MahavishnuApp()

    # Store memory in AgentDB (via Oneiric)
    doc = VectorDocument(
        vector=[0.1, 0.2, 0.3, ...],  # Your embedding
        metadata={
            "type": "decision",
            "content": "Chose PostgreSQL for ACID compliance",
            "timestamp": "2025-01-23T10:00:00Z",
        },
    )

    # Get AgentDB adapter
    adapter = await app.lifecycle.activate("adapter", "vector")

    # Store
    doc_id = await adapter.insert("agent_memories", [doc])
    print(f"✅ Stored: {doc_id}")

    # Search
    results = await adapter.search(
        collection="agent_memories",
        query_vector=[0.1, 0.2, 0.3, ...],
        limit=5,
    )
    print(f"✅ Found: {len(results)} memories")
```

______________________________________________________________________

## 🏗️ Architecture

```
Mahavishnu Orchestrator
    │
    ├─ Oneiric Configuration
    │   └─ settings/mahavishnu.yaml
    │
    ├─ Lifecycle Manager
    │   ├─ vector: agentdb (primary, hot)
    │   └─ vector: pgvector (backup, cold)
    │
    └─ Adapters
        ├─ AgentDB (sub-1ms latency)
        │   └─ MCP client integration
        │
        └─ pgvector (persistent)
            ├─ PostgreSQL 16
            └─ GCS backup (pg_dump + gsutil)
```

______________________________________________________________________

## 📊 Hybrid Strategy

### Hot Data (AgentDB)

- **Use for**: Active agent memory, recent decisions, frequently accessed
- **Access**: Sub-1ms latency
- **Storage**: In-memory (configurable disk)
- **Sync**: QUIC multi-node

### Cold Data (pgvector + GCS)

- **Use for**: Long-term storage, audit trail, backups
- **Access**: Fast (PostgreSQL) but slower than AgentDB
- **Storage**: PostgreSQL + GCS
- **Backup**: Automated via pg_dump + gsutil

### Sync Patterns

**Option 1: Write-Through** (Consistency over latency)

```python
# Write to both immediately
await asyncio.gather(
    agentdb.insert(collection, [doc]),
    pgvector.insert(collection, [doc]),
)
```

**Option 2: Write-Back** (Latency over consistency)

```python
# Write to AgentDB first
await agentdb.insert(collection, [doc])

# Async sync to pgvector
asyncio.create_task(sync_to_pgvector(collection, doc))
```

**Option 3: Periodic** (Simple, eventual consistency)

```bash
# Cron job every hour
0 * * * * /usr/local/bin/sync_memory.sh
```

______________________________________________________________________

## 🔧 Oneiric Integration

### Adapter Registration

AgentDB is now registered in Oneiric's bootstrap system:

```python
# /Users/les/Projects/oneiric/oneiric/adapters/bootstrap.py
from .vector import AgentDBAdapter, PineconeAdapter, QdrantAdapter

def builtin_adapter_metadata() -> list[AdapterMetadata]:
    return [
        # ... other adapters ...
        AgentDBAdapter.metadata,  # ✅ Added
        PineconeAdapter.metadata,
        QdrantAdapter.metadata,
        # ...
    ]
```

### Usage in Mahavishnu

```python
from mahavishnu.core.app import MahavishnuApp

# Initialize Mahavishnu
app = MahavishnuApp()

# Get AgentDB adapter (Oneiric manages lifecycle)
agentdb = await app.lifecycle.activate("adapter", "vector")

# Use it!
results = await agentdb.search(...)
```

______________________________________________________________________

## 💡 Next Steps

### Immediate

1. ✅ **AgentDB adapter created** in Oneiric
1. 📝 **Documentation created** for hybrid approach
1. 🧪 **Test locally** with AgentDB MCP server

### Implementation

1. **Install AgentDB**: `npm install -g agentdb`
1. **Start MCP server**: `agentdb mcp start`
1. **Configure Mahavishnu**: Add AgentDB settings to `oneiric.yaml`
1. **Test integration**: Run memory operations via Mahavishnu
1. **Add pgvector backup**: Install PostgreSQL + pgvector for persistence

### Production

1. **Set up sync strategy**: Choose write-through/write-back/periodic
1. **Configure GCS backup**: pg_dump + gsutil automation
1. **Add monitoring**: OpenTelemetry metrics for memory system
1. **Test failover**: Ensure pgvector works if AgentDB is down

______________________________________________________________________

## 📚 Resources

- **Hybrid Memory Guide**: `docs/HYBRID_AGENTDB_PGVECTOR_MEMORY.md`
- **Oneiric Vector Adapters**: `/Users/les/Projects/oneiric/docs/analysis/VECTOR_ADAPTERS.md`
- **AgentDB Repo**: [github.com/ruvnet/claude-flow](https://github.com/ruvnet/claude-flow)
- **AgentDB NPM**: npmjs.com/package/agentdb

______________________________________________________________________

## ✅ Summary

**What We Built**:

- ✅ Oneiric AgentDB adapter (full VectorBase implementation)
- ✅ MCP client integration
- ✅ Lifecycle management (init, health, cleanup)
- ✅ Complete documentation for hybrid approach
- ✅ Integration patterns with Mahavishnu

**Why This Rocks**:

- ⚡ **Sub-1ms hot data** with AgentDB
- 💾 **Production backups** with pgvector + GCS
- 🛠️ **Oneiric integration** (lifecycle, health checks)
- 🔄 **Flexible sync** strategies
- 🎯 **Purpose-built for AI agents**

**The hybrid approach gives you the best of both worlds!** 🚀
