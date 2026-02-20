# Agno Adapter Completion - Implementation Plan

**Document Version:** 1.1
**Created:** 2026-02-20
**Updated:** 2026-02-20
**Author:** AI Engineering Team
**Status:** Planning - SDK Verified

> **SDK Verification (2026-02-20):** Import paths have been verified against Agno v2.5.3.
> See Section 0 for the complete list of verified correct import paths.

## Executive Summary

This document outlines a comprehensive implementation plan for completing the Agno adapter in Mahavishnu. The current implementation exists as a stub with mock agents; this plan transforms it into a production-ready multi-agent AI orchestration system using the real Agno library (available on PyPI as `agno>=2.5.0`).

## 0. SDK Verification (Agno v2.5.3)

> **Verified:** 2026-02-20 via `uv pip install agno>=2.5.0`

### Correct Import Paths

```python
# Core Primitives
from agno.agent import Agent
from agno.team import Team, TeamMode  # modes: coordinate, route, broadcast, tasks
from agno.workflow import Workflow

# LLM Models (use id= parameter, NOT model=)
from agno.models.openai import OpenAIChat  # NOT OpenAI
from agno.models.anthropic import Claude   # requires: pip install anthropic
from agno.models.ollama import Ollama      # requires: pip install ollama

# Tools
from agno.tools.mcp import MCPTools  # Native MCP integration
from agno.tools import Toolkit

# Run Outputs (location differs from assumptions)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput

# Knowledge & Memory
from agno.knowledge import Knowledge
from agno.memory import MemoryManager, UserMemory

# Database (requires sqlalchemy)
from agno.db.sqlite import SqliteDb      # requires: pip install sqlalchemy
from agno.db.base import Db
```

### API Differences from Original Assumptions

| Assumption | Actual API |
|------------|------------|
| `OpenAI(model='gpt-4o')` | `OpenAIChat(id='gpt-4o')` |
| `from agno.run import RunOutput` | `from agno.run.agent import RunOutput` |
| Custom tool registry | Use native `MCPTools(transport='sse')` |

### MCPTools Transports

```python
# SSE transport (for HTTP MCP servers like Mahavishnu)
MCPTools(url="http://localhost:8677/mcp", transport="sse")

# Stdio transport (for local MCP servers)
MCPTools(command="uvx", args=["my-mcp-server"], transport="stdio")
```

## 1. Architecture Overview

### 1.1 Current State

The Agno adapter currently exists in two locations:
- `mahavishnu/engines/agno_adapter.py` - Partial implementation with mock agents
- `mahavishnu/adapters/ai/agno_adapter.py` - HTTP stub for external Agno server

### 1.2 Target Architecture

```
+------------------------------------------------------------------+
|                        MahavishnuApp                              |
|  - Configuration (Oneiric)                                        |
|  - Pool Manager Integration                                       |
|  - Workflow State Tracking                                        |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                    AgnoAdapter (Production)                       |
|  - Implements OrchestratorAdapter interface                       |
|  - Multi-agent team management                                    |
|  - Tool registration and execution                                |
|  - Memory/storage integration                                     |
|  - OpenTelemetry instrumentation                                  |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                      Agno SDK (agno>=2.5.0)                       |
|  - Agent, Team, Workflow primitives                               |
|  - MCPTools for tool integration                                  |
|  - SqliteDb/PostgresDb for memory                                 |
|  - AgentOS for production serving                                 |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                    LLM Providers                                  |
|  - Anthropic Claude (claude-sonnet-4-6)                           |
|  - OpenAI GPT (gpt-4o)                                            |
|  - Ollama (qwen2.5, llama2) - local                               |
+------------------------------------------------------------------+
```

### 1.3 Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `AgnoAdapter` | Main adapter implementing `OrchestratorAdapter` | `mahavishnu/engines/agno_adapter.py` |
| `AgnoConfig` | Pydantic configuration model | `mahavishnu/core/config.py` |
| `AgentTeamManager` | Multi-agent team orchestration | `mahavishnu/engines/agno_teams.py` |
| `AgnoToolRegistry` | MCP tool registration | `mahavishnu/engines/agno_tools.py` |
| `AgnoMemoryStore` | Memory/storage integration | `mahavishnu/engines/agno_memory.py` |
| `AgnoInstrumentation` | OpenTelemetry setup | `mahavishnu/engines/agno_telemetry.py` |

## 2. Phase Breakdown (6 Weeks)

### Phase 1: Foundation (Week 1-2)

**Objectives:**
- Install Agno SDK and validate integration
- Implement production-ready `AgnoAdapter` class
- Configure LLM providers (Anthropic, OpenAI, Ollama)
- Add comprehensive error handling

**Deliverables:**
- [ ] Update `pyproject.toml` with Agno dependencies
- [ ] Implement `AgnoAdapter` with real Agent creation
- [ ] LLM provider factory pattern
- [ ] Configuration schema in `settings/mahavishnu.yaml`
- [ ] Unit tests for adapter initialization

**Key Files:**
```
mahavishnu/
  engines/
    agno_adapter.py       # Main adapter (production)
  core/
    config.py             # Add AgnoConfig
tests/
  unit/
    test_adapters/
      test_agno_adapter.py  # Comprehensive tests
```

### Phase 2: Multi-Agent Teams (Week 2-3)

**Objectives:**
- Implement Team and Workflow primitives
- Agent collaboration patterns
- Task distribution and result aggregation

**Deliverables:**
- [ ] `AgentTeamManager` class for team orchestration
- [ ] Agent team configuration schema (YAML/JSON)
- [ ] Team-based task execution
- [ ] Result aggregation from multiple agents
- [ ] Integration tests for multi-agent scenarios

**Key Files:**
```
mahavishnu/
  engines/
    agno_teams.py         # Team management
    agno_teams/
      __init__.py
      manager.py          # AgentTeamManager
      config.py           # TeamConfig models
      patterns.py         # Collaboration patterns
settings/
  agno_teams/
    code_review.yaml      # Example team config
    research.yaml         # Research team config
```

### Phase 3: Tool Integration (Week 3-4)

**Objectives:**
- Expose Mahavishnu MCP tools to Agno agents
- Implement tool registration and discovery
- Tool execution with proper error handling

**Deliverables:**
- [ ] `AgnoToolRegistry` for MCP tool integration
- [ ] Tool discovery from Mahavishnu MCP server
- [ ] Async tool execution with timeout handling
- [ ] Tool result validation and transformation
- [ ] Example tools: file operations, code search, repo management

**Key Files:**
```
mahavishnu/
  engines/
    agno_tools.py         # Tool registry
    agno_tools/
      __init__.py
      registry.py         # AgnoToolRegistry
      wrappers.py         # Tool function wrappers
      validators.py       # Input/output validation
```

### Phase 4: Memory & Storage (Week 4-5)

**Objectives:**
- Integrate Agno memory with Mahavishnu storage
- Session-based conversation persistence
- Knowledge base integration with LlamaIndex

**Deliverables:**
- [ ] `AgnoMemoryStore` for storage abstraction
- [ ] SQLite storage implementation (development)
- [ ] PostgreSQL storage implementation (production)
- [ ] Session management for user isolation
- [ ] Knowledge base integration hooks

**Key Files:**
```
mahavishnu/
  engines/
    agno_memory.py        # Memory integration
    agno_memory/
      __init__.py
      store.py            # AgnoMemoryStore
      sqlite.py           # SQLite implementation
      postgres.py         # PostgreSQL implementation
      session.py          # Session management
```

### Phase 5: OpenTelemetry & Observability (Week 5)

**Objectives:**
- Distributed tracing for agent execution
- Metrics collection (latency, token usage, errors)
- Integration with existing Mahavishnu observability

**Deliverables:**
- [ ] `AgnoInstrumentation` for OTel setup
- [ ] Span creation for agent runs
- [ ] Metrics: agent latency, token usage, tool calls
- [ ] Error tracking and alerting integration
- [ ] Dashboard templates (Grafana)

**Key Files:**
```
mahavishnu/
  engines/
    agno_telemetry.py     # OTel instrumentation
    agno_telemetry/
      __init__.py
      tracer.py           # Span management
      metrics.py          # Prometheus metrics
      integration.py      # Mahavishnu observability
docs/
  grafana/
    Agno_Dashboard.json   # Grafana dashboard
```

### Phase 6: Pool Integration & Production (Week 6)

**Objectives:**
- Connect Agno agents to Mahavishnu pool infrastructure
- Production deployment configuration
- Comprehensive documentation

**Deliverables:**
- [ ] Pool-aware agent execution
- [ ] Session-Buddy integration for memory aggregation
- [ ] Production configuration templates
- [ ] API documentation
- [ ] Migration guide from stub adapter

**Key Files:**
```
mahavishnu/
  engines/
    agno_pool.py          # Pool integration
  docs/
    agno_adapter.md       # User documentation
    agno_migration.md     # Migration guide
settings/
  production/
    agno.yaml             # Production config
```

## 3. API Design

### 3.1 AgnoAdapter Interface

```python
from mahavishnu.core.adapters.base import OrchestratorAdapter, AdapterType, AdapterCapabilities

class AgnoAdapter(OrchestratorAdapter):
    """Production Agno adapter for multi-agent AI orchestration."""

    def __init__(self, config: MahavishnuSettings) -> None:
        """Initialize adapter with configuration."""

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.AGNO

    @property
    def name(self) -> str:
        return "agno"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
            has_cloud_ui=False,  # AgentOS UI available separately
        )

    async def initialize(self) -> None:
        """Initialize Agno SDK, LLM providers, and storage."""

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute task using Agno agents across repositories."""

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status."""

    # Extended API

    async def create_team(self, team_config: TeamConfig) -> str:
        """Create an agent team from configuration."""

    async def run_agent(
        self,
        agent_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AgentRunResult:
        """Run a single agent with message and context."""

    async def run_team(
        self,
        team_id: str,
        task: str,
        mode: str = "coordinate",  # coordinate, route, collaborate
    ) -> TeamRunResult:
        """Run an agent team with task."""

    async def register_tool(self, tool: AgnoTool) -> None:
        """Register a tool for use by agents."""

    async def get_agent_memory(self, agent_id: str, user_id: str) -> list[dict]:
        """Get memory entries for agent and user."""

    async def shutdown(self) -> None:
        """Gracefully shutdown adapter and cleanup resources."""
```

### 3.2 Team Configuration Schema

```yaml
# settings/agno_teams/code_review.yaml
team:
  name: "code_review_team"
  description: "Multi-agent team for comprehensive code review"

  mode: "coordinate"  # coordinate, route, collaborate

  leader:
    name: "review_coordinator"
    role: "Coordinates code review across specialists"
    model: "claude-sonnet-4-6"
    instructions: |
      You are a code review coordinator. Distribute review tasks
      to specialist agents and aggregate their findings.

  members:
    - name: "security_analyst"
      role: "Security vulnerability detection"
      model: "claude-sonnet-4-6"
      tools: ["search_code", "read_file", "check_dependencies"]
      instructions: |
        Analyze code for security vulnerabilities including:
        - SQL injection risks
        - XSS vulnerabilities
        - Authentication/authorization flaws
        - Sensitive data exposure

    - name: "quality_engineer"
      role: "Code quality and best practices"
      model: "claude-sonnet-4-6"
      tools: ["search_code", "read_file", "run_linter"]
      instructions: |
        Evaluate code quality including:
        - Adherence to style guides
        - Complexity metrics
        - Test coverage gaps
        - Documentation completeness

    - name: "performance_analyst"
      role: "Performance optimization"
      model: "gpt-4o"
      tools: ["search_code", "read_file", "analyze_dependencies"]
      instructions: |
        Identify performance concerns:
        - Algorithm complexity
        - Memory usage patterns
        - Database query efficiency
        - Caching opportunities

  memory:
    enabled: true
    db_type: "postgres"  # sqlite, postgres
    table_name: "code_review_memory"
    num_history_runs: 10

  tools:
    - search_code
    - read_file
    - check_dependencies
    - run_linter
    - analyze_dependencies

  guardrails:
    max_tokens: 4000
    timeout_seconds: 300
    require_approval: false
```

### 3.3 Configuration Model

```python
from pydantic import BaseModel, Field
from typing import Literal

class AgnoLLMConfig(BaseModel):
    """LLM provider configuration for Agno."""
    provider: Literal["anthropic", "openai", "ollama"] = Field(
        default="ollama",
        description="LLM provider (anthropic, openai, ollama)"
    )
    model: str = Field(
        default="qwen2.5:7b",
        description="Model identifier"
    )
    api_key_env: str | None = Field(
        default=None,
        description="Environment variable name for API key"
    )
    base_url: str | None = Field(
        default="http://localhost:11434",
        description="Base URL for Ollama or custom endpoints"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=128000,
        description="Maximum tokens per response"
    )

    model_config = {"extra": "forbid"}


class AgnoMemoryConfig(BaseModel):
    """Memory and storage configuration."""
    enabled: bool = Field(default=True)
    db_type: Literal["sqlite", "postgres"] = Field(default="sqlite")
    db_path: str = Field(default="data/agno.db")
    connection_string: str | None = Field(
        default=None,
        description="PostgreSQL connection string (set via env)"
    )
    num_history_runs: int = Field(default=10, ge=0, le=100)

    model_config = {"extra": "forbid"}


class AgnoToolsConfig(BaseModel):
    """Tool integration configuration."""
    mcp_server_url: str = Field(
        default="http://localhost:8677/mcp",
        description="Mahavishnu MCP server URL for tool discovery"
    )
    enabled_tools: list[str] = Field(
        default_factory=lambda: [
            "search_code", "read_file", "write_file",
            "list_repos", "get_repo_info", "run_command"
        ]
    )
    tool_timeout_seconds: int = Field(default=60, ge=5, le=600)

    model_config = {"extra": "forbid"}


class AgnoAdapterConfig(BaseModel):
    """Complete Agno adapter configuration."""
    enabled: bool = Field(default=True)

    llm: AgnoLLMConfig = Field(default_factory=AgnoLLMConfig)

    memory: AgnoMemoryConfig = Field(default_factory=AgnoMemoryConfig)

    tools: AgnoToolsConfig = Field(default_factory=AgnoToolsConfig)

    teams_config_path: str = Field(
        default="settings/agno_teams",
        description="Path to team configuration files"
    )

    default_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Default agent execution timeout"
    )

    max_concurrent_agents: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum concurrent agent executions"
    )

    telemetry_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry instrumentation"
    )

    model_config = {"extra": "forbid"}
```

## 4. Agent Team Configuration

### 4.1 Team Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `coordinate` | Leader agent distributes tasks to members | Code review, research |
| `route` | Single agent selected based on task type | Customer support, Q&A |
| `collaborate` | All agents work together on same task | Brainstorming, complex analysis |

### 4.2 Built-in Team Templates

```yaml
# settings/agno_teams/research.yaml
team:
  name: "research_team"
  mode: "coordinate"
  leader:
    name: "research_coordinator"
    role: "Coordinates research across sources"
    model: "claude-sonnet-4-6"
  members:
    - name: "web_researcher"
      role: "Web search and content extraction"
      model: "gpt-4o"
      tools: ["web_search", "read_url"]
    - name: "code_researcher"
      role: "Code analysis and documentation"
      model: "claude-sonnet-4-6"
      tools: ["search_code", "read_file"]
    - name: "doc_synthesizer"
      role: "Synthesizes findings into reports"
      model: "claude-sonnet-4-6"
```

## 5. Memory Integration

### 5.1 Storage Backends

```python
from abc import ABC, abstractmethod
from typing import Any
from agno.db.base import Db

class AgnoMemoryStore(ABC):
    """Abstract memory store for Agno agents."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize storage backend."""

    @abstractmethod
    async def get_db(self) -> Db:
        """Get Agno-compatible database instance."""

    @abstractmethod
    async def save_memory(self, agent_id: str, user_id: str, memory: dict) -> None:
        """Save memory entry."""

    @abstractmethod
    async def load_memory(self, agent_id: str, user_id: str, limit: int = 10) -> list[dict]:
        """Load recent memory entries."""

    @abstractmethod
    async def clear_memory(self, agent_id: str, user_id: str) -> None:
        """Clear memory for agent/user."""

    @abstractmethod
    async def close(self) -> None:
        """Close storage connection."""


class SqliteMemoryStore(AgnoMemoryStore):
    """SQLite-based memory storage for development."""

    def __init__(self, db_path: str = "data/agno.db"):
        self.db_path = db_path
        self._db: SqliteDb | None = None

    async def get_db(self) -> SqliteDb:
        if self._db is None:
            from agno.db.sqlite import SqliteDb
            self._db = SqliteDb(db_file=self.db_path)
        return self._db


class PostgresMemoryStore(AgnoMemoryStore):
    """PostgreSQL-based memory storage for production."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self._db: PostgresDb | None = None

    async def get_db(self) -> PostgresDb:
        if self._db is None:
            from agno.db.postgres import PostgresDb
            self._db = PostgresDb(connection_string=self.connection_string)
        return self._db
```

### 5.2 Session-Buddy Integration

```python
class SessionBuddyMemoryBridge:
    """Bridge between Agno memory and Session-Buddy for aggregation."""

    def __init__(self, session_buddy_url: str):
        self.session_buddy_url = session_buddy_url

    async def sync_memories(
        self,
        agent_id: str,
        memories: list[dict]
    ) -> None:
        """Sync agent memories to Session-Buddy for cross-pool access."""
        # Implementation sends memories to Session-Buddy MCP server

    async def search_cross_pool(
        self,
        query: str,
        agent_ids: list[str] | None = None
    ) -> list[dict]:
        """Search memories across all pools via Session-Buddy."""
        # Implementation queries Session-Buddy for relevant memories
```

## 6. Tool Integration

### 6.1 Native MCP Integration (Recommended)

> **SDK Verified:** Agno v2.5.3 includes native MCP support via `MCPTools`

```python
from agno.tools.mcp import MCPTools
from agno.agent import Agent

# Native MCP integration with Mahavishnu MCP server
mcp_tools = MCPTools(
    url="http://localhost:8680/mcp",  # Mahavishnu MCP endpoint
    transport="sse",
)

# Use directly in agent
agent = Agent(
    name="Code Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[mcp_tools],  # All MCP tools available automatically
)
```

### 6.2 Custom Tool Registry (For Built-in Tools)

For Mahavishnu-specific tools not exposed via MCP:

```python
from agno.tools import Toolkit
from typing import Callable, Any

class AgnoToolRegistry:
    """Registry for exposing Mahavishnu-specific tools to Agno agents."""

    def __init__(self, mcp_server_url: str | None = None):
        self.mcp_server_url = mcp_server_url
        self._toolkit = Toolkit()

    async def register_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
    ) -> None:
        """Register a tool with Agno-compatible wrapper."""
        self._toolkit.add_function(
            name=name,
            fn=handler,
            description=description,
        )

    def get_toolkit(self) -> Toolkit:
        """Get the toolkit for use in agents."""
        return self._toolkit
```

### 6.2 Built-in Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_code` | Search code in repositories | `query`, `repos`, `file_types` |
| `read_file` | Read file contents | `path`, `start_line`, `end_line` |
| `write_file` | Write file contents | `path`, `content`, `mode` |
| `list_repos` | List configured repositories | `tag`, `role` |
| `get_repo_info` | Get repository metadata | `repo_path` |
| `run_command` | Execute shell command | `command`, `cwd`, `timeout` |
| `web_search` | Search the web | `query`, `num_results` |
| `read_url` | Fetch URL content | `url`, `timeout` |

## 7. Code Structure

```
mahavishnu/
  engines/
    __init__.py
    agno_adapter.py           # Main adapter (production)
    agno_teams/
      __init__.py
      manager.py              # AgentTeamManager
      config.py               # TeamConfig, MemberConfig
      patterns.py             # Coordination patterns
    agno_tools/
      __init__.py
      registry.py             # AgnoToolRegistry
      wrappers.py             # Tool function wrappers
      builtin.py              # Built-in tools
    agno_memory/
      __init__.py
      store.py                # AgnoMemoryStore ABC
      sqlite.py               # SQLite implementation
      postgres.py             # PostgreSQL implementation
      session_bridge.py       # Session-Buddy integration
    agno_telemetry/
      __init__.py
      tracer.py               # Span management
      metrics.py              # Prometheus metrics
      integration.py          # Mahavishnu observability
  core/
    config.py                 # Add AgnoAdapterConfig

settings/
  agno_teams/
    code_review.yaml
    research.yaml
    customer_support.yaml

tests/
  unit/
    test_engines/
      test_agno_adapter.py
      test_agno_teams.py
      test_agno_tools.py
      test_agno_memory.py
  integration/
    test_agno_e2e.py
```

## 8. Testing Strategy

### 8.1 Unit Tests

```python
# tests/unit/test_engines/test_agno_adapter.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings, AgnoAdapterConfig

@pytest.fixture
def agno_config():
    return AgnoAdapterConfig(
        enabled=True,
        llm=AgnoLLMConfig(provider="ollama", model="qwen2.5:7b"),
        memory=AgnoMemoryConfig(db_type="sqlite"),
    )

@pytest.fixture
def mock_settings(agno_config):
    settings = MagicMock(spec=MahavishnuSettings)
    settings.agno = agno_config
    return settings

@pytest.mark.asyncio
async def test_adapter_initialization(mock_settings):
    """Test AgnoAdapter initializes correctly."""
    adapter = AgnoAdapter(config=mock_settings)
    await adapter.initialize()

    assert adapter.adapter_type == AdapterType.AGNO
    assert adapter.capabilities.supports_multi_agent is True

@pytest.mark.asyncio
async def test_create_single_agent(mock_settings):
    """Test creating a single agent."""
    adapter = AgnoAdapter(config=mock_settings)
    await adapter.initialize()

    agent = await adapter._create_agent(
        name="test_agent",
        role="Test agent",
        instructions="Test instructions"
    )

    assert agent is not None
    assert hasattr(agent, 'run')

@pytest.mark.asyncio
async def test_execute_code_sweep(mock_settings, tmp_path):
    """Test executing code sweep task."""
    adapter = AgnoAdapter(config=mock_settings)
    await adapter.initialize()

    result = await adapter.execute(
        task={"type": "code_sweep", "params": {}},
        repos=[str(tmp_path)]
    )

    assert result["status"] == "completed"
    assert result["engine"] == "agno"
    assert len(result["results"]) == 1
```

### 8.2 Integration Tests

```python
# tests/integration/test_agno_e2e.py

import pytest
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_agent_workflow():
    """Test complete agent workflow with real LLM."""
    settings = MahavishnuSettings()
    adapter = AgnoAdapter(config=settings)
    await adapter.initialize()

    # Create team from config
    team_id = await adapter.create_team_from_config(
        "settings/agno_teams/research.yaml"
    )

    # Run team task
    result = await adapter.run_team(
        team_id=team_id,
        task="Research best practices for Python async programming"
    )

    assert result.status == "completed"
    assert len(result.responses) > 0

    await adapter.shutdown()
```

### 8.3 Mock Agent Tests

For testing without real LLM access:

```python
class MockAgent:
    """Mock agent for testing without LLM dependencies."""

    def __init__(self, name: str, role: str, instructions: str):
        self.name = name
        self.role = role
        self.instructions = instructions

    async def run(self, message: str, context: dict = None) -> "MockResponse":
        # Generate deterministic response based on message content
        content = f"Mock response from {self.name} for: {message[:50]}..."
        return MockResponse(content=content)

class MockResponse:
    def __init__(self, content: str):
        self.content = content
        self.run_id = "mock_run_123"
```

## 9. Configuration

### 9.1 settings/mahavishnu.yaml Additions

```yaml
# Agno adapter configuration
agno:
  enabled: true

  llm:
    provider: "ollama"           # anthropic, openai, ollama
    model: "qwen2.5:7b"
    base_url: "http://localhost:11434"
    temperature: 0.7
    max_tokens: 4096

  memory:
    enabled: true
    db_type: "sqlite"            # sqlite, postgres
    db_path: "data/agno.db"
    num_history_runs: 10

  tools:
    mcp_server_url: "http://localhost:8677/mcp"
    enabled_tools:
      - search_code
      - read_file
      - write_file
      - list_repos
    tool_timeout_seconds: 60

  teams_config_path: "settings/agno_teams"
  default_timeout_seconds: 300
  max_concurrent_agents: 5
  telemetry_enabled: true
```

### 9.2 Environment Variables

```bash
# LLM Provider API Keys (set as needed)
ANTHROPIC_API_KEY="sk-ant-..."
OPENAI_API_KEY="sk-..."

# PostgreSQL connection (if using postgres memory)
MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING="postgresql://user:pass@host:5432/agno"

# Override default model
MAHAVISHNU_AGNO__LLM__MODEL="claude-sonnet-4-6"
MAHAVISHNU_AGNO__LLM__PROVIDER="anthropic"
```

## 10. Dependencies

### 10.1 pyproject.toml Additions

```toml
[project.optional-dependencies]
agno = [
    "agno>=2.5.0,<3.0.0",
    "mcp>=1.0.0",
]

# Development dependencies for Agno testing
[project.optional-dependencies."agno-dev"]
agno = [
    "agno[os]>=2.5.0,<3.0.0",   # Includes AgentOS extras
    "mcp>=1.0.0",
    "anthropic>=0.40.0",         # For Claude models
    "openai>=1.0.0",             # For GPT models
]
```

### 10.2 Version Constraints

| Package | Version | Notes |
|---------|---------|-------|
| `agno` | `>=2.5.0,<3.0.0` | Core SDK with Agent/Team/Workflow |
| `mcp` | `>=1.0.0` | MCP protocol for tools |
| `anthropic` | `>=0.40.0` | Optional: Claude models |
| `openai` | `>=1.0.0` | Optional: GPT models |

## 11. Risk Assessment

### 11.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agno API changes | Medium | High | Pin version, monitor changelog |
| LLM rate limits | High | Medium | Implement backoff, use local fallback |
| Memory storage scaling | Medium | Medium | Use PostgreSQL for production |
| Tool execution failures | Medium | Medium | Comprehensive error handling |
| Pool integration complexity | Medium | High | Phase 6 dedicated to integration |

### 11.2 Mitigation Strategies

1. **API Stability**: Pin Agno to minor version, subscribe to release notes
2. **LLM Reliability**: Implement multi-provider fallback (Anthropic -> OpenAI -> Ollama)
3. **Performance**: Use connection pooling, batch operations, async execution
4. **Testing**: 80%+ coverage, integration tests with mock LLMs

## 12. Success Criteria

### 12.1 Phase Completion Criteria

| Phase | Success Criteria |
|-------|------------------|
| Phase 1 | Adapter initializes, health check passes, single agent runs |
| Phase 2 | Team creation from YAML, coordinated task execution |
| Phase 3 | 5+ tools registered and callable from agents |
| Phase 4 | Memory persists across sessions, Session-Buddy syncs |
| Phase 5 | Traces visible in OTel backend, metrics in Prometheus |
| Phase 6 | Pool routing works, production config validated |

### 12.2 Final Acceptance Criteria

- [ ] All unit tests pass (>80% coverage)
- [ ] Integration tests pass with mock and real LLMs
- [ ] Documentation complete (API docs, migration guide)
- [ ] Performance: <5s agent initialization, <30s task execution
- [ ] Reliability: 99% success rate with retry logic
- [ ] Security: API keys from environment only, input validation
- [ ] Observability: Full OTel tracing, metrics dashboard

## 13. Migration Guide Summary

### 13.1 From Stub Adapter

1. Update `pyproject.toml` with Agno dependencies
2. Add `agno:` section to `settings/mahavishnu.yaml`
3. Set `MAHAVISHNU_AGNO__LLM__PROVIDER` environment variable
4. Create team configurations in `settings/agno_teams/`
5. Update any code using `AgnoAdapter` to use new API

### 13.2 Breaking Changes

| Old API | New API | Notes |
|---------|---------|-------|
| `_create_agent(task_type)` | `create_agent(config)` | Config-based creation |
| `execute(task, repos)` | `execute(task, repos)` | Same signature, enhanced response |
| No team support | `create_team(config)` | New feature |
| No memory | `get_agent_memory()` | New feature |

---

**Document Approval:**

| Role | Name | Date |
|------|------|------|
| AI Engineer | [Pending] | [Pending] |
| Tech Lead | [Pending] | [Pending] |
| Architect | [Pending] | [Pending] |
