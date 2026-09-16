---
status: draft
role: canonical
kind: decision
date: 2026-09-16
last_reviewed: 2026-09-16
superseded_by: null
blocks_on:
  - "docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md"
  - "docs/adr/017-oneiric-shared-persistence-substrate.md"
related:
  - "docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md"
  - "docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md"
  - "docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md"
decision_date: null
topic: mcp-gateway-pattern
---

# ADR 018: MCP Gateway Pattern — Options A (status quo), B (full gateway), C (hybrid)

## Status

**Proposed** (2026-09-16) — pending review.

The Dhara MCP decomposition spec
(`docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md`)
introduced `mcp_common.tools.dispatch.register_local_namespace(component=..., tools=[...])`
(Phase 1.5) and its generalization
`mcp_common.tools.dispatch.register_remote_tools(server, namespace, tools=...)`
(Phase 11) without explicitly deciding whether Mahavishnu should *use*
these primitives to consolidate the running process count, or only
*expose* them for other consumers.

This ADR evaluates three options and recommends one, anchoring the
choice to the recently-completed Phase 10 (Postgres consolidation
hygiene) and Phase 12 (Hook Bus Coordination, Redis Streams
producer/consumer decoupling) work.

## Context

### Current operational shape (counted 2026-09-16)

Five Bodai MCP servers run as separate launchd-managed processes:

| Component | launchd Label | Port | /health endpoint | Auth env var (when enabled) |
|-----------|---------------|------|------------------|-----------------------------|
| Mahavishnu | `com.mcp.mahavishnu` | 8680 | `http://127.0.0.1:8680/health` | `MAHAVISHNU_AUTH_SECRET` |
| Akosha | `com.mcp.akosha` | 8682 | `http://127.0.0.1:8682/health` | `AKOSHA_AUTH_SECRET` |
| Dhara | `com.mcp.dhara` | 8683 | `http://127.0.0.1:8683/health` | `DHARA_AUTH_SECRET` |
| Session-Buddy | `com.mcp.session-buddy` | 8678 | `http://127.0.0.1:8678/health` | `SESSION_BUDDY_AUTH_SECRET` |
| Crackerjack | `com.mcp.crackerjack` | 8676 | `http://127.0.0.1:8676/health` | `CRACKERJACK_AUTH_SECRET` |

**Counts today:**

- **5 launchd plists** (`~/Library/LaunchAgents/com.mcp.{mahavishnu,akosha,dhara,session-buddy,crackerjack}.plist`).
- **5 /health endpoints** (one per process).
- **5 mcp-common instantiations** (one per process — each server imports
  `mcp_common.auth`, `mcp_common.config`, `mcp_common.tools.dispatch`,
  etc., at startup).
- **5 auth secret env vars** (one per process; per the
  `2026-04-27-bodai-auth-standardization-design.md` migration).
- **2 library dependencies duplicated**: `fastmcp`, `mcp-common`, plus
  per-component state libs (aiosqlite, zstandard, etc.).
- **5 startup scripts** (`launch_with_healthcheck.sh` wrapper + per-
  component `launch_mcp_with_secrets.py` / `python -m <pkg> mcp start`).
- **5 sets of resource limits** (Memory/NumberOfFiles per Hard/Soft
  ResourceLimits dict).
- **5 log paths** under `~/.local/state/mcp/logs/`.
- **1,570 LOC of mcp-common auth surface** (14 files) imported by all 5.

### Why the question is open now

Two recent decisions move the substrate toward gateway-readiness
without committing to it:

1. **ADR 017 (2026-09-14)** establishes **Oneiric as the single
   persistence substrate** for all Bodai components. Cross-component
   state reads (`mahavishnu → akosha → dhara`) flow through Oneiric
   adapters rather than direct Python imports. This decouples the
   *state* layer from the *process* layer; whether to also collapse
   the process layer is a separate decision.
2. **Phase 10 (Postgres consolidation hygiene)** retires pgvector
   duplicates, fixes Oneiric OTel default URLs, and removes
   sed-replicated schema files. Phase 10 closed 2026-09-15 and
   eliminated the last reason to keep `akosha` and `mahavishnu`
   running their own DuckDB/Postgres instances locally.
3. **Phase 12 (Hook Bus Coordination)** ships Redis Streams as the
   cross-component event bus via
   `oneiric.adapters.queue.redis_streams`. Producers (Claude hooks,
   jot drainers, audit loggers) and consumers (DHARA subscriber,
   Mahavishnu aggregator) are now decoupled at the *event* layer; the
   MCP process boundary is no longer load-bearing for hook
   propagation. Phase 12a hard-cutovered the JSON-file queue
   2026-09-15.

The question is no longer "do we have the substrate to consolidate?"
(the substrate exists), but "should we, and how aggressively?"

## Decision

**Recommend Option C (hybrid gateway): Mahavishnu gateways the
read-only / cross-cutting wrapper tools; each component retains its
own process for stateful, in-process domain tools.**

Rationale in §"Recommendation" below. The hybrid split:

- **Gateway surface (Mahavishnu + `mcp_common.tools.dispatch.register_remote_tools`)**:
  PyCharm wrappers (`pycharm_search_code_patterns`,
  `pycharm_find_usages`, etc. — Phase 1.5), `discover_tools`,
  `health`, trace catalog, and any tool whose implementation is
  itself an HTTP/MCP call to another component. These are the
  "consolidated wrapper" groups already scoped in the decomposition
  spec §5 Phase 1.5.
- **Direct surface (stateful domain tools in their own process)**:
  Akosha's `query_local_traces`, `search_all_systems`,
  `query_knowledge_graph` (state-bearing HotStore reads); Dhara's
  replacement tools after decomposition; Session-Buddy's
  `store_reflection`, `search_by_concept`; Crackerjack's
  `crackerjack_run_stage`, `search_code`, `search_semantic`. These
  hold an open connection / lock / in-memory index that does not
  survive a process restart, so the cost of proxying them through a
  gateway exceeds the benefit.

This is **Option C**, not Option B. The full gateway (Option B)
would require proxying stateful tools through an extra process hop,
paying 50-200ms per call for connection re-handling and turning
Mahavishnu into a single point of failure for every Bodai tool.

## Three options analyzed

### Option A — Status quo (five processes)

Keep the current shape: one launchd plist, one /health endpoint, one
auth secret, one mcp-common instantiation, one set of resource
limits per component.

**Pros:**

- **Independent release cadence.** Each Bodai component ships at
  its own pace (the pre-1.0 merge-to-main policy reinforces this).
  Phase 3 took 7 PRs across 7 repos with 2-week soaks; that would
  have been impossible in a monorepo gateway.
- **Per-component failure isolation.** Akosha can crash on a malformed
  trace ingest without taking Mahavishnu's worker pools offline.
  This is observed in practice (e.g. `akosha-list-skills-503` on
  2026-09-09 did not affect `pool_route_execute`).
- **Operator muscle memory is preserved.** Operators know
  `mahavishnu mcp status`, `akosha mcp status`, etc. as separate
  commands. Five HealthMonitor instances, five Grafana dashboard
  tabs, five Alertmanager rules — all working today.
- **Resource limits are per-component.** Mahavishnu's 1 GiB hard
  memory limit does not have to cover Akosha's vector-store
  working set. Today each component gets its own
  `HardResourceLimits.Memory = 1073741824`.
- **Component-specific tool profiles.** Dhara has
  `DHARA_TOOL_PROFILE=standard`; Mahavishnu has the default `full`.
  Profile isolation is implicit in process isolation.

**Cons:**

- **5 launchd plists to maintain.** Each `.bak.<timestamp>` file in
  `~/Library/LaunchAgents/` is a regression waiting to happen (see
  `2026-09-09-neo4j-grafana-stale-pid-port-drift.md` for a related
  operational class).
- **5 auth secret env vars to rotate.** mcp-common's auth surface
  has converged on a single `JWTManager`, but each component
  instantiates it with its own secret.
- **5 /health endpoints to monitor.** Alertmanager rules, Grafana
  blackbox exporters, on-call routing — all duplicated.
- **5 sets of mcp-common initialization cost** at startup.
- **Cross-component correlation requires extra plumbing.** Tool
  invocations that need to span components (e.g. Akosha traces +
  Dhara storage) currently rely on the bus (Phase 12) or direct MCP
  tool calls. The bus handles events; tool fan-out still pays the
  cost of 5 client connections.

### Option B — Full gateway (one process, four libraries)

Mahavishnu becomes the only MCP server process. Akosha, Crackerjack,
Oneiric expose their tools via
`mcp_common.tools.dispatch.register_remote_tools(server, namespace="akosha"|"crackerjack"|"oneiric", tools=[...])` — a
generalization of Phase 1.5's `register_local_namespace` primitive.

**Pros:**

- **Single auth surface.** One `MAHAVISHNU_AUTH_SECRET` (or one per-
  component-namespaced variant enforced by mcp-common).
- **Single /health endpoint.** `http://127.0.0.1:8680/health`
  aggregates per-component health via the `HealthMonitor` primitive
  that already exists in `mcp_common`.
- **Single launchd plist, single set of resource limits.**
- **Single mcp-common instantiation.** Startup cost paid once.
- **Coordinated release for cross-component API changes.** Phase 12
  bus work makes this safe: producers/consumers decouple at the
  event layer, so a coordinated gateway release does not force
  every consumer to upgrade in lockstep.
- **Tool names stable.** Agent prompts (`.claude/agents/akosha-
  specialist.md`, etc.) continue to work because tool names are
  namespaced (`mcp__mahavishnu__akosha_*`) but the prefix is
  implementation detail.

**Cons:**

- **Single point of failure.** A bug in Mahavishnu's lifespan, a
  deadlock in `HybridAdapterRegistry._metadata`, or a memory blow-up
  in one of the gatewayed libraries takes out *every* Bodai MCP
  tool. The wire-up discipline rule
  (`mcp-backend-wiring-discipline.md`) explicitly forbids pools with
  registered tools but no active workers from returning `ok` —
  Option B concentrates the same risk surface in one process.
- **50-200ms latency tax per stateful tool.** Each
  Akosha/Crackerjack/Session-Buddy tool call goes through an extra
  MCP-client-to-MCP-server hop inside one process. Connection
  reuse helps but does not eliminate the cost. Today's
  `query_local_traces` ~30ms tool call becomes ~80-130ms.
- **Coordinated release is a regression risk for the "independent
  release cadence" benefit of Option A.** Phase 3 took 7 PRs across
  7 repos. Phase 10 took 6 tasks across 5 repos. A monorepo gateway
  would force these to merge as one big-bang PR.
- **Larger Mahavishnu binary.** Akosha's HotStore client (~2,400
  LOC) + Crackerjack's quality engine + Oneiric's adapter
  registry all loaded into one Python process. Memory ceiling
  doubles (from 5 × 1 GiB = 5 GiB to ~2-3 GiB for the gateway,
  since not all libraries are warm at once, but with no isolation).
- **Cross-component imports re-appear.** Phase 5 of the serverless
  plan eliminated 8 direct Dhara imports + 1 direct Akosha import
  from Mahavishnu. Option B reverses this for the gatewayed tools
  (Mahavishnu imports Akosha's tool implementations).
- **Operator muscle memory is broken.** `akosha mcp status` becomes
  `mahavishnu mcp status --component akosha`. Operator dashboards
  that scrape 5 /health endpoints now scrape 1.

### Option C — Hybrid (gateway for read-only wrappers, direct for stateful tools)

Mahavishnu gateways the **read-only, cross-cutting, in-process-
stateless wrappers** via `register_remote_tools`. Akosha,
Session-Buddy, Crackerjack, Oneiric retain their own processes for
stateful domain tools (HotStore reads, vector searches, persistent
KV, semantic indices).

**Wrapper groups already scoped for Phase 1.5
(decomposition spec §5 Phase 1.5):**

- PyCharm wrappers (`pycharm_search_code_patterns`,
  `pycharm_find_usages`, `pycharm_get_ide_diagnostics`,
  `pycharm_get_symbol_info`, `pycharm_health`) — already stateless
  in mcp-common's `mcp_common.ide.pycharm_tools` module.
- `discover_tools` (meta-tool; already common across all 5).
- `health` (aggregator pattern; mcp-common already supports it).
- Trace catalog (read-only; cache can be invalidated per call).
- Catalog / agent / skill registries (read-only; published via
  bus from Crackerjack after Phase 1.5).

**Stateful groups staying in their own process:**

- Akosha: `query_local_traces`, `search_all_systems`,
  `query_knowledge_graph`, `cross_repo_capability_search`,
  `find_function_usage`, `search_code_patterns` — all read from
  HotStore with open DuckDB / pgvector connections.
- Dhara (post-decomposition): durable object store, time-series
  writes — operationally distinct from read-only catalog.
- Session-Buddy: `store_reflection`, `search_by_concept`,
  `fingerprint_search`, `apply_pattern`, `trigger_learning` — open
  SQLite connections + per-session state.
- Crackerjack: `crackerjack_run_stage`, `search_code`,
  `search_semantic`, `crackerjack_list_agents`,
  `crackerjack_list_skills` — open DuckDB indexes, subprocess
  quality gates.
- Mahavishnu own stateful tools: `pool_route_execute`,
  `launch_worker`, `workflow_get_outcome_tool`,
  `webhook_replay_tool` — open WebSocket connections, durable
  worker records, pool state.

**Pros:**

- **Captures Option B's benefits for the wrapper groups.** One
  source of truth for the read-only / consolidated surface; one
  set of tests for the wrappers; one place to bump versions.
- **Avoids Option B's failure-mode concentration.** Akosha's vector
  store crash does not take out Session-Buddy's memory writes.
- **Avoids Option B's coordinated-release risk.** Phase 3 / Phase
  10 / Phase 12 timelines remain valid; the wrapper consolidation
  is a separate, smaller milestone.
- **Phases incrementally.** Start with PyCharm wrappers
  (Phase 1.5 already designed for this). Add `discover_tools` and
  `health` next. Defer trace catalog and registry wrappers.
- **Operator muscle memory preserved.** Stateful commands unchanged
  (`akosha mcp status` still works for the stateful subset). Only
  the wrapper subset moves.

**Cons:**

- **Two patterns to maintain.** Operators and contributors must
  understand which tools are gatewayed and which are not. The
  `tool_versions.py` registry and `mcp_common.tools.dispatch` API
  help, but the distinction is real.
- **Some wrapper-to-stateful handoffs cross the process boundary.**
  `mcp__akosha__query_local_traces` (stateful, in Akosha) followed
  by `mcp__mahavishnu__discover_tools` (gatewayed) crosses two
  processes, which is the same cost as today. Net latency change:
  zero for cross-tool calls, marginal improvement for wrapper-only
  flows.
- **Migration is an opt-in exercise per component.** Each component
  decides which wrapper groups to register via
  `register_remote_tools`. Without coordination, the gateway
  surface becomes inconsistent (some wrappers in Akosha, some in
  Mahavishnu).
- **Phase 12 bus does not eliminate cross-process call cost.**
  The bus decouples event producers/consumers, not tool fan-out.
  Option C does not change the MCP-client-to-MCP-server hop for
  stateful tools.

## Metrics (counted 2026-09-16)

The same shape exists in `~/Library/LaunchAgents/` and
`/Users/les/Projects/<component>/settings/`. All counts are
operational (not code lines).

### Today (Option A status quo)

| Metric | Count | Source |
|--------|-------|--------|
| launchd plists | 5 | `com.mcp.{mahavishnu,akosha,dhara,session-buddy,crackerjack}.plist` |
| /health endpoints | 5 | ports 8680 / 8682 / 8683 / 8678 / 8676 |
| mcp-common instantiations | 5 | one per process at startup |
| Auth secret env vars | 5 | `MAHAVISHNU_AUTH_SECRET` + 4 sibling names per `2026-04-27-bodai-auth-standardization-design.md` |
| Start scripts (launch wrappers) | 5 | `launch_with_healthcheck.sh` + 5 per-component scripts |
| Hard memory limits | 5 × 1 GiB = 5 GiB ceiling | per-plist `HardResourceLimits.Memory` |
| Log files | 5 | `~/.local/state/mcp/logs/{component}.log` + `.err` |
| HealthMonitor feeds | 5 | one per process via `mcp_common.health.ComponentHealth` |
| Grafana /health dashboard tabs | 5 | one blackbox-exporter probe per port |
| Alertmanager /health alert rules | 5 | one per component |

### Option B (full gateway)

| Metric | Count | Change |
|--------|-------|--------|
| launchd plists | 1 | -4 |
| /health endpoints | 1 | -4 (aggregated via `HealthMonitor`) |
| mcp-common instantiations | 1 | -4 |
| Auth secret env vars | 1 | -4 |
| Start scripts | 1 | -4 |
| Hard memory limits | 1 × 2-3 GiB | ceiling approximately halved by sharing, but no isolation |
| Log files | 1 | -4 |
| HealthMonitor feeds | 1 (aggregator) | -4 |
| Grafana tabs | 1 | -4 |
| Alertmanager rules | 1 (aggregator with per-feed sub-rules) | -4 base, +4 sub-rules = 0 net change |
| **Latency tax on stateful tools** | **+50-200ms per call** | **regression** |
| **Single point of failure** | **1 process** | **regression** |

### Option C (hybrid — recommended)

| Metric | Count | Change vs A |
|--------|-------|-----------|
| launchd plists | 5 (unchanged for stateful components) | 0 |
| /health endpoints | 5 (unchanged) | 0 |
| mcp-common instantiations | 5 (unchanged) | 0 |
| Auth secret env vars | 5 (unchanged) | 0 |
| Start scripts | 5 (unchanged) | 0 |
| Wrapper tool groups gatewayed | ~5 (PyCharm, discover_tools, health, trace catalog, registry) | new |
| Stateful tool groups direct | ~25-30 (Akosha, Dhara, Session-Buddy, Crackerjack, Mahavishnu own stateful) | 0 |
| Latency tax on stateful tools | 0 (unchanged) | 0 |
| Single point of failure | none new | 0 |
| Coordinated release overhead | 1 small milestone (the wrappers), not 7 big-bang | improved |
| **Wrapper consolidation wins** | same as Option B for the wrapper subset | improved |

The Option C numbers are the *delta* — the wrappers gain Option B's
benefits; the stateful surface retains Option A's isolation and zero-
added-latency.

## Recommendation

**Adopt Option C: gateway for read-only wrappers, direct for
stateful tools.**

### Rationale

1. **Phase 10 closed the substrate case for consolidation, but did
   not force a process collapse.** Postgres consolidation hygiene
   was about *which Postgres instance* runs the vector store, not
   *how many Python processes* host the MCP surface. Process count
   is a separate axis.
2. **Phase 12 decoupled event producers from consumers via the
   Redis Streams bus.** Tool fan-out still crosses processes, but
   the bus already absorbs the cross-component correlation load.
   Option B's "single process for everything" benefit is therefore
   smaller post-Phase 12 than pre-Phase 12.
3. **The decomposition spec already designed Option C's surface.**
   Phase 1.5 (`register_local_namespace`) + Phase 11
   (`register_remote_tools`) of the Dhara MCP decomposition spec
   is the *exact* primitive Option C needs. We do not have to
   invent a new mechanism; we have to choose to use it.
4. **Single point of failure risk is asymmetric.** Akosha's vector
   store, Session-Buddy's per-session SQLite, Crackerjack's quality
   engine subprocess, and Mahavishnu's WebSocket fan-out each have
   different failure modes. Collapsing them into one process loses
   the isolation that has historically kept Bodai tools available
   during partial outages. The decomposition spec's own
   `wire-up-contract.md` (`mcp-backend-wiring-discipline.md`)
   treats isolated failure as load-bearing.
5. **Operator muscle memory.** Five `/health` endpoints and five
   `mcp status` commands are operational anchors. Consolidating them
   is a one-time savings; breaking them costs every operator and
   every runbook.
6. **Pre-1.0 merge policy rewards independent releases.** The 7-PR
   Phase 3 sequence (with 2-week soaks) and the 5-component Phase
   10 sequence both demonstrate that independent releases are how
   Bodai ships. Option B reverses that for tooling.
7. **Latency tax on stateful tools.** Akosha's
   `query_local_traces` (~30ms) goes to ~80-130ms through a
   gateway proxy. For a tool that is invoked dozens of times per
   agent turn, that 50-100ms per call is visible. Phase 9's
   `ecosystem_pulse` skill already runs multi-call traces; adding
   50-100ms × N calls erodes the user-facing latency budget.

### What "Option C" looks like in practice

**Mahavishnu (gateway for the wrapper subset):**

```python
# mahavishnu/mcp/server_core.py — Phase 1.5 wiring
from mcp_common.tools.dispatch import register_remote_tools
from mcp_common.ide.pycharm_tools import (
    pycharm_search_code_patterns, pycharm_find_usages,
    pycharm_get_ide_diagnostics, pycharm_get_symbol_info,
    pycharm_health,
)

# PyCharm wrappers: already stateless in mcp-common
register_remote_tools(
    server=mcp,
    namespace="akosha",
    tools=[pycharm_search_code_patterns, pycharm_find_usages, ...],
)
# Same for "crackerjack", "session_buddy" namespaces
```

**Akosha / Crackerjack / Session-Buddy / Dhara (stateful subset):**
unchanged. Each keeps its own process, its own port, its own
`mcp status` command.

**Tool name stability:** agents continue to call
`mcp__akosha__pycharm_search_code_patterns` — the namespace is
preserved, the underlying implementation may route through Mahavishnu
after Phase 1.5 lands.

### Sequencing

Phase 1.5 of the decomposition spec already plans the wrapper
consolidation. Option C is Option 1.5 + "stop there." Specifically:

1. **Phase 1.5 (5 wrapper-category commits)** — land as planned in the
   decomposition spec §5 Phase 1.5.
2. **Phase 1.5.1 (new, post-Phase-1.5)** — audit call sites; confirm
   no agent prompt broke.
3. **Phase 1.6 (new)** — add `discover_tools` and `health`
   aggregator to the gateway if not already in Phase 1.5.
4. **No Phase 2.X consolidation.** Stop after the wrapper groups.
   Stateful tools stay in their own processes.
5. **Re-evaluate after Phase 13 / serverless-readiness Phase 8**
   (EventBridge WAL). If the bus further reduces cross-component
   fan-out, Option B may become more attractive. Re-open this ADR
   in Q1-2027 with new telemetry.

### Phase 12 / Phase 10 alignment

- **Phase 10** did the substrate work that *enables* Option C
  without forcing it. Option C explicitly preserves the
  independent-release cadence that Phase 10 was designed around.
- **Phase 12**'s Redis Streams bus means producers (hooks,
  drainers, audit loggers) and consumers (DHARA, Mahavishnu
  aggregator) decouple at the event layer. Option C's gateway does
  not have to host producer/consumer logic — that lives in the bus
  consumer pattern, not in the MCP surface.

## Rollback plan

If Option C's wrapper consolidation introduces regressions:

1. **Per-wrapper-group rollback.** Each wrapper group (PyCharm,
   discover_tools, health, trace catalog, registry) is a separate
   `register_remote_tools` call. Disable one group at a time by
   reverting its commit; the other groups continue to work.
2. **Phase 1.5 commit-by-commit rollback.** The decomposition spec
   already plans Phase 1.5 as 5 separate commits. Roll back to any
   of the first 4 commits and Phase 1.5 partial state is
   recoverable.
3. **Full revert.** `git revert` the Phase 1.5 merge commit per
   repo. Restart the five launchd plists. Stateful surface returns
   to Option A in <2 minutes.
4. **No data migration.** Phase 1.5 changes tool *registration*, not
   tool *data*. HotStore, Dhara, Session-Buddy stores, Crackerjack
   indexes — none are touched. Rollback is configuration-only.

**Signals to roll back:**

- Any wrapper tool returns 5xx more than 1% of invocations over a
  7-day window.
- Latency p99 on a wrapper tool exceeds 500ms (Option B's per-tool
  ceiling we are choosing to avoid).
- An agent prompt that previously worked starts returning "tool not
  found" — indicates namespace mismatch in the registration.

## Status

- **2026-09-16**: This ADR drafted. Phase 10 closed 2026-09-15;
  Phase 12a hard-cutover landed 2026-09-15. Both Phase 10 and
  Phase 12 results referenced.
- **Pending**: review against the decomposition spec §5 Phase 1.5
  plan, multi-agent review, and user ratification.

## References

- `docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md`
  §5 Phase 1.5 (wrapper consolidation) + §4.6 (Phase 11
  `register_remote_tools` rename).
- `docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md`
  — Phase 1.5 sequencing.
- `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`
  — Phase 8 (EventBridge WAL) and Phase 10 (Postgres consolidation
  hygiene).
- `docs/adr/017-oneiric-shared-persistence-substrate.md` —
  persistence substrate (read *with* this ADR; together they cover
  state and process layers).
- `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` —
  adapter catalog boundary; Option C respects the same surface.
- `docs/superpowers/specs/2026-04-27-bodai-auth-standardization-design.md`
  — auth consolidation that gives Option B its "single auth surface"
  benefit (Option C retains per-component auth secrets).
- `.claude/decisions/wire-up-contract.md` and
  `.claude/decisions/mcp-backend-wiring-discipline.md` —
  integration / failure-isolation rules that motivate Option C's
  preservation of independent processes.
- `mcp_common.tools.dispatch.register_local_namespace` and
  `register_remote_tools` — the primitives Option C uses.
