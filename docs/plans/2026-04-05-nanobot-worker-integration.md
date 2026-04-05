# Plan: Nanobot Worker Integration + Claude MCP Serve Autostart

## Context

Mahavishnu's ecosystem has multiple AI assistants (Claude Code, Codex, Qwen, Nanobot) that currently operate independently. This plan adds:

1. **`claude mcp serve` to autostart** — via supergateway stdio→HTTP bridge, giving nanobot and other MCP clients access to Claude Code's tools
2. **`NanobotWorker`** — an in-process worker using nanobot's Python API (`AgentRunner`/`AgentLoop`) for structured AI task execution without terminal overhead
3. **New `IN_PROCESS` worker category** — for workers that run via Python API directly (no terminal, no MCP client)

Existing workers (`terminal-claude`, `terminal-codex`, `terminal-qwen`, `terminal-openclaw`) remain unchanged.

---

## Phase A: Autostart — `claude mcp serve` via Supergateway

### A1. Add entry to `~/.claude.json`

Add `"claude-code"` MCP server config under `mcpServers`:
```json
"claude-code": {
  "type": "http",
  "url": "http://localhost:8700/mcp"
}
```

### A2. Add case to autostart script

**File**: `~/.claude/scripts/auto-start-mcp-servers.sh`

Add before the `*)` catch-all (~line 180):
```bash
"claude-code"|"claude-mcp-serve")
    start_server_if_needed "$server_name" "$port" \
        "npx -y supergateway --stdio \"claude mcp serve\" --outputTransport streamableHttp --port $port --streamableHttpPath /mcp --stateful --logLevel info"
    ;;
```

Note: supergateway takes 5-10s to initialize. The existing `max_wait=8` in `start_server_if_needed` may need bumping to `max_wait=15` for this entry if initial testing shows timeouts.

### A3. Add to nanobot config (optional)

**File**: `~/.nanobot/config.json`

Add under `tools.mcpServers`:
```json
"claude-code": {
  "type": "streamableHttp",
  "url": "http://localhost:8700/mcp",
  "tool_timeout": 120,
  "enabled_tools": ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "LSP"]
}
```

**Critical**: Limit `enabled_tools` to non-recursive tools. No `Bash` or `Skill` to prevent loops (nanobot → claude → bash → nanobot).

---

## Phase B: NanobotWorker Core Implementation

### B1. Add `IN_PROCESS` worker category

**File**: `mahavishnu/workers/registry.py`

Add to `WorkerCategory` enum:
```python
IN_PROCESS = "in_process"  # In-process Python API workers
```

### B2. Register nanobot worker types

**File**: `mahavishnu/workers/registry.py`

Add to `WORKER_REGISTRY`:
```python
"in-process-nanobot": WorkerConfig(
    name="Nanobot AgentRunner",
    worker_type="in-process-nanobot",
    command="",
    category=WorkerCategory.IN_PROCESS,
    description="In-process nanobot AgentRunner for lightweight AI tasks",
    completion_markers=[],
    stream_format="text",
    supports_interactive=False,
    default_timeout=300,
),
"in-process-nanobot-loop": WorkerConfig(
    name="Nanobot AgentLoop",
    worker_type="in-process-nanobot-loop",
    command="",
    category=WorkerCategory.IN_PROCESS,
    description="Full nanobot AgentLoop with sessions, memory, MCP tools",
    completion_markers=[],
    stream_format="text",
    supports_interactive=False,
    default_timeout=600,
),
```

### B3. Create NanobotWorker class

**New file**: `mahavishnu/workers/nanobot_worker.py`

Two modes:
- **Runner mode** (`in-process-nanobot`): Uses `nanobot.agent.runner.AgentRunner` — bare LLM+tools loop, no sessions/memory, lightweight
- **Loop mode** (`in-process-nanobot-loop`): Uses `nanobot.agent.loop.AgentLoop` — full features (sessions, memory, MCP tools, skills)

Key design:
- Extends `BaseWorker`, implements all 5 abstract methods
- Accepts `nanobot_provider` (nanobot LLM provider instance) via constructor
- No terminal dependency, no MCP client dependency
- Timeout enforced via `asyncio.wait_for()`
- `worker_id` generated as `nanobot_{uuid_hex[:12]}` (avoids the ApplicationWorker bug where worker_id is never set)
- Loop mode creates a fresh `AgentLoop` per execute call (prevents state leakage), cleans up with `close_mcp()`

### B4. Update WorkerManager

**File**: `mahavishnu/workers/manager.py`

1. Add `nanobot_provider: Any = None` to `WorkerManager.__init__()`
2. Add `IN_PROCESS` branch in `_create_worker()`:
```python
elif config.category == WorkerCategory.IN_PROCESS:
    if worker_type.startswith("in-process-nanobot"):
        from .nanobot_worker import NanobotWorker
        return NanobotWorker(
            worker_type=worker_type,
            nanobot_provider=self.nanobot_provider,
            config=config,
            session_buddy_client=self.session_buddy_client,
        )
    raise ValueError(f"Unknown in-process worker: {worker_type}")
```

### B5. Wire provider through app initialization

**File**: `mahavishnu/core/adapters/worker.py` (line 59-64)

Pass `nanobot_provider` when constructing `WorkerManager`:
```python
self.worker_manager = WorkerManager(
    terminal_manager=terminal_mgr,
    max_concurrent=max_concurrent,
    debug_mode=False,
    session_buddy_client=None,
    nanobot_provider=...,  # from config/env
)
```

**File**: `mahavishnu/core/app.py`

Add `_init_nanobot_provider()` method that:
1. Checks for `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` env vars (already set in your environment for z.ai)
2. Creates an `OpenAICompatProvider` from nanobot
3. Stores as `self._nanobot_provider`
4. Logs a warning (not crash) if provider can't be configured

### B6. Update exports

**File**: `mahavishnu/workers/__init__.py`

- Add `from .nanobot_worker import NanobotWorker`
- Add `"NanobotWorker"` to `__all__`
- Update module docstring

### B7. Add nanobot dependency

**File**: `pyproject.toml`

Add to dependencies: `"nanobot>=0.1.4"` (already installed in venv)

---

## Phase C: Optional MCP Tool for External Consumers

**File**: `mahavishnu/mcp/tools/worker_tools.py`

Add `nanobot_run` convenience MCP tool — a one-shot wrapper that:
1. Creates a temporary `NanobotWorker`
2. Executes the task
3. Returns result
4. Cleans up

This lets any MCP client (nanobot, session-buddy, external tools) call nanobot's AI capabilities through Mahavishnu without managing workers.

---

## Verification

### Phase A verification:
```bash
# 1. Start claude mcp serve via supergateway
# Check it's running:
lsof -i :8700
# 2. Test MCP endpoint:
curl -X POST http://localhost:8700/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
# Should return list of Claude Code tools
```

### Phase B verification:
```bash
# 1. Run existing tests
pytest tests/unit/test_workers.py -v

# 2. Test NanobotWorker directly
python -c "
from mahavishnu.workers.nanobot_worker import NanobotWorker
w = NanobotWorker(nanobot_provider=None)  # Should construct without error
print(w.worker_id)
print(w.worker_type)
"

# 3. Test worker creation via registry
python -c "
from mahavishnu.workers.registry import get_worker_config
config = get_worker_config('in-process-nanobot')
print(config.name, config.category)
"
```

### Phase C verification:
```bash
# Test via MCP tool call (if nanobot provider configured)
# Through mahavishnu MCP: nanobot_run(prompt="Hello", mode="runner")
```
