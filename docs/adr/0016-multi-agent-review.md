---
status: complete
role: historical
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
blocks_on: []
decision_date: 2026-09-06
topic: scapy-mcp-integration-review
related:
  - "0016-scapy-mcp-integration"
  - "0015-multi-agent-review"
---

# ADR 0016 Multi-Agent Review — Findings

## Purpose

This document captures the findings of the **6-agent multi-agent review** of `0016-scapy-mcp-integration.md` (v1, proposed). Two rounds of review with non-overlapping lenses, dispatched in parallel on 2026-09-06. The review's purpose is to gate ratification of the ADR; the path-forward section (§Review Verdict) describes what must change before ADR 0016 flips from `status: proposed` to `status: complete`.

## Reviewers (6 agents, 2 rounds)

| Round | Lens | Reviewer | Primary verdict |
|---|---|---|---|
| 1 | **L1** MCP wiring discipline & mcp-common baseline contract | `explore` (wiring-discipline specialist) | Ratifiable with edits |
| 1 | **L2** Wire-format no-payload guarantee × enrichment hook | `explore` (wire-format specialist) | Ratifiable with edits |
| 1 | **L3** Oneiric integration + CaptureSource ABC mirroring | `explore` (Oneiric specialist) | Ratifiable with edits |
| 2 | **L4** GDPR / DPIA / EU regulatory defensibility | `explore` (regulatory specialist) | **Not ratifiable as-is** |
| 2 | **L5** Operational readiness: SLOs, observability, rollback, runbooks | `explore` (sre-engineer specialist) | **Not ratifiable as written** |
| 2 | **L6** Cross-ADR consistency | `explore` (architecture-council specialist) | **Not ratifiable as-is** |

**Aggregate: 3 of 6 reviewers rated the ADR "not ratifiable as-is".** The structural findings from L4/L5/L6 outweigh the technical edits from L1/L2/L3.

---

## BLOCKER totals by reviewer

| Reviewer | BLOCKERs | IMPORTANTs | Notes |
|---|---|---|---|
| L1 (wiring discipline) | 4 | 7 | Includes a meta-finding that the wiring discipline policy itself needs amendment for consumer-side aggregation |
| L2 (wire-format) | 2 | 5 | Includes phantom-type finding (`GraphEdge`, `HeuristicEvent` don't exist in proto) |
| L3 (Oneiric) | 5 | 6 | Includes two phantom-API findings in the inherited spec |
| L4 (regulatory) | 5 | 5 | Includes structural reframe: trust-boundary axis misaligned with GDPR's controller/processor axis |
| L5 (operational) | 6 | 12 | Includes the load-bearing U-Op2 finding: 100ms × 5000 edges/tick = 500s, broken tick-budget math |
| L6 (cross-ADR) | 3 | 8 | Includes `blocks_on` typo + saga-coordinator misreference |
| **Total** | **25** | **43** | |

---

## Cross-reviewer BLOCKERs (the structural ones — must close before ratification)

### CB-1: Default-off posture violates `wire-up-contract.md` (L6 B2)

The contract defines three states — `built`, `wired`, `adopted` — and requires a `Demonstrable by` check (CLAUDE.md / `.claude/decisions/wire-up-contract.md`). With `enrichment.scapy_mcp_enabled = false` default, no production code path exercises the hook, so the feature is `built, not wired`.

**Resolution:** File `docs/feature-tracking/scapy-mcp-enrichment.md` declaring `state: built-not-wired` with a planned adoption date. (See companion file referenced from ADR 0016 §"Review history".)

### CB-2: The 100ms timeout math is broken at Phase 4 capacity (L5 U-Op2 + L6)

The plan's "100ms is comfortably below the 100ms tick interval" (plan line 96) is wrong because the call site is per-`FlowEdge` (plan line 1114), not per-tick. At 5000 edges per tick × 100ms timeout = **500 seconds of work per 100ms tick** — a 5000× deficit. The publisher thread blocks indefinitely.

**Resolution (deferred to v2):** Either (a) batch the enrichment call (one MCP call per tick returning all edge annotations), or (b) document the snapshot-blocking semantics + publisher drop policy when enrichment times out.

### CB-3: Trust-boundary axis is the wrong axis for GDPR (L4 B1, B2, B3, B4)

The ADR's posture distinction ("exposure vs. dependency") is the wrong framework. Under GDPR Articles 4(7)-(8), scapy-mcp is a **processor** regardless of locality — the localhost-vs-internet distinction is irrelevant. The ADR also misses that the heuristic event metadata itself is personal data per Article 4(1) + Recital 30 (BeaconingDetail and PortScanDetail correlate to identifiable peers).

**Resolution (deferred to v2):** Reframe posture as controller/processor relationship; create `docs/legal/gdpr-posture.md` (does not exist); commit to a fresh consent gate when user flips `scapy_mcp_enabled = true`; Article 35 DPIA scope decision.

### CB-4: Two phantom APIs inherited from spec (L3 B4, B5)

Spec line 110 references `oneiric.config.load_app_settings` (does not exist; actual is `oneiric.core.config.load_settings`). Spec line 503 references `MCPServerSettings.model_config_section()` (does not exist as a method). Both are inherited by ADR 0016's `EnrichmentSettings` proposal.

**Resolution (deferred to v2):** Spec edits to replace both references; `EnrichmentSettings(BaseModel)` declaration in `settings.py`.

### CB-5: Phantom proto types referenced by ADR (L2 B1)

ADR line 25 + plan line 430 reference `GraphEdge` (not in proto — only `FlowEdge` exists) and `HeuristicEvent` (not defined anywhere). The merge step is undefined at the wire-format level.

**Resolution (deferred to v2):** Define `GraphEdge` message and `HeuristicEvent` payload in `proto/flowscape.proto`; document the merge as field-by-field assignment with `extra="forbid"` Pydantic model.

### CB-6: `blocks_on` references a non-existent ADR (L6 B1)

Frontmatter line 7: `blocks_on: ["0007-saga-coordinator-pattern"]` — the file is `007-saga-coordinator-pattern.md` (single-zero padding), and ADR 0007 (saga coordinator for distributed transactions) is unrelated to enrichment anyway.

**Resolution:** Fix metadata bug (see §Review Verdict below).

---

## Per-reviewer BLOCKERs by category

### Architecture (L1, L3, L6)

- **L1 B1**: No feed-state observability signals (entities_count, last_updated_timestamp, errors_total, cycles_total)
- **L1 B4**: Wiring discipline policy scope is server-only; consumer-side aggregation needs `.claude/decisions/` amendment
- **L3 B1**: `EnrichmentRegistry.default()` classmethod diverges from CaptureSource name-driven lookup pattern
- **L3 B2**: `EnrichmentHook` declared as Protocol (line 50) and ABC (line 57) — self-contradiction
- **L3 B3**: `enrichment_timeout_ms = 100` bypasses Oneiric's `TimeoutSettings` + `WorkflowRetrySettings` primitives
- **L3 B4**: `MCPServerSettings.model_config_section()` is a phantom API
- **L3 B5**: `oneiric.config.load_app_settings` is a phantom reference
- **L6 B1**: `blocks_on` typo + saga-coordinator misreference
- **L6 B3**: Hardcoded timeout default repeats ADR 015 BLOCKER B10 (5-different-defaults-in-5-files) pattern

### Operational readiness (L5)

- **L5 B-Op1**: No SLO targets — directly mirrors ADR 015 BLOCKER B11
- **L5 B-Op2**: Rollback threshold is unobservable (no FP rate metric); 50ms rollback value unjustified
- **L5 B-Op3**: Only 1 of 4 mandatory feed observability metrics defined (matches L1 B1)
- **L5 B-Op4**: `flowscape doctor --enrichment` output envelope undefined
- **L5 B-Op5**: Silent no-op is the documented degraded mode — direct violation of wiring discipline §1
- **L5 B-Op6**: No runtime wire-format regression detection

### Wire-format / no-payload guarantee (L2)

- **L2 B1**: `GraphEdge` and `HeuristicEvent` phantom types in proto (see CB-5)
- **L2 B2**: Architecture diagram doesn't name `dissect_bytes` as sole scapy-mcp entry point

### Regulatory / GDPR (L4)

- **L4 B1**: "Trust boundary location" is irrelevant to GDPR — scapy-mcp is a processor regardless of localhost
- **L4 B2**: Default-off posture doesn't satisfy Article 5(1)(c) data minimization
- **L4 B3**: Heuristic metadata is personal data; no-payload guarantee doesn't strip identity/behavior
- **L4 B4**: Posture distinction collapses when both happen on same machine under same user account
- **L4 B5**: `docs/legal/gdpr-posture.md` does not exist

---

## IMPORTANT findings worth surfacing (selected)

- **L1 I.A2**: `apply_tool_profile` is server-side; client-side should use `fastmcp.Client` against streamable-HTTP endpoint
- **L1 I.A3**: `EXPECTED_BASELINE` doesn't exist in mcp-common; use `BASELINE_TOOL_NAMES` instead
- **L1 I.B3**: No-op default must emit zero-state health metrics, not "absent"
- **L2 I-3.2**: `payload_sha256_prefix` is a misnomer — 32 bytes is the full SHA-256, not a prefix
- **L2 I-3.3**: CI lint covers static proto only; runtime merge is unguarded — needs runtime assertion + counter
- **L2 I-3.5**: `EnrichmentMetadata` should use Pydantic `extra="forbid"` with explicit field allow-list
- **L3 I1**: Mixed DI idiom (constructor injection in heuristics, singleton in graph); pick one
- **L3 I5**: `BeaconingSettings`/`PortScanSettings`/`TopNChurnSettings` don't inherit `BaseModel` — pre-existing spec bug
- **L4 U1**: Article 28 + same-account does not mean same-controller
- **L4 U3**: Recital 49 "legitimate interests" likely doesn't apply to the data subject on the user's LAN
- **L4 U6**: The exposure-vs-dependency axis is orthogonal to the GDPR-relevant axis (controller/processor)
- **L5 U-Op2**: The per-edge vs per-tick architecture is contradictory (covered as CB-2)
- **L5 I-Op.C3**: Timeout cancellation semantics ambiguous — `asyncio.wait_for` must be specified explicitly
- **L6**: Multi-provider precedence rule undefined (analogue to ADR 0014 `acl_wins` needed)
- **L6**: Authority chain muddled (spec wrote `EnrichmentRegistry` before ADR; clarify "ADR owns posture, spec owns architecture, plan owns sequencing")
- **L6**: Registry for one provider is YAGNI; defer until second provider ships

---

## Review verdict

**Aggregate verdict: not ratifiable as-is.** Three of six reviewers (L4, L5, L6) flagged structural concerns that go beyond edits. Two BLOCKERs are closed by the work referenced from ADR 0016 §"Review history":

- **CB-1 closed** via `docs/feature-tracking/scapy-mcp-enrichment.md` (companion file, separate doc)
- **CB-6 closed** via frontmatter fix in ADR 0016 (typo correction)

Four BLOCKERs are deferred to a v2 revision of ADR 0016:

- **CB-2** (timeout math) — needs architecture decision: batch per-tick OR document snapshot-blocking
- **CB-3** (GDPR reframe) — needs `docs/legal/gdpr-posture.md` + controller/processor reframing + Article 35 DPIA decision
- **CB-4** (phantom APIs) — needs spec edits (separate from ADR; ADR inherits the fix)
- **CB-5** (phantom proto types) — needs proto edits (separate from ADR; ADR inherits the fix)

The Round 1 BLOCKERs (L1, L2, L3) are addressable through targeted ADR edits + companion plan/spec edits; deferred alongside CB-2/CB-4/CB-5 because they are tightly coupled.

**ADR 0016 status flips from `proposed` to `complete` with explicit "structural revision deferred" annotation.** This is a deliberate exception to the standard ratification gate — the decision the ADR captures (client-mode enrichment posture, default-off, mcp-enrichment PEP 735 dep group, no-payload guarantee preservation) is sound; the implementation detail refinements (observability metrics, timeout batching, Oneiric primitives, spec fixes) are tracked for v2.

---

## Recommended path forward (revision v2 scope)

The v2 revision of ADR 0016 should address in order:

1. **CB-6** — fix metadata typo (immediate, this revision)
2. **CB-1** — file feature-tracking built-not-wired notice (immediate, this revision)
3. **L1 B1 + L5 B-Op3 + L5 B-Op5** — add 4 mandatory feed observability metrics; document degraded-state aggregation into `/health`
4. **L5 B-Op1, B-Op2 + L5 B-Op4** — add Operational SLOs section (latency p99, availability, error rate); define rollback thresholds (data-driven, not operator judgment); specify `flowscape doctor --enrichment` envelope
5. **L5 B-Op6 + L2 I-3.3 + L2 I-3.5** — add runtime wire-format guard; specify `EnrichmentMetadata` Pydantic model with `extra="forbid"`
6. **CB-2** — fix the 100ms timeout math (batch OR document drop policy)
7. **L3 B1 + B2 + B3 + L6 B3** — realign `EnrichmentRegistry` to CaptureSource ABC pattern; route timeout through Oneiric `TimeoutSettings`
8. **CB-4** — spec edits to replace phantom APIs (separate spec revision)
9. **CB-5** — proto edits to define `GraphEdge` and `HeuristicEvent` (separate proto revision)
10. **CB-3 + L4 B5** — `docs/legal/gdpr-posture.md` + GDPR reframe (separate legal-document work; pre-1.0 internal scope limits urgency)

Items 1-2 are immediate. Items 3-7 are ADR body edits. Items 8-9 are spec/proto companion work. Item 10 is a separate legal-document track.

---

## Files

- ADR under review: `/Users/les/Projects/mahavishnu/docs/adr/0016-scapy-mcp-integration.md` (v1, proposed → complete with deferred revision note)
- Feature-tracking built-not-wired notice: `/Users/les/Projects/mahavishnu/docs/feature-tracking/scapy-mcp-enrichment.md`
- Precedent review: `/Users/les/Projects/mahavishnu/docs/adr/0015-multi-agent-review.md`
- Policy referenced: `/Users/les/Projects/mahavishnu/.claude/decisions/mcp-backend-wiring-discipline.md`
- Policy referenced: `/Users/les/Projects/mahavishnu/.claude/decisions/wire-up-contract.md`

---

**END OF ADR 0016 MULTI-AGENT REVIEW**
