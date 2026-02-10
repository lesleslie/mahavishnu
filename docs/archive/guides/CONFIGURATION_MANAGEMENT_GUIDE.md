# Configuration Management Guide

**Integration #25: Git-Based Configuration Management for Mahavishnu**

Table of Contents:
- [Overview](#overview)
- [Architecture](#architecture)
- [Oneiric Integration](#oneiric-integration)
- [Schema Validation](#schema-validation)
- [Multi-Environment Setup](#multi-environment-setup)
- [Versioning and Rollback](#versioning-and-rollback)
- [Git-Based Versioning](#git-based-versioning)
- [CLI Commands](#cli-commands)
- [Best Practices](#best-practices)
- [Setup Guide](#setup-guide)
- [API Reference](#api-reference)

## Overview

The Configuration Management integration provides comprehensive configuration lifecycle management including validation, versioning, rollback, environment promotion, and Git-based version control for all Mahavishnu settings.

### Key Features

- **Oneiric Integration**: Deep integration with Oneiric's layered configuration system
- **Schema Validation**: JSON schema validation for all configuration changes
- **Version History**: Automatic versioning with rollback capabilities
- **Environment Promotion**: Dev → Staging → Prod promotion workflows
- **Git-Based**: Configuration as code with diff tracking
- **Hot-Reload**: Dynamic configuration reloading without restart
- **CLI Interface**: Comprehensive CLI for all operations

### Why Configuration Management Matters

- **Safety**: Validate changes before applying
- **Auditability**: Track who changed what and when
- **Recoverability**: Rollback to previous working configurations
- **Consistency**: Ensure configurations match across environments
- **Compliance**: Meet change management requirements

## Architecture

### Configuration Layer System

Mahavishnu uses Oneiric's layered configuration system with 4 layers:

```
┌─────────────────────────────────────────────────────────────┐
│                   Layer 4: Environment Variables              │
│                   MAHAVISHNU_*__* (highest priority)         │
├─────────────────────────────────────────────────────────────┤
│                   Layer 3: Local Configuration               │
│                   settings/local.yaml (gitignored)            │
├─────────────────────────────────────────────────────────────�
│                   Layer 2: Committed Configuration          │
│                   settings/mahavishnu.yaml (committed)       │
├─────────────────────────────────────────────────────────────┤
│                   Layer 1: Default Values                   │
│                   Pydantic model defaults                 │
└─────────────────────────────────────────────────────────────┘

Values merge (higher layers override lower layers)
```

### Configuration Flow

```
1. Load Default Values (Pydantic)
   ↓
2. Load settings/mahavishnu.yaml (Git)
   ↓
3. Load settings/local.yaml (Local overrides)
   ↓
4. Load Environment Variables (Runtime overrides)
   ↓
5. Validate against Schema
   ↓
6. Initialize MahavishnuApp with validated config
   ↓
7. Apply configuration to all integrations
   ↓
8. Ready to serve requests
```

### Version Control Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   Configuration Change                     │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Save Version                           │
│  - version_id: dev_20240101_120000                       │
│  - environment: dev                                   │
│  - config_data: {...}                                   │
│  - created_by: admin                                   │
│  - description: "Enable new feature"                    │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Git Commit                            │
│  - Automatic commit to config history                  │
│  - Diff tracking                                      │
│  - Rollback capability                                │
└─────────────────────────────────────────────────────────────┘
```

## Oneiric Integration

### Deep Oneiric Integration

The Configuration Management system extends Oneiric's Config class with version control, validation, and rollback capabilities.

#### Oneiric Config Extension

**Extended Configuration Class**:
```python
from oneiric.config import Config
from mahavishnu.integrations.configuration_management import ConfigurationManager

class VersionedConfig(Config):
    """Extended Oneiric configuration with versioning."""

    def __init__(self, *args, config_manager: ConfigurationManager = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_manager = config_manager

    async def save_version(
        self,
        description: str = "",
        environment: str = "dev",
        created_by: str = "system",
    ) -> str:
        """Save current configuration as version."""
        config_data = self.export()

        version = self._config_manager.save_version(
            config_data=config_data,
            environment=Environment(environment),
            created_by=created_by,
            description=description,
        )

        logger.info(f"Configuration saved as version: {version.version_id}")
        return version.version_id

    async def validate(self) -> list[str]:
        """Validate configuration against schema."""
        errors = []

        # Validate with Pydantic
        try:
            MahavishnuSettings(**self.export())
        except Exception as e:
            errors.append(str(e))

        return errors

    def export(self) -> dict[str, Any]:
        """Export configuration as dictionary."""
        return self.get()  # Oneiric's get() returns merged config
```

#### Accessing Configuration via Oneiric

**Method 1: Direct Access** (Python):
```python
from oneiric.config import Config

config = Config()

# Get value (merged from all layers)
value = config.get("pools.enabled")

# Get nested value
value = config.get("otel_storage.connection_string")

# Get all configuration
all_config = config.get()
```

**Method 2: Environment Override** (Runtime):
```bash
# Override any configuration field via environment variable
export MAHAVISHNU_POOLS_ENABLED="false"
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://..."

python -c "
from oneiric.config import Config
config = Config()
print(config.get('pools.enabled'))  # Prints: false
"
```

**Method 3: File-Based** (settings/local.yaml):
```yaml
# settings/local.yaml (gitignored)
pools:
  enabled: false

otel_storage:
  connection_string: "postgresql://user:pass@host/db"
```

### Extending Oneiric for Custom Configuration

**Add Custom Configuration Section**:

**Step 1: Define Pydantic Model**:
```python
from pydantic import BaseModel, Field
from oneiric.config import ConfigDict

class CustomFeatureConfig(BaseModel):
    """Custom feature configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable custom feature",
    )
    setting1: str = Field(
        default="default_value",
        description="First setting",
    )
    setting2: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="Second setting",
    )

    model_config = ConfigDict(
        extra="forbid",
        env_prefix="MAHAVISHNU_CUSTOM_FEATURE_",
    )
```

**Step 2: Extend MahavishnuSettings**:
```python
from mahavishnu.core.config import MahavishnuSettings

class MahavishnuSettings(BaseModel):
    """Extended Mahavishnu settings with custom feature."""

    # Existing fields...
    server_name: str
    pools: PoolConfig
    # ... other fields ...

    # New custom feature
    custom_feature: CustomFeatureConfig = Field(
        default_factory=CustomFeatureConfig,
        description="Custom feature configuration",
    )
```

**Step 3: Use in Code**:
```python
from oneiric.config import Config

config = Config()

# Access custom feature
custom_config = config.get("custom_feature")
print(custom_config["enabled"])
print(custom_config["setting1"])
print(custom_config["setting2"])
```

**Step 4: Configure via YAML**:
```yaml
# settings/mahavishnu.yaml
custom_feature:
  enabled: true
  setting1: "production_value"
  setting2: 500
```

**Step 5: Override via Environment**:
```bash
export MAHAVISHNU_CUSTOM_FEATURE__SETTING2="750"
```

## Schema Validation

### JSON Schema Generation

**Generate Schema**:
```python
from mahavishnu.core.config import MahavishnuSettings

# Get JSON schema
schema = MahavishnuSettings.model_json_schema()

# Save schema
import json
with open("config-schema.json", "w") as f:
    json.dump(schema, f, indent=2)
```

**Schema Structure**:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "MahavishnuSettings",
  "type": "object",
  "properties": {
    "server_name": {
      "type": "string",
      "description": "Server name for this instance"
    },
    "pools": {
      "$ref": "#/$defs/PoolConfig"
    },
    "otel_storage": {
      "$ref": "#/$defs/OTelStorageConfig"
    }
  },
  "$defs": {
    "PoolConfig": {
      "type": "object",
      "properties": {
        "enabled": {"type": "boolean"},
        "min_workers": {"type": "integer"},
        "max_workers": {"type": "integer"}
      }
    }
  }
}
```

### Validation Rules

**Type Validation**:
```python
from pydantic import ValidationError, ValidationError

try:
    config = MahavishnuSettings(
        server_name="Mahavishnu",
        pools=PoolConfig(
            min_workers=5,
            max_workers=3,  # ❌ Invalid! max < min
        )
    )
except ValidationError as e:
    print(f"Validation error: {e}")
    # Output: 1 validation error for PoolConfig
    #   max_workers
    │     ensure this value is greater than or equal to min_workers
```

**Range Validation**:
```python
class PoolConfig(BaseModel):
    min_workers: int = Field(ge=1, le=100)
    max_workers: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def validate_workers(cls, model):
        if model.max_workers < model.min_workers:
            raise ValueError("max_workers must be >= min_workers")
        return model
```

**Conditional Validation**:
```python
class ObservabilityConfig(BaseModel):
    enabled: bool
    jaeger_endpoint: Optional[str] = None

    @model_validator(mode="after")
    def validate_observability(cls, model):
        if model.enabled and not model.jaeger_endpoint:
            raise ValueError(
                "jaeger_endpoint required when enabled=true"
            )
        return model
```

### Custom Validators

**Add Custom Validator**:
```python
from pydantic import field_validator

class CertificateConfig(BaseModel):
    domains: list[str] = Field(...)

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, v):
        if not v:
            raise ValueError("domains cannot be empty")

        # Validate domain format
        import re
        domain_pattern = r"^[a-z0-9]([\-\.][a-z0-9]+)*$"

        for domain in v:
            if not re.match(domain_pattern, domain):
                raise ValueError(
                    f"Invalid domain format: {domain}"
                )

        return v
```

## Multi-Environment Setup

### Environment Separation

**Directory Structure**:
```
settings/
├── mahavishnu.yaml      # Base configuration (committed)
├── local.yaml           # Local overrides (gitignored)
├── dev.yaml             # Development overrides
├── staging.yaml         # Staging overrides
└── prod.yaml            # Production overrides
```

**Configuration Loading Order**:
```python
from oneiric.config import Config
import os

def load_config_for_environment(env: str) -> Config:
    """Load configuration for specific environment."""
    config = Config()

    # Load base configuration
    config.load_yaml("settings/mahavishnu.yaml")

    # Load environment-specific overrides
    env_file = f"settings/{env}.yaml"
    if Path(env_file).exists():
        config.load_yaml(env_file)

    # Load local overrides (highest priority)
    if Path("settings/local.yaml").exists():
        config.load_yaml("settings/local.yaml")

    # Apply environment variables
    config.load_env()

    return config
```

### Environment Promotion

**Promotion Workflow**:
```
Development → Staging → Production
     │              │
     │              └─→ Test in staging
     │
     └─→ Ready for staging promotion
```

**CLI Promotion**:
```bash
# Promote dev → staging
mahavishnu config promote --from dev --to staging

# Promote staging → prod
mahavishnu config promote --from staging --to prod
```

**Pre-Promotion Checklist**:
```bash
# 1. Validate staging configuration
mahavishnu config validate --env staging

# 2. Review diff
mahavishnu config diff --env staging

# 3. Dry-run promotion
mahavishnu config promote --from dev --to staging --dry-run

# 4. Actual promotion
mahavishun config promote --from dev --to staging
```

**Rollback After Promotion**:
```bash
# If issues found, rollback
mahavishnu config rollback staging_20240101_120000

# Verify rollback
mahavishnu config diff  # # Compare current vs rolled back
```

## Versioning and Rollback

### Version Management

**Version Schema**:
```
{environment}_{timestamp}

Examples:
- dev_20240101_120000
- staging_20240101_130000
- prod_20240101_140000
```

**Version Metadata**:
```python
@dataclass
class ConfigVersion:
    version_id: str
    config_data: dict[str, Any]
    environment: Environment
    created_at: datetime
    created_by: str
    description: str
```

**Save Version**:
```python
from mahavishnu.integrations.configuration_management import ConfigurationManager

manager = ConfigurationManager(settings)

version = manager.save_version(
    config_data={
        "pools": {"enabled": True, "min_workers": 2},
        "otel_storage": {"enabled": True},
    },
    environment=Environment.DEV,
    created_by="admin@company.com",
    description="Enable pools and OTel storage",
)

print(f"Version saved: {version.version_id}")
```

**List Versions**:
```bash
# List all versions
mahavishnu config versions

# List production versions only
mahavishnu config versions --env prod

# Show last 20 versions
mahavishnu config versions --count 20
```

### Rollback Procedures

**Rollback to Previous Version**:
```bash
# View version history
mahavishnu config versions

# Rollback to specific version
mahavishnu config rollback prod_20240101_120000

# Dry-run first
mahavishnu config rollback prod_20240101_120000 --dry-run
```

**Rollback Safety**:
```python
async def safe_rollback(
    manager: ConfigurationManager,
    version_id: str,
    create_backup: bool = True,
) -> bool:
    """Safely rollback with automatic backup."""

    # 1. Validate target version exists
    version = manager.get_version(version_id)
    if not version:
        print(f"❌ Version not found: {version_id}")
        return False

    # 2. Save current config as backup
    if create_backup:
        current_config = manager._export_current_config()
        backup_version = manager.save_version(
            config_data=current_config,
            environment=Environment.PROD,
            created_by="system",
            description=f"Auto-saved before rollback to {version_id}",
        )
        print(f"✅ Backup saved: {backup_version.version_id}")

    # 3. Load target version
    try:
        target_config = version.config_data

        # 4. Validate target configuration
        errors = manager.validate_config(target_config)
        if errors:
            print(f"❌ Target version has validation errors:")
            for error in errors:
                print(f"  - {error}")
            return False

        # 5. Apply rollback (manual step for safety)
        print(f"\n✅ Validation passed")
        print(f"\n📋 Manual steps required:")
        print(f"  1. Review configuration above")
        print(f"  2. Edit settings/local.yaml to match")
        print(f"  3. Restart Mahavishnu")
        print(f"  4. Verify system health")

        return True

    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        return False
```

## Git-Based Versioning

### Git Integration

**Automatic Git Commits**:
```python
import subprocess
from pathlib import Path

def git_commit_version(version_id: str, description: str):
    """Commit configuration version to Git."""
    subprocess.run([
        "git",
        "add",
        f"config_versions/{version_id}.json",
    ])

    commit_message = f"config: {description}\n\nVersion: {version_id}"

    subprocess.run([
        "git",
        "commit",
        "-m",
        commit_message,
    ])

    print(f"✅ Committed version {version_id} to Git")
```

**View Git History**:
```bash
# View git log for configuration changes
git log --oneline -- config_versions/

# Show diff for specific version
git show config_versions/dev_20240101_120000.json
```

### Configuration Diffs

**Compare Environments**:
```bash
# Compare current vs staging
mahavishnu config diff --env staging

# Compare current vs version
mahavishnu config diff --version dev_20240101_120000

# Output:
# Current vs staging
#
# pools.enabled
#   Current: [green]true[/green]
#   Target:  [yellow]false[/yellow]
```

**Unified Diff Format**:
```bash
# Show unified diff
mahavishnu config diff --env prod --format json

# Output:
{
  "pools.enabled": {
    "current": true,
    "target": false
  },
  "pools.min_workers": {
    "current": 2,
    "target": 5
  }
}
```

### Branch Strategy

**Environment Branches**:
```bash
# Main branch
main  # Production configuration

# Environment branches
dev  # Development configuration
staging  # Staging configuration

# Feature branches
feature/pools-optimization
feature/otel-storage-migration
```

**Promotion Workflow**:
```bash
# 1. Develop on dev branch
git checkout dev
# Edit settings/local.yaml
git commit -m "Enable pools"

# 2. Test in staging
git checkout staging
git merge dev
# Test staging environment

# 3. Promote to production
git checkout main
git merge staging

# 4. Tag release
git tag -a v1.0.0 -m "Release v1.0.0"
```

## CLI Commands

### Configuration Listing

**List All Configuration**:
```bash
# List all configuration
mahavishnu config list

# List specific group
mahavishnu config list --group pools

# Output format
mahavishnu config list --format json
mahavishnu config list --format yaml
mahavishnu config list --format markdown
```

**Rich Table Output**:
```
┌────────────────────────────────────────────────────────────────┐
│ Configuration                                         │
├────────────────────────────────────────────────────────────────┤
│ Path                    │ Value       │ Description                 │
├────────────────────────────────────────────────────────────────┤
│ pools.enabled            │ true        │ Enable pool management      │
│ pools.min_workers        │ 2           │ Minimum worker pool size      │
│ pools.max_workers        │ 10          │ Maximum worker pool size      │
│ otel_storage.enabled      │ true        │ Enable OTel storage           │
│ otel_storage.endpoint     │ localhost:  │ OTel endpoint               │
└────────────────────────────────────────────────────────────────┘
```

### Configuration Retrieval

**Get Specific Value**:
```bash
# Get nested value
mahavishnu config get pools.enabled

# Get deeply nested value
mahavishnu config get otel_storage.connection_string

# Output
true
postgresql://user:pass@localhost/db
```

### Configuration Updates

**Set Configuration Value**:
```bash
# Enable pools
mahavishnu config set pools.enabled true

# Set worker count
mahavishnu config set pools.min_workers 5

# Save to file
mahavishnu config set pools.enabled true --save

# Validate after setting
mahavishnu config set pools.min_workers 5 --validate
```

**Update with Validation**:
```python
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.integrations.configuration_management import ConfigurationManager

# Load current settings
settings = MahavishnuSettings()
manager = ConfigurationManager(settings)

# Update value
manager.set_config_value("pools.enabled", True)

# Validate changes
errors = manager.validate_config(settings.model_dump())

if errors:
    print("Validation errors:")
    for error in errors:
        print(f"  - {error}")
else:
    print("✅ Configuration is valid")
```

### Schema Operations

**Show JSON Schema**:
```bash
# Show full schema
mahavishnu config schema

# Show schema for specific group
mahavishnu config schema --group pools

# Output as YAML
mahavishnu config schema --format yaml
```

**Schema Documentation**:
```json
{
  "$schema": "https://json-schema.org/database",
  "title": "MahavishnuSettings",
  "type": "object",
  "properties": {
    "pools": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean",
          "description": "Enable pool management"
        },
        "min_workers": {
          "type": "integer",
          "minimum": 1,
          "maximum": 100
        }
      }
    }
  }
}
```

## Best Practices

### Configuration Organization

**Principle**: Group related settings together

**Good Organization**:
```yaml
# settings/mahavishnu.yaml
server_name: "Mahavishnu Orchestrator"

# Pool configuration
pools:
  enabled: true
  default_pool_type: "mahavishnu"
  routing_strategy: "least_loaded"

# Worker configuration
workers:
  enabled: true
  default_adapter: "llamaindex"

# Observability
otel_storage:
  enabled: true
  endpoint: "http://localhost:4317"
  connection_string: "postgresql://..."

# Quality control
qc:
  enabled: true
  min_score: 80
```

**Poor Organization**:
```yaml
# ❌ Don't mix unrelated settings
server_name: "Mahavishnu"
min_workers: 2
enabled: true
endpoint: "http://..."
connection_string: "postgresql://..."
```

### Configuration Validation

**Add Validation Rules**:
```python
from pydantic import Field, field_validator

class PoolConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="Enable pool management",
    )

    min_workers: int = Field(
        default=2,
        ge=1,
        le=100,
        description="Minimum worker pool size",
    )

    max_workers: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Maximum worker pool size",
    )

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v, info):
        if "min_workers" in info.data:
            if v < info.data["min_workers"]:
                raise ValueError(
                    f"max_workers ({v}) must be >= min_workers "
                    f"({info.data['min_workers']})"
                )
        return v
```

### Environment Variable Usage

**Naming Convention**:
```
MAHAVISHNU_{GROUP}__{FIELD}

Examples:
MAHAVISHNU_POOLS__ENABLED
MAHAVISHNU_OTEL_STORAGE__ENDPOINT
MAHAVISHNU_WORKERS__DEFAULT_ADAPTER
```

**Environment Type Conversion**:
```python
import os

# Boolean
enabled = os.getenv("MAHAVISHNU_POOLS__ENABLED", "false").lower() == "true"

# Integer
min_workers = int(os.getenv("MAHAVAVISHNU_POOLS__MIN_WORKERS", "2"))

# Float
sample_rate = float(os.getenv("MAHAVISHNU_DISTRIBUTED_TRACING__SAMPLE_RATE", "1.0"))
```

**Common Pitfalls**:
```python
# ❌ String instead of boolean
enabled = os.getenv("MAHAVISHNU_POOLS__ENABLED")  # Returns "true" or "false"

# ✅ Parse boolean correctly
enabled = os.getenv("MAHAVISHNU_POOLS__ENABLED", "false").lower() == "true"

# ❌ String instead of integer
workers = os.getenv("MAHAVISHNU_POOLS__MIN_WORKERS")  # Returns "2"

# ✅ Parse integer correctly
workers = int(os.getenv("MAHAVISHNU_POOLS__MIN_WORKERS", "2"))
```

### Configuration Secrets

**Never Commit Secrets**:
```yaml
# ❌ DON'T DO THIS
api_keys:
  openai: "sk-proj-abc123..."  # Committed secret!

# ✅ DO THIS
api_keys:
  openai: ${OPENAI_API_KEY}  # Environment variable
```

**Use Environment Variables**:
```bash
# Set environment variable
export MAHAVISHNU_AUTH__SECRET_KEY="production-secret"

# Reference in YAML
auth:
  secret_key: "${MAHAVISHNU_AUTH__SECRET_KEY}"
```

**Validate Secret Presence**:
```python
from pydantic import field_validator, SecretStr

class AuthConfig(BaseModel):
    secret_key: SecretStr = Field(...)

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v):
        if not v.get_secret_value():
            raise ValueError("secret_key cannot be empty")
        return v
```

## Setup Guide

### Initial Setup

**1. Initialize Configuration Files**:
```bash
# Create settings directory
mkdir -p settings

# Generate default configuration
mahavishnu config init --env dev

# Review generated file
cat settings/dev.yaml
```

**2. Customize for Environment**:
```yaml
# settings/dev.yaml
server_name: "Mahavishnu Dev"
pools:
  enabled: false  # Disable pools in development
workers:
  default_adapter: "llamaindex"

otel_storage:
  endpoint: "http://localhost:4317"
  connection_string: "postgresql://dev:dev@localhost/mahavishnu"
```

**3. Validate Configuration**:
```bash
# Validate all configuration
mahavishnu config validate

# Validate specific group
mahavishnu config validate --group pools

# Show schema
mahavishnu config schema
```

### Production Setup

**1. Create Production Configuration**:
```bash
# Initialize production config
mahavishnu config init --env prod --force
```

**2. Configure for Production**:
```yaml
# settings/prod.yaml
server_name: "Mahavishnu Production"

pools:
  enabled: true
  min_workers: 5
  max_workers: 50
  routing_strategy: "least_loaded"

workers:
  enabled: true

otel_storage:
  enabled: true
  endpoint: "http://otel-collector:4317"
  connection_string: "${DATABASE_URL}"

auth:
  enabled: true
  secret_key: "${MAHAVISHNU_AUTH__SECRET_KEY}"
```

**3. Set Environment Variables**:
```bash
# Database URL
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://..."

# Secret key
export MAHAVISHNU_AUTH__SECRET_KEY="${VAULT_SECRET}"

# Tracing
export MAHAVISHNU_DISTRIBUTED_TRACING__SAMPLE_RATE="0.1"
```

**4. Validate and Save**:
```bash
# Validate production configuration
mahavishnu config validate --env prod

# Save current config as version
mahavishnu config export \
  --env prod \
  --output config-backup-prod.json \
  --secrets
```

## API Reference

### ConfigurationManager

Main configuration manager class.

#### Methods

##### `save_version()`
Save a new configuration version.

**Signature**:
```python
async def save_version(
    self,
    config_data: dict[str, Any],
    environment: Environment,
    created_by: str,
    description: str = "",
) -> ConfigVersion
```

**Parameters**:
- `config_data` (dict): Configuration data dictionary
- `environment` (Environment): Target environment
- `created_by` (str): User creating version
- `description` (str): Version description

**Returns**:
- `ConfigVersion`: Created version object

**Example**:
```python
version = await manager.save_version(
    config_data=settings.model_dump(),
    environment=Environment.PROD,
    created_by="admin@company.com",
    description="Enable production pools",
)
```

##### `get_version()`
Get version by ID.

**Signature**:
```python
def get_version(self, version_id: str) -> Optional[ConfigVersion]
```

**Parameters**:
- `version_id` (str): Version identifier

**Returns**:
- `ConfigVersion | None`: Version object or None

##### `list_versions()`
List versions, optionally filtered by environment.

**Signature**:
```python
def list_versions(
    self,
    environment: Optional[Environment] = None,
) -> list[ConfigVersion]
```

**Returns**:
- `list[ConfigVersion]`: List of version objects

##### `rollback_to_version()`
Rollback configuration to previous version.

**Signature**:
```python
def rollback_to_version(self, version_id: str) -> dict[str, Any]
```

**Parameters**:
- `version_id` (str): Version to rollback to

**Returns**:
- `dict`: Configuration data from version

### Configuration Commands CLI

#### `config list`

List all configuration values.

**Usage**:
```bash
mahavishnu config list [--group GROUP] [--format FORMAT]
```

**Options**:
- `--group, -g`: Configuration group to show
- `--format, -f`: Output format (table, json, yaml, markdown)
- `--descriptions/--no-descriptions`: Show/hide descriptions

#### `config get`

Get a specific configuration value.

**Usage**:
```bash
mahavishnu config get KEY
```

**Arguments**:
- `KEY`: Configuration key (e.g., pools.enabled)

#### `config set`

Set a configuration value.

**Usage**:
```bash
mahavishnu config set KEY VALUE [--save] [--no-validate]
```

**Arguments**:
- `KEY`: Configuration key
- `VALUE`: Configuration value

**Options**:
- `--save, -s`: Save to settings/local.yaml
- `--validate/--no-validate`: Validate after setting

#### `config validate`

Validate all configurations against schemas.

**Usage**:
```bash
mahavishnu config validate [--schema] [--group GROUP]
```

**Options**:
- `--schema, -s`: Show JSON schema
- `--group, -g`: Validate specific group

#### `config diff`

Show configuration changes.

**Usage**:
```bash
mahavishnu config diff [--env ENV] [--version VERSION]
```

**Options**:
- `--env, -e`: Environment to compare
- `--version, -v`: Version to compare

#### `config versions`

Show configuration version history.

**Usage**:
```bash
mahavishnu config versions [--env ENV] [--count N] [--format FORMAT]
```

**Options**:
- `--env, -e`: Filter by environment
- `--count, -n`: Number of versions to show
- `--format, -f`: Output format (table, json, yaml)

#### `config rollback`

Rollback configuration to previous version.

**Usage**:
```bash
mahavishnu config rollback VERSION_ID [--dry-run] [--backup/--no-backup]
```

**Arguments**:
- `VERSION_ID`: Version ID to rollback to

**Options**:
- `--dry-run`: Show changes without applying
- `--backup/--no-backup`: Save current config before rollback

#### `config promote`

Promote configuration between environments.

**Usage**:
```bash
mahavishnu config promote --from SOURCE --to TARGET [--dry-run] [--version/--no-version]
```

**Options**:
- `--from, -f`: Source environment (dev, staging, prod)
- `--to, -t`: Target environment
- `--dry-run`: Show changes without applying
- `--version/--no-version`: Create version before promoting

#### `config reload`

Reload all integrations and configurations (hot-reload).

**Usage**:
```bash
mahavishnu config reload [--integration NAME] [--graceful/--force]
```

**Options**:
- `--integration, -i`: Reload specific integration
- `--graceful/--force`: Graceful reload with drain vs force immediate

#### `config export`

Export all configurations to file.

**Usage**:
```bash
mahavishnu config export [--output FILE] [--env ENV] [--secrets] [--format FORMAT]
```

**Options**:
- `--output, -o`: Output file (default: config_export.json)
- `--env, -e`: Environment to export
- `--secrets`: Include secret values
- `--format, -f`: Output format (json, yaml)

#### `config import`

Import configurations from file.

**Usage**:
```bash
mahavishnu config import FILE [--merge] [--validate-only] [--version/--no-version]
```

**Arguments**:
- `FILE`: Configuration file to import

**Options**:
- `--merge`: Merge with existing config
- `--validate-only`: Validate without importing
- `--version/--no-version`: Create version before importing

---

**Next**: [Certificate Management Guide](CERTIFICATE_MANAGEMENT_GUIDE.md)
