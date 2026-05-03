# Bodai Ecosystem Execution Board (Prioritized)

**Date**: 2026-04-04
**Window**: 2026-04-06 to 2026-07-03 (90 days)
**Primary Source**: `docs/FEATURE_ROADMAP_NEXT_STEPS.md`
**Review Inputs**: Architecture, SRE/Operations, Delivery/Testing sub-agent reviews

## 1) Prioritized Initiative Board

| Pri | Initiative | Probability | Start | End | Owner | Dependencies | Effort (eng-weeks) | LOC Delta (est) |
|---|---|---:|---|---|---|---|---:|---:|
| 0 | Phase 0 cleanup (bak + monitoring dedupe) | 95% | 2026-04-06 | 2026-04-10 | Platform Eng | None | 1.0 | -9,200 to -9,000 |
| 1 | Health/readiness/metrics contract + `mahavishnu health` | 90% | 2026-04-06 | 2026-04-17 | Platform Eng + SRE | `I0-4` | 2.0 | -100 to +500 |
| 2 | Config unification + `mahavishnu validate --full` | 85% | 2026-04-13 | 2026-04-24 | Core Eng | `I1-1` | 2.0 | -200 to +700 |
| 3 | MCP lifecycle formalization | 82% | 2026-04-13 | 2026-04-24 | Core Eng | `I1-1` | 2.0 | -100 to +600 |
| 4 | MCP utility tools (`list/test/metrics`) | 82% | 2026-04-20 | 2026-04-24 | MCP Eng | `I1-2` | 1.0 | +200 to +500 |
| 5 | Ecosystem contract tests (release-blocking) | 84% | 2026-04-20 | 2026-05-08 | QA/Infra | `I1-4`, `I2-4`, `I3-4` | 3.0 | +800 to +1,600 |
| 6 | Retry/circuit-breaker centralization | 74% | 2026-04-27 | 2026-05-15 | SRE + Core Eng | `I5-1` | 3.0 | -100 to +900 |
| 7 | Chaos tests v1 | 74% | 2026-05-04 | 2026-05-22 | SRE + QA | `I6-2` | 2.5 | +500 to +1,000 |
| 8 | Engine adapter decomposition | 80% | 2026-05-11 | 2026-06-05 | Adapters Eng | `I3-4`, `I5-2` | 4.0 | -300 to -1,200 |
| 9 | Typed event envelope + governance | 76% | 2026-05-18 | 2026-06-12 | Core Eng | `I5-1` | 3.0 | -100 to +700 |
| 10 | Low-value tool retirement | 88% | 2026-05-25 | 2026-06-19 | Product + Platform | `I4-3`, `I5-3` | 2.0 | -800 to -2,500 |
| 11 | Cache + tiered retrieval defaults | 79% | 2026-06-01 | 2026-06-19 | Search/Infra | `I5-1` | 2.0 | -100 to +600 |
| 12 | Golden paths for top workflows | 78% | 2026-06-01 | 2026-06-26 | Platform + DX | `I5-3`, `I9-3` | 2.5 | -200 to +500 |
| 13 | Dashboard Phase 2 (Textual, conditional) | 81% | 2026-06-08 | 2026-06-26 | Platform UI | `G1` | 2.5 | +1,000 to +2,500 |
| 14 | Dashboard Phase 3 (Grafana alignment) | 67% | 2026-06-15 | 2026-06-26 | SRE + Platform UI | `I13-3` | 1.5 | -50 to +300 |
| 15 | Content quality ML enhancements | 68% | 2026-06-15 | 2026-07-03 | ML Eng + Ingestion | `I9-2` | 3.0 | +800 to +2,000 |

## 1.1) Master Checklist (Link to Individual Initiative Plans)

Completion rule for this master checklist:

- An initiative can be checked complete only when all of its work package checkboxes are complete in the linked initiative doc and that initiative's exit criteria are met.

- [x] [Initiative 0: Phase 0 Cleanup](./initiatives/00-phase0-cleanup.md)

- [x] [Initiative 1: Health/Readiness/Metrics Contract + `mahavishnu health`](./initiatives/01-health-contract-and-command.md)

- [x] [Initiative 2: Config Unification + Validation CLI](./initiatives/02-config-unification-validation-cli.md)

- [x] [Initiative 3: MCP Lifecycle Formalization](./initiatives/03-mcp-lifecycle-formalization.md)

- [x] [Initiative 4: MCP Utility Tools](./initiatives/04-mcp-utility-tools.md)

- [x] [Initiative 5: Ecosystem Contract Tests](./initiatives/05-ecosystem-contract-tests.md)

- [x] [Initiative 6: Retry/Circuit-Breaker Centralization](./initiatives/06-retry-circuit-centralization.md)

- [x] [Initiative 7: Chaos Tests v1](./initiatives/07-chaos-tests-v1.md)

- [x] [Initiative 8: Engine Adapter Decomposition](./initiatives/08-engine-adapter-decomposition.md)

- [ ] [Initiative 9: Typed Event Envelope + Governance](./initiatives/09-typed-event-envelope-governance.md)

- [ ] [Initiative 10: Low-Value Tool Retirement](./initiatives/10-low-value-tool-retirement.md)

- [ ] [Initiative 11: Cache + Tiered Retrieval Defaults](./initiatives/11-cache-tiered-retrieval-defaults.md)

- [ ] [Initiative 12: Golden Paths for Top Workflows](./initiatives/12-golden-paths-workflows.md)

- [ ] [Initiative 13: Dashboard Phase 2 (Textual, Conditional)](./initiatives/13-dashboard-phase2-textual.md)

- [ ] [Initiative 14: Dashboard Phase 3 (Grafana Alignment)](./initiatives/14-dashboard-phase3-grafana-alignment.md)

- [ ] [Initiative 15: Content Quality ML Enhancements](./initiatives/15-content-quality-ml-enhancements.md)

## 1.2) Current Execution Slice

This is the recommended order for the remaining `gpt-5.4 mini` budget:

1. `I0` Phase 0 cleanup: complete.
1. `I1` Health/readiness/metrics contract + `mahavishnu health`: complete.
1. `I4` MCP utility tools: complete.
1. `I2` Config unification + validation CLI: complete.
1. `I3` MCP lifecycle formalization: complete.
1. `I5` Ecosystem contract tests: complete.
1. `I6` Retry/circuit-breaker centralization: complete.
1. `I7` Chaos tests v1: complete.
1. `I8` Engine adapter decomposition: complete.

Execution rules for this slice:

- `I0` is complete.
- `I1` is complete.
- Do not start `I4` work packages until `I1-2` is complete.
- `I2` is complete.
- `I3` is complete.
- Stop after any initiative if the linked initiative doc has all work package checkboxes complete and exit criteria are met.

## 2) Global Gates and Safety Controls

### Baseline gates (active immediately)

- `G0_plan_dependency_check`: all active work packages must satisfy dependency IDs.
- `G0_config_validation_matrix`: required env/schema checks for affected paths.
- `G0_canary_health_gate`: rollback on SLO breach where rollout exists.
- `G0_flaky_budget_gate`: quarantine threshold with owner SLA.
- `G1`: Initiative 1 adoption gate. `mahavishnu health` must have at least `3` active weekly developers before Initiative 13 implementation starts.

### Post-contract gates (mandatory after Initiative 5 completes)

- `contract_tests_required`: pass/fail release blocker.
- `metrics_contract_guard`: required metric families + label cardinality checks.

### Dependency semantics

- Initiative start dates indicate planning/discovery kickoff.
- Implementation work packages may begin only after listed dependency IDs are complete.
- Tracker should enforce dependencies at work package level (`Ix-y`, `Gx`).

### Standard rollout sequence

1. Shadow (`0%`) for 24h.
1. Canary (`1%`) for 2h.
1. Partial (`10%`) for 8h.
1. Majority (`50%`) for 24h including peak.
1. Full (`100%`) for 72h stabilization.

### Automatic rollback triggers (any single trigger)

- Availability drop `>0.1%`.
- p99 latency breach for `>15m`.
- Contract parity mismatch `>=0.1%`.
- Search quality score falls below baseline by `>2%`.

## 3) Detailed Implementation Plan By Initiative

Detailed execution rule:

- This section is a high-level summary. The linked initiative docs in `docs/plans/initiatives/` are authoritative for per-initiative work package status, detailed dependencies, risks, and exit criteria.

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

**Status**

- Complete as of 2026-04-04.

## Initiative 6: Retry/circuit-breaker policy centralization

**Scope**

- Single resilience module with dependency-class policy matrix.

**Tasks**

- Create dependency taxonomy (required/optional/local/external).
- Implement policy defaults (timeout/retry/backoff/circuit thresholds).
- Instrument retry amplification and circuit open metrics.
- Replace ad hoc retry implementations in core flows.

**Acceptance**

- Retry amplification factor \<1.3x.
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
- Cyclomatic complexity reduced by at least `20%` in target files.
- No target adapter module exceeds `700` lines after decomposition.

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

- Tool surface reduced per target.
- Tool-related incidents decrease by at least `20%` over the next 30-day window.
- Mean monthly maintenance tickets for removed tools drops by at least `30%`.

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

- Read-only dashboard renders all planned screens with live data for 5 consecutive days.
- Dashboard crash-free sessions `>=99%` during pilot window.
- Incident response median time does not degrade by more than `5%` in pilot window.

## Initiative 14: Dashboard Phase 3 (Grafana alignment)

**Scope**

- Align TUI and Grafana on same Prometheus metrics.

**Tasks**

- Add sweep history dashboard.
- Validate panel query correctness against canonical metrics inventory.
- Remove corrupted/empty legacy dashboard JSON.

**Acceptance**

- Dashboard query errors \<2%.
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
- Do not run more than **2 heavy implementation streams concurrently**.
- Additional concurrent initiatives may run only in planning/discovery/docs mode until dependencies are met.
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

## 7) Issue-Sized Work Package Backlog (1-3 day chunks)

### Initiative 0 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I0-1 | Inventory and classify all `.bak` files | 0.5d | Platform Eng | None | inventory artifact committed |
| I0-2 | Remove `.bak` files and update ignore rules | 0.5d | Platform Eng | I0-1 | `find . -name '*.bak'` returns 0 |
| I0-3 | Consolidate `AlertManager` implementation | 1.0d | Platform Eng | I0-1 | single canonical class remains |
| I0-4 | Resolve dashboard config split and imports | 1.0d | Platform Eng | I0-3 | tests pass and no duplicate config types |

### Initiative 1 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I1-1 | Author health schema spec (`v1`) | 1.0d | Platform Eng | I0-4 | schema doc + model in code |
| I1-2 | Implement schema in Mahavishnu endpoint | 1.0d | Platform Eng | I1-1 | endpoint response validates |
| I1-3 | Implement `mahavishnu health` + `--json` | 1.0d | Platform Eng | I1-2 | CLI works for all 6 components |
| I1-4 | Timeout/failure behavior tests + telemetry | 1.0d | SRE | I1-3 | unreachable service reported, no crash |

### Initiative 2 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I2-1 | Scaffold `config_validator.py` command | 0.5d | Core Eng | I1-1 | command wired in CLI |
| I2-2 | Add repo/adapters/pool checks | 1.0d | Core Eng | I2-1 | invalid configs fail with clear errors |
| I2-3 | Add MCP connectivity and full mode checks | 1.0d | Core Eng | I2-2 | `validate --full` covers connectivity |
| I2-4 | Add CI config matrix job | 1.0d | QA/Infra | I2-3 | job required in PR checks |

### Initiative 3 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I3-1 | Add abstract lifecycle contract | 0.5d | Core Eng | I1-1 | base adapter exposes required methods |
| I3-2 | Add `AdapterMetadata` model | 0.5d | Core Eng | I3-1 | metadata available on all adapters |
| I3-3 | Update Prefect/Agno/LlamaIndex implementations | 1.5d | Core Eng | I3-2 | adapters implement contract |
| I3-4 | Lifecycle conformance tests | 1.0d | QA/Infra | I3-3 | CI blocks non-conforming adapters |

### Initiative 4 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I4-1 | Add `mcp_list_tools` implementation + tests | 1.0d | MCP Eng | I1-2 | tool enumerates registered tools |
| I4-2 | Add `mcp_test_connection` + tests | 1.0d | MCP Eng | I4-1 | connectivity checks return typed result |
| I4-3 | Add `mcp_get_metrics` + tests | 1.0d | MCP Eng | I4-1 | health metrics tool returns schema output |

### Initiative 5 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I5-1 | Define contract matrix and fixtures | 1.0d | QA/Infra | I1-4,I2-4,I3-4 | matrix doc + fixtures merged |
| I5-2 | Implement deterministic contract suite | 2.0d | QA/Infra | I5-1 | suite stable and non-flaky |
| I5-3 | CI gating + compatibility report artifact | 1.0d | QA/Infra | I5-2 | required check enabled |

### Initiative 6 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I6-1 | Dependency taxonomy and policy matrix | 1.0d | SRE | I5-1 | policy doc approved |
| I6-2 | Shared retry/circuit module | 2.0d | Core Eng | I6-1 | module available and tested |
| I6-3 | Migrate top 3 critical flows | 2.0d | Core Eng | I6-2 | old retry code removed for those paths |
| I6-4 | Add retry amplification and circuit metrics | 1.0d | SRE | I6-3 | dashboards show policy behavior |

### Initiative 7 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I7-1 | Chaos harness scaffolding | 1.0d | SRE + QA | I6-2 | harness can inject controlled faults |
| I7-2 | Worker kill + network partition scenarios | 2.0d | SRE + QA | I7-1 | scenarios reproducible in CI env |
| I7-3 | Resource exhaustion + cascading failure scenarios | 2.0d | SRE + QA | I7-1 | game-day checklist passes |

### Initiative 8 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I8-1 | Prefect split + parity tests | 2.0d | Adapters Eng | I3-4,I5-2 | split merged with parity green |
| I8-2 | Agno split + parity tests | 2.0d | Adapters Eng | I8-1 | split merged with parity green |
| I8-3 | LlamaIndex split + parity tests | 2.0d | Adapters Eng | I8-2 | split merged with parity green |
| I8-4 | Remove dead compatibility shims | 1.0d | Adapters Eng | I8-3 | no unused split-era shim modules |

### Initiative 9 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I9-1 | Event envelope spec + versioning policy | 1.0d | Core Eng | I5-1 | ✅ policy approved and documented |
| I9-2 | Schema validation library and CI checks | 1.0d | Core Eng | I9-1 | ✅ CI fails unversioned events |
| I9-3 | Migrate high-volume event producers | 2.0d | Core Eng | I9-2 | ✅ top producers emit envelope |

### Initiative 10 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I10-1 | Telemetry-based tool ranking report | 1.0d | Product + Platform | I4-3,I5-3 | ✅ ranked list published |
| I10-2 | Deprecation warnings and migration notes | 1.0d | Platform Eng | I10-1 | warnings visible in CLI/MCP |
| I10-3 | Remove bottom 10-20% tools safely | 2.0d | Platform Eng | I10-2 | removals complete, tests green |

### Initiative 11 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I11-1 | Cache policy doc (TTL/invalidation) | 1.0d | Search/Infra | I5-1 | ✅ policy approved |
| I11-2 | Implement default tiering in query paths | 2.0d | Search/Infra | I11-1 | tiering active in target paths |
| I11-3 | Cache observability and regression tests | 1.0d | Search/Infra | I11-2 | hit-rate and stale-data tests in CI |

### Initiative 12 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I12-1 | Select top 10 workflows + baseline metrics | 1.0d | Platform + DX | I5-3 | list and baselines published |
| I12-2 | Implement canonical CLI/MCP pathways | 2.0d | Platform + DX | I12-1 | golden commands usable |
| I12-3 | Add non-canonical warnings and docs | 1.0d | Platform + DX | I12-2 | variance warnings active |

### Initiative 13 work packages (conditional)

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I13-1 | Add `[tui]` dependency and bootstrap app shell | 1.0d | Platform UI | I1 adoption gate | app boots in local env |
| I13-2 | Implement overview + sweep screens | 2.0d | Platform UI | I13-1 | screens render live data |
| I13-3 | Implement routing/alerts screens + read-only constraints | 2.0d | Platform UI | I13-2 | no mutating ops available |

### Initiative 14 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I14-1 | Map TUI metrics to canonical Prometheus inventory | 1.0d | SRE + Platform UI | I13-3 | inventory mapping doc merged |
| I14-2 | Add sweep history dashboard and panel tests | 1.0d | SRE + Platform UI | I14-1 | panel smoke tests pass |
| I14-3 | Remove corrupted legacy dashboard assets | 0.5d | SRE | I14-2 | only valid dashboard JSON remains |

### Initiative 15 work packages

| ID | Work package | Est | Owner | Depends on | Done when |
|---|---|---:|---|---|---|
| I15-1 | Define labeled dataset and eval rubric | 1.0d | ML Eng + Ingestion | I9-2 | ✅ rubric + dataset snapshot committed |
| I15-2 | Implement readability/depth/completeness scoring | 2.0d | ML Eng + Ingestion | I15-1 | evaluator no longer returns stub |
| I15-3 | Offline evaluation and threshold tuning | 1.0d | ML Eng + Ingestion | I15-2 | >=10% improvement achieved |
| I15-4 | Staged rollout + drift monitoring dashboard | 1.0d | ML Eng + SRE | I15-3 | staged rollout complete, alerts live |

## 8) Suggested Tracking Conventions

- Track each work package as an issue labeled with `initiative:<id>` and `phase:foundation|reliability|optimization`.
- Use one parent epic per initiative (`I0`..`I15`) and link all child work packages.
- Mark any package over 3 days as split-required before sprint planning.
