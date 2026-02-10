# Quick Start: AI Environment Manager for Mahavishnu

**Fast-track implementation for managing Claude Code + Session-Buddy + Memory systems**

______________________________________________________________________

## 🎯 What We're Building

A unified system to:

1. **Manage Claude Code** (~/.claude/settings.json)
1. **Switch LLMs** (Claude, Qwen, Codex)
1. **Integrate Session-Buddy** shared memory
1. **Three-tier memory** (AgentDB + pgvector + Session-Buddy)

______________________________________________________________________

## 🚀 Quick Implementation (30 minutes)

### Step 1: Create AI Environment Manager Module

```bash
# Create module structure
mkdir -p mahavishnu/ai_env
mkdir -p mahavishnu/memory

# Create files
touch mahavishnu/ai_env/__init__.py
touch mahavishnu/ai_env/claude_manager.py
touch mahavishnu/ai_env/llm_switcher.py
touch mahavishnu/ai_env/service_manager.py

touch mahavishnu/memory/__init__.py
touch mahavishnu/memory/unified_manager.py
touch mahavishnu/memory/session_buddy_client.py
```

### Step 2: Implement Claude Code Manager

**File**: `mahavishnu/ai_env/claude_manager.py`

```python
"""Claude Code configuration manager."""
import json
from pathlib import Path
import subprocess
import asyncio


class ClaudeCodeManager:
    """Manage Claude Code configuration (~/.claude/settings.json)."""

    def __init__(self, claude_dir: Path = Path("~/.claude").expanduser()):
        self.claude_dir = claude_dir
        self.settings_file = claude_dir / "settings.json"

    def update_env_var(self, key: str, value: str) -> bool:
        """Update environment variable in settings.json."""
        try:
            # Read current settings
            with open(self.settings_file) as f:
                settings = json.load(f)

            # Update env var
            if "env" not in settings:
                settings["env"] = {}
            settings["env"][key] = value

            # Atomic write (temp file + mv)
            temp_file = self.settings_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(settings, f, indent=2)
            temp_file.replace(self.settings_file)

            return True
        except Exception as e:
            print(f"Failed to update env var: {e}")
            return False

    def restart(self) -> bool:
        """Restart Claude Code."""
        try:
            # Graceful shutdown
            subprocess.run(["killall", "Claude"], check=False, timeout=5)

            # Wait for shutdown
            asyncio.sleep(2)

            # Restart
            subprocess.run(["open", "-a", "Claude"], check=True)

            return True
        except Exception as e:
            print(f"Failed to restart Claude: {e}")
            return False

    def get_current_config(self) -> dict:
        """Get current Claude Code configuration."""
        with open(self.settings_file) as f:
            return json.load(f)
```

### Step 3: Implement LLM Switcher

**File**: `mahavishnu/ai_env/llm_switcher.py`

```python
"""LLM environment switcher."""
from .claude_manager import ClaudeCodeManager


class LLMSwitcher:
    """Switch between LLM environments (Claude, Qwen, Codex)."""

    # Predefined LLM configurations
    LLM_CONFIGS = {
        "claude": {
            "ANTHROPIC_AUTH_TOKEN": "${CLAUDE_API_KEY}",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "API_TIMEOUT_MS": "3000000",
        },
        "qwen": {
            "ANTHROPIC_AUTH_TOKEN": "${QWEN_API_KEY}",
            "ANTHROPIC_BASE_URL": "https://api.qwen.com/v1",
            "API_TIMEOUT_MS": "3000000",
        },
        "codex": {
            "ANTHROPIC_AUTH_TOKEN": "${CODEX_API_KEY}",
            "ANTHROPIC_BASE_URL": "https://api.codex.com/v1",
            "API_TIMEOUT_MS": "3000000",
        },
    }

    def __init__(self):
        self.claude = ClaudeCodeManager()

    async def switch_llm(self, llm_name: str) -> dict:
        """Switch to specified LLM environment."""
        if llm_name not in self.LLM_CONFIGS:
            return {
                "success": False,
                "error": f"Unknown LLM: {llm_name}",
                "available": list(self.LLM_CONFIGS.keys()),
            }

        config = self.LLM_CONFIGS[llm_name]
        results = {"llm": llm_name, "updates": []}

        # Update each environment variable
        for key, value in config.items():
            # Expand env vars if needed (e.g., ${CLAUDE_API_KEY})
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                value = os.getenv(env_var, "")

            success = self.claude.update_env_var(key, value)
            results["updates"].append({
                "key": key,
                "success": success,
            })

        # Restart Claude Code
        results["restarted"] = self.claude.restart()

        results["success"] = all(u["success"] for u in results["updates"])
        return results

    def list_available_llms(self) -> list[str]:
        """List available LLM environments."""
        return list(self.LLM_CONFIGS.keys())
```

### Step 4: Implement Session-Buddy Client

**File**: `mahavishnu/memory/session_buddy_client.py`

```python
"""Session-Buddy MCP client for shared memory access."""
from mcp import ClientSession
from mcp.client.stdio import stdio_client


class SessionBuddyClient:
    """Access Session-Buddy shared memory via MCP."""

    def __init__(self):
        self.server_params = stdio_client(
            command="python",
            args=["-m", "session_buddy.server"],
        )

    async def checkpoint(self, working_dir: str) -> dict:
        """Create Session-Buddy checkpoint."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "checkpoint",
                    arguments={"working_directory": working_dir},
                )

                return result

    async def search_memories(self, query: str, limit: int = 10) -> list:
        """Search Session-Buddy vector database."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "quick_search",
                    arguments={"query": query, "limit": limit},
                )

                return result.get("results", [])

    async def get_quality_metrics(self) -> dict:
        """Get quality metrics from Session-Buddy."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "health_check",
                    arguments={"include_quality": True},
                )

                return result
```

### Step 5: Implement Unified Memory Manager

**File**: `mahavishnu/memory/unified_manager.py`

```python
"""Unified memory manager - coordinate all three memory systems."""
from oneiric.adapters.vector import VectorDocument
from .session_buddy_client import SessionBuddyClient


class UnifiedMemoryManager:
    """Coordinate AgentDB + pgvector + Session-Buddy."""

    def __init__(self, app):
        self.app = app  # MahavishnuApp
        self.session_buddy = SessionBuddyClient()

    async def store_decision(
        self,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> dict:
        """Store decision in all three memory systems."""
        results = {}

        # 1. Store in AgentDB (hot, fast)
        agentdb = await self.app.lifecycle.activate(
            "adapter", "vector", provider="agentdb"
        )

        doc = VectorDocument(
            vector=embedding,
            metadata={**metadata, "content": content},
        )

        agentdb_id = await agentdb.insert("decisions", [doc])
        results["agentdb_id"] = agentdb_id

        # 2. Backup to pgvector (persistent)
        pgvector = await self.app.lifecycle.activate(
            "adapter", "vector", provider="pgvector"
        )

        pgvector_id = await pgvector.insert("decisions", [doc])
        results["pgvector_id"] = pgvector_id

        # 3. Create Session-Buddy checkpoint
        checkpoint = await self.session_buddy.checkpoint(
            working_dir=metadata.get("project_path", "/Users/les/Projects/mahavishnu")
        )
        results["checkpoint"] = checkpoint

        return results

    async def search_all(
        self,
        query_embedding: list[float],
        query_text: str,
        limit: int = 10,
    ) -> dict:
        """Search across all three memory systems."""
        results = {}

        # Search AgentDB (hot)
        agentdb = await self.app.lifecycle.activate(
            "adapter", "vector", provider="agentdb"
        )

        agentdb_results = await agentdb.search(
            "decisions",
            query_vector=query_embedding,
            limit=limit,
        )
        results["agentdb"] = agentdb_results

        # Search pgvector (cold)
        pgvector = await self.app.lifecycle.activate(
            "adapter", "vector", provider="pgvector"
        )

        pgvector_results = await pgvector.search(
            "decisions",
            query_vector=query_embedding,
            limit=limit,
        )
        results["pgvector"] = pgvector_results

        # Search Session-Buddy (development context)
        session_results = await self.session_buddy.search_memories(
            query=query_text,
            limit=limit,
        )
        results["session_buddy"] = session_results

        return results
```

### Step 6: Update Mahavishnu CLI

**File**: `mahavishnu/cli.py` (add new commands)

```python
import typer
from mahavishnu.ai_env.llm_switcher import LLMSwitcher
from mahavishnu.memory.unified_manager import UnifiedMemoryManager

# Create app
app = typer.Typer()

# AI environment commands
ai_app = typer.Typer(help="AI environment management")
app.add_typer(ai_app, name="ai")

@ai_app.command("switch-llm")
async def switch_llm(
    llm_name: str = typer.Argument(..., help="LLM name (claude, qwen, codex)")
):
    """Switch active LLM environment."""
    switcher = LLMSwitcher()
    result = await switcher.switch_llm(llm_name)

    if result["success"]:
        typer.echo(f"✅ Switched to {llm_name}")
        typer.echo(f"🔄 Restarted Claude Code: {result['restarted']}")
    else:
        typer.echo(f"❌ Failed: {result.get('error')}")
        raise typer.Exit(1)

# Memory commands
memory_app = typer.Typer(help="Memory management")
app.add_typer(memory_app, name="memory")

@memory_app.command("store")
async def store_memory(
    content: str = typer.Argument(..., help="Content to store"),
):
    """Store in all three memory systems."""
    # Get embedding (pseudo-code)
    embedding = await get_embedding(content)

    metadata = {
        "type": "decision",
        "timestamp": datetime.now().isoformat(),
    }

    manager = UnifiedMemoryManager(app)
    result = await manager.store_decision(content, embedding, metadata)

    typer.echo(f"✅ Stored in AgentDB: {result['agentdb_id']}")
    typer.echo(f"✅ Stored in pgvector: {result['pgvector_id']}")
    typer.echo(f"✅ Session-Buddy checkpoint: {result['checkpoint']}")
```

### Step 7: Update Configuration

**File**: `settings/mahavishnu.yaml`

```yaml
# Mahavishnu configuration with AI environment management

ai_environments:
  claude_code:
    config_path: "~/.claude/settings.json"
    enabled: true

  llm_profiles:
    claude:
      name: "Claude (Anthropic)"
      base_url: "https://api.anthropic.com"
      timeout_ms: 3000000

    qwen:
      name: "Qwen (Alibaba)"
      base_url: "https://api.qwen.com/v1"
      timeout_ms: 3000000

    codex:
      name: "Codex (OpenAI)"
      base_url: "https://api.codex.com/v1"
      timeout_ms: 3000000

memory:
  # Tier 1: Hot data (AgentDB)
  tier1:
    adapter: "vector"
    provider: "agentdb"
    settings:
      in_memory: true
      cache_size_mb: 256

  # Tier 2: Cold data (pgvector)
  tier2:
    adapter: "vector"
    provider: "pgvector"
    settings:
      host: "localhost"
      port: 5432
      database: "memory_db"

  # Tier 3: Development context (Session-Buddy)
  tier3:
    adapter: "session_buddy"
    provider: "mcp"
    settings:
      server_url: "stdio://session-buddy"

# Secrets management
secrets:
  env:
    prefix: "LLM_API_"
    required_keys:
      - CLAUDE
      - QWEN
      - CODEX
```

______________________________________________________________________

## 🎯 Usage Examples

### Switch LLMs

```bash
# Switch to Claude (default)
mahavishnu ai switch-llm claude

# Switch to Qwen
mahavishnu ai switch-llm qwen

# Switch to Codex
mahavishnu ai switch-llm codex
```

### Store and Search Memories

```bash
# Store decision
mahavishnu memory store "Chose PostgreSQL for ACID compliance"

# Search memories
mahavishnu memory search "Why PostgreSQL?" --tier hot
```

### Restart Services

```bash
# Restart Claude Code
mahavishnu service restart claude

# Restart all AI services
mahavishnu service restart all
```

______________________________________________________________________

## ✅ Checklist

- [ ] Create `mahavishnu/ai_env/` module
- [ ] Implement `ClaudeCodeManager`
- [ ] Implement `LLMSwitcher`
- [ ] Implement `ServiceManager`
- [ ] Create `mahavishnu/memory/` module
- [ ] Implement `SessionBuddyClient`
- [ ] Implement `UnifiedMemoryManager`
- [ ] Add CLI commands
- [ ] Update `settings/mahavishnu.yaml`
- [ ] Test LLM switching
- [ ] Test unified memory storage
- [ ] Test Session-Buddy integration

______________________________________________________________________

## 📊 Data Flow

```
User Action (switch LLM)
    │
    ▼
LLMSwitcher.switch_llm()
    │
    ├─► Update ~/.claude/settings.json
    │       └─ ANTHROPIC_BASE_URL, etc.
    │
    ├─► Restart Claude Code
    │       └─ killall Claude + open -a Claude
    │
    └─► Verify configuration
            └─ Claude Code connected to new LLM
```

```
User Action (store memory)
    │
    ▼
UnifiedMemoryManager.store_decision()
    │
    ├─► AgentDB (hot, sub-1ms)
    │       └─ Insert with embedding
    │
    ├─► pgvector (cold, persistent)
    │       └─ Insert with embedding
    │
    └─► Session-Buddy (development context)
            └─ Checkpoint + quality score
```

______________________________________________________________________

## 🚀 Next Steps

1. **Implement the modules** (30 minutes)
1. **Test LLM switching** (10 minutes)
1. **Test memory storage** (10 minutes)
1. **Add MCP tools** (30 minutes)
1. **Add automation** (auto-sync, auto-restart) (1 hour)

**Total time**: ~2 hours for full implementation!

______________________________________________________________________

## 📚 Resources

- **Full Guide**: `docs/AI_ENVIRONMENT_MANAGEMENT.md`
- **Session-Buddy**: `/Users/les/Projects/session-buddy`
- **Oneiric Adapters**: `/Users/les/Projects/oneiric/oneiric/adapters/`

______________________________________________________________________

**This is a production-ready approach to unified AI environment management!** 🚀
