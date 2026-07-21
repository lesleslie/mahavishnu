---
status: complete
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: convergence-control-plane
---

# Bodai Deployment Guide: Local vs Serverless

## **Plan**: `2026-05-23-bodai-routing-feedback-loop-v4.md` — Phase 5.3 **Status**: `complete, implementation` <!-- legacy status: complete, implementation — see YAML frontmatter --> **Purpose**: Document local vs serverless deployment patterns for the Bodai feedback loop

## Overview

The Bodai feedback loop spans four components:

| Component | Default storage | Serverless-ready storage | Port |
|-----------|----------------|------------------------|------|
| Mahavishnu | `:memory:` DuckDB | PostgreSQL + pgvector (`otel_traces` table) | 8680 |
| Akosha | `:memory:` DuckDB | PostgreSQL + pgvector (`conversations` table) | 8682 |
| Dhara | FileStorage (persistent) | **NOT serverless** (fcntl locks) | 8683 |
| Session-Buddy | `:memory:` DuckDB | PostgreSQL + pgvector | 8678 |

**Key constraint**: Dhara **cannot** run serverless — it requires a persistent VM/container. All other components can run serverless with pgvector backends.

______________________________________________________________________

## Deployment Modes

### Mode 1: Full Local (All In-Process)

No external services. Each component uses `:memory:` DuckDB. Traces lost on restart.

```bash
# Start all components — each has zero external dependencies
mahavishnu mcp start     # port 8680
akosha mcp start         # port 8682
session-buddy start     # port 8678
dhara start             # port 8683 (persistent file storage)
```

**Pros**: Zero setup, works offline, fastest iteration
**Cons**: Traces lost on restart, no cross-component shared state

______________________________________________________________________

### Mode 2: Hybrid — Local + Shared pgvector

Components that need persistence share a PostgreSQL + pgvector instance. Dhara still runs on a persistent VM.

```bash
# 1. Start PostgreSQL with pgvector
docker run -d -p 5432:5432 \
  -e POSTGRES_DB=mahavishnu \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=secret \
  pgvector/pgvector:pg16

# 2. Enable vector extension
psql -U postgres -h localhost -d mahavishnu -c "CREATE EXTENSION vector;"

# 3. Start Dhara on persistent VM
dhara start             # port 8683

# 4. Start Akosha with pgvector
export AKOSHA__STORAGE__HOT__BACKEND=pgvector
export AKOSHA__STORAGE__HOT__PG_URL=postgresql://postgres:secret@localhost:5432/akosha
akosha mcp start

# 5. Start Mahavishnu with pgvector
export MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql
export MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=postgresql://postgres:secret@localhost:5432/mahavishnu
mahavishnu mcp start
```

> **Akosha/Mahavishnu shared PG**: They can share the same PostgreSQL instance — Akosha uses its own `conversations` table, Mahavishnu uses `otel_traces`. No schema collision.

**Pros**: Traces survive restarts, cold-starts supported for Akosha/Mahavishnu
**Cons**: Dhara still requires persistent VM, PostgreSQL must be running

______________________________________________________________________

### Mode 3: Full Serverless (Akosha + Mahavishnu only)

Akosha and Mahavishnu deploy to serverless compute (Cloudflare Workers, AWS Lambda, etc.) backed by cloud PostgreSQL (Neon, Supabase, Railway). Dhara remains on a persistent VM.

```bash
# Cloud PostgreSQL setup (Neon example)
createdb mahavishnu_serverless
psql "postgresql://postgres:password@ep-xxx.neon.tech/mahavishnu_serverless" \
  -c "CREATE EXTENSION vector;"

# Deploy Akosha (serverless)
export AKOSHA__STORAGE__HOT__BACKEND=pgvector
export AKOSHA__STORAGE__HOT__PG_URL=postgresql://postgres:password@ep-xxx.neon.tech/akosha
# Deploy to Cloudflare Workers / AWS Lambda

# Deploy Mahavishnu (serverless)
export MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql
export MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=postgresql://postgres:password@ep-xxx.neon.tech/mahavishnu
# Deploy to serverless compute

# Dhara still runs on persistent VM
ssh user@dhara-vm "cd /opt/dhara && docker compose up -d"
```

**Pros**: Akosha/Mahavishnu scale to zero, cold-starts work
**Cons**: Dhara single point of failure, cloud PG costs money, network latency to PostgreSQL

______________________________________________________________________

## Shared pgvector Architecture

Both Akosha and Mahavishnu can share the same PostgreSQL instance when using pgvector:

```
                    ┌──────────────────────────────────────────┐
                    │     PostgreSQL + pgvector                  │
                    │  (cloud-hosted: Neon, Supabase, Railway)  │
                    └─────────────────────┬──────────────────────┘
                                         │
              ┌──────────────────────────┴──────────────────────┐
              │                                                   │
     Akosha HotStore                                Mahavishnu OtelIngester
     Table: conversations                              Table: otel_traces
     HNSW index on embedding                           HNSW index on embedding
     Collection: conversations                         Collection: otel_traces
```

- **No table collision**: Akosha uses `conversations`, Mahavishnu uses `otel_traces`
- **No schema interference**: Different tables, different indexes
- **Connection pooling**: Handled by the cloud PostgreSQL provider
- **Backup independent**: Each component manages its own table data

______________________________________________________________________

## Oneiric Environment Variable Naming

All Bodai components use Oneiric layered config with `__` as the nested delimiter:

### Mahavishnu OTel Ingester

```bash
export MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql   # duckdb or postgresql
export MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=<url>     # required if TYPE=postgresql
```

### Akosha Hot Store

```bash
export AKOSHA__STORAGE__HOT__BACKEND=pgvector   # duckdb or pgvector
export AKOSHA__STORAGE__HOT__PG_URL=<url>       # required if BACKEND=pgvector
```

> **Critical**: Flat env var names like `MAHAVISHNU_OTEL_INGESTER_STORAGE_TYPE` (single `_`) will **not** be resolved. Oneiric requires double underscore `__` between section levels.

______________________________________________________________________

## Dhara — NOT Serverless

Dhara **cannot** run serverless due to architectural blockers:

1. **fcntl file locks** — exclusive locks on local files, incompatible with Lambda/Cloud Functions
1. **Hardcoded `FileStorage`** — MCP server always uses FileStorage; no cloud primary store
1. **In-memory LRU cache** — assumes object lifetime across invocations
1. **Cloud adapters are backup-only** — S3/GCS/Azure adapters only work for backup subsystem

**Impact**: Dhara must be deployed on a persistent VM/container. This is fine — the standalone constraint is met as long as Dhara is available, not specifically serverless.

For a Dhara serverless re-architecture, see [Dhara GitHub Issues](https://github.com/lesleslie/dhara/issues).

______________________________________________________________________

## Standalone Operation Matrix

| Components running | Behavior | Degradation |
|---|---|---|
| Any single component alone (local dev) | `:memory:` DuckDB, zero deps | None |
| Any single component alone (deployed) | pgvector via cloud Postgres | None |
| Mahavishnu only | Routes with `least_loaded` | Feedback loop inactive |
| Mahavishnu + Dhara | No fitness signals → fallback to `least_loaded` | Routing not optimized |
| Akosha only | Polls endpoints. None reachable → logs warning, idles | Feedback loop inactive |
| Akosha + Dhara | Buffers in-memory. No trace source → idles | Signals when components available |
| Mahavishnu + Akosha + Dhara | Complete loop | Limited trace set |
| Full chain (all components) | Complete feedback loop | None |
| Akosha (serverless) + Mahavishnu (local) | Akosha polls Mahavishnu via MCP. Mahavishnu has `:memory:` — traces lost on restart. | Traces incomplete but loop active |
| Akosha (local) + Mahavishnu (serverless) | Akosha polls via local network. Mahavishnu pgvector survives cold-starts. | Works if network reachable |

______________________________________________________________________

## Environment Detection & Defaults

| Scenario | Hot store backend | How triggered |
|---|---|---|
| Fresh clone, no setup | `:memory:` DuckDB | No env var set → code default |
| Local Postgres running | Shared pgvector | `*__*__PG_URL` set to local Postgres URL |
| Serverless deployment | Shared pgvector | `*__*__PG_URL` set to cloud Postgres URL |
| Akosha Lite mode | `:memory:` DuckDB | `AKOSHA_MODE=lite` env var (explicit override) |
| Akosha Standard mode | pgvector + Redis L2 | `AKOSHA__STORAGE__HOT__PG_URL` set |

______________________________________________________________________

## Infrastructure Prerequisite

Before using pgvector backends, the `vector` extension must be enabled on your PostgreSQL instance:

```sql
CREATE EXTENSION vector;
```

This enables:

- `vector` data type and `FLOAT[n]` vector columns
- `array_cosine_similarity()` and other vector functions
- HNSW index support for fast approximate nearest-neighbor search

```bash
# Verify
psql -U postgres -h localhost -d mahavishnu \
  -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
# Expected: vector | 16 | 0.5.0 | f
```

______________________________________________________________________

## Quick Reference

### Start Local (Zero Setup)

```bash
mahavishnu mcp start   # Uses :memory: DuckDB
akosha mcp start       # Uses :memory: DuckDB
dhara start            # Uses FileStorage (persistent)
```

### Start with Shared pgvector

```bash
# 1. Start PostgreSQL
docker run -d -p 5432:5432 pgvector/pgvector:pg16
psql -U postgres -h localhost -c "CREATE EXTENSION vector;"

# 2. Start Dhara (persistent VM required)
dhara start

# 3. Start Akosha
export AKOSHA__STORAGE__HOT__BACKEND=pgvector
export AKOSHA__STORAGE__HOT__PG_URL=postgresql://postgres@localhost:5432/akosha
akosha mcp start

# 4. Start Mahavishnu
export MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql
export MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=postgresql://postgres@localhost:5432/mahavishnu
mahavishnu mcp start
```

### Verify pgvector is Working

```bash
# Mahavishnu — check OTel ingester stats
mahavishnu mcp call get_otel_ingester_stats
# Should show: storage_backend: "duckdb_hotstore" (or "pgvector_hotstore")

# Akosha — check hot store type
curl http://localhost:8682/health | jq .storage_backend
```
