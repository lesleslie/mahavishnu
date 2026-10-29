---
status: active
role: canonical
date: 2026-10-21
last_reviewed: 2026-10-21
topic: fitness-analyzer-pair-inventory
---
# Fitness analyzer pair inventory: declared ∪ observed

Resolves **§5.7 / Q1** of `docs/specs/2026-10-20-bodai-otel-substrate-read-path.md`,
the question spec §5.7 says R-6 "must not be implemented until it is answered."
It is answered here: **declared inventory for R-6's first cut, union'd with
observed data in the long-term design, with the difference surfaced as report
output.**

## Context

The pair set is the mechanism of the whole rewiring, and it is currently an
emergent property of the HTTP fan-out. `fitness_analyzer.py:109-112` gathers
over `self._component_endpoints` — a **registration-time list**, not a
data-derived one. When a component returns nothing, its name is still in the
pair set. That property (inventory independent of traffic) is what makes a
quiet service visible as quiet.

Rewiring removes the enumeration. §5.7 offers three replacements; none is
correct alone.

## The finding that reframes the choice

**The fan-out is already dead.** Verified 2026-10-21:

- `FitnessAnalyzer()` is constructed with no arguments (`akosha/mcp/tools/__init__.py:170`),
  so `component_endpoints or []` at `fitness_analyzer.py:66` yields an empty list.
- `add_component` (`fitness_analyzer.py:73`) is the only other writer and has
  **zero call sites** fleet-wide.
- `init_fitness_analyzer` (`fitness_tools.py:19`) only stores the global; it logs
  `"Initialized with %d component endpoints"` — which logs **0**.
- `fitness_analyzer.py:162` guards on `if not self._component_endpoints:`, so
  `analyzer.start()` polls nothing.

So `run_fitness_analysis` currently reports on no components. Spec §5.6's stated
fear — "silent-signal-regression" of a *working* signal — does not apply,
because there is no working signal to regress. The real risk is the mirror
image: **shipping a path that returns zeros and looks healthy.**

That reframing does not reduce Q1's importance; it raises the stakes. With an
empty substrate, a data-derived inventory returns *no pairs at all* and a static
one returns *declared pairs with zero rows* — the same dashboard, opposite
readings, no signal that anything is wrong.

## Decision

**The analyzer's pair set is a declared inventory, union'd with observed pairs.
The report carries the difference.**

| Pair state | Reading |
|---|---|
| declared **and** rows | healthy |
| declared, **no** rows | idle or broken — still listed, so checkable |
| observed, **not** declared | drift — a producer emits a pair nobody inventoried |

No single-source option produces the third row. Expected-only cannot see a
producer starting to emit something undeclared; observed-only cannot see a
declared producer going quiet. The union makes **both** visible, and the
undeclared-observed set doubles as the staleness alarm — if the inventory rots,
that row appears, and that is a build failing rather than a number quietly
going wrong.

### Why not the other two

- **`SELECT DISTINCT` — rejected.** It re-derives the inventory from the data,
  which is a regression *toward* the property the rewrite exists to fix,
  reintroduced at the substrate layer. It is also the only option whose failure
  is invisible: a migrated-but-silent producer disappears, and "idle" becomes
  indistinguishable from "broken."
- **`known_mcp_servers` roster — rejected as specified, adopted in substance.**
  §5.7 rejects it because the producer→pairs mapping "does not exist today."
  It is smaller than that. Both **axes are already canonical** (below); what is
  genuinely new is one table joining them. The roster is the right *seed* for
  the inventory, not the wrong mechanism.
- **Static configured list — adopted for R-6.** Predictable and explicit, and
  the only first-cut option where silence stays distinguishable from absence.

### The declared inventory is cheap, because the axes already exist

§5.7 treats the missing mapping as the blocker. Both axes are already governed:

- **`task_class`** — `TaskCategory` StrEnum, 15 values,
  `mahavishnu/core/model_routing.py:94-112`, already CI-pinned to
  `settings/models.yaml` by `tests/unit/test_task_router.py::TestYAMLRoutingSync`.
- **`selector`** — 5 values in use: `least_loaded`, `round_robin`, `random`,
  `affinity`, `peer_affinity`.

So the inventory is not hand-invented. It is one new table over already-guarded
enums, seeded from `otel.receiver.known_mcp_servers`.

## The constraint that decides whether this works

**Do not declare the cross product.** 15 categories × 5 selectors is 75 pairs. A
full cross-product inventory yields 75 rows of "configured but never emitted" —
the *same* healthy-looking-zero defect, merely louder. The inventory must be a
curated per-producer list of pairs actually expected to be emitted.

Two rules make curation enforceable rather than aspirational:

1. **A pair enters the inventory only with a named emitter** — a producer
   instance expected to produce it. No emitter, no declaration.
2. **A pair leaves when its emitter is decommissioned**, and the removal is a
   visible diff in review rather than a silent edit. This is the counterpart to
   the undeclared-observed row: both make drift show up as work.

An inventory that cannot go stale is not being curated; it is being ignored.

## What this does and does not unblock

**Unblocks:** R-6's Step 1 (plan §"Task R-6", Step 1: "Answer §5.7 before writing
code"). The decision is recorded here as that step asks.

**Does not unblock:** R-6 itself. It stays blocked by R-5, which needs v7 PR-0a
(`spans_substrate` DDL — currently **0 occurrences** in
`oneiric/adapters/vector/duckdb_hot_store.py`) and PR-A3 (`OTLPReceiver` —
currently **0 files** in `akosha/`). R-6's rewiring calls `SpanQuery.summary`
against a table that does not yet exist.

## Implemented 2026-10-22 — and what it changed

R-6 shipped (`akosha`, same day). Two things this decision did **not** predict,
both found by the characterization tests this very decision's context refers to:

**1. `p99_latency_ms` is now a real percentile — a deliberate behaviour change.**
The removed `_compute_signal` computed `sorted[min(int(n * 0.99), n - 1)]`,
which equals the *maximum* for any `n <= 100`. The substrate uses
`PERCENTILE_CONT(0.99)`, which interpolates. Same ten spans, latency 1..10:
`10.0` before, `9.91` after. Downstream consumers may notice. Recorded in
`akosha/tests/unit/test_fitness_p99_semantics.py`.

**2. `SpanQuery.summary` now takes `scored_outcomes_only`, and the two callers
disagree.** The `spans_summary` MCP tool (R-3) scores only `success`/`error` —
an `unsettled` span is neither, and must not pad the denominator. That contract
is tested and intentional. The analyzer's historical denominator was *every*
returned row, with only `'error'` counted as a failure. Filtering would silently
redefine a reported fitness number. So the population is now an explicit
parameter rather than a hidden one, and each caller states which it wants.

The first R-6 attempt removed the `outcome IN (...)` predicate outright, on the
reasoning that it was untested. It was tested — in `tests/unit/mcp/`, which the
initial grep missed. Reverting to a parameter was the correct fix; deleting a
shipped contract to suit one caller was not.

**Consequence for this decision's scope:** the analyzer constructed with no
arguments still has no `SpanQuery` and no declared pairs, so every cycle is a
no-op. Supplying both belongs to the lifespan that owns the OTLP receiver
(PR-A3). Until then R-6 is inert, not broken.

## Status

Active. The declared list and the no-data distinction are implemented. The union
with observed pairs, and the undeclared-observed drift row, are additive and do
not change the output shape.
