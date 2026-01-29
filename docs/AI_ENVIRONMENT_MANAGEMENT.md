# Global AI Environment Management with Mahavishnu

**Managing ~/.claude, LLM environments, and integrating with Session-Buddy shared memory**

**Date**: 2025-01-23
**Status**: Architecture & Implementation Options

______________________________________________________________________

## 🎯 Overview

Mahavishnu can manage your global AI environments including:

- **Claude Code** (~/.claude, ~/.claude/settings.json)
- **LLM Environments** (Claude Code, Qwen, Codex, etc.)
- **Session-Buddy** shared memory integration
- **Unified memory system** (Session-Buddy + AgentDB + pgvector)

______________________________________________________________________

## 📊 Current Configuration Analysis

### Claude Code Structure

```bash
~/.claude/
├── settings.json              # Main configuration
├── settings.local.json        # Local overrides
├── .claude/                   # Internal Claude Code data
├── scripts/                   # Hook scripts
│   ├── auto-start-mcp-servers.sh
│   ├── inject-insights.sh
│   └── optimize_context.py
├── projects/                  # Project-specific contexts
└── plugins/                   # Installed plugins
```

### Current settings.json Structure

```json
{
  "permissions": { ... },
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/scripts/auto-start-mcp-servers.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [ ... ],
    "PostToolUse": [ ... ]
  },
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/scripts/session_progress_real.py"
  },
  "enabledPlugins": { ... },
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "...",
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1
  }
}
```

______________________________________________________________________

## 🏗️ Architecture Options

### Option 1: Direct File Manipulation

**Approach**: Mahavishnu directly reads/writes ~/.claude/settings.json

```python
"""Direct Claude Code configuration management."""
from pathlib import Path
import json
import subprocess


class ClaudeCodeManager:
    """Manage Claude Code configuration directly."""

    def __init__(self, claude_dir: Path = Path("~/.claude").expanduser()):
        self.claude_dir = claude_dir
        self.settings_file = claude_dir / "settings.json"

    def update_env_var(self, key: str, value: str) -> None:
        """Update environment variable in settings.json."""
        with open(self.settings_file) as f:
            settings = json.load(f)

        if "env" not in settings:
            settings["env"] = {}

        settings["env"][key] = value

        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)

    def restart_claude(self) -> None:
        """Restart Claude Code to apply changes."""
        # macOS: Restart via launchctl
        subprocess.run(["killall", "Claude"], check=False)
        subprocess.run(["open", "-a", "Claude"])

    def add_hook(self, hook_type: str, command: str) -> None:
        """Add a hook to settings.json."""
        with open(self.settings_file) as f:
            settings = json.load(f)

        if "hooks" not in settings:
            settings["hooks"] = {}

        if hook_type not in settings["hooks"]:
            settings["hooks"][hook_type] = []

        settings["hooks"][hook_type].append({
            "matcher": ".*",
            "hooks": [{"type": "command", "command": command}]
        })

        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)
```

**Pros**:

- ✅ Simple and direct
- ✅ No dependencies
- ✅ Full control over configuration

**Cons**:

- ❌ Manual JSON parsing
- ❌ No validation
- ❌ Race conditions if multiple processes

______________________________________________________________________

### Option 2: Oneiric Secrets Adapter (RECOMMENDED)

**Approach**: Use Oneiric's existing secrets adapters

```yaml
# settings/mahavishnu.yaml
secrets:
  # Environment variables (current Claude Code env vars)
  env:
    prefix: "CLAUDE_"  # CLAUDE_ANTHROPIC_AUTH_TOKEN, etc.
    required_keys:
      - ANTHROPIC_AUTH_TOKEN
      - ANTHROPIC_BASE_URL

  # File-based secrets for LLM API keys
  file:
    path: "~/.claude/secrets.json"
    required_keys:
      - claude_api_key
      - qwen_api_key
      - codex_api_key
```

```python
"""Oneiric-powered AI environment management."""
from oneiric.core.lifecycle import LifecycleManager
from oneiric.adapters.secrets import EnvSecretAdapter


class AIAccountManager:
    """Manage multiple AI environments via Oneiric."""

    def __init__(self):
        self.lifecycle = LifecycleManager(resolver)

    async def update_claude_env(self, key: str, value: str) -> None:
        """Update Claude Code environment variable."""
        env_adapter = await self.lifecycle.activate(
            "secrets", "env"
        )

        # Update environment variable
        import os
        os.environ[f"CLAUDE_{key}"] = value

        # Write to settings.json
        self._update_claude_settings(key, value)

    async def switch_llm(self, llm_name: str) -> None:
        """Switch active LLM (Claude, Qwen, Codex)."""
        llm_configs = {
            "claude": {
                "ANTHROPIC_AUTH_TOKEN": "...",
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            },
            "qwen": {
                "ANTHROPIC_AUTH_TOKEN": "...",
                "ANTHROPIC_BASE_URL": "https://api.qwen.com",
            },
            "codex": {
                "ANTHROPIC_AUTH_TOKEN": "...",
                "ANTHROPIC_BASE_URL": "https://api.codex.com",
            },
        }

        config = llm_configs[llm_name]

        # Update all env vars
        for key, value in config.items():
            await self.update_claude_env(key, value)

        # Restart Claude Code
        self._restart_claude()

    def _restart_claude(self) -> None:
        """Restart Claude Code."""
        import subprocess
        subprocess.run(["killall", "Claude"], check=False)
        subprocess.run(["open", "-a", "Claude"])
```

**Pros**:

- ✅ Oneiric integration (lifecycle, health checks)
- ✅ Multiple secret sources (env, file, AWS, GCP)
- ✅ Validation and type safety
- ✅ Hot-swappable adapters

**Cons**:

- ⚠️ Need to implement Claude Code-specific logic

______________________________________________________________________

### Option 3: Claude Code MCP Tools

**Approach**: Use Claude Code's MCP server for configuration

```python
"""Claude Code MCP integration."""
from mcp import ClientSession
from mcp.client.stdio import stdio_client


class ClaudeCodeMCPClient:
    """Manage Claude Code via MCP."""

    def __init__(self):
        self.server_params = stdio_client(
            command="claude",
            args=["mcp"],
        )

    async def update_config(self, key: str, value: str) -> None:
        """Update Claude Code configuration via MCP."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call Claude Code MCP tool
                result = await session.call_tool(
                    "update_settings",
                    arguments={"key": key, "value": value},
                )

                return result
```

**Pros**:

- ✅ Official Claude Code API
- ✅ Type-safe MCP protocol
- ✅ Future-proof

**Cons**:

- ❌ Claude Code MCP may not expose config tools yet
- ❌ Requires Claude Code to be running

______________________________________________________________________

## 🔗 Session-Buddy Integration

### Current Session-Buddy Features

**What Session-Buddy Provides**:

- ✅ **Vector database** (DuckDB FLOAT[384] embeddings)
- ✅ **Knowledge graph** (DuckPGQ for entities/relationships)
- ✅ **Quality scoring** (filesystem-based assessment)
- ✅ **Cross-session memory** (shared across projects)
- ✅ **MCP server** (localhost:8678)
- ✅ **Tools**: checkpoint, start, end, health_check, etc.

### Accessing Session-Buddy Shared Memory

```python
"""Integrate with Session-Buddy shared memory."""
from mcp import ClientSession
from mcp.client.stdio import stdio_client


class SessionBuddyClient:
    """Access Session-Buddy shared memory."""

    def __init__(self):
        self.server_params = stdio_client(
            command="python",
            args=["-m", "session_buddy.server"],
        )

    async def get_session_context(self, session_id: str) -> dict:
        """Get session context from Session-Buddy."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Get session data
                result = await session.call_tool(
                    "checkpoint",
                    arguments={
                        "working_directory": "/Users/les/Projects/mahavishnu",
                        "session_id": session_id,
                    },
                )

                return result

    async def search_memories(self, query: str, limit: int = 10) -> list:
        """Search Session-Buddy vector database."""
        async with self.server_params as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Progressive search
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

______________________________________________________________________

## 🚀 Unified Memory Architecture

### Three-Tier Memory System

```
┌─────────────────────────────────────────────────────────────┐
│  Mahavishnu Orchestrator                                    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Unified Memory Manager                              │   │
│  │  ├─ Session-Buddy (development sessions)            │   │
│  │  ├─ AgentDB (hot agent memory, sub-1ms)              │   │
│  │  └─ pgvector (cold storage, GCS backup)             │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  AI Environment Manager                              │   │
│  │  ├─ Claude Code (~/.claude/settings.json)           │   │
│  │  ├─ Qwen (config + env vars)                        │   │
│  │  └─ Codex (config + env vars)                       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Integration Flow

```python
"""Unified memory and AI environment management."""
from mahavishnu.core.app import MahavishnuApp
from oneiric.adapters.vector import VectorDocument


class UnifiedMemoryManager:
    """Manage all memory systems and AI environments."""

    def __init__(self):
        self.app = MahavishnuApp()
        self.session_buddy = SessionBuddyClient()

    async def store_decision(
        self,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> dict:
        """Store decision in all three memory systems."""

        # 1. Store in AgentDB (hot, fast)
        agentdb = await self.app.lifecycle.activate(
            "adapter", "vector", provider="agentdb"
        )

        doc = VectorDocument(
            vector=embedding,
            metadata={**metadata, "content": content},
        )

        agentdb_id = await agentdb.insert("decisions", [doc])

        # 2. Backup to pgvector (persistent)
        pgvector = await self.app.lifecycle.activate(
            "adapter", "vector", provider="pgvector"
        )

        pgvector_id = await pgvector.insert("decisions", [doc])

        # 3. Create Session-Buddy checkpoint
        checkpoint_result = await self.session_buddy.get_session_context(
            session_id=metadata.get("session_id")
        )

        return {
            "agentdb_id": agentdb_id,
            "pgvector_id": pgvector_id,
            "checkpoint": checkpoint_result,
        }

    async def search_all_memories(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> dict:
        """Search across all memory systems."""

        # Search AgentDB (hot, fast)
        agentdb = await self.app.lifecycle.activate(
            "adapter", "vector", provider="agentdb"
        )

        agentdb_results = await agentdb.search(
            "decisions",
            query_vector=query_embedding,
            limit=limit,
        )

        # Search Session-Buddy (development context)
        session_results = await self.session_buddy.search_memories(
            query="PostgreSQL decision",
            limit=limit,
        )

        return {
            "agentdb": agentdb_results,
            "session_buddy": session_results,
        }
```

______________________________________________________________________

## 🔧 Service Management

### Restarting Services

```python
"""Service management for AI environments."""
import subprocess
import asyncio
from pathlib import Path


class ServiceManager:
    """Manage AI environment services."""

    async def restart_all_services(self) -> dict:
        """Restart all AI environment services."""

        results = {}

        # 1. Restart Claude Code
        results["claude"] = await self._restart_claude()

        # 2. Restart Session-Buddy MCP server
        results["session_buddy"] = await self._restart_session_buddy()

        # 3. Restart AgentDB MCP server
        results["agentdb"] = await self._restart_agentdb()

        return results

    async def _restart_claude(self) -> bool:
        """Restart Claude Code."""
        try:
            # Graceful shutdown
            subprocess.run(["killall", "Claude"], check=False)

            # Wait for shutdown
            await asyncio.sleep(2)

            # Restart
            subprocess.run(["open", "-a", "Claude"], check=True)

            return True
        except Exception as e:
            print(f"Failed to restart Claude: {e}")
            return False

    async def _restart_session_buddy(self) -> bool:
        """Restart Session-Buddy MCP server."""
        try:
            # Find and kill Session-Buddy process
            result = subprocess.run(
                ["pgrep", "-f", "session_buddy.server"],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                pid = result.stdout.strip()
                subprocess.run(["kill", pid], check=True)

            # Wait for shutdown
            await asyncio.sleep(1)

            # Restart via launchd
            subprocess.run(
                ["launchctl", "start", "com.sessionbuddy.server"],
                check=True,
            )

            return True
        except Exception as e:
            print(f"Failed to restart Session-Buddy: {e}")
            return False

    async def _restart_agentdb(self) -> bool:
        """Restart AgentDB MCP server."""
        try:
            # Find and kill AgentDB process
            result = subprocess.run(
                ["pgrep", "-f", "agentdb"],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                pid = result.stdout.strip()
                subprocess.run(["kill", pid], check=True)

            # Wait for shutdown
            await asyncio.sleep(1)

            # Restart AgentDB
            subprocess.run(
                ["agentdb", "mcp", "start"],
                check=True,
            )

            return True
        except Exception as e:
            print(f"Failed to restart AgentDB: {e}")
            return False
```

______________________________________________________________________

## 💡 Recommended Implementation

### Phase 1: Foundation

1. **Create AI Environment Manager Module**

   ```python
   # mahavishnu/ai_env/
   ├── __init__.py
   ├── claude_manager.py      # Claude Code configuration
   ├── llm_switcher.py        # Switch between LLMs
   └── service_manager.py     # Service restart logic
   ```

1. **Create Unified Memory Module**

   ```python
   # mahavishnu/memory/
   ├── __init__.py
   ├── unified_manager.py     # Coordinate all memory systems
   ├── session_buddy.py       # Session-Buddy client
   └── hybrid_memory.py       # AgentDB + pgvector sync
   ```

1. **Update Mahavishnu Configuration**

   ```yaml
   # settings/mahavishnu.yaml
   ai_environments:
     claude_code:
       config_path: "~/.claude/settings.json"
       enabled: true

     llm_profiles:
       claude:
         anthropic_base_url: "https://api.anthropic.com"
       qwen:
         anthropic_base_url: "https://api.qwen.com"
       codex:
         anthropic_base_url: "https://api.codex.com"

   memory:
     tier1:
       adapter: "agentdb"
       provider: "agentdb"
       use_case: "hot"

     tier2:
       adapter: "vector"
       provider: "pgvector"
       use_case: "cold"

     tier3:
       adapter: "session_buddy"
       provider: "mcp"
       use_case: "development"
   ```

### Phase 2: Integration

1. **MCP Tools for Mahavishnu**

   ```python
   @mcp_tool()
   async def switch_llm(llm_name: str) -> dict:
       """Switch active LLM environment."""
       manager = AIAccountManager()
       return await manager.switch_llm(llm_name)

   @mcp_tool()
   async def store_unified_memory(
       content: str,
       embedding: list[float],
       metadata: dict,
   ) -> dict:
       """Store in all three memory systems."""
       manager = UnifiedMemoryManager()
       return await manager.store_decision(content, embedding, metadata)

   @mcp_tool()
   async def restart_ai_services() -> dict:
       """Restart all AI environment services."""
       manager = ServiceManager()
       return await manager.restart_all_services()
   ```

1. **CLI Commands**

   ```bash
   # Switch LLM
   mahavishnu ai switch-llm claude
   mahavishnu ai switch-llm qwen
   mahavishnu ai switch-llm codex

   # Memory operations
   mahavishnu memory store "content" --metadata "type=decision"
   mahavishnu memory search "PostgreSQL" --tier hot

   # Service management
   mahavishnu service restart claude
   mahavishnu service restart all
   ```

### Phase 3: Automation

1. **Auto-Sync Between Memory Systems**

   - Write-through: Store in AgentDB + pgvector + Session-Buddy
   - Periodic sync: Cron job every hour
   - Event-driven: Sync on checkpoint

1. **Auto-Restart Services**

   - Detect config changes
   - Auto-restart affected services
   - Health check verification

1. **Auto-Switch LLMs**

   - Detect API failures
   - Auto-fallback to backup LLM
   - Alert on failures

______________________________________________________________________

## 📚 Data Flow Diagrams

### Decision Storage Flow

```
User makes decision (e.g., "Use PostgreSQL")
    │
    ▼
Mahavishnu Decision Store
    │
    ├─► AgentDB (hot, sub-1ms access)
│       └─ Store: embedding + metadata
│
├─► pgvector (persistent backup)
│       └─ Store: embedding + metadata
│
└─► Session-Buddy (development context)
    └─ Checkpoint: git commit + quality score
```

### Memory Search Flow

```
User searches: "Why PostgreSQL?"
    │
    ▼
Mahavishnu Memory Search
    │
    ├─► AgentDB (search hot data)
│       └─ Return: Recent decisions (sub-1ms)
│
├─► pgvector (search persistent data)
│       └─ Return: Historical decisions
│
└─► Session-Buddy (search development context)
    └─ Return: Code changes, quality scores

Merge results by similarity score → Return to user
```

______________________________________________________________________

## 🔐 Security Considerations

### API Key Management

```yaml
# Best practices for API keys
secrets:
  # Never store in plaintext
  # Use Oneiric secret adapters

  # Option 1: Environment variables
  env:
    prefix: "LLM_API_"
    required_keys:
      - CLAUDE
      - QWEN
      - CODEX

  # Option 2: File-based (encrypted)
  file:
    path: "~/.claude/secrets.json.gpg"
    encryption: "gpg"

  # Option 3: Cloud secrets (production)
  aws:
    secret_id: "mahavishnu/llm-keys"
    region: "us-east-1"

  gcp:
    secret_id: "mahavishnu-llm-keys"
    project: "mahavishnu-prod"
```

### Permissions

```json
// ~/.claude/settings.json - Restrict Mahavishnu access
{
  "permissions": {
    "allow": [
      "Bash(mahavishnu:*)",
      "Read(//Users/les/Projects/mahavishnu/**)",
    ],
    "deny": [
      "Bash(mahavishnu:*rm*)",
      "Bash(mahavishnu:*delete*)",
    ]
  }
}
```

______________________________________________________________________

## 🚦 Recommendations

### ✅ DO THIS

1. **Use Oneiric for secrets management**

   - EnvSecretAdapter for environment variables
   - FileSecretAdapter for API keys
   - Multiple secret sources (env, file, AWS, GCP)

1. **Integrate with Session-Buddy MCP**

   - Access shared memory via MCP client
   - Use checkpoint for session snapshots
   - Leverage progressive search for code context

1. **Implement three-tier memory system**

   - AgentDB: Hot data (active agent memory)
   - pgvector: Cold data (persistent archive)
   - Session-Buddy: Development context (quality scores)

1. **Auto-restart services**

   - launchd for macOS (native)
   - Supervisord for cross-platform
   - Health checks before restart

### ❌ DON'T DO THIS

1. **Don't store API keys in plaintext**

   - Use Oneiric secret adapters
   - Encrypt sensitive data
   - Use environment variables

1. **Don't restart services without health checks**

   - Verify service is healthy before restart
   - Graceful shutdown first
   - Wait for cleanup

1. **Don't ignore race conditions**

   - Use file locking when writing config
   - Atomic writes (write to temp, then mv)
   - Validate JSON before saving

______________________________________________________________________

## 📖 Resources

- **Claude Code Settings**: [code.claude.com/docs/settings](https://code.claude.com/docs/en/settings)
- **Session-Buddy MCP**: `/Users/les/Projects/session-buddy`
- **Oneiric Adapters**: `/Users/les/Projects/oneiric/oneiric/adapters/`
- **AgentDB Adapter**: Created in Oneiric (`agentdb.py`)

______________________________________________________________________

## Summary

**Yes! Mahavishnu should manage global AI environments!**

**Recommended Stack**:

1. **Oneiric**: Secrets management, configuration
1. **Session-Buddy MCP**: Development session context
1. **AgentDB**: Hot agent memory (sub-1ms)
1. **pgvector**: Persistent archive with GCS backup
1. **Service Manager**: Auto-restart services

**Benefits**:

- ✅ Unified memory across all AI environments
- ✅ Seamless LLM switching (Claude, Qwen, Codex)
- ✅ Automatic service restart on config changes
- ✅ Cross-session shared memory via Session-Buddy
- ✅ Three-tier memory (hot, warm, cold)

**Next Steps**:

1. Implement `mahavishnu/ai_env/` module
1. Implement `mahavishnu/memory/` module
1. Add MCP tools for LLM switching and memory management
1. Create CLI commands for common operations
1. Add auto-sync between memory systems

This is a **powerful unified approach** to AI environment management! 🚀
