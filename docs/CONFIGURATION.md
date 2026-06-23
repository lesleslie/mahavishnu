# Configuration Reference

Configuration uses Oneiric layered loading: defaults → `settings/mahavishnu.yaml` → `settings/local.yaml` → environment variables (`MAHAVISHNU_*`).

## Main Configuration File

**Location**: `settings/mahavishnu.yaml` (committed)

```yaml
server_name: "Mahavishnu Orchestrator"

# Adapters
adapters:
  prefect: true        # Prefect workflow orchestration
  llamaindex: true     # RAG pipelines
  agno: true           # Multi-agent teams

# Quality control
qc:
  enabled: true
  min_score: 80

# WebSocket real-time updates
websocket:
  enabled: true
  host: "127.0.0.1"
  port: 8690

# Pool management
pools_enabled: true
default_pool_type: "mahavishnu"  # mahavishnu, session_buddy, runpod

# Content ingestion
ingestion:
  enabled: true
  quality_threshold: 0.7

# Authentication
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60

# Routing system
routing:
  enabled: true
  cost_budget_type: "daily"
  cost_limit: 100
  optimization_strategy: "cost"
```

## Local Configuration

**Location**: `settings/local.yaml` (gitignored)

Override any settings for local development without affecting committed config.

## Required Environment Variables

- `MAHAVISHNU_AUTH_SECRET` — JWT secret (minimum 32 characters)
- `RUNPOD_API_KEY` — Required for RunPodPool (set before spawning)

## Other Configuration Files

- `settings/repos.yaml` — Repository manifest with tags and metadata
- `settings/embeddings.yaml` — Embedding model configuration for content ingestion
- `settings/models.yaml` — LLM provider and model routing configuration
- `oneiric.yaml` — Legacy Oneiric config (backward compatible)

## Key Environment Variables

Access via `MAHAVISHNU_{FIELD}` pattern:

```bash
export MAHAVISHNU_AUTH_SECRET="your-secret-minimum-32-characters"
export MAHAVISHNU_POOLS_ENABLED=true
export MAHAVISHNU_DEFAULT_POOL_TYPE=mahavishnu
export MAHAVISHNU_TOOL_PROFILE=full  # full, standard, minimal
```

## LLM Provider Configuration

See `docs/plans/2026-05-10-minimax27-provider-migration.md` for current provider setup. Primary provider is MiniMax M2.7 with Ollama local fallback.

Task-based routing maps categories to optimal models via `mahavishnu/workers/task_router.py`.
