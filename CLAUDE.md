# CLAUDE.md

Guidance for Claude Code working with Mahavishnu. Start with `AGENTS.md` for a shorter bootstrap.

## Ecosystem Context

Mahavishnu is the control plane for the **Bodai Ecosystem**:

| Component | Role | Port |
|-----------|------|------|
| **Mahavishnu** | Orchestrator | 8680 |
| [Akosha](https://github.com/lesleslie/akosha) | Seer (Intelligence) | 8682 |
| [Dhara](https://github.com/lesleslie/dhara) | Curator (State) | 8683 |
| [Session-Buddy](https://github.com/lesleslie/session-buddy) | Builder (Memory) | 8678 |
| [Crackerjack](https://github.com/lesleslie/crackerjack) | Inspector (Quality) | 8676 |
| [Oneiric](https://github.com/lesleslie/oneiric) | Foundation | N/A |

Routes tasks to Akosha, persists state to Dhara, tracks context in Session-Buddy, validates with Crackerjack.

## Project Overview

Mahavishnu is repo-centric orchestration infrastructure optimized for the Bodai ecosystem. Not a general-purpose end-user product. Provides:

- **Adapters**: Prefect, LlamaIndex, Agno (all production-ready)
- **Multi-pool orchestration**: Horizontal scaling across local, delegated, cloud workers
- **WebSocket infrastructure**: Real-time workflow monitoring
- **Content ingestion**: Webpages, blogs, books, OpenTelemetry traces
- **MCP tools**: ~174 tools across pool, worker, coordination, messaging, session-buddy, OTel domains

**Product posture**: Internal-first. MCP-first. Control-plane scope.

## Memory Routing

Claude Code memory is split by layer — **do not write `project` or `reference` types to CC memory files**:

| Type | Where | Why |
|------|-------|-----|
| `user` | CC memory file (`~/.claude/projects/.../memory/`) | Needed at session start before MCP is up |
| `feedback` | CC memory file | Same — shapes Claude's behavior immediately |
| `project` | Session-Buddy `store_reflection` MCP tool | Searchable by all Bodai components |
| `reference` | Session-Buddy `store_reflection` MCP tool | Same |

When saving `project`/`reference` memory, call `store_reflection(content, tags=["project"|"reference", <topic-tags>])` via the Session-Buddy MCP. When recalling, use `quick_search` or `search_by_concept`.

## Key Architecture

**Oneiric layered config**: Defaults → `settings/mahavishnu.yaml` → `settings/local.yaml` → env vars (`MAHAVISHNU_*`).

**Adapter Pattern**: All engines implement `OrchestratorAdapter` from `mahavishnu/core/adapters/base.py`.

**Error Handling**: Custom exception hierarchy in `mahavishnu/core/errors.py` with structured context.

**Configuration**: `MahavishnuSettings` extends `MCPServerSettings` from mcp-common.

## Quick Start

**Setup**:

```bash
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
```

**Testing & Quality**:

```bash
pytest                                    # Run tests
pytest --cov=mahavishnu --cov-report=html
crackerjack run                          # All quality checks
```

**MCP Server**:

```bash
mahavishnu mcp start|status|health|stop
```

**CLI**: See [CLI Reference](docs/CLI_REFERENCE.md) for all commands (repo, content, pool, routing, monitoring, etc.)

## Reference Documentation

For detailed information, see:

- **[CLI Reference](docs/CLI_REFERENCE.md)** — All CLI commands organized by subsystem
- **[Routing Guide](docs/ROUTING_GUIDE.md)** — Adaptive routing, metrics, alerting, Grafana setup
- **[Repository Roles](docs/REPOSITORY_ROLES.md)** — Role taxonomy and metadata
- **[Pool Reference](docs/POOL_REFERENCE.md)** — Pool types, configuration, usage patterns
- **[Data Ingestion](docs/DATA_INGESTION.md)** — Content and OpenTelemetry trace ingestion
- **[Configuration](docs/CONFIGURATION.md)** — Config files, environment variables, LLM routing
- **[File Reference](docs/FILE_REFERENCE.md)** — Core app, MCP, pools, workers, CLI, ingesters

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

**RunPodPool** (GPU Cloud):

- Serverless GPU execution via RunPod Flash API
- Auto-scales worker pods on demand
- Use for: GPU/ML workloads in cloud

### Pool and Terminal Architecture

Mahavishnu has three independent pool/executor abstractions with distinct ownership:

| Module | Location | Purpose | Scope |
|--------|----------|---------|-------|
| **Multi-pool orchestration** | `mahavishnu/pools/` | Production task distribution across MahavishnuPool, SessionBuddyPool, RunPodPool | Cross-server, auto-scaling |
| **iTerm2 session pool** | `mahavishnu/terminal/pool.py` | macOS iTerm2 terminal session management via AppleScript | Local development only |
| **Process pool executor** | `mahavishnu/core/process_pool_executor.py` | Generic ProcessPoolExecutor for blocking CPU-bound operations | Single-process offload |

These modules share no imports or state. `pools/` is the production orchestration layer. `terminal/pool.py` is an iTerm2-specific visualization tool. `process_pool_executor.py` is a low-level utility for event loop unblocking.

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
  - `runpod`: GPU cloud execution via RunPod Flash API

### Documentation

- [Pool Architecture](docs/POOL_ARCHITECTURE.md) - Complete architecture guide
- [Migration Guide](docs/POOL_MIGRATION.md) - From WorkerManager to pools
- [MCP Tools Spec](docs/MCP_TOOLS_SPECIFICATION.md) - Pool MCP tool reference
- Implementation Progress - Implementation status

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
  prefect: true     # Fully implemented
  llamaindex: true  # Fully implemented
  agno: true        # Fully implemented
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
default_pool_type: "mahavishnu"  # mahavishnu, session_buddy, runpod

# Content ingestion
ingestion:
  enabled: true
  quality_threshold: 0.7
```

**settings/local.yaml**: Local overrides (gitignored)

**settings/embeddings.yaml**: Embedding model configuration for content ingestion

**oneiric.yaml**: Legacy Oneiric config (still supported for backward compatibility)

## Critical Architecture Decisions

### LLM Provider Configuration (MiniMax M3 Primary)

Mahavishnu uses MiniMax M3 models as the primary cloud LLM provider. M2.7 is retained as the documented fallback when M3 is unavailable.

- **Primary provider**: `minimax` (OpenAI-compatible API at `https://api.minimax.io/v1`)
- **Local fallbacks**: `ollama` at `http://localhost:11434` and `llama_server` (llama.cpp) at `http://localhost:8081` with `qwen3.5`
- **Default models**:
  - `MiniMax-M3` — primary for quality-sensitive tasks
  - `MiniMax-M3-highspeed` — used for SWARM, QUICK, AGENT_LOOP, CREATIVE, GENERAL
  - `MiniMax-M2.7` and `MiniMax-M2.7-highspeed` — final fallback when M3 is unavailable
- **Optional compatibility provider**: `zai` (OpenAI-compatible API at `https://api.z.ai/api/coding/paas/v4`) when explicitly configured
- **Auth env var**: `MINIMAX_API_KEY` (in the parent shell) is required by both the cloud worker and the `minimax-coding-plan` MCP server in `.mcp.json` — export it in your shell rc, never inline the literal. Region selector `MINIMAX_API_HOST` is already pinned to `https://api.minimax.io` in `.mcp.json`.
- **Task-based routing**: `TaskRouter` in `mahavishnu/workers/task_router.py` maps task categories to optimal models; the in-code `DEFAULT_MINIMAX_ROUTING` and the YAML in `settings/models.yaml` are pinned in sync by a CI guard test (`tests/unit/test_task_router.py::TestYAMLRoutingSync`)

**Task-to-Model Mapping (MiniMax cloud)**:

| Categories | Cloud Model |
|------------|-------------|
| CODE_GENERATION, CODE_REVIEW, DEBUGGING, REFACTORING, TESTING, REASONING, ANALYSIS, DOCUMENTATION, VISION, EMBEDDING, ML_INFERENCE | `MiniMax-M3` |
| SWARM, QUICK, AGENT_LOOP, CREATIVE, GENERAL | `MiniMax-M3-highspeed` |

For local fallbacks (`llama_server`, `ollama`), see `settings/models.yaml`.

**Key files**:

- `mahavishnu/workers/cloud_worker.py` — OpenAI-compatible worker for MiniMax
- `mahavishnu/workers/task_router.py` — `TaskCategory` enum, model routing
- `settings/models.yaml` — YAML-driven provider and model configuration
- `tests/unit/test_task_router.py::TestYAMLRoutingSync` — guard test pinning YAML ↔ in-code routing

If MiniMax becomes unavailable, operators can temporarily restore `zai` as an optional non-default provider by reintroducing the compatibility settings in `settings/models.yaml` and setting `default_provider` back to `zai` only for the affected environment.

See `docs/plans/2026-05-10-minimax27-provider-migration.md` for the M2.7 → M3 migration history and `docs/adr/` for the full Architecture Decision Records.

See `docs/adr/` for full Architecture Decision Records:

- **ADR 001**: Use Oneiric for configuration and logging
- **ADR 002**: MCP-first design with FastMCP + mcp-common
- **ADR 003**: Error handling with retry, circuit breakers, dead letter queues
- **ADR 004**: Adapter architecture for multi-engine support
- **ADR 005**: Unified memory architecture

## MCP Server Tools

All MCP tools are registered in `mahavishnu/mcp/tools/` using FastMCP decorators. See `docs/MCP_TOOLS_SPECIFICATION.md` for complete tool specifications including parameters, returns, and error handling.

### Tool Profile System

Tools are gated by the `MAHAVISHNU_TOOL_PROFILE` environment variable:

- `full` (default): All 14 tool groups (~174 tools)
- `standard`: Core 7 groups (terminal, pool, worker, messaging, git, session-buddy)
- `minimal`: Health probes only

Profile configuration is in `mahavishnu/mcp/tools/profiles.py`. A `discover_tools(query)` meta-tool is always registered so Claude can find unloaded tools.

## Tool Preferences

This project ships a Mahavishnu control plane with ~174 MCP tools. For non-trivial work, prefer Mahavishnu workers over direct local invocations.

### When to use Mahavishnu workers

Use `mcp__mahavishnu__*` tools when the task:

- Touches **more than one file** (refactors, multi-file edits, dependency updates)
- Involves **builds, tests, or test runs** (`pytest`, `crackerjack`, `ruff`, `mypy`, type checks)
- Is described as **"refactor," "analyze," "audit," "deploy," "build," "test,"** or **"review"**
- Should appear in **ecosystem observability** (Dhara, Akosha, Grafana dashboards)
- Might need **retry, recovery, or cross-server delegation**
- Involves **multiple repositories** or cross-cutting changes

The primary entry point for non-trivial work:

```python
mcp__mahavishnu__pool_route_execute(
    prompt="<clear task description>",
    pool_selector="least_loaded",  # or round_robin, affinity, peer_affinity
    timeout=300,
)
```

For long-running or async work:

```python
mcp__mahavishnu__dispatch_to_pool(
    prompt="<task>",
    caller_kind="claude_code",
    parent_session_id="<session-id>",  # for traceability
    async_callback=True,  # returns workflow_id immediately
)
```

### When to use local tools (Bash, Edit, Read, Write)

Use the built-in tools **only** when:

- You need **direct file inspection** before deciding what to do (read-only exploration)
- The task is **trivially small** (\<5 lines changed, single file)
- You're **discovering or explaining** the codebase
- The task is **conversation-local** (e.g., updating this file, fixing a typo, drafting docs)
- Mahavishnu pools are **unavailable** (use `mcp__mahavishnu__pool_health` to check; if down, surface the unavailability to the user — do not silently fall back to local tools, since local fallback breaks the audit trail. See "Degraded mode" below.)

### Dispatching non-trivial work

For tasks that should explicitly bypass the main session's tool set, dispatch the `mahavishnu-orchestrator` subagent (`.claude/agents/mahavishnu-orchestrator.md`). That agent only uses Mahavishnu MCP tools; it does not edit files directly.

### Choosing between /vishnu and mahavishnu-orchestrator

`/vishnu` is a shortcut that steers tool selection without forcing tool isolation; `mahavishnu-orchestrator` is forced delegation with strict tool restrictions. Both route through Mahavishnu; the difference is who picks the tools. Use `/vishnu` when you want a quick way to indicate preference; use `mahavishnu-orchestrator` when the parent agent wants strict control over which tools the delegated worker can use.

### MCP tool discovery

To find what Mahavishnu can do, call:

```python
mcp__mahavishnu__discover_tools(query="<capability or task>")
```

Use this before assuming a capability does not exist.

### Degraded mode

If Mahavishnu pools are unhealthy or unreachable, **surface the unavailability to the user** rather than silently falling back. Local fallback would break the audit trail (the plan's primary stated outcome), and silent fallback also erodes user trust in the routing layer.

Recommended behavior when Mahavishnu is down:

1. Run `mcp__mahavishnu__pool_health` to confirm the failure mode (degraded vs. unreachable).
1. Tell the user: "Mahavishnu is unavailable; doing this locally without observability. Proceed?"
1. If the user agrees, proceed locally but emit a structured note in the conversation: `[vishnu] local fallback — no observability for {task}`.
1. Queue the task for replay: write a marker to `~/.mahavishnu/fallback-queue/{task-id}.json` so an operator can replay it through Mahavishnu later.

This policy harmonizes with the `mahavishnu-orchestrator` subagent's "fail-loud, no silent fallback" rule and the `/vishnu` skill's "ask the user" rule. One consistent posture across all surfaces.

### Cost and latency note

Mahavishnu adds ~200-500ms of pool routing overhead vs. local `Bash`. For trivial operations this is wasted time; reserve Mahavishnu for tasks where the overhead is amortized across meaningful work.

### Worker activity visibility

When you dispatch a task to a Mahavishnu worker, the run continues out-of-band — you do not see it inline. Use these surfaces to observe activity while the run is in progress, instead of waiting blindly for the result.

Three external surfaces:

- `/vishnu-status` slash command — prints the pool list, per-pool health, and recent metrics.
- MCP log file at `~/.mahavishnu/logs/mcp.log` — tail it for structured events from every worker call.
- WebSocket subscriber on port `8690` — channels `workflow:{workflow_id}`, `pool:{pool_id}`, `worker:{worker_id}`, and `global` (see [WebSocket Real-Time Architecture](#websocket-real-time-architecture) for the broadcast methods).

For inline visibility from inside this Claude session, the `.claude/hooks/mahavishnu-activity-stream.py` hook surfaces a compact stream of worker events directly in the conversation so you can correlate them with the work you dispatched.

See `.claude/decisions/mahavishnu-tool-preference-policy.md` for the full operational rule on where tool-selection steering may live.

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
1. **Qwen free service** - Fallback authentication
1. **Custom JWT** - Manual JWT token authentication

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

- Webpages (delegated to `web_reader` MCP server on port 8699)
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

### Optional Dependency Groups (PEP 735)

Several runtime integrations are **not** in `[project].dependencies` because their
backing libraries are large, narrow in scope, or only meaningful on specific
deployments. They live in optional `dependency-groups` so a lean install
(`uv sync`) does not pull them in. Install per-group with `uv sync --group <name>`
or include them in `dev` via `{include-group = "<name>"}` (already wired for `dev`).

| Group | Use it for | Install |
|-------|-----------|---------|
| `ai` | The Pydantic AI agent runtime (`mahavishnu.adapters.ai.pydantic_ai_adapter`). Lazy-imported at runtime; only needed when that adapter is enabled. | `uv sync --group ai` |
| `gpu` | Serverless GPU execution via RunPod Flash (`mahavishnu.pools.runpod_pool`). Pulls the RunPod SDK; only deploy when using GPU pools. | `uv sync --group gpu` |
| `content-ingest` | PDF, EPUB, and trafilatura readability extraction. The base `content_ingester.py` lazy-imports `pypdf`/`ebooklib`; `trafilatura` powers the web-extract escalation path. | `uv sync --group content-ingest` |
| `storage-pg` | PostgreSQL pgvector adapter with HNSW (`mahavishnu.adapters.pgvector_adapter`). Lazy-imported; only needed for the PostgreSQL OTel storage backend. | `uv sync --group storage-pg` |

All four groups are already pulled in by `dev` so the test suite exercises the
wrapper modules. Production deployments that do not need a given integration
can omit the group; the wrapper code raises a clear `RuntimeError` pointing to
the missing install (e.g. `"pypdf not installed. Install with: uv pip install pypdf"`).

### OpenTelemetry Trace Ingestion

Mahavishnu can ingest and semantically search OpenTelemetry traces:

**Ingester Class**: `mahavishnu/ingesters/otel_ingester.py`

**Storage Options**:

1. **DuckDB** (zero-dependency, in-memory or file-based)
1. **PostgreSQL + pgvector** (production, persistent, vector similarity)

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

1. **All adapters are production-ready** - Prefect, LlamaIndex (0.14.x), and Agno are fully implemented

1. **WebSocket servers run on separate ports**:

   - Mahavishnu: 8690 (orchestration events)
   - Pool events: 8691 (pool status updates)
   - Session-Buddy: 8765 (already deployed)
   - Akosha: 8692 (pattern detection)
   - Crackerjack: 8686 (test execution)

1. **MCP tools are organized by domain** - Each file in `mcp/tools/` serves a specific domain

1. **All CLI sub-commands are modular** - Each has its own file in `cli/` or matching module

1. **Authentication is multi-provider** - Claude Code, Qwen, or custom JWT

1. **Configuration is layered** - Oneiric loads from defaults → YAML → env vars

1. **iTerm2 adapter limitation** - The iTerm2 Python API is designed for standalone scripts, not embedding in existing async apps. Use mcpretentious or mock adapters for pool management.

## Process Discipline

Features have been built but not wired into apps and workflows. To prevent
that, every plan and every feature delivery must answer the wiring
question explicitly before the work is considered done.

- Use `docs/plans/TEMPLATE.md` for any new plan. Every phase deliverable
  must include an **Integration Contract** block (Triggered from, Returns
  to / updates, Demonstrable by, Rollback signal, Observability added).
- Run `python scripts/audit_orphans.py` before marking a feature
  complete. If the audit reports recently-added symbols with zero
  callers, the feature is not done — either wire it or remove it.
- Track `{built, wired, adopted}` state for every feature using
  `docs/feature-tracking/TEMPLATE.md`. A feature stays in `built` state
  only while the wiring work is open and dated.
- The `feature-delivery-lifecycle` workflow (`workflows:feature:feature-delivery-lifecycle`)
  contains a dedicated **Wiring** phase between Design and Validate —
  follow it for every non-trivial delivery.

The full policy lives in `.claude/decisions/wire-up-contract.md`. The
canonical template lives in `docs/plans/TEMPLATE.md`.

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
  - `mahavishnu/pools/runpod_pool.py` - GPU cloud pool
- **Memory aggregator**: `mahavishnu/pools/memory_aggregator.py` - Cross-pool memory sync
- **WebSocket broadcasting**: `mahavishnu/pools/websocket/` - Real-time pool events

### Workers & Terminal

- **Worker manager**: `mahavishnu/workers/manager.py` - Worker lifecycle
- **Worker base**: `mahavishnu/workers/base.py` - Abstract worker interface
- **Container worker**: `mahavishnu/workers/container.py` - Containerized execution
- **Cloud worker**: `mahavishnu/workers/cloud_worker.py` - OpenAI-compatible cloud worker with MiniMax primary defaults
- **Task router**: `mahavishnu/workers/task_router.py` - Task classification + model selection
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

<!-- CRACKERJACK_START -->

## Crackerjack Integration

Mahavishnu uses Crackerjack for repo-wide quality gates and can consume Crackerjack MCP capabilities when the server is connected.

### Recommended Workflow

```bash
crackerjack run
pytest -m "not slow"
pytest --cov=mahavishnu --cov-report=html
```

Use the dedicated command sections above for Ruff, type checking, security, and MCP server smoke tests. Avoid duplicating those checks in ad hoc shell scripts.

### MCP-Aware Usage

When Crackerjack MCP is available, prefer using it for quality status, job tracking, and skill discovery instead of re-implementing local wrappers. See the Crackerjack repo docs for current MCP tool names and workflow details.

### Mahavishnu Orchestration Mode

When a request spans multiple repositories or needs concurrent execution:

1. Resolve target repos from the configured repository catalog.
1. Route via Mahavishnu pool/workflow tools instead of manual per-repo shell loops.
1. Use `least_loaded` as the default selector unless the user requests another strategy.
1. Emit workflow and repository status updates for downstream repos when coordination is involved.
1. Report engine choice and execution outcome in the final response.

Default command sequence:

1. `mahavishnu metrics engines --source auto --output table`
1. `mahavishnu pool route --prompt "<task>" --selector least_loaded`
1. If workflow semantics are needed, use workflow-triggering tools instead of ad hoc loops.

## Crackerjack-Compliant Code

> **Hard limits and tool config live in `pyproject.toml`** (Ruff, mypy, pyright, pytest, bandit, complexipy). The `crackerjack-compliant-code` skill is the full procedural reference — load it when implementing a feature. This section captures project **conventions that aren't obvious from the config** plus known enforcement gaps.

### Conventions (project-level, not all in config)

- **`from __future__ import annotations`** as the first non-comment line of every source file. Place after any module docstring.
- **Imports sorted within each section** (stdlib → third-party → first-party, with `force-sort-within-sections = true` and `known-first-party = ["mahavishnu"]`).
- **Modern syntax**: `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path` for filesystem paths (not `os.path`). Target Python 3.13.
- **Function arguments with default `None`** must be typed `X | None = None` (mypy `no_implicit_optional = true`). `def f(x: int = None)` will fail.
- **No `assert` in production code** (`mahavishnu/**`). Use the `mahavishnu/core/errors.py` exception hierarchy. Enforced by bandit B101.
- **No `Any` in tool inputs or orchestration state.** Use `TYPE_CHECKING` and a typed protocol to escape. **Enforcement gap**: mypy warns on `Any` returns but not on `Any` parameters.
- **In `except` blocks, use `logger.exception(...)`**, never `logger.error(..., exc_info=True)`.
- **All I/O in the orchestration layer is async.** No blocking calls (`time.sleep`, `requests`, sync file I/O) inside async functions — use `httpx`, `aiofiles`, or `loop.run_in_executor`. Sync code only at worker boundaries and CLI entry points.
- **Use the Oneiric logger** (`oneiric.logging`) — not stdlib `logging`, not `print()`.
- **Remove unused imports and dead code immediately** (Ruff F401 / UP).

### Test conventions

- **Use the project pytest markers** (don't invent new ones): `unit`, `integration`, `e2e`, `property`, `slow`, `timeout`, `ci`, `crackerjack`, plus adapter-specific (`prefect`, `llamaindex`, `agno`, `hatchet`, `mcp`, `chaos`, `requires_network`, `requires_auth`).
- **Async tests** don't need `@pytest.mark.asyncio` — `asyncio_mode = "auto"`.
- **Per-test timeout: 300 s ceiling, not target.** Any test >10 s should be `@pytest.mark.slow` and skipped with `-m "not slow"` for fast feedback.
- **The `tests.*` namespace has relaxed typing** (mypy `disallow_untyped_defs = false`), but the conventions above (imports, `__future__`, `pathlib`) still apply. Asserts are idiomatic in tests.

### Hard limits (set in `pyproject.toml`; the gate fails on breach)

| Limit | Value | Config key |
|---|---|---|
| Line length | 100 chars | `[tool.ruff] line-length` |
| Function args | 10 (excludes `self`, `cls`, `*args`, `**kwargs`) | `[tool.ruff.lint.pylint] max-args` |
| Branches | 15 | `[tool.ruff.lint.pylint] max-branches` |
| Returns | 6 | `[tool.ruff.lint.pylint] max-returns` |
| Statements | 55 ceiling — practical target 30 | `[tool.ruff.lint.pylint] max-statements` |
| Coverage | 80% | `[tool.pytest] addopts --cov-fail-under` |

If the gate is passing but this table disagrees, trust the gate. A sync test (analogous to `tests/unit/test_task_router.py::TestYAMLRoutingSync`) is worth adding to pin them.

### Lint configuration (Ruff)

- **Active**: `I`, `N`, `UP`, `B`, `C4`, `SIM`, `TCH`, plus the `P` pylint subset for hard limits.
- **Ignored (gate won't catch)**: `B904`, `N806`, `E402`, `SIM102`, `SIM105`, `SIM108`. You may still fix these in new code; do not churn existing code to address them.
- **Per-file-ignore** (configured in `pyproject.toml` `[tool.ruff.lint.per-file-ignores]`):
  - `B008` in `mahavishnu/**/*cli*.py` AND `mahavishnu/cli/**/*.py` (two patterns overlap; both are intentional). Typer idiom: `typer.Option(...)` in default args.
  - `.claude/skills/tools/**/*.py` → `B008` only. Skill scripts use Typer defaults.
  - `tests/property/**/*.py` → `ALL`. Reference planned-but-never-implemented modules (`mahavishnu.learning.database.*` etc.). Pure noise until the tests are completed or removed.
  - `tests/unit/test_core/test_validators_comprehensive.py`, `tests/unit/test_session_buddy.py` → `ALL`. Both self-skip at module load via `pytest.skip(..., allow_module_level=True)`.
  - `tests/conftest.py` → `F401`. Uses `try/except ImportError` to re-export fixture symbols for global pytest availability.
  - `tests/**/*.py` → `B017, B007, E741, N801, N802, N803, N814, N818, SIM116, SIM117`. Stylistic test smells (capitalized fixtures, broad-blind `pytest.raises(Exception)`, nested `with`, etc.); enforced for `mahavishnu/` production code.
  - `scripts/**`, `monitoring/**`, `examples/**`, `migrations/**` → stylistic rules (`B007, B008, E741, F401, F841, I001, SIM108, SIM116, SIM117, TC003`, with rule selection tailored per path). Tooling/admin paths — not production.
  - Update this section whenever a new per-file-ignore is added.

### Type checker configuration

- **Mypy strict** (Python 3.13, `disallow_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`, `warn_no_return`, `strict_optional`, `warn_return_any`).
- **Pyright strict** with `reportMissingTypeStubs` downgraded to warning.
- Both run; both must pass.

### Known enforcement gaps

- "No Any" is only partially enforced (mypy warns on returns, not params) — manual review.
- Bandit does not scan test files — review auth, deserialization, and shell calls in tests by hand.

<!-- CRACKERJACK_END -->
