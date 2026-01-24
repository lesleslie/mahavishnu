# Configuration

This guide covers how to configure Mahavishnu for your environment.

## Configuration Overview

Mahavishnu uses a layered configuration system:

1. Default values in Pydantic models
2. `settings/mahavishnu.yaml` (committed to git)
3. `settings/local.yaml` (gitignored, local overrides)
4. Environment variables `MAHAVISHNU_*`

## Main Configuration File

Create `settings/mahavishnu.yaml` for your configuration:

```yaml
server_name: "Mahavishnu Orchestrator"
cache_root: .oneiric_cache
health_ttl_seconds: 60.0
log_level: INFO
repos_path: "~/repos.yaml"

adapters:
  airflow: false  # Use Prefect instead
  crewai: false   # Use LangGraph instead
  langgraph: true
  agno: false
  prefect: true

qc:
  enabled: true
  min_score: 80
  checks:
    - linting
    - type_checking
    - security_scan

auth:
  enabled: false  # Set to true in production
  algorithm: "HS256"
  expire_minutes: 60
```

## Local Configuration

For local development, create `settings/local.yaml`:

```yaml
server_name: "Mahavishnu Local Development"
log_level: DEBUG

auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 120
```

## Environment Variables

Required environment variables:

- `MAHAVISHNU_AUTH_SECRET`: JWT secret (required if auth is enabled)
- `MAHAVISHNU_LLM_API_KEY`: API key for LLM provider
- `MAHAVISHNU_REPOS_PATH`: Path to repos.yaml file

## Adapter Configuration

### LangGraph Adapter

```yaml
langgraph:
  enabled: true
  llm_provider: "openai"
  llm_model: "gpt-4o"
  llm_temperature: 0.1
  llm_timeout: 30
```

### Prefect Adapter

```yaml
prefect:
  enabled: true
  api_url: "https://api.prefect.cloud"
  api_key: "${PREFECT_API_KEY}"
  work_pool: "default"
```

### Agno Adapter

```yaml
agno:
  enabled: false  # Experimental
  runtime: "local"
  agent_os_enabled: true
``