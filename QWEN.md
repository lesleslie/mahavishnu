# Mahavishnu - Global Orchestrator Package

## Project Overview

Mahavishnu is a modular orchestration platform that provides unified interfaces for managing workflows across multiple repositories. It serves as a global orchestrator that can coordinate operations across different codebases using various workflow engines.

The project is built with Python and leverages several key technologies:
- **Typer**: For the command-line interface
- **Oneiric**: For configuration and logging
- **PyYAML**: For YAML parsing
- **FastMCP**: For the MCP server
- **OpenTelemetry**: For observability
- **Various orchestration engines**: Prefect, LlamaIndex, Agno

## Architecture

Mahavishnu follows a modular architecture with the following components:

- **Core**: Oneiric-powered configuration and logging
- **CLI**: Typer-based command-line interface
- **Engines**: Adapters for different orchestration engines (Prefect, LlamaIndex, Agno)
- **MCP**: Machine Learning Communication Protocol server
- **Integrations**: Quality control (Crackerjack) and session management (Session-Buddy)
- **Shared Infrastructure**: mcp-common package with code graph analysis and messaging types

### Key Components

1. **Core Application (`mahavishnu/core/app.py`)**: Main application class that manages configuration, repository loading, and adapter initialization.

2. **CLI Module (`mahavishnu/cli.py`)**: Implements the command-line interface with commands like `sweep`, `mcp-serve`, and `list-repos`.

3. **Engine Adapters (`mahavishnu/engines/`)**: Contains adapter implementations for different orchestration engines (Prefect, LlamaIndex, Agno).

4. **MCP Server (`mahavishnu/mcp/server_core.py`)**: Implements the Machine Learning Communication Protocol server for tool integration.

5. **Shared Infrastructure (`mcp-common/`)**: Contains shared components used by both Mahavishnu and Session Buddy, including code graph analysis and messaging types.

## Building and Running

### Installation

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

### Usage

#### Basic Commands

```bash
# Perform an AI sweep across repositories with the 'agent' tag using LlamaIndex
mahavishnu sweep --tag agent --adapter llamaindex

# List all repositories
mahavishnu list-repos

# List repositories with a specific tag
mahavishnu list-repos --tag python

# Start the MCP server
mahavishnu mcp start

# Launch terminal sessions
mahavishnu terminal launch "python -c 'print(\"Hello\")'" --count 2
```

### Configuration

Mahavishnu uses multiple configuration sources with the following precedence (later overrides earlier):
1. Default values in Pydantic models
2. `settings/mahavishnu.yaml` (committed)
3. `settings/local.yaml` (gitignored)
4. Environment variables `MAHAVISHNU_*`

#### Environment Variables

- `MAHAVISHNU_AUTH_SECRET`: JWT secret (required if auth is enabled)
- `MAHAVISHNU_LLM_API_KEY`: API key for LLM provider
- `MAHAVISHNU_REPOS_PATH`: Path to repos.yaml file

#### repos.yaml
Repository manifest defining projects and their tags:
```yaml
repos:
  - name: "my-project"
    package: "my_project"
    path: "/path/to/my-project"
    tags: ["backend", "python"]
    description: "My backend services repository"
    mcp: "native"
```

## Development Conventions

### Project Structure
```
mahavishnu/
├── pyproject.toml          # Dependencies: oneiric, typer, prefect, llamaindex, agno, etc.
├── README.md
├── IMPLEMENTATION_PLAN.md  # Implementation plan
├── mahavishnu/
│   ├── __init__.py
│   ├── core/               # Oneiric-powered app entry (config, logging)
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── adapters/
│   │   ├── circuit_breaker.py
│   │   └── observability.py
│   ├── cli.py              # Typer app with commands
│   ├── mcp/                # MCP server using fastmcp
│   ├── engines/            # Adapter implementations
│   │   ├── __init__.py
│   │   ├── prefect_adapter.py
│   │   ├── llamaindex_adapter.py
│   │   └── agno_adapter.py
│   ├── qc/                 # Quality control integration
│   ├── session/            # Session management
│   ├── terminal/           # Terminal management
│   └── prototypes/         # Prototype scripts
├── mcp-common/             # Shared infrastructure
│   ├── pyproject.toml
│   ├── README.md
│   └── mcp_common/
│       ├── __init__.py
│       ├── code_graph/     # Code graph analysis
│       │   ├── __init__.py
│       │   └── analyzer.py
│       └── messaging/      # Shared messaging types
│           ├── __init__.py
│           └── types.py
├── repos.yaml              # Your repo manifest
└── settings/               # Configuration files
    ├── mahavishnu.yaml     # Main config
    └── local.yaml          # Local overrides (gitignored)
```

### Adapter Interface

All orchestrator adapters implement the `OrchestratorAdapter` base class:

```python
class OrchestratorAdapter(ABC):
    @abstractmethod
    async def execute(self, task: Dict[str, Any], repos: List[str]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_health(self) -> Dict[str, Any]:
        pass
```

### Testing

Run all tests:
```bash
pytest
```

Run with coverage:
```bash
pytest --cov=mahavishnu --cov-report=html
```

## Key Features

1. **Multi-engine Support**: Seamlessly switch between Prefect, LlamaIndex, and Agno
2. **Repository Management**: Organize and operate on repositories using tags
3. **CLI Interface**: Intuitive command-line interface powered by Typer
4. **MCP Server**: Machine Learning Communication Protocol server for tool integration
5. **Terminal Management**: Advanced terminal session management with multiple adapters
6. **Quality Control**: Integration with Crackerjack for code quality checks
7. **Session Management**: Integration with Session-Buddy for workflow checkpoints
8. **Observability**: OpenTelemetry integration for metrics and tracing
9. **Security**: JWT authentication with multiple provider support
10. **Concurrency Control**: Built-in concurrency limits and circuit breakers

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
- Prefect adapter (stub only, 143 lines)
- Agno adapter (stub only, 116 lines)
- MCP tools (terminal tools complete, core orchestration tools missing)

**Not Started**:
- Actual adapter logic (Prefect, Agno need implementation)
- LLM provider integrations for Prefect and Agno
- Production error recovery patterns
- Full observability implementation
- Crackerjack QC integration
- Session-Buddy checkpoint integration

## Development

To contribute to Mahavishnu:

1. Fork the repository
2. Create a virtual environment: `uv venv`
3. Install in editable mode: `uv pip install -e .`
4. Make your changes
5. Run tests: `pytest`
6. Submit a pull request

## Shared Infrastructure (mcp-common)

The mcp-common package contains shared components used by both Mahavishnu and Session Buddy:

- **Code Graph Analysis**: AST-based analysis of codebases to extract functions, classes, and relationships
- **Messaging Types**: Shared data structures for inter-project communication
- **MCP Contracts**: Standardized tool contracts for Machine Learning Communication Protocol

## Security

Mahavishnu implements comprehensive security measures:
- **JWT Authentication**: Multiple provider support (Claude Code, Qwen, custom)
- **Path Validation**: Prevents directory traversal attacks
- **Environment-Based Secrets**: No API keys in configuration files
- **Auth Secret Strength Validation**: Minimum 32 characters required