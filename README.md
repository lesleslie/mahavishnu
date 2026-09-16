# Mahavishnu Orchestrate

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![Framework: FastMCP](https://img.shields.io/badge/framework-FastMCP-0ea5e9)](https://github.com/jlowin/fastmcp)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.14+](https://img.shields.io/badge/python-3.14%2B-green)](https://www.python.org/downloads/)

> **Etymology**: From Sanskrit *maha* (great) + *Vishnu* (the preserver in Hindu trinity)
>
> Part of the [Bodai Ecosystem](https://github.com/lesleslie/bodai) - The Orchestrator component

**Mahavishnu** is the internal control plane for the Bodai ecosystem: a multi-repo, multi-engine, async-first orchestration system for coordinating work across our own repositories, MCP services, and AI-capable backends. It enables workflow routing, cross-repository coordination, operational tooling, and headless worker orchestration.

Mahavishnu is maintained as ecosystem infrastructure for Bodai-owned repos.

## Bodai Ecosystem Role

Mahavishnu is the **orchestrator** of the [Bodai ecosystem](https://github.com/lesleslie/bodai) — it coordinates work across the other components: routing tasks through worker pools, sweeping workflows across multiple Bodai repos, and managing the lifecycle of ecosystem services (Akosha, Dhara, Session-Buddy, Crackerjack, Oneiric).

Standalone, Mahavishnu is a general-purpose multi-repo orchestration system — useful for any team that needs to coordinate workflows, tools, and AI-capable backends across many repositories. See [bodai/docs](https://github.com/lesleslie/bodai) for the full integration story.

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
- **Jot inbox and workflow dispatch** - Capture, search, defer, and dispatch durable jots
- **Plan index and agent surfaces** - Inspect Dhara-backed plans and registered specialist agents

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
| Hatchet | Durable workflow engine | Optional durable workflow adapter behind Mahavishnu | shipped | You need event-driven agent loops or a Prefect alternative |
| LlamaIndex | Retrieval / knowledge engine | Canonical retrieval engine | shipped | You need knowledge-grounded responses or RAG |

Hatchet is disabled by default and requires the optional `hatchet` dependency
group plus `HATCHET_CLIENT_TOKEN` when enabled.

Practical guidance:

- Use **Hermes** if the product is the assistant itself.
- Use **OpenClaw** if the product is channel-aware delivery or communications.
- Use **Mahavishnu** if the product is cross-repo orchestration and control.
- Use **Agno** if the product needs an agent loop inside a system you already own.
- Use **Prefect** if the product needs dependable workflows, schedules, and retries.
- Use **Hatchet** if the product needs durable event-driven workflows or agent loops.
- Use **LlamaIndex** if the product needs a retrieval and knowledge plane.

### Symbiotic usage

Hermes and OpenClaw can complement Mahavishnu instead of competing with it.

- **Hermes in front of Mahavishnu**: use Hermes as the user-facing assistant runtime for chat, voice, and interactive task intake, then hand orchestration, policy, and long-lived state to Mahavishnu.
- **OpenClaw in front of Mahavishnu**: use OpenClaw as a channel-aware delivery layer for handoffs, notifications, and message routing, then let Mahavishnu decide what should happen next.
- **Mahavishnu in the middle**: keep it as the control plane that owns routing, approvals, workflow state, and ecosystem coordination.

That gives the system a clean split:

- Hermes and OpenClaw handle entry points and delivery
- Mahavishnu handles orchestration and policy
- Agno, Prefect, Hatchet, and LlamaIndex handle specialized execution backends

### Learning and skills

Mahavishnu includes an opt-in, review-gated learning pipeline that turns
recurring execution patterns into governed skill proposals:

1. **Observe** - Collect task outcomes and execution evidence from Session-Buddy.
1. **Store** - Persist evidence for later retrieval and analysis.
1. **Retrieve** - Use Akosha and Session-Buddy to find related goals, repositories, and prior evidence.
1. **Synthesize** - Cluster recurring patterns and produce sanitized `SkillDraft` artifacts.
1. **Review** - Run metadata, trigger-condition, security, and optional Crackerjack quality checks.
1. **Promote** - Human-approved drafts can be activated, deprecated, or rolled back through the skill governance registry.

The pipeline is disabled by default; enable it with `learning.enabled: true` or
`MAHAVISHNU_LEARNING__ENABLED=true`. It never auto-activates a skill: automated
checks can approve a draft for review, but activation still requires an explicit
human approval under the governance policy.

Operators can inspect and trigger the pipeline through the learning MCP tools:
`get_pipeline_status`, `list_evidence`, `trigger_synthesis`,
`list_pending_drafts`, and `get_promotion_history`. The TUI also exposes a
skill-draft review screen. See the [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md)
for the tool contracts.

## Quick Links

- [Getting Started Guide](docs/GETTING_STARTED.md)
- [CLI Reference](docs/CLI_REFERENCE.md)
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
| | - Local  |         | - Claude |                |- Issues |   |
| | - Deleg  |         | - MiniMax|                |- Todos  |   |
| | - Pi     |         | - Session-Buddy          |- Deps   |   |
| | - RunPod |         | - OpenClaw               |-Messages|   |
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
- Pluggable adapters for LlamaIndex (RAG), Prefect (flows), Agno (agents), Hatchet (durable workflows)
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

- Python 3.14 or later
- uv (recommended) or pip
- git

### Install Mahavishnu

```bash
# Clone the repository
git clone https://github.com/lesleslie/mahavishnu.git
cd mahavishnu

# Install the package and development dependency group
uv sync --group dev

# Verify installation
uv run mahavishnu --help
```

See [Getting Started Guide](docs/GETTING_STARTED.md) for detailed installation instructions.

## Quick Start

### 1. Configure Repositories

Edit `settings/ecosystem.yaml` to define your repositories. This is the
canonical repository manifest. A legacy `repos.yaml` fallback remains only for
older tooling that has not yet been migrated:

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
repos_path: settings/ecosystem.yaml

# Pool management
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"

# Worker orchestration
workers:
  enabled: true
  max_concurrent: 10
  default_type: "terminal-claude"

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

The CLI starts the MCP server on `http://127.0.0.1:8680` by default. The lower-level `FastMCPServer.start()` API defaults to port 3000 unless a port is supplied. The server currently exposes 173 tools: 27 inline core tools plus 146 profile-gated tools across 35 modules. Tool exposure is controlled by `MAHAVISHNU_TOOL_PROFILE`: `full` (default), `standard`, or `minimal`.

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

1. Load repositories from `settings/ecosystem.yaml`.
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

**PiPool** (Pi coding-agent)

- Runs the Pi coding agent through its JSON-RPC subprocess interface
- Fixed at one worker per pool; spawn additional pools for more capacity
- Requires the Pi runtime configuration and is disabled by default

**RunPodPool** (GPU Cloud)

- Serverless GPU execution via RunPod Flash API
- Register with `pool_type="runpod"`, requires `RUNPOD_API_KEY`
- Disabled by default; enable the RunPod pool in local configuration before spawning it
- Subclass `RunPodPool` and override `_build_endpoint()` for a concrete GPU handler (`GpuHandlerPool`)
- Use for: vision and ML inference workloads

### Worker Types

All workers implement the `BaseWorker` contract. Most registered worker types are
built from a small set of worker families:

- **`GenericShellWorker`** - Terminal, CLI, shell, REPL, remote, database, WebAssembly, and infrastructure workers. AI CLI extensions include `terminal-claude`, `terminal-qwen` (supported non-default), `terminal-codex`, `terminal-deepagents`, and `terminal-clai`.
- **`ApplicationWorker`** - MCP-backed application integrations exposed as `application-*` worker types.
- **Gateway workers** - Dedicated protocol workers including `gateway-openclaw`, `openhands`, `a2a`, and `terminal-crow`.
- **Isolated workers** - `apple-container`, `e2b-sandbox`, and the optional `shepherd` backend. The compatibility names `container` and `container-executor` select the automatic Apple-container-to-E2B isolation path; they are not separate container implementations.

Use `mahavishnu workers list-types --all` to inspect the complete registry and
`mahavishnu workers list-types --ready --explain` to see which types are ready
in the current environment.

Worker selection policy:

- See [Worker Classification Policy](docs/policies/worker-classification-policy.md) for the rule set that decides terminal vs gateway vs external reference.

### Routing Notes

- Communication-style tasks such as notifications, handoffs, replies, inbox triage, and channel delivery prefer **gateway-openclaw** when `OPENCLAW_GATEWAY_URL` is configured. There is no CLI fallback — operators who want local OpenClaw execution must configure the gateway URL or run OpenClaw externally (e.g., via `cc-connect` with Claude Code).
- Coding tasks remain on coding workers such as Claude or the configured cloud provider unless you explicitly request OpenClaw.

### Worker Availability and Optional Backends

Inspect worker availability and capability readiness with:

```bash
# List every registered worker type
uv run mahavishnu workers list-types --all

# Show only workers currently ready to route
uv run mahavishnu workers list-types --ready --explain
```

Optional runtime groups are installed with PEP 735 dependency groups, not project extras:

```bash
uv sync --group ai        # Pydantic AI adapter
uv sync --group gpu       # RunPod GPU pool
uv sync --group sandbox   # E2B sandbox worker
uv sync --group shepherd  # Shepherd worker backend
```

External worker CLIs must still be installed separately and available on `PATH`.

Structured output note:

- `terminal-codex` uses `codex exec --json` and completes on an explicit sentinel marker.
- `terminal-qwen` remains available as a supported non-default worker type.

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
mahavishnu team parse "Build a REST API with authentication"

# Create and run a team from a goal
mahavishnu team create --goal "Review code for security issues" --run
```

See **[Goal-Driven Teams Documentation](docs/GOAL_DRIVEN_TEAMS.md)** for complete guide with examples, skill reference, and collaboration modes.

## MCP Tools

Mahavishnu's MCP server exposes **173 tools** (146 profile-gated + 27 inline core) across 35 tool modules (see `MAHAVISHNU_TOOL_PROFILE` for gating). The detailed inventory is maintained in the [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md).

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

- `index_code_graph` - Legacy shim for code indexing; prefer `code_index.index_repo`
- `get_function_context` - Get function context
- `find_related_code` - Legacy shim; prefer `treesitter_tools`
- `index_documentation` - Legacy shim for documentation indexing; prefer `code_index.index_repo`
- `search_documentation` - Legacy shim; prefer `search_tools.hybrid_search`
- `send_project_message` - Send project message
- `list_project_messages` - List project messages

See [MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md) for complete documentation with examples.

## Configuration

Mahavishnu uses a layered configuration system:

1. Default values in Pydantic models
1. `settings/mahavishnu.yaml` (committed to git)
1. `settings/local.yaml` (gitignored, local overrides)
1. `$XDG_CONFIG_HOME/mahavishnu/config.yaml` (user configuration)
1. `$XDG_CONFIG_HOME/mahavishnu/local.yaml` (user-local overrides)
1. Environment variables: `MAHAVISHNU_{GROUP}__{FIELD}`

Oneiric uses `~/.config` when `XDG_CONFIG_HOME` is not set, so the default
user configuration locations are `~/.config/mahavishnu/config.yaml` and
`~/.config/mahavishnu/local.yaml`. User-level files override the repository
configuration; environment variables have higher priority than all layered
files. An explicit `MAHAVISHNU_CONFIG` path takes precedence over these
layers.

### Environment Variables

```bash
# Authentication
export MAHAVISHNU_AUTH__SECRET="your-32-character-secret"

# Primary LLM provider (MiniMax — OpenAI-compatible)
export MINIMAX_API_KEY="your-minimax-api-key"
export MINIMAX_BASE_URL="https://api.minimax.io/v1"  # optional override

# RunPod GPU pool (optional)
export RUNPOD_API_KEY="your-runpod-api-key"

# Hatchet durable workflow engine (optional)
export HATCHET_CLIENT_TOKEN="your-hatchet-client-token"

# Pool configuration
export MAHAVISHNU_POOLS__ENABLED="true"
export MAHAVISHNU_POOLS__DEFAULT_TYPE="mahavishnu"

# MCP tool surface (full | standard | minimal)
export MAHAVISHNU_TOOL_PROFILE="full"

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
  default_type: "terminal-claude"

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
# Run the test suite through the ecosystem quality gate
crackerjack run --run-tests

# Run with verbose progress
crackerjack run --run-tests --verbose

# Preview the validation workflow without applying fixes
crackerjack run --run-tests --dry-run
```

### Code Quality

```bash
# Run the repository quality gates
crackerjack run

# Run quality gates with verbose progress
crackerjack run --verbose
```

Crackerjack is the **ecosystem-wide CI/quality gate runner** for Bodai/Mahavishnu repos and the authoritative source of validation results across components.

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
|   +-- mcp/            # MCP server, tools, agents, and profiles
|   |   +-- server_core.py
|   |   +-- tools/      # MCP tool implementations
|   |   +-- agents/     # Registered specialist agents
|   +-- pools/          # Pool management
|   +-- workers/        # Worker orchestration
|   +-- cli/            # Typer subcommands (teams, jots, plans, monitoring, etc.)
|   +-- jot/            # Durable Jot inbox and workflow dispatch
|   +-- plan_index/     # Dhara-backed plan index
|   +-- _main_cli.py    # CLI entrypoint
+-- tests/              # Test suite
+-- docs/               # Documentation
+-- examples/           # Example scripts
|   +-- goal_driven_team_tutorial.py  # Goal-driven teams tutorial
+-- settings/           # Configuration files
    +-- mahavishnu.yaml
    +-- ecosystem.yaml
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
- **Security Checklist** - Security guidelines

### LLM Gateway Docs

- **[LLM Inventory](docs/llm-inventory.md)** - Current client routing, direct-provider state, and cross-repo LLM callsite inventory
- **[Bifrost Reactivation Runbook](docs/bifrost-reactivation-runbook.md)** - How to bring the dormant local gateway back later
- **[Bifrost Gateway Plan](docs/plans/2026-04-08-bifrost-gateway-plan.md)** - Implementation history, milestones, and paused cutover status

## Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
1. Create a feature branch: `git checkout -b feature/amazing-feature`
1. Make your changes
1. Run validation with [Crackerjack](https://github.com/lesleslie/crackerjack): `crackerjack run --run-tests`
1. Commit your changes: `git commit -m 'Add amazing feature'`
1. Push to branch: `git push origin feature/amazing-feature`
1. Submit a pull request

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Mahavishnu is built on the work of the open-source projects and infrastructure
providers below:

- **FastMCP** - MCP server framework
- **Pydantic** - Typed configuration and request validation
- **Typer** - Command-line interface framework
- **OpenTelemetry** - Tracing, metrics, and observability conventions
- **Apple Container** - Local microVM isolation on supported Apple silicon hosts
- **E2B** - Cloud sandbox isolation fallback
- **RunPod** - Serverless GPU execution backend

______________________________________________________________________

**Made with** :heart: **by the Mahavishnu team**

For questions and support, please open an issue on GitHub.
