______________________________________________________________________

## name: configure-oneiric description: Use when configuring Oneiric applications or setting up layered configuration. Use when user asks to configure Oneiric, set up environment variables, or understand configuration precedence. Use for config validation and troubleshooting.

# Configure Oneiric

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| dhara | 8683 | grep | mcp\_\_dhara\_\_list_adapters, mcp\_\_dhara\_\_get_adapter, mcp\_\_dhara\_\_store_adapter | 30s |

Oneiric uses a **4-layer configuration system** with deterministic precedence. This skill guides you through setting up, validating, and troubleshooting Oneiric configuration.

**Core principle:** Configuration flows from defaults → committed → local → environment, with each layer overriding the previous.

## When to Use

**Use when:**

- Setting up Oneiric for the first time
- Configuring adapters, services, tasks, events, or workflows
- Troubleshooting configuration issues
- Understanding why a config value isn't applied
- Setting environment-specific overrides

**Don't use when:**

- Managing component lifecycle (use `manage-lifecycle`)
- Resolving components (use `resolve-components`)
- Remote manifest distribution (use `remote-manifests`)

## Configuration Layers

**4-Layer Precedence (Low to High):**

| Layer | Location | Purpose | Precedence |
|-------|----------|---------|------------|
| **1. Defaults** | Pydantic model defaults | Base values | Lowest (1) |
| **2. Committed** | `oneiric.yaml` (committed to repo) | Project defaults | Low (2) |
| **3. Local** | `local.yaml` (gitignored) | Local development | High (3) |
| **4. Environment** | `ONEIRIC_{DOMAIN}__{FIELD}` | Deployment-specific | Highest (4) |

**Key principle:** Higher layers override lower layers. Environment variables always win.

## Quick Reference

```bash
# 1. View current configuration
oneiric config show

# 2. Validate configuration
oneiric config validate

# 3. Test config precedence
oneiric config explain --field <field>

# 4. Generate config template
oneiric config init > oneiric.yaml

# 5. View effective config (all layers merged)
oneiric config effective
```

## Implementation

### Step 1: Understand Configuration Structure

**Oneiric domains correspond to configuration sections:**

```yaml
# oneiric.yaml
adapters:
  database:
    host: localhost
    port: 5432

services:
  api:
    enabled: true
    port: 8080

tasks:
  cleanup:
    schedule: "0 2 * * *"

events:
  user_created:
    priority: 10

workflows:
  onboarding:
    timeout: 3600
```

**Domain structure:**

- `adapters` - External system integrations
- `services` - Long-running services
- `tasks` - Scheduled jobs
- `events` - Event definitions
- `workflows` - DAG workflows
- `actions` - Action definitions

### Step 2: Create Base Configuration

**Generate template:**

```bash
oneiric config init > oneiric.yaml
```

**Or create manually:**

```yaml
# oneiric.yaml
adapters:
  database:
    url: "postgresql://localhost:5432/mydb"
    pool_size: 10
    timeout: 30

  logging:
    level: INFO
    format: json

services:
  api:
    host: "0.0.0.0"
    port: 8080
    workers: 4

tasks:
  cleanup:
    enabled: true
    schedule: "0 2 * * *"
```

### Step 3: Add Local Overrides

**Create local overrides (gitignored):**

```yaml
# local.yaml
adapters:
  database:
    url: "postgresql://localhost:5432/devdb"
    pool_size: 5  # Smaller pool for dev

  logging:
    level: DEBUG  # Verbose logging locally

services:
  api:
    port: 8000  # Different port for local dev
    reload: true  # Auto-reload on code changes
```

**Local file location:**

- Project root: `local.yaml`
- Config directory: `config/local.yaml`
- XDG config: `~/.config/oneiric/local.yaml`

### Step 4: Set Environment Variables

**Environment variable format:**

```bash
# Format: ONEIRIC_{DOMAIN}__{FIELD}
# Example: adapters.database.url → ONEIRIC_ADAPTERS__DATABASE__URL

export ONEIRIC_ADAPTERS__DATABASE__URL="postgresql://prod-db:5432/app"
export ONEIRIC_ADAPTERS__LOGGING__LEVEL="WARNING"
export ONEIRIC_SERVICES__API__PORT="9000"
```

**Naming rules:**

- Prefix: `ONEIRIC_`
- Domain: Uppercase domain name (`ADAPTERS`, `SERVICES`, `TASKS`)
- Double underscore: `__` between domain and subdomain
- Field: Uppercase field name
- Nested: Use `__` for each level (e.g., `ADAPTERS__DATABASE__POOL_SIZE`)

**Via MCP:**

```python
import os
os.environ["ONEIRIC_ADAPTERS__DATABASE__URL"] = "postgresql://..."

# Config automatically reloads
from oneiric.core.config import OneiricSettings
settings = OneiricSettings.load()  # Uses env var
```

### Step 5: Validate Configuration

**Check configuration validity:**

```bash
oneiric config validate
```

**Validation checks:**

- ✅ YAML syntax is valid
- ✅ Required fields present
- ✅ Field types match Pydantic models
- ✅ URLs are well-formed
- ✅ Numeric values in valid ranges
- ✅ Enum values are valid

**Via MCP:**

```python
result = await mcp.call_tool("mcp__mahavishnu__get_health", {})

# Returns:
{
    "valid": true,
    "errors": [],
    "warnings": ["Optional field 'timeout' not set, using default"]
}
```

### Step 6: Debug Configuration Issues

**View effective configuration (all layers merged):**

```bash
oneiric config effective
```

**Understand why a value is set:**

```bash
oneiric config explain --field adapters.database.url
```

**Output:**

```
Field: adapters.database.url
Value: "postgresql://prod-db:5432/app"
Source: environment (layer 4)
Overrides:
  - Committed config (layer 2): "postgresql://localhost:5432/mydb"
  - Local config (layer 3): "postgresql://localhost:5432/devdb"
```

**Common issues:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| Value not applied | Lower layer overridden | Check env vars or local.yaml |
| Type error | String instead of int | Fix YAML type (port: 8000 not "8000") |
| Field not found | Typo in field name | Check spelling against schema |
| Required field missing | Not set in any layer | Add to oneiric.yaml |

## Configuration Patterns

### Development Environment

```yaml
# oneiric.yaml (committed)
adapters:
  database:
    pool_size: 10
  logging:
    format: json

# local.yaml (gitignored)
adapters:
  database:
    url: "postgresql://localhost/dev"
  logging:
    level: DEBUG
```

### Production Environment

```bash
# No local.yaml in production
# Use environment variables for secrets
export ONEIRIC_ADAPTERS__DATABASE__URL=$DATABASE_URL
export ONEIRIC_ADAPTERS__REDIS__URL=$REDIS_URL
export ONEIRIC_LOGGING__LEVEL="INFO"
```

### Testing Environment

```bash
# Override via environment
export ONEIRIC_ADAPTERS__DATABASE__URL="sqlite:///test.db"
export ONEIRIC_LOGGING__LEVEL="WARNING"
```

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Wrong env var format** | Environment variable ignored | Use `ONEIRIC_{DOMAIN}__{FIELD}` format |
| **String instead of int** | Type validation error | Don't quote numbers in YAML |
| **Committing local.yaml** | Production uses dev config | Add `local.yaml` to `.gitignore` |
| **Not using effective config** | Confusing which value applies | Use `oneiric config effective` to see merged result |
| **Assuming reload is instant** | Config changes not applied | Config reloads on process restart or SIGHUP |

## Real-World Impact

**Before this skill:**

- Users confused by config precedence → 30 minutes debugging
- Wrong env var format → changes not applied
- Committed local.yaml → production used dev settings

**After this skill:**

- Clear layer understanding → instant troubleshooting
- Correct env var format → changes work first time
- Proper .gitignore → production stays secure

## Example Workflows

**New Project Setup:**

```bash
# 1. Generate config
oneiric config init > oneiric.yaml

# 2. Customize for project
vim oneiric.yaml

# 3. Create local overrides
cat > local.yaml <<EOF
adapters:
  logging:
    level: DEBUG
EOF

# 4. Validate
oneiric config validate

# 5. Add to .gitignore
echo "local.yaml" >> .gitignore
```

**Debugging Config:**

```bash
# User: "Why is database pool_size 5 instead of 10?"

# 1. Check effective config
oneiric config effective | grep pool_size

# 2. Explain the field
oneiric config explain --field adapters.database.pool_size

# Output shows:
# Layer 2 (committed): pool_size: 10
# Layer 3 (local): pool_size: 5  ← Override found here
```

**Production Deployment:**

```bash
# 1. No local.yaml in production
rm local.yaml

# 2. Set production env vars
export ONEIRIC_ADAPTERS__DATABASE__URL=$DATABASE_URL
export ONEIRIC_ADAPTERS__REDIS__URL=$REDIS_URL
export ONEIRIC_LOGGING__LEVEL="INFO"

# 3. Validate
oneiric config validate

# 4. Start application
python -m myapp
```

## Related Skills

- **REQUIRED:** `manage-lifecycle` - After configuring, manage component lifecycle
- **REQUIRED:** `resolve-components` - Understanding component resolution
- **REQUIRED:** `remote-manifests` - For remote configuration distribution

## Related Documentation

- [Oneiric README](https://github.com/lesleslie/oneiric) - Complete configuration guide
- [Config Module](oneiric/core/config.py) - Pydantic models and validation
- [ADR 001: Oneiric Configuration](docs/adr/001-oneiric-config.md) - Architecture decisions
