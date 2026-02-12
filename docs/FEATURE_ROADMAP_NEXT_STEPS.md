# Mahavishnu Feature Roadmap

**Date**: 2026-02-12
**Purpose**: Next development priorities after ULID migration completion

---

## ULID Migration Status: ✅ COMPLETE

All ULID migration work (Phases 0-7) is **production-ready**:
- ✅ Dhruva ULID generation (19,901 ops/sec)
- ✅ Oneiric services (collision detection, migration utilities)
- ✅ Crackerjack correlation IDs (ULID[:16])
- ✅ Session-Buddy session IDs (full ULID)
- ✅ Akosha entity IDs (full ULID)
- ✅ Mahavishnu workflow models (ULID tracking)
- ✅ Cross-system integration tests (100% pass rate)

**Ready for**: Production deployment with zero data loss

---

## Next Development Priorities

### Priority 1: Complete Adapter Implementations

**Current State**: LlamaIndex is fully implemented, Prefect/Agno are stubs

#### 1.1 Prefect Adapter (Est. 2-3 days)

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/adapters/prefect_adapter.py`

**Tasks**:
- [ ] Implement `OrchestratorAdapter` interface fully
- [ ] Add workflow deployment methods (`deploy_flow()`, `deploy_flow_from_file()`)
- [ ] Add execution monitoring (`get_flow_status()`, `get_flow_run_state()`)
- [ ] Implement state synchronization (Mahavishnu → Prefect DB)
- [ ] Add flow cancellation and cleanup
- [ ] Write comprehensive tests

**Business Value**:
- Production-ready workflow orchestration
- Integration with Prefect Cloud/Server
- UI visibility via Prefect dashboard

#### 1.2 Agno Adapter (Est. 2-3 days)

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/adapters/agno_adapter.py`

**Tasks**:
- [ ] Implement `OrchestratorAdapter` interface fully
- [ ] Add crew creation (`create_crew()`, `create_crew_from_config()`)
- [ ] Add task execution (`execute_task()`, `execute_task_batch()`)
- [ ] Implement crew management (`list_crews()`, `get_crew_status()`)
- [ ] Add result aggregation (`get_crew_results()`)
- [ ] Write comprehensive tests

**Business Value**:
- Multi-agent AI task execution
- Crew-based parallel processing
- Agent collaboration patterns

---

### Priority 2: Enhanced Pool Management

**Current State**: MahavishnuPool fully implemented, SessionBuddyPool implemented, KubernetesPool planned

#### 2.1 Kubernetes Pool Implementation (Est. 3-4 days)

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/pools/kubernetes_pool.py`

**Tasks**:
- [ ] Implement `KubernetesPool` class
- [ ] Add pod lifecycle management (create, wait, cleanup)
- [ ] Add HorizontalPodAutoscaler integration
- [ ] Implement ConfigMap/Secret management
- [ ] Add resource request/limit handling
- [ ] Write E2E tests with kind/mock K8s API

**Business Value**:
- Cloud-native worker pool orchestration
- Auto-scaling based on queue depth
- Production-ready container execution

#### 2.2 Pool Monitoring Dashboard (Est. 1-2 days)

**File**: `/Users/les/Projects/mahavishnu/docs/grafana/Pool_Monitoring.json`

**Tasks**:
- [ ] Create Grafana dashboard JSON
- [ ] Add pool health panels (worker distribution, queue depth)
- [ ] Add throughput metrics (tasks/sec, avg execution time)
- [ ] Add error rate tracking (failed executions, timeouts)
- [ ] Add pool comparison panel (Mahavishnu vs SessionBuddy)

**Business Value**:
- Real-time visibility into pool performance
- Capacity planning insights
- Bottleneck identification

---

### Priority 3: Content Quality Enhancements

**Current State**: Basic quality evaluation implemented

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/ingesters/quality_evaluator.py`

**Tasks**:
- [ ] Add ML-based quality scoring (train model on labeled data)
- [ ] Implement readability metrics (Flesch-Kincaid grade level)
- [ ] Add technical depth analysis (code complexity, API usage)
- [ ] Add completeness scoring (coverage of key topics)
- [ ] Create quality trend dashboard (Grafana integration)

**Business Value**:
- Automated content filtering
- Higher quality knowledge base
- Improved RAG relevance

---

### Priority 4: CLI & Developer Experience

#### 4.1 Interactive CLI Mode (Est. 2-3 days)

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/cli/interactive.py`

**Tasks**:
- [ ] Add Rich-based terminal UI
- [ ] Implement workflow selection menus (fzf-like fuzzy search)
- [ ] Add real-time progress bars for long operations
- [ ] Implement confirmation prompts for destructive operations
- [ ] Add command history and replay

**Business Value**:
- Better developer experience
- Reduced cognitive load
- Fewer accidental mistakes

#### 4.2 Configuration Validation (Est. 1-2 days)

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/cli/config_validator.py`

**Tasks**:
- [ ] Pre-flight checks before Mahavishnu starts
- [ ] Validate repository paths exist
- [ ] Validate adapter configs (Prefect URL, Agno settings)
- [ ] Test MCP server connectivity
- [ ] Validate pool configuration (min/max workers, routing strategy)
- [ ] Add `mahavishnu validate --full` command

**Business Value**:
- Fail fast on configuration errors
- Clear error messages
- Reduced debugging time

---

## Quick Wins (1-2 days each)

### Win 1: MCP Tool Enhancements

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/`

**Ideas**:
- Add `mcp_list_tools()` tool (show all available tools)
- Add `mcp_test_connection()` tool (ping specific server)
- Add `mcp_get_metrics()` tool (query server health)
- Improve error messages with remediation suggestions

### Win 2: Documentation Improvements

**File**: `/Users/les/Projects/mahavishnu/docs/`

**Ideas**:
- Add "Getting Started" tutorial (5-minute read)
- Create architecture decision records (ADRs) for major choices
- Add troubleshooting guide with common issues
- Create video demos for key workflows
- Add API reference with examples

### Win 3: Testing Infrastructure

**File**: `/Users/les/Projects/mahavishnu/tests/`

**Ideas**:
- Add property-based tests (Hypothesis) for ID validation
- Add load tests for pool performance
- Add chaos engineering tests (kill workers mid-execution)
- Add integration test suite (end-to-end workflows)
- Improve test coverage to >80%

---

## Recommended Execution Order

**Week 1** (Quick Wins):
1. MCP Tool Enhancements (1 day)
2. Config Validation CLI (1-2 days)
3. Testing Infrastructure (2 days)

**Week 2-3** (Core Features):
4. Prefect Adapter (2-3 days)
5. Agno Adapter (2-3 days)
6. Kubernetes Pool (3-4 days)

**Week 4+** (Advanced Features):
7. Pool Monitoring Dashboard (1-2 days)
8. Content Quality ML (2-3 days)
9. Interactive CLI (2-3 days)

---

## Ready to Start?

All infrastructure is in place. Choose a priority and begin:

```bash
# Example: Start Prefect adapter implementation
cd /Users/les/Projects/mahavishnu
# Edit mahavishnu/adapters/prefect_adapter.py
# Run tests
pytest tests/unit/test_prefect_adapter.py -v
```

**Generated**: 2026-02-12
**Status**: Ready for development
