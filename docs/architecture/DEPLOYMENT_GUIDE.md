# Mahavishnu Deployment Guide: Claude Code + Qwen Integration

**Version:** 1.0
**Date:** 2025-01-24
**Purpose:** Comprehensive guide for deploying Mahavishnu with Claude Code and Qwen

______________________________________________________________________

## Table of Contents

1. [Deployment Overview](#deployment-overview)
1. [Option 1: Mahavishnu as MCP Server for Claude Code](#option-1-mahavishnu-as-mcp-server-for-claude-code)
1. [Option 2: Mahavishnu Embedded in Qwen Sessions](#option-2-mahavishnu-embedded-in-qwen-sessions)
1. [Option 3: Hybrid Deployment (Both Claude Code and Qwen)](#option-3-hybrid-deployment-both-claude-code-and-qwen)
1. [Subscription Authentication Setup](#subscription-authentication-setup)
1. [Configuration Examples](#configuration-examples)
1. [Troubleshooting](#troubleshooting)

______________________________________________________________________

## Deployment Overview

Mahavishnu supports **three deployment models**:

### Deployment Architecture Comparison

| Aspect | MCP Server | Embedded in Qwen | Hybrid |
|---------|-----------|------------------|--------|
| **Claude Code Integration** | ✅ Native via MCP | ❌ Not available | ✅ Best of both |
| **Qwen Integration** | ❌ Not available | ✅ Python library | ✅ Flexible |
| **Subscription Auth** | ✅ Required | ❌ Free tier | ✅ Configurable |
| **Resource Usage** | Separate process | Within Qwen | Both |
| **Performance** | Dedicated | Shared | Optimized |
| **Use Case** | Production workflows | Development/testing | Full-featured |

**Recommended:**

- **Production:** Option 1 (MCP Server)
- **Development:** Option 2 (Embedded in Qwen)
- **Full-Featured:** Option 3 (Hybrid)

______________________________________________________________________

## Option 1: Mahavishnu as MCP Server for Claude Code

### Architecture

```
┌─────────────────────────────────────────┐
│  Claude Code Desktop App                │
│  (with subscription)                     │
└──────────────┬──────────────────────────┘
               │ MCP Protocol (stdio)
               ↓
┌─────────────────────────────────────────┐
│  Mahavishnu MCP Server                  │
│  - Validates subscription tokens         │
│  - Orchestrates workflows               │
│  - Manages repositories                 │
│  - Runs quality control                 │
│  - Returns results via MCP              │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Your Git Repositories                  │
└─────────────────────────────────────────┘
```

### Setup Steps

#### Step 1: Configure Claude Code MCP Settings

**File:** `~/.claude/.mcp.json`

```json
{
  "mcpServers": {
    "mahavishnu": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/les/Projects/mahavishnu",
        "run",
        "mahavishnu",
        "mcp",
        "start"
      ],
      "env": {
        "MAHAVISHNU_SUBSCRIPTION_TOKEN": "your_claude_subscription_token_here",
        "MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET": "your_32char_secret_key_here"
      }
    }
  }
}
```

#### Step 2: Set Environment Variables

```bash
# Required for subscription auth
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_32char_secret_key_here_minimum"

# Optional: Claude Code subscription token
export MAHAVISHNU_SUBSCRIPTION_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# PostgreSQL configuration
export MAHAVISHNU_PG_HOST="localhost"
export MAHAVISHNU_PG_PORT="5432"
export MAHAVISHNU_PG_DATABASE="mahavishnu"
export MAHAVISHNU_PG_USER="postgres"
export MAHAVISHNU_PG_PASSWORD="your_password"

# Ollama configuration
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"
```

#### Step 3: Start Mahavishnu MCP Server

```bash
cd /Users/les/Projects/mahavishnu

# Start MCP server
mahavishnu mcp start

# Or run directly with uv
uv run mahavishnu mcp start
```

#### Step 4: Verify Connection in Claude Code

```python
# In Claude Code, Mahavishnu tools will be available:
# - mahavishnu_list_repos
# - mahavishnu_workflow_sweep
# - mahavishnu_get_health
# - etc.

# Test in Claude Code:
"""
Can you list all repositories tagged as 'backend' and trigger
a workflow sweep using the LangGraph adapter?
"""
```

### Benefits of MCP Server Deployment

✅ **Native Claude Code Integration**
✅ **Subscription-based access control**
✅ **Dedicated resources (no Qwen overhead)**
✅ **Production-ready**
✅ **Easy updates (restart MCP server)**

### Limitations

❌ **Cannot run inside Qwen sessions**
❌ **Requires separate process**
❌ **Higher resource usage**

______________________________________________________________________

## Option 2: Mahavishnu Embedded in Qwen Sessions

### Architecture

```
┌─────────────────────────────────────────┐
│  Qwen Session (Free, no auth)          │
│  - Runs Python code                     │
│  - Imports Mahavishnu as library        │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Mahavishnu (embedded in Qwen)         │
│  - Skips subscription checks            │
│  - Orchestrates workflows               │
│  - Direct API calls                    │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Your Git Repositories                  │
└─────────────────────────────────────────┘
```

### Setup Steps

#### Step 1: Ensure Mahavishnu is Installed

```bash
cd /Users/les/Projects/mahavishnu

# Install in development mode
uv pip install -e ".[dev]"

# Or install with specific dependencies
uv pip install -e ".[postgres]"
```

#### Step 2: Configure Qwen Environment (No Auth Required)

```bash
# Set up environment (no subscription auth needed for Qwen)
export MAHAVISHNU_QWEN_MODE="true"

# PostgreSQL configuration
export MAHAVISHNU_PG_HOST="localhost"
export MAHAVISHNU_PG_PORT="5432"
export MAHAVISHNU_PG_DATABASE="mahavishnu"

# Ollama configuration
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"
```

#### Step 3: Use Mahavishnu Inside Qwen

```python
# Inside Qwen session
from mahavishnu.core import MahavishnuApp
import asyncio


async def main():
    # Initialize Mahavishnu (no auth needed for Qwen)
    app = MahavishnuApp()

    # Get repositories
    repos = app.get_repos(tag="backend")

    # Execute workflow
    result = await app.execute_workflow(
        task={"type": "code_sweep"}, adapter_name="langgraph", repos=repos
    )

    print(f"Workflow completed: {result}")


# Run in Qwen
asyncio.run(main())
```

#### Step 4: Or Use CLI Commands

```bash
# Direct CLI usage (auth optional for Qwen)
mahavishnu list-repos --tag backend
mahavishnu workflow sweep --adapter langgraph
```

### Benefits of Embedded Deployment

✅ **No subscription required (Qwen is free)**
✅ **Runs inside Qwen sessions**
✅ **Lower resource usage**
✅ **Simpler setup**
✅ **Direct Python API access**

### Limitations

❌ **Cannot use in Claude Code**
❌ **No subscription-based access control**
❌ **Limited to Qwen environment**
❌ **No MCP tools**

______________________________________________________________________

## Option 3: Hybrid Deployment (Both Claude Code and Qwen)

### Architecture

```
┌──────────────────────┐        ┌──────────────────────┐
│  Claude Code           │        │  Qwen Session         │
│  (with subscription)    │        │  (free tier)           │
└──────────┬─────────────┘        └──────────┬─────────────┘
           │                                   │
           │ MCP Protocol                       │ Python import
           ↓                                   ↓
     ┌────────────────────────────────────────┐
     │  Mahavishnu (Hybrid Mode)              │
     │  - Detects client type                  │
     │  - Enforces auth for Claude Code        │
     │  - Skips auth for Qwen                 │
     │  - Shared memory + state                │
     └────────────────────────────────────────┘
                      │
                      ↓
     ┌────────────────────────────────────────┐
     │  Your Git Repositories                  │
     └────────────────────────────────────────┘
```

### Setup Steps

#### Step 1: Configure Hybrid Mode

**settings/mahavishnu.yaml:**

```yaml
server_name: "Mahavishnu Orchestrator"

# Enable both deployment modes
deployment_mode: "hybrid"

# Subscription auth (for Claude Code)
subscription_auth_enabled: true
subscription_auth_expire_minutes: 480

# Qwen mode (free tier)
qwen_mode_enabled: true
qwen_bypass_subscription: true

# Adapters
adapters:
  prefect: true
  llamaindex: true
  agno: true
```

#### Step 2: Implement Client Detection

**File to Create:** `mahavishnu/core/client_detector.py`

```python
"""Client detection for hybrid deployment."""

from enum import Enum
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class ClientType(str, Enum):
    """Type of client connecting to Mahavishnu."""

    CLAUDE_CODE = "claude_code"
    QWEN = "qwen"
    CLI = "cli"
    UNKNOWN = "unknown"


class ClientDetector:
    """Detect client type and apply appropriate auth rules."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.hybrid_mode = getattr(config, "deployment_mode", "mcp") == "hybrid"
        self.qwen_bypass = getattr(config, "qwen_bypass_subscription", False)

    def detect_client(self, request_headers: dict) -> ClientType:
        """Detect client type from request.

        Args:
            request_headers: HTTP headers from request

        Returns:
            Detected client type
        """
        # Check for Qwen user agent
        user_agent = request_headers.get("user-agent", "")
        if "qwen" in user_agent.lower():
            logger.debug("Detected Qwen client")
            return ClientType.QWEN

        # Check for Claude Code subscription token
        auth_header = request_headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove 'Bearer '

            # Decode token to check subscription type
            try:
                import jwt

                payload = jwt.decode(token, options={"verify_signature": False})

                if "subscription_type" in payload:
                    if payload["subscription_type"] == "claude_code":
                        logger.debug("Detected Claude Code client")
                        return ClientType.CLAUDE_CODE
                    elif payload["subscription_type"] == "codex":
                        logger.debug("Detected Codex client")
                        return ClientType.CLAUDE_CODE

            except Exception as e:
                logger.warning("Failed to decode subscription token", error=str(e))

        # Default: unknown client
        logger.debug("Unknown client type detected")
        return ClientType.UNKNOWN

    def should_require_auth(self, client_type: ClientType) -> bool:
        """Determine if auth should be required for this client.

        Args:
            client_type: Detected client type

        Returns:
            True if auth required, False otherwise
        """
        # Qwen bypasses subscription auth in hybrid mode
        if client_type == ClientType.QWEN and self.hybrid_mode and self.qwen_bypass:
            logger.info("Qwen client bypassing subscription auth (hybrid mode)")
            return False

        # Claude Code requires subscription auth
        if client_type == ClientType.CLAUDE_CODE:
            return True

        # CLI doesn't require auth (optional)
        if client_type == ClientType.CLI:
            return getattr(self.config, "cli_auth_enabled", False)

        # Unknown clients require auth if subscription auth is enabled
        return getattr(self.config, "subscription_auth_enabled", False)

    def get_client_info(self, client_type: ClientType) -> dict:
        """Get client information for logging/metrics.

        Args:
            client_type: Detected client type

        Returns:
            Client information dict
        """
        return {
            "client_type": client_type.value,
            "subscription_required": self.should_require_auth(client_type),
            "deployment_mode": "hybrid" if self.hybrid_mode else "single",
        }
```

#### Step 3: Integrate Client Detector into App

**File to Modify:** `mahavishnu/core/app.py`

```python
"""Add client detection to MahavishnuApp."""

from .client_detector import ClientDetector, ClientType


class MahavishnuApp:
    """Main application with hybrid client support."""

    def __init__(self, config: Any | None = None) -> None:
        # ... existing init ...

        # Initialize client detector
        self.client_detector = ClientDetector(config) if config else None

    async def execute_workflow_hybrid(
        self, task: dict, adapter_name: str, repos: list, request_headers: dict | None = None
    ) -> dict:
        """Execute workflow with client-aware auth (HYBRID MODE).

        Args:
            task: Workflow task definition
            adapter_name: Adapter to use
            repos: Repositories to process
            request_headers: HTTP headers for client detection

        Returns:
            Workflow execution results
        """
        # Detect client type
        client_type = ClientType.UNKNOWN
        if self.client_detector and request_headers:
            client_type = self.client_detector.detect_client(request_headers)

        # Check if auth required
        if self.client_detector and self.client_detector.should_require_auth(client_type):
            # Verify subscription token
            auth_header = request_headers.get("authorization", "")
            if not auth_header:
                raise AuthenticationError(
                    "Authentication required for this client",
                    client_type=client_type.value,
                    suggestion="Provide valid subscription token",
                )

            # Verify auth
            from .subscription_auth import MultiAuthHandler

            auth_handler = MultiAuthHandler(self.config)
            auth_result = auth_handler.authenticate_request(auth_header)

            logger.info(
                "Client authenticated",
                client_type=auth_result.get("method"),
                user=auth_result.get("user"),
            )
        else:
            logger.info(
                "Skipping auth check",
                client_type=client_type.value,
                reason="Qwen free tier or auth not required",
            )

        # Execute workflow (same logic for all clients)
        return await self._execute_workflow_internal(task, adapter_name, repos)
```

#### Step 4: Start Hybrid Server

```bash
# Start hybrid MCP server
export MAHAVISHNU_DEPLOYMENT_MODE=hybrid
mahavishnu mcp start
```

### Benefits of Hybrid Deployment

✅ **Best of both worlds**
✅ **Claude Code integration (with subscription)**
✅ **Qwen integration (free tier)**
✅ **Single codebase**
✅ **Flexible access control**
✅ **Shared state and memory**

### Limitations

⚠️ **More complex setup**
⚠️ **Requires client detection logic**
⚠️ **Potential auth bypass risks**

______________________________________________________________________

## Subscription Authentication Setup

### Overview

Mahavishnu uses **subscription-based JWT tokens** for Claude Code and Codex authentication.

### Token Creation Flow

```
┌─────────────────────────────────────────┐
│  Claude Code / Codex Platform           │
│  - User has valid subscription          │
│  - Generates subscription token          │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Token Creation                         │
│  1. User ID: "claude_user_123"          │
│  2. Subscription: "claude_code"         │
│  3. Scopes: ["read", "execute", etc.]    │
│  4. Expiration: 480 minutes              │
│  5. Secret: MAHAVISHNU_SUBSCRIPTION_...  │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  JWT Token Generated                    │
│  eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  │
│  {                                     │
│    "sub": "claude_user_123",            │
│    "user_id": "claude_user_123",        │
│    "subscription_type": "claude_code",  │
│    "scopes": ["read", "execute"],       │
│    "exp": 1706140800                    │
│  }                                     │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Mahavishnu Validates Token              │
│  1. Receives token in Authorization     │
│  2. Verifies signature                  │
│  3. Checks subscription_type             │
│  4. Validates expiration                │
│  5. Checks scopes                      │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  Access Granted or Denied                │
└─────────────────────────────────────────┘
```

### Creating Subscription Tokens

#### Method 1: Using Python API

```python
from mahavishnu.core.subscription_auth import MultiAuthHandler
from mahavishnu.core.config import MahavishnuSettings
import os

# Configure
os.environ["MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"] = "your_32char_secret_key_here_minimum"

config = MahavishnuSettings(
    subscription_auth_enabled=True,
    subscription_auth_secret=os.environ.get("MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET"),
)

# Create auth handler
auth_handler = MultiAuthHandler(config)

# Create Claude Code subscription token
claude_token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123", scopes=["read", "execute", "workflow_manage"]
)

print(f"Claude Code token: {claude_token}")

# Create Codex subscription token
codex_token = auth_handler.create_codex_subscription_token(
    user_id="codex_user_456", scopes=["read", "execute"]
)

print(f"Codex token: {codex_token}")
```

#### Method 2: Using CLI

```bash
# Generate Claude Code token
mahavishnu auth create-token \
    --user-id claude_user_123 \
    --subscription claude_code \
    --scopes read,execute,workflow_manage

# Generate Codex token
mahavishnu auth create-token \
    --user-id codex_user_456 \
    --subscription codex \
    --scopes read,execute
```

### Validating Subscription Tokens

#### In Mahavishnu MCP Server

```python
from mahavishnu.core.subscription_auth import MultiAuthHandler


# In MCP tool implementation
@app.mcp_tool()
async def mahavishnu_workflow_sweep(
    adapter: str,
    repos: list[str],
    auth_header: str,  # Passed from Claude Code
) -> dict:
    """Execute workflow sweep with subscription auth."""

    # Validate subscription token
    auth_handler = MultiAuthHandler(app.config)

    try:
        auth_result = auth_handler.authenticate_request(auth_header)

        # Check scopes
        if "workflow_manage" not in auth_result.get("scopes", []):
            raise Exception("Insufficient permissions: workflow_manage scope required")

        # Check subscription type
        if auth_result["subscription_type"] not in ["claude_code", "codex"]:
            raise Exception(f"Invalid subscription type: {auth_result['subscription_type']}")

        # Proceed with workflow
        result = await app.execute_workflow(
            task={"type": "sweep"}, adapter_name=adapter, repos=repos
        )

        return result

    except Exception as e:
        return {"error": str(e), "authenticated": False}
```

### Token Structure

**Decoded Token Example:**

```json
{
  "sub": "claude_user_123",
  "user_id": "claude_user_123",
  "subscription_type": "claude_code",
  "scopes": ["read", "execute", "workflow_manage"],
  "exp": 1706140800,
  "iat": 1706120000
}
```

**Field Descriptions:**

- `sub`: JWT standard subject claim (user identifier)
- `user_id`: Mahavishnu-specific user ID
- `subscription_type`: Type of subscription ("claude_code" or "codex")
- `scopes`: List of granted permissions
- `exp`: Expiration timestamp (Unix timestamp)
- `iat`: Issued at timestamp (Unix timestamp)

### Available Scopes

| Scope | Description | Claude Code | Codex | Qwen |
|-------|-------------|-------------|-------|------|
| `read` | Read repositories and configurations | ✅ | ✅ | ✅ |
| `execute` | Execute workflows | ✅ | ✅ | ✅ |
| `workflow_manage` | Create/modify workflows | ✅ | ❌ | ✅ |
| `admin` | Full administrative access | ✅ | ❌ | ❌ |

______________________________________________________________________

## Configuration Examples

### Example 1: Claude Code Production Deployment

**settings/mahavishnu.yaml:**

```yaml
server_name: "Mahavishnu Production"
deployment_mode: "mcp"

# Subscription authentication (REQUIRED)
subscription_auth_enabled: true
subscription_auth_expire_minutes: 480  # 8 hours

# PostgreSQL
postgresql:
  enabled: true
  host: "postgres.production.internal"
  port: 5432
  database: "mahavishnu_prod"
  pool_size: 50  # Higher for production
  max_overflow: 50

# Ollama
llm_model: "nomic-embed-text"
ollama_base_url: "http://ollama.internal:11434"

# Adapters
adapters:
  prefect: true
  llamaindex: true
  agno: true

# Quality control
qc_enabled: true
qc_min_score: 85  # Higher threshold for production

# Observability
metrics_enabled: true
tracing_enabled: true
otlp_endpoint: "http://jaeger:4317"
```

**Environment Variables:**

```bash
# Required
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="${MAHAVISHNU_SECRET}"
export MAHAVISHNU_PG_PASSWORD="${POSTGRES_PASSWORD}"

# Optional
export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317"
export MAHAVISHNU_LOG_LEVEL="INFO"
```

### Example 2: Qwen Development Deployment

**settings/local.yaml:**

```yaml
server_name: "Mahavishnu Dev (Qwen Mode)"
deployment_mode: "embedded"

# Qwen mode (free tier, no auth)
qwen_mode_enabled: true
qwen_bypass_subscription: true

# PostgreSQL (local)
postgresql:
  enabled: true
  host: "localhost"
  port: 5432
  database: "mahavishnu_dev"
  pool_size: 10  # Lower for dev
  max_overflow: 20

# Ollama (local)
llm_model: "nomic-embed-text"
ollama_base_url: "http://localhost:11434"

# Adapters
adapters:
  prefect: false  # Disable for dev
  llamaindex: true
  agno: true

# Quality control (relaxed)
qc_enabled: true
qc_min_score: 70  # Lower threshold for dev

# Observability (console only)
metrics_enabled: false
tracing_enabled: false
```

**Usage in Qwen:**

```python
# Inside Qwen session
from mahavishnu.core import MahavishnuApp
import os

# Set Qwen mode
os.environ["MAHAVISHNU_QWEN_MODE"] = "true"

# Initialize (no auth needed)
app = MahavishnuApp()

# Use it
repos = app.get_repos(tag="backend")
result = await app.execute_workflow(
    task={"type": "code_sweep"}, adapter_name="langgraph", repos=repos
)
```

### Example 3: Hybrid Deployment

**settings/mahavishnu.yaml:**

```yaml
server_name: "Mahavishnu Hybrid"
deployment_mode: "hybrid"

# Enable both modes
subscription_auth_enabled: true
qwen_mode_enabled: true
qwen_bypass_subscription: true

# PostgreSQL
postgresql:
  enabled: true
  host: "localhost"
  port: 5432
  database: "mahavishnu"
  pool_size: 30
  max_overflow: 40

# Ollama
llm_model: "nomic-embed-text"
ollama_base_url: "http://localhost:11434"

# Adapters
adapters:
  prefect: true
  llamaindex: true
  agno: true
```

______________________________________________________________________

## Troubleshooting

### Issue 1: "Subscription authentication failed"

**Symptoms:**

- Claude Code can't connect to Mahavishnu MCP server
- Error: "Authentication required"

**Solutions:**

1. Check MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET is set
1. Verify subscription token is valid
1. Check token expiration
1. Ensure subscription_auth_enabled=true

```bash
# Debug auth
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="test_secret_32chars_minimum"
mahavishnu mcp health

# Verify token
python -c "
from mahavishnu.core.subscription_auth import MultiAuthHandler
import os

config = MahavishnuSettings(
    subscription_auth_enabled=True,
    subscription_auth_secret=os.environ['MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET']
)

auth = MultiAuthHandler(config)
token = auth.create_claude_subscription_token('test_user')
print(f'Token: {token}')

result = auth.authenticate_request(f'Bearer {token}')
print(f'Result: {result}')
"
```

### Issue 2: "Qwen can't import mahavishnu"

**Symptoms:**

- ImportError when importing in Qwen
- Module not found errors

**Solutions:**

1. Install Mahavishnu in development mode
1. Ensure Python version is 3.10+
1. Check virtual environment

```bash
# In Qwen session or terminal
cd /Users/les/Projects/mahavishnu

# Install
uv pip install -e ".[dev]"

# Or install specific dependencies
uv pip install -e ".[postgres]"

# Verify installation
python -c "from mahavishnu.core import MahavishnuApp; print('OK')"
```

### Issue 3: "MCP server not starting"

**Symptoms:**

- mahavishnu mcp start fails
- Connection errors in Claude Code

**Solutions:**

1. Check port conflicts
1. Verify dependencies installed
1. Check logs for specific errors

```bash
# Check dependencies
uv pip list | grep mahavishnu

# Try starting with verbose output
mahavishnu mcp start --verbose

# Check MCP server status
mahavishnu mcp status

# Test connection
mahavishnu mcp health
```

### Issue 4: "Database connection errors"

**Symptoms:**

- Can't connect to PostgreSQL
- Connection pool exhausted

**Solutions:**

1. Verify PostgreSQL is running
1. Check connection pool settings
1. Test database connection

```bash
# Test PostgreSQL connection
psql -h localhost -U postgres -d mahavishnu

# Check connection pool settings
grep -A5 "postgresql:" settings/mahavishnu.yaml

# Test connection from Python
python -c "
import asyncpg
async def test():
    conn = await asyncpg.connect('postgresql://postgres:password@localhost/mahavishnu')
    result = await conn.fetchval('SELECT 1')
    await conn.close()
    print(f'DB OK: {result}')

import asyncio
asyncio.run(test())
"
```

### Issue 5: "Ollama embeddings not working"

**Symptoms:**

- Embedding generation fails
- "model not found" errors

**Solutions:**

1. Ensure Ollama is running
1. Pull the embedding model
1. Check base URL

```bash
# Start Ollama
ollama serve

# Pull embedding model
ollama pull nomic-embed-text

# Test embedding generation
curl http://localhost:11434/api/embeddings -d '{
  "model": "nomic-embed-text",
  "prompt": "test"
}'

# Test from Python
python -c "
from llama_index.embeddings.ollama import OllamaEmbedding
import asyncio

async def test():
    embed_model = OllamaEmbedding(
        model_name='nomic-embed-text',
        base_url='http://localhost:11434'
    )
    embedding = await embed_model.aget_text_embedding('test')
    print(f'Embedding dimension: {len(embedding)}')

asyncio.run(test())
"
```

______________________________________________________________________

## Quick Start Guides

### Quick Start: Claude Code (5 Minutes)

```bash
# 1. Set up environment
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_32char_secret_key_here"
export MAHAVISHNU_PG_PASSWORD="your_password"

# 2. Configure Claude Code
cat > ~/.claude/.mcp.json << 'EOF'
{
  "mcpServers": {
    "mahavishnu": {
      "command": "uv",
      "args": ["--directory", "/Users/les/Projects/mahavishnu", "run", "mahavishnu", "mcp", "start"],
      "env": {
        "MAHAVISHNU_SUBSCRIPTION_TOKEN": "your_token_here"
      }
    }
  }
}
EOF

# 3. Restart Claude Code
# (Use Claude Code menu: Developer > Reload Window)

# 4. Test in Claude Code
"""
Can you list all repositories and trigger a workflow sweep?
"""

# 5. Verify
mahavishnu mcp health
```

### Quick Start: Qwen (3 Minutes)

```bash
# 1. In Qwen session
pip install -e "/Users/les/Projects/mahavishnu[dev]"

# 2. Use Mahavishnu
python << 'EOF'
from mahavishnu.core import MahavishnuApp
import asyncio

async def main():
    app = MahavishnuApp()
    repos = app.get_repos(tag="backend")
    print(f"Found {len(repos)} repositories")
    for repo in repos:
        print(f"  - {repo.name}")

asyncio.run(main())
EOF

# 3. Done!
```

______________________________________________________________________

## Summary

### Deployment Choice Guide

| Use Case | Recommended Option |
|---------|-------------------|
| **Production with Claude Code** | Option 1: MCP Server |
| **Development with Qwen** | Option 2: Embedded |
| **Both Claude Code and Qwen** | Option 3: Hybrid |
| **Testing locally** | Option 2: Embedded |
| **Multi-user team** | Option 1: MCP Server |

### Key Takeaways

1. **Claude Code**: Requires subscription token, uses MCP protocol
1. **Qwen**: Free tier, no subscription required, Python library
1. **Hybrid**: Best of both, requires client detection
1. **Authentication**: JWT-based with subscription metadata
1. **Configuration**: Single codebase, deployment-specific settings

______________________________________________________________________

**Document Version:** 1.0
**Date:** 2025-01-24
**Next:** Configure and deploy based on your use case
