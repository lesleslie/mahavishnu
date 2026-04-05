# OpenClaw Webhook Integration

## Overview

Mahavishnu exposes webhook endpoints for external platforms like OpenClaw to trigger orchestration workflows. Webhooks provide a push-based integration pattern where external systems notify Mahavishnu of events that require processing.

## Endpoints

### POST `/webhooks/openclaw/sweep`

Triggers a sweep workflow across all repositories matching a tag.

**Rate Limit:** 10 requests/minute per IP

**Request Body:**

```json
{
  "tag": "backend",
  "adapter": "agno",
  "task_description": "Security scan all backend repos",
  "priority": "high",
  "dry_run": false,
  "metadata": {
    "source": "openclaw",
    "trigger": "scheduled"
  }
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `tag` | string | yes | - | Repository tag (alphanumeric, underscores, hyphens only) |
| `adapter` | string | no | `"agno"` | One of: `agno`, `llamaindex`, `prefect` |
| `task_description` | string | no | `null` | Max 1000 chars |
| `priority` | string | no | `"normal"` | One of: `low`, `normal`, `high`, `critical` |
| `dry_run` | boolean | no | `false` | Simulate without executing |
| `metadata` | object | no | `{}` | Max 4KB JSON |

**Response (200):**

```json
{
  "status": "accepted",
  "message": "Sweep workflow initiated for tag 'backend'",
  "workflow_id": "wf-sweep-backend-user123",
  "accepted_at": "2026-04-03T12:00:00Z",
  "details": {
    "tag": "backend",
    "adapter": "agno",
    "task_type": "code_sweep",
    "fallback_chain": ["agno", "prefect", "llamaindex"],
    "dry_run": false,
    "user": "user123"
  }
}
```

### POST `/webhooks/openclaw/workflow`

Triggers a workflow across specified repositories.

**Rate Limit:** 5 requests/minute per IP

**Request Body:**

```json
{
  "repos": ["mahavishnu/core", "mahavishnu/mcp"],
  "adapter": "prefect",
  "workflow_type": "quality_check",
  "task_description": "Run quality checks on core modules",
  "parallel": true,
  "fail_fast": false,
  "timeout_seconds": 300,
  "metadata": {}
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repos` | string[] | yes | - | 1-100 repository paths |
| `adapter` | string | no | `"prefect"` | One of: `agno`, `llamaindex`, `prefect` |
| `workflow_type` | string | no | `"code_sweep"` | Max 64 chars |
| `task_description` | string | no | `null` | Max 1000 chars |
| `parallel` | boolean | no | `true` | Execute across repos in parallel |
| `fail_fast` | boolean | no | `false` | Stop on first failure |
| `timeout_seconds` | integer | no | `300` | Range: 60-3600 |
| `metadata` | object | no | `{}` | Max 4KB JSON |

**Response (200):**

```json
{
  "status": "accepted",
  "message": "Workflow initiated for 2 repositories",
  "workflow_id": "wf-workflow-user123",
  "accepted_at": "2026-04-03T12:00:00Z",
  "details": {
    "repos": ["mahavishnu/core", "mahavishnu/mcp"],
    "repos_count": 2,
    "adapter": "prefect",
    "task_type": "quality_check",
    "fallback_chain": ["prefect", "agno", "llamaindex"],
    "parallel": true,
    "timeout_seconds": 300,
    "user": "user123"
  }
}
```

### GET `/webhooks/openclaw/health`

Health check endpoint for the webhook subsystem.

**Response (200):**

```json
{
  "status": "healthy",
  "service": "mahavishnu-webhooks",
  "endpoints": ["/openclaw/sweep", "/openclaw/workflow"]
}
```

## Authentication

All webhook endpoints require a valid `Authorization` header with a Bearer token:

```
Authorization: Bearer <token>
```

Authentication is handled by `MultiAuthHandler` which supports multiple providers:

1. **JWT tokens** - Standard JWT with expiry validation
2. **API keys** - Pre-configured API keys for service-to-service auth
3. **Subscription tokens** - Claude Code subscription-based auth

**Error Response (401):**

```json
{
  "detail": {
    "error_code": "AUTHENTICATION_ERROR",
    "message": "Authentication failed",
    "recovery": [
      "Ensure token is valid and not expired",
      "Use 'Bearer <token>' format in Authorization header"
    ]
  }
}
```

## Error Handling

### Validation Errors (422)

Request body validation failures return structured errors:

```json
{
  "detail": [
    {
      "loc": ["body", "tag"],
      "msg": "Invalid tag '../../../etc/passwd'. Must contain only alphanumeric characters, underscores, and hyphens",
      "type": "value_error"
    }
  ]
}
```

### Rate Limit Errors (429)

```json
{
  "status": "error",
  "error_code": "RATE_LIMIT_EXCEEDED",
  "message": "Rate limit exceeded: 10/minute",
  "recovery": ["Retry after 60 seconds"]
}
```

### Security Validation

All inputs are validated against injection attacks:

- **Path traversal**: Tags and repo paths reject `..`, `/../`, `~` prefixes
- **Size limits**: Metadata capped at 4KB, descriptions at 1000 chars
- **Enumeration**: Adapter values validated against known enum
- **Quantity limits**: Max 100 repos per workflow request

## Integration Examples

### Python (httpx)

```python
import httpx

async def trigger_sweep(tag: str, token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8680/webhooks/openclaw/sweep",
            json={"tag": tag, "adapter": "agno", "priority": "high"},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()
```

### curl

```bash
curl -X POST http://localhost:8680/webhooks/openclaw/sweep \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tag": "backend", "adapter": "agno"}'
```

### OpenClaw Agent Integration

```python
from mahavishnu.webhooks.models import OpenClawSweepRequest, OpenClawWorkflowRequest

# Build validated request
request = OpenClawSweepRequest(
    tag="backend",
    adapter="agno",
    task_description="Sweep backend repos for security issues",
    priority="high",
)

# Serialize for HTTP transport
payload = request.model_dump_json()
```

## Source Files

| File | Purpose |
|------|---------|
| `mahavishnu/webhooks/models.py` | Pydantic request/response models |
| `mahavishnu/webhooks/router.py` | FastAPI router with endpoints |
| `mahavishnu/core/subscription_auth.py` | MultiAuthHandler |
| `mahavishnu/core/rate_limiting.py` | Rate limit decorator |
| `mahavishnu/core/routing.py` | TaskRouter with intent classification |
