# Mahavishnu Integration Plan: AI Agent Platforms

**Document Version:** 2.0
**Last Updated:** 2026-03-25
**Status:** Proposal (Roadmap Mode)
**Owner:** Mahavishnu Core Team

> This document is currently a forward-looking roadmap. It will transition to a live status document once implementation work starts.

---

## Executive Summary

This document outlines integration opportunities between **Mahavishnu** (multi-repository orchestration platform) and four AI agent platforms:

1. **Oh My OpenAgent / Sisyphus** (Priority 1 - Strategic)
2. **Pydantic AI `clai`** (Priority 2 - Quick Win)
3. **OpenClaw** (Priority 3 - Multi-Channel)
4. **DeepAgents CLI** (Priority 4 - Ecosystem Expansion)

All four platforms lack native multi-repository orchestration capabilities, which is Mahavishnu's core strength. Integration positions Mahavishnu as the **cross-repo orchestration layer** for the broader AI agent ecosystem.

---

## Integration Priority Matrix

| Priority | Platform | Integration Type | Effort | Strategic Value | Market Reach |
|----------|----------|------------------|--------|-----------------|--------------|
| 🥇 **1** | **Oh My OpenAgent / Sisyphus** | MCP Server + Category Handler | 6-7 days | **Highest** | 43.3k ⭐, 1.4M+ downloads (estimate, as of 2026-03-25) |
| 🥈 **2** | **Pydantic AI `clai`** | Agent Export + MCP Server | 2.5-3.5 days | **High** | Pydantic ecosystem (72 repos, estimate) |
| 🥉 **3** | **OpenClaw** | Custom Skill + Webhook | 5-6 days | **High** | 5,700+ skills, 25+ channels (estimate) |
| 4 | **DeepAgents CLI** | Skills + Subagent Target | 4-5 days | **Medium** | LangChain ecosystem |

---

## Current Baseline (Already Implemented)

The following foundation is already present in Mahavishnu and should be treated as baseline, not new scope:

- Worker registry entries: `terminal-opencode`, `terminal-openclaw`, `terminal-deepagents`, `terminal-clai`
- OpenClaw gateway worker: `gateway-openclaw` (HTTP JSON-RPC client + worker abstraction)
- Worker profile extras in packaging: `worker-openclaw`, `worker-deepagents`, `worker-clai`

Roadmap work below focuses on hardening, packaging, docs, and cross-platform user experience.

---

## Platform Analysis

### 1. Oh My OpenAgent / Sisyphus

#### Overview

**Oh My OpenAgent (OMO)** is a multi-model agent orchestration harness for OpenCode that transforms single AI agents into coordinated development teams.

**Sisyphus** is the primary orchestrator ("The CTO Who Never Sleeps") that:
- Plans, delegates to specialists, and drives tasks to completion
- Uses Intent Gate → Codebase Assessment → Smart Delegation → Verification
- Runs parallel agents (Prometheus for planning, Atlas for execution)
- Provides session continuity via `boulder.json`

#### Architecture

```
User Request → [Intent Gate] → [Sisyphus] → [Specialist Agents]
                                          ├─ Prometheus (planning)
                                          ├─ Atlas (execution)
                                          ├─ Oracle (architecture)
                                          ├─ Librarian (search)
                                          └─ Explore (codebase grep)
```

#### Key Features

| Feature | Description |
|---------|-------------|
| **Parallel Execution** | Fires 5+ background agents simultaneously |
| **Hash-Anchored Edits** | Uses `LINE#ID` content hashing for edit validation |
| **Intent Gate** | Classifies true intent before acting |
| **LSP + AST Tools** | IDE precision (rename, go-to-definition) |
| **Discipline Enforcement** | Prevents agents from producing low-quality output |
| **Working Modes** | Ultrawork (auto) and Prometheus (interview-based) |

#### Integration Fit

| Factor | Assessment |
|--------|------------|
| **MCP Role** | Client (consumes servers) ↔ Mahavishnu Server |
| **Multi-Repo** | ❌ Gap (Mahavishnu fills this) |
| **Category Routing** | ✅ Aligns with Mahavishnu adapters |
| **Session Continuity** | Boulder.json ↔ Session-Buddy (complementary) |
| **Project Context** | AGENTS.md (compatible format) |

---

### 2. Pydantic AI `clai`

#### Overview

**Pydantic AI** is a production-grade GenAI agent framework. The `clai` CLI tool provides:
- Interactive terminal chat with LLMs
- Custom agent loading (`--agent module:variable`)
- Builtin tools (web_search, code_execution)
- MCP server attachment capability
- Web UI (`clai web`)
- Message history persistence

#### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Provider** | OpenAI, Anthropic, etc. via `--model` |
| **Custom Agents** | Load agents via `--agent module:variable` |
| **Builtin Tools** | web_search, code_execution, MCP tools |
| **Web Interface** | `clai web` launches browser-based chat |
| **Message History** | Persistent conversation context |
| **Syntax Highlighting** | Configurable code themes |

#### Integration Fit

| Factor | Assessment |
|--------|------------|
| **MCP Role** | Client (consumes servers) ↔ Mahavishnu Server |
| **Multi-Repo** | ❌ Gap (Mahavishnu fills this) |
| **Agent Model** | `Agent` class (compatible with Mahavishnu tools) |
| **Validation** | Pydantic models (shared foundation) |
| **CLI Style** | Interactive chat + commands |

---

### 3. DeepAgents CLI (LangChain)

#### Overview

**DeepAgents CLI** is an open-source terminal coding agent built on the Deep Agents SDK with:
- Persistent memory across sessions
- `AGENTS.md` project context files
- Subagent delegation with `task` tool
- Custom subagents via markdown configs
- Skills system (reusable capabilities)
- Remote sandbox execution

#### Key Features

| Feature | Description |
|---------|-------------|
| **Persistent Memory** | Stores context in `~/.deepagents/<agent>/memories/` |
| **AGENTS.md** | Global and project-specific configuration |
| **Subagents** | Delegate work via `task` tool |
| **Skills** | Reusable capabilities in skill directories |
| **Context Compaction** | Auto-summarizes older messages |
| **Remote Sandboxes** | Isolated code execution |

#### Integration Fit

| Factor | Assessment |
|--------|------------|
| **MCP Role** | Client (consumes servers) ↔ Mahavishnu Server |
| **Multi-Repo** | ❌ Gap (Mahavishnu fills this) |
| **Agent Model** | Subagents + Skills (compatible) |
| **Memory** | Persistent memories (complementary to Session-Buddy) |
| **Project Context** | AGENTS.md (compatible format) |

---

### 4. OpenClaw

#### Overview

**OpenClaw** is a **personal AI assistant** designed to run on your own devices with:
- **25+ messaging channel support** (WhatsApp, Telegram, Slack, Discord, iMessage, etc.)
- **Local-first Gateway** architecture (ws://127.0.0.1:18789)
- **Multi-agent routing** with isolated sessions
- **ClawHub skills registry** (5,700+ skills)
- **Voice wake + talk mode** (macOS/iOS/Android)
- **Live Canvas** for visual agent interaction

#### Architecture

```
Messaging Channels (25+ platforms)
               │
               ▼
┌───────────────────────────────┐
│            Gateway            │
│       (control plane)         │
│     ws://127.0.0.1:18789      │
└──────────────┬────────────────┘
               │
               ├─ Pi agent (RPC)
               ├─ CLI (openclaw …)
               ├─ WebChat UI
               ├─ macOS app
               └─ iOS / Android nodes
```

**Key Subsystems:**
- **Gateway WebSocket Network** — Single WS control plane for clients, tools, and events
- **Tailscale Exposure** — Serve/Funnel for remote Gateway dashboard access
- **Browser Control** — OpenClaw-managed Chrome/Chromium with CDP control
- **Canvas + A2UI** — Agent-driven visual workspace
- **Nodes** — Camera, screen record, location, notifications, system.run/notify

#### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Channel Inbox** | 25+ platforms: WhatsApp, Telegram, Slack, Discord, etc. |
| **Local-First Gateway** | Single control plane for sessions, channels, tools, events |
| **Multi-Agent Routing** | Route inbound channels to isolated agents |
| **Voice Wake + Talk Mode** | Wake words on macOS/iOS, continuous voice on Android |
| **Live Canvas** | Agent-driven visual workspace with A2UI |
| **First-Class Tools** | Browser, canvas, nodes, cron, sessions, Discord/Slack actions |
| **Companion Apps** | macOS menu bar app + iOS/Android nodes |
| **Skills Platform** | ClawHub registry with 5,700+ skills |

#### MCP Support Status

| Aspect | Status |
|--------|--------|
| **Native MCP Client** | ❌ Not supported (issue #8188 closed) |
| **MCP Adapter** | ✅ Community: `openclaw-mcp-adapter` (OpenClaw → MCP Server) |
| **External MCP** | ⚠️ Workaround: Custom skills or webhooks |

#### Integration Fit

| Factor | Assessment |
|--------|------------|
| **MCP Role** | No native client ↔ Mahavishnu Server (gap) |
| **Multi-Repo** | ❌ Gap (Mahavishnu fills this) |
| **Agent Model** | Skills + Plugins (compatible) |
| **Session Memory** | Gateway sessions (complementary) |
| **Project Context** | SKILL.md (compatible format) |
| **Unique Value** | 25+ messaging channels for workflow triggers |

---

## Integration Opportunities

### Oh My OpenAgent / Sisyphus

| ID | Integration | Effort | Impact | Priority |
|----|-------------|--------|--------|----------|
| **OMO-1** | MCP Server Registration | Low | High | ✅ P0 |
| **OMO-2** | Category Handler | Medium | High | ✅ P0 |
| **OMO-3** | Sisyphus Delegation Target | Medium | High | ✅ P1 |
| **OMO-4** | Shared AGENTS.md Format | Low | Medium | ⚠️ P2 |
| **OMO-5** | Session Continuity Bridge | High | Medium | ⚠️ P3 |

### Pydantic AI `clai`

| ID | Integration | Effort | Impact | Priority |
|----|-------------|--------|--------|----------|
| **PAI-1** | Mahavishnu as Pydantic Agent | Low | High | ✅ P0 |
| **PAI-2** | MCP Server Attachment | Low | High | ✅ P0 |
| **PAI-3** | Engine Adapter | Medium | Medium | ⚠️ P2 |
| **PAI-4** | Shared Tool Definitions | Low | Medium | ⚠️ P2 |
| **PAI-5** | Web UI Integration | High | Low | ❌ P3 |

### DeepAgents CLI

| ID | Integration | Effort | Impact | Priority |
|----|-------------|--------|--------|----------|
| **DA-1** | Mahavishnu as DeepAgents Skill | Medium | Medium | ✅ P1 |
| **DA-2** | Subagent Target | Medium | Medium | ✅ P1 |
| **DA-3** | MCP Server Attachment | Low | Medium | ✅ P1 |
| **DA-4** | Memory Sharing | High | Low | ❌ P3 |
| **DA-5** | AGENTS.md Compatibility | Low | Low | ❌ P3 |

### OpenClaw

| ID | Integration | Effort | Impact | Priority |
|----|-------------|--------|--------|----------|
| **OC-1** | Custom Mahavishnu Skill | Medium | High | ✅ P0 |
| **OC-2** | Gateway Webhook Integration | Low | Medium | ✅ P1 |
| **OC-3** | MCP Adapter Extension | High | High | ⚠️ P2 |
| **OC-4** | Multi-Agent Routing Target | Medium | Medium | ⚠️ P2 |
| **OC-5** | Channel-Specific Workflows | Medium | Low | ❌ P3 |

---

## Technical Implementation

### OMO-1: MCP Server Registration

**Goal:** Expose Mahavishnu as MCP server in OMO configuration.

```yaml
# ~/.oh-my-openagent/config.yaml
mcpServers:
  mahavishnu:
    command: mahavishnu
    args: ["mcp", "start"]
    env:
      MAHAVISHNU_AUTH_SECRET: "${MAHAVISHNU_AUTH_SECRET}"
      MAHAVISHNU_REPOS_PATH: ~/repos.yaml
```

**Implementation Steps:**
1. Verify Mahavishnu MCP server exposes OMO-compatible tools
2. Document OMO configuration format
3. Test tool discovery in OMO sessions
4. Create example workflows

**Files to Modify:**
- `mahavishnu/mcp/server_core.py` - Add OMO-compatible tool schemas
- `docs/integrations/oh-my-openagent.md` - Integration guide

---

### OMO-2: Category Handler

**Goal:** Register Mahavishnu as `multi-repo` category in OMO routing.

```yaml
# ~/.oh-my-openagent/config.yaml
categories:
  multi-repo-sweep:
    handler: mahavishnu
    mcp:
      command: mahavishnu
      args: ["mcp", "start"]
```

```python
# mahavishnu/mcp/tools/omo_tools.py
from typing import Any

from fastmcp import FastMCP

from mahavishnu.core.app import MahavishnuApp


def register_omo_tools(server: FastMCP, app: MahavishnuApp) -> None:
    @server.tool()
    async def sisyphean_sweep(
        intent: str,
        tags: list[str],
        adapter: str = "agno",
    ) -> dict[str, Any]:
        """
        Execute a sweep optimized for Sisyphus delegation.
        Returns deterministic summary fields for OMO verification flows.
        """
        target_repos = []
        for tag in tags:
            target_repos.extend(app.get_repos(tag=tag))

        # De-duplicate while preserving order
        target_repos = list(dict.fromkeys(target_repos))
        task = {"type": "code_sweep", "params": {"intent": intent, "tags": tags}}

        result = await app.execute_workflow_parallel(
            task=task,
            adapter_name=adapter,
            repos=target_repos,
        )

        return {
            "intent": intent,
            "tags": tags,
            "repos": target_repos,
            "result": result,
        }
```

**Implementation Steps:**
1. Define OMO category tool schema
2. Implement result formatting for OMO verification
3. Test delegation flow (Sisyphus → Mahavishnu → Results)
4. Document category configuration

---

### PAI-1: Mahavishnu as Pydantic Agent

**Goal:** Export Mahavishnu tools as Pydantic AI `Agent`.

```python
# mahavishnu/agents/pydantic_agent.py
"""
Mahavishnu Pydantic AI Agent Integration

Usage:
    clai --agent mahavishnu.agents.pydantic_agent:mahavishnu_agent
"""
from pydantic_ai import Agent

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings

mahavishnu_agent = Agent(
    name="mahavishnu",
    instructions="""You are a multi-repository orchestration assistant.
    You can execute workflows across repositories using Prefect, LlamaIndex, or Agno.
    
    Available capabilities:
    - Sweep repositories with AI analysis
    - Execute workflows on tagged repositories
    - Run quality checks via Crackerjack
    - Manage terminal sessions
    """,
)

@mahavishnu_agent.tool
async def sweep_repos(tag: str, adapter: str = "llamaindex") -> dict:
    """
    Execute AI sweep across repositories with given tag.
    
    Args:
        tag: Repository tag to filter (e.g., 'backend', 'python')
        adapter: Orchestration adapter (prefect, llamaindex, agno)
    
    Returns:
        Dictionary with sweep results per repository
    """
    settings = MahavishnuSettings()
    app = MahavishnuApp(config=settings)
    repos = app.get_repos(tag=tag)
    
    if not repos:
        return {"error": f"No repositories found with tag '{tag}'"}
    
    task = {"type": "code_sweep", "params": {"tag": tag}}
    result = await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
    return {"repositories": repos, "result": result}

@mahavishnu_agent.tool
async def run_workflow(name: str, repos: list[str], adapter: str = "agno") -> dict:
    """
    Run a named workflow on specified repositories.
    
    Args:
        name: Workflow name from configuration
        repos: List of repository names or tags
    
    Returns:
        Workflow execution results
    """
    settings = MahavishnuSettings()
    app = MahavishnuApp(config=settings)
    task = {"type": name, "params": {}}
    return await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
```

**Implementation Steps:**
1. Create `mahavishnu/agents/` package
2. Implement Pydantic AI agent with Mahavishnu tools
3. Confirm `pydantic-ai` dependency/version compatibility (already in core dependencies)
4. Document installation and usage
5. Test with `clai` CLI

**Files to Create:**
- `mahavishnu/agents/__init__.py`
- `mahavishnu/agents/pydantic_agent.py`
- `docs/integrations/pydantic-ai.md`

**Files to Modify:**
- `pyproject.toml` - Pin/adjust `pydantic-ai` version if compatibility issues are found

---

### PAI-2: MCP Server Attachment

**Goal:** Enable Mahavishnu MCP server attachment in Pydantic AI sessions.

```python
# User's clai session
from pydantic_ai import Agent
from pydantic_ai.mcp import attach_mcp

agent = Agent()

# Attach Mahavishnu MCP server
await attach_mcp(
    agent,
    command="mahavishnu",
    args=["mcp", "start"],
    env={
        "MAHAVISHNU_AUTH_SECRET": "...",
        "MAHAVISHNU_REPOS_PATH": "~/repos.yaml"
    }
)
```

**Implementation Steps:**
1. Verify Mahavishnu MCP server compatibility with Pydantic AI
2. Document attachment procedure
3. Create example session scripts
4. Test tool discovery and execution

---

### DA-1: Mahavishnu as DeepAgents Skill

**Goal:** Package Mahavishnu workflows as DeepAgents skills.

```python
# skills/mahavishnu-sweep/__init__.py
"""
Mahavishnu Sweep Skill for DeepAgents

DeepAgents automatically discovers and loads this skill.
Place in ~/.deepagents/skills/mahavishnu-sweep/ or project's skills/ directory.
"""
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings

async def sweep(tag: str, adapter: str = "llamaindex"):
    """
    Execute AI sweep across tagged repositories.
    
    Args:
        tag: Repository tag to filter
        adapter: Orchestration adapter to use
    
    Returns:
        Dictionary with sweep results
    """
    settings = MahavishnuSettings()
    app = MahavishnuApp(config=settings)
    repos = app.get_repos(tag=tag)
    
    if not repos:
        return {"error": f"No repositories found with tag '{tag}'"}
    
    task = {"type": "code_sweep", "params": {"tag": tag}}
    results = await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
    return {
        "skill": "mahavishnu-sweep",
        "tag": tag,
        "adapter": adapter,
        "repositories": len(repos),
        "results": results
    }

async def get_capabilities():
    """Return skill capabilities for DeepAgents discovery."""
    return {
        "name": "mahavishnu-sweep",
        "version": "1.0.0",
        "description": "Multi-repository AI sweep using Mahavishnu",
        "functions": ["sweep", "run_workflow"],
        "requirements": ["mahavishnu"]
    }
```

**Implementation Steps:**
1. Create skill package structure
2. Implement skill functions
3. Document installation (global vs. project-local)
4. Test skill discovery in DeepAgents sessions

**Files to Create:**
- `mahavishnu/integrations/deepagents_skills/mahavishnu-sweep/__init__.py`
- `mahavishnu/integrations/deepagents_skills/mahavishnu-sweep/README.md`

---

### OC-1: Custom Mahavishnu Skill

**Goal:** Package Mahavishnu workflows as OpenClaw skills in ClawHub registry.

```markdown
# ~/.openclaw/workspace/skills/mahavishnu-sweep/SKILL.md

---
name: mahavishnu-sweep
version: 1.0.0
description: Multi-repository AI sweep using Mahavishnu orchestration
author: Mahavishnu Team
tags: [orchestration, multi-repo, sweep]
---

## Capabilities

This skill enables OpenClaw to execute AI sweeps across multiple repositories
using Mahavishnu.

## Tools

### sweep_repos

Execute AI sweep across repositories with given tag.

**Parameters:**
- `tag` (string): Repository tag to filter (e.g., 'backend', 'python')
- `adapter` (string): Orchestration adapter (prefect, llamaindex, agno)

**Example:**
```
sweep_repos(tag="backend", adapter="llamaindex")
```

### run_workflow

Run a named workflow on specified repositories.

**Parameters:**
- `name` (string): Workflow name
- `repos` (array): List of repository names or tags

**Example:**
```
run_workflow(name="ci-pipeline", repos=["backend", "frontend"])
```

## Configuration

```json
{
  "mahavishnu": {
    "repos_path": "~/repos.yaml",
    "auth_secret": "${MAHAVISHNU_AUTH_SECRET}"
  }
}
```
```

**Implementation:**

```python
# ~/.openclaw/workspace/skills/mahavishnu-sweep/skill.py
"""
Mahavishnu Sweep Skill for OpenClaw

OpenClaw automatically discovers and loads this skill.
Place in ~/.openclaw/workspace/skills/mahavishnu-sweep/ directory.
"""
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings

async def sweep_repos(tag: str, adapter: str = "llamaindex"):
    """
    Execute AI sweep across tagged repositories.
    
    Args:
        tag: Repository tag to filter
        adapter: Orchestration adapter to use
    
    Returns:
        Dictionary with sweep results
    """
    settings = MahavishnuSettings()
    app = MahavishnuApp(config=settings)
    repos = app.get_repos(tag=tag)
    
    if not repos:
        return {"error": f"No repositories found with tag '{tag}'"}
    
    task = {"type": "code_sweep", "params": {"tag": tag}}
    results = await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
    return {
        "skill": "mahavishnu-sweep",
        "tag": tag,
        "adapter": adapter,
        "repositories": len(repos),
        "results": results
    }

async def run_workflow(name: str, repos: list[str], adapter: str = "agno"):
    """Run workflow on repositories."""
    settings = MahavishnuSettings()
    app = MahavishnuApp(config=settings)
    task = {"type": name, "params": {}}
    return await app.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )

async def get_capabilities():
    """Return skill capabilities for OpenClaw discovery."""
    return {
        "name": "mahavishnu-sweep",
        "version": "1.0.0",
        "description": "Multi-repository AI sweep using Mahavishnu",
        "functions": ["sweep_repos", "run_workflow"],
        "requirements": ["mahavishnu"]
    }
```

**Implementation Steps:**
1. Create skill package structure with SKILL.md
2. Implement skill functions
3. Document installation via ClawHub or manual
4. Test skill discovery in OpenClaw sessions

**Files to Create:**
- `mahavishnu/integrations/openclaw_skills/mahavishnu-sweep/SKILL.md`
- `mahavishnu/integrations/openclaw_skills/mahavishnu-sweep/skill.py`
- `mahavishnu/integrations/openclaw_skills/mahavishnu-sweep/README.md`

**Installation:**
```bash
# Install Mahavishnu skill
openclaw skill install mahavishnu-sweep

# Or manually
cp -r mahavishnu-sweep ~/.openclaw/workspace/skills/
```

---

### OC-2: Gateway Webhook Integration

**Goal:** Enable OpenClaw to trigger Mahavishnu workflows via webhooks.

```python
# mahavishnu/integrations/openclaw_webhook.py
"""
OpenClaw Gateway Webhook Integration

OpenClaw can trigger Mahavishnu workflows via webhooks.
Configure in OpenClaw: /webhooks/register
"""
from fastapi import FastAPI, Header, HTTPException
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings

app = FastAPI()

@app.post("/webhooks/openclaw/sweep")
async def openclaw_sweep(
    tag: str,
    adapter: str = "llamaindex",
    authorization: str = Header(default="")
):
    """
    OpenClaw webhook to trigger Mahavishnu sweep.
    
    OpenClaw configuration:
    ```yaml
    webhooks:
      - name: mahavishnu-sweep
        url: http://mahavishnu:8000/webhooks/openclaw/sweep
        method: POST
        params:
          tag: "{{tag}}"
          adapter: "{{adapter}}"
    ```
    """
    # TODO: Replace with Mahavishnu's shared auth layer when endpoint is implemented.
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    app_instance = MahavishnuApp(config=MahavishnuSettings())
    repos = app_instance.get_repos(tag=tag)
    
    if not repos:
        raise HTTPException(404, f"No repos with tag '{tag}'")
    
    task = {"type": "code_sweep", "params": {"tag": tag}}
    results = await app_instance.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
    return {"status": "success", "results": results}

@app.post("/webhooks/openclaw/workflow")
async def openclaw_workflow(
    name: str,
    repos: list[str],
    adapter: str = "agno",
    authorization: str = Header(default="")
):
    """OpenClaw webhook to trigger Mahavishnu workflow."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    app_instance = MahavishnuApp(config=MahavishnuSettings())
    task = {"type": name, "params": {}}
    return await app_instance.execute_workflow_parallel(
        task=task,
        adapter_name=adapter,
        repos=repos,
    )
```

**OpenClaw Configuration:**

```json
// ~/.openclaw/openclaw.json
{
  "webhooks": [
    {
      "name": "mahavishnu-sweep",
      "url": "http://localhost:8000/webhooks/openclaw/sweep",
      "method": "POST",
      "auth": {
        "type": "bearer",
        "token": "${MAHAVISHNU_API_KEY}"
      }
    },
    {
      "name": "mahavishnu-workflow",
      "url": "http://localhost:8000/webhooks/openclaw/workflow",
      "method": "POST",
      "auth": {
        "type": "bearer",
        "token": "${MAHAVISHNU_API_KEY}"
      }
    }
  ]
}
```

**Implementation Steps:**
1. Add webhook endpoints to Mahavishnu API
2. Document OpenClaw webhook configuration
3. Test webhook triggering from OpenClaw
4. Create example workflows

**Files to Create:**
- `mahavishnu/integrations/openclaw_webhook.py`
- `docs/integrations/openclaw-webhooks.md`

---

### OC-3: MCP Adapter Extension (Optional)

**Goal:** Extend `openclaw-mcp-adapter` to enable OpenClaw → Mahavishnu MCP communication.

**Note:** OpenClaw lacks native MCP client support. This integration requires either:
- Contributing to the community `openclaw-mcp-adapter` project
- Building a Mahavishnu-specific OpenClaw plugin

**Approach A: Contribute to openclaw-mcp-adapter**

```typescript
// openclaw-mcp-adapter/mcp-client.ts
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';

export class MahavishnuMCPClient {
  private client: Client;
  
  constructor() {
    this.client = new Client({
      name: 'openclaw-mahavishnu-client',
      version: '1.0.0',
    });
  }
  
  async connect(url: string) {
    const transport = new SSEClientTransport(new URL(url));
    await this.client.connect(transport);
    
    // Discover Mahavishnu tools
    const tools = await this.client.listTools();
    return tools;
  }
  
  async sweepRepos(tag: string, adapter: string) {
    const result = await this.client.callTool({
      name: 'sweep_repos',
      arguments: { tag, adapter },
    });
    return result;
  }
}
```

**Approach B: Build Mahavishnu-specific OpenClaw Plugin**

```typescript
// openclaw-mahavishnu-plugin/index.ts
import { Plugin } from '@openclaw/core';
import { MahavishnuClient } from './mahavishnu-client';

export class MahavishnuPlugin extends Plugin {
  private client: MahavishnuClient;
  
  async initialize(config: PluginConfig) {
    this.client = new MahavishnuClient(config.mahavishnu);
    
    // Register tools with OpenClaw
    this.registerTool('sweep_repos', this.sweepRepos.bind(this));
    this.registerTool('run_workflow', this.runWorkflow.bind(this));
  }
  
  async sweepRepos(tag: string, adapter: string) {
    return await this.client.sweepRepos(tag, adapter);
  }
  
  async runWorkflow(name: string, repos: string[]) {
    return await this.client.runWorkflow(name, repos);
  }
}
```

**Implementation Steps:**
1. Evaluate community adapter vs. custom plugin approach
2. Implement MCP client or plugin
3. Test Mahavishnu tool discovery and execution
4. Publish to npm or ClawHub registry

**Files to Create:**
- `mahavishnu/integrations/openclaw-mcp-adapter/` (if contributing)
- `mahavishnu/integrations/openclaw-mahavishnu-plugin/` (if custom)

---

## Implementation Timeline

### Phase 1: Quick Wins (Week 1-2)

**Focus:** Pydantic AI integration + OpenClaw webhooks (lowest effort, immediate value)

| Task | Owner | Effort | Deliverable |
|------|-------|--------|-------------|
| MCP Server hardening | Core Team | 2 days | Stable tool contracts |
| Pydantic Agent export | Integration Team | 2 days | `mahavishnu.agents.pydantic_agent` |
| OpenClaw webhook endpoints | Integration Team | 1 day | `/webhooks/openclaw/*` endpoints |
| Documentation | Docs Team | 1 day | Integration guides |

**Success Criteria (Target):**
- [ ] Users can attach Mahavishnu to Pydantic AI `clai` sessions
- [ ] All Mahavishnu MCP tools available in `clai`
- [ ] OpenClaw can trigger Mahavishnu via webhooks
- [ ] Documentation published

---

### Phase 2: Strategic Integration (Week 3-5)

**Focus:** Oh My OpenAgent / Sisyphus (highest strategic value) + OpenClaw skills

| Task | Owner | Effort | Deliverable |
|------|-------|--------|-------------|
| OMO MCP server registration | Core Team | 2 days | MCP server compatibility |
| Category handler implementation | Integration Team | 3 days | Sisyphus delegation |
| OpenClaw skill packaging | Integration Team | 2 days | ClawHub skill submission |
| Testing + examples | QA Team | 2 days | Production-ready integration |

**Success Criteria (Target):**
- [ ] Mahavishnu available as OMO MCP server
- [ ] Sisyphus can delegate multi-repo tasks
- [ ] Mahavishnu skill available in OpenClaw ClawHub
- [ ] Example workflows documented

---

### Phase 3: Ecosystem Expansion (Week 6-8)

**Focus:** DeepAgents CLI + OpenClaw MCP adapter (ecosystem diversification)

| Task | Owner | Effort | Deliverable |
|------|-------|--------|-------------|
| DeepAgents skill packaging | Integration Team | 2 days | Skills marketplace submission |
| OpenClaw MCP adapter evaluation | Core Team | 2 days | Adapter vs. plugin decision |
| Cross-platform memory sync | Core Team | 3 days | Session continuity protocol |
| Engine adapter (optional) | Core Team | 3 days | Pydantic AI as backend |

**Success Criteria (Target):**
- [ ] Mahavishnu skills available in DeepAgents
- [ ] OpenClaw MCP adapter decision documented
- [ ] Memory sync between platforms (optional)
- [ ] Integration documented

---

## Risk Assessment

### Technical Risks

| Risk | Platform | Probability | Impact | Mitigation |
|------|----------|-------------|--------|------------|
| API changes | All | Medium | Medium | Pin versions, follow stable releases |
| MCP spec evolution | All | Low | High | Engage with MCP working group |
| Tool schema mismatches | Pydantic AI | Low | Low | Use Pydantic models for validation |
| Category routing conflicts | OMO | Low | Medium | Use unique category names (`mahavishnu-*`) |
| Memory format conflicts | DeepAgents | Medium | Low | Use separate namespaces |
| OpenClaw MCP limitations | OpenClaw | High | Medium | Use webhooks + skills as workaround |
| ClawHub skill review | OpenClaw | Medium | Low | Follow security best practices |

### Strategic Risks

| Risk | Platform | Probability | Impact | Mitigation |
|------|----------|-------------|--------|------------|
| Platform deprecation | All | Low | High | Diversify across multiple platforms |
| Market consolidation | All | Medium | Medium | Maintain Mahavishnu as standalone |
| Feature overlap | DeepAgents | Medium | Low | Focus on multi-repo differentiation |
| Ecosystem fragmentation | All | High | Low | Support all major platforms |
| OpenClaw community adoption | OpenClaw | Medium | Medium | Engage with community early |

---

## Success Metrics

### Adoption Metrics

| Metric | Target | Timeline |
|--------|--------|----------|
| Integration downloads | 1,000+ | 3 months |
| Active integration users | 100+ | 3 months |
| GitHub stars (integration docs) | 50+ | 2 months |
| Community contributions | 5+ PRs | 6 months |

### Technical Metrics

| Metric | Target | Timeline |
|--------|--------|----------|
| Tool call success rate | >99% | Ongoing |
| MCP server uptime | >99.9% | Ongoing |
| Integration test coverage | >90% | Per release |
| Documentation completeness | 100% | Per release |

---

## Maintenance Plan

### Ongoing Responsibilities

| Task | Frequency | Owner |
|------|-----------|-------|
| Version compatibility checks | Monthly | Core Team |
| Integration test updates | Per release | QA Team |
| Documentation updates | Per release | Docs Team |
| Community support | Ongoing | All Teams |
| Platform liaison | Quarterly | Core Team |

### Version Compatibility Matrix

| Mahavishnu | OMO | Pydantic AI | OpenClaw | DeepAgents |
|------------|-----|-------------|----------|------------|
| 0.3.x (current) | 0.5.x+ | 0.2.x+ | 1.0.x+ | 0.3.x+ |
| 0.4.x (planned) | 0.5.x+ | 0.2.x+ | 1.0.x+ | 0.3.x+ |
| 1.0.x (target) | 0.6.x+ | 0.3.x+ | 1.1.x+ | 0.4.x+ |

---

## Appendix A: Platform Comparison

| Feature | Mahavishnu | OMO/Sisyphus | Pydantic AI | OpenClaw | DeepAgents |
|---------|-----------|--------------|-------------|----------|------------|
| **Primary Focus** | Multi-repo orchestration | Multi-agent coordination | Agent framework | Personal assistant | Terminal agent |
| **MCP Role** | Server | Client | Client | ❌ No native | Client |
| **Agent Model** | Adapters | Categories | `Agent` class | Skills + Plugins | Subagents + Skills |
| **Session Memory** | Session-Buddy | Boulder.json | Message history | Gateway sessions | Persistent memories |
| **Project Context** | repos.yaml | AGENTS.md | AGENTS.md | SKILL.md | AGENTS.md |
| **Multi-Repo** | ✅ Core feature | ❌ Gap | ❌ Gap | ❌ Gap | ❌ Gap |
| **Workflow Engines** | Prefect, LlamaIndex, Agno | Native | Pydantic AI | Native | Native |
| **Quality Control** | Crackerjack | Built-in verification | Not built-in | Not built-in | Not built-in |
| **Web UI** | None | OpenCode TUI | `clai web` | Live Canvas | None |
| **Messaging Channels** | ❌ None | ❌ None | ❌ None | ✅ 25+ platforms | ❌ None |
| **Voice Interface** | ❌ None | ❌ None | ❌ None | ✅ Wake + talk | ❌ None |
| **Mobile Apps** | ❌ None | ❌ None | ❌ None | ✅ iOS/Android | ❌ None |

---

## Appendix B: Quick Start Guides

### Pydantic AI Integration

```bash
# Install Mahavishnu (includes pydantic-ai dependency in current releases)
pip install mahavishnu

# Use in clai session
clai --agent mahavishnu.agents.pydantic_agent:mahavishnu_agent

# Or attach via MCP (in clai session)
from pydantic_ai.mcp import attach_mcp
await attach_mcp(agent, command="mahavishnu", args=["mcp", "start"])
```

### Oh My OpenAgent Integration

```yaml
# ~/.oh-my-openagent/config.yaml
mcpServers:
  mahavishnu:
    command: mahavishnu
    args: ["mcp", "start"]
    env:
      MAHAVISHNU_REPOS_PATH: ~/repos.yaml
```

### DeepAgents Integration

```bash
# Install Mahavishnu skills
cp -r mahavishnu/integrations/deepagents_skills/mahavishnu-sweep \
  ~/.deepagents/skills/

# Use in DeepAgents session
# "Use the mahavishnu-sweep skill on backend repos"
```

### OpenClaw Integration

```bash
# Option 1: Install Mahavishnu skill (recommended)
openclaw skill install mahavishnu-sweep

# Use in OpenClaw chat (any channel: WhatsApp, Slack, Discord, etc.)
# "Run sweep_repos with tag='backend' and adapter='llamaindex'"

# Option 2: Configure webhook trigger
# ~/.openclaw/openclaw.json
{
  "webhooks": [
    {
      "name": "mahavishnu-sweep",
      "url": "http://localhost:8000/webhooks/openclaw/sweep",
      "method": "POST",
      "auth": {
        "type": "bearer",
        "token": "${MAHAVISHNU_API_KEY}"
      }
    }
  ]
}

# Then trigger via chat command or voice:
# "Trigger mahavishnu-sweep webhook with tag backend"
```

**Killer Use Case:**

```
User (via WhatsApp to OpenClaw): "Run security sweep on all backend repos"
  ↓
OpenClaw: Routes to Mahavishnu skill
  ↓
Mahavishnu: Executes sweep with tag="backend", adapter="llamaindex"
  ↓
Results: Sent back via WhatsApp with summary + links to detailed reports
```

---

## Appendix C: Contact & Resources

- **Mahavishnu Repository:** `/Users/les/Projects/mahavishnu`
- **Documentation:** `docs/integrations/` (integration-specific guides are planned in this roadmap)
- **Integration Issues:** GitHub Issues (label: `integration`)
- **Platform Documentation:**
  - [Oh My OpenAgent](https://ohmyopenagent.com/)
  - [Pydantic AI](https://ai.pydantic.dev/)
  - [OpenClaw](https://github.com/openclaw/openclaw)
  - [DeepAgents](https://docs.langchain.com/oss/python/deepagents/cli/overview)
- **Community Registries:**
  - [ClawHub (OpenClaw Skills)](https://github.com/SamurAIGPT/awesome-openclaw)
  - [Pydantic AI Packages](https://pypi.org/project/pydantic-ai/)

---

**Document History:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-25 | Mahavishnu Core Team | Initial proposal |
| 2.0 | 2026-03-25 | Mahavishnu Core Team | Added OpenClaw integration |
