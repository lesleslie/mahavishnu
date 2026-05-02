# Mahavishnu Orchestrate

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![Framework: FastMCP](https://img.shields.io/badge/framework-FastMCP-0ea5e9)](https://github.com/jlowin/fastmcp)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.13+](https://img.shields.io/badge/python-3.13%2B-green)](https://www.python.org/downloads/)

> **Etymology**: From Sanskrit *maha* (great) + *Vishnu* (the preserver in Hindu trinity)
>
> Part of the [Bodai Ecosystem](https://github.com/lesleslie/bodai) - The Orchestrator component

**Mahavishnu** is the internal control plane for the Bodai ecosystem: a multi-repo, multi-engine, async-first orchestration system for coordinating work across our own repositories, MCP services, and AI-capable backends. It enables workflow routing, cross-repository coordination, operational tooling, and headless worker orchestration.

Mahavishnu is maintained first as ecosystem infrastructure for Bodai-owned repos. Some parts are reusable and may have future commercial value, but the current product posture is internal orchestration rather than a polished general-purpose external platform.

## Quality & CI

Crackerjack is the standard quality-control and CI/CD gate across Mahavishnu and the broader Bodai ecosystem. Prefer Crackerjack-aligned local validation before relying on narrower repo-only checks.

## Ecosystem Components

| Component | Role | Port | Description |
|-----------|------|------|-------------|
| [Mahavishnu](https://github.com/lesleslie/mahavishnu) | Orchestrator | 8680 | Multi-engine workflow orchestration |
| [Akosha](https://github.com/lesleslie/akosha) | Seer | 8682 | Cross-system intelligence & embeddings |
| [Dhara](https://github.com/lesleslie/dhara) | Curator | 8683 | Persistent object storage with ACID |
| [Session-Buddy](https://github.com/lesleslie/session-buddy) | Builder | 8678 | Session lifecycle & knowledge graphs |
| [Crackerjack](https://github.com/lesleslie/crackerjack) | Inspector | 8676 | Quality gates & CI/CD validation |
| [Oneiric](https://github.com/lesleslie/oneiric) | Foundation | N/A | Component resolution, lifecycle management, adapter system, action kits, domain bridges, runtime orchestration, remote delivery |

## Positioning

Mahavishnu is best understood as an ecosystem control plane, not as a general-purpose coding agent. Its current sweet spot is coordinating repo-centric workflows, tools, and services across the Bodai stack.

Commercially, the most plausible future niche is a narrow B2B control plane for AI-native engineering teams managing many repos, tools, and agent workflows. That is a possible direction, not the current primary product shape.

## Capabilities

### Implemented and actively used

- **Multi-repo orchestration** - Coordinate workflows across Bodai-owned repositories and services
- **MCP server surface** - FastMCP-based server exposing orchestration, coordination, and operational tools
- **Cross-repository coordination** - Track issues, todos, dependencies, and status across the ecosystem
- **Repository messaging** - Async message passing between repositories for event-driven coordination
- **Headless worker orchestration** - Execute tasks in parallel using terminal-based and adapter-backed workers
- **Goal-driven teams** - Create multi-agent teams from natural-language goals
- **OpenTelemetry ingestion and search** - Ingest traces and search them semantically
- **Role-based organization and routing** - Classify repos and route work by role and task type

### Implemented but uneven in maturity

- **Multi-pool execution** - Local and delegated pools are real; some cloud-oriented paths are less mature than the core local control plane
- **Multiple orchestration adapters** - Prefect, Agno, and LlamaIndex integrations exist, but operator maturity varies by workflow and deployment context
- **Observability and monitoring** - Present across metrics, health, and WebSocket surfaces, but some surrounding docs and dashboards are still catching up

### Experimental or planned edges

- **Broader cloud pool execution** - Treat specialized cloud/GPU paths as experimental unless validated for the target workflow
- **Autonomous skill synthesis / self-improvement loops** - Supporting pieces exist, but fully autonomous self-modification is not the current operating model

## Orchestrator Landscape

This is the short version of where each system fits. It is not a scorecard.

Legend:

- `shipped` = already implemented in Bodai or Mahavishnu today
- `external` = comparison-only reference from another project

| System | Primary role | Boundary in Bodai | Status | Use when |
|--------|--------------|-------------------|--------|----------|
| Hermes Agent | End-user agent runtime | External reference; borrow UX/runtime patterns selectively | external | You want a user-facing assistant/runtime first |
| OpenClaw | Channel-aware gateway/runtime | Shipped delivery integration; not the canonical control plane | shipped | You need message delivery, handoffs, or channel operations |
| Mahavishnu | Control plane / orchestrator | Canonical internal control plane | shipped | You want to orchestrate work across many Bodai repos and services |
| Agno | Interactive agent engine | Canonical runtime adapter behind Mahavishnu | shipped | You want an embedded agent runtime inside your own system |
| Prefect | Durable workflow engine | Canonical workflow engine | shipped | You need reliable batch or scheduled automation |
| LlamaIndex | Retrieval / knowledge engine | Canonical retrieval engine | shipped | You need knowledge-grounded responses or RAG |

Practical guidance:

- Use **Hermes** if the product is the assistant itself.
- Use **OpenClaw** if the product is channel-aware delivery or communications.
- Use **Mahavishnu** if the product is cross-repo orchestration and control.
- Use **Agno** if the product needs an agent loop inside a system you already own.
- Use **Prefect** if the product needs dependable workflows, schedules, and retries.
- Use **LlamaIndex** if the product needs a retrieval and knowledge plane.

Core Bodai control-plane components today are:

- Mahavishnu
- Agno
- Prefect
- LlamaIndex

Supporting delivery and ecosystem components include:

- OpenClaw
- Hermes-style entry points as a reference pattern
- Session-Buddy
- Akosha
- Crackerjack
- Oneiric

### Symbiotic usage

Hermes and OpenClaw can complement Mahavishnu instead of competing with it.

- **Hermes in front of Mahavishnu**: use Hermes as the user-facing assistant runtime for chat, voice, and interactive task intake, then hand orchestration, policy, and long-lived state to Mahavishnu.
- **OpenClaw in front of Mahavishnu**: use OpenClaw as a channel-aware delivery layer for handoffs, notifications, and message routing, then let Mahavishnu decide what should happen next.
- **Mahavishnu in the middle**: keep it as the control plane that owns routing, approvals, workflow state, and ecosystem coordination.

That gives the system a clean split:

- Hermes and OpenClaw handle entry points and delivery
- Mahavishnu handles orchestration and policy
- Agno, Prefect, and LlamaIndex handle specialized execution backends

### Learning and skills

Hermes advertises a built-in learning loop: it persists useful context, searches prior conversations, and refines skills over time. In Bodai today, we have supporting pieces, not a finished autonomous loop.

Supporting pieces today:

- Session-Buddy for checkpoints and session lifecycle
- `mahavishnu/memory/MEMORY.md` for durable memory
- Akosha-backed semantic search and cross-system retrieval
- skill-oriented specs and recovery workflows in `docs/superpowers/specs/`

Planned piece:

- a fully automatic skill synthesis loop that drafts, validates, and activates new skills on its own

The recommended path is to add that as a bounded ecosystem feature:

1. capture successful sessions and outcomes
2. retrieve similar prior work
3. draft or update a skill
4. require review before activation
5. surface the review queue in the TUI

That gets the benefit of Hermes-style self-improvement without making the runtime self-modifying.

## Quick Links

- [Getting Started Guide](docs/GETTING_STARTED.md)
- [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md)
- [Architecture Documentation](docs/architecture/ARCHITECTURE.md)
- [Visual Guide](docs/VISUAL_GUIDE.md)
- [Workflow Diagrams](docs/WORKFLOW_DIAGRAMS.md)
- [Pool Architecture](docs/POOL_ARCHITECTURE.md)
- [Goal-Driven Teams](docs/GOAL_DRIVEN_TEAMS.md)
- [Admin Shell Guide](docs/ADMIN_SHELL.md)

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

### Capability Maturity Snapshot

This table clarifies current maturity so multi-engine expectations match implementation status.

| Capability | Status | Notes |
|-----------|--------|-------|
| Multi-repo orchestration | Implemented | Repository manifest (`settings/repos.yaml`), cross-repo coordination, dependency/status tooling |
| Async orchestration runtime | Implemented | Async-first core, async messaging, concurrent worker and pool execution |
| Multi-pool execution (local/delegated/K8s) | Implemented | Routing strategies and pool health/monitoring are implemented |
| LlamaIndex engine adapter | Implemented | RAG pipeline integration is implemented |
| Prefect engine adapter | Implemented | Full Prefect 3.x SDK integration with flows, deployments, schedules, and task orchestration (1,800+ LOC) |
| Agno engine adapter | Implemented | Multi-agent teams with MCP tools, Ollama/Claude/OpenAI support, and agent lifecycle management (1,400+ LOC) |

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

The MCP server starts on `http://127.0.0.1:3000` and exposes 49+ orchestration and coordination tools.

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

### Async Orchestration Flow

A typical async orchestration path looks like this:

1. Load repositories from `settings/repos.yaml`.
1. Classify task intent and select an engine and worker strategy.
1. Route execution to the best pool (`least_loaded`, `round_robin`, `random`, or `affinity`).
1. Execute concurrently on workers (or delegated pools) with async task handling.
1. Emit coordination and repository-messaging events for downstream repos and services.
1. Observe health and status, then apply retries/backoff where configured.

Minimal example (Python):

```python
from mahavishnu.core.app import MahavishnuApp

app = MahavishnuApp()
await app.initialize()

result = await app.pool_manager.route_task(
    prompt="Run quality checks on tagged backend repos",
    strategy="least_loaded",
)
print(result)
```

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
- Use for: deployed workloads, auto-scaling workloads

### Worker Types

- **terminal-qwen** - Headless Qwen CLI execution
- **terminal-claude** - Headless Claude Code CLI execution
- **terminal-codex** - Headless Codex CLI execution in one-shot mode with marker-based completion
- **terminal-openclaw** - Headless OpenClaw agent execution for local communication and delivery tasks
- **terminal-deepagents** - Headless DeepAgents CLI execution in one-shot mode with marker-based completion
- **terminal-clai** - Headless CLAI CLI execution in one-shot mode with marker-based completion
- **gateway-openclaw** - Preferred OpenClaw gateway worker over HTTP JSON-RPC for channel-aware communication tasks
- **container-executor** - Containerized task execution (Phase 3)

Worker selection policy:

- See [Worker Classification Policy](docs/policies/worker-classification-policy.md) for the rule set that decides terminal vs gateway vs external reference.

### Routing Notes

- Communication-style tasks such as notifications, handoffs, replies, inbox triage, and channel delivery prefer **gateway-openclaw** when `OPENCLAW_GATEWAY_URL` is configured, and fall back to **terminal-openclaw** otherwise.
- Coding tasks remain on coding workers such as Qwen and Claude unless you explicitly request OpenClaw.

### Optional Worker CLI Profiles

These worker CLIs are optional and can be enabled via extras:

```bash
# Enable metadata profiles for alternate CLI workers
uv sync --extra worker-alt-cli

# Or enable specific profiles
uv sync --extra worker-openclaw --extra worker-deepagents --extra worker-clai
```

Important: these extras are profile flags only. You must install the actual CLI binaries
(`openclaw`, `deepagents-cli`, `clai`) so they are available on your `PATH`.

Structured output note:
- `terminal-openclaw` is JSON-native and completes on valid JSON output.
- `terminal-codex` uses `codex exec --json` and completes on an explicit sentinel marker.
- `terminal-deepagents` uses `deepagents-cli --non-interactive --quiet --no-stream` and completes on an explicit sentinel marker because the verified task-run path is plain text.
- `terminal-clai` uses `clai --no-stream` and completes on an explicit sentinel marker because the verified one-shot path is plain text.

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

Mahavishnu's MCP server exposes **49 tools** across 6 categories:

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

Note: Crackerjack is the **ecosystem-wide CI/quality gate runner** for Bodai/Mahavishnu repos. Use it as the authoritative source of CI results across components.

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
- **[Architecture](docs/architecture/ARCHITECTURE.md)** - System architecture and evolution
- **[Pool Architecture](docs/POOL_ARCHITECTURE.md)** - Multi-pool orchestration details
- **[Goal-Driven Teams](docs/GOAL_DRIVEN_TEAMS.md)** - Create teams from natural language goals
- **[Admin Shell Guide](docs/ADMIN_SHELL.md)** - Interactive debugging
- **[Deployment Guide](docs/PRODUCTION_DEPLOYMENT_GUIDE.md)** - Deployment checklist and operational notes
- **[MCP Tools Specification](docs/MCP_TOOLS_SPECIFICATION.md)** - Detailed tool specs
- **[Codex + Claude Routing Playbook](docs/integrations/CODEX_CLAUDE_ENGINE_ROUTING_PLAYBOOK.md)** - Configure agents to use Mahavishnu engines and multi-repo orchestration consistently
- **[Security Checklist](SECURITY_CHECKLIST.md)** - Security guidelines

### LLM Gateway Docs

- **[LLM Inventory](docs/llm-inventory.md)** - Current client routing, direct-provider state, and cross-repo LLM callsite inventory
- **[Bifrost Reactivation Runbook](docs/bifrost-reactivation-runbook.md)** - How to bring the dormant local gateway back later
- **[Bifrost Gateway Plan](docs/plans/2026-04-08-bifrost-gateway-plan.md)** - Implementation history, milestones, and paused cutover status

## Project Status

### Current Implementation

**Quality Score: 92/100 (Validated and implemented)**

Important scope note: Mahavishnu is validated for multi-repo orchestration, async coordination, and pool/worker routing. Engine adapter maturity varies by adapter (see Capability Maturity Snapshot).

**Completed:**

- Security hardening (JWT auth, Claude Code + Qwen support)
- Async base adapter architecture
- FastMCP-based MCP server (49 tools)
- Multi-pool orchestration (local, delegated, K8s)
- Worker orchestration (Qwen, Claude, OpenClaw terminal/gateway)
- Cross-repository coordination (issues, todos, dependencies)
- Repository messaging (async event-driven)
- OpenTelemetry integration (DuckDB + semantic search)
- Configuration system (Oneiric patterns)
- CLI with authentication framework
- Admin shell (IPython-based)
- Test infrastructure (12 test files)

**Engine Adapter Maturity:**

- LlamaIndex adapter (RAG pipelines, fully implemented)
- Prefect adapter (fully implemented — flows, deployments, schedules)
- Agno adapter (fully implemented — multi-agent teams, MCP tools)

**Roadmap:**

- Phase 4: Deployment Features (error recovery, full observability)
- Phase 5: Comprehensive Testing & Documentation
- Phase 6: Release Readiness (security audit, benchmarking)

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

- **Oneiric** - Platform foundation: component resolution, lifecycle management, adapter system, action kits, domain bridges, runtime orchestration, remote delivery
- **FastMCP** - MCP server implementation
- **mcp-common** - Shared MCP types and contracts
- **Crackerjack** - Quality control and testing

---

**Made with** :heart: **by the Mahavishnu team**

For questions and support, please open an issue on GitHub.
