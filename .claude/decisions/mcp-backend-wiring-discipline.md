---
status: active
role: canonical
date: 2026-09-05
last_reviewed: 2026-09-06
superseded_by: null
topic: mcp-backend-wiring-discipline
amended_by: "2026-09-06 — §7 Consumer-side aggregation added (trigger: ADR 0016 L1 BLOCKER B4 in docs/adr/0016-multi-agent-review.md)"
---

# MCP Backend Wiring Discipline

## Context

The 2026-09-05 Akosha audit revealed a process failure pattern: a Bodai MCP server can pass all tests, return 200 OK on `/health`, and register N tools, while being functionally empty (knowledge graph 0 entities, OTel 0 traces, system metrics 0 entries, code-pattern search 0 matches). Akosha had 30 registered tools, 2,020 passing tests, and `/health` returning 200 — and yet every "intelligence" query returned silence. This is wiring drift invisible to surface signals.

The failure mode is structural:

1. **Surface health check vs. functional health check** — `/health` returns 200 regardless of whether data feeds are producing. K8s liveness probes treat the server as healthy.
2. **Tests probe the tool surface, not the data surface** — a test calls `mcp__akosha__query_knowledge_graph(...)` and passes when it gets `{"neighbors": []}` back. The test never asks "should there be neighbors?"
3. **No end-to-end smoke test** — no CI job spins up the server, waits for warmup, and asserts non-empty results from each registered tool.
4. **No feed observability** — no metric like `akosha.kg.entities_indexed_total` that alerts when it stops incrementing.
5. **No proactive audit cadence** — the wiring-drift problem was only caught because someone explicitly asked for an audit.

This decision doc extends `wire-up-contract.md` from plan-time enforcement to runtime enforcement. The wire-up contract says "every deliverable must have an Integration Contract block at plan time." This doc says "every deliverable must have a working data feed at runtime."

## Decision rule

### 1. Health probes must check backend state, not just process liveness

Every Bodai MCP server's `/health` endpoint MUST:

- Aggregate the state of every data feed (`feed.state ∈ {healthy, degraded, dead}`)
- Return 200 + `{"status": "ok", "feeds": {...}}` only when all feeds are `healthy`
- Return 503 + `{"status": "degraded", "feeds": {...}}` when any feed is not `healthy`

A process being alive is not the same as a process being functional. The current `/health` returning `{"status": "ok"}` regardless of backend state is the root cause of "the system looks healthy but isn't producing."

Applies to: **akosha, mahavishnu, dhara, session-buddy, crackerjack, neo4j-mcp, and every other Bodai MCP server.**

### 2. End-to-end smoke tests in CI for every MCP server

Every Bodai MCP server MUST have a smoke test that:

- Spins up the server in a subprocess.
- Waits for a configurable warmup window (default 60 seconds).
- Calls each registered tool with a representative query.
- Asserts non-empty results for at least one query per tool category.

CI fails if the smoke test finds a registered tool returning empty results. Without this, "registered but disconnected" features stay registered-but-disconnected forever.

### 3. Per-feed observability metrics are mandatory

Every data feed MUST expose:

- `feed.entities_count` (gauge)
- `feed.last_updated_timestamp` (gauge, alert when older than 5× polling interval)
- `feed.errors_total` (counter)
- `feed.cycles_total` (counter, incremented each polling cycle)

The `last_updated_timestamp` rule is the single most important signal: a feed that's "alive but silent" looks identical to a feed that's "alive and producing" without this metric. Alerting fires when `last_updated_timestamp` is older than `5 × polling_interval`.

### 4. Wire-up contract enforced at CI time

For every MCP tool registration, a corresponding integration test at `tests/integration/test_<tool>_e2e.py` MUST exist and assert non-empty results within the smoke-test window.

CI fails if a tool is registered without an integration test. This is a wire-up lint rule — not a "make it nicer" guideline.

### 5. Recurring audit cadence

A monthly automated audit runs against every Bodai repo:

- Knowledge graph non-empty
- OTel traces ingesting within last 5 minutes
- Code patterns indexed for known files
- All registered MCP tools have non-empty responses for at least one query

Output: a single dashboard table; alert on any red row. Tracked under `bodai-radar` workflow.

### 6. Reframe the metric

Replace "registered tool count" with "working tool count" in dashboards, READMEs, and feature descriptions. A tool is *working* if it returned non-empty in the last 60 seconds. Counting registered tools is a vanity metric; counting working tools is a value metric.

### 7. Consumer-side aggregation (amended 2026-09-06)

**Trigger:** the 6-agent multi-agent review of ADR 0016 (`docs/adr/0016-multi-agent-review.md`) L1 BLOCKER B4 found that the policy as written scopes to "MCP servers" only (per §1: *"Applies to: akosha, mahavishnu, dhara, session-buddy, crackerjack, neo4j-mcp, and every other Bodai MCP server"*). The scapy-mcp enrichment integration in Flowscape v1 is **consumer-side** — Flowscape *calls* scapy-mcp, it does not expose scapy-mcp-shaped tools to other clients. The L1 reviewer's finding: this policy needs an explicit consumer-side coverage, not a bypass.

**Amendment:** every Bodai component that consumes an external MCP server as an enrichment provider, plugin, or external dependency (Flowscape calling scapy-mcp is the first case; unifi-mcp-in-v2 is the second planned) MUST:

- **7.1 — Register the dependency in `settings/ecosystem.yaml` with a `path` and `mcp:` field, just like the MCP servers themselves.** Consumer-side aggregations are first-class components, not "vendor libraries". The `mahavishnu list-repos` exit gate that applies to MCP servers (`docs/superpowers/plans/2026-09-06-registry-manifest-migration.md` Task 1) applies equally to consumer-side aggregations.
- **7.2 — Expose the same four feed observability signals** that §3 mandates for MCP servers: `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`. For Flowscape's enrichment surface, these are `flowscape.enrichment.{entities_count, last_updated_timestamp, errors_total, cycles_total}` (per ADR 0016 v2 §"Operational SLOs and Feed Observability"). The no-op default (when `enrichment.scapy_mcp_enabled = false`) emits `0`/`now()`/`0`/`0` so "registered but disabled" looks identical to "registered and producing" — *not* "absent" — per the wiring-discipline audit posture.
- **7.3 — `flowscape doctor --enrichment` (or equivalent per-component health check) surfaces the consumer-side feed state** with the same envelope as the MCP-server `/health` does. Exit codes: 0=healthy, 1=degraded, 2=dead, 3=not_registered. The doctor output schema is documented in ADR 0016 v2 §"`flowscape doctor --enrichment` output envelope".
- **7.4 — Consumer-side aggregation enters the same `/health` aggregator** when the consuming component ships server-mode. Until then, the doctor command is the visible surface.
- **7.5 — The consumer-side aggregation has the same end-to-end smoke test in CI as a server-side tool** (§2): spin up the consuming component AND the upstream MCP server in subprocesses; warmup window; call the consumer-side enrichment call; assert non-empty (when the provider is registered) or explicitly-empty-but-healthy (when the no-op default is in effect).

**Example:** Flowscape v1 with scapy-mcp enrichment implements §7.1–§7.5 as follows: scapy-mcp is registered in `mahavishnu/settings/ecosystem.yaml` (per Plan 0a Task 1 commit `4bae6c24`); `EnrichmentRegistry` emits the four signals per §7.2; `flowscape doctor --enrichment` is the doctor surface per §7.3; `/health` aggregation deferred to Phase 7b.2 when server-mode ships; the integration test in `tests/integration/test_enrichment.py` calls a FastMCP in-memory mock scapy-mcp and asserts non-empty enrichment values per §7.5.

**Why this amendment matters:** the original §1 was written assuming every Bodai MCP server is server-side. The scapy-mcp integration exposes a new topology (one Bodai component calling another as a dependency). Without §7, that topology would slip through the wiring-discipline audit silently — exactly the failure pattern §1 was written to prevent.

## Status

Active. Implementing in Akosha first (Wave 5 of `docs/superpowers/specs/2026-09-05-akosha-hardening-design.md`), then rolling out to the other Bodai MCP servers in subsequent hardening waves.

## Cross-references

- `wire-up-contract.md` — sibling decision at plan-time; this doc extends to runtime.
- `bodai-observability-pattern.md` — observability surface for cross-component monitoring.
- `docs/superpowers/specs/2026-09-05-akosha-hardening-design.md` — first implementation wave.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/mcp-surface-health-illusion.md` — the failure pattern that motivated this rule.

## Implementation checklist

When adding a new MCP tool to any Bodai component:

- [ ] Tool registration includes `tests/integration/test_<tool>_e2e.py` with non-empty-result assertion.
- [ ] Data feed behind the tool exposes `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`.
- [ ] `/health` aggregator includes this feed's state.
- [ ] CI smoke test (per §2) calls this tool and asserts non-empty response.
- [ ] No PR merges without all four boxes checked.

When adding a **consumer-side MCP aggregation** (per §7, amended 2026-09-06):

- [ ] The upstream MCP server is registered in `settings/ecosystem.yaml` with `path` and `mcp:` field (§7.1).
- [ ] The consumer surface emits the same four feed observability signals the server side would (§7.2).
- [ ] A `doctor --<surface>` command (or equivalent) surfaces the consumer-side feed state (§7.3).
- [ ] When the consuming component ships server-mode, the consumer-side feed enters `/health` aggregation (§7.4).
- [ ] Integration test (`tests/integration/test_<consumer>_e2e.py`) spins up both sides, calls the consumer-side hook, and asserts non-empty when the upstream is registered (§7.5).
