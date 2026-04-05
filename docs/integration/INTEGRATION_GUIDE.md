# Mahavishnu Integration Guide

## Overview

Mahavishnu provides multiple integration patterns for external systems to consume its orchestration capabilities:

| Pattern | Use Case | Transport |
|---------|----------|-----------|
| **MCP Tools** | Direct tool invocation | stdio/HTTP (FastMCP) |
| **Pydantic AI Agent** | Python agent frameworks | Python import |
| **Webhooks** | Push-based events | HTTP POST |
| **Factory Functions** | Embedding in Python apps | Python import |

## 1. MCP Client Integration

### Connecting

External MCP clients connect to Mahavishnu's FastMCP server via HTTP:

```
http://localhost:8680
```

### Tool Versioning

Every MCP tool is versioned. Check versions before relying on specific response schemas:

```python
# Via MCP tool call
result = await mcp_client.call_tool("get_tool_versions", {})
# Returns: {"versions": {"list_repos": "1.0.0", ...}, "total_tools": 187}

# Check specific tool
result = await mcp_client.call_tool("get_tool_versions", {"tool_name": "trigger_workflow"})
# Returns: {"version": "1.1.0", "tool_name": "trigger_workflow"}
```

### Return Schema Contract

All tools follow a consistent return pattern:

**Success:**
```json
{"status": "success", "...": "..."}
```

**Error:**
```json
{"status": "error", "error": "descriptive message", "...": "..."}
```

Every return that includes an `"error"` key also includes a `"status"` key.

### Core Tools

| Tool | Version | Purpose |
|------|---------|---------|
| `list_repos` | 1.0.0 | List repositories with filtering |
| `trigger_workflow` | 1.1.0 | Execute workflow across repos |
| `get_workflow_status` | 1.0.0 | Check workflow execution status |
| `list_workflows` | 1.0.0 | List/filter workflows |
| `cancel_workflow` | 1.0.0 | Cancel running workflow |
| `get_tool_versions` | 1.0.0 | Query tool version registry |

### Health Checking

```
GET /health → {"status": "ok", "service": "mahavishnu", "version": "x.y.z"}
```

## 2. Pydantic AI Agent

### Basic Usage

```python
from mahavishnu.agents import get_mahavishnu_agent

agent = get_mahavishnu_agent()

# Sweep repos with adaptive routing
from mahavishnu.agents.mahavishnu_agent import SweepReposRequest
result = await agent.sweep_repos(SweepReposRequest(tag="backend"))
print(result.success, result.workflow_id)

# Route task by natural language intent
from mahavishnu.agents.mahavishnu_agent import RouteTaskRequest
result = await agent.route_task(
    RouteTaskRequest(intent="security scan backend repos", strategy="success_rate")
)
print(result.adapter_used, result.fallback_chain)

# Check pool capacity
status = await agent.get_pool_status()
print(status.total_pools, status.active_workers)

# Debug routing decisions
info = await agent.get_routing_info(task_type="ai_task", strategy="balanced")
print(info.primary_adapter, info.adapter_scores)
```

### Dependency Injection

```python
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.agents import MahavishnuAgent

# Inject existing app (testing)
app = MahavishnuApp(MahavishnuSettings())
agent = MahavishnuAgent(app=app)

# Or inject config
agent = MahavishnuAgent(config=MahavishnuSettings())

# Reset singleton for testing
from mahavishnu.agents.mahavishnu_agent import reset_agent
reset_agent()
```

### Pydantic AI Integration

```python
from pydantic_ai import Agent
from mahavishnu.agents import get_mahavishnu_agent

orchestrator = get_mahavishnu_agent()
ai_agent = Agent('claude:opus-4-6')

@ai_agent.tool
async def sweep_backend_repos(ctx) -> str:
    """Sweep all backend repositories."""
    from mahavishnu.agents.mahavishnu_agent import SweepReposRequest
    result = await orchestrator.sweep_repos(SweepReposRequest(tag="backend"))
    return f"Sweep {'succeeded' if result.success else 'failed'}: {result.error or result.workflow_id}"
```

## 3. Webhook Integration

See [OpenClaw Webhook Documentation](../integrations/openclaw_webhooks.md) for full specification.

Quick reference:

```bash
# Sweep by tag
curl -X POST http://localhost:8680/webhooks/openclaw/sweep \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tag": "backend", "adapter": "agno"}'

# Workflow across repos
curl -X POST http://localhost:8680/webhooks/openclaw/workflow \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repos": ["org/repo1", "org/repo2"], "workflow_type": "code_sweep"}'

# Health check
curl http://localhost:8680/webhooks/openclaw/health
```

## 4. Factory Functions

Thread-safe singleton factories for embedding Mahavishnu components:

```python
from mahavishnu.factories import (
    get_pool_manager,
    get_websocket_server,
    get_terminal_manager,
)

# Pool management
pool_mgr = get_pool_manager()
status = await pool_mgr.get_all_pool_status()

# WebSocket broadcasting
ws_server = get_websocket_server()
await ws_server.broadcast_workflow_started("wf-123", {"tag": "backend"})
```

## 5. AST-Based Contract Testing

The integration test suite at `tests/integration/test_mcp_external.py` validates tool contracts without running infrastructure:

```python
# Tests parse Python AST to verify:
# - All @server.tool() functions have docstrings
# - All tools return dict[str, Any]
# - Error returns include both "status" and "error" keys
# - All parameters have type annotations
# - All tools are registered in TOOL_VERSIONS
# - Versions follow semver (major.minor.patch)
```

Run: `pytest tests/integration/test_mcp_external.py -v`
