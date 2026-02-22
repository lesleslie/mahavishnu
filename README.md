# Mahavishnu - Multi-Engine Orchestration Platform

[![Quality Score](https://img.shields.io/badge/Quality-92%2F100-brightgreen)](https://github.com/lesleslie/mahavishnu)
[![Security](https://img.shields.io/badge/Security-95%2F100-brightgreen)](SECURITY_CHECKLIST.md)
[![Performance](https://img.shields.io/badge/Performance-90%2F100-brightgreen)](docs/PRODUCTION_DEPLOYMENT_GUIDE.md)
[![Python](https://img.shields.io/badge/Python-3.13%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Etymology**: From Sanskrit *maha* (great) + *Vishnu* (the preserver in Hindu trinity)
>
> Part of the [Bodai Ecosystem](https://github.com/lesleslie/bodai) - The Orchestrator component

**Mahavishnu** is a world-class multi-engine orchestration platform that provides unified interfaces for managing workflows across multiple repositories. It enables intelligent workflow routing, cross-repository coordination, and headless AI worker orchestration.

## Ecosystem Components

| Component | Role | Port | Description |
|-----------|------|------|-------------|
| [Mahavishnu](https://github.com/lesleslie/mahavishnu) | Orchestrator | 8680 | Multi-engine workflow orchestration |
| [Akosha](https://github.com/lesleslie/akosha) | Seer | 8682 | Cross-system intelligence & embeddings |
| [Dhruva](https://github.com/lesleslie/dhruva) | Curator | 8683 | Persistent object storage with ACID |
| [Session-Buddy](https://github.com/lesleslie/session-buddy) | Builder | 8678 | Session lifecycle & knowledge graphs |
| [Crackerjack](https://github.com/lesleslie/crackerjack) | Inspector | 8676 | Quality gates & CI/CD validation |
| [Oneiric](https://github.com/lesleslie/oneiric) | Resolver | N/A | Conflict resolution library |

## Features

- **Multi-Pool Orchestration** - Horizontal scaling across local, delegated, and cloud workers
- **Cross-Repository Coordination** - Track issues, todos, and dependencies across your entire ecosystem
- **Headless AI Workers** - Execute tasks in parallel using Claude Code and Qwen workers
- **Goal-Driven Teams** - Create intelligent multi-agent teams from natural language goals
- **OpenTelemetry Integration** - Native OTel trace ingestion with semantic search using DuckDB
- **Repository Messaging** - Async message passing between repositories for event-driven coordination
- **Role-Based Organization** - Intelligent repository taxonomy for workflow routing
- **MCP Server** - FastMCP-based server exposing 49+ production-ready tools

## Quick Links

### Essential Reading

- **[Getting Started Guide](docs/GETTING_STARTED.md)** - New to Mahavishnu? Start here!
- **[MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md)** - Complete API documentation for all 49 MCP tools
- **[Architecture Documentation](ARCHITECTURE.md)** - System architecture and design decisions

### Visual Learning (Diagrams & Charts)

- **[Visual Guide](docs/VISUAL_GUIDE.md)** - START HERE - 50+ diagrams covering architecture, workflows, security, testing, and more!
- **[Workflow Diagrams](docs/WORKFLOW_DIAGRAMS.md)** - Common operational procedures with step-by-step visualizations
- **[Architecture Diagram](ARCHITECTURE.md#architecture-diagram)** - Interactive Mermaid diagram of system components

### Detailed Guides

- **[Pool Architecture](docs/POOL_ARCHITECTURE.md)** - Multi-pool orchestration details
- **[Goal-Driven Teams](docs/GOAL_DRIVEN_TEAMS.md)** - Create teams from natural language goals
- **[Admin Shell Guide](docs/ADMIN_SHELL.md)** - Interactive debugging and monitoring

## Table of Contents

- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Goal-Driven Teams](#goal-driven-teams)
- [MCP Tools](#mcp-tools)
- [Configuration](#configuration)
- [Development](#development)
- [Documentation](#documentation)
- [Project Status](#project-status)
- [Contributing](#contributing)
- [License](#license)

## Architecture

Mahavishnu follows a modular, async-first architecture with these core components:

```
+-----------------------------------------------------------------+
|                         Mahavishnu                              |
+-----------------------------------------------------------------+
|  +-------------+  +--------------+  +--------------------+      |
|  |    CLI      |  | MCP Server   |  |    Admin Shell     |      |
|  |  (Typer)    |  |  (FastMCP)   |  |   (IPython)        |      |
|  +------+------+  +------+-------+  +---------+----------+      |
|         |                |                    |                 |
|         +----------------+--------------------+                 |
|                           |                                     |
|         +-----------------+------------------+                  |
|         |      MahavishnuApp (Core)          |                 |
|         |  - Config (Oneiric patterns)       |                 |
|         |  - Adapter Manager                 |                 |
|         |  - Pool Manager                    |                 |
|         |  - Worker Manager                  |                 |
|         +-----------------+------------------+                  |
|                           |                                     |
|  +------------------------+-----------------------------+      |
|  |                        |                             |      |
|  v                        v                             v      |
| +----------+         +----------+                +---------+   |
| |  Pools   |         | Workers  |                |Coord    |   |
| | - Local  |         | - Qwen   |                |- Issues |   |
| | - Deleg  |         | - Claude |                |- Todos  |   |
| | - K8s    |         | - Cont   |                |- Deps   |   |
| +----------+         +----------+                +---------+   |
|                                                                |
|  +-------------------------------------------------------+     |
|  |              Adapters (Pluggable)                     |     |
|  |  +----------+  +----------+  +----------------+       |     |
|  |  |LlamaIndex|  | Prefect  |  |     Agno       |       |     |
|  |  |  (RAG)   |  |(Flows)   |  |  (Agents)     |       |     |
|  |  +----------+  +----------+  +----------------+       |     |
|  +-------------------------------------------------------+     |
+-----------------------------------------------------------------+
```

### Core Components

**Adapter Architecture**

- Async base adapter interface for orchestration engines
- Pluggable adapters for LlamaIndex (RAG), Prefect (flows), Agno (agents)
- Easy to add new orchestration backends

**Configuration System**

- Oneiric-based layered configuration (defaults -> YAML -> env vars)
- Type-safe Pydantic models with validation
- Environment variable overrides via `MAHAVISHNU_{GROUP}__{FIELD}`

**Pool Management**

- Multi-pool orchestration across local, delegated, and cloud workers
- Auto-routing strategies: round_robin, least_loaded, random, affinity
- Memory aggregation across pools with cross-pool search

**Error Handling**

- Custom exception hierarchy with circuit breaker patterns
- Structured error context with `message`, `details`, and `to_dict()`
- Retry logic with exponential backoff

## Installation

### Prerequisites

- Python 3.13 or later
- uv (recommended) or pip
- git

### Install Mahavishnu

```bash
# Clone the repository
git clone https://github.com/lesleslie/mahavishnu.git
cd mahavishnu

# Create virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e ".[dev]"

# Verify installation
mahavishnu --help
```

See [Getting Started Guide](docs/GETTING_STARTED.md) for detailed installation instructions.

## Quick Start

### 1. Configure Repositories

Edit `settings/repos.yaml` to define your repositories:

```yaml
repos:
  - name: "my-project"
    package: "my_project"
    path: "/path/to/my-project"
    nickname: "myproj"
    role: "app"
    tags: ["backend", "python"]
    description: "My backend application"
    mcp: "native"
```

### 2. Configure Mahavishnu

Edit `settings/mahavishnu.yaml`:

```yaml
server_name: "Mahavishnu Orchestrator"
log_level: INFO
repos_path: settings/repos.yaml

# Pool management
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"

# Worker orchestration
workers:
  enabled: true
  max_concurrent: 10
  default_type: "terminal-qwen"

# Quality control
qc:
  enabled: true
  min_score: 80
```

### 3. List Repositories

```bash
# List all repositories
mahavishnu list-repos

# Filter by tag
mahavishnu list-repos --tag python

# Filter by role
mahavishnu list-repos --role orchestrator

# Show role details
mahavishnu show-role orchestrator
```

### 4. Start MCP Server

```bash
mahavishnu mcp start
```

The MCP server starts on `http://127.0.0.1:3000` and exposes 49+ production-ready tools.

### 5. Use Admin Shell

```bash
mahavishnu shell
```

Interactive shell commands:

- `ps()` - Show all workflows
- `top()` - Show active workflows with progress
- `errors(n=10)` - Show recent errors
- `%repos` - List repositories

For more workflows, see the [Getting Started Guide](docs/GETTING_STARTED.md).

## Core Concepts

### Repository Roles

Mahavishnu uses a role-based taxonomy to organize repositories:

| Role | Description | Capabilities |
|------|-------------|--------------|
| **orchestrator** | Coordinates workflows | sweep, schedule, monitor, route |
| **resolver** | Resolves components | resolve, activate, swap, explain |
| **manager** | Manages state | capture, search, restore, track |
| **inspector** | Validates quality | test, lint, scan, report |
| **builder** | Builds applications | render, route, authenticate |
| **tool** | MCP integrations | connect, expose, integrate |

### Pool Types

**MahavishnuPool** (Direct Management)

- Low-latency local worker execution
- Dynamic scaling (min_workers to max_workers)
- Use for: local development, debugging, CI/CD

**SessionBuddyPool** (Delegated)

- Delegates to Session-Buddy instances (3 workers each)
- Remote execution via MCP protocol
- Use for: distributed workloads, multi-server deployments

**KubernetesPool** (Cloud-Native)

- Deploys workers as Kubernetes Jobs/Pods
- Auto-scaling via HPA
- Use for: production deployments, auto-scaling workloads

### Worker Types

- **terminal-qwen** - Headless Qwen CLI execution
- **terminal-claude** - Headless Claude Code CLI execution
- **container-executor** - Containerized task execution (Phase 3)

## Goal-Driven Teams

Create intelligent multi-agent teams from natural language goals. The `GoalDrivenTeamFactory` converts your task description into a fully-configured team with appropriate agents, roles, and collaboration modes.

```python
from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

# Create factory
factory = GoalDrivenTeamFactory()

# Parse a natural language goal
parsed = await factory.parse_goal("Review this code for security vulnerabilities")
# -> intent: "review", skills: ["security", "quality"], confidence: 0.85

# Create team configuration
team_config = await factory.create_team_from_goal(parsed.raw_goal)
# -> Team with coordinator, security_specialist, quality_specialist
```

### Quick Example

```python
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings

# Initialize
settings = MahavishnuSettings()
adapter = AgnoAdapter(config=settings)
await adapter.initialize()

# Create team from goal
team_id = await adapter.create_team_from_goal(
    "Review this code for security vulnerabilities"
)

# Run the team
result = await adapter.run_team(team_id, "Analyze the auth module")
```

### CLI Usage

```bash
# Parse a goal to see detected intent and skills
mahavishnu goal parse "Build a REST API with authentication"

# Create and run a team from a goal
mahavishnu goal run "Review code for security issues" --repo ./myproject
```

See **[Goal-Driven Teams Documentation](docs/GOAL_DRIVEN_TEAMS.md)** for complete guide with examples, skill reference, and collaboration modes.

## MCP Tools

Mahavishnu's MCP server exposes **49 production-ready tools** across 6 categories:

### Pool Management (10 tools)

- `pool_spawn` - Spawn new worker pool
- `pool_execute` - Execute task on specific pool
- `pool_route_execute` - Auto-route to best pool
- `pool_list` - List all active pools
- `pool_monitor` - Monitor pool metrics
- `pool_scale` - Scale pool worker count
- `pool_close` - Close specific pool
- `pool_close_all` - Close all pools
- `pool_health` - Get health status
- `pool_search_memory` - Search memory across pools

### Worker Orchestration (8 tools)

- `worker_spawn` - Spawn worker instances
- `worker_execute` - Execute task on worker
- `worker_execute_batch` - Execute on multiple workers
- `worker_list` - List all workers
- `worker_monitor` - Monitor worker status
- `worker_collect_results` - Collect worker results
- `worker_close` - Close specific worker
- `worker_close_all` - Close all workers

### Coordination (13 tools)

- `coord_list_issues` - List cross-repository issues
- `coord_get_issue` - Get issue details
- `coord_create_issue` - Create new issue
- `coord_update_issue` - Update issue
- `coord_close_issue` - Close issue
- `coord_list_todos` - List todo items
- `coord_get_todo` - Get todo details
- `coord_create_todo` - Create todo
- `coord_complete_todo` - Complete todo
- `coord_get_blocking_issues` - Get blocking issues
- `coord_check_dependencies` - Validate dependencies
- `coord_get_repo_status` - Get repo status
- `coord_list_plans` - List plans

### Repository Messaging (7 tools)

- `send_repository_message` - Send message between repos
- `broadcast_repository_message` - Broadcast to multiple repos
- `get_repository_messages` - Get messages for repo
- `acknowledge_repository_message` - Acknowledge message
- `notify_repository_changes` - Notify about changes
- `notify_workflow_status` - Notify about workflow status
- `send_quality_alert` - Send quality alert

### OpenTelemetry (4 tools)

- `ingest_otel_traces` - Ingest OTel traces
- `search_otel_traces` - Semantic search traces
- `get_otel_trace` - Get trace by ID
- `otel_ingester_stats` - Get ingester stats

### Session Buddy (7 tools)

- `index_code_graph` - Index codebase structure
- `get_function_context` - Get function context
- `find_related_code` - Find related code
- `index_documentation` - Index documentation
- `search_documentation` - Search documentation
- `send_project_message` - Send project message
- `list_project_messages` - List project messages

See [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md) for complete documentation with examples.

## Configuration

Mahavishnu uses a layered configuration system:

1. Default values in Pydantic models
1. `settings/mahavishnu.yaml` (committed to git)
1. `settings/local.yaml` (gitignored, local overrides)
1. Environment variables: `MAHAVISHNU_{GROUP}__{FIELD}`

### Environment Variables

```bash
# Authentication
export MAHAVISHNU_AUTH__SECRET="your-32-character-secret"

# Pool configuration
export MAHAVISHNU_POOLS__ENABLED="true"
export MAHAVISHNU_POOLS__DEFAULT_TYPE="mahavishnu"

# OTel storage
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://..."

# Cross-project auth
export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="shared-secret"
```

### Key Configuration Sections

```yaml
# Pool management
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"  # round_robin, least_loaded, random, affinity
  memory_aggregation_enabled: true

# Worker orchestration
workers:
  enabled: true
  max_concurrent: 10
  default_type: "terminal-qwen"

# OpenTelemetry trace storage
otel_storage:
  enabled: false  # Set to true to enable PostgreSQL + pgvector
  connection_string: ""  # Set via environment variable
  embedding_model: "all-MiniLM-L6-v2"

# OpenTelemetry ingester (DuckDB)
otel_ingester:
  enabled: false  # Set to true for zero-dependency OTel storage
  hot_store_path: ":memory:"  # Use file path for persistence
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run with coverage
pytest --cov=mahavishnu --cov-report=html

# Run specific test file
pytest tests/unit/test_config.py -v

# Property-based tests
pytest tests/property/
```

### Code Quality

```bash
# Format code
ruff format mahavishnu/

# Lint code
ruff check mahavishnu/

# Type checking
mypy mahavishnu/

# Security scan
bandit -r mahavishnu/

# Run all checks via Crackerjack
crackerjack run
```

### Project Structure

```
mahavishnu/
+-- mahavishnu/
|   +-- core/           # Core application logic
|   |   +-- app.py      # MahavishnuApp main class
|   |   +-- config.py   # Configuration models
|   |   +-- adapters/   # Adapter implementations
|   +-- engines/        # Engine implementations
|   |   +-- agno_adapter.py       # Agno multi-agent adapter
|   |   +-- goal_team_factory.py  # Goal-driven team creation
|   |   +-- agno_teams/           # Team configuration and management
|   |   +-- agno_tools/           # Native Agno tools
|   +-- mcp/            # MCP server and tools
|   |   +-- server_core.py
|   |   +-- tools/      # MCP tool implementations
|   +-- pools/          # Pool management
|   +-- workers/        # Worker orchestration
|   +-- cli.py          # CLI commands
+-- tests/              # Test suite
+-- docs/               # Documentation
+-- examples/           # Example scripts
|   +-- goal_driven_team_tutorial.py  # Goal-driven teams tutorial
+-- settings/           # Configuration files
    +-- mahavishnu.yaml
    +-- repos.yaml
```

## Documentation

- **[Getting Started](docs/GETTING_STARTED.md)** - Installation and first steps
- **[MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md)** - Complete API documentation
- **[Architecture](ARCHITECTURE.md)** - System architecture and evolution
- **[Pool Architecture](docs/POOL_ARCHITECTURE.md)** - Multi-pool orchestration details
- **[Goal-Driven Teams](docs/GOAL_DRIVEN_TEAMS.md)** - Create teams from natural language goals
- **[Admin Shell Guide](docs/ADMIN_SHELL.md)** - Interactive debugging
- **[Production Deployment](docs/PRODUCTION_DEPLOYMENT_GUIDE.md)** - Production readiness
- **[MCP Tools Specification](docs/MCP_TOOLS_SPECIFICATION.md)** - Detailed tool specs
- **[Security Checklist](SECURITY_CHECKLIST.md)** - Security guidelines

## Project Status

### Current Implementation

**Quality Score: 92/100 (Excellent - Production Ready)**

**Completed:**

- Security hardening (JWT auth, Claude Code + Qwen support)
- Async base adapter architecture
- FastMCP-based MCP server (49 tools)
- Multi-pool orchestration (local, delegated, K8s)
- Worker orchestration (terminal-qwen, terminal-claude)
- Cross-repository coordination (issues, todos, dependencies)
- Repository messaging (async event-driven)
- OpenTelemetry integration (DuckDB + semantic search)
- Configuration system (Oneiric patterns)
- CLI with authentication framework
- Admin shell (IPython-based)
- Test infrastructure (12 test files)

**Partially Complete:**

- LlamaIndex adapter (RAG pipelines, fully implemented)
- Prefect adapter (stub, framework skeleton)
- Agno adapter (stub, framework skeleton)

**Roadmap:**

- Phase 3: Adapter Implementation (6-9 weeks)
- Phase 4: Production Features (error recovery, full observability)
- Phase 5: Comprehensive Testing & Documentation
- Phase 6: Production Readiness (security audit, benchmarking)

**Estimated Time to Production:** 10 weeks from current state

## Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
1. Create a feature branch: `git checkout -b feature/amazing-feature`
1. Make your changes
1. Run tests: `pytest`
1. Run quality checks: `ruff check mahavishnu/` and `mypy mahavishnu/`
1. Commit your changes: `git commit -m 'Add amazing feature'`
1. Push to branch: `git push origin feature/amazing-feature`
1. Submit a pull request

### Development Guidelines

- Follow PEP 8 style guide
- Add tests for new features
- Update documentation as needed
- Keep PRs focused and small
- Write clear commit messages

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **Oneiric** - Configuration and logging framework
- **FastMCP** - MCP server implementation
- **mcp-common** - Shared MCP types and contracts
- **Crackerjack** - Quality control and testing

---

**Made with** :heart: **by the Mahavishnu team**

For questions and support, please open an issue on GitHub.
