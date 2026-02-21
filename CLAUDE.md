# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Ecosystem Context

Mahavishnu is part of the **Bodai Ecosystem** - a collection of interconnected components:

| Component | Role | Port | Description |
|-----------|------|------|-------------|
| **Mahavishnu** | Orchestrator | 8680 | Multi-engine workflow orchestration (this repo) |
| [Akosha](https://github.com/lesleslie/akosha) | Seer | 8682 | Cross-system intelligence & embeddings |
| [Dhruva](https://github.com/lesleslie/dhruva) | Curator | 8683 | Persistent object storage with ACID |
| [Session-Buddy](https://github.com/lesleslie/session-buddy) | Builder | 8678 | Session lifecycle & knowledge graphs |
| [Crackerjack](https://github.com/lesleslie/crackerjack) | Inspector | 8676 | Quality gates & CI/CD validation |
| [Oneiric](https://github.com/lesleslie/oneiric) | Resolver | N/A | Conflict resolution library |

**Key Interactions:**
- Routes tasks to **Akosha** for intelligence operations
- Persists state to **Dhruva** for recovery
- Tracks context in **Session-Buddy**
- Validates with **Crackerjack** before execution

## Project Overview

Mahavishnu is a multi-engine orchestration platform that provides a unified interface for managing workflows across multiple repositories. It currently provides:

- LlamaIndex adapter for RAG pipelines (fully implemented with Ollama embeddings)
- Prefect adapter stub (framework skeleton, no actual orchestration yet)
- Agno adapter stub (framework skeleton, no actual agent execution yet)
- **Multi-pool orchestration** for horizontal scaling across local, delegated, and cloud workers
- **WebSocket infrastructure** for real-time workflow monitoring and coordination
- **Content ingestion** system for blogs, webpages, and books
- **OpenTelemetry ingester** with semantic search using pgvector

### Key Architectural Patterns

**Oneiric Integration**: All configuration uses Oneiric patterns with layered loading:

1. Default values in Pydantic models
1. `settings/mahavishnu.yaml` (committed)
1. `settings/local.yaml` (gitignored, local dev)
1. Environment variables `MAHAVISHNU_{FIELD}`

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
# Format code (Ruff replaces black/isort)
ruff format mahavishnu/

# Lint (Ruff replaces flake8)
ruff check mahavishnu/
ruff check --fix mahavishnu/  # Auto-fix issues

# Type check (mypy or pyright fallback)
mypy mahavishnu/
pyright mahavishnu/  # Fallback option

# Security scan
bandit -r mahavishnu/
safety check

# Additional checks
creosote                    # Detect unused dependencies
refurb mahavishnu/          # Modern Python suggestions
codespell mahavishnu/        # Typo detection
complexipy --max_complexity 15 mahavishnu/  # Complexity checking

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

**Repository Management:**
```bash
# List all repositories
mahavishnu list-repos

# List repositories by tag
mahavishnu list-repos --tag backend

# List repositories by role
mahavishnu list-repos --role orchestrator

# List all available roles
mahavishnu list-roles

# Show detailed information about a specific role
mahavishnu show-role tool

# List all repository nicknames
mahavishnu list-nicknames
```

**Content Ingestion:**
```bash
# Ingest a webpage
mahavishnu ingest web --url "https://example.com"

# Ingest a blog
mahavishnu ingest blog --url "https://blog.example.com/post"

# Ingest a book (PDF/EPUB)
mahavishnu ingest book --path ~/Documents/book.pdf

# Evaluate content quality
mahavishnu quality evaluate --content-id <id>
```

**WebSocket & Monitoring:**
```bash
# Start WebSocket server for real-time updates
mahavishnu websocket start --port 8690

# View pool metrics via WebSocket
mahavishnu monitor pools

# View workflow execution status
mahavishnu monitor workflows
```

**Adaptive Routing System**

Mahavishnu implements intelligent adaptive routing with statistical learning and cost optimization:

**Routing CLI Commands** (`routing_cli.py`):
   - View adapter statistics and performance
   - Recalculate preference order based on latest data
   - Configure cost budgets with alerts
   - Set optimization strategies by task type
   - Manage A/B tests for routing preferences

```bash
# View routing statistics
mahavishnu routing stats

# Recalculate adapter preferences
mahavishnu routing recalculate

# Set cost budget
mahavishnu routing set-budget --type daily --limit 50

# Set optimization strategy
mahavishnu routing set-strategy --task-type AI_TASK --strategy cost

# List all budgets
mahavishnu routing list-budgets

# Delete budget
mahavishnu routing delete-budget --type daily
```

**Monitoring & Alerting**:
   - **Routing Metrics** (`mahavishnu/core/routing_metrics.py`):
     - Prometheus metrics for routing decisions, adapter executions, fallbacks, costs, A/B tests
     - Counter metrics: decisions, executions, fallbacks, costs, budget alerts, A/B test events
     - Histogram metrics: routing latency, adapter latency, fallback chain length, cost distribution
     - Gauge metrics: current costs, active experiments
     - Summary: Metrics server on port 9091
     - **Alerting System** (`mahavishnu/core/routing_alerts.py`):
     - Adapter degradation detection (success rate < 95%)
     - Cost spike detection (2x multiplier triggers alert)
     - Excessive fallback detection (> 10% rate)
     - Alert handlers: Logging, Webhook (Slack/PagerDuty/etc.)
     - Background evaluation loop (60s intervals)
   - **Grafana Dashboard** (`docs/grafana/Routing_Monitoring.json`):
     - 12 panels: routing decisions, success rates, latency percentiles, fallbacks, costs, budgets, A/B tests
     - Dashboard UID: `mahavishnu-routing-monitoring`
     - Import: Dashboards → Import → Upload `Routing_Monitoring.json`
     - Configure Prometheus datasource: `http://localhost:9091`

**Routing Metrics Setup**

The routing metrics system is automatically initialized when MahavishnuApp starts. The Prometheus metrics server runs on port 9091 (configurable via `monitoring.routing_metrics_port`).

**Metrics Initialization:**
```python
from mahavishnu.core.routing_metrics import get_routing_metrics

# Lazy singleton pattern - components use shared metrics instance
metrics = get_routing_metrics()

# Or initialize with custom metrics instance
from mahavishnu.core.routing_metrics import RoutingMetrics
metrics = RoutingMetrics()
```

**Starting Metrics Server:**
```bash
# Metrics server starts automatically with MahavishnuApp
python -m mahavishnu.core.routing_metrics

# Or manually start metrics server
python -m mahavishnu.core.routing_metrics
# Metrics available at: http://localhost:9091
```

**Grafana Dashboard Setup:**
1. Start Prometheus metrics server (if not already running)
2. Open Grafana: http://localhost:3000
3. Go to Dashboards → Import
4. Upload `docs/grafana/Routing_Monitoring.json`
5. Import dashboard and select Prometheus datasource: `http://localhost:9091`
6. View real-time routing metrics and alerts

**Key Architecture Insights:**
   - **StatisticalRouter**: Analyzes adapter performance and generates preference orders
   - **CostOptimizer**: Pareto frontier analysis for cost-aware routing
   - **TaskRouter**: Coordinates adapters with fallback chains and graceful degradation
   - **ExecutionTracker**: Storage-agnostic metrics collection with batch writes
   - **Lazy metric initialization**: Prevents duplicate Prometheus registration errors

**Key Architecture Insights**:
   - **StatisticalRouter**: Analyzes adapter performance and dynamically updates preference order
   - **CostOptimizer**: Pareto frontier analysis for multi-objective optimization (cost vs latency vs success)
   - **TaskRouter**: Coordinates adapters with fallback chains and graceful degradation
   - **ExecutionTracker**: Storage-agnostic metrics with batch writes and TTL cleanup
   - **Lazy metric initialization**: Prevents duplicate Prometheus registration errors

**Workflow Sweep:**
```bash
# Trigger workflow sweep
mahavishnu sweep --tag python --adapter prefect
```

#### Role-Based Repository Organization

Mahavishnu uses a role-based taxonomy to organize repositories and enable intelligent workflow routing. Each repository is assigned a single role that defines its purpose and capabilities within the ecosystem.

**Available Roles:**

| Role | Description | Capabilities | Example Repos |
|------|-------------|---------------|---------------|
| **orchestrator** | Coordinates workflows and manages cross-repository operations | sweep, schedule, monitor, route, coordinate | mahavishnu (vishnu) |
| **resolver** | Resolves components, dependencies, and lifecycle management | resolve, activate, swap, explain, watch | oneiric |
| **manager** | Manages state, sessions, and knowledge across the ecosystem | capture, search, restore, track, analyze | session-buddy (buddy) |
| **inspector** | Validates code quality and enforces development standards | test, lint, scan, report, validate | crackerjack (jack) |
| **builder** | Builds applications and web interfaces | render, route, authenticate, build | fastblocks |
| **soothsayer** | Reveals hidden patterns and insights across distributed systems | aggregate, search, detect, correlate, graph | akosha |
| **app** | End-user applications with graphical interfaces | interface, automate, serve-users, integrate | mdinject, splashstand |
| **asset** | UI libraries, component collections, and style guides | style, theme, componentize, design | fastbulma |
| **foundation** | Foundational utilities, libraries, and shared code | share, standardize, abstract, build-upon | mcp-common |
| **visualizer** | Creates visual diagrams and documentation | draw, render, visualize, document | excalidraw-mcp, mermaid-mcp |
| **extension** | Extends framework capabilities with pluggable modules | extend, filter, enhance, plug-in | jinja2-inflection, jinja2-custom-delimiters |
| **tool** | Specialized tools and integrations via MCP protocol | connect, expose, integrate | mailgun-mcp, raindropio-mcp, unifi-mcp, etc. |

**Role-Based Query Examples:**

```bash
# Find all orchestrator repos (should be just mahavishnu)
mahavishnu list-repos --role orchestrator

# Find all MCP tool integrations
mahavishnu list-repos --role tool

# Find all UI libraries
mahavishnu list-repos --role asset

# Show detailed info about the tool role
mahavishnu show-role tool
```

**Repository Metadata:**

Each repository in `settings/repos.yaml` includes:

- `name`: Repository name
- `package`: Python package name
- `path`: Filesystem path
- `nickname`: Short nickname (optional)
- `role`: Single role from taxonomy
- `tags`: List of tags for additional categorization
- `description`: Human-readable description
- `mcp`: "native" for core MCP servers, "3rd-party" for external integrations

## Pool Management

Mahavishnu supports a **multi-pool orchestration architecture** that enables horizontal scaling across local, delegated, and cloud worker resources.

### Pool Types

**MahavishnuPool** (Direct Management):

- Wraps existing WorkerManager for local worker execution
- Low-latency task execution
- Dynamic scaling (min_workers to max_workers)
- Use for: local development, debugging, CI/CD

**SessionBuddyPool** (Delegated):

- Delegates worker management to Session-Buddy instances
- Each Session-Buddy instance manages exactly 3 workers
- Remote execution via MCP protocol
- Use for: distributed workloads, multi-server deployments

**KubernetesPool** (Cloud-Native):

- Deploys workers as Kubernetes Jobs/Pods
- Auto-scaling via HorizontalPodAutoscaler
- Cloud resource management
- Use for: production deployments, auto-scaling workloads

### Pool CLI Commands

```bash
# Spawn a pool
mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5

# List all pools
mahavishnu pool list

# Execute on specific pool
mahavishnu pool execute pool_abc --prompt "Write code"

# Auto-route to best pool
mahavishnu pool route --prompt "Write code" --selector least_loaded

# Scale pool
mahavishnu pool scale pool_abc --target 10

# Monitor pools
mahavishnu pool health

# Close pools
mahavishnu pool close pool_abc
mahavishnu pool close-all
```

### Pool Configuration

Enable pools in `settings/mahavishnu.yaml`:

```yaml
# Pool configuration
pools_enabled: true
default_pool_type: "mahavishnu"
pool_routing_strategy: "least_loaded"  # round_robin, least_loaded, random, affinity

# Memory aggregation
memory_aggregation_enabled: true
memory_sync_interval: 60
session_buddy_pool_url: "http://localhost:8678/mcp"
akosha_url: "http://localhost:8682/mcp"

# WebSocket broadcasting (real-time pool events)
pool_websocket_enabled: true
pool_websocket_port: 8691
```

### Usage Examples

**Spawn and Execute**:

```python
from mahavishnu.pools import PoolManager, PoolConfig, PoolSelector

# Create pool manager
pool_mgr = PoolManager(terminal_manager=tm, message_bus=MessageBus())

# Spawn local pool
config = PoolConfig(name="local", pool_type="mahavishnu", min_workers=2, max_workers=5)
pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

# Execute task
result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Write code"})

# Auto-route
result = await pool_mgr.route_task(
    {"prompt": "Write tests"},
    pool_selector=PoolSelector.LEAST_LOADED,
)
```

**Memory Aggregation**:

```python
from mahavishnu.pools import MemoryAggregator

aggregator = MemoryAggregator()
await aggregator.start_periodic_sync(pool_manager)

# Search across pools
results = await aggregator.cross_pool_search("API implementation", pool_mgr)
```

### Key Features

- **Auto-routing**: 4 strategies (round_robin, least_loaded, random, affinity)
- **Inter-pool communication**: Async message bus for coordination
- **Memory aggregation**: Automatic sync from pools → Session-Buddy → Akosha
- **Dynamic scaling**: Scale pools up/down based on load
- **Health monitoring**: Track pool and worker status
- **WebSocket broadcasting**: Real-time pool events to connected clients
- **Pool types**:
  - `mahavishnu`: Direct worker management (low latency)
  - `session_buddy`: Delegated to Session-Buddy instances (3 workers each)
  - `kubernetes`: K8s-native deployment (planned)

### Documentation

- [Pool Architecture](docs/POOL_ARCHITECTURE.md) - Complete architecture guide
- [Migration Guide](docs/POOL_MIGRATION.md) - From WorkerManager to pools
- [MCP Tools Spec](docs/MCP_TOOLS_SPECIFICATION.md) - Pool MCP tool reference
- [Implementation Progress](POOL_IMPLEMENTATION_PROGRESS.md) - Implementation status

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
  prefect: true     # Stub implementation
  llamaindex: true  # Fully implemented
  agno: true        # Stub implementation
qc:
  enabled: true
  min_score: 80

# WebSocket configuration
websocket:
  enabled: true
  host: "127.0.0.1"
  port: 8690

# Pool management
pools_enabled: true
default_pool_type: "mahavishnu"  # mahavishnu, session_buddy, kubernetes

# Content ingestion
ingestion:
  enabled: true
  quality_threshold: 0.7
```

**settings/local.yaml**: Local overrides (gitignored)

**settings/embeddings.yaml**: Embedding model configuration for content ingestion

**oneiric.yaml**: Legacy Oneiric config (still supported for backward compatibility)

## Critical Architecture Decisions

See `docs/adr/` for full Architecture Decision Records:

- **ADR 001**: Use Oneiric for configuration and logging
- **ADR 002**: MCP-first design with FastMCP + mcp-common
- **ADR 003**: Error handling with retry, circuit breakers, dead letter queues
- **ADR 004**: Adapter architecture for multi-engine support
- **ADR 005**: Unified memory architecture

## MCP Server Tools

All MCP tools are registered in `mahavishnu/mcp/tools/` using FastMCP decorators. See `docs/MCP_TOOLS_SPECIFICATION.md` for complete tool specifications including parameters, returns, and error handling.

## Security

See `SECURITY_CHECKLIST.md` for comprehensive security guidelines. Key points:

- All inputs must use Pydantic models for validation
- Secrets loaded from environment variables only
- JWT authentication when auth_enabled
- Path traversal prevention on all repository paths
- No shell commands with user input

## Important Architectural Patterns

### Multi-Auth Provider Support

Mahavishnu supports multiple authentication providers through `MultiAuthHandler`:

1. **Claude Code subscription** - Automatic detection via subscription check
2. **Qwen free service** - Fallback authentication
3. **Custom JWT** - Manual JWT token authentication

Configuration in `settings/mahavishnu.yaml`:
```yaml
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60
```

Environment variable for JWT secret:
```bash
export MAHAVISHNU_AUTH_SECRET="your-secret-minimum-32-characters"
```

### WebSocket Real-Time Architecture

Mahavishnu implements a WebSocket broadcasting system for real-time updates:

**Server**: `mahavishnu/websocket/server.py` (port 8690)

**Channels**:
- `workflow:{workflow_id}` - Workflow-specific updates
- `pool:{pool_id}` - Pool status updates
- `worker:{worker_id}` - Worker-specific events
- `global` - System-wide orchestration events

**Broadcast Methods**:
```python
await server.broadcast_workflow_started(workflow_id, metadata)
await server.broadcast_workflow_stage_completed(workflow_id, stage_name, result)
await server.broadcast_workflow_completed(workflow_id, final_result)
await server.broadcast_workflow_failed(workflow_id, error)
```

**Integration Example**: `examples/websocket_integration.py`

### Content Ingestion Pipeline

Mahavishnu can ingest web content, blogs, and books into the knowledge ecosystem:

**Ingester Class**: `mahavishnu/ingesters/content_ingester.py`

**Supported Content Types**:
- Webpages (via BeautifulSoup HTTP fetching)
- Blogs (RSS/Atom feeds)
- Books (PDF via pypdf, EPUB via ebooklib)

**Quality Evaluation**: `mahavishnu/ingesters/quality_evaluator.py`
- Evaluates content quality before ingestion
- Scores for readability, technical depth, completeness
- Configurable quality thresholds

**Usage**:
```bash
# Ingest a webpage
mahavishnu ingest web --url "https://example.com"

# Ingest a blog
mahavishnu ingest blog --url "https://blog.example.com/post"

# Ingest a book
mahavishnu ingest book --path ~/Documents/book.pdf
```

### OpenTelemetry Trace Ingestion

Mahavishnu can ingest and semantically search OpenTelemetry traces:

**Ingester Class**: `mahavishnu/ingesters/otel_ingester.py`

**Storage Options**:
1. **DuckDB** (zero-dependency, in-memory or file-based)
2. **PostgreSQL + pgvector** (production, persistent, vector similarity)

**Semantic Search**: Embeds trace spans with fastembed for semantic search

**Usage**:
```python
from mahavishnu.ingesters import OtelIngester

otel = OtelIngester()
await otel.initialize(storage_type="duckdb")  # or "postgresql"
await otel.ingest_trace(trace_data)
results = await otel.search_traces("error handling")
await otel.close()
```

## Dependency Management

Use `~=` (compatible release clause) for stable dependencies, `>=` only for early-development packages like FastMCP. See `pyproject.toml` for examples.

## Examples Directory

The `examples/` directory contains runnable examples for key features:

- `websocket_integration.py` - WebSocket server integration
- `websocket_client_examples.py` - WebSocket client patterns
- `pool_monitoring_demo.py` - Pool monitoring with WebSocket
- `workflow_monitoring_demo.py` - Workflow status monitoring
- `web_ingestion_example.py` - Webpage ingestion
- `book_ingestion_example.py` - PDF/EPUB book ingestion
- `otel_ingester_example.py` - OpenTelemetry trace ingestion
- `oneiric_workflow_examples.py` - Oneiric workflow patterns
- `cli_ingestion_examples.sh` - CLI ingestion commands

## Important Implementation Notes

1. **LlamaIndex is the only production-ready adapter** - Prefect and Agno are stubs
2. **WebSocket servers run on separate ports**:
   - Mahavishnu: 8690 (orchestration events)
   - Pool events: 8691 (pool status updates)
   - Session-Buddy: 8765 (already deployed)
   - Akosha: 8692 (pattern detection)
   - Crackerjack: 8686 (test execution)

3. **MCP tools are organized by domain** - Each file in `mcp/tools/` serves a specific domain
4. **All CLI sub-commands are modular** - Each has its own file in `cli/` or matching module
5. **Authentication is multi-provider** - Claude Code, Qwen, or custom JWT
6. **Configuration is layered** - Oneiric loads from defaults → YAML → env vars

## Key File Locations

### Core Application
- **Core application**: `mahavishnu/core/app.py` - MahavishnuApp class
- **Configuration**: `mahavishnu/core/config.py` - MahavishnuSettings (Oneiric-based)
- **Base adapter**: `mahavishnu/core/adapters/base.py` - OrchestratorAdapter interface
- **Error types**: `mahavishnu/core/errors.py` - Custom exception hierarchy
- **Repo models**: `mahavishnu/core/repo_models.py` - Repository metadata structures

### MCP & WebSocket
- **MCP server**: `mahavishnu/mcp/server.py` - FastMCP server
- **WebSocket server**: `mahavishnu/websocket/server.py` - Real-time updates
- **MCP tools**: `mahavishnu/mcp/tools/` - Tool implementations
  - `pool_tools.py` - Pool management (10 tools)
  - `worker_tools.py` - Worker orchestration (8 tools)
  - `coordination_tools.py` - Issues, todos, dependencies (13 tools)
  - `repository_messaging_tools.py` - Inter-repo messaging (7 tools)
  - `otel_tools.py` - OpenTelemetry trace ingestion (4 tools)
  - `session_buddy_tools.py` - Session-Buddy integration (7 tools)

### Pool Management
- **Pool manager**: `mahavishnu/pools/manager.py` - Multi-pool orchestration
- **Pool implementations**:
  - `mahavishnu/pools/mahavishnu_pool.py` - Direct worker management
  - `mahavishnu/pools/session_buddy_pool.py` - Delegated pool
  - `mahavishnu/pools/kubernetes_pool.py` - K8s native (planned)
- **Memory aggregator**: `mahavishnu/pools/memory_aggregator.py` - Cross-pool memory sync
- **WebSocket broadcasting**: `mahavishnu/pools/websocket/` - Real-time pool events

### Workers & Terminal
- **Worker manager**: `mahavishnu/workers/manager.py` - Worker lifecycle
- **Worker base**: `mahavishnu/workers/base.py` - Abstract worker interface
- **Container worker**: `mahavishnu/workers/container.py` - Containerized execution
- **Terminal manager**: `mahavishnu/terminal/manager.py` - Terminal session management
- **Terminal adapters**:
  - `iterm2.py` - iTerm2 integration
  - `mcpretentious.py` - MCP-retentious terminal

### Data Ingestion
- **OTel ingester**: `mahavishnu/ingesters/otel_ingester.py` - Trace ingestion with pgvector
- **Content ingester**: `mahavishnu/ingesters/content_ingester.py` - Web/book/blog ingestion
- **Quality evaluator**: `mahavishnu/ingesters/quality_evaluator.py` - Content quality scoring

### CLI Sub-commands
- **Backup CLI**: `mahavishnu/cli/backup_cli.py` - Backup/recovery commands
- **Coordination CLI**: `mahavishnu/coordination_cli.py` - Issues/todos/dependencies
- **Ecosystem CLI**: `mahavishnu/ecosystem_cli.py` - Repository management
- **Ingestion CLI**: `mahavishnu/ingestion_cli.py` - Content ingestion
- **Metrics CLI**: `mahavishnu/metrics_cli.py` - Observability metrics
- **Monitoring CLI**: `mahavishnu/monitoring_cli.py` - Health monitoring
- **Production CLI**: `mahavishnu/cli/production_cli.py` - Production readiness
- **Quality CLI**: `mahavishnu/quality_cli.py` - Quality evaluation
- **Sync CLI**: `mahavishnu/sync_cli.py` - Claude-Qwen config sync

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
await mcp.call_tool(
    "execute_skill",
    {
        "skill_id": "skill_abc123",
        "issue_type": "refactoring",
        "issue_data": {"message": "...", "file_path": "..."},
    },
)
```

Available agent types:

- **RefactoringAgent**: Code restructuring and modernization
- **SecurityAgent**: Security vulnerability analysis
- **PerformanceAgent**: Performance optimization
- **TestAgent**: Test generation and improvement
- **DocumentationAgent**: Documentation enhancement

For more details, see [Crackerjack Documentation](https://github.com/yourusername/crackerjack#readme).

<!-- CRACKERJACK_END -->
