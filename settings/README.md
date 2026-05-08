# Mahavishnu Configuration Files

This directory contains all YAML configuration files for Mahavishnu.
Run `mahavishnu config validate --strict` to verify all files against the Pydantic schema.

## Files

| File | Purpose | Committed |
|------|---------|-----------|
| `mahavishnu.yaml` | Main application config — all `MahavishnuSettings` fields | Yes |
| `local.yaml` | Local overrides (gitignored) — same structure as `mahavishnu.yaml` | No |
| `models.yaml` | LLM provider and model configuration | Yes |
| `embeddings.yaml` | Embedding model configuration for content ingestion | Yes |
| `repos.yaml` | Repository manifest (legacy; prefer `ecosystem.yaml`) | Yes |
| `ecosystem.yaml` | Canonical repository manifest with roles, tags, and descriptions | Yes |

## Validation

```bash
# Report-only (no exit code change):
mahavishnu config validate

# Strict mode (exits 1 on any error):
mahavishnu config validate --strict

# Full check including runtime connectivity:
mahavishnu config validate --full
```

## Environment Variables

All `MahavishnuSettings` fields can be overridden via environment variables using the pattern:

```
MAHAVISHNU_{FIELD}=value
MAHAVISHNU_{GROUP}__{FIELD}=value   # nested groups use double underscore
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAHAVISHNU_AUTH_SECRET` | — | JWT signing secret (min 32 chars, required when auth enabled) |
| `MAHAVISHNU_UNIFIED_VALIDATION_ENABLED` | `false` | Enable strict config validation on startup |
| `RUNPOD_API_KEY` | — | Required before spawning `pool_type=runpod` pools |
| `MAHAVISHNU_DHARA_STATE__ENABLED` | `true` | Enable Dhara state persistence |
| `MAHAVISHNU_DHARA_STATE__FLUSH_INTERVAL_SECONDS` | `60` | Routing buffer flush interval |
