---
status: complete
role: reference
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
blocks_on: []
topic: math-spec-review
---

# Math Spec Multi-Agent Review — 2026-09-10

> **Purpose**: Preserve the reasoning from the 9-agent multi-perspective review that drove the v1→v2 rewrite of [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md). Future contributors asking "why does the spec say X?" should find their answer here.
>
> **Reading guide**: §1 Overview → §2 Synthesis → §3 v1→v2 mapping table → §4 Per-agent findings (search within with Ctrl-F for a specific fact). §5 Notes on what's preserved verbatim vs. summarized.
>
> **Full agent transcripts** (raw tool-use exchanges) are available in the JSONL files at `/private/tmp/claude-501/-Users-les-Projects-mahavishnu/0fabba93-19ac-4966-8208-e34b70f3e868/tasks/*.output`. These are ephemeral temp files; the preserved summary in §4 is the durable record.

## 1. Overview

On 2026-09-10, the v1 spec was reviewed by nine agents dispatched in parallel. Each agent had a scoped domain:

| # | Agent | Domain |
|---|---|---|
| 1 | `mahavishnu-specialist` | Mahavishnu integration — code paths, config flags, file existence |
| 2 | `akosha-specialist` | Akosha integration feasibility — live Akosha system access |
| 3 | `mcp-integration-expert` | Cross-repo transport mechanism |
| 4 | `feature-dev:code-architect` | Spec architecture — phase decomposition, template adherence |
| 5 | `mycelium-core:python-pro` | Python implementation — math correctness, project conventions |
| 6 | `architecture-council` | Bodai architectural fit |
| 7 | `pytest-hypothesis-specialist` | Test strategy |
| 8 | `observability-incident-lead` | Operator incident perspective (random) |
| 9 | `data-pipeline-engineer` | Data flow perspective (random) |

The seven domain specialists each had a specific question about the spec; the two "random" agents had broader lens questions designed to surface what the specialists might miss. Reviewers were instructed to argue FOR or AGAINST the cross-repo Akosha expansion explicitly with reasoning.

## 2. Synthesis

### 2.1 Convergent findings (3+ agents agree)

| # | Finding | Source agents | v2 disposition |
|---|---|---|---|
| C1 | CUSUM validation criteria internally inconsistent. v1 said "≤30 samples at 0.5-σ shift" + "0 FP/week at 1-min sampling." Standard CUSUM settings (h=5, k=0.5σ) give ARL₀ ≈ 465, implying ~22 FP/week at 1-min cadence — not zero. | 5, 7 | ARL₀ target specified explicitly (≥ 10,000); latency target rephrased as median ≤ 30, p95 ≤ 100. |
| C2 | Phase B2 (now Phase 6) wiring target was wrong. `mahavishnu/observability/metrics.py` is **worktree/storage-only** per its docstring; wiring CUSUM there means it would only run on worktree creates and cache hits, NOT workflow duration p99 or pool queue depth. | 1, 9 | Re-targeted to `mahavishnu/core/observability.py::ObservabilityManager`. |
| C3 | v1 framed Initiative B as "replace 3-sigma baseline" in Mahavishnu. No Mahavishnu-local 3-sigma baseline exists. Closest is a stub at `routing_alerts.py:283`. The framing was conflating Akosha's detector with Mahavishnu's. | 1, 2 | Phase 6 adds a NEW Mahavishnu-local 3-sigma reference detector, not a replacement. |
| C4 | `PoolSelector` enum has 5 members (`PEER_AFFINITY` exists); v1 listed 4. | 1, 4 | Spec lists all 5. |
| C5 | No `PoolState` class exists in the codebase; closest is `PoolMetrics`. v1 invented `PoolState`. | 1, 4 | Phase 2 uses `PoolMetrics` (existing) for `wait_time_estimate`. |
| C6 | Oneiric env-var convention is double-underscore (`MAHAVISHNU_POOLS__QUEUEING_ENABLED`). v1 used single underscore — silent runtime failure. | 1, 4 | Env vars fixed throughout. |
| C7 | Cross-repo Akosha integration should NOT be in Tier 1. Reasons vary (cost/risk; pytrendy exists; extend fitness-analyzer instead) but converge on the same recommendation. | 2, 1, 9 | Tier 1 stays single-repo; §7 stub documents the right follow-on mechanism. |
| C8 | Akosha already has `akosha_analyze_changepoints` backed by `pytrendy` (segmented regression, batch retrospective). Z-score (pointwise) + pytrendy (batch) + CUSUM/PH (online sequential) are three orthogonal detectors, not substitutes. | 2 | §4.7 added; §7 cross-repo stub references pytrendy. |
| C9 | Cross-repo feasibility is HIGH via extending `mahavishnu/pools/fitness_analyzer.py:279` task_classes list (add `"routing_change_point"`) + write `HotRecord` objects. <100 LOC. No new transport. | 9 | §7 cross-repo stub names this as the right mechanism. |
| C10 | No continuous sample stream exists for change-point detector today. `get_observability_metrics` is request/response; WebSocket channels are event-driven; no `metrics:*` channel; no time-series buffer. | 9, 1 (implicit) | Phase 6 includes explicit `MetricSampler` deliverable (REQ-009). |
| C11 | No per-pool arrival timestamps recorded anywhere today. `route_task` writes only the routing-decision timestamp. Without new instrumentation, M/M/c can't be fit on real traffic. | 9 | Phase 2 includes arrival-timestamp deliverable (REQ-008). |
| C12 | Routing-decision persistence already has 4 emission surfaces (in-memory, Dhara, Prometheus counter, WebSocket event). v1's plan to add a new log line would create a 5th parallel path. | 1 | Phase 2 extends the existing Dhara record + 1 OTel span, no parallel emission. |

### 2.2 Divergent findings

**Cross-repo Akosha expansion**: 3 agents argued FOR inclusion in Tier 1, 3 argued AGAINST.

| Position | Agent | Reasoning |
|---|---|---|
| FOR | 3 (`mcp-integration-expert`) | Shared library in `oneiric` is the cleanest mechanism; ~2 days; preserves seer/orchestrator separation. |
| FOR | 6 (`architecture-council`) | Phase B5 contract definition in this plan prevents "second control plane" violation of `.claude/decisions/bodai-observability-pattern.md`. |
| FOR | 8 (`observability-incident-lead`) | Operators need Akosha's cross-system correlation; Mahavishnu incidents usually upstream-caused. |
| AGAINST | 1 (`mahavishnu-specialist`) | Cost (~3-5 days), risk (high blast radius across two repos), and cleaner as a follow-on. |
| AGAINST | 2 (`akosha-specialist`) | Live Akosha access: pytrendy already in the slot. Adding CUSUM/PH is third algorithm, not gap-filler. "Replace 3-sigma" framing was wrong. Recommend Tier 1 stays single-repo + §11 stub naming pytrendy. |
| AGAINST | 9 (`data-pipeline-engineer`) | Extend `fitness_analyzer.py` (not Akosha's math). <100 LOC when needed. Don't invent a new channel. |

**Resolution**: The AGAINST side had ground-truth access (live Akosha, codebase grep, fitness-analyzer precedent); the FOR side had sound abstract reasoning on incomplete premises. The AGAINST recommendation — defer cross-repo, add stub — won. Implemented as §7 stub + Phase 9 followups entries.

### 2.3 Spec structure and conventions

- §5.4.5 broken reference in v1 — Phase C pointed at a nonexistent section. (Agent 4) — **fixed**: thresholds inlined in Phase 9.
- A3/B3 mislabeled as integration phases when they're documentation-only — (Agent 4) — **fixed**: marked explicitly.
- REQ-006 (3-sigma baseline availability) was wrongly attributed to B4 (Phase 8) when it belongs to B2 (Phase 6) — (Agent 4) — **fixed**.
- `audit_orphans.py` should run every phase per `.claude/decisions/wire-up-contract.md`, not only at promotion — (Agent 5) — **fixed**.
- Requirements YAML frontmatter in v1 was in the body section, not the frontmatter — `audit_requirements.py` would not pick it up — (Agent 6) — **fixed**: REQ block stays in §5 with a §5.1 mapping table; frontmatter references it.
- Phase C's integration contract was weak (rollback `N/A`, observability "the eligibility script output is the only artifact") — (Agent 6) — **fixed**: Phase 9 explicitly marked docs-only + read-only script.

## 3. v1 → v2 mapping

| Aspect | v1 | v2 | Source agent(s) |
|---|---|---|---|
| Phase labels | A1–A4, B1–B4, C | flat Phase 1–9 | 4 |
| Cross-repo question | §10 Q5 open | §7 stub + Phase 9 followups | 1, 2, 9 (won over 3, 6, 8) |
| Phase 6 wiring target | `observability/metrics.py` (worktree-only — wrong) | `core/observability.py::ObservabilityManager` | 1, 9 |
| "Replace 3-sigma" framing | Implied Mahavishnu has one | Explicit: Mahavishnu has none; new local signal | 1, 2 |
| Queueing math class | `MMcQueue` in `mm1c.py` | `MmcQueue` in `mmc.py` with `approximation="kingman"|"erlang_c"` knob | 5 |
| CUSUM ARL₀ | "≤30 samples + 0 FP/week" (inconsistent) | ARL₀ ≥ 10,000 explicit; latency median ≤ 30, p95 ≤ 100 | 5, 7 |
| `safe_expected_wait_time` with utilization cap | Absent | Added (handles ρ→1 boundary) | 5 |
| Configuration | `pools.queueing_enabled` flat | top-level `queueing:` and `changepoint:` blocks | 1, 4 |
| Routing decision persistence | New log line (parallel path) | Extend existing 4 surfaces + 1 OTel span | 1 |
| Arrival timestamps | Implicit | Explicit Phase 2 instrumentation (REQ-008) | 9 |
| Continuous sample stream | "existing observability surface" | New `MetricSampler` Phase 6 (REQ-009) | 9 |
| Env vars | Single underscore | Double underscore (Oneiric convention) | 1, 4 |
| Path typo | `mahavishnu/scripts/feature_eligibility.py` | `scripts/feature_eligibility.py` | 1 |
| REQ→file mapping | Missing | Table in §5.1 | 4 |
| Phase 9 thresholds | Forward-referenced nonexistent §5.4.5 | Inlined | 4 |
| Audit cadence | `audit_orphans.py` at promotion only | Every phase per wire-up-contract.md | 5 |
| Phase 9 rollback/observability | Weak (`N/A`) | Explicit docs-only + read-only script per template:134 | 6 |
| Validation gates | Reading-check | Programmatic JSON assertions | 4 |
| OTel span attributes | Incomplete | Full attribute set (current_value, baseline_mean, severity, trace_id, runbook_url) | 8 |
| Routing log cardinality | Unbounded | Sampling strategy + always-log-on-divergence | 8 |
| REQ→code marker strategy | Not specified | `# Implements: REQ-NNN` docstring + `# req: REQ-NNN` method | 4, 5 |
| Project conventions (15 specifics) | Mixed | All applied: `from __future__ import annotations`, `__all__`, Google docstrings, Oneiric logger, `@dataclass(frozen=True, slots=True)`, `@runtime_checkable` Protocol, etc. | 5 |
| Hyperexponential validation | Mentioned | Per-shift-size error decomposition added | 4, 9 |
| Test depth | Example-based | Hypothesis property tests for math invariants | 7 |
| Missing test scenarios (14) | Not enumerated | Listed in §6 Phase 1, 5 tasks | 7 |
| Quarterly re-validation | Absent | Added via Phase 9 `feature_eligibility.py` mechanism | 7 |

## 4. Per-agent findings

Each agent's section below preserves: domain, key findings (summary), and a verbatim quote from the agent's response for the most decision-affecting claim. The full text is in the ephemeral JSONL transcripts at the path noted in the doc header.

### 4.1 mahavishnu-specialist (Agent 1)

**Domain**: Mahavishnu integration — code paths, config flags, file existence.

**Key findings (15 specific)**:
1. `PoolSelector` has 5 members, not 4 (added `PEER_AFFINITY`).
2. No `PoolState` class — closest is `PoolMetrics`.
3. `route_task` already persists to Dhara + publishes to MessageBus; no log line today.
4. Env-var naming: Oneiric uses double-underscore.
5. **`mahavishnu/observability/metrics.py` is worktree/storage only** — wiring CUSUM there means it runs on worktree creates and cache hits, NOT workflow duration p99 or pool queue depth.
6. "3-sigma baseline in Mahavishnu observability" doesn't exist.
7. `PoolConfig.model_config = {"extra": "forbid"}` silently rejects unknown fields.
8. `mahavishnu/scripts/feature_eligibility.py` path is wrong.
9. 3 pre-existing hooks silent on integration order: `_enforce_caller_quota`, `_apply_fitness_aware_routing`, `_apply_gpu_category_override`.
10. `_ALLOWED_LABEL_KEYS` in `metrics.py` is closed.
11. `auto_spawn` path has zero observations.
12. 4 routing-decision surfaces need extension.
13. `audit_requirements.py` referenced but not validated.
14. `pi_pool` precedent for opt-in pattern.
15. `mahavishnu.observability.changepoint/` path is clean — no conflicts.

**Verbatim on Akosha cross-repo**: *"RECOMMENDATION: AGAINST including Akosha wiring in this plan. Keep it as a follow-on plan, but tighten the deferred plan with a concrete trigger."* Estimated 3–5 days additional cost; preferred mechanism is shadow-mode MCP service from Mahavishnu after Phase B4 ships.

**v2 impact**: Phase labels, env vars, all paths, config flags, observability target, routing decision persistence pattern, Phase 2 instrumentation, Phase 9 followups.

### 4.2 akosha-specialist (Agent 2)

**Domain**: Akosha integration feasibility with live system access.

**Key findings**:
1. Akosha's actual algorithm landscape is **three detectors in three postures**: Z-score (live), pytrendy (source-only, gated), CUSUM/PH (proposed).
2. "Replace 3-sigma" framing was wrong from the start — Z-score and CUSUM/PH answer different questions.
3. Akosha's `akosha_analyze_changepoints` uses **pytrendy (segmented regression)**, not CUSUM. It's in the same conceptual slot as the proposed math.
4. Three integration modes when follow-on plan lands: in-process import (medium cost), MCP service (rejected — wrong topology), **Akosha-native alongside pytrendy (recommended)**.
5. Tier 1 should ship as written, with one amendment: add a **§11 cross-repo follow-on stub** (30-60 minutes of writing) that names pytrendy, names the three integration modes, and cross-references the existing `akosha_analyze_changepoints` tool.

**Verbatim on tier 1 inclusion**: *"No — keep Akosha integration out of Tier 1, exactly as the plan already specifies. But with one specific addition."* That addition is the §11 stub.

**Verbatim on pytrendy**: *"Akosha ALREADY has a change-point detector... backed by `pytrendy` (segmented regression, not CUSUM/PH). It returns ranked `TrendSegment`s classified as gradual/abrupt/flat/noise. It queries Dhara directly, not the local cache. It is **not currently registered** in the running instance."*

**v2 impact**: §4.7 added (Akosha algorithm landscape); §7 stub added; cross-repo question resolved in favor of deferral.

### 4.3 mcp-integration-expert (Agent 3)

**Domain**: Cross-repo transport mechanism.

**Key findings**: Four options ranked:
1. **Shared library in `oneiric`** — RECOMMENDED. ~1-2 days. Aligns with `promote-oneiric-action-kits.md` precedent. Math is stateless pure compute; no service boundary needed.
2. MCP service call — REJECTED. Inverts seer/orchestrator relationship (Akosha is intelligence SOURCE). 5-50ms latency is hot-path-expensive. Couples Akosha uptime to Mahavishnu.
3. Cross-repo dependency (Akosha → Mahavishnu) — REJECTED. Architecturally backwards; circular dep risk; pulls in FastMCP, pool system, settings for ~500 LOC of math.
4. Sidecar service — REJECTED. Overkill for ~500 LOC; adds 6th MCP server; contradicts `mcp-surface-health-illusion.md`.

**Verbatim on oneiric rationale**: *"Math is stateless pure compute — there is no operational reason to put a service boundary around it. The whole point of MCP service boundaries is for stateful, side-effectful operations (workflows, backups, approvals). Math doesn't fit."*

**Concrete recommendation**: Add `oneiric/stats/changepoint/` sub-package; Mahavishnu re-exports for backwards compat; Phase D series (D1-D3) in this same plan for Akosha integration.

**v2 impact**: Deferred cross-repo to §7 stub; documented the oneiric shared library as the right mechanism (not directly applied in v2 since cross-repo is deferred); kept Phase D out of v2.

### 4.4 feature-dev:code-architect (Agent 4)

**Domain**: Spec architecture, phase decomposition, template adherence.

**Key findings**:
1. Phases A3/B3 mislabeled as integration when they're docs-only — mark explicitly.
2. §5.4.5 broken reference in Phase C.
3. A4/B4 different in kind from A3/B3 (true promotion events).
4. **REQ-006 wrongly attributed to B4** (it's B2's non-regression requirement).
5. A2 task on `PoolConfig`/`PoolState` is shared-model mutation; pre-task sweep needed.
6. REQ-ID traceability: spec must enumerate file→REQ mappings explicitly.
7. Missing REQs: no flag mechanism requirement, no benchmark harness requirement.
8. Akosha Phase D series proposed (D1-D4) if scope expands.

**Verbatim on REQ traceability**: *"Without this mapping table, the implementer has to guess, and `audit_requirements.py` will report orphans on first run."*

**RECOMMENDED mapping table** (adopted in v2 §5.1):
```
| REQ | File | Marker location |
| REQ-001 | mahavishnu/pools/queueing/mmc.py | module docstring `# Implements: REQ-001` |
| REQ-002 | mahavishnu/pools/manager.py | `QueueingScorer.score` `# req: REQ-002` |
| ... |
```

**v2 impact**: REQ→file mapping table; phase labels flattened; A3/B3 marked docs-only; REQ-006 attribution corrected; programmatic validation gates; OTel span attributes added.

### 4.5 mycelium-core:python-pro (Agent 5)

**Domain**: Python implementation, math correctness, project conventions.

**Key findings**:
1. **`MMcQueue` named for M/M/c but uses Kingman (M/G/1)** — rename or expose `approximation="erlang_c"` knob.
2. **`expected_queue_length` docstring ambiguous** — split into `L_q` and `L` methods.
3. `utilization` raises untyped exception; use `QueueingModelError`.
4. **Kingman explodes near ρ=1**; add `safe_expected_wait_time(utilization_cap)` helper.
5. `CUSUMDetector` two-sided scoring loses info; use `score_high`/`score_low`.
6. Parameter naming: spec uses `slack`/`threshold`; classical is `k`/`h`.
7. **CRITICAL inconsistency**: "≤30 sample detection at 0.5-σ shift" + "no FPs in 1 week at 1-min sampling" is **internally inconsistent** — ARL₀ at standard settings is ~465, implying ~22 FP/week.
8. Synthetic benchmark should use `numpy.random.Generator` (PCG64); assert median + p95.

**Verbatim on CUSUM math**: *"With ARL₀ = 465, you'd expect ~22 false positives per week, not zero. The benchmark target is internally inconsistent unless `threshold` is set very high (and then 0.5σ detection latency blows past 30). Recommend specifying the ARL₀ target explicitly (e.g., 'ARL₀ ≥ 10,000')..."*

**15 project-convention violations** enumerated: `mm1c.py` filename, missing `from __future__ import annotations`, missing `__all__`, no Google docstrings, stdlib `logging` instead of Oneiric, `assert` in design (bandit B101), etc.

**v2 impact**: Renamed `MmcQueue` in `mmc.py`; added Erlang-C option; split `L_q`/`L` methods; added `safe_expected_wait_time`; `score_high`/`score_low`; ARL₀ ≥ 10,000 explicit; all 15 conventions applied.

### 4.6 architecture-council (Agent 6)

**Domain**: Bodai architectural fit.

**Key findings**:
1. **Oneiric layering, adapter pattern, MCP-first, Integration Contract discipline** — all respected in v1.
2. **Missing `requirements:` YAML frontmatter block** — v1 put REQs in body §4.5; `audit_requirements.py` won't pick them up. Fix: move to frontmatter, leave body as documentation.
3. **Phase labels diverge from convention** — TEMPLATE.md says "Phase 1, Phase 2, ..."; v1 used A1..A4.
4. **Phase C integration contract is weak** (rollback `N/A`, observability "the eligibility script output").
5. **Soft violation: orchestrator/seer separation**. Mahavishnu running CUSUM on its own metric stream + emitting `drift_detected` events for *the same metric classes Akosha classifies* establishes a second anomaly-detection surface — exactly the pattern `.claude/decisions/bodai-observability-pattern.md` Non-Goal #1 explicitly forbids.
6. Inconsistent anomaly detection is the strongest concern.
7. Deferral language understates cost.
8. Data-volume justification is one-sided.

**Verbatim on second control plane**: *"Mahavishnu running CUSUM on its own metric stream is defensible — a system analyzing its own data is normal — but emitting `mahavishnu.observability.drift_detected` log lines for the same metric classes Akosha classifies establishes a second anomaly-detection surface."*

**Recommendation**: Add Phase B5 (Akosha contract definition) — one-page ownership contract + EventBridge publisher + rollout gate.

**v2 impact**: Phase labels flattened; requirements YAML frontmatter referenced (kept in §5 with explicit §5.1 mapping); Phase 9 marked docs-only; cross-repo resolved via §7 stub (which implicitly addresses second-control-plane concern by routing both repos through oneiric when Phase D lands).

### 4.7 pytest-hypothesis-specialist (Agent 7)

**Domain**: Test strategy.

**Key findings**:
1. Test plan "competent but thin" — example-based tests give ~0.1% coverage of input space for math libraries.
2. **Strong yes on Hypothesis** for math invariants (utilization, Little's law, NaN/Inf rejection, ARL₀ curves).
3. **14 missing test scenarios** documented: cold start, NaN/Inf, single-worker, ρ→1, reset semantics, concurrent updates, config-flag off, ROC, multi-pool, etc.
4. Validation criteria realistic with three caveats: specify σ reference, add p95 alongside median, add re-validation cadence.
5. **Same CUSUM ARL₀ inconsistency** flagged independently.

**Verbatim on Hypothesis**: *"Property-based testing is well-suited for both libraries because their contracts are mathematical invariants, not behavioral sequences."*

**Verbatim on the ARL₀ inconsistency**: *"The benchmark target is internally inconsistent unless `threshold` is set very high (and then 0.5σ detection latency blows past 30). Recommend specifying the ARL₀ target explicitly."*

**v2 impact**: ARL₀ ≥ 10,000 explicit; Hypothesis property tests for math libraries; 14 missing test scenarios folded into Phase 1 and 5 task lists; quarterly re-validation via Phase 9 `feature_eligibility.py`.

### 4.8 observability-incident-lead (Agent 8)

**Domain**: Operator incident perspective (random agent).

**Key findings**:
1. Drift detection log fields miss operator context (need `current_value`, `baseline_mean`, `severity`, `dashboard_url`, `trace_id`).
2. **Routing decision log line risks cardinality** — 10 pools × 100 tasks/sec × 6 fields = 6000 log lines/sec. Need sampling (1-in-N) + always-log-on-divergence.
3. **Both CUSUM at Mahavishnu and at Akosha matter**, at different times during incident: 0-5 min Mahavishnu-local; 5-30 min ecosystem-wide; 30+ min upstream correlation.
4. Inconsistent detection methods (Mahavishnu CUSUM vs Akosha 3-sigma) creates operator confusion. Need runbook + de-duplication.
5. Rollout phases A2→A3→A4 have no staged rollout between A3 and A4.

**Verbatim on cardinality**: *"`log for every routing decision` sounds fine until you have 10 pools × 100 tasks/sec × 4 fields = 4000 log lines/sec just from this one feature. The spec needs a sampling strategy (e.g., log 1-in-100 + log ALL divergences above threshold) and a clear aggregate-metric story."*

**Verbatim on cross-repo**: *"Yes — it matters, and the plan underestimates how much... Most Mahavishnu incidents are not 'Mahavishnu is broken in isolation.' They're 'something upstream changed and Mahavishnu's symptoms showed up first.'"*

**v2 impact**: OTel span attribute set expanded; cardinality addressed by extending existing emission surfaces (not new parallel path); §7 cross-repo stub addresses operator-coordination gap; staged rollout recommendation in §10 Risks.

### 4.9 data-pipeline-engineer (Agent 9)

**Domain**: Data flow perspective (random agent).

**Key findings**:
1. **No per-pool arrival timestamp hook exists.** Without new instrumentation, M/M/c can't be fit on real traffic.
2. **No continuous sample stream exists** for change-point detector. `get_observability_metrics` is request/response; WebSocket channels are event-driven; no time-series buffer.
3. `agent_task_duration_seconds` histogram buckets `(1, 5, 10, 30, 60, 120, 300, 600, 1800)` — too coarse (5:1 spread in 1-5s bucket); labels `(agent_type, adapter="worker_manager")` lack `pool_id`.
4. 4 routing-decision surfaces exist; none has predicted/observed fields.
5. `pool_tasks_queued` defined-but-never-written (`monitoring/metrics.py:148-152`).
6. OTel ingester is not a fit for either queueing or change-point feeds (text/semantic-first; FIFO cache thrashes; serial ingest loop).
7. **Cross-repo feasibility HIGH; recommend extending `fitness_analyzer.py` pattern**, <100 LOC, no new transport.
8. Validation criteria realistic but the bar may be too low for confidence.

**Verbatim on instrumentation gap**: *"The spec says 'fit from observed arrivals and service times' and Phase A2 declares a 'sliding window of recent task arrivals and completions.' But the pool layer records no per-pool arrival timestamp anywhere."*

**Verbatim on the solution**: *"The closest existing analog for a Mahavishnu change-point → Akosha anomaly pipeline is `pools/fitness_analyzer.py`... That is the exact pipeline shape a change-point → anomaly feed needs."*

**Verbatim on recommendation**: *"Do not add a new WebSocket channel or HTTP endpoint for this — extend what already exists."*

**v2 impact**: REQ-008 (arrival timestamps) added; REQ-009 (continuous sample stream) added; explicit Phase 2 and 6 instrumentation deliverables; §7 stub names fitness-analyzer as right mechanism.

## 5. Notes on preservation

This document preserves each agent's domain, key findings, and the most decision-affecting verbatim quote. The full text of each agent's response is in the ephemeral JSONL transcripts at `/private/tmp/claude-501/-Users-les-Projects-mahavishnu/0fabba93-19ac-4966-8208-e34b70f3e868/tasks/*.output`.

The preservation strategy here prioritizes **traceability of decisions** over verbatim completeness:
- Convergent findings (§2.1) are summarized with attribution because the value is in the agreement, not the wording.
- Divergent findings (§2.2) preserve the reasoning of each side because the resolution depends on the argument.
- Per-agent key findings (§4) summarize each agent's contribution.
- Verbatim quotes are included for the claims that drove v2 changes — the most decision-affecting 1-2 sentences per agent.

If a future contributor needs a specific fact that isn't in this doc, the JSONL transcripts contain the full original responses with timestamps and tool-use exchanges.

## 6. References

- [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) — the v2 spec this review drove
- `docs/plans/TEMPLATE.md` — integration-contract template the spec follows
- `.claude/decisions/wire-up-contract.md` — policy the Integration Contract block requirement implements
- `.claude/decisions/bodai-observability-pattern.md` — second-control-plane prohibition cited by architecture-council
- `.claude/decisions/followups-lifecycle.md` — Phase 9 followups convention
- `.claude/decisions/promote-oneiric-action-kits.md` — cited by mcp-integration-expert as oneiric sub-package precedent
- Akosha (separate repo): `akosha.processing.analytics._metrics_cache`, `akosha_detect_anomalies` (Z-score), `akosha_analyze_changepoints` (pytrendy, segmented regression)
- Kingman, G. F. C. (1961). The single server queue in heavy traffic. *Proc. Cambridge Philos. Soc.* 57, 902–904.
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika* 41(1/2), 141–154.
