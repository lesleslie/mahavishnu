# Mahavishnu - Global Orchestrator Package

## Project Overview

Mahavishnu is a modular orchestration platform that provides unified interfaces to various workflow engines including Airflow, CrewAI, LangGraph, and Agno. It enables developers to manage multi-repository projects with AI-powered automation and orchestration.

The project is built with Python and leverages several key technologies:
- **Typer**: For the command-line interface
- **Oneiric**: For configuration and logging
- **PyYAML**: For YAML parsing
- **Airflow, CrewAI, LangGraph, Agno**: For workflow orchestration
- **FastAPI & Uvicorn**: For the MCP server
- **MCP Common**: For Machine Learning Communication Protocol

## Architecture

Mahavishnu follows a modular architecture with the following components:

- **Core**: Oneiric-powered configuration and logging
- **CLI**: Typer-based command-line interface
- **Engines**: Adapters for different orchestration engines
- **MCP**: Machine Learning Communication Protocol server
- **Integrations**: Hooks for Crackerjack (QC) and Session-Buddy

### Key Components

1. **Core Application (`mahavishnu/core/app.py`)**: Main application class that manages configuration, repository loading, and adapter initialization.

2. **CLI Module (`mahavishnu/cli.py`)**: Implements the command-line interface with commands like `sweep`, `mcp-serve`, and `list-repos`.

3. **Engine Adapters (`mahavishnu/engines/`)**: Contains adapter implementations for different orchestration engines (Airflow, CrewAI, LangGraph, Agno).

4. **MCP Server (`mahavishnu/mcp/server.py`)**: Implements the Machine Learning Communication Protocol server for tool integration.

## Building and Running

### Installation

```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate
uv pip install -e .

# Or using pip
pip install -e .
```

### Usage

#### Basic Commands

```bash
# Perform an AI sweep across repositories with the 'agent' tag using CrewAI
mahavishnu sweep --tag agent --adapter crewai

# List all repositories
mahavishnu list-repos

# List repositories with a specific tag
mahavishnu list-repos --tag python

# Start the MCP server
mahavishnu mcp-serve
```

### Configuration

Mahavishnu uses two main configuration files:

- `repos.yaml`: Defines your repositories and their tags
- `oneiric.yaml`: Configures adapters, logging, and LLM providers

## Development Conventions

### Project Structure
```
mahavishnu/
├── pyproject.toml          # Dependencies: oneiric, typer, airflow, crewai, langgraph, agno, etc.
├── README.md
├── IMPLEMENTATION_PLAN.md  # Implementation plan
├── mahavishnu/
│   ├── __init__.py
│   ├── core/               # Oneiric-powered app entry (config, logging)
│   │   ├── app.py
│   │   └── adapters/       # Oneiric adapters for engines
│   ├── cli.py              # Typer app with commands
│   ├── mcp/                # MCP server using mcp-common
│   ├── engines/            # Adapter implementations
│   │   ├── airflow_adapter.py
│   │   ├── crewai_adapter.py
│   │   ├── langgraph_adapter.py
│   │   └── agno_adapter.py
├── repos.yaml              # Your repo manifest
└── oneiric.yaml            # Oneiric config (adapters enabled, LLM keys)
```

### Adapter Interface

All orchestrator adapters implement the `OrchestratorAdapter` base class:

```python
class OrchestratorAdapter(ABC):
    @abstractmethod
    def execute(self, task: Dict[str, Any], repos: List[str]) -> Dict[str, Any]:
        pass
```

### Configuration Files

#### repos.yaml
Repository manifest defining projects and their tags:
```yaml
repos:
  - path: "/path/to/repo1"
    tags: ["backend", "python"]
    description: "Backend services repository"
```

#### oneiric.yaml
Application configuration:
```yaml
adapters:
  airflow: true
  crewai: true
  langgraph: true
  agno: true

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    - type: file
      filename: logs/mahavishnu.log
    - type: console

llm_providers:
  openai:
    api_key: ${OPENAI_API_KEY}
    model: gpt-4
```

## Key Features

1. **Multi-engine Support**: Seamlessly switch between Airflow, CrewAI, LangGraph, and Agno
2. **Repository Management**: Organize and operate on repositories using tags
3. **CLI Interface**: Intuitive command-line interface powered by Typer
4. **MCP Server**: Machine Learning Communication Protocol server for tool integration
5. **Configurable**: Flexible configuration via Oneiric framework

## Development

To contribute to Mahavishnu:

1. Fork the repository
2. Create a virtual environment: `uv venv`
3. Install in editable mode: `uv pip install -e .`
4. Make your changes
5. Submit a pull request

## Current Status

Based on the implementation plan, the project is in development with the foundation (Phase 1) completed and work ongoing in Phase 2 (Engine Integration). The core architecture is in place with basic CLI functionality and adapter interfaces implemented.