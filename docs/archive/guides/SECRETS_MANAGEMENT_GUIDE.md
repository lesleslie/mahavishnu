# Secrets Management Guide

**Integration #21: Comprehensive Secrets Management for Mahavishnu Ecosystem**

Table of Contents:
- [Overview](#overview)
- [Architecture](#architecture)
- [Oneiric Integration](#oneiric-integration)
- [Secret Storage Backends](#secret-storage-backends)
- [Secret Lifecycle Management](#secret-lifecycle-management)
- [Secret Injection](#secret-injection)
- [Secret Scanning](#secret-scanning)
- [Security Best Practices](#security-best-practices)
- [Setup Guides](#setup-guides)
- [Troubleshooting](#troubleshooting)
- [API Reference](#api-reference)

## Overview

The Secrets Management integration provides a unified, secure system for managing sensitive credentials across the entire Mahavishnu ecosystem. It extends Oneiric's configuration layer system to provide encrypted storage, automatic rotation, injection, and scanning capabilities.

### Key Features

- **Centralized SecretVault**: Single source of truth for all secrets
- **AES-256-GCM Encryption**: Military-grade encryption for all secrets at rest
- **Automatic Rotation**: Scheduled rotation with verification and rollback
- **Secret Injection**: Inject secrets into applications via env vars, files, or templates
- **Secret Scanning**: Detect hardcoded secrets in codebases
- **Access Logging**: Comprehensive audit trail for compliance (SOC2, HIPAA, PCI-DSS)
- **Multiple Backends**: Local, Vault, AWS Secrets Manager, Azure Key Vault
- **RBAC**: Role-based access control for secrets

### Why Secrets Management Matters

- **Security**: Prevents credential leakage in code and configuration files
- **Compliance**: Meets regulatory requirements for secret management
- **Automation**: Enables automated rotation and zero-downtime credential updates
- **Consistency**: Single source of truth across all services and environments
- **Auditability**: Complete access logs for security investigations

## Architecture

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Mahavishnu Ecosystem                     │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────┐  │
│  │            SecretVault (Main Interface)               │  │
│  │  - store_secret()                                      │  │
│  │  - get_secret()                                        │  │
│  │  - rotate_secret()                                     │  │
│  │  - inject_secret()                                     │  │
│  │  - scan_repository()                                   │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                │
│            ┌───────────────┼───────────────┐                │
│            ▼               ▼               ▼                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Secret     │  │   Rotation   │  │  Injection   │     │
│  │   Backends   │  │   Engine     │  │  Handlers    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                 │                  │              │
│         ▼                 ▼                  ▼              │
│  ┌──────────────────────────────────────────────────┐     │
│  │         Oneiric Configuration Layer             │     │
│  │  - MAHAVISHNU_SECRETS__{SECRET_NAME}             │     │
│  │  - settings/mahavishnu.yaml                      │     │
│  │  - settings/local.yaml                           │     │
│  │  - Environment variables                          │     │
│  └──────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Secret Types Supported

| Secret Type | Description | Example | Auto-Rotation |
|-------------|-------------|---------|---------------|
| `API_KEY` | API keys for external services | `sk-...` (OpenAI) | Yes |
| `DATABASE_PASSWORD` | Database credentials | `postgres://...` | Yes |
| `SSH_KEY` | SSH private keys | `-----BEGIN RSA PRIVATE KEY-----` | No |
| `TLS_CERTIFICATE` | TLS/SSL certificates | `-----BEGIN CERTIFICATE-----` | No |
| `OAUTH_TOKEN` | OAuth access tokens | `Bearer ...` | Yes |
| `JWT_TOKEN` | JWT bearer tokens | `eyJ...` | Yes |
| `ENVIRONMENT_VARIABLE` | Generic environment variables | Any value | Yes |
| `SERVICE_ACCOUNT_KEY` | Service account JSON keys | Google Cloud JSON | No |
| `WEBHOOK_SECRET` | Webhook signature secrets | GitHub webhook secret | Yes |
| `ENCRYPTION_KEY` | Symmetric encryption keys | Base64-encoded key | No |

### Data Flow

```
1. Secret Storage:
   User → SecretVault.store_secret() → Encryption → Backend Storage

2. Secret Retrieval:
   Application → SecretVault.get_secret() → Backend → Decryption → Value

3. Secret Rotation:
   Scheduler → SecretVault.rotate_secret() → Generate New → Verify → Update Backend

4. Secret Injection:
   Application → SecretVault.inject_secret() → Get Secret → Inject (env/file/template)

5. Secret Scanning:
   Repository → SecretVault.scan_repository() → Pattern Matching → Report Findings
```

## Oneiric Integration

### Deep Oneiric Integration

The secrets management system extends Oneiric's layered configuration system to provide seamless secret access across all layers.

#### Oneiric Layer System

Oneiric loads configuration in layers (highest priority first):

1. **Environment Variables** (`MAHAVISHNU_SECRETS__*`)
2. **Local Configuration** (`settings/local.yaml`) - Gitignored
3. **Committed Configuration** (`settings/mahavishnu.yaml`)
4. **Default Values** (Pydantic model defaults)

#### Accessing Secrets via Oneiric

**Method 1: Environment Variable**

```python
import os
from oneiric.config import Config

# Load configuration
config = Config()

# Access secret via environment variable
api_key = os.getenv("MAHAVISHNU_SECRETS__OPENAI_API_KEY")
```

**Method 2: Direct Vault Access**

```python
from mahavishnu.integrations.secrets_management import SecretVault
from mahavishnu.core.config import MahavishnuSettings

# Initialize vault
settings = MahavishnuSettings()
vault = SecretVault(settings.secrets_management)
await vault.initialize()

# Get secret
value, record = await vault.get_secret("openai-api-key")
```

**Method 3: Oneiric Config Injection**

```python
from oneiric.config import Config

config = Config()

# Secrets are injected as: secrets.{secret_name}
openai_key = config.get("secrets.openai_api_key")
```

### Extending Oneiric for Secrets

To add custom secret providers to Oneiric, extend the `Config` class:

```python
from oneiric.config import Config, ConfigDict
from mahavishnu.integrations.secrets_management import SecretVault

class MahavishnuConfigWithSecrets(Config):
    """Extended Oneiric configuration with secrets integration."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._secret_vault = None

    async def get_secret(self, name: str) -> str | None:
        """Get secret from vault with Oneiric fallback."""
        # Try vault first
        if self._secret_vault:
            try:
                value, _ = await self._secret_vault.get_secret(name)
                return value
            except Exception:
                pass

        # Fall back to Oneiric layers
        return self.get(f"secrets.{name}")
```

### Configuration Schema

The secrets management configuration is defined in `MahavishnuSettings`:

```python
class SecretsConfig(BaseModel):
    """Configuration for secrets management system."""

    # Master encryption
    master_key_path: str = "data/secrets/master.key"

    # Storage backend selection
    default_backend: BackendType = BackendType.LOCAL
    storage_path: str = "data/secrets/vault.db"

    # Vault configuration
    vault_addr: str | None = None
    vault_token: str | None = None
    vault_mount: str = "secret"

    # AWS Secrets Manager
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # Azure Key Vault
    azure_vault_url: str | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None

    # Rotation
    rotation_enabled: bool = True
    rotation_days: int = 90
    rotate_before_expiry_days: int = 7
    verify_after_rotation: bool = True
    rollback_on_failure: bool = True

    # Scanning
    scan_on_write: bool = True
    scan_patterns: list[str] = [
        "*.py", "*.js", "*.ts", "*.yaml",
        "*.yml", "*.json", "*.env", "*.sh"
    ]

    # Access logging
    access_log_enabled: bool = True
    access_log_retention_days: int = 90

    # RBAC
    rbac_enabled: bool = False
    default_access_level: AccessLevel = AccessLevel.READ
```

### Configuration via Oneiric Layers

**settings/mahavishnu.yaml** (committed):
```yaml
secrets_management:
  enabled: true
  default_backend: local
  master_key_path: /var/lib/mahavishnu/secrets/master.key
  storage_path: /var/lib/mahavishnu/secrets/vault.db

  rotation:
    enabled: true
    rotation_days: 90
    verify_after_rotation: true

  scanning:
    enabled: true
    scan_on_write: true
```

**settings/local.yaml** (gitignored):
```yaml
secrets_management:
  vault_token: ${VAULT_TOKEN}  # From environment
  access_log_enabled: true
```

**Environment Variables**:
```bash
export MAHAVISHNU_SECRETS_MANAGEMENT__VAULT_TOKEN="s.1234567890"
export MAHAVISHNU_SECRETS_MANAGEMENT__STORAGE__ENCRYPTION_KEY="base64key"
```

## Secret Storage Backends

### Backend Comparison

| Backend | Encryption | Scalability | Cost | Complexity | Best For |
|---------|-----------|-------------|------|------------|----------|
| **Local** | AES-256-GCM | Low | Free | Low | Development, small deployments |
| **Vault** | AES-256-GCM | High | Paid | High | Production, enterprise |
| **AWS Secrets Manager** | KMS | Very High | Per secret | Medium | AWS environments |
| **Azure Key Vault** | HSM | Very High | Per operation | Medium | Azure environments |

### Local Backend (SQLite)

**Architecture**: Encrypted SQLite database with AES-256-GCM

**Pros**:
- Zero setup
- No external dependencies
- Free
- Fast for small datasets

**Cons**:
- Single-server only
- Manual backup required
- Limited scalability

**Setup**:
```python
from mahavishnu.integrations.secrets_management import SecretVault, SecretsConfig

config = SecretsConfig(
    default_backend=BackendType.LOCAL,
    master_key_path="data/secrets/master.key",
    storage_path="data/secrets/vault.db",
)

vault = SecretVault(config)
await vault.initialize()
```

**File Structure**:
```
data/secrets/
├── master.key          # Master encryption key (400 permissions)
├── vault.db            # Encrypted SQLite database
└── backups/            # Automatic backups
```

### Vault Backend (HashiCorp)

**Architecture**: Vault KV v2 secrets engine with AES-256-GCM

**Pros**:
- Centralized secret management
- Dynamic secrets (database credentials, certificates)
- Audit logging
- High availability
- Encryption as a service

**Cons**:
- Requires Vault infrastructure
- Paid for enterprise features
- More complex setup

**Setup**:

1. **Install Vault**:
```bash
# macOS
brew install vault

# Linux
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
sudo apt-get install vault
```

2. **Configure Vault**:
```bash
# Start Vault in dev mode (testing only)
vault server -dev

# Production setup
vault server -config=/etc/vault/config.hcl
```

3. **Enable KV v2**:
```bash
vault secrets enable -path=mahavishnu kv-v2
```

4. **Configure Mahavishnu**:

```yaml
# settings/mahavishnu.yaml
secrets_management:
  default_backend: vault
  vault_addr: "https://vault.example.com:8200"
  vault_token: "${VAULT_TOKEN}"  # From environment
  vault_mount: "mahavishnu"
```

```python
config = SecretsConfig(
    default_backend=BackendType.VAULT,
    vault_addr="https://vault.example.com:8200",
    vault_token=os.getenv("VAULT_TOKEN"),
    vault_mount="mahavishnu",
)
```

**Vault Authentication Methods**:

**Token Authentication** (simplest):
```bash
export VAULT_TOKEN="s.1234567890"
```

**AppRole Authentication** (recommended for production):
```python
import hvac

client = hvac.Client(url="https://vault.example.com:8200")

# Login with AppRole
client.auth.approle.login(
    role_id=os.getenv("VAULT_ROLE_ID"),
    secret_id=os.getenv("VAULT_SECRET_ID"),
)

token = client.token
```

**Kubernetes Authentication**:
```python
client = hvac.Client(url="https://vault.example.com:8200")
client.auth.kubernetes.login(
    role="mahavishnu",
    jwt_path="/var/run/secrets/kubernetes/serviceaccount/token",
)
```

### AWS Secrets Manager

**Architecture**: AWS KMS encryption with automatic rotation

**Pros**:
- Managed service (no infrastructure)
- Automatic rotation with Lambda
- High availability
- IAM integration
- Fine-grained access control

**Cons**:
- AWS vendor lock-in
- Cost per secret per month
- Latency for cross-region access

**Setup**:

1. **Create IAM Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:CreateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DeleteSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret/mahavishnu/*"
    }
  ]
}
```

2. **Configure Mahavishnu**:

```yaml
# settings/mahavishnu.yaml
secrets_management:
  default_backend: aws_secrets_manager
  aws_region: "us-east-1"
```

```bash
# AWS credentials via environment
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"
```

3. **Store Secret in AWS**:
```bash
aws secretsmanager create-secret \
  --name mahavishnu/openai-api-key \
  --secret-string "sk-..."
```

4. **Access from Code**:
```python
config = SecretsConfig(
    default_backend=BackendType.AWS_SECRETS_MANAGER,
    aws_region="us-east-1",
)

vault = SecretVault(config)
await vault.initialize()

value, record = await vault.get_secret("openai-api-key")
```

**Automatic Rotation with AWS**:

1. **Create Lambda Function**:
```python
import json
import boto3
import os

def lambda_handler(event, context):
    secret_name = event["SecretId"]
    client = boto3.client("secretsmanager")

    # Generate new secret
    new_secret = generate_new_secret()

    # Update secret
    client.put_secret_value(
        SecretId=secret_name,
        SecretString=new_secret,
    )

    return {"Status": "Success"}
```

2. **Enable Rotation**:
```bash
aws secretsmanager rotate-secret \
  --secret-id mahavishnu/openai-api-key \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:RotateSecret \
  --rotation-rules AutomaticallyAfterDays=90
```

### Azure Key Vault

**Architecture**: Azure HSM-backed encryption

**Pros**:
- Managed service
- HSM-backed security
- Azure AD integration
- Soft delete and purge protection
- Certificate management

**Cons**:
- Azure vendor lock-in
- Cost per operation
- Latency for cross-region access

**Setup**:

1. **Create Key Vault**:
```bash
az keyvault create \
  --name mahavishnu-vault \
  --resource-group mahavishnu-rg \
  --location eastus
```

2. **Create Service Principal**:
```bash
az ad sp create-for-rbac \
  --name mahavishnu \
  --skip-assignment
```

3. **Grant Access**:
```bash
az keyvault set-policy \
  --name mahavishnu-vault \
  --spn <client-id> \
  --secret-permissions get list set delete
```

4. **Configure Mahavishnu**:

```yaml
secrets_management:
  default_backend: azure_key_vault
  azure_vault_url: "https://mahavishnu-vault.vault.azure.net/"
```

```bash
export AZURE_TENANT_ID="..."
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
```

5. **Access from Code**:
```python
config = SecretsConfig(
    default_backend=BackendType.AZURE_KEY_VAULT,
    azure_vault_url="https://mahavishnu-vault.vault.azure.net/",
)

vault = SecretVault(config)
await vault.initialize()

value, record = await vault.get_secret("openai-api-key")
```

## Secret Lifecycle Management

### Secret Lifecycle States

```
┌─────────┐
│ CREATE  │ → User or system creates secret
└────┬────┘
     │
     ▼
┌─────────┐
│ ACTIVE  │ → Secret is in use, accessible to authorized users
└────┬────┘
     │
     ├──────────────────┐
     │                  │
     ▼                  ▼
┌─────────┐      ┌─────────┐
│ROTATING │      │ REVOKED │ → Manually revoked, access denied
└────┬────┘      └─────────┘
     │
     ▼
┌─────────┐
│ ACTIVE  │ → New version, continues to ACTIVE
└────┬────┘
     │
     ▼
┌─────────┐
│ EXPIRED │ → Past expiration date, cannot be used
└────┬────┘
     │
     ▼
┌─────────────────┐
│PENDING_DELETION│ → Scheduled for deletion
└─────────────────┘
```

### Creating Secrets

**Basic Secret Creation**:
```python
from mahavishnu.integrations.secrets_management import (
    SecretVault,
    SecretType,
    SecretsConfig,
)

vault = SecretVault()
await vault.initialize()

# Store API key
secret_id = await vault.store_secret(
    secret_type=SecretType.API_KEY,
    name="openai-api-key",
    value="sk-proj-abc123...",
    description="OpenAI API key for GPT-4 access",
    tags=["openai", "llm", "production"],
    service="openai",
    rotation_days=90,
)

print(f"Secret stored: {secret_id}")
```

**With Metadata**:
```python
from datetime import datetime, timedelta

# Store with expiration
secret_id = await vault.store_secret(
    secret_type=SecretType.DATABASE_PASSWORD,
    name="postgres-production",
    value="postgres://user:pass@host:5432/db",
    description="Production PostgreSQL connection string",
    service="postgresql",
    rotation_days=30,
    expires_at=datetime.now() + timedelta(days=180),
)
```

### Retrieving Secrets

**Simple Retrieval**:
```python
# Get secret value and metadata
value, record = await vault.get_secret("openai-api-key")

print(f"Value: {value}")
print(f"Type: {record.secret_type}")
print(f"Created: {record.metadata.created_at}")
print(f"Expires: {record.metadata.expires_at}")
print(f"Days remaining: {record.metadata.days_remaining}")
```

**With Error Handling**:
```python
from mahavishnu.integrations.secrets_management import (
    SecretNotFoundError,
    AuthorizationError,
)

try:
    value, record = await vault.get_secret("openai-api-key")
    print(f"Secret retrieved: {value[:10]}...")

except SecretNotFoundError:
    print("Secret not found - check secret name")

except AuthorizationError:
    print("Not authorized to access this secret")

except Exception as e:
    print(f"Error: {e}")
```

### Updating Secrets

**Update Without Rotation**:
```python
# Update secret value (new version created)
updated_record = await vault.update_secret(
    name="openai-api-key",
    value="sk-proj-newkey456...",
    user="admin@company.com",
)

print(f"Updated to version: {updated_record.metadata.version}")
```

### Rotating Secrets

**Manual Rotation**:
```python
# Rotate secret with verification
result = await vault.rotate_secret(
    name="openai-api-key",
    new_value="sk-proj-newkey789...",  # Optional: auto-generate
    verify=True,  # Verify secret works after rotation
    rollback_on_failure=True,  # Rollback if verification fails
)

if result.success:
    print(f"Rotated: {result.old_version} → {result.new_version}")
else:
    print(f"Rotation failed: {result.error}")
    if result.rolled_back:
        print("Rolled back to previous version")
```

**Automatic Rotation**:
```python
# Background task runs every hour
async def rotation_scheduler():
    while True:
        # Check all secrets for rotation needs
        secrets = await vault.list_secrets(status=SecretStatus.ACTIVE)

        for secret in secrets:
            # Check if rotation needed
            if await vault._should_rotate(secret):
                print(f"Rotating: {secret.name}")
                await vault.rotate_secret(secret.name)

        # Sleep for 1 hour
        await asyncio.sleep(3600)

# Start rotation scheduler
asyncio.create_task(rotation_scheduler())
```

### Deleting Secrets

**Soft Delete (Pending Deletion)**:
```python
# Mark secret for deletion (recoverable for 30 days)
from datetime import datetime, timedelta

# Update metadata to pending deletion
await vault.update_metadata(
    domain="old-secret",
    status="pending_deletion",
)

# Secret is now inaccessible but not deleted
```

**Hard Delete**:
```python
# Permanently delete secret
deleted = await vault.delete_secret(
    name="old-secret",
    user="admin@company.com",
)

if deleted:
    print("Secret permanently deleted")
```

## Secret Injection

Secret injection delivers secrets to applications without hardcoding them in configuration files.

### Injection Methods

#### Environment Variable Injection

**Use Case**: Container orchestration (Kubernetes, Docker Compose)

**Setup**:
```python
from mahavishnu.integrations.secrets_management import (
    SecretVault,
    InjectionType,
)

vault = SecretVault()
await vault.initialize()

# Inject as environment variable
await vault.inject_secret(
    secret_name="openai-api-key",
    injection_type=InjectionType.ENV_VAR,
    target="my-app",
    env_var_name="OPENAI_API_KEY",
    restart_required=True,
)
```

**Kubernetes Deployment**:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: myapp:latest
    env:
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: mahavishnu-secrets
          key: openai-api-key
```

**Mahavishnu Integration**:
```python
# Mahavishnu automatically injects secrets before launching workers
async def inject_secrets_before_start(worker_config):
    vault = SecretVault()
    await vault.initialize()

    # Inject secrets from configuration
    for secret_ref in worker_config.required_secrets:
        await vault.inject_secret(
            secret_name=secret_ref.name,
            injection_type=InjectionType.ENV_VAR,
            target="worker",
            env_var_name=secret_ref.env_var,
        )
```

#### File Mount Injection

**Use Case**: Applications that read secrets from files (NGINX, Apache)

**Setup**:
```python
# Mount secret as file
await vault.inject_secret(
    secret_name="tls-certificate",
    injection_type=InjectionType.FILE_MOUNT,
    target="nginx",
    file_path="/etc/secrets/tls.crt",
    file_permissions="0400",  # Read-only owner
)
```

**Kubernetes Secret**:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: tls-certificate
type: Opaque
stringData:
  tls.crt: |
    -----BEGIN CERTIFICATE-----
    ...
    -----END CERTIFICATE-----
---
apiVersion: v1
kind: Pod
metadata:
  name: nginx
spec:
  containers:
  - name: nginx
    image: nginx:latest
    volumeMounts:
    - name: tls-cert
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: tls-cert
    secret:
      secretName: tls-certificate
```

#### Template Reference Injection

**Use Case**: Configuration files with secret placeholders

**Template File** (`config.yaml`):
```yaml
database:
  host: postgres.example.com
  port: 5432
  username: admin
  password: {{ POSTGRES_PASSWORD }}
  ssl: true
```

**Injection**:
```python
# Inject secret via template replacement
await vault.inject_secret(
    secret_name="postgres-password",
    injection_type=InjectionType.TEMPLATE_REFERENCE,
    target="my-app",
    template_pattern="{{ POSTGRES_PASSWORD }}",
)
```

**Implementation**:
```python
import re
from pathlib import Path

async def inject_template_secrets(config_path: Path):
    vault = SecretVault()
    await vault.initialize()

    # Read template
    content = config_path.read_text()

    # Find all secret placeholders
    pattern = r"\{\{\s*(\w+)\s*\}\}"
    matches = re.findall(pattern, content)

    # Replace each placeholder
    for secret_name in matches:
        value, _ = await vault.get_secret(secret_name)
        content = content.replace(f"{{{{ {secret_name }}}}", value)

    # Write injected config (in-memory only, never commit!)
    injected_path = config_path.with_suffix(".injected.yaml")
    injected_path.write_text(content)

    # Set restrictive permissions
    injected_path.chmod(0o400)
```

### Dynamic Secret Updates

**Hot-Reload Without Restart**:
```python
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SecretReloadHandler(FileSystemEventHandler):
    """Reload secrets when vault changes."""

    def __init__(self, vault: SecretVault):
        self.vault = vault
        self.subscribers = []

    def on_modified(self, event):
        """Handle vault modification."""
        if event.src_path.endswith("vault.db"):
            asyncio.create_task(self._notify_subscribers())

    async def _notify_subscribers(self):
        """Notify all subscribers of secret update."""
        for callback in self.subscribers:
            await callback()

    def subscribe(self, callback):
        """Subscribe to secret updates."""
        self.subscribers.append(callback)

# Usage
async def update_openai_config():
    """Update OpenAI client when secret changes."""
    vault = SecretVault()
    await vault.initialize()

    # Get new secret
    api_key, _ = await vault.get_secret("openai-api-key")

    # Update client configuration
    openai.api_key = api_key

    print("OpenAI API key updated")

# Watch for changes
handler = SecretReloadHandler(vault)
handler.subscribe(update_openai_config)

observer = Observer()
observer.schedule(handler, path="data/secrets", recursive=False)
observer.start()
```

## Secret Scanning

Secret scanning detects hardcoded secrets in codebases before they're committed to version control.

### Scanning Patterns

The scanner uses regex patterns to detect various secret types:

| Pattern Type | Regex Pattern | Confidence | Severity |
|--------------|--------------|------------|----------|
| OpenAI API Key | `sk-[a-zA-Z0-9]{48}` | 0.9 | Critical |
| GitHub Token | `ghp_[a-zA-Z0-9]{36}` | 0.9 | High |
| AWS Access Key | `aws.*access[_-]?key.*[:=].*['\"]([a-z0-9/+=]{20,})['\"]` | 0.7 | High |
| Stripe Key | `sk_live_[a-zA-Z0-9]{24,}` | 0.9 | Critical |
| Private Key | `-----BEGIN [A-Z]+ PRIVATE KEY-----` | 1.0 | Critical |
| Database URL | `(postgres|mysql)://[^:]+:[^@]+@[^/]+` | 0.6 | High |
| JWT Token | `eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+` | 0.5 | Medium |

### Running Scans

**Scan Entire Repository**:
```python
from mahavishnu.integrations.secrets_management import SecretVault

vault = SecretVault()
await vault.initialize()

# Scan repository
report = await vault.scan_repository(
    repository_path="/path/to/repo",
    file_patterns=None,  # Use default patterns
    secret_types=None,  # Scan all types
)

# Print results
print(f"Scanned: {report.files_scanned} files")
print(f"Findings: {report.total_findings} secrets")
print(f"  Critical: {report.critical_count}")
print(f"  High: {report.high_count}")
print(f"  Medium: {report.medium_count}")
print(f"  Low: {report.low_count}")
```

**Scan Specific File Patterns**:
```python
# Scan only Python and YAML files
report = await vault.scan_repository(
    repository_path="/path/to/repo",
    file_patterns=["*.py", "*.yaml", "*.yml"],
)
```

**Scan Specific Secret Types**:
```python
from mahavishnu.integrations.secrets_management import SecretType

# Scan for API keys and database passwords only
report = await vault.scan_repository(
    repository_path="/path/to/repo",
    secret_types=[SecretType.API_KEY, SecretType.DATABASE_PASSWORD],
)
```

### Pre-Commit Hook

**Setup Pre-Commit Hook** (`.git/hooks/pre-commit`):
```bash
#!/bin/bash
# Pre-commit hook to scan for secrets

echo "Scanning for hardcoded secrets..."

# Run scan
python -c "
import asyncio
from mahavishnu.integrations.secrets_management import SecretVault

async def scan():
    vault = SecretVault()
    await vault.initialize()

    report = await vault.scan_repository('.')

    if report.total_findings > 0:
        print(f'\n❌ Found {report.total_findings} hardcoded secrets!')
        print('Please remove them before committing.')

        for finding in report.findings[:10]:  # Show first 10
            print(f'  {finding.file_path}:{finding.line_number}')
            print(f'    Type: {finding.secret_type.value}')
            print(f'    Severity: {finding.severity}')

        if report.total_findings > 10:
            print(f'  ... and {report.total_findings - 10} more')

        exit(1)

    print('✅ No secrets found')

asyncio.run(scan())
"

# Check exit code
if [ $? -ne 0 ]; then
    exit 1
fi
```

**Install Hook**:
```bash
# Make executable
chmod +x .git/hooks/pre-commit

# Test
git commit -m "test"  # Should trigger scan
```

### CI/CD Integration

**GitHub Actions** (`.github/workflows/secret-scan.yml`):
```yaml
name: Secret Scanning

on: [pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install mahavishnu

    - name: Scan for secrets
      env:
        MAHAVISHNU_SECRETS__SCAN_ENABLED: "true"
      run: |
        python -c "
import asyncio
from mahavishnu.integrations.secrets_management import SecretVault

async def scan():
    vault = SecretVault()
    await vault.initialize()

    report = await vault.scan_repository('.')

    if report.total_findings > 0:
        print(f'Found {report.total_findings} secrets!')
        exit(1)

asyncio.run(scan())
        "
```

### Custom Patterns

**Add Custom Pattern**:
```python
from mahavishnu.integrations.secrets_management import SECRET_PATTERNS, SecretType

# Add custom pattern for company-specific tokens
SECRET_PATTERNS[SecretType.API_KEY].append(
    r"COMPANY_TOKEN_[A-Z0-9]{32}"
)

# Now scans will detect COMPANY_TOKEN_ patterns
```

## Security Best Practices

### Master Key Management

**Generate Secure Master Key**:
```python
import os

# Generate 256-bit (32 byte) master key
master_key = os.urandom(32)

# Encode as base64 for storage
import base64
master_key_b64 = base64.b64encode(master_key).decode()

# Store in secure location
with open("data/secrets/master.key", "wb") as f:
    f.write(master_key)

# Set restrictive permissions
import os
os.chmod("data/secrets/master.key", 0o400)  # Read-only owner
```

**Hardware Security Module (HSM)**:
```python
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Derive master key from hardware-protected key
def derive_master_key_from_hsm(hsm_key: bytes, salt: bytes) -> bytes:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"mahavishnu-master-key",
    )
    return kdf.derive(hsm_key)
```

### Secret Access Control

**Role-Based Access Control (RBAC)**:
```python
from mahavishnu.integrations.secrets_management import AccessLevel

# Configure RBAC
config = SecretsConfig(
    rbac_enabled=True,
    default_access_level=AccessLevel.READ,
)

# Define role permissions
ROLE_PERMISSIONS = {
    "admin": [AccessLevel.READ, AccessLevel.WRITE, AccessLevel.DELETE, AccessLevel.ADMIN],
    "developer": [AccessLevel.READ, AccessLevel.WRITE],
    "operator": [AccessLevel.READ],
    "auditor": [AccessLevel.READ],
}

# Check access in custom RBAC implementation
async def check_rbac_access(user: str, secret: SecretRecord, required: AccessLevel) -> bool:
    # Get user roles from your auth system
    user_roles = await get_user_roles(user)

    # Check if any role has required permission
    for role in user_roles:
        if required in ROLE_PERMISSIONS.get(role, []):
            return True

    return False
```

### Audit Logging

**Enable Comprehensive Logging**:
```python
from mahavishnu.integrations.secrets_management import SecretVault

vault = SecretVault()
await vault.initialize()

# All secret access is automatically logged
value, record = await vault.get_secret("openai-api-key", user="john@company.com")

# View access log
log = await vault.get_access_log("openai-api-key")

print(f"Total accesses: {log.total_accesses}")
print(f"Failed accesses: {log.failed_accesses}")

for entry in log.entries:
    print(f"{entry.timestamp}: {entry.user} - {entry.action}")
```

**Integrate with SIEM**:
```python
import aiohttp

async def send_to_siem(log_entry: AccessLogEntry):
    """Send access log to SIEM (Splunk, Elasticsearch, etc.)."""
    payload = {
        "timestamp": log_entry.timestamp.isoformat(),
        "user": log_entry.user,
        "action": log_entry.action,
        "secret_id": log_entry.secret_id,
        "source_ip": log_entry.source_ip,
        "success": log_entry.success,
    }

    async with aiohttp.ClientSession() as session:
        await session.post(
            "https://splunk.example.com:8088/services/collector",
            json=payload,
            headers={"Authorization": "Splunk <token>"},
        )
```

### Secret Rotation Best Practices

**Rotation Strategy**:
1. **API Keys**: Rotate every 90 days
2. **Database Passwords**: Rotate every 30-60 days
3. **Certificates**: Rotate 7-30 days before expiry
4. **OAuth Tokens**: Rotate before expiration

**Safe Rotation Process**:
```python
async def safe_rotation_with_verification(
    vault: SecretVault,
    secret_name: str,
    verify_fn: callable,  # Function to test new secret
):
    """Rotate secret with verification and rollback."""

    # 1. Get current secret
    current_value, _ = await vault.get_secret(secret_name)

    # 2. Generate new secret
    new_value = generate_new_secret(secret_name)

    # 3. Update secret (version +1)
    try:
        await vault.update_secret(
            name=secret_name,
            value=new_value,
            rotate=True,
        )

        # 4. Verify new secret works
        if not await verify_fn(new_value):
            raise Exception("Verification failed")

        print(f"✅ Rotation successful: {secret_name}")

    except Exception as e:
        # 5. Rollback on failure
        print(f"❌ Rotation failed: {e}, rolling back...")
        await vault.update_secret(
            name=secret_name,
            value=current_value,
            rotate=False,
        )
        print("✅ Rollback complete")
```

### Compliance

**SOC2 Compliance**:
- Enable access logging: `access_log_enabled: true`
- Set retention period: `access_log_retention_days: 365` (7 years)
- Enable RBAC: `rbac_enabled: true`
- Enforce rotation: `rotation_days: 90`

**HIPAA Compliance**:
- Encrypt at rest: AES-256-GCM (default)
- Encrypt in transit: TLS 1.3 for all connections
- Audit trails: Access logging with user attribution
- Minimum necessary: RBAC with least privilege

**PCI-DSS Compliance**:
- Rotate quarterly: `rotation_days: 90`
- Strong cryptography: AES-256-GCM
- Access control: RBAC + MFA
- Audit logs: Immutable logging with 1-year retention

## Setup Guides

### Development Setup

**1. Install Dependencies**:
```bash
cd /path/to/mahavishnu
pip install -e ".[dev]"
```

**2. Enable Secrets Management**:
```yaml
# settings/mahavishnu.yaml
secrets_management:
  enabled: true
  default_backend: local
  master_key_path: data/secrets/master.key
  storage_path: data/secrets/vault.db

  rotation:
    enabled: false  # Disable in development

  scanning:
    enabled: true
    scan_on_write: true
```

**3. Initialize Vault**:
```python
from mahavishnu.integrations.secrets_management import create_vault

vault = await create_vault()
```

**4. Store First Secret**:
```python
await vault.store_secret(
    secret_type=SecretType.API_KEY,
    name="openai-test-key",
    value="sk-test-...",
    description="Test OpenAI key for development",
)
```

### Production Setup

**1. Use HashiCorp Vault**:
```yaml
# settings/mahavishnu.yaml (production)
secrets_management:
  enabled: true
  default_backend: vault
  vault_addr: "https://vault.example.com:8200"
  vault_token: "${VAULT_TOKEN}"  # From environment
  vault_mount: "mahavishnu"

  rotation:
    enabled: true
    rotation_days: 90
    verify_after_rotation: true
    rollback_on_failure: true

  scanning:
    enabled: true
    scan_on_write: true

  access_log_enabled: true
  access_log_retention_days: 365
  rbac_enabled: true
```

**2. Configure Vault AppRole**:
```bash
# Create AppRole for Mahavishnu
vault auth enable approle
vault write auth/approle/role/mahavishnu \
  token_policies="mahavishnu-policy" \
  token_ttl=1h \
  token_max_ttl=4h

# Get Role ID and Secret ID
vault read auth/approle/role/mahavishnu/role-id
vault write -f auth/approle/role/mahavishnu/secret-id
```

**3. Set Environment Variables**:
```bash
export VAULT_ADDR="https://vault.example.com:8200"
export VAULT_ROLE_ID="..."
export VAULT_SECRET_ID="..."
export MAHAVISHNU_SECRETS_MANAGEMENT__VAULT_TOKEN="$(vault write -field=token auth/approle/login role_id=${VAULT_ROLE_ID} secret_id=${VAULT_SECRET_ID})"
```

**4. Enable Automatic Rotation**:
```python
# Create rotation schedule
import asyncio
from mahavishnu.integrations.secrets_management import SecretVault

async def rotation_scheduler():
    vault = SecretVault()
    await vault.initialize()

    while True:
        # Check for secrets needing rotation
        secrets = await vault.list_secrets(status=SecretStatus.ACTIVE)

        for secret in secrets:
            if await vault._should_rotate(secret):
                print(f"Rotating: {secret.name}")
                await vault.rotate_secret(secret.name)

        # Sleep 1 hour
        await asyncio.sleep(3600)

# Start scheduler
asyncio.create_task(rotation_scheduler())
```

**5. Setup Monitoring**:
```yaml
# Enable Grafana dashboard
# See: docs/grafana/secrets-dashboard.json
```

### AWS Setup

**1. Create Secrets Manager Secret**:
```bash
aws secretsmanager create-secret \
  --name mahavishnu/openai-api-key \
  --description "OpenAI API key for Mahavishnu" \
  --secret-string "sk-proj-..."
```

**2. Configure IAM Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:mahavishnu/*"
    }
  ]
}
```

**3. Configure Mahavishnu**:
```yaml
secrets_management:
  enabled: true
  default_backend: aws_secrets_manager
  aws_region: "us-east-1"
```

**4. Enable Automatic Rotation**:
```bash
# Create Lambda function
aws lambda create-function \
  --function-name RotateMahavishnuSecret \
  --runtime python3.11 \
  --role lambda-secrets-manager-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip

# Enable rotation
aws secretsmanager rotate-secret \
  --secret-id mahavishnu/openai-api-key \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:RotateMahavishnuSecret \
  --rotation-rules AutomaticallyAfterDays=90
```

### Azure Setup

**1. Create Key Vault**:
```bash
az keyvault create \
  --name mahavishnu-kv \
  --resource-group mahavishnu-rg \
  --location eastus \
  --enable-purge-protection true \
  --enable-soft-delete true
```

**2. Create Service Principal**:
```bash
az ad sp create-for-rbac \
  --name mahavishnu-secrets \
  --skip-assignment

# Capture output
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
export AZURE_TENANT_ID="..."
```

**3. Grant Access Policy**:
```bash
az keyvault set-policy \
  --name mahavishnu-kv \
  --spn $AZURE_CLIENT_ID \
  --secret-permissions get list set delete
```

**4. Store Secret**:
```bash
az keyvault secret set \
  --vault-name mahavishnu-kv \
  --name openai-api-key \
  --value "sk-proj-..."
```

**5. Configure Mahavishnu**:
```yaml
secrets_management:
  enabled: true
  default_backend: azure_key_vault
  azure_vault_url: "https://mahavishnu-kv.vault.azure.net/"
```

## Troubleshooting

### Common Issues

**Issue: "Master key not found"**

**Cause**: Master key file doesn't exist or path is incorrect

**Solution**:
```bash
# Check if master key exists
ls -la data/secrets/master.key

# If missing, generate new key
python -c "
import os
from mahavishnu.integrations.secrets_management import SecretVault

# Generate and save master key
master_key = os.urandom(32)
os.makedirs('data/secrets', exist_ok=True)
with open('data/secrets/master.key', 'wb') as f:
    f.write(master_key)
os.chmod('data/secrets/master.key', 0o400)
print('✅ Master key generated')
"
```

**Issue: "Failed to decrypt secret"**

**Cause**: Master key changed or secret corrupted

**Solution**:
```python
# Verify master key
from pathlib import Path

master_key_path = Path("data/secrets/master.key")
if not master_key_path.exists():
    print("❌ Master key not found!")
    print("If you have a backup, restore from:")
    print("  data/secrets/backups/")
else:
    print("✅ Master key found")

    # Test decryption
    from mahavishnu.integrations.secrets_management import SecretVault
    vault = SecretVault()
    await vault.initialize()

    try:
        value, _ = await vault.get_secret("test-secret")
        print(f"✅ Decryption successful: {value[:10]}...")
    except Exception as e:
        print(f"❌ Decryption failed: {e}")
```

**Issue: "Vault connection refused"**

**Cause**: Vault server not running or incorrect address

**Solution**:
```bash
# Check Vault status
vault status

# If not running, start Vault
vault server -dev  # Development only

# Production: Check Vault service
sudo systemctl status vault

# Test connection
curl https://vault.example.com:8200/v1/sys/health
```

**Issue: "AWS credentials not found"**

**Cause**: AWS credentials not configured

**Solution**:
```bash
# Option 1: Environment variables
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"

# Option 2: AWS credentials file
aws configure

# Option 3: IAM role (EC2/Lambda)
# No configuration needed, automatically uses instance profile

# Test credentials
aws sts get-caller-identity
```

**Issue: "Secret not found in Azure"**

**Cause**: Secret name incorrect or permissions issue

**Solution**:
```bash
# List all secrets
az keyvault secret list \
  --vault-name mahavishnu-kv \
  --output table

# Check permissions
az keyvault show \
  --name mahavishnu-kv \
  --resource-group mahavishnu-rg

# Verify service principal has access
az ad sp show --id $AZURE_CLIENT_ID
```

### Debug Mode

**Enable Debug Logging**:
```yaml
# settings/mahavishnu.yaml
log_level: "DEBUG"
```

```python
import structlog

logger = structlog.get_logger(__name__)
logger.debug("Secret vault operations", operation="get_secret", secret_name="test")
```

**Enable Vault Audit Logging**:
```bash
# Enable Vault audit logging
vault audit enable file file_path=/var/log/vault_audit.log

# View audit logs
tail -f /var/log/vault_audit.log
```

### Recovery Procedures

**Restore from Backup**:
```bash
# List backups
ls -lah data/secrets/backups/

# Restore specific backup
cp data/secrets/backups/vault.db.backup_20240101 data/secrets/vault.db

# Restart Mahavishnu
mahavishnu restart
```

**Recover Master Key**:
```python
# If you have a master key backup
from pathlib import Path
import shutil

# Restore from backup
backup_key = Path("data/secrets/master.key.backup")
shutil.copy(backup_key, "data/secrets/master.key")

# Set permissions
import os
os.chmod("data/secrets/master.key", 0o400)
```

### Performance Tuning

**Optimize for High Throughput**:
```python
from mahavishnu.integrations.secrets_management import SecretVault, SecretsConfig

config = SecretsConfig(
    # Use faster backend (Vault > AWS > Local)
    default_backend=BackendType.VAULT,

    # Enable connection pooling
    vault_max_connections=100,

    # Cache secrets in memory (TTL: 5 minutes)
    cache_enabled=True,
    cache_ttl_seconds=300,
)

vault = SecretVault(config)
await vault.initialize()
```

**Optimize for Low Latency**:
```python
# Preload frequently accessed secrets
async def preload_secrets(vault: SecretVault, secret_names: list[str]):
    """Preload secrets into cache."""
    for name in secret_names:
        try:
            await vault.get_secret(name)
            print(f"✅ Preloaded: {name}")
        except Exception as e:
            print(f"❌ Failed to preload {name}: {e}")

# Preload on startup
await preload_secrets(vault, [
    "openai-api-key",
    "postgres-password",
    "redis-password",
])
```

## API Reference

### SecretVault

**Main interface for secrets management.**

#### Methods

##### `store_secret()`

Store a new secret in the vault.

**Signature**:
```python
async def store_secret(
    self,
    secret_type: SecretType,
    name: str,
    value: str,
    description: str = "",
    tags: list[str] | None = None,
    service: str | None = None,
    rotation_days: int | None = None,
    expires_at: datetime | None = None,
    created_by: str = "system",
) -> str
```

**Parameters**:
- `secret_type` (SecretType): Type of secret being stored
- `name` (str): Unique secret name (alphanumeric, dash, underscore, dot)
- `value` (str): Secret value to encrypt and store
- `description` (str): Human-readable description
- `tags` (list[str]): Tags for organization and filtering
- `service` (str): Service this secret is for (e.g., "openai")
- `rotation_days` (int): Rotation interval in days (1-365)
- `expires_at` (datetime): Optional expiration date
- `created_by` (str): User or service creating the secret

**Returns**:
- `str`: Secret ID (SHA-256 hash of name)

**Raises**:
- `SecretAlreadyExistsError`: If secret with same name exists
- `SecretEncryptionError`: If encryption fails

**Example**:
```python
secret_id = await vault.store_secret(
    secret_type=SecretType.API_KEY,
    name="openai-api-key",
    value="sk-proj-abc123...",
    description="OpenAI API key for GPT-4",
    tags=["openai", "llm", "production"],
    service="openai",
    rotation_days=90,
)
```

##### `get_secret()`

Retrieve and decrypt a secret.

**Signature**:
```python
async def get_secret(
    self,
    name: str,
    user: str = "system",
    source_ip: str | None = None,
) -> tuple[str, SecretRecord]
```

**Parameters**:
- `name` (str): Secret name
- `user` (str): User or service requesting the secret
- `source_ip` (str | None): Optional source IP address

**Returns**:
- `tuple[str, SecretRecord]`: (decrypted_value, secret_record)

**Raises**:
- `SecretNotFoundError`: If secret not found
- `SecretDecryptionError`: If decryption fails
- `AuthorizationError`: If user lacks access

**Example**:
```python
value, record = await vault.get_secret(
    name="openai-api-key",
    user="john@company.com",
    source_ip="192.168.1.100",
)

print(f"Value: {value}")
print(f"Type: {record.secret_type}")
print(f"Created: {record.metadata.created_at}")
```

##### `rotate_secret()`

Rotate a secret with verification and rollback.

**Signature**:
```python
async def rotate_secret(
    self,
    name: str,
    new_value: str | None = None,
    verify: bool = True,
    rollback_on_failure: bool = True,
) -> RotationResult
```

**Parameters**:
- `name` (str): Secret name to rotate
- `new_value` (str | None): New secret value (None to auto-generate)
- `verify` (bool): Verify secret works after rotation
- `rollback_on_failure` (bool): Rollback if verification fails

**Returns**:
- `RotationResult`: Rotation result with success status and version info

**Example**:
```python
result = await vault.rotate_secret(
    name="openai-api-key",
    new_value="sk-proj-newkey456...",
    verify=True,
    rollback_on_failure=True,
)

if result.success:
    print(f"Rotated: {result.old_version} → {result.new_version}")
else:
    print(f"Failed: {result.error}")
```

##### `inject_secret()`

Inject a secret into an application.

**Signature**:
```python
async def inject_secret(
    self,
    secret_name: str,
    injection_type: InjectionType,
    target: str,
    env_var_name: str | None = None,
    file_path: str | None = None,
    template_pattern: str | None = None,
    restart_required: bool = True,
    user: str = "system",
) -> bool
```

**Parameters**:
- `secret_name` (str): Name of secret to inject
- `injection_type` (InjectionType): How to inject the secret
- `target` (str): Target application or service
- `env_var_name` (str | None): Environment variable name (for ENV_VAR type)
- `file_path` (str | None): File path for mounting (for FILE_MOUNT type)
- `template_pattern` (str | None): Template pattern (for TEMPLATE_REFERENCE type)
- `restart_required` (bool): Restart application after injection
- `user` (str): User performing injection

**Returns**:
- `bool`: True if injection succeeded

**Example**:
```python
success = await vault.inject_secret(
    secret_name="openai-api-key",
    injection_type=InjectionType.ENV_VAR,
    target="my-app",
    env_var_name="OPENAI_API_KEY",
)
```

##### `scan_repository()`

Scan a repository for hardcoded secrets.

**Signature**:
```python
async def scan_repository(
    self,
    repository_path: str,
    file_patterns: list[str] | None = None,
    secret_types: list[SecretType] | None = None,
) -> SecretScanReport
```

**Parameters**:
- `repository_path` (str): Path to repository to scan
- `file_patterns` (list[str] | None): File patterns to scan (default: config.scan_patterns)
- `secret_types` (list[SecretType] | None): Secret types to scan for (default: all)

**Returns**:
- `SecretScanReport`: Scan report with findings

**Example**:
```python
report = await vault.scan_repository(
    repository_path="/path/to/repo",
    file_patterns=["*.py", "*.yaml"],
    secret_types=[SecretType.API_KEY, SecretType.DATABASE_PASSWORD],
)

print(f"Found {report.total_findings} secrets")
for finding in report.findings:
    print(f"  {finding.file_path}:{finding.line_number} - {finding.secret_type.value}")
```

### Data Models

#### `SecretsConfig`

Configuration for secrets management system.

**Fields**:
- `enabled` (bool): Enable secrets management
- `master_key_path` (str): Path to master encryption key
- `storage_path` (str): Path to local secret storage
- `default_backend` (BackendType): Default backend for storing secrets
- `vault_addr` (str | None): HashiCorp Vault address
- `vault_token` (str | None): Vault token
- `vault_mount` (str): Vault KV mount point
- `aws_region` (str | None): AWS region for Secrets Manager
- `azure_vault_url` (str | None): Azure Key Vault URL
- `rotation` (RotationConfig): Automatic rotation settings
- `scan_on_write` (bool): Scan code on write operations
- `scan_patterns` (list[str]): File patterns to scan for secrets
- `access_log_enabled` (bool): Enable secret access logging
- `access_log_retention_days` (int): Retention period for access logs
- `rbac_enabled` (bool): Enable role-based access control

**Example**:
```python
config = SecretsConfig(
    enabled=True,
    default_backend=BackendType.VAULT,
    vault_addr="https://vault.example.com:8200",
    vault_mount="mahavishnu",
    rotation=RotationConfig(
        enabled=True,
        rotation_days=90,
    ),
)
```

#### `SecretRecord`

A secret record stored in the vault.

**Fields**:
- `id` (str): Unique secret identifier
- `name` (str): Secret name (unique identifier)
- `secret_type` (SecretType): Type of secret
- `status` (SecretStatus): Current status
- `encrypted_value` (bytes): Encrypted secret value
- `nonce` (bytes): AES-GCM nonce for decryption
- `salt` (bytes): Salt for key derivation
- `metadata` (SecretMetadata): Secret metadata
- `backend` (BackendType): Backend storing this secret

**Example**:
```python
record = SecretRecord(
    id="abc123",
    name="openai-api-key",
    secret_type=SecretType.API_KEY,
    status=SecretStatus.ACTIVE,
    encrypted_value=b"...",
    nonce=b"...",
    salt=b"...",
    metadata=SecretMetadata(
        created_by="admin@company.com",
        description="OpenAI API key",
    ),
)
```

#### `SecretMetadata`

Metadata associated with a secret.

**Fields**:
- `created_at` (datetime): When the secret was created
- `updated_at` (datetime): When the secret was last updated
- `expires_at` (datetime | None): When the secret expires
- `rotation_days` (int): Rotation interval in days (1-365)
- `last_rotated` (datetime | None): When the secret was last rotated
- `version` (int): Secret version number
- `created_by` (str): User/service that created the secret
- `description` (str): Human-readable description
- `tags` (list[str]): Tags for organizing secrets
- `service` (str | None): Service this secret is for
- `environment` (str): Environment (production, staging, development)

**Example**:
```python
metadata = SecretMetadata(
    created_by="admin@company.com",
    description="OpenAI API key for GPT-4",
    tags=["openai", "llm"],
    service="openai",
    rotation_days=90,
)
```

### Enums

#### `SecretType`

Types of secrets supported by the vault.

**Values**:
- `API_KEY`: API key for external services
- `DATABASE_PASSWORD`: Database credentials
- `SSH_KEY`: SSH private key
- `TLS_CERTIFICATE`: TLS/SSL certificate
- `OAUTH_TOKEN`: OAuth access token
- `JWT_TOKEN`: JWT bearer token
- `ENVIRONMENT_VARIABLE`: Generic environment variable
- `SERVICE_ACCOUNT_KEY`: Service account JSON key
- `WEBHOOK_SECRET`: Webhook signature secret
- `ENCRYPTION_KEY`: Symmetric encryption key

#### `SecretStatus`

Status of a secret in the vault.

**Values**:
- `ACTIVE`: Secret is active and in use
- `ROTATING`: Secret is currently being rotated
- `EXPIRED`: Secret has expired
- `REVOKED`: Secret has been revoked
- `PENDING_DELETION`: Secret is scheduled for deletion

#### `InjectionType`

Methods for injecting secrets into applications.

**Values**:
- `ENV_VAR`: Inject as environment variable
- `FILE_MOUNT`: Mount as file (for Kubernetes/Docker)
- `DYNAMIC_UPDATE`: Dynamically update running application
- `TEMPLATE_REFERENCE`: Template-based reference in config files

#### `BackendType`

Secret storage backend providers.

**Values**:
- `LOCAL`: Local file-based storage (encrypted)
- `VAULT`: HashiCorp Vault
- `AWS_SECRETS_MANAGER`: AWS Secrets Manager
- `AZURE_KEY_VAULT`: Azure Key Vault

---

**Next**: [Rate Limiting Guide](RATE_LIMITING_GUIDE.md)
