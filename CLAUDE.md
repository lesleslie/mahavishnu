# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mahavishnu is a multi-engine orchestration platform that provides a unified interface for managing workflows across multiple repositories. It supports Airflow, CrewAI, LangGraph, and Agno through a common adapter pattern.

### Key Architectural Patterns

**Oneiric Integration**: All configuration uses Oneiric patterns with layered loading:
1. Default values in Pydantic models
2. `settings/mahavishnu.yaml` (committed)
3. `settings/local.yaml` (gitignored, local dev)
4. Environment variables `MAHAVISHNU_{FIELD}`

**Adapter Pattern**: All orchestration engines implement `OrchestratorAdapter` from `mahavishnu/core/adapters/base.py`. Adapters are initialized in `MahavishnuApp._initialize_adapters()` only if enabled in configuration.

**Error Handling**: Custom exception hierarchy in `mahavishnu/core/errors.py` provides structured error context with `message`, `details`, and `to_dict()` method for API responses.

**Configuration Class**: `MahavishnuSettings` extends `MCPServerSettings` from mcp-common, providing field validation, type coercion, and environment variable overrides.

## Development Commands

### Environment Setup
```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"  # Installs dev dependencies

# Or with pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_config.py

# Run with coverage
pytest --cov=mahavishnu --cov-report=html

# Run async tests specifically
pytest tests/unit/ -k "async"

# Property-based tests with Hypothesis
pytest tests/property/
```

### Code Quality
```bash
# Format code
black mahavishnu/

# Sort imports
isort mahavishnu/

# Lint
flake8 mahavishnu/

# Type check
mypy mahavishnu/

# Security scan
bandit -r mahavishnu/
safety check

# Run all checks via Crackerjack
crackerjack run
```

### MCP Server
```bash
# Start MCP server
mahavishnu mcp start

# Check MCP server status
mahavishnu mcp status

# Run health probe
mahavishnu mcp health

# Stop MCP server
mahavishnu mcp stop
```

### CLI Commands
```bash
# List all repositories
mahavishnu list-repos

# List repositories by tag
mahavishnu list-repos --tag backend

# Trigger workflow sweep
mahavishnu workflow sweep --tag backend --adapter langgraph
```

## Configuration Files

**repos.yaml**: Repository manifest with tags and metadata
```yaml
repos:
  - path: "/path/to/repo"
    tags: ["backend", "python"]
    description: "Backend services"
```

**settings/mahavishnu.yaml**: Main configuration (Oneiric-compatible)
```yaml
server_name: "Mahavishnu Orchestrator"
adapters:
  airflow: true
  crewai: true
qc:
  enabled: true
  min_score: 80
```

**settings/local.yaml**: Local overrides (gitignored)

**oneiric.yaml**: Legacy Oneiric config (still supported for backward compatibility)

## Critical Architecture Decisions

See `docs/adr/` for full Architecture Decision Records:

- **ADR 001**: Use Oneiric for configuration and logging
- **ADR 002**: MCP-first design with FastMCP + mcp-common
- **ADR 003**: Error handling with retry, circuit breakers, dead letter queues
- **ADR 004**: Adapter architecture for multi-engine support

## MCP Server Tools

All MCP tools are registered in `mahavishnu/mcp/tools/` using FastMCP decorators. See `docs/MCP_TOOLS_SPECIFICATION.md` for complete tool specifications including parameters, returns, and error handling.

## Security

See `SECURITY_CHECKLIST.md` for comprehensive security guidelines. Key points:
- All inputs must use Pydantic models for validation
- Secrets loaded from environment variables only
- JWT authentication when auth_enabled
- Path traversal prevention on all repository paths
- No shell commands with user input

## Dependency Management

Use `~=` (compatible release clause) for stable dependencies, `>=` only for early-development packages like FastMCP. See `pyproject.toml` for examples.

## Key File Locations

- **Core application**: `mahavishnu/core/app.py` - MahavishnuApp class
- **Configuration**: `mahavishnu/core/config.py` - MahavishnuSettings
- **Base adapter**: `mahavishnu/core/adapters/base.py` - OrchestratorAdapter
- **CLI**: `mahavishnu/cli.py` - Typer app
- **MCP server**: `mahavishnu/mcp/server_core.py` - FastMCP server
- **Error types**: `mahavishnu/core/errors.py` - Custom exceptions

<!-- CRACKERJACK_START -->
## Crackerjack Integration

This project uses [Crackerjack](https://github.com/yourusername/crackerjack) for quality control and AI-assisted development.

### Quick Start

```bash
# Run all quality checks
crackerjack run all

# Run with AI auto-fix enabled
crackerjack run test --ai-fix

# Check quality metrics
crackerjack status

# View execution history
crackerjack history
```

### Quality Commands

```bash
# Testing (with parallel execution)
pytest -n auto                           # Run tests in parallel
pytest -m "unit"                         # Run only unit tests
pytest -m "not slow"                     # Skip slow tests
pytest --cov=mahavishnu --cov-report=html  # Coverage report

# Code quality (Ruff)
ruff check mahavishnu/                   # Lint
ruff format mahavishnu/                  # Format
ruff check --fix mahavishnu/             # Auto-fix issues

# Type checking
pyright mahavishnu/                      # Type checking (fallback)
mypy mahavishnu/                         # Alternative type checker

# Security
bandit -r mahavishnu/                    # Security linting
safety check                             # Dependency vulnerabilities
creosote                                 # Detect unused dependencies

# Modernization & complexity
refurb mahavishnu/                       # Modern Python suggestions
codespell mahavishnu/                    # Typo detection
complexipy --max_complexity 15 mahavishnu/  # Complexity checking
```

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
def test_adapter_initialization():
    """Fast, isolated unit test."""
    pass

@pytest.mark.integration
@pytest.mark.airflow
def test_airflow_workflow_execution():
    """Integration test for Airflow adapter."""
    pass

@pytest.mark.slow
@pytest.mark.e2e
def test_full_orchestration_workflow():
    """End-to-end test (marked as slow)."""
    pass

@pytest.mark.property
@given(st.text())  # Hypothesis strategy
def test_property_based(input_data):
    """Property-based test."""
    assert len(input_data) >= 0
```

Run tests by marker:
```bash
pytest -m unit                    # Only unit tests
pytest -m "integration and airflow"  # Airflow integration tests
pytest -m "not slow"              # Skip slow tests
```

### Quality Control with Crackerjack

Crackerjack provides automated quality checks and settings management:

```bash
# Run all quality checks
crackerjack run

# Run specific checks
crackerjack run --check ruff
crackerjack run --check pytest
crackerjack run --check bandit

# Configure settings
crackerjack settings init
crackerjack settings validate
```

### Quality Gates

The project enforces these quality standards:

- **Coverage**: Minimum 80% test coverage (`--cov-fail-under=80`)
- **Complexity**: Maximum cyclomatic complexity of 15 per function
- **Timeout**: Tests timeout after 5 minutes (configurable per test)
- **Type Safety**: Strict type checking with mypy

### AI Agent Skills

Crackerjack provides AI agent skills via MCP:

```python
# Available when MCP server is connected
await mcp.call_tool("list_skills", {"skill_type": "all"})

# Find skills for specific issues
await mcp.call_tool("get_skills_for_issue", {"issue_type": "complexity"})

# Execute a skill
await mcp.call_tool("execute_skill", {
    "skill_id": "skill_abc123",
    "issue_type": "refactoring",
    "issue_data": {"message": "...", "file_path": "..."}
})
```

Available agent types:
- **RefactoringAgent**: Code restructuring and modernization
- **SecurityAgent**: Security vulnerability analysis
- **PerformanceAgent**: Performance optimization
- **TestAgent**: Test generation and improvement
- **DocumentationAgent**: Documentation enhancement

For more details, see [Crackerjack Documentation](https://github.com/yourusername/crackerjack#readme).
<!-- CRACKERJACK_END -->

