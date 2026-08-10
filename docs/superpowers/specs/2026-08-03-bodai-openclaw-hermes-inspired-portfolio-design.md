# Bodai OpenClaw/Hermes-Inspired Follow-Ups — Portfolio Design

Date: 2026-08-03
Status: Draft (pending user review)
Owner: les
Scope: Cross-repo portfolio, no implementation yet

## Context

Mahavishnu is the control plane for the **Bodai Ecosystem** (Mahavishnu / Session-Buddy / Akosha / Crackerjack / Dhara / Oneiric). The 2026-07-21 worker-readiness design froze a worker surface and a contract; the 2026-08-03 worker-surface cleanup (`chore(workers): remove terminal-openclaw and terminal-zsh`, commit `5bfa2430`) simplified it further. cc-connect is intentionally out of scope — operators use it separately with Claude Code.

The cleanup leaves three architectural gaps that OpenClaw and Hermes already solve:

1. **Durable ingress** — webhook endpoints accept work but never enqueue; an MCP restart loses accepted requests.
1. **Durable memory lifecycle** — channel sessions live only in memory; durable storage for forked conversations / branch metadata is missing.
1. **Rubric-scored outcomes** — every workflow execution publishes a status but no structured outcome rubric; downstream routing decisions and adaptive scheduling have nothing to act on.

The previous research (`wf_37283d45-77e`, `wc34b8gza`) inventoried 16 immediate candidates across the Bodai ecosystem. They cluster around three leverage primitives — **durable ingress**, **durable memory lifecycle**, **rubric-scored outcomes**. This portfolio coordinates them.

## Scope

### In scope

- The 16 ranked candidates from the prior research inventory, grouped by owning repo.
- Cross-repo sequencing, dependency graph, integration contract template.
- {built, wired, adopted} tracking.
- One consolidated spec for Crackerjack (per user direction — combine skill metrics wire-up, outcome contract completion, AsyncTaskManager durability, plugin trust fixes, malformed SessionBuddyMCPTracker URL fix).

### Out of scope

- Per-repo implementation details. Each per-repo spec lives in its own repo and gets its own brainstorming → spec → plan → implementation cycle.
- cc-connect integration into Mahavishnu.
- Anything beyond the 16 inventoried candidates (research-only ideas stay parked in the portfolio appendix).
- External productization. This is internal control-plane work.

## Architecture overview — dependency graph

Three layers. Higher layers depend on lower layers; lower layers can ship and be adopted independently.

```
Layer 0 — Dhara substrate (D-WIRE, internal Dhara repo)
  D-LOCK      substrate-backed LockStore
  D-AUDIT     durable AuditLog subscriber
  D-OBJ-SCHEMA typed object schemas for cross-system durable entities
  D-REPLAY-VEC vector clock / Lamport sequencing for durable objects
      │
      ▼
Layer 1 — Per-repo specs (parallel)
  M-INFRA   Mahavishnu (control plane)
  S-MEM     Session-Buddy (memory + channel sessions)
  A-RUBRIC  Akosha (intelligence + fitness)
  C-WIRE    Crackerjack (one combined spec, per user direction)
      │
      ▼
Layer 2 — Cross-cutting integration specs
  X-REPLAY         end-to-end replay path (M + S-B + D)
  X-RUBRIC-FEEDBACK Crackerjack rubric evaluator → Akosha (A + C + M)
  X-CHANNEL-DURABLE end-to-end channel session durability (S-B + D + A event log)
```

The portfolio spec is the source of truth for layer membership and the integration contract template. Per-repo specs own their internal sequencing.

## Per-repo items (16 candidates, by owning repo)

Layer 0 items live in Dhara. The Mahavishnu repo does not own any Layer 0 work; it consumes it.

### Layer 0 — Dhara (`D-WIRE`)

| ID | Item | Why this layer |
|---|---|---|
| D-LOCK | Substrate-backed LockStore | Replaces JSON file store. Every durable primitive below needs locks. |
| D-AUDIT | Durable AuditLog subscriber | One-line wiring; every durable write produces a structured audit record. |
| D-OBJ-SCHEMA | Typed object schemas for cross-system durable entities | Single source of truth for `workflow_outcome`, `approval_log`, `channel_session_state`, `webhook_ingress`, `audit_record`. |
| D-REPLAY-VEC | Vector clock / Lamport sequencing for durable objects | Required for X-REPLAY ordering invariants. |

### Layer 1 — Mahavishnu (`M-INFRA`)

| ID | Item | Notes |
|---|---|---|
| M-WEBHOOK-DURABLE | Durable webhook ingress via MemoryOutbox | Closes P0-3/P0-4/P0-5 in `docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md`. Depends on D-LOCK + D-AUDIT. |
| M-APPROVAL-LOG | Approval history persistence + read | Stop deleting on resolve; expose `list_approval_history(approval_id, since, status)`. Depends on D-OBJ-SCHEMA. |
| M-WORKER-LEASE | Lease + heartbeat for durable worker records | Add `lease_expires_at` and `last_heartbeat_at` to `DurableWorkerRecord`; `reap_zombies` task. Depends on D-LOCK. |
| M-WORKFLOW-OUTCOME | Structured `WorkflowOutcome` model + Dhara persistence | Persist to `workflow-results/{workflow_id}/`. Depends on D-OBJ-SCHEMA + D-AUDIT. |
| M-TOOL-AUDIT | Per-caller tool invocation log + profile overrides | Depends on D-AUDIT. |
| M-TRANSCRIPT-TAIL | `transcript_tail(workflow_id, since_offset)` MCP tool | Additive; capture primitive already exists. |

Deferred to a later spec: adaptive scheduling (A-RUBRIC) and provider routing (X-RUBRIC-FEEDBACK).

### Layer 1 — Session-Buddy (`S-MEM`)

| ID | Item | Notes |
|---|---|---|
| S-MEM-VERSIONS | `version`, `supersedes_id`, `parent_session_id`, `branch_reason` columns + `fork_session` MCP tool | Depends on D-OBJ-SCHEMA. |
| S-CHANNEL-DURABLE | Dhara-backed read/write for `_ChannelSessionStore` | Depends on D-LOCK + D-AUDIT. |
| S-SKILL-PROVENANCE | Surface `source_memory_ids` for distilled skills | Additive; no deps. |
| S-REPLAY | `memory/persistence.py` adapter + replay primitives | Depends on D-REPLAY-VEC. |

### Layer 1 — Akosha (`A-RUBRIC`)

| ID | Item | Notes |
|---|---|---|
| A-EVENT-LOG | Durable event log for `pattern_detected` / `anomaly_detected` / etc. | Depends on D-OBJ-SCHEMA + D-AUDIT. |
| A-RUBRIC-TABLE | `rubrics` table keyed by `task_class` | New table. No deps. |
| A-RUBRIC-MCP | `score_rubric` MCP tool + Crackerjack evaluator adapter | Depends on A-RUBRIC-TABLE; pairs with X-RUBRIC-FEEDBACK. |

### Layer 1 — Crackerjack (`C-WIRE`, single combined spec)

Per user direction: one Crackerjack spec covering all six items below.

| ID | Item | Notes |
|---|---|---|
| C-SKILL-METRICS | Wire up `_update_success_rate` for failures/timeouts; fix `search_names` vs `search_tool_names` keyword mismatch in `mcp/tools/skill_tools.py:179-187` | Additive. |
| C-OUTCOME-CONTRACT | Complete `QualityGateReport.passed` + `blocking_failure` to consider optional/warning checks | Additive. |
| C-ASYNC-DURABILITY | Persist `AsyncTaskManager` jobs; add restart-safe result store | Depends on D-LOCK. |
| C-PLUGIN-TRUST | Fix `CustomHookPlugin` `assert` use; fix malformed `PluginMetadata.requires_python` `'>= 3.11'`; fix malformed `SessionBuddyMCPTracker` default URL; replace `_get_test_status` 100% placeholder | Quality fixes; ship together. |
| C-WEBSOCKET-AUTH | Fix WebSocket subscription auth normalize (`crackerjack: read` becoming `crackerjack:read` after space-to-colon) | Auth fix. |
| C-HOOKS-LIST | Refresh stale `CRITICAL_HOOKS` list in `SecurityAuditor` (add semgrep, betterleaks) | Quality fix. |

### Layer 2 — Cross-cutting

| ID | Item | Spans |
|---|---|---|
| X-REPLAY | End-to-end replay path: M-WORKFLOW-OUTCOME → S-REPLAY → D-REPLAY-VEC | M + S-B + D |
| X-RUBRIC-FEEDBACK | Crackerjack rubric evaluator writing back into Akosha `rubrics.score`; Mahavishnu uses this for adaptive scheduling | A + C + M |
| X-CHANNEL-DURABLE | Channel session durability: Slack/Signal/terminal events → S-CHANNEL-DURABLE → A-EVENT-LOG | S-B + D + A |

## Sequencing

The dependency graph dictates the order. Within a layer, items are sequenced by user value × feasibility.

### Phase 0 — Substrate (D-WIRE)

D-WIRE must ship before any Layer 1 work that depends on it. Internal order:

1. D-OBJ-SCHEMA first (defines the shapes every other durable primitive consumes).
1. D-LOCK second (locks depend on typed objects).
1. D-AUDIT third (audit subscriber consumes the same shapes).
1. D-REPLAY-VEC last (vector clocks only matter once replay is being built).

### Phase 1 — Per-repo specs in parallel

After D-WIRE lands, the four per-repo specs can run in parallel:

- **M-INFRA** picks up M-WEBHOOK-DURABLE, M-APPROVAL-LOG, M-WORKER-LEASE, M-WORKFLOW-OUTCOME, M-TOOL-AUDIT, M-TRANSCRIPT-TAIL.
- **S-MEM** picks up S-MEM-VERSIONS, S-CHANNEL-DURABLE, S-SKILL-PROVENANCE, S-REPLAY.
- **A-RUBRIC** picks up A-EVENT-LOG, A-RUBRIC-TABLE, A-RUBRIC-MCP.
- **C-WIRE** is split by dependency. The five D-LOCK-independent items (C-SKILL-METRICS, C-OUTCOME-CONTRACT, C-PLUGIN-TRUST, C-WEBSOCKET-AUTH, C-HOOKS-LIST) ship in Phase 1 alongside the others. C-ASYNC-DURABILITY moves to Phase 1.5 — it ships once D-LOCK lands.

Recommended order within Phase 1 (user value × risk):

1. The five D-LOCK-independent C-WIRE items first — purely additive fixes inside one repo, lowest coordination cost.
1. M-WEBHOOK-DURABLE next — closes a documented P0 risk and produces an immediately observable improvement.
1. S-MEM-VERSIONS next — unblocks S-REPLAY and X-REPLAY; user-visible immediately.
1. A-RUBRIC-TABLE next — establishes the shape M-INFRA and X-RUBRIC-FEEDBACK consume.
1. The rest in any order.
1. C-ASYNC-DURABILITY ships as soon as D-LOCK lands (Phase 1.5).

### Phase 2 — Cross-cutting specs

After Phase 1 lands:

1. **X-CHANNEL-DURABLE** — depends on S-CHANNEL-DURABLE + A-EVENT-LOG.
1. **X-RUBRIC-FEEDBACK** — depends on A-RUBRIC-TABLE + A-RUBRIC-MCP + C-OUTCOME-CONTRACT.
1. **X-REPLAY** — depends on S-REPLAY + M-WORKFLOW-OUTCOME + D-REPLAY-VEC.

Deferred: M-INFRA adaptive scheduling is gated on X-RUBRIC-FEEDBACK being adopted.

## Integration contract (template)

Every per-repo spec and every Layer 2 spec MUST declare the same five fields. The portfolio maintains a status table that includes the contract verbatim.

```markdown
## Integration Contract

**Triggered from:** (concrete callsite, e.g. "mcp__mahavishnu__pool_route_execute timeout window")
**Returns to / updates:** (concrete durable entity, e.g. "DurableWorkerRecord.lease_expires_at")
**Demonstrable by:** (concrete test or smoke command, e.g. "pytest tests/unit/test_worker_lease.py + curl /metrics | grep lease_reap")
**Rollback signal:** (concrete signal, e.g. "metric:lease_reap_invocations=0 AND lease_expired_count climbs; revert per-component commit")
**Observability added:** (concrete metric, log line, or audit event, e.g. "audit:worker.lease.expired with worker_id + lease_age_s")
```

Specs missing any of the five fields are not adopted.

## Status table

State per item. Updated at each layer gate.

| ID | Repo | State | Plan link | Spec link |
|---|---|---|---|---|
| D-LOCK | dhara | parked | — | — |
| D-AUDIT | dhara | adopted | [completion report](../../../dhara/docs/feature-tracking/2026-08-10-d-audit.md) | — |
| D-OBJ-SCHEMA | dhara | parked | — | — |
| D-REPLAY-VEC | dhara | parked | — | — |
| M-WEBHOOK-DURABLE | mahavishnu | building | [completion report](feature-tracking/2026-08-10-m-webhook-durable.md) | [spec](2026-08-10-m-webhook-durable-design.md) |
| M-WEBHOOK-DURABLE-WIRED | mahavishnu | parked | — | — | (mount receiver in production ingress — plan not yet authored)
| M-APPROVAL-LOG | mahavishnu | wired | [completion report](feature-tracking/2026-08-10-m-approval-log.md) | [spec](2026-08-10-m-approval-log-design.md) |
| M-WORKER-LEASE | mahavishnu | parked | — | — |
| M-WORKFLOW-OUTCOME | mahavishnu | wired | [completion report](feature-tracking/2026-08-10-m-workflow-outcome.md) | [spec](2026-08-10-m-workflow-outcome-design.md) |
| M-TOOL-AUDIT | mahavishnu | parked | — | — |
| M-TRANSCRIPT-TAIL | mahavishnu | parked | — | — |
| S-MEM-VERSIONS | session-buddy | parked | — | — |
| S-CHANNEL-DURABLE | session-buddy | parked | — | — |
| S-SKILL-PROVENANCE | session-buddy | parked | — | — |
| S-REPLAY | session-buddy | parked | — | — |
| A-EVENT-LOG | akosha | parked | — | — |
| A-RUBRIC-TABLE | akosha | parked | — | — |
| A-RUBRIC-MCP | akosha | parked | — | — |
| C-SKILL-METRICS | crackerjack | parked | — | — |
| C-OUTCOME-CONTRACT | crackerjack | parked | — | — |
| C-ASYNC-DURABILITY | crackerjack | parked | — | — |
| C-PLUGIN-TRUST | crackerjack | parked | — | — |
| C-WEBSOCKET-AUTH | crackerjack | parked | — | — |
| C-HOOKS-LIST | crackerjack | parked | — | — |
| X-REPLAY | portfolio | parked | — | — |
| X-RUBRIC-FEEDBACK | portfolio | parked | — | — |
| X-CHANNEL-DURABLE | portfolio | parked | — | — |

States: `parked` (queued in portfolio), `building` (per-repo spec exists, plan in progress), `wired` (merged, observability confirms trigger fires), `adopted` (at least one real workflow exercises the path).

## Open questions

1. **Dhara ownership of typed schemas** — should D-OBJ-SCHEMA live in Dhara or in a shared `bodai-contracts` package? Current portfolio assumes Dhara. Worth confirming with the Dhara maintainer before D-WIRE brainstorming starts.
1. **A-RUBRIC evaluator authority** — does the rubric evaluator run inside Crackerjack (C-OUTCOME-CONTRACT) and push to Akosha, or inside Akosha pulling from Crackerjack? The dependency graph allows either; the choice affects who owns the failure mode when the evaluator is down. To resolve in A-RUBRIC brainstorming.
1. **M-WORKER-LEASE backward compat** — adding `lease_expires_at` to existing `DurableWorkerRecord` rows is a migration. Decide between hard migration vs dual-read window before M-WORKER-LEASE spec.

## Appendix — research-only ideas (not in the 16, parked for later)

These came up in the brainstorming pass but are not committed to the portfolio:

- Per-call profile overrides (deferred to M-TOOL-AUDIT feedback).
- Fair queueing across pools (no concrete pain point yet; revisit if pool starvation emerges).
- Per-tenant circuit breakers (needs a tenant concept we don't yet have).
- Cross-system fitness signals (needs A-EVENT-LOG + X-RUBRIC-FEEDBACK first).
