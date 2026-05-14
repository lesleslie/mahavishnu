# Mahavishnu Feature Roadmap

**Updated**: 2026-04-04
**Previous Version**: 2026-02-12 (archived)

______________________________________________________________________

## Completed Work (since last roadmap)

### Phase 2: Pattern Detection & Prediction (COMPLETE)

All Phase 2 implementation files are located in `mahavishnu/core/`:

| File | Lines | Description |
|------|-------|-------------|
| `pattern_detection.py` | 554 | PatternDetector with duration/blocker/sequence detection |
| `blocker_detection.py` | 449 | BlockerDetector with alerts and metrics |
| `predictions.py` | 577 | BlockerPredictor + DurationEstimator |
| `task_ordering.py` | 797 | 5 ordering strategies, critical path analysis |
| `dependency_graph.py` | 671 | Graph with cycle detection |
| `dependency_manager.py` | 593 | Auto block/unblock with events |
| `dependency_visualization.py` | 459 | ASCII tree/chain/matrix rendering |
| `models/pattern.py` | 187 | Pattern data models |

**Total**: 4,287 lines, code, 8 files, 196 tests passing

SQL migration: `migrations/add_patterns.sql`

### Adapter Reorganization (COMPLETE)

Adapters were reorganized into a clear facade + implementation pattern:

- `adapters/` — Public import facade (thin re-exports) + standalone adapters
- `engines/` — Full implementations with SDK integration (6,290 lines)
- `core/adapters/` — Base classes and interfaces

| Adapter | Location | Lines | Status |
|---------|----------|-------|--------|
| PrefectAdapter | `engines/prefect_adapter.py` | 1,828 | Complete |
| AgnoAdapter | `engines/agno_adapter.py` | 1,419 | Complete |
| LlamaIndexAdapter | `engines/llamaindex_adapter.py` | 1,140 | Complete |
| PydanticAIAdapter | `adapters/ai/pydantic_ai_adapter.py` | 1,029 | Complete |
| PgvectorAdapter | `adapters/pgvector_adapter.py` | 636 | Complete |

Support modules in `engines/`:

- `prefect_models.py` (314 lines), `prefect_schedules.py` (510 lines), `prefect_registry.py` (363 lines)
- `goal_team_factory.py` (716 lines)

### Pool Management (COMPLETE)

- MahavishnuPool — Direct worker management
- SessionBuddyPool — Delegated to Session-Buddy instances
- KubernetesPool — `pools/kubernetes_pool.py` (507 lines, not Note: untested without cluster)
- Pool Monitoring Dashboard — `docs/grafana/Pool_Monitoring.json`

### Additional Dashboards (COMPLETE)

4 Grafana dashboards in `docs/grafana/`:

- `Pool_Monitoring.json` — Pool health and worker distribution
- `Routing_Monitoring.json` — Routing metrics and decisions
- `WebSocket_Monitoring.json` — WebSocket performance
- `Symbiotic-Ecosystem.json` — Ecosystem overview

### Testing Infrastructure (SUBSTANTIALLY COMPLETE)

- **194 test files**, ~81K lines of test code
- **7 Hypothesis property-based test files** in `tests/property/`
- **Load testing infrastructure** in `mahavishnu/core/load_testing.py` and `mahavishnu/testing/`
- **10 ADR documents** in `docs/adr/`
- **Getting Started guide** (`docs/GETTING_STARTED.md`, 15K)
- **Troubleshooting guide** (`docs/src/troubleshooting.md`)

______________________________________________________________________

## Current Architecture

### Adapter Organization (Facade + Implementation)

```
mahavishnu/
  adapters/                  # PUBLIC FACADE - re-exports only
    __init__.py              # Re-exports from engines/ for public API
    ai/
      pydantic_ai_adapter.py   # Standalone (1,029 lines)
    pgvector_adapter.py      # Standalone (636 lines)
    rag/
      llamaindex_adapter.py   # Re-export shim
    workflow/
      prefect_adapter.py     # Deprecated re-export
  engines/                  # FULL IMPLEMENTATIONS
    prefect_adapter.py       # 1,828 lines
    prefect_models.py         # 314 lines
    prefect_schedules.py      # 510 lines
    prefect_registry.py       # 363 lines
    agno_adapter.py           # 1,419 lines
    llamaindex_adapter.py     # 1,140 lines
    goal_team_factory.py     # 716 lines
  core/
    adapters/
      base.py                  # OrchestratorAdapter interface
      worker.py               # Worker adapter
```

______________________________________________________________________

## Remaining Work

### Priority 1: Content Quality ML Enhancements

**File**: `mahavishnu/ingesters/quality_evaluator.py`
**Current State**: Basic stub (84 lines, returns hardcoded `1.0` scores)

**Tasks**:

- [ ] Add ML-based quality scoring (train model on labeled data)
- [ ] Implement readability metrics (Flesch-Kincaid grade level)
- [ ] Add technical depth analysis (code complexity, API usage)
- [ ] Add completeness scoring (coverage of key topics)
- [ ] Create quality trend dashboard (Grafana integration)

**Business Value**: Automated content filtering, higher quality knowledge base, improved RAG relevance

### Priority 2: Unified Ecosystem Dashboard TUI

**Rationale**: All 6 ecosystem components already have IPython AdminShells (via Oneiric), Typer CLIs, and MCP health endpoints. Building per-component interactive CLIs would create N UI layers for N components with inconsistent UX. A single unified dashboard — hosted in Mahavishnu as the orchestration hub — provides cross-component visibility that per-component dashboards cannot achieve.

**Existing Infrastructure** (current surfaces):

- `tui/command_palette.py` — Fuzzy search command palette
- `core/task_dashboard.py` — Themes, key bindings, panel abstractions (525 lines)
- `core/repo_dashboard.py` — Repository health dashboard (509 lines)
- `core/monitoring.py` — AlertManager, MonitoringDashboard, MetricsExporter
- `core/routing_metrics.py` — Full Prometheus integration
- `websocket/server.py` — Real-time event streaming on port 8690
- `shell/formatters.py` — Rich formatters for workflows, logs, repos
- 5 Grafana dashboards in `docs/grafana/`

**Pre-requisite Cleanup** (historical note only):

- [x] Delete 78 `.bak` files in source tree
- [x] Consolidate duplicate `AlertManager` classes
- [x] Resolve `MonitoringDashboard` / `DashboardConfig` split

**Phase 1: Unified Health Command** (2-3 days):

- [ ] Define standardized `health()` response schema in `mcp-common`
- [ ] Ensure all 6 components expose consistent health endpoint via MCP
- [ ] Build `mahavishnu health` Typer command — Rich table showing all 6 component statuses
- [ ] Handle timeouts gracefully (unreachable = down, not crash)
- [ ] Add `--json` flag for CI/CD pipeline integration
- **Go/No-Go Gate**: If < 3 developers use `mahavishnu health` regularly after 2 weeks, stop and reassess.

**Phase 2: Interactive Textual Dashboard** (3-5 days, conditional on Phase 1 adoption):

- [ ] Add `textual>=0.50.0` as optional `[tui]` dependency
- [ ] Build `mahavishnu dashboard` command with Textual app
- [ ] Ecosystem Overview screen — component cards with health/uptime/metrics
- [ ] Sweep Progress screen — live per-repo progress bars via WebSocket
- [ ] Routing & Adapters screen — adapter health, success rates, fallback chains
- [ ] Alerts screen — active alerts with acknowledge/dismiss
- [ ] Auto-discover admin shell helpers from each component

**Phase 3: Grafana Alignment** (1-2 days):

- [ ] Wire Grafana and TUI to same Prometheus metrics
- [ ] Add Sweep History Grafana dashboard (TUI = live, Grafana = historical)
- [ ] Delete empty/corrupted `Symbiotic-Ecosystem.json` (0 panels)

**Not in scope**:

- Replacing Grafana (complementary: TUI = live diagnostics, Grafana = time-series + alerting)
- Mobile/web dashboard
- Admin actions beyond alert acknowledgment (keep TUI read-only for safety)

**Business Value**: Single command to check ecosystem health (replaces running 6 separate commands), real-time cross-component visibility, unified diagnostic workflow

### Priority 3: Configuration Validation CLI

**File**: `mahavishnu/cli/config_validator.py` (new)

**Tasks**:

- [ ] Pre-flight checks before Mahavishnu starts
- [ ] Validate repository paths exist
- [ ] Validate adapter configs (Prefect URL, Agno settings)
- [ ] Test MCP server connectivity
- [ ] Validate pool configuration (min/max workers. routing strategy)
- [ ] Add `mahavishnu validate --full` command

### Priority 4: Chaos Engineering Tests

**Current State**: Property-based and load tests exist, No chaos tests.

**Tasks**:

- [ ] Add failure injection tests (kill workers mid-execution)
- [ ] Add network partition tests
- [ ] Add resource exhaustion tests
- [ ] Add cascading failure tests

### Priority 5: MCP Utility Tools (Quick Wins)

**Tasks**:

- [ ] Add `mcp_list_tools()` tool (enumerate all available tools)
- [ ] Add `mcp_test_connection()` tool(ping specific server)
- [ ] Add `mcp_get_metrics()` tool (query server health)

### Priority 6: Engine Adapter Decomposition (Refactoring)

**Current State**: Engine files are large (1,000-1,800 lines each).

**Tasks**:

- [ ] Split `engines/prefect_adapter.py` into `prefect_client.py`, + `prefect_deployments.py` + `prefect_executor.py`
- [ ] Split `engines/agno_adapter.py` into `agno_config.py` + `agno_adapter.py` + `agno_agent_factory.py`
- [ ] Split `engines/llamaindex_adapter.py` into `llamaindex_config.py` + `llamaindex_ingestion.py` + `llamaindex_query.py`

### Priority 7: Lifecycle Formalization

**Current State**: Adapters informally follow `initialize()`/`get_health()`/`shutdown()` but but codified in base class.

**Tasks**:

- [ ] Add `initialize()`, `get_health()`, `cleanup()` as abstract methods on `OrchestratorAdapter`
- [ ] Add `AdapterMetadata` class property (Oneiric pattern)
- [ ] Update all engine adapters to implement the new abstract methods

______________________________________________________________________

## Recommended Execution Order

**Week 1** (Quick Wins + Prerequisite Cleanup):

1. Phase 0: Delete `.bak` files, consolidate `AlertManager` (1-2 days)
1. MCP Utility Tools (1 day)
1. Configuration Validation CLI (1 day)

**Week 2-3** (Core Features):
4\. Unified Dashboard Phase 1: `mahavishnu health` command (2-3 days)
5\. Content Quality ML (2-3 days)
6\. Chaos Engineering Tests (2 days)

**Week 4-5** (Conditional on Adoption):
7\. Unified Dashboard Phase 2: Textual TUI (3-5 days, only if Phase 1 gets adoption)
8\. Engine Adapter Decomposition (2-3 days)

**Week 6+** (Polish):
9\. Unified Dashboard Phase 3: Grafana alignment (1-2 days)
10\. Lifecycle Formalization (1 day)

**Go/No-Go Gates**:

- Phase 2 dashboard proceeds only if `mahavishnu health` gets regular use (3+ developers)
- Each phase gated on previous phase delivering measurable value

______________________________________________________________________

## Infrastructure Status

| Component | Status | Port | Notes |
|-----------|--------|------|-------|
| MCP Server | Running | 8680 | Main orchestration API |
| WebSocket Server | Running | 8690 | Real-time updates |
| Routing Metrics | Running | 9091 | Prometheus metrics |
| Pool Manager | Implemented | N/A | Multi-pool orchestration |
| Kubernetes Pool | Implemented (untested) | N/A | Needs cluster for testing |
| Grafana Dashboards | Complete | 3000 | 4 dashboards ready to import |
| Test Suite | 194 files, 81K lines | Property + load tests, No chaos |

**Generated**: 2026-04-04
**status**: Current
