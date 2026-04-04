# Bodai Ecosystem Execution Board (Prioritized)

**Date**: 2026-04-04  
**Window**: 2026-04-06 to 2026-07-03 (90 days)  
**Primary Source**: `docs/FEATURE_ROADMAP_NEXT_STEPS.md`  
**Review Inputs**: Architecture, SRE/Operations, Delivery/Testing sub-agent reviews

## 1) Prioritized Initiative Board

| Pri | Initiative | Probability | Start | End | Owner | Dependencies | Effort (eng-weeks) | LOC Delta (est) |
|---|---|---:|---|---|---|---|---:|---:|
| 0 | Phase 0 cleanup (bak + monitoring dedupe) | 95% | 2026-04-06 | 2026-04-10 | Platform Eng | None | 1.0 | -9,200 to -9,000 |
| 1 | Health/readiness/metrics contract + `mahavishnu health` | 90% | 2026-04-06 | 2026-04-17 | Platform Eng + SRE | 0 | 2.0 | -100 to +500 |
| 2 | Config unification + `mahavishnu validate --full` | 85% | 2026-04-13 | 2026-04-24 | Core Eng | 1 | 2.0 | -200 to +700 |
| 3 | MCP lifecycle formalization | 82% | 2026-04-13 | 2026-04-24 | Core Eng | 1 | 2.0 | -100 to +600 |
| 4 | MCP utility tools (`list/test/metrics`) | 82% | 2026-04-20 | 2026-04-24 | MCP Eng | 1 | 1.0 | +200 to +500 |
| 5 | Ecosystem contract tests (release-blocking) | 84% | 2026-04-20 | 2026-05-08 | QA/Infra | 1,2,3 | 3.0 | +800 to +1,600 |
| 6 | Retry/circuit-breaker centralization | 74% | 2026-04-27 | 2026-05-15 | SRE + Core Eng | 1,3,5 | 3.0 | -100 to +900 |
| 7 | Chaos tests v1 | 74% | 2026-05-04 | 2026-05-22 | SRE + QA | 6 | 2.5 | +500 to +1,000 |
| 8 | Engine adapter decomposition | 80% | 2026-05-11 | 2026-06-05 | Adapters Eng | 3,5 | 4.0 | -300 to -1,200 |
| 9 | Typed event envelope + governance | 76% | 2026-05-18 | 2026-06-12 | Core Eng | 5 | 3.0 | -100 to +700 |
| 10 | Low-value tool retirement | 88% | 2026-05-25 | 2026-06-19 | Product + Platform | 4,5 | 2.0 | -800 to -2,500 |
| 11 | Cache + tiered retrieval defaults | 79% | 2026-06-01 | 2026-06-19 | Search/Infra | 5 | 2.0 | -100 to +600 |
| 12 | Golden paths for top workflows | 78% | 2026-06-01 | 2026-06-26 | Platform + DX | 5,9 | 2.5 | -200 to +500 |
| 13 | Dashboard Phase 2 (Textual, conditional) | 81% | 2026-06-08 | 2026-06-26 | Platform UI | 1 gate pass | 2.5 | +1,000 to +2,500 |
| 14 | Dashboard Phase 3 (Grafana alignment) | 67% | 2026-06-15 | 2026-06-26 | SRE + Platform UI | 13 | 1.5 | -50 to +300 |
| 15 | Content quality ML enhancements | 68% | 2026-06-15 | 2026-07-03 | ML Eng + Ingestion | 5,9 | 3.0 | +800 to +2,000 |

## 2) Global Gates and Safety Controls

### Required CI gates for all rollout phases
- `contract_tests_required`: pass/fail release blocker.
- `config_validation_matrix`: required env/schema checks.
- `metrics_contract_guard`: required metric families + label cardinality checks.
- `canary_health_gate`: rollback on SLO breach.
- `flaky_budget_gate`: quarantine threshold with owner SLA.

### Standard rollout sequence
1. Shadow (`0%`) for 24h.
2. Canary (`1%`) for 2h.
3. Partial (`10%`) for 8h.
4. Majority (`50%`) for 24h including peak.
5. Full (`100%`) for 72h stabilization.

### Automatic rollback triggers (any single trigger)
- Availability drop `>0.1%`.
- p99 latency breach for `>15m`.
- Contract parity mismatch `>=0.1%`.
- Search quality score falls below baseline by `>2%`.

## 3) Detailed Implementation Plan By Initiative

## Initiative 0: Phase 0 cleanup
**Scope**
- Delete `.bak` files in repo.
- Consolidate duplicate `AlertManager` in `mahavishnu/core/monitoring.py` and `mahavishnu/core/monitoring_infra.py`.
- Resolve `MonitoringDashboard` / `DashboardConfig` split.

**Tasks**
- Inventory dead/duplicate backup assets.
- Remove all `.bak` artifacts from tracked source tree.
- Select one canonical monitoring implementation path and migrate imports.
- Run unit tests for monitoring and health modules.

**Acceptance**
- No `.bak` files under source tree.
- Monitoring tests pass with single `AlertManager` implementation.
- No duplicate dashboard config classes in core path.

## Initiative 1: Health/readiness/metrics contract + `mahavishnu health`
**Scope**
- Standardized health schema across 6 ecosystem components.
- `mahavishnu health` command with Rich output and `--json`.

**Tasks**
- Define response schema (`status`, `uptime`, `version`, `dependencies`, `timestamp`).
- Align each service endpoint to schema.
- Implement command aggregation with timeout-safe behavior.
- Add integration tests for reachable/unreachable service states.

**Acceptance**
- Command returns all component states within p95 < 2s in local env.
- `--json` shape stable and validated by schema tests.
- Adoption gate: at least 3 active developers using command weekly.

## Initiative 2: Config unification + validation CLI
**Scope**
- New `mahavishnu validate --full` preflight checks.

**Tasks**
- Create `mahavishnu/cli/config_validator.py`.
- Validate repo paths, adapter config, MCP connectivity, pool constraints.
- Add fail-fast startup checks and explicit error messages.
- Add CI matrix job for env variants.

**Acceptance**
- Preflight catches misconfigurations before startup.
- Config-related startup incident rate reduced by 50%.
- Validation command used in deployment pipeline.

## Initiative 3: MCP lifecycle formalization
**Scope**
- Codify lifecycle in `OrchestratorAdapter` and all engine adapters.

**Tasks**
- Add abstract methods: `initialize()`, `get_health()`, `cleanup()`.
- Add `AdapterMetadata` contract.
- Update all adapters and tests.
- Publish migration note for adapter implementers.

**Acceptance**
- All adapters implement lifecycle contract.
- Lifecycle contract tests enforced in CI.

## Initiative 4: MCP utility tools
**Scope**
- Add three tools: `mcp_list_tools`, `mcp_test_connection`, `mcp_get_metrics`.

**Tasks**
- Add tools in `mahavishnu/mcp/tools/`.
- Register in `mahavishnu/mcp/server_core.py`.
- Add schema validation + error envelopes.
- Add unit + integration tests.

**Acceptance**
- Tool success rate >99% in integration tests.
- All tools discoverable and documented.

## Initiative 5: Ecosystem contract tests (release-blocking)
**Scope**
- Cross-component compatibility tests for Mahavishnu + ecosystem services.

**Tasks**
- Define contract matrix: API shape, error envelope, auth expectations.
- Implement deterministic test suite and split slower integration suites.
- Make suite mandatory for merge/promotion.
- Publish compatibility report artifact.

**Acceptance**
- Compatibility pass rate >98%.
- Breaking contract changes blocked pre-merge.

## Initiative 6: Retry/circuit-breaker policy centralization
**Scope**
- Single resilience module with dependency-class policy matrix.

**Tasks**
- Create dependency taxonomy (required/optional/local/external).
- Implement policy defaults (timeout/retry/backoff/circuit thresholds).
- Instrument retry amplification and circuit open metrics.
- Replace ad hoc retry implementations in core flows.

**Acceptance**
- Retry amplification factor <1.3x.
- MTTR improved by 20% over baseline.

## Initiative 7: Chaos tests v1
**Scope**
- Failure injection for workers, network, resource pressure, cascading failure.

**Tasks**
- Add test harness and fault injection controls.
- Implement game-day scenarios for dependency outage behavior.
- Validate degraded-mode behavior for optional dependencies.
- Add runbook steps for abort/recovery.

**Acceptance**
- Weekly game-day run with pass/fail reporting.
- Core task SLOs hold during dependency failures.

## Initiative 8: Engine adapter decomposition
**Scope**
- Split oversized adapter modules while preserving behavior.

**Tasks**
- `prefect_adapter.py` -> `prefect_client.py`, `prefect_deployments.py`, `prefect_executor.py`.
- `agno_adapter.py` -> `agno_config.py`, `agno_adapter.py`, `agno_agent_factory.py`.
- `llamaindex_adapter.py` -> `llamaindex_config.py`, `llamaindex_ingestion.py`, `llamaindex_query.py`.
- Add parity tests before/after split and rollback path per adapter.

**Acceptance**
- Behavior parity tests green.
- Reduced module complexity and improved maintainability.

## Initiative 9: Typed event envelope + governance
**Scope**
- Standard event schema for inter-component messaging.

**Tasks**
- Define envelope fields: `event_id`, `schema_version`, `correlation_id`, `causation_id`, `source`, `timestamp`, `payload`.
- Add compatibility/versioning policy.
- Add schema registry checks in CI.
- Migrate high-volume events first.

**Acceptance**
- No unversioned events in production paths.
- Contract compatibility checks enforced in CI.

## Initiative 10: Low-value feature/tool retirement
**Scope**
- Remove low-value/high-failure tools using telemetry evidence.

**Tasks**
- Rank tools by usage, success rate, and maintenance burden.
- Mark deprecations with warnings and timeline.
- Remove bottom 10-20% with migration notes.
- Measure incident/support-load change.

**Acceptance**
- Measurable reduction in failure surface.
- Support burden and incident volume down.

## Initiative 11: Cache + tiered retrieval defaults
**Scope**
- Standardize cache policy and progressive retrieval behavior.

**Tasks**
- Define TTL/invalidation policy by data class.
- Implement default tiering for query-heavy flows.
- Add cache observability dashboards and saturation alerts.
- Add regression tests for stale-data edge cases.

**Acceptance**
- Cache hit rate +15%.
- p95 query latency -20% on target workflows.

## Initiative 12: Golden paths
**Scope**
- Canonical 5-10 orchestration workflows with guardrails.

**Tasks**
- Select top workflows by frequency and business value.
- Document canonical inputs/outputs and failure behavior.
- Add CLI/MCP affordances pointing users to canonical paths.
- Add lint/check warnings for non-canonical usage where safe.

**Acceptance**
- Ad hoc workflow variance reduced by 30%.

## Initiative 13: Dashboard Phase 2 (conditional)
**Scope**
- Textual dashboard for live diagnostics.

**Tasks**
- Add optional `textual` dependency (`[tui]` extra).
- Implement screens: ecosystem overview, sweep progress, routing/adapters, alerts.
- Reuse existing WebSocket stream and formatter stack.
- Add read-only safety boundary.

**Acceptance**
- Gate only opens if Initiative 1 adoption threshold met.
- No material increase in incident response time due to tool instability.

## Initiative 14: Dashboard Phase 3 (Grafana alignment)
**Scope**
- Align TUI and Grafana on same Prometheus metrics.

**Tasks**
- Add sweep history dashboard.
- Validate panel query correctness against canonical metrics inventory.
- Remove corrupted/empty legacy dashboard JSON.

**Acceptance**
- Dashboard query errors <2%.
- TUI and Grafana surface consistent core metrics.

## Initiative 15: Content quality ML enhancements
**Scope**
- Replace quality evaluator stub with real scoring.

**Tasks**
- Implement readability, technical depth, completeness scoring.
- Build training/evaluation pipeline using labeled examples.
- Add trend reporting and quality drift alerts.
- Run offline benchmark and staged online rollout.

**Acceptance**
- Offline quality metric improves >=10% vs baseline.
- Online retrieval/relevance metrics improve without latency regressions.

## 4) Capacity Model and Sequencing Rules

- Planning assumption: `2 backend engineers + 0.5 SRE + 0.5 QA` (~2.5 FTE effective).
- Do not run more than **2 major initiatives concurrently**.
- Prioritize contract and reliability work before UI and ML work.
- Use explicit deferral criteria for non-critical ecosystem services.

## 5) LOC Reduction Estimate

Current observed baseline (2026-04-04):
- `.bak` files: 41 files, ~9,195 lines.
- Large adapters + monitoring modules under direct scope: ~5,467 lines.

Expected removable LOC from plan:
- Guaranteed cleanup: ~9.2k lines.
- Additional likely reductions from dedupe/refactor/retirement: ~1.3k to ~4.0k lines.

**Estimated total removable LOC**: **~10.5k to ~13.2k lines**.

Note: Net repository LOC can still grow if Dashboard and ML initiatives add more new code than removed legacy code; this board tracks removable debt, not guaranteed net LOC decrease.

## 6) Review Log

- Architecture review: recommended front-loading contracts/lifecycle and making contract tests release-blocking.
- SRE review: added explicit traffic gates, rollback triggers, and operational runbooks/checklists.
- Delivery/testing review: added CI gate hardening, flaky test controls, and realistic 90-day capacity constraints.
