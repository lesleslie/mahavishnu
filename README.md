# Mahavishnu - Global Orchestrator Package

Mahavishnu is a modular orchestration platform that provides unified interfaces for managing workflows across multiple repositories. It supports high-level orchestration with Prefect, RAG pipelines with LlamaIndex, and fast AI agents with Agno—all integrated with a unified memory system for intelligent knowledge management.

## Features

### Core Components
- **Prefect Integration**: High-level orchestration with dynamic flows, scheduling, and state management
- **LlamaIndex RAG**: Repository/document ingestion, embedding with Ollama, vector stores for semantic search
- **Agno Agents**: Fast, scalable single/multi-agents with memory, tools, and multi-LLM routing
- **Unified Memory**: Integration with Session-Buddy for project memory, global insights, and cross-project intelligence

### Platform Features
- **Repository Management**: Organize and operate on repositories using tags
- **CLI Interface**: Intuitive command-line interface powered by Typer
- **MCP Server**: Machine Learning Communication Protocol server for tool integration
- **Configurable**: Flexible configuration via Oneiric framework
- **Secure**: JWT authentication and path validation
- **Observable**: Built-in metrics and tracing with OpenTelemetry
- **Resilient**: Circuit breaker and retry patterns

## Installation

```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate
uv pip install -e .

# Or using pip
pip install -e .
```

## Quick Start

### 1. Configure your repositories

Create a `repos.yaml` file to define your repositories:

```yaml
repos:
  - name: "my-project"
    package: "my_project"
    path: "/path/to/my-project"
    tags: ["backend", "python"]
    description: "My backend services repository"
    mcp: "native"
```

### 2. Configure Mahavishnu

Create `settings/mahavishnu.yaml` for your configuration:

```yaml
server_name: "Mahavishnu Orchestrator"
cache_root: .oneiric_cache
health_ttl_seconds: 60.0
log_level: INFO
repos_path: "~/repos.yaml"

# Core Components (Simplified Architecture)
adapters:
  prefect: true       # High-level orchestration with dynamic flows
  llamaindex: true    # RAG pipelines for knowledge bases
  agno: true          # Fast, scalable AI agents

# LLM Configuration (for LlamaIndex and Agno)
llm_model: "nomic-embed-text"  # Ollama embedding model
ollama_base_url: "http://localhost:11434"  # Ollama API endpoint

# Memory Integration (NEW)
memory_service:
  enabled: true
  enable_rag_search: true
  enable_agent_memory: true
  enable_reflection_search: true

qc:
  enabled: true
  min_score: 80
  checks:
    - linting
    - type_checking
    - security_scan

auth:
  enabled: false  # Set to true in production
  algorithm: "HS256"
  expire_minutes: 60
```

For local development, create `settings/local.yaml`:

```yaml
server_name: "Mahavishnu Local Development"
log_level: DEBUG

auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 120
```

### 3. Usage

Perform an AI sweep across repositories with the 'agent' tag using LangGraph:

```bash
mahavishnu sweep --tag agent --adapter langgraph
```

List all repositories:

```bash
mahavishnu list-repos
```

List repositories with a specific tag:

```bash
mahavishnu list-repos --tag python
```

Start the MCP server:

```bash
mahavishnu mcp-serve
```

## Configuration

Mahavishnu uses a layered configuration system:

1. Default values in Pydantic models
2. `settings/mahavishnu.yaml` (committed to git)
3. `settings/local.yaml` (gitignored, local overrides)
4. Environment variables `MAHAVISHNU_*`

### Environment Variables

- `MAHAVISHNU_AUTH_SECRET`: JWT secret (required if auth is enabled)
- `MAHAVISHNU_LLM_API_KEY`: API key for LLM provider
- `MAHAVISHNU_REPOS_PATH`: Path to repos.yaml file

## Core Components

### Prefect: Workflow Orchestration

Prefect provides high-level orchestration with dynamic flows:

**Use Cases:**
- Production workflows with scheduling requirements
- State management and flow coordination
- Deployment pipelines and batch processing

**Example:**
```bash
# Trigger Prefect workflow
mahavishnu workflow trigger --name etl_pipeline --adapter prefect
```

### LlamaIndex: RAG & Knowledge Bases

LlamaIndex powers RAG (Retrieval-Augmented Generation) pipelines:

**Features:**
- Repository/document ingestion from `repos.yaml`
- Vector embeddings with Ollama (local models)
- Semantic search across codebases
- Integration with Agno agents for knowledge bases

**Example:**
```bash
# Ingest repository into RAG knowledge base
mahavishnu ingest --repo /path/to/repo --adapter llamaindex

# Query knowledge base
mahavishnu query --query "authentication patterns" --adapter llamaindex
```

### Agno: AI Agents

Agno provides fast, scalable AI agent workflows:

**Features:**
- Single and multi-agent systems
- Memory and tools for agents
- Multi-LLM routing (Ollama, Claude, Qwen)
- High-performance agent execution

**Example:**
```bash
# Run agent workflow
mahavishnu workflow sweep --tag backend --adapter agno
```

## Memory Architecture

Mahavishnu features a **unified memory system** that integrates multiple storage backends:

### Memory Systems

**1. Session-Buddy Integration (Project Memory + Global Intelligence)**
- **Reflection Database**: DuckDB-based storage at `~/.claude/data/reflection.duckdb`
- **Project Memory**: Mahavishnu workflow executions and orchestration patterns
- **Global Memory**: Insights shared across all projects
- **Cross-Project Search**: Dependency-aware result ranking
- **Automatic Insights Capture**: Extracts learnings from `★ Insight ─────` patterns

**2. AgentDB + PostgreSQL (Agent Memory)**
- **High-Volume Storage**: Scales for frequent agent operations
- **Agent Conversations**: Chat history and context tracking
- **Tool Usage History**: Agent tool invocations and results
- **Reasoning Traces**: Agent decision processes
- **Persistent Storage**: PostgreSQL-backed for durability

**3. LlamaIndex + AgentDB (RAG Knowledge Base)**
- **Vector Embeddings**: Ollama-powered local embeddings
- **Document Chunks**: Intelligent text splitting for retrieval
- **Semantic Search**: High-quality RAG retrieval
- **Large-Scale**: Handles millions of documents

### Unified Memory Search

Search across all memory systems with a single query:

```python
from mahavishnu.core.memory_integration import UnifiedMemoryQuery

# Search across all memory systems
results = await memory.unified_search(
    UnifiedMemoryQuery(
        query="orchestration patterns for microservices",
        sources=["session_buddy", "agentdb", "llamaindex"],
        limit=20
    )
)
```

### Cross-Project Intelligence

Mahavishnu integrates with Session-Buddy's cross-project features:

- **Project Groups**: Related projects coordinated by Mahavishnu
- **Dependency Tracking**: Repos know they're orchestrated by Mahavishnu
- **Knowledge Sharing**: Solutions found in one project help in related projects
- **Dependency-Aware Search**: Results ranked by project relationships

**Example:**
When fixing an authentication issue in `auth-service`, the solution automatically becomes discoverable in `user-service` (which depends on `auth-service`) via Mahavishnu's cross-project memory.

For detailed architecture documentation, see [MEMORY_ARCHITECTURE_PLAN.md](MEMORY_ARCHITECTURE_PLAN.md).

## Security

Mahavishnu implements several security measures:

- JWT authentication for API access
- Path validation to prevent directory traversal
- Secrets management via environment variables
- Configuration validation

To enable authentication, set `auth.enabled: true` in your configuration and provide a `MAHAVISHNU_AUTH_SECRET` environment variable with at least 32 characters.

## Architecture

Mahavishnu follows a modular architecture with the following components:

### Core Components

- **Prefect Adapter**: High-level orchestration with dynamic flows and scheduling
- **LlamaIndex Adapter**: RAG pipelines for knowledge bases and semantic search
- **Agno Adapter**: Fast, scalable AI agents with memory and tools

### Memory Integration

- **Session-Buddy Integration**: Project memory, global insights, cross-project intelligence
- **AgentDB + PostgreSQL**: High-volume agent memory storage
- **LlamaIndex RAG**: Vector embeddings and semantic search
- **Unified Memory Service**: Single interface to all memory systems

### Platform Services

- **CLI**: Typer-based command-line interface
- **MCP Server**: Machine Learning Communication Protocol server
- **Terminal Management**: Multi-terminal session management (10+ concurrent sessions)
- **Integrations**: Hooks for Crackerjack (QC) and Session-Buddy

### Technology Stack

- **Configuration**: Oneiric framework for layered config and logging
- **Embeddings**: Ollama (local models, no external APIs)
- **Vector Storage**: AgentDB with PostgreSQL backend
- **Authentication**: JWT with configurable secrets
- **Observability**: OpenTelemetry metrics and tracing

## Terminal Management

Mahavishnu includes advanced terminal management capabilities for launching and controlling multiple terminal sessions concurrently.

**Key Features:**
- Launch 10+ concurrent terminal sessions
- Hot-swappable adapters (iTerm2 ↔ mcpretentious)
- Connection pooling for reduced overhead
- iTerm2 profile support
- Command injection and output capture

**Quick Start:**
```yaml
# settings/mahavishnu.yaml
terminal:
  enabled: true
  adapter_preference: "auto"  # Auto-detect iTerm2, fallback to mcpretentious
```

```bash
# Launch 3 Qwen sessions
mahavishnu terminal launch "qwen" --count 3

# Or via MCP tools (when server is running)
await mcp.call_tool("terminal_launch", {"command": "qwen", "count": 3})
```

For full documentation, see [docs/TERMINAL_MANAGEMENT.md](docs/TERMINAL_MANAGEMENT.md).

## Development

To contribute to Mahavishnu:

1. Fork the repository
2. Create a virtual environment: `uv venv`
3. Install in editable mode: `uv pip install -e .`
4. Make your changes
5. Run tests: `pytest`
6. Submit a pull request

## Testing

Run all tests:

```bash
pytest
```

Run unit tests:

```bash
pytest tests/unit/
```

Run integration tests:

```bash
pytest tests/integration/
```

## License

This project is licensed under the MIT License.