# Mahavishnu Migration Guide

**Version:** 0.1.0
**Last Updated:** 2025-02-05
**Est. Migration Time:** 2-4 hours (depending on project size)

This guide helps you migrate legacy Mahavishnu code to current patterns, covering WorkerManager to Pools, authentication upgrades, async transitions, configuration migration, and dependency updates.

---

## Table of Contents

1. [Quick Start (5-Minute Overview)](#quick-start-5-minute-overview)
2. [Migration Scenarios](#migration-scenarios)
   - [Scenario 1: WorkerManager to Pools](#scenario-1-workermanager-to-pools)
   - [Scenario 2: Local to JWT Authentication](#scenario-2-local-to-jwt-authentication)
   - [Scenario 3: Sync to Async Patterns](#scenario-3-sync-to-async-patterns)
   - [Scenario 4: Configuration Migration](#scenario-4-configuration-migration)
   - [Scenario 5: Dependency Updates](#scenario-5-dependency-updates)
3. [Breaking Changes by Version](#breaking-changes-by-version)
4. [Rollback Procedures](#rollback-procedures)
5. [Troubleshooting](#troubleshooting)
6. [FAQ](#faq)

---

## Quick Start (5-Minute Overview)

### What Changed?

| Area | Old Pattern | New Pattern | Impact |
|------|------------|-------------|---------|
| **Worker Management** | `WorkerManager` with manual worker IDs | `PoolManager` with automatic routing | High |
| **Authentication** | Local-only | JWT tokens with secret validation | Medium |
| **Code Patterns** | Synchronous functions | Async/await everywhere | High |
| **Configuration** | `oneiric.yaml` single file | Layered YAML + env vars | Low |
| **Dependencies** | Unpinned `fastmcp` | Pinned `fastmcp~=2.14.5` | Medium |

### Migration Checklist

```bash
# 1. Update dependencies
uv pip install -e ".[dev]"

# 2. Update configuration files
cp settings/mahavishnu.yaml settings/mahavishnu.yaml.bak
# Edit settings/mahavishnu.yaml with new structure

# 3. Migrate code (see scenarios below)

# 4. Run tests
pytest -xvs

# 5. Verify deployment
mahavishnu mcp health
```

### Expected Effort

- **Small projects** (< 10 files using Mahavishnu): 1-2 hours
- **Medium projects** (10-50 files): 2-4 hours
- **Large projects** (50+ files): 4-8 hours

---

## Migration Scenarios

### Scenario 1: WorkerManager to Pools

**Difficulty:** Medium | **Impact:** High | **Breaking:** Yes

#### Overview

The `WorkerManager` class has been superseded by the `PoolManager` architecture, which provides:
- Automatic worker selection (no manual worker IDs)
- Multiple pool types (local, delegated, Kubernetes)
- Inter-pool communication via message bus
- Memory aggregation across pools

#### Before: WorkerManager Pattern

```python
from mahavishnu.workers import WorkerManager
from mahavishnu.terminal.manager import TerminalManager

# Create managers
terminal_mgr = TerminalManager.create(config, mcp_client=None)
worker_mgr = WorkerManager(
    terminal_manager=terminal_mgr,
    max_concurrent=10,
)

# Manual worker spawning
worker_ids = await worker_mgr.spawn_workers(
    worker_type="terminal-qwen",
    count=3,
)

# Manual worker selection
result = await worker_mgr.execute_task(
    worker_ids[0],  # Must track worker IDs
    {"prompt": "Write code"},
)

# Manual cleanup
await worker_mgr.close_all()
```

#### After: PoolManager Pattern

```python
from mahavishnu.pools import PoolManager, PoolConfig, PoolSelector
from mahavishnu.mcp.protocols.message_bus import MessageBus

# Create managers
terminal_mgr = TerminalManager.create(config, mcp_client=None)
pool_mgr = PoolManager(
    terminal_manager=terminal_mgr,
    session_buddy_client=None,
    message_bus=MessageBus(),
)

# Pool auto-spawns workers
config = PoolConfig(
    name="local-pool",
    pool_type="mahavishnu",
    min_workers=3,
    max_workers=10,
)
pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

# Automatic worker selection
result = await pool_mgr.execute_on_pool(
    pool_id,
    {"prompt": "Write code"},
)

# Or use auto-routing (no pool ID needed)
result = await pool_mgr.route_task(
    {"prompt": "Write code"},
    pool_selector=PoolSelector.LEAST_LOADED,
)

# Cleanup
await pool_mgr.close_all()
```

#### Key Differences

| Aspect | WorkerManager | PoolManager |
|--------|--------------|-------------|
| **Worker IDs** | Manual tracking | Automatic selection |
| **Scaling** | `spawn_workers()` / `close_worker()` | `pool.scale(target_workers)` |
| **Routing** | Manual logic | 4 built-in strategies |
| **Communication** | None | MessageBus for inter-pool |
| **Memory** | Manual Session-Buddy calls | Automatic aggregation |

#### Migration Steps

**Step 1: Update Imports**

```python
# Old imports
from mahavishnu.workers import WorkerManager

# New imports
from mahavishnu.pools import PoolManager, PoolConfig, PoolSelector
from mahavishnu.mcp.protocols.message_bus import MessageBus
```

**Step 2: Replace Initialization**

```python
# Old
worker_mgr = WorkerManager(
    terminal_manager=terminal_mgr,
    max_concurrent=10,
)

# New
pool_mgr = PoolManager(
    terminal_manager=terminal_mgr,
    session_buddy_client=None,
    message_bus=MessageBus(),
)
```

**Step 3: Replace Worker Spawning**

```python
# Old
worker_ids = await worker_mgr.spawn_workers(
    worker_type="terminal-qwen",
    count=3,
)

# New
config = PoolConfig(
    name="local-pool",
    pool_type="mahavishnu",
    min_workers=3,
    max_workers=10,
)
pool_id = await pool_mgr.spawn_pool("mahavishnu", config)
```

**Step 4: Replace Task Execution**

```python
# Old (manual worker selection)
result = await worker_mgr.execute_task(
    worker_ids[0],
    {"prompt": "Write code"},
)

# New (automatic selection)
result = await pool_mgr.execute_on_pool(
    pool_id,
    {"prompt": "Write code"},
)

# Or with auto-routing
result = await pool_mgr.route_task(
    {"prompt": "Write code"},
    pool_selector=PoolSelector.LEAST_LOADED,
)
```

**Step 5: Replace Scaling Logic**

```python
# Old
new_workers = await worker_mgr.spawn_workers("terminal-qwen", 5)
for wid in workers_to_remove:
    await worker_mgr.close_worker(wid)

# New
pool = pool_mgr._pools[pool_id]
await pool.scale(target_workers=10)
```

**Step 6: Update Configuration**

```yaml
# Old: settings/mahavishnu.yaml
workers_enabled: true
max_concurrent_workers: 10
worker_default_type: "terminal-qwen"

# New: settings/mahavishnu.yaml
workers:
  enabled: true
  max_concurrent: 10
  default_type: "terminal-qwen"

pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"
  min_workers: 1
  max_workers: 10
```

#### Common Migration Patterns

**Pattern 1: Single WorkerManager → Single Pool**

```python
# Before
class TaskRunner:
    def __init__(self):
        self.worker_mgr = WorkerManager(terminal_mgr=tm)
        self.workers = []

    async def start(self):
        self.workers = await self.worker_mgr.spawn_workers(
            "terminal-qwen", count=3
        )

    async def execute(self, prompt: str):
        return await self.worker_mgr.execute_task(
            self.workers[0],
            {"prompt": prompt},
        )

# After
class TaskRunner:
    def __init__(self):
        self.pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())
        self.pool_id = None

    async def start(self):
        config = PoolConfig(
            name="task-runner",
            pool_type="mahavishnu",
            min_workers=3,
            max_workers=10,
        )
        self.pool_id = await self.pool_mgr.spawn_pool("mahavishnu", config)

    async def execute(self, prompt: str):
        return await self.pool_mgr.execute_on_pool(
            self.pool_id,
            {"prompt": prompt},
        )
```

**Pattern 2: Multiple WorkerManagers → Pool Manager**

```python
# Before
class MultiTaskExecutor:
    def __init__(self):
        self.primary_workers = WorkerManager(terminal_mgr=tm1, max_concurrent=5)
        self.secondary_workers = WorkerManager(terminal_mgr=tm2, max_concurrent=10)

    async def execute(self, prompt: str, use_primary: bool = True):
        if use_primary:
            return await self.primary_workers.execute_task(
                self.primary_ids[0], {"prompt": prompt}
            )
        else:
            return await self.secondary_workers.execute_task(
                self.secondary_ids[0], {"prompt": prompt}
            )

# After
class MultiTaskExecutor:
    def __init__(self):
        self.pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())

    async def start(self):
        config1 = PoolConfig(name="primary", pool_type="mahavishnu", min_workers=2, max_workers=5)
        await self.pool_mgr.spawn_pool("mahavishnu", config1)

        config2 = PoolConfig(name="secondary", pool_type="mahavishnu", min_workers=5, max_workers=10)
        await self.pool_mgr.spawn_pool("mahavishnu", config2)

    async def execute(self, prompt: str, use_primary: bool = True):
        affinity = "primary" if use_primary else "secondary"
        return await self.pool_mgr.route_task(
            {"prompt": prompt},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity=affinity,
        )
```

#### CLI Command Migration

```bash
# Old CLI
mahavishnu workers spawn --type terminal-qwen --count 3
mahavishnu workers execute --worker-id worker_abc --prompt "Write code"

# New CLI
mahavishnu pool spawn --type mahavishnu --name local --min 3 --max 10
mahavishnu pool execute pool_abc --prompt "Write code"
mahavishnu pool route --prompt "Write code" --selector least_loaded
```

#### MCP Tool Migration

```python
# Old MCP tools
await mcp.call_tool("worker_spawn", {
    "worker_type": "terminal-qwen",
    "count": 3,
})
await mcp.call_tool("worker_execute", {
    "worker_id": "worker_abc",
    "prompt": "Write code",
})

# New MCP tools
await mcp.call_tool("pool_spawn", {
    "pool_type": "mahavishnu",
    "name": "local",
    "min_workers": 3,
    "max_workers": 10,
})
await mcp.call_tool("pool_execute", {
    "pool_id": "pool_abc",
    "prompt": "Write code",
})
# Or with auto-routing
await mcp.call_tool("pool_route_execute", {
    "prompt": "Write code",
    "pool_selector": "least_loaded",
})
```

#### Backward Compatibility

The old `WorkerManager` is still available but deprecated. You can temporarily disable pools:

```yaml
# settings/mahavishnu.yaml
pools:
  enabled: false  # Use legacy WorkerManager

workers:
  enabled: true
```

```python
# Legacy code still works
from mahavishnu.workers import WorkerManager
worker_mgr = WorkerManager(terminal_manager=tm)
```

---

### Scenario 2: Local to JWT Authentication

**Difficulty:** Low | **Impact:** Medium | **Breaking:** No (opt-in)

#### Overview

Mahavishnu now supports JWT-based authentication for production deployments. Local development can continue without authentication.

#### Before: Local-Only Authentication

```yaml
# settings/mahavishnu.yaml (old)
server_name: "Mahavishnu Local"
# No auth section
```

```python
# No authentication in code
app = MahavishnuApp()
```

#### After: JWT Authentication

**Step 1: Generate Secret Key**

```bash
# Generate secure secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Output example: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

**Step 2: Configure JWT**

```yaml
# settings/mahavishnu.yaml (new)
server_name: "Mahavishnu Production"

auth:
  enabled: true
  secret: "${MAHAVISHNU_AUTH__SECRET}"  # Set via environment
  algorithm: "HS256"
  expire_minutes: 60
```

**Step 3: Set Environment Variable**

```bash
# Never commit secrets to git!
export MAHAVISHNU_AUTH__SECRET="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"

# Or use a secret manager
export MAHAVISHNU_AUTH__SECRET="$(vault get -field=secret mahavishnu/jwt)"
```

**Step 4: Update Code (if using custom auth)**

```python
# Old: No auth
from mahavishnu.core.app import MahavishnuApp
app = MahavishnuApp()

# New: With auth validation
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings

settings = MahavishnuSettings()
if settings.auth.enabled:
    # Validate JWT secret is set
    if not settings.auth.secret:
        raise ValueError("MAHAVISHNU_AUTH__SECRET must be set when auth is enabled")

app = MahavishnuApp(settings=settings)
```

#### JWT Token Validation

```python
from mahavishnu.core.auth import validate_jwt_token, create_jwt_token

# Create token (for testing)
token = create_jwt_token(
    user_id="user@example.com",
    secret=settings.auth.secret,
    algorithm=settings.auth.algorithm,
    expire_minutes=settings.auth.expire_minutes,
)

# Validate token
try:
    payload = validate_jwt_token(
        token=token,
        secret=settings.auth.secret,
        algorithm=settings.auth.algorithm,
    )
    print(f"Valid token for user: {payload['user_id']}")
except ValueError as e:
    print(f"Invalid token: {e}")
```

#### Subscription-Based Authentication (Optional)

For Claude Code or subscription-based access:

```yaml
# settings/mahavishnu.yaml
subscription_auth:
  enabled: true
  secret: "${MAHAVISHNU_SUBSCRIPTION_AUTH__SECRET}"
  algorithm: "HS256"
  expire_minutes: 60
```

```bash
export MAHAVISHNU_SUBSCRIPTION_AUTH__SECRET="your-subscription-secret"
```

#### Authentication Migration Checklist

- [ ] Generate JWT secret key
- [ ] Set `MAHAVISHNU_AUTH__SECRET` environment variable
- [ ] Update `settings/mahavishnu.yaml` with auth config
- [ ] Add auth validation to startup code
- [ ] Test with valid JWT token
- [ ] Test with invalid JWT token (should reject)
- [ ] Document secret rotation procedure

---

### Scenario 3: Sync to Async Patterns

**Difficulty:** High | **Impact:** High | **Breaking:** Yes

#### Overview

Mahavishnu now uses `async/await` throughout for better concurrency. All I/O operations (MCP calls, pool operations, config loading) are async.

#### Before: Synchronous Code

```python
from mahavishnu.workers import WorkerManager

class TaskExecutor:
    def __init__(self):
        self.worker_mgr = WorkerManager(terminal_mgr=tm)

    def execute_task(self, prompt: str):
        # Synchronous execution
        worker_id = self.worker_mgr.spawn_workers("terminal-qwen", 1)[0]
        result = self.worker_mgr.execute_task(worker_id, {"prompt": prompt})
        return result

# Usage
executor = TaskExecutor()
result = executor.execute_task("Write code")
```

#### After: Asynchronous Code

```python
from mahavishnu.pools import PoolManager

class TaskExecutor:
    def __init__(self):
        self.pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())

    async def execute_task(self, prompt: str):
        # Asynchronous execution
        config = PoolConfig(name="executor", pool_type="mahavishnu", min_workers=1)
        pool_id = await self.pool_mgr.spawn_pool("mahavishnu", config)
        result = await self.pool_mgr.execute_on_pool(pool_id, {"prompt": prompt})
        return result

# Usage
async def main():
    executor = TaskExecutor()
    result = await executor.execute_task("Write code")
    return result

# Run async code
import asyncio
result = asyncio.run(main())
```

#### Migration Patterns

**Pattern 1: Function Migration**

```python
# Before (sync)
def process_task(task: dict) -> dict:
    result = worker_mgr.execute_task(worker_id, task)
    return result

# After (async)
async def process_task(task: dict) -> dict:
    result = await pool_mgr.execute_on_pool(pool_id, task)
    return result
```

**Pattern 2: Class Migration**

```python
# Before (sync)
class DataProcessor:
    def __init__(self):
        self.worker_mgr = WorkerManager(terminal_mgr=tm)

    def process(self, data: list) -> list:
        results = []
        for item in data:
            result = self.worker_mgr.execute_task(worker_id, item)
            results.append(result)
        return results

# After (async)
class DataProcessor:
    def __init__(self):
        self.pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())

    async def process(self, data: list) -> list:
        results = []
        for item in data:
            result = await self.pool_mgr.execute_on_pool(pool_id, item)
            results.append(result)
        return results
```

**Pattern 3: Batch Processing**

```python
# Before (sync)
def process_batch(tasks: list[dict]) -> list[dict]:
    results = []
    for task in tasks:
        result = worker_mgr.execute_task(worker_id, task)
        results.append(result)
    return results

# After (async with concurrent execution)
async def process_batch(tasks: list[dict]) -> list[dict]:
    # Execute tasks concurrently
    import asyncio

    coroutines = [
        pool_mgr.execute_on_pool(pool_id, task)
        for task in tasks
    ]
    results = await asyncio.gather(*coroutines)
    return results
```

**Pattern 4: Context Managers**

```python
# Before (sync)
from contextlib import contextmanager

@contextmanager
def worker_context():
    worker_mgr = WorkerManager(terminal_mgr=tm)
    try:
        yield worker_mgr
    finally:
        worker_mgr.close_all()

# Usage
with worker_context() as mgr:
    result = mgr.execute_task(worker_id, task)

# After (async)
from contextlib import asynccontextmanager

@asynccontextmanager
async def pool_context():
    pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())
    try:
        yield pool_mgr
    finally:
        await pool_mgr.close_all()

# Usage
async with pool_context() as mgr:
    result = await mgr.execute_on_pool(pool_id, task)
```

#### Testing Migration

```python
# Before (sync tests)
def test_task_execution():
    executor = TaskExecutor()
    result = executor.execute_task({"prompt": "Test"})
    assert result["status"] == "completed"

# After (async tests)
import pytest

@pytest.mark.asyncio
async def test_task_execution():
    executor = TaskExecutor()
    result = await executor.execute_task({"prompt": "Test"})
    assert result["status"] == "completed"
```

#### CLI Migration

```python
# Before (sync CLI)
import typer

app = typer.Typer()

@app.command()
def execute(prompt: str):
    result = worker_mgr.execute_task(worker_id, {"prompt": prompt})
    print(result)

# After (async CLI)
import typer

app = typer.Typer()

@app.command()
def execute(prompt: str):
    async def _execute():
        result = await pool_mgr.execute_on_pool(pool_id, {"prompt": prompt})
        print(result)

    import asyncio
    asyncio.run(_execute())
```

#### Common Async Pitfalls

**Pitfall 1: Forgetting `await`**

```python
# Wrong
result = pool_mgr.execute_on_pool(pool_id, task)  # Returns coroutine

# Correct
result = await pool_mgr.execute_on_pool(pool_id, task)
```

**Pitfall 2: Mixing Sync and Async**

```python
# Wrong
def sync_function():
    async_call()  # Can't await in sync function

# Correct
async def async_function():
    await async_call()

# Or use asyncio.run
def sync_function():
    asyncio.run(async_function())
```

**Pitfall 3: Not Using `asyncio.gather`**

```python
# Wrong (sequential execution)
async def process_many(items):
    results = []
    for item in items:
        result = await process_item(item)
        results.append(result)
    return results

# Correct (concurrent execution)
async def process_many(items):
    coroutines = [process_item(item) for item in items]
    results = await asyncio.gather(*coroutines)
    return results
```

---

### Scenario 4: Configuration Migration

**Difficulty:** Low | **Impact:** Low | **Breaking:** No

#### Overview

Configuration has moved from a single `oneiric.yaml` file to a layered system with `settings/mahavishnu.yaml` + `settings/local.yaml` + environment variables.

#### Before: Single Configuration File

```yaml
# oneiric.yaml (legacy)
server_name: "Mahavishnu"
log_level: "INFO"
pools_enabled: true
max_concurrent_workers: 10
otel_storage_connection_string: "postgresql://..."
```

#### After: Layered Configuration

**File 1: settings/mahavishnu.yaml (committed)**

```yaml
# settings/mahavishnu.yaml
server_name: "Mahavishnu Orchestrator"
log_level: "INFO"

pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"
  min_workers: 1
  max_workers: 10

otel_storage:
  enabled: true
  # Connection string set via environment
```

**File 2: settings/local.yaml (gitignored)**

```yaml
# settings/local.yaml (gitignored)
pools:
  min_workers: 2  # Local override

otel_storage:
  connection_string: "postgresql://dev:dev@localhost/mahavishnu"
```

**File 3: Environment Variables (runtime)**

```bash
# Production overrides
export MAHAVISHNU_POOLS__MAX_WORKERS="50"
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://prod:secret@host/db"
```

#### Configuration Loading Order

```
1. Pydantic defaults (lowest priority)
2. settings/mahavishnu.yaml (committed)
3. settings/local.yaml (gitignored)
4. Environment variables MAHAVISHNU_{GROUP}__{FIELD} (highest priority)
```

#### Migration Steps

**Step 1: Create New Configuration Structure**

```bash
# Create settings directory
mkdir -p settings

# Create local.yaml (gitignored)
cat > settings/local.yaml << 'EOF'
# Local development overrides
# This file is gitignored
EOF

# Add to .gitignore
echo "settings/local.yaml" >> .gitignore
```

**Step 2: Convert Configuration**

```python
# Old: Flat configuration
# oneiric.yaml
pools_enabled: true
max_concurrent_workers: 10
worker_default_type: "terminal-qwen"

# New: Nested configuration
# settings/mahavishnu.yaml
pools:
  enabled: true
  max_workers: 10
  default_type: "terminal-qwen"

workers:
  enabled: true
  default_type: "terminal-qwen"
```

**Step 3: Update Environment Variables**

```bash
# Old format (no nesting)
export MAHAVISHNU_POOLS_ENABLED="true"
export MAHAVISHNU_MAX_CONCURRENT_WORKERS="10"

# New format (nested with __)
export MAHAVISHNU_POOLS__ENABLED="true"
export MAHAVISHNU_POOLS__MAX_WORKERS="10"
```

**Step 4: Update Code References**

```python
# Old: Flat access
from oneiric.config import Config
config = Config()
pools_enabled = config.get("pools_enabled")

# New: Nested access
from mahavishnu.core.config import MahavishnuSettings
settings = MahavishnuSettings()
pools_enabled = settings.pools.enabled
```

#### Configuration Validation

```python
# New: Pydantic validation
from pydantic import ValidationError

try:
    settings = MahavishnuSettings(
        pools=PoolConfig(
            enabled=True,
            min_workers=5,
            max_workers=3,  # Invalid! max < min
        )
    )
except ValidationError as e:
    print(f"Configuration error: {e}")
```

#### Migration Script

```python
#!/usr/bin/env python3
"""Migrate oneiric.yaml to settings/mahavishnu.yaml"""

import yaml
from pathlib import Path

def migrate_config(old_file: Path, new_file: Path):
    """Migrate old config to new structure."""
    # Load old config
    with open(old_file) as f:
        old_config = yaml.safe_load(f)

    # Transform to new structure
    new_config = {
        "server_name": old_config.get("server_name", "Mahavishnu"),
        "log_level": old_config.get("log_level", "INFO"),
        "pools": {
            "enabled": old_config.get("pools_enabled", False),
            "max_workers": old_config.get("max_concurrent_workers", 10),
        },
        "otel_storage": {
            "enabled": old_config.get("otel_storage_enabled", False),
            "connection_string": old_config.get("otel_storage_connection_string", ""),
        },
    }

    # Write new config
    with open(new_file, "w") as f:
        yaml.dump(new_config, f, default_flow_style=False)

    print(f"Migrated {old_file} -> {new_file}")

if __name__ == "__main__":
    migrate_config(Path("oneiric.yaml"), Path("settings/mahavishnu.yaml"))
```

---

### Scenario 5: Dependency Updates

**Difficulty:** Medium | **Impact:** Medium | **Breaking:** Yes

#### Overview

Key dependency changes:
- `fastmcp` now pinned to `~=2.14.5` (was unpinned `>=0.2.0`)
- `httpx` conflict resolved (fastmcp requires `>=0.28.1`)
- `pydantic` upgraded to `>=2.12.5`

#### FastMCP Pinning

**Why?**

FastMCP 3.0.0b1 was beta and had breaking changes. Version 2.14.5 is the latest stable release.

**Before: Unpinned FastMCP**

```toml
# pyproject.toml (old)
dependencies = [
    "fastmcp>=0.2.0",  # Could install 3.0.0b1 (breaking)
]
```

**After: Pinned FastMCP**

```toml
# pyproject.toml (new)
dependencies = [
    "fastmcp~=2.14.5",  # Stable 2.x series only
]
```

#### httpx Version Conflict

**The Problem:**

- `fastmcp~=2.14.5` requires `httpx>=0.28.1`
- `llama-index-embeddings-ollama` requires `httpx<0.28.0`

**Solutions:**

**Option 1: Disable LlamaIndex (Recommended for now)**

```toml
# pyproject.toml
# Note: llamaindex extras disabled due to httpx version conflict
# Install separately with: uv sync --extra llamaindex
# rag = [  # Disabled
#     "llama-index-core>=0.12.0,<0.13.0",
#     "llama-index-embeddings-ollama>=0.4.0,<0.5.0",
# ]
```

**Option 2: Use Ollama Directly**

```python
# Instead of llama-index-embeddings-ollama, use Ollama directly
import httpx

async def get_embedding(text: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:11434/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
        )
        return response.json()["embedding"]
```

**Option 3: Wait for Upstream Fix**

Monitor:
- FastMCP releases: https://pypi.org/project/fastmcp/
- LlamaIndex releases: https://pypi.org/project/llama-index-embeddings-ollama/

#### Migration Steps

**Step 1: Update pyproject.toml**

```bash
# Backup old pyproject.toml
cp pyproject.toml pyproject.toml.bak

# Update dependencies (already done in repository)
# Just verify fastmcp is pinned:
grep fastmcp pyproject.toml

# Expected output:
# "fastmcp~=2.14.5",
```

**Step 2: Clean and Reinstall**

```bash
# Remove old virtual environment
rm -rf .venv

# Create new environment
uv venv
source .venv/bin/activate

# Install with pinned dependencies
uv pip install -e ".[dev]"

# Verify versions
pip list | grep fastmcp
# Expected: fastmcp          2.14.5

pip list | grep httpx
# Expected: httpx            0.28.1
```

**Step 3: Run Tests**

```bash
# Run full test suite
pytest -xvs

# Run specific integration tests
pytest tests/integration/ -k "mcp"
```

**Step 4: Verify MCP Server**

```bash
# Start MCP server
mahavishnu mcp start

# Check health
mahavishnu mcp health

# Expected output:
# Mahavishnu MCP Server: healthy
```

#### Breaking Changes Summary

| Package | Old Version | New Version | Breaking Change |
|---------|-------------|-------------|-----------------|
| `fastmcp` | `>=0.2.0` | `~=2.14.5` | Pinned to 2.x series |
| `httpx` | `>=0.27.0` | `>=0.28.1` | Minor version bump |
| `llama-index-*` | Enabled | Disabled | httpx conflict |
| `pydantic` | `>=2.0.0` | `>=2.12.5` | New validation features |

#### Rollback if Needed

If dependency updates cause issues:

```bash
# Restore old pyproject.toml
cp pyproject.toml.bak pyproject.toml

# Reinstall old versions
uv pip install -e ".[dev]"

# Verify
pip list | grep fastmcp
```

---

## Breaking Changes by Version

### Version 0.1.0 (Current)

#### WorkerManager Deprecation

- **Change**: `WorkerManager` deprecated in favor of `PoolManager`
- **Impact**: High - requires code changes for worker management
- **Migration**: See [Scenario 1](#scenario-1-workermanager-to-pools)
- **Grace Period**: WorkerManager still works but emits deprecation warnings

#### FastMCP Pinning

- **Change**: `fastmcp` pinned to `~=2.14.5`
- **Impact**: Medium - prevents automatic upgrade to 3.x
- **Migration**: Update `pyproject.toml` and reinstall
- **Breaking**: Yes - 3.x has API changes

#### Async-Only API

- **Change**: All I/O operations now async
- **Impact**: High - requires wrapping sync code in async
- **Migration**: See [Scenario 3](#scenario-3-sync-to-async-patterns)
- **Breaking**: Yes - sync wrappers removed

#### Configuration Structure

- **Change**: Nested configuration with `settings/mahavishnu.yaml`
- **Impact**: Low - mostly additive changes
- **Migration**: See [Scenario 4](#scenario-4-configuration-migration)
- **Breaking**: No - old `oneiric.yaml` still supported

### Future Breaking Changes (Planned)

#### Version 0.2.0 (Planned)

- **WorkerManager Removal**: Complete removal of deprecated `WorkerManager`
- **LlamaIndex Re-enabling**: Fix httpx conflict and re-enable RAG extras
- **Auth Default Change**: JWT auth enabled by default for production

---

## Rollback Procedures

### Quick Rollback (5 minutes)

If migration causes immediate issues:

```bash
# 1. Stop Mahavishnu
mahavishnu mcp stop

# 2. Restore previous configuration
cp settings/mahavishnu.yaml.bak settings/mahavishnu.yaml

# 3. Revert code changes
git checkout HEAD -- mahavishnu/

# 4. Reinstall dependencies
uv pip install -e ".[dev]"

# 5. Restart
mahavishnu mcp start
```

### Full Rollback (30 minutes)

If migration requires complete reversion:

#### Step 1: Disable New Features

```yaml
# settings/mahavishnu.yaml
pools:
  enabled: false  # Disable PoolManager

workers:
  enabled: true   # Use WorkerManager
```

#### Step 2: Restore Old Code Pattern

```python
# Revert to WorkerManager
from mahavishnu.workers import WorkerManager

worker_mgr = WorkerManager(terminal_manager=tm)
worker_ids = await worker_mgr.spawn_workers("terminal-qwen", 3)
result = await worker_mgr.execute_task(worker_ids[0], task)
```

#### Step 3: Restore Old Dependencies

```bash
# Revert pyproject.toml
git checkout HEAD~1 -- pyproject.toml

# Reinstall
uv pip install -e ".[dev]"
```

#### Step 4: Verify Rollback

```bash
# Run tests
pytest -xvs

# Check MCP server
mahavishnu mcp health

# Verify worker execution
mahavishnu workers execute --prompt "Test"
```

### Partial Rollback (Specific Scenarios)

#### Rollback Pool Manager Only

```yaml
# Disable pools
pools:
  enabled: false

# Keep workers enabled
workers:
  enabled: true
```

```python
# Use WorkerManager directly
from mahavishnu.workers import WorkerManager
# Legacy code works
```

#### Rollback Authentication Only

```yaml
# Disable JWT
auth:
  enabled: false
```

```bash
# Unset environment variable
unset MAHAVISHNU_AUTH__SECRET
```

#### Rollback Async Changes Only

```python
# Use sync wrapper
def sync_execute(pool_mgr, pool_id, task):
    import asyncio
    return asyncio.run(pool_mgr.execute_on_pool(pool_id, task))

# Usage
result = sync_execute(pool_mgr, pool_id, task)
```

---

## Troubleshooting

### Issue 1: Import Errors After Migration

**Symptom:**

```python
ModuleNotFoundError: No module named 'mahavishnu.workers'
```

**Solution:**

```bash
# Reinstall dependencies
uv pip install -e ".[dev]"

# Verify installation
pip list | grep mahavishnu
```

### Issue 2: Pool Not Starting

**Symptom:**

```python
PoolInitializationError: Failed to initialize pool 'local-pool'
```

**Solution:**

```bash
# Check configuration
mahavishnu config get pools.enabled

# Check pool manager health
mahavishnu pool health

# View logs
tail -f /tmp/mahavishnu.log
```

### Issue 3: Authentication Failing

**Symptom:**

```python
ValidationError: secret must be set via MAHAVISHNU_AUTH__SECRET
```

**Solution:**

```bash
# Set secret
export MAHAVISHNU_AUTH__SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Verify
mahavishnu config get auth.secret
```

### Issue 4: Async/Await Errors

**Symptom:**

```python
SyntaxError: 'await' outside async function
```

**Solution:**

```python
# Wrap in async function
async def main():
    result = await pool_mgr.execute_on_pool(pool_id, task)
    return result

# Run with asyncio
import asyncio
result = asyncio.run(main())
```

### Issue 5: Configuration Not Loading

**Symptom:**

```python
ConfigurationError: settings/mahavishnu.yaml not found
```

**Solution:**

```bash
# Create settings directory
mkdir -p settings

# Generate default config
mahavishnu config init

# Validate
mahavishnu config validate
```

### Issue 6: Dependency Conflicts

**Symptom:**

```bash
ERROR: ResolutionImpossible: for dependencies
```

**Solution:**

```bash
# Clean install
rm -rf .venv
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Check for conflicts
pip check
```

### Issue 7: MCP Server Not Starting

**Symptom:**

```bash
Error: Mahavishnu MCP server failed to start
```

**Solution:**

```bash
# Check port availability
lsof -i :8680

# Kill existing process
kill $(lsof -t -i:8680)

# Restart
mahavishnu mcp start

# Check health
mahavishnu mcp health
```

### Issue 8: Tests Failing After Migration

**Symptom:**

```bash
FAILED test_pools.py - test_pool_execution
```

**Solution:**

```bash
# Run with verbose output
pytest -xvs tests/unit/test_pools.py

# Check for async issues
pytest -xvs --asyncio-mode=auto

# Run specific test
pytest -xvs -k "test_pool_execution"
```

---

## FAQ

### Q: Is WorkerManager being removed?

**A:** No, `WorkerManager` is deprecated but still functional. It will be removed in version 0.2.0 (planned). We recommend migrating to `PoolManager` now to avoid breaking changes later.

### Q: Can I use PoolManager and WorkerManager together?

**A:** Yes, but not recommended. They manage separate worker pools and can lead to resource conflicts. Choose one pattern for your application.

### Q: Do I need to enable JWT authentication?

**A:** No, JWT authentication is opt-in (`enabled: false` by default). Only enable it for production deployments or when serving requests over a network.

### Q: How do I generate a secure JWT secret?

**A:** Use Python's `secrets` module:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Q: Can I migrate incrementally?

**A:** Yes! Each migration scenario is independent:
1. Migrate WorkerManager → PoolManager ( Scenario 1)
2. Enable JWT auth (Scenario 2)
3. Convert sync → async (Scenario 3)
4. Update configuration (Scenario 4)
5. Update dependencies (Scenario 5)

### Q: What if I have custom worker types?

**A:** Custom worker types still work with PoolManager. Just specify the `worker_type` in `PoolConfig`:

```python
config = PoolConfig(
    name="custom-pool",
    pool_type="mahavishnu",
    worker_type="my-custom-worker",  # Custom type
    min_workers=2,
)
```

### Q: How do I monitor pool performance?

**A:** Use the built-in monitoring tools:

```bash
# Pool health
mahavishnu pool health

# Pool metrics
mahavishnu pool monitor

# Memory aggregation
mahavishnu pool search-memory --query "API"
```

### Q: Can I use environment variables for all configuration?

**A:** Yes! Use the `MAHAVISHNU_{GROUP}__{FIELD}` format:

```bash
export MAHAVISHNU_POOLS__ENABLED="true"
export MAHAVISHNU_POOLS__MIN_WORKERS="5"
export MAHAVISHNU_AUTH__SECRET="your-secret"
```

### Q: What's the performance impact of pools?

**A**: Pools add ~5ms overhead per operation but provide:
- Automatic routing
- Inter-pool communication
- Memory aggregation
- Better scalability (10,000+ workers vs 100 with WorkerManager)

### Q: How do I rollback if migration fails?

**A:** See [Rollback Procedures](#rollback-procedures). Quick rollback:

```bash
# 1. Disable pools
mahavishnu config set pools.enabled false --save

# 2. Restart
mahavishnu mcp restart

# 3. Verify
mahavishnu workers execute --prompt "Test"
```

### Q: Where can I get help?

**A:**
- Review [POOL_ARCHITECTURE.md](POOL_ARCHITECTURE.md)
- Check [POOL_MIGRATION.md](POOL_MIGRATION.md) for pool-specific migration
- Run tests: `pytest -xvs`
- View logs: `tail -f /tmp/mahavishnu.log`
- Open an issue on GitHub

---

## Additional Resources

- [Pool Architecture](POOL_ARCHITECTURE.md) - Complete pool system documentation
- [Pool Migration](POOL_MIGRATION.md) - WorkerManager to Pools deep dive
- [Configuration Management](CONFIGURATION_MANAGEMENT_GUIDE.md) - Configuration best practices
- [ADR 004: Adapter Architecture](adr/004-adapter-architecture.md) - Architecture decisions
- [Pytest Asyncio](https://pytest-asyncio.readthedocs.io/) - Async testing patterns

---

**Document Version:** 1.0.0
**Last Updated:** 2025-02-05
**Authors:** Mahavishnu Development Team
**License:** MIT
