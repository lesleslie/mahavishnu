# Mahavishnu - Multi-Engine Orchestration Platform

Mahavishnu is a modular orchestration platform that provides unified interfaces for managing workflows across multiple repositories. It currently supports Prefect for high-level orchestration, with planned support for LangGraph and Agno for AI agent workflows.

## Current Status

**Implementation Phase**: Phase 1 Complete (Foundation + Core Architecture)

**Completed**:
- Security hardening (JWT auth, Claude Code + Qwen support)
- Async base adapter architecture
- FastMCP-based MCP server with terminal management
- Configuration system using Oneiric patterns
- CLI with authentication framework
- Repository management (9 repos configured)
- Test infrastructure (11 test files)

**Partially Complete**:
- Adapter implementations (stubs/skeleton only - actual orchestration logic not implemented)
- MCP tools (terminal tools complete, core orchestration tools missing)

**Not Started**:
- Actual adapter logic (Prefect, LangGraph, Agno)
- LLM provider integrations
- Production error recovery patterns
- Full observability implementation
- Crackerjack QC integration
- Session-Buddy checkpoint integration

See [UNIFIED_IMPLEMENTATION_STATUS.md](UNIFIED_IMPLEMENTATION_STATUS.md) for detailed progress tracking.

## Architecture

Mahavishnu follows a modular architecture with the following components:

### Core Components

- **Adapter Architecture**: Async base adapter interface for orchestration engines
- **Configuration System**: Oneiric-based layered configuration (defaults -> YAML -> env vars)
- **Error Handling**: Custom exception hierarchy with circuit breaker patterns
- **Repository Management**: YAML-based repository manifest with tag filtering

### Platform Services

- **CLI**: Typer-based command-line interface with authentication
- **MCP Server**: FastMCP-based server for tool integration
- **Terminal Management**: Multi-terminal session management (10+ concurrent sessions)
- **Security**: JWT authentication with multiple providers (Claude Code, Qwen, custom)

### Technology Stack

- **Configuration**: Oneiric framework for layered config and logging
- **Authentication**: JWT with configurable secrets and multiple providers
- **Observability**: OpenTelemetry metrics and tracing (framework defined, not fully instrumented)

## Installation

```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate
uv pip install -e .

# Or using pip
python -m venv .venv
source .venv/bin/activate
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

Mahavishnu currently includes 9 configured repositories:
- crackerjack
- session-buddy
- mcp-common
- fastblocks
- mahavishnu
- excalidraw-mcp
- mermaid-mcp
- acb
- bevy

### 2. Configure Mahavishnu

Create `settings/mahavishnu.yaml` for your configuration:

```yaml
server_name: "Mahavishnu Orchestrator"
cache_root: .oneiric_cache
health_ttl_seconds: 60.0
log_level: INFO
repos_path: "~/repos.yaml"

# Adapters (currently stub/skeleton implementations)
adapters:
  prefect: true       # High-level orchestration
  llamaindex: true    # RAG pipelines for knowledge bases
  agno: true          # Fast, scalable AI agents

# LLM Configuration (for LlamaIndex and Agno)
llm_model: "nomic-embed-text"  # Ollama embedding model
ollama_base_url: "http://localhost:11434"  # Ollama API endpoint

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

**Note**: Adapter implementations are currently stubs/skeletons. Actual workflow execution is not yet implemented.

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

## Adapters

### Prefect: Workflow Orchestration

**Status**: Stub implementation (143 lines)

Prefect provides high-level orchestration with dynamic flows:

**Use Cases**:
- Production workflows with scheduling requirements
- State management and flow coordination
- Deployment pipelines and batch processing

**Current Implementation**: Returns simulated results, not real orchestration

**Planned Features**:
- Dynamic flow creation from task specifications
- Hybrid execution support (local, cloud, containers)
- State management and checkpointing

### LlamaIndex: RAG & Knowledge Bases

**Status**: Stub implementation (348 lines)

LlamaIndex powers RAG (Retrieval-Augmented Generation) pipelines:

**Features**:
- Repository/document ingestion from `repos.yaml`
- Vector embeddings with Ollama (local models)
- Semantic search across codebases
- Integration with AI agents for knowledge bases

**Current Implementation**: Returns simulated results, not real RAG

**Planned Features**:
- Vector embeddings with Ollama
- Document chunking and indexing
- Semantic search queries

### Agno: AI Agents

**Status**: Stub implementation (116 lines)

Agno provides fast, scalable AI agent workflows:

**Features**:
- Single and multi-agent systems
- Memory and tools for agents
- Multi-LLM routing (Ollama, Claude, Qwen)
- High-performance agent execution

**Current Implementation**: Returns simulated results, not real agent orchestration

**Planned Features**:
- Agent lifecycle management
- Tool integration
- Multi-LLM routing

## MCP Server

Mahavishnu includes a FastMCP-based MCP server for tool integration.

### Terminal Management (Implemented)

**Status**: Complete (11,453 lines of terminal tools)

Terminal management tools are fully implemented:
- `terminal_launch`: Launch terminal sessions
- `terminal_type`: Type commands in terminals
- `terminal_read`: Read terminal output
- `terminal_close`: Close terminal sessions
- `terminal_list`: List active terminals

**Features**:
- Launch 10+ concurrent terminal sessions
- Hot-swappable adapters (iTerm2 <-> mcpretentious)
- Connection pooling for reduced overhead
- iTerm2 profile support

### Core Orchestration Tools (Not Implemented)

**Status**: Not yet implemented

The following tools are specified but not yet implemented:
- `list_repos`: List repositories with tag filtering
- `trigger_workflow`: Trigger workflow execution
- `get_workflow_status`: Check workflow status
- `cancel_workflow`: Cancel running workflow
- `list_adapters`: List available adapters

See [docs/MCP_TOOLS_SPECIFICATION.md](docs/MCP_TOOLS_SPECIFICATION.md) for complete tool specifications.

## Security

Mahavishnu implements comprehensive security measures:

### Authentication

- **JWT Authentication**: Multiple provider support
  - Claude Code subscription authentication
  - Qwen free service authentication
  - Custom JWT tokens
- **Path Validation**: Prevents directory traversal attacks
- **Environment-Based Secrets**: No API keys in configuration files
- **Auth Secret Strength Validation**: Minimum 32 characters required

### Configuration

To enable authentication, set `auth.enabled: true` in your configuration:

```yaml
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60
```

Provide a `MAHAVISHNU_AUTH_SECRET` environment variable with at least 32 characters.

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

Run with coverage:

```bash
pytest --cov=mahavishnu --cov-report=html
```

## Documentation

- [Implementation Status](UNIFIED_IMPLEMENTATION_STATUS.md) - Detailed progress tracking
- [Architecture Decision Records](docs/adr/) - Technical decisions and rationale
- [MCP Tools Specification](docs/MCP_TOOLS_SPECIFICATION.md) - Complete tool API documentation
- [Implementation Summary](docs/IMPLEMENTATION_SUMMARY.md) - Modernization notes (Prefect vs Airflow, LangGraph vs CrewAI)
- [Terminal Management](docs/TERMINAL_MANAGEMENT.md) - Terminal feature documentation

## Project Status

**Roadmap**:
- Phase 0: Security Hardening (Complete)
- Phase 1: Foundation Architecture (Complete)
- Phase 2: MCP Server (Partial - terminal tools complete, core tools missing)
- Phase 3: Adapter Implementation (Not Started - 6-9 weeks estimated)
- Phase 4: Production Features (Not Started - error recovery, observability, QC integration)
- Phase 5: Testing & Documentation (Not Started - comprehensive test suite, user docs)
- Phase 6: Production Readiness (Not Started - security audit, performance benchmarking)

**Estimated Time to Production**: 10 weeks from current state

## License

This project is licensed under the MIT License.
