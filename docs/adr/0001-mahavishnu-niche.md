---
status: active
role: canonical
kind: decision
date: 2026-09-26
last_reviewed: 2026-09-26
superseded_by: null
blocks_on: []
decision_date: 2026-09-26
topic: mahavishnu-niche
---

# ADR 0001: Mahavishnu's Niche — LLM Control Plane + Repo Orchestrator

## Status

**Accepted** (2026-09-26)

## Context

Mahavishnu sits in an ecosystem of adjacent tools, each with its own niche:

| Adjacent tool | Niche | Where it overlaps Mahavishnu |
|---|---|---|
| **Conductor OSS** (Netflix-origin Java/Spring) | Workflow execution engine for microservices | Both orchestrate LLM/API/tool calls; both schedule tasks across workers |
| **Prefect** | General-purpose data workflow orchestration | Both run Python tasks; both have adapters and pools |
| **LangGraph / LlamaIndex / Agno** | LLM agent frameworks | Both invoke LLMs; both produce execution traces |
| **Akosha** | Cross-system intelligence + pattern detection | Consumes events Mahavishnu publishes; both observe |
| **Crackerjack** | Repo-level quality gates + linting | Both run on git repos; Crackerjack reviews PRs |
| **Session-Buddy** | Cross-session memory aggregation | Both store execution context; Session-Buddy is the memory layer |

Without an explicit niche statement, every borrowable feature from these tools becomes a candidate — and "borrow from them" can drift into "pivot toward theirs." Conductor OSS is the highest risk because its surface area (HMAC signing, nonce eviction, DLQ, rate limiting, webhooks, retry policies, multi-secret rotation) is vast and well-engineered.

## Decision

**Mahavishnu's clearest niche is the LLM control plane + repo orchestrator.** Borrowing from adjacent tools must mean *deepening* that niche, not *pivoting* toward theirs.

### What Mahavishnu IS

- **LLM control plane**: the central dispatcher for LLM-based work across Mahavishnu-managed repos. Routes prompts to pools of workers, retries on transient failures, dispatches via `pool_route_execute`.
- **Repo orchestrator**: executes work in isolated worktrees (`WorktreeInfo`, `worktree_manager`), coordinates multi-repo workflows, tracks per-repo state.
- **Bodai event-bus publisher**: publishes workflow lifecycle events to Akosha via `safe_publish(envelope)`. Other Bodai components (Crackerjack, Akosha, Session-Buddy) consume those events.
- **MCP-first**: 173 tools (146 decorated + 27 inline core) across 35 profile-gated groups. External clients interact via MCP, not CLI.

### What Mahavishnu IS NOT

- **Not a general-purpose end-user product.** No marketing site, no SaaS tier, no "Mahavishnu for Teams." Internal-first only.
- **Not a workflow execution engine for microservices.** Conductor OSS owns this niche. Borrowing its webhooks, DLQs, HMAC, nonce eviction, and multi-secret rotation competes with Conductor's niche.
- **Not a webhook intake daemon.** External systems (GitHub, Stripe, etc.) publish to Akosha directly via the standard Akosha publisher, not through Mahavishnu.
- **Not a generic markdown-board engine.** Only our own jot files (`.mahavishnu/board.md`) are in scope.
- **Not a cross-system authentication provider.** MultiAuthHandler exists but is Bodai-internal; not a competitor to Auth0/Okta.

## Deepening filter — three questions before adopting a feature

Before adopting any feature from an adjacent tool, answer all three:

1. **Does it deepen Mahavishnu's niche?** If the feature primarily serves a different niche (Conductor's microservices workflow, Auth0's auth provider, etc.), decline.
2. **Does it integrate cleanly with Bodai components?** If the feature requires Akosha + Crackerjack + Session-Buddy to work, it's probably Bodai-shaped (good); if it requires external SaaS, probably not.
3. **Does it NOT compete with the source tool?** If adopting the feature would make Mahavishnu a direct competitor to Conductor / Prefect / Auth0 for that feature's users, decline.

A feature passes only if all three answers are positive.

## Worked examples

### Example 1: C-7 webhook nonce eviction sweeper — DROPPED (2026-09-26)

Conductor's webhook→EventStore nonce eviction loop serves external webhook intake. Mahavishnu is an LLM control plane, not an event intake daemon. **Failed question 3** — competing with Conductor's niche for webhook consumers. **Dropped.**

### Example 2: C-10 ecosystem intake — SIMPLIFIED (2026-09-26)

Original C-10 (HMAC + nonce + DLQ + multi-secret rotation + register MCP tool) was Conductor-shape. Simplified to: one endpoint, allowlist, sanitize-only, no HMAC, no nonce, no DLQ, no registration tool. The 3 internal Bodai sources (`git-monitor`, `crontroller`, `ops-bridge`) publish via the allowlisted endpoint or directly to Akosha. External systems publish to Akosha directly — never through Mahavishnu.

### Example 3: C-6 idempotency on `pool_route_execute` — KEPT (2026-09-26)

Idempotency-key tracking is a common workflow-engine primitive. But C-6's version uses Oneiric `HashAction` to hash the dispatch fingerprint (not a raw `source:nonce` string), enforces uniqueness at the DB level (not via runtime DLQ), and fails-CLOSED on store unavailability. **All three questions pass:** it deepens the LLM-dispatch reliability niche, integrates with Akosha's event-bus pattern, and does not compete with Conductor because Mahavishnu's idempotency is tied to LLM dispatch semantics (prompt fingerprint) rather than HTTP webhook semantics.

## Consequences

### Positive

- Borrowing decisions are explicit. Future contributors know what to ask before adopting a feature ("does it pass the deepening filter?").
- The niche filter is a load-bearing constraint on the plan set: `docs/plans/2026-09-26-conductor-oss-borrowed-features.md` (parent spec) and its 11 implementation plans reference this ADR by name for every niche-driven decision (C-7 drop, C-10 simplification, C-11 scope, C-13 cross-repo split).
- The Bodai ecosystem stays coherent: Akosha is the event bus, Crackerjack is the quality gate, Session-Buddy is the memory layer, Mahavishnu is the control plane.

### Negative

- Mahavishnu cannot serve users who want a general-purpose webhook intake. Operators must use Akosha or another tool.
- Some Conductor features that would be useful in isolation (HMAC-signed webhook intake, multi-secret rotation) are not available. Operators who need those features must run Conductor alongside Mahavishnu.
- The deepening filter occasionally rejects features that "would be nice to have" but compete with the source tool's niche. This is acceptable per the no-backcompat policy.

## Related

- `docs/plans/2026-09-26-conductor-oss-borrowed-features.md` — parent spec for the 11 borrowed features; every niche-driven decision cites this ADR
- `docs/CLAUDE.md` (mahavishnu repo) — ecosystem context table
- `feedback-no-backwards-compat-pre-1.0` (CC memory) — pre-1.0 zero backcompat posture that aligns with this niche filter
- `bodai-pre-1.0-merge-policy` (CC memory) — direct-to-main merge policy for pre-1.0 work
