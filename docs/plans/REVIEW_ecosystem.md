---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Ecosystem Review: Bodai Routing Feedback Loop Plan

## **Reviewer**: ecosystem-review (general agent) **Date**: 2026-05-23 **Plan**: `docs/plans/2026-05-23-bodai-routing-feedback-loop.md` **Verdict**: **REVISIONS NEEDED** — 5 issues found (1 critical, 2 moderate, 2 informational)

## 1. Standalone Constraint Validation

### 1.1 Per-Component Analysis

| Component | Runs standalone? | Evidence |
|---|---|---|
| **Mahavishnu** | ✅ Yes | `DharaStateBackend` in `mahavishnu/core/state_backends/dhara.py:110` — `put()` is a no-op when circuit is open. Pool manager falls back to `least_loaded` when no signals. |
| **Akosha** | ⚠️ Conditional | Fitness analyzer uses in-memory buffer when Dhara is down (plan line 148). However: if Mahavishnu is down, Akosha **logs warning and skips** (plan line 146) — this means Akosha's feedback loop stalls but the component itself continues. Acceptable. |
| **Dhara** | ✅ Yes | Pure KV store. No active role in the feedback loop — only stores signals written to it. |
| **Session-Buddy** | ✅ Yes | Emits OTel locally via `OTelStorageAdapter`. No routing decisions. OTel → local pgvector → optional push to Mahavishnu. |
| **Crackerjack** | ✅ Yes | Emits OTel locally. No routing decisions. Same as Session-Buddy. |
| **Oneiric** | ✅ Yes | Shared foundation. `OTelStorageAdapter` runs in-process with local pgvector — no external dependencies. |

**Constraint verdict**: Standalone constraint is satisfied structurally. Each component continues operating when others are down.

______________________________________________________________________

## 2. Standalone Operation Matrix Review

### 2.1 Completeness Check

| Entry | Accurate? | Issue |
|---|---|---|
| Mahavishnu only | ✅ | Routes with `least_loaded`. OTel ingester stores traces locally. |
| Akosha only | ✅ | Fitness job runs, finds no traces, logs warning, idles. Correct. |
| Dhara only | ⚠️ | "Stores whatever is written to it" — correct but incomplete. Dhara has no active background processes, so it just sits idle. This is fine but the description understates that Dhara is **passive** — it doesn't initiate anything. |
| Session-Buddy only | ✅ | Emits OTel locally. Correct. |
| Crackerjack only | ✅ | Emits OTel locally. Correct. |
| Full chain up | ✅ | Complete feedback loop. Correct. |

### 2.2 Missing Entries

The matrix is missing entries for **partial chain scenarios** — cases where some (not all) components are running. These are more realistic failure modes than "only X running":

| Partial chain | Behavior | Status |
|---|---|---|
| Mahavishnu + Akosha (no Dhara) | Akosha buffers signals in-memory. Mahavishnu has no signals → falls back to `least_loaded`. Routing works but not optimized. | ⚠️ **Not documented** — potential silent degradation |
| Mahavishnu + Dhara (no Akosha) | No fitness signals written. Mahavishnu falls back to `least_loaded`. Routing works with default strategy. | ⚠️ **Not documented** — this is actually the most likely production state |
| Akosha + Dhara (no Mahavishnu) | Akosha can't query traces → logs warning, idles. No signals written. Dhara sits idle. | ✅ Implicitly covered by "Akosha only" row |
| Mahavishnu only, Dhara up | Mahavishnu writes pool/routing state to Dhara but reads no fitness signals → `least_loaded` fallback. Normal operation. | ❌ **Not in matrix** — should be added |

**Matrix verdict**: Basic cases are correct. Partial-chain scenarios are not covered — these are the realistic deployment states and operators need to know what to expect.

______________________________________________________________________

## 3. Circuit Breaker and Fallback Pattern Analysis

### 3.1 Dhara Circuit Breaker (Mahavishnu side)

**Location**: `mahavishnu/core/state_backends/dhara.py:24-25, 81-106`

The circuit breaker is **write-side only**:

- `put()` (line 108) — circuit breaker respected ✅
- `get()` (line 176) — circuit breaker respected ✅
- `list_prefix()` (line 202) — circuit breaker respected ✅

**Behavior when circuit open**: All reads and writes become no-ops. `RoutingFitnessReader` calling `get()` on a circuit-open Dhara gets `None` → falls back to `least_loaded` ✅. This is correct.

**Recovery**: Circuit half-opens after 30s (line 88) and allows one probe. If that probe succeeds, circuit closes. If it fails, circuit stays open for another 30s.

**Gap**: The circuit breaker does NOT have a **success threshold** — one successful call after a failure closes the circuit. In a flaky Dhara scenario, this could cause rapid open/close cycling. Not critical for this plan but worth noting.

### 3.2 Akosha In-Memory Buffer (Dhara down scenario)

**Plan reference**: Line 147-148

> "If Dhara is down, buffer signals in-memory (dict with TTL) and retry on next cycle."

**Problem**: The plan does NOT specify:

1. **Maximum buffer size** — if Dhara is down for hours, unbounded in-memory dict could cause OOM
1. **TTL for buffered signals** — signals have a 2× window expiry (plan line 67), but buffered signals may exceed this if Dhara is down for extended periods
1. **What "retry on next cycle" means** — does Akosha have a background thread that periodically tries to flush the buffer? Is there a maximum retry interval?

**The buffer is essentially a write-through cache that persists nothing when Dhara is unavailable.** Any crash of Akosha during Dhara outage loses all buffered signals.

**Risk level**: Moderate. Acceptable for initial implementation but needs a defined maximum buffer size and TTL.

### 3.3 Mahavishnu OTel Fallback

**Plan reference**: Line 86-88

> "When Mahavishnu is reachable: Each component optionally also pushes to Mahavishnu's OTel ingestion endpoint."

**Gap**: The plan says "optional" and "off by default." But it doesn't specify **what Akosha does when Mahavishnu is unreachable for trace querying**.

Plan line 146 says Akosha "logs a warning and skips." This means:

- During Mahavishnu outage, Akosha's fitness analyzer produces **no signals**
- Mahavishnu continues routing with `least_loaded`
- When Mahavishnu recovers, Akosha resumes querying

**This is acceptable** — the feedback loop gracefully degrades. But the plan doesn't address **backfill**: does Akosha re-query the window that was missed during outage? If Mahavishnu stores traces locally and they're queryable after recovery, Akosha should ideally backfill. This is not mentioned.

**Risk level**: Moderate (informational). Backfill would improve the loop but is not required for initial implementation.

______________________________________________________________________

## 4. Dependency Chain and Crash Scenario Analysis

### 4.1 Akosha crashes mid-analysis

**Scenario**: Akosha's `fitness_analyzer.py` is computing signals and writing to Dhara. Akosha crashes after writing some signals but before completing all task classes.

**Outcome**:

- Partial signals in Dhara for this cycle
- Next cycle (60s later) re-computes from scratch — partial signals from previous cycle may be stale but will be overwritten with fresh computation
- **No orphaned signals** — signals are self-expiring (TTL = 2× window)
- Mahavishnu reads whatever signals exist; if a task_class has no fresh signal, falls back to `least_loaded`

**Risk**: Low. The rolling window + TTL design means partial writes don't corrupt state.

### 4.2 Dhara crashes mid-write from Akosha

**Scenario**: Akosha writes `routing_fitness/CODE_REVIEW/least_loaded` = `{"score": 0.95, ...}` to Dhara. Dhara crashes before commit.

**Outcome**:

- Signal not persisted
- Next cycle: Akosha re-computes from traces and writes again
- Mahavishnu sees no signal → `least_loaded` fallback

**Akosha's in-memory buffer** would also lose this signal if Akosha crashes before buffer flush.

**Risk**: Low. The loop is eventually consistent — missed signals just mean one cycle uses fallback. The TTL ensures stale signals expire.

### 4.3 Mahavishnu crashes mid-routing decision

**Scenario**: Mahavishnu's `RoutingFitnessReader` reads a signal from Dhara, then Mahavishnu crashes before the routing decision is used.

**Outcome**:

- Signal was already read — not mutated
- Mahavishnu restarts, pool manager continues with `least_loaded` (or reads signal again)
- No stale state

**Risk**: Low. `RoutingFitnessReader` only reads; no mutations to Dhara in this path.

### 4.4 Dhara has stale selectors

**Scenario**: A selector was good 2 hours ago but is now degraded (e.g., a specific pool is failing). Akosha's last computation was 30 minutes ago.

**Plan says**: Signals expire after 2× window (line 67). With 1-hour window, signals expire after 2 hours if not refreshed.

**What happens**:

- If Akosha is running: signals refreshed every 60s → stale signals are overwritten ✅
- If Akosha is down: signals expire after 2 hours → Mahavishnu falls back to `least_loaded` ✅

**Edge case**: Akosha is running but Mahavishnu's OTel store has a gap (traces not pushed during network issue). Akosha computes based on incomplete data → may write a signal based on partial window. This could mislead Mahavishnu into choosing a suboptimal selector.

**Risk**: Moderate. The partial-trace scenario is not addressed. Recommend logging when trace count is suspiciously low for a given window.

______________________________________________________________________

## 5. Hidden Coupling Risks

### 5.1 CRITICAL: Akosha's MCP client dependency on Mahavishnu

**Plan reference**: Line 216-217

> "Akosha has an MCP client module (`akosha/mcp/client.py`) that can call Mahavishnu's MCP tools."

**Finding**: `akosha/mcp/client.py` does not exist in the Akosha codebase (verified by searching `/Users/les/Projects/akosha`). The plan assumes this module exists and can be used to call `query_component_traces`.

**Implication**: Either:

1. This is a planned new file (not in scope)
1. An existing module is intended (but which one?)
1. The plan needs to specify how Akosha calls Mahavishnu's MCP tools

**The plan says "Start with"**, implying this is a known gap. But the dependency is tight: Akosha cannot compute fitness without Mahavishnu's trace store. If the client module is non-trivial to build, this could delay implementation.

**Recommendation**: Define the MCP client interface explicitly in the plan. Confirm which existing Akosha module handles outbound MCP calls, or add `akosha/mcp/client.py` to the Key Files table.

### 5.2 MODERATE: OTelStorageAdapter requires pgvector extension

**Plan reference**: Line 23-24

> "Oneiric OTelStorageAdapter → local pgvector or DuckDB"

**Finding**: From `oneiric/oneiric/adapters/observability/otel.py:56-67`, the adapter checks for the `vector` extension at startup and raises a clear error if missing:

```python
result = await session.execute(
    text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
)
if not result.fetchone():
    raise RuntimeError("Pgvector extension not installed.")
```

**Implication**: Every Bodai component (including Session-Buddy, Crackerjack, etc.) must have **pgvector installed and the extension created** for `OTelStorageAdapter` to function. This is an infrastructure dependency not mentioned in the plan.

**DuckDB path**: The plan mentions DuckDB as an alternative backend. However, the `OTelStorageAdapter` in Oneiric uses asyncpg for PostgreSQL. DuckDB support would need to be added or the plan must specify which components use pgvector vs. DuckDB.

**Risk**: Moderate. Operators may not realize pgvector is required for every component. Should be documented as a prerequisite.

### 5.3 MODERATE: Trace schema coupling via span attributes

**Plan reference**: Line 90-97

Span attributes (`.set_attribute("bodai.task_class", ...)`) are the integration point. All Bodai components must emit the same four attributes: `task_class`, `selector`, `outcome`, `pool_id`, `duration_ms`.

**Finding**: The plan assumes these attributes are set by each component. But:

- If any component uses a different attribute name or format (e.g., `taskType` vs `task_class`), Akosha's group-by will silently miss those traces
- If a component emits `outcome = "failure"` instead of `"error"`, the failure rate calculation will be wrong

**No validation mechanism** is specified — Akosha just groups by whatever it receives. A schema validation step when traces are ingested into Mahavishnu's store (or when Akosha queries) would catch mismatches.

**Risk**: Moderate. Silent data quality issues. Recommend adding schema validation in `query_component_traces` to reject traces missing required attributes.

### 5.4 INFORMATIONAL: Dhara key naming convention conflict

**Plan reference**: Line 53-64 (Fitness Signal Schema)

The plan defines fitness signal keys as:

```
routing_fitness/{task_class}/{selector}
```

**Finding**: `DharaStateBackend` in Mahavishnu (`mahavishnu/core/state_backends/dhara.py:66-70`) uses a different key format for routing decisions:

```
routing/v1/{task_class}/{timestamp_ms}
```

These are **different key namespaces** (note: `routing_fitness/` vs `routing/v1/`), so there is no actual conflict. However:

- The plan does NOT specify that the fitness signal namespace is separate from the existing routing decision namespace
- If someone later wants to query "what did Mahavishnu route to" vs "what is the fitness score", they need to know two different key patterns
- `MahavishnuPoolManager` persists routing decisions under `routing/v1/` (line 143 in `manager.py`), not under `routing_fitness/`

**Risk**: Informational. The separate namespaces are fine but the plan should explicitly note this to avoid future confusion.

### 5.5 INFORMATIONAL: Fitness signal read is not protected by circuit breaker on the read path

**Plan reference**: Line 117

> "Circuit breaker: uses Oneiric's `CircuitBreaker` to handle Dhara unavailability"

**Finding**: The plan says `RoutingFitnessReader` uses a circuit breaker. Looking at `DharaStateBackend`, the circuit breaker is embedded in that class — reads via `get()` and `list_prefix()` are both circuit-protected. However:

- `RoutingFitnessReader` is described as a **new class** that reads from Dhara
- It is not clear whether `RoutingFitnessReader` uses `DharaStateBackend.get()` directly (which would inherit circuit breaker protection) or implements its own DharaClient calls (which would NOT have circuit breaker protection)

If `RoutingFitnessReader` calls `DharaClient` directly (via `mahavishnu/core/dhara_adapter.py`), it would bypass the circuit breaker in `DharaStateBackend`.

**Risk**: Informational. The plan should specify that `RoutingFitnessReader` must use `DharaStateBackend` (which has circuit breaker) rather than `DharaClient` directly.

______________________________________________________________________

## 6. Summary of Issues

| # | Severity | Issue | Location in Plan |
|---|---|---|---|
| 1 | **CRITICAL** | `akosha/mcp/client.py` does not exist — MCP client for calling Mahavishnu's `query_component_traces` is not yet built | Line 216-217 |
| 2 | **MODERATE** | OTelStorageAdapter requires pgvector extension — undocumented infrastructure prerequisite | Line 23-24 |
| 3 | **MODERATE** | Akosha in-memory buffer has no max size or flush TTL defined — OOM risk during extended Dhara outage | Line 147-148 |
| 4 | **MODERATE** | No backfill mechanism when Mahavishnu recovers — gaps in trace history during outage are permanent | Line 146 |
| 5 | **INFORMATIONAL** | No schema validation on trace attributes — silent mismatches will corrupt fitness calculations | Line 90-97 |

______________________________________________________________________

## 7. Recommendations

### Must Fix Before Implementation

1. **Add `akosha/mcp/client.py` to Key Files table** or specify which existing module handles outbound MCP calls to Mahavishnu. This is a hard dependency — Akosha cannot compute fitness without it.

1. **Document pgvector as an infrastructure prerequisite** in the plan's setup section. Every Bodai component needs it.

### Should Fix for Robustness

3. **Define in-memory buffer limits**: max size (e.g., 1000 signals) and max buffer age (e.g., 5 minutes before TTL expiry). Without this, the in-memory buffer is a potential OOM source.

1. **Add trace schema validation** in `query_component_traces` or Akosha's fitness analyzer — at minimum, log a warning if required `bodai.*` attributes are missing.

### Nice to Have (Post-MVP)

5. **Backfill on recovery**: When Mahavishnu recovers, Akosha should query the full window that was missed (tracked via a `last_query_timestamp` persisted to Dhara).

1. **Circuit breaker success threshold**: Current implementation closes after one success — consider requiring N consecutive successes before closing (reduces flapping).

______________________________________________________________________

## 8. Standalone Operation Matrix (Updated)

Replace the existing matrix with this expanded version:

| Components running | Behavior | Degradation |
|---|---|---|
| Mahavishnu only | Routes with `least_loaded`. OTel ingester stores traces locally. | None — fully functional |
| Mahavishnu + Dhara only | Mahavishnu writes pool/routing state to Dhara. No fitness signals (Akosha down) → fallback to `least_loaded`. | Routing works with default strategy |
| Akosha only | Fitness job runs, finds no traces (Mahavishnu down), logs warning, idles. No signals written. | Feedback loop inactive; Akosha itself continues |
| Akosha + Dhara only | Akosha buffers signals in-memory. No trace store (Mahavishnu down). On Dhara up, buffered signals written on next cycle. | Feedback loop partial; signals written when Mahavishnu available |
| Dhara only | Passive KV store — idles. No active processes. | None |
| Session-Buddy only | Emits OTel locally. No routing decisions. | None |
| Crackerjack only | Emits OTel locally. No routing decisions. | None |
| Full chain up | Complete feedback loop: traces → Akosha → Dhara → Mahavishnu routing | None |
| Mahavishnu + Akosha + Dhara | Complete feedback loop minus trace push from other components. Akosha computes fitness; Mahavishnu routes. | Signals computed from Mahavishnu's own traces only |

______________________________________________________________________

*End of review*
