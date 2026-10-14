---
status: draft
role: historical
kind: audit
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on: []
topic: akosha-hnsw-on-duckdb
---

# Akosha: HNSW Index Creation Fails on DuckDB

**Status:** Open <!-- legacy status: Open — see YAML frontmatter -->.
Discovery during the 2026-09-14 akosha `/health=503` investigation.
Log evidence: `HNSW index creation failed: Binder Error: Unknown
index type: HNSW` repeated 5× per akosha poll cycle in
`/Users/les/.local/state/mcp/logs/akosha.err`.

This is **out of scope** for
`docs/plans/2026-09-14-common-mcp-client-transport-unification.md`
(Phase 5 stub at §3 + §5.5 in that document); tracked here so the
discovery isn't lost and so a future plan can pick it up cleanly.

## Background

The akosha `code_graphs_feed` ingester attempts to create an HNSW
index for vector-similarity queries on the DuckDB-backed `HotStore`.
DuckDB does not ship a native HNSW index type — its documented
capability is `ART` indexes via the `vss` extension; HNSW support is
not a DuckDB feature. The `Binder Error: Unknown index type: HNSW`
is DuckDB's planner rejecting the `CREATE INDEX ... USING HNSW`
statement.

The pattern was likely copy-pasted from Akosha's pgvector backend
(supports HNSW natively) and not adapted to the DuckDB backend's
capability set. The pgvector backend is documented as an optional
dependency via `[dependency-groups]` `storage-pg` in Akosha's
`pyproject.toml`; default installations run on DuckDB and therefore
hit this bug on every poll cycle.

## Why out of scope for the mcp-common transport plan

That plan's purpose is to fix the cross-server transport and time-
bounded `/health` aggregation. The HNSW bug:

1. Is in akosha-only code (not in `mcp-common`).
2. Affects `code_graphs_feed.ok`, not `local_traces_feed.ok` —
   the latter is what the 2026-09-13 `/health=503` investigation
   was focused on.
3. Has a different fix surface (DuckDB schema design, possibly
   switching to `ART` or skipping the index when on DuckDB).
4. Does not block any other Bodai MCP server.

Folding it into the transport plan would dilute the integration-
contract evidence (the HNSW fix doesn't touch the transport layer).
A standalone plan + followup is cleaner for review and audit.

## Next-steps for a future plan

1. Decide between (a) disabling HNSW on DuckDB and accepting a
   linear-scan hot_store.query_traces, or (b) switching code_graphs
   storage to pgvector by default, or (c) using `vss` extension's
   `ART` index when available.
2. Add a `plan_id` column to the `conversations` table that
   distinguishes between pgvector-backed and DuckDB-backed installs
   (already partially in place via `isinstance(hot_store, HotStore)`
   checks).
3. Tests: confirm `code_graphs_feed.ok=true` when vector-emission
   succeeds AND HNSW (or chosen replacement) actually builds.
4. Migration: operate the HNSW failure path as a documented
   "degraded" mode for the duration of the rollout so operators
   see the gap rather than a silent linear-scan.

## Refs

- `akosha/akosha/storage/hot_store.py` (HNSW CREATE INDEX call site).
- `akosha/akosha/ingestion/code_graph_ingester.py` (consumer).
- `/Users/les/.local/state/mcp/logs/akosha.err` (5× HNSW Binder Error per cycle).
- `docs/plans/2026-09-14-common-mcp-client-transport-unification.md`
  §3 + §5.5 (out-of-plan pointer).
