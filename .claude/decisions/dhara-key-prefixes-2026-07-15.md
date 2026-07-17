---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: dhara-key-prefixes
---

# Dhara Key Prefixes for Ultracode Integration

## Context

The ultracode integration wiring plan (see
`docs/plans/2026-07-11-ultracode-integration-wiring.md`) introduces three
new Dhara-persisted data domains:

| Phase | Producer | Reader(s) |
|---|---|---|
| 1 — Diverse-refuter verification | `mahavishnu/core/verification.py` | `mahavishnu metrics verification`, future approval review UI |
| 3 — Routing-decision telemetry | `pool_route_execute`, `PoolManager.route_task` | `mahavishnu metrics dispatch`, Akosha cross-pool analytics |
| 4 — Cross-repo clone handling | `clone_refactor_group`, `clone_detect_ecosystem` | refactor DAG consumer, audit log readers |

Each of these domains has its own payload schema and its own consumer
read-path. Sharing a single key prefix (e.g. dumping everything under
`ultracode/`) would force readers to filter-by-suffix; isolating each
domain under its own top-level prefix lets `Dhara.list_prefix(...)`
return exactly the slice a reader needs.

## Decision rule

Canonical Dhara key prefixes for ultracode-persisted data are:

| Prefix | Phase | Payload shape |
|---|---|---|
| `verification/` | Phase 1 | `{proposal_id, refuter_results[], consensus, persisted, timestamp}` |
| `routing-decisions/` | Phase 3 | `{caller_kind, parent_session_id, pool_id, async_callback, timestamp}` |
| `clone-handled/` | Phase 4 (planned) | `{cluster_id, repos[], action, operator, timestamp}` |

Implementation rules:

1. **One prefix per domain.** Do not co-locate verification records and
   routing decisions under a shared `ultracode/` namespace. The
   `DharaClient.list_prefix` cost grows linearly with the namespace; a
   shared prefix means each reader pays for every other reader's writes.

1. **No trailing path component in the prefix itself.** Producers must
   append their own subpath (e.g. `verification/{proposal_id}/{verdict_id}`,
   `routing-decisions/{ts_ms}-{caller_kind}-{pool_id}`). The prefix
   constant in `mahavishnu/metrics_cli.py` (`VERIFICATION_KEY_PREFIX`,
   `ROUTING_DECISIONS_KEY_PREFIX`) is the contract both producer and
   reader respect.

1. **Use the existing `list_prefix` MCP tool**, not a custom scanner.
   The producer side already has `DharaStateBackend.put` /
   `DharaStateBackend.list_prefix`; readers (CLI, dashboards) must use
   the same surface so that circuit-breaker, retry, and config-gating
   semantics stay consistent.

1. **TTL semantics differ per prefix.** `verification/` records are
   short-lived (operator-facing audit trail, 30-day TTL is sensible).
   `routing-decisions/` are longer-lived (analytics base table, 90-day
   TTL default). Document any change to these defaults next to the
   prefix constant in `metrics_cli.py` so producers stay in sync.

## Status  <!-- legacy status: Active — see YAML frontmatter -->

Active. The two CLI subcommands added 2026-07-15
(`mahavishnu metrics verification`, `mahavishnu metrics dispatch`)
implement the reader side for `verification/` and `routing-decisions/`.
The producer side for `verification/` is wired in
`mahavishnu/core/verification.py` (Phase 1 deliverable); the producer
side for `routing-decisions/` lands with the Phase 3 wiring of
`PoolManager.route_task`. The `clone-handled/` prefix is reserved for
the Phase 4 work and has no reader yet.

## References

- `docs/plans/2026-07-11-ultracode-integration-wiring.md` — phases 1, 3, 4
- `mahavishnu/core/state_backends/dhara.py` — `DharaStateBackend.list_prefix`
- `mahavishnu/core/dhara_adapter.py` — `DharaClient.call_tool`
- `mahavishnu/metrics_cli.py` — `VERIFICATION_KEY_PREFIX`,
  `ROUTING_DECISIONS_KEY_PREFIX`, the two subcommands
- `.claude/decisions/bodai-observability-pattern.md` — single-source-of-truth
  for Dhara as the ecosystem state layer
