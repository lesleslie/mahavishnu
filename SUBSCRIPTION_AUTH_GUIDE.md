# Mahavishnu Subscription Authentication Guide

**Version:** 1.0
**Date:** 2025-01-24
**Purpose:** Complete guide to subscription-based authentication for Claude Code, Codex, and Qwen

---

## Table of Contents

1. [Authentication Overview](#authentication-overview)
2. [Subscription Token Structure](#subscription-token-structure)
3. [Token Creation](#token-creation)
4. [Token Validation](#token-validation)
5. [Integration Guide](#integration-guide)
6. [Security Best Practices](#security-best-practices)
7. [Troubleshooting](#troubleshooting)

---

## Authentication Overview

### Supported Authentication Methods

Mahavishnu supports **three authentication methods**:

| Method | Description | Use Case | Subscription Required |
|--------|-------------|----------|---------------------|
| **JWT** | Traditional JWT auth | Legacy systems | No |
| **Subscription Token** | JWT with subscription metadata | Claude Code, Codex | Yes |
| **Qwen Free** | No authentication required | Qwen sessions | No (free tier) |

### Authentication Flow

```
┌─────────────────┐
│  Client          │
│  (Claude Code,   │
│   Codex, Qwen)   │
└────────┬────────┘
         │
         │ 1. Request with Authorization header
         ↓
┌─────────────────────────────────────────────────┐
│  Mahavishnu MultiAuthHandler                    │
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │ Detect token type                         │  │
│  │ (subscription vs standard JWT)           │  │
│  └──────────────┬──────────────────────────┘  │
│                 │                              │
│  ┌──────────────▼──────────────────────────┐  │
│  │ Is subscription token?                   │  │
│  │ ┌─────────────┬────────────────────┐     │  │
│  │ │ Yes          │ No                  │     │  │
│  │ └──┬──────────┘ └────────────────────┘     │  │
│  │     │                                  │  │
│  │  ▼                                  │  │
│  │ ┌────────────────────────────────────┐ │  │
│  │ │ Verify with subscription secret      │ │  │
│  │ │ Check subscription_type               │ │  │
│  │ │ Check expiration                      │ │  │
│  │ │ Check scopes                          │  │  │
│  │ └────────────────────────────────────┘ │  │
│  │                                         │  │
│  │ ▼                                       │  │
│  │ ┌────────────────────────────────────┐ │  │
│  │ │ Verify with JWT secret                 │ │  │
│  │ │ Check expiration                      │  │  │
│  │ └────────────────────────────────────┘ │  │
│  │                                         │  │
│  │ ▼                                       │  │
│  │ ┌────────────────────────────────────┐ │  │
│  │ │ Return authentication result           │ │  │
│  │ │ - user                               │ │  │
│  │ │ - method (jwt, claude_subscription,   │ │  │
│  │ │         codex_subscription, qwen_free)│  │  │
│  │ │ - subscription_type                   │ │  │
│  │ │ - scopes                             │  │  │
│  │ │ - authenticated                      │ │  │  │
│  │ └────────────────────────────────────┘ │  │
│  │                                         │  │
│  └─────────────────────────────────────────┘  │
│                                               │
│  ┌──────────────┬──────────────────────────┐  │
│  │ Qwen client? │ Other client?            │  │
│  │ ┌────────┐   │ ┌────────────────┐       │  │
│  │ │Bypass  │   │ │ Check auth       │       │  │
│  │ │auth    │   │ │if enabled       │       │  │
│  │ └───────┘   │ └────────────────┘       │  │
│  │              │                          │  │
│  │   ▼          │    ▼                     │  │
│  │ ┌──────────────────────┐  ┌──────┐  │  │
│  │ │ Allow access         │  │Deny │  │  │
│  │ │ (Qwen is free)      │  │     │  │  │
│  │ └──────────────────────┘  └──────┘  │  │
│  │                                         │  │
│  └─────────────────────────────────────────┘  │
│                                               │
└───────────────────────────────────────────┘
```

---

## Subscription Token Structure

### Token Components

**Encoded JWT Token:**

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjbGF1ZGVfdXNlcl8xMjMiLCJ1c2VyX2lkIjoic3Vic2NyaXB0aW9uX3R5cGUiOiJjbGF1ZGVfY29kZSIsInNjb3BlcyI6WyJyZWFkIiwiZXhlY3V0ZSIsIndvcmtmbG93X21hbmFnZSJdLCJleHAiOjE3MDYxNDA4MDAsImlhdCI6MTcwNjEyMDAwMH0.some_signature
```

**Decoded Payload:**

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

### Token Fields Explained

| Field | Type | Description | Example |
|-------|------|-------------|--------|
| `sub` | string | JWT standard: Subject identifier | "claude_user_123" |
| `user_id` | string | Mahavishnu-specific user ID | "claude_user_123" |
| `subscription_type` | string | Type of subscription | "claude_code", "codex" |
| `scopes` | string[] | Granted permissions | ["read", "execute"] |
| `exp` | integer | Expiration timestamp (Unix epoch) | 1706140800 |
| `iat` | integer | Issued-at timestamp (Unix epoch) | 1706120000 |

### Subscription Types

| Subscription Type | Value | Description | Access Level |
|------------------|-------|-------------|-------------|
| **Claude Code** | `claude_code` | Claude Code subscription | Full access to MCP tools |
| **Codex** | `codex` | Codex subscription | Limited access (no workflow_manage) |
| **Qwen Free** | N/A | Qwen (no token needed) | Free tier, no auth required |

### Available Scopes

| Scope | Permission | Claude Code | Codex | Qwen |
|-------|-----------|-------------|-------|------|
| `read` | Read repositories and configurations | ✅ | ✅ | ✅ |
| `execute` | Execute workflows | ✅ | ✅ | ✅ |
| `workflow_manage` | Create/modify/delete workflows | ✅ | ❌ | ✅ |
| `admin` | Full administrative access | ✅ | ❌ | ❌ |

---

## Token Creation

### Method 1: Python API

**File:** `create_subscription_token.py`

```python
"""Create subscription tokens for Mahavishnu."""
import os
from mahavishnu.core.subscription_auth import MultiAuthHandler
from mahavishnu.core.config import MahavishnuSettings

# Configure
os.environ['MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET'] = 'your_32char_secret_key_here_minimum'

config = MahavishnuSettings(
    subscription_auth_enabled=True,
    subscription_auth_secret=os.environ.get('MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET'),
    subscription_auth_expire_minutes=480  # 8 hours
)

# Initialize auth handler
auth_handler = MultiAuthHandler(config)

# Example 1: Create Claude Code subscription token
claude_token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123",
    scopes=["read", "execute", "workflow_manage"]
)

print("=" * 80)
print("CLAUDE CODE SUBSCRIPTION TOKEN")
print("=" * 80)
print(f"Token: {claude_token}")
print(f"User ID: claude_user_123")
print(f"Subscription Type: claude_code")
print(f"Scopes: read, execute, workflow_manage")
print(f"Expires: 8 hours from creation")
print()

# Example 2: Create Codex subscription token
codex_token = auth_handler.create_codex_subscription_token(
    user_id="codex_user_456",
    scopes=["read", "execute"]  # No workflow_manage for Codex
)

print("=" * 80)
print("CODEX SUBSCRIPTION TOKEN")
print("=" * 80)
print(f"Token: {codex_token}")
print(f"User ID: codex_user_456")
print(f"Subscription Type: codex")
print(f"Scopes: read, execute")
print(f"Expires: 8 hours from creation")
print()

# Example 3: Create custom subscription token
custom_token = auth_handler.subscription_auth.create_subscription_token(
    user_id="custom_user_789",
    subscription_type="custom_subscription",
    scopes=["read", "execute", "workflow_manage", "admin"]
)

print("=" * 80)
print("CUSTOM SUBSCRIPTION TOKEN")
print("=" * 80)
print(f"Token: {custom_token}")
print(f"User ID: custom_user_789")
print(f"Subscription Type: custom_subscription")
print(f"Scopes: read, execute, workflow_manage, admin")
print(f"Expires: 8 hours from creation")
```

### Method 2: CLI Commands

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

# Generate token with custom expiration
mahavishnu auth create-token \
    --user-id claude_user_123 \
    --subscription claude_code \
    --scopes read,execute \
    --expire-minutes 1440  # 24 hours
```

### Method 3: HTTP API (Future Enhancement)

**Endpoint:** `POST /api/v1/auth/token`

```bash
curl -X POST http://localhost:3035/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer admin_token" \
  -d '{
    "user_id": "claude_user_123",
    "subscription_type": "claude_code",
    "scopes": ["read", "execute", "workflow_manage"],
    "expire_minutes": 480
  }'
```

---

## Token Validation

### Validation Process

**Step 1: Receive Authorization Header**

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Step 2: Extract and Decode Token**

```python
# Extract token from header
auth_header = request.headers.get("Authorization")
if not auth_header or not auth_header.startswith("Bearer "):
    raise AuthenticationError("Missing or invalid Authorization header")

token = auth_header[len("Bearer "):]

# Decode token (without verification first)
import jwt
try:
    payload = jwt.decode(token, options={"verify_signature": False})
except jwt.exceptions.DecodeError:
    raise AuthenticationError("Invalid token format")
```

**Step 3: Determine Token Type**

```python
# Check if it's a subscription token
is_subscription_token = "subscription_type" in payload

if is_subscription_token:
    # Route to subscription auth
    auth_result = subscription_auth.verify_subscription_token(token)
else:
    # Route to JWT auth
    auth_result = jwt_auth.verify_token(token)
```

**Step 4: Verify Subscription Token**

```python
async def verify_subscription_token(self, token: str) -> SubscriptionTokenData:
    """Verify subscription token (CORRECTED)."""
    try:
        payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])

        # Extract required fields
        user_id = payload.get("user_id")
        subscription_type = payload.get("subscription_type")

        # Validate required fields
        if not user_id or not subscription_type:
            raise AuthenticationError(
                "Invalid subscription token: missing required fields",
                details={"error": "user_id or subscription_type not found"}
            )

        # Create token data
        token_data = SubscriptionTokenData(
            user_id=user_id,
            subscription_type=subscription_type,
            exp=payload.get("exp"),
            scopes=payload.get("scopes", [])
        )

        # Check expiration
        if datetime.utcnow().timestamp() > token_data.exp:
            raise AuthenticationError(
                "Subscription token has expired",
                details={"error": "Expired token", "exp": token_data.exp}
            )

        return token_data

    except jwt.exceptions.InvalidSignatureError:
        raise AuthenticationError(
            "Invalid subscription token signature",
            details={"error": "Invalid signature"}
        )
    except jwt.exceptions.DecodeError:
        raise AuthenticationError(
            "Could not decode subscription token",
            details={"error": "Decode error"}
        )
    except Exception as e:
        raise AuthenticationError(
            f"Subscription authentication error: {str(e)}",
            details={"error": str(e)}
        )
```

**Step 5: Check Scopes**

```python
# After authentication
required_scope = "workflow_manage"

if required_scope not in auth_result.get("scopes", []):
    raise AuthorizationError(
        f"Insufficient permissions: {required_scope} scope required",
        details={
            "required_scope": required_scope,
            "available_scopes": auth_result.get("scopes", [])
        }
    )
```

---

## Integration Guide

### Integration in Mahavishnu MCP Server

**File:** `mahavishnu/mcp/tools/workflow_tools.py`

```python
"""MCP tools with subscription authentication (CORRECTED)."""
from fastmcp import FastMCP
from mahavishnu.core.subscription_auth import MultiAuthHandler
import structlog

logger = structlog.get_logger(__name__)

def register_workflow_tools(mcp: FastMCP, app) -> None:
    """Register workflow tools with subscription auth."""

    @mcp.tool()
    async def mahavishnu_list_repos(
        tag: str | None = None,
        auth_header: str | None = None
    ) -> list[dict]:
        """List repositories with subscription authentication.

        Args:
            tag: Optional tag filter
            auth_header: Authorization header from Claude Code

        Returns:
            List of repository information

        Raises:
            AuthenticationError: If auth fails
        """
        # Validate subscription token
        if not app.config.subscription_auth_enabled:
            # Auth disabled, allow access
            logger.warning("Subscription auth disabled, allowing access")
        elif not auth_header:
            raise AuthenticationError(
                "Authentication required: Missing Authorization header",
                details={"suggestion": "Provide valid subscription token"}
            )
        else:
            # Verify subscription token
            auth_handler = MultiAuthHandler(app.config)
            auth_result = auth_handler.authenticate_request(auth_header)

            # Check scopes
            if "read" not in auth_result.get("scopes", []):
                raise AuthorizationError(
                    "Insufficient permissions: 'read' scope required",
                    details={"available_scopes": auth_result.get("scopes", [])}
                )

            logger.info(
                "Client authenticated",
                method=auth_result.get("method"),
                user=auth_result.get("user"),
                subscription_type=auth_result.get("subscription_type")
            )

        # Proceed with repository listing
        repos = app.get_repos(tag=tag)

        return [
            {
                "id": repo.id,
                "name": repo.name,
                "path": repo.path,
                "tags": repo.tags
            }
            for repo in repos
        ]

    @mcp.tool()
    async def mahavishnu_workflow_sweep(
        adapter: str,
        repos: list[str],
        task: dict,
        auth_header: str | None = None
    ) -> dict:
        """Execute workflow sweep with subscription authentication.

        Args:
            adapter: Adapter to use (langgraph, airflow, crewai, agno)
            repos: List of repository paths or IDs
            task: Task definition
            auth_header: Authorization header from Claude Code

        Returns:
            Workflow execution results

        Raises:
            AuthenticationError: If auth fails
            AuthorizationError: If insufficient permissions
        """
        # Validate subscription token (same as above)
        if app.config.subscription_auth_enabled and auth_header:
            auth_handler = MultiAuthHandler(app.config)
            auth_result = auth_handler.authenticate_request(auth_header)

            # Check scopes
            required_scopes = ["execute", "workflow_manage"]

            for scope in required_scopes:
                if scope not in auth_result.get("scopes", []):
                    raise AuthorizationError(
                        f"Insufficient permissions: '{scope}' scope required",
                        details={
                            "required_scopes": required_scopes,
                            "available_scopes": auth_result.get("scopes", [])
                        }
                    )

            logger.info(
                "Workflow sweep authorized",
                method=auth_result.get("method"),
                user=auth_result.get("user")
            )

        # Proceed with workflow execution
        result = await app.execute_workflow(
            task=task,
            adapter_name=adapter,
            repos=repos
        )

        return result
```

### Integration in Qwen Sessions

**File:** `qwen_integration_example.py`

```python
"""Mahavishnu integration in Qwen sessions (NO AUTH REQUIRED)."""
from mahavishnu.core import MahavishnuApp
import asyncio
import os

async def main():
    """Use Mahavishnu in Qwen (free tier, no auth)."""

    # Set Qwen mode (bypasses subscription checks)
    os.environ['MAHAVISHNU_QWEN_MODE'] = 'true'

    # Initialize Mahavishnu (no auth needed)
    app = MahavishnuApp()

    # Get repositories
    repos = app.get_repos(tag="backend")

    print(f"Found {len(repos)} repositories")

    # Execute workflow
    result = await app.execute_workflow(
        task={
            "type": "code_sweep",
            "description": "Analyze code quality across backend repos"
        },
        adapter_name="langgraph",
        repos=[repo.path for repo in repos]
    )

    print(f"Workflow completed: {result}")

    # Clean up
    await app.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Security Best Practices

### 1. Secret Management

**DO:** Store secrets in environment variables
```bash
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_32char_secret_key_minimum"
```

**DON'T:** Hardcode secrets in code
```python
# DON'T DO THIS
SECRET = "my_secret"  # ❌ Vulnerable to git commits
```

**DO:** Use .env files (gitignored)
```bash
# .env
MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_32char_secret_key_minimum"
MAHAVISHNU_PG_PASSWORD="your_password"
```

### 2. Token Expiration

**Recommended Settings:**

| Environment | Token Lifetime | Reason |
|------------|---------------|--------|
| **Development** | 60-120 minutes | Short-lived for security |
| **Staging** | 240-480 minutes (4-8 hours) | Balance security/convenience |
| **Production** | 480-1440 minutes (8-24 hours) | Longer for convenience |

**Configuration:**

```yaml
# settings/mahavishnu.yaml (development)
subscription_auth_expire_minutes: 60

# settings/mahavishnu.yaml (production)
subscription_auth_expire_minutes: 480
```

### 3. Scope-Based Access Control

**DO:** Use minimal required scopes

```python
# Good: Minimal scopes for read-only operation
read_only_token = auth_handler.create_claude_subscription_token(
    user_id="reader_user",
    scopes=["read"]  # Only read permission
)

# Good: Specific scopes for workflow management
workflow_token = auth_handler.create_claude_subscription_token(
    user_id="workflow_manager",
    scopes=["read", "execute", "workflow_manage"]  # All needed scopes
)
```

**DON'T:** Grant unnecessary scopes

```python
# DON'T DO THIS: Over-privileged token
admin_token = auth_handler.create_claude_subscription_token(
    user_id="regular_user",
    scopes=["read", "execute", "workflow_manage", "admin"]  # ❌ Admin not needed!
)
```

### 4. Token Rotation

**Implement token rotation:**

```python
async def rotate_token(user_id: str, old_token: str) -> str:
    """Rotate subscription token while preserving session."""

    # Validate old token
    try:
        old_data = auth_handler.authenticate_request(f"Bearer {old_token}")
    except AuthenticationError:
        raise ValueError("Old token is invalid")

    # Create new token
    new_token = auth_handler.create_claude_subscription_token(
        user_id=user_id,
        scopes=old_data.get("scopes", ["read", "execute"])
    )

    logger.info(
        "Token rotated",
        user_id=user_id,
        old_token_exp=old_data.get("exp"),
        new_token_exp=get_token_exp(new_token)
    )

    return new_token
```

### 5. Token Revocation

**Implement token revocation list:**

```python
class TokenRevocationList:
    """Track revoked tokens."""

    def __init__(self):
        self.revoked: set[str] = set()
        self.revoked_until: Dict[str, datetime] = {}

    def revoke_token(self, token: str, revoke_until: datetime) -> None:
        """Revoke a token until specified time."""
        self.revoked.add(token)
        self.revoked_until[token] = revoke_until

    def is_revoked(self, token: str) -> bool:
        """Check if token is revoked."""
        if token not in self.revoked:
            return False

        # Check if revocation period has expired
        revoke_until = self.revoked_until.get(token)
        if revoke_until and datetime.utcnow() > revoke_until:
            # Remove from revoked list (cleanup)
            del self.revoked[token]
            del self.revoked_until[token]
            return False

        return True
```

### 6. Audit Logging

**Log all authentication events:**

```python
async def authenticate_and_log(
    auth_handler: MultiAuthHandler,
    token: str,
    request_metadata: dict
) -> dict:
    """Authenticate with comprehensive audit logging."""

    # Perform authentication
    auth_result = auth_handler.authenticate_request(f"Bearer {token}")

    # Log authentication event
    logger.info(
        "Authentication successful",
        user=auth_result.get("user"),
        method=auth_result.get("method"),
        subscription_type=auth_result.get("subscription_type"),
        scopes=auth_result.get("scopes"),
        client_ip=request_metadata.get("client_ip"),
        user_agent=request_metadata.get("user_agent"),
        timestamp=datetime.utcnow().isoformat()
    )

    # Store authentication event in database
    await store_auth_event(
        user_id=auth_result.get("user"),
        auth_method=auth_result.get("method"),
        subscription_type=auth_result.get("subscription_type"),
        scopes=auth_result.get("scopes"),
        client_ip=request_metadata.get("client_ip"),
        success=True
    )

    return auth_result
```

---

## Troubleshooting

### Issue: "Subscription token has expired"

**Symptoms:**
```
AuthenticationError: Subscription token has expired
Details: Expired token
```

**Solutions:**

1. **Check token expiration:**
```python
import jwt
from datetime import datetime

token = "your_token_here"
payload = jwt.decode(token, options={"verify_signature": False})
exp = payload["exp"]
exp_datetime = datetime.fromtimestamp(exp)

print(f"Token expired at: {exp_datetime}")
print(f"Current time: {datetime.utcnow()}")
```

2. **Generate new token:**
```python
new_token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123",
    scopes=["read", "execute"]
)
```

3. **Extend expiration in configuration:**
```yaml
# settings/mahavishnu.yaml
subscription_auth_expire_minutes: 1440  # 24 hours instead of 8
```

### Issue: "Insufficient permissions"

**Symptoms:**
```
AuthorizationError: Insufficient permissions: 'workflow_manage' scope required
```

**Solutions:**

1. **Check available scopes:**
```python
result = auth_handler.authenticate_request(f"Bearer {token}")
print(f"Available scopes: {result['scopes']}")
```

2. **Create new token with required scopes:**
```python
new_token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123",
    scopes=["read", "execute", "workflow_manage"]  # Add workflow_manage
)
```

### Issue: "Invalid subscription token signature"

**Symptoms:**
```
AuthenticationError: Invalid subscription token signature
```

**Solutions:**

1. **Verify secret matches:**
```bash
# Check environment variable
echo $MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET

# Should be same as used when creating token
```

2. **Regenerate token with correct secret:**
```python
# Ensure secret is set correctly
os.environ['MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET'] = 'your_32char_secret_key_minimum'

# Create new token
token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123",
    scopes=["read", "execute"]
)
```

### Issue: "Missing subscription_type in token"

**Symptoms:**
```
AuthenticationError: Invalid subscription token: missing required fields
```

**Solutions:**

1. **Token was created as standard JWT (not subscription)**
2. **Use create_claude_subscription_token() or create_codex_subscription_token() instead**

```python
# WRONG: Standard JWT
jwt_token = jwt_auth.create_access_token({"sub": "user"})

# CORRECT: Subscription token
subscription_token = auth_handler.create_claude_subscription_token(
    user_id="claude_user_123",
    scopes=["read", "execute"]
)
```

---

## Quick Reference

### Token Creation Commands

```bash
# Claude Code token (8 hour expiry)
mahavishnu auth create-token \
  --user-id claude_user_123 \
  --subscription claude_code \
  --scopes read,execute,workflow_manage \
  --expire-minutes 480

# Codex token (8 hour expiry)
mahavishnu auth create-token \
  --user-id codex_user_456 \
  --subscription codex \
  --scopes read,execute \
  --expire-minutes 480

# Short-lived token (1 hour expiry for development)
mahavishnu auth create-token \
  --user-id dev_user \
  --subscription claude_code \
  --scopes read,execute \
  --expire-minutes 60
```

### Token Validation Examples

```python
# Validate Claude Code token
from mahavishnu.core.subscription_auth import MultiAuthHandler

auth_handler = MultiAuthHandler(config)

result = auth_handler.authenticate_request(
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
)

print(f"User: {result['user']}")
print(f"Method: {result['method']}")
print(f"Subscription: {result['subscription_type']}")
print(f"Scopes: {result['scopes']}")
```

### Environment Variables

```bash
# Required for subscription auth
export MAHAVISHNU_SUBSCRIPTION_AUTH_SECRET="your_32char_secret_key_minimum"

# Optional: Pass token directly (for testing)
export MAHAVISHNU_SUBSCRIPTION_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# PostgreSQL
export MAHAVISHNU_PG_HOST="localhost"
export MAHAVISHNU_PG_PORT="5432"
export MAHAVISHNU_PG_DATABASE="mahavishnu"
export MAHAVISHNU_PG_USER="postgres"
export MAHAVISHNU_PG_PASSWORD="your_password"

# Ollama
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"
```

---

## Summary

### Authentication Methods Comparison

| Feature | JWT | Subscription Token | Qwen Free |
|---------|-----|------------------|----------|
| **Claude Code** | ❌ No | ✅ Yes | ❌ No |
| **Codex** | ❌ No | ✅ Yes | ❌ No |
| **Qwen** | ❌ No | ❌ No | ✅ Yes |
| **MCP Integration** | ❌ No | ✅ Yes | ❌ No |
| **API Access** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Subscription Required** | ❌ No | ✅ Yes | ❌ No |

### Recommended Setup by Use Case

| Use Case | Recommended Auth | Configuration |
|----------|-----------------|--------------|
| **Claude Code production** | Subscription token | `subscription_auth_enabled: true` |
| **Codex production** | Subscription token | `subscription_auth_enabled: true` |
| **Qwen development** | None (free tier) | `qwen_mode_enabled: true` |
| **Hybrid deployment** | Multi-auth | Both subscription and Qwen enabled |
| **Local development** | None (optional) | `subscription_auth_enabled: false` |

---

**Document Version:** 1.0
**Date:** 2025-01-24
**Status:** Complete
**Next:** Set up authentication for your deployment

**Related Documents:**
- `DEPLOYMENT_GUIDE.md` (Deployment options)
- `mahavishnu/core/subscription_auth.py` (Implementation)
- `test_auth_integration.py` (Test examples)
