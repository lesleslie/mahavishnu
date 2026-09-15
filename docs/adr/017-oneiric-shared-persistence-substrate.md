---
status: draft
role: canonical
kind: decision
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on: []
decision_date: 2026-09-14
topic: persistence-substrate
---

# ADR 017: Oneiric as the shared persistence substrate for Bodai

## Status

**Proposed** (2026-09-14) — pending review and adoption

Promoted from Appendix C of the serverless-readiness plan
(`docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`,
status: active) during plan-promotion time. This ADR carries the
decision into the canonical record so it is not buried inside a
long plan document.

## Context

Prior to this ADR, each Bodai component chose its own persistence
stack:

- **Mahavishnu:** `mahavishnu/ingesters/otel_ingester.py` directly imported
  `from akosha.storage import HotStore` (line 1319 and 8 other direct
  dhara package imports).
- **Akosha:** bespoke `HotStorageConfig` with hardcoded DuckDB defaults
  (`akosha/akosha/config.py:40-53`).
- **Dhara:** hardcoded `FileStorage` in `dhara/dhara/mcp/server_core.py:141-148`,
  no cloud primary adapter, fcntl-based locks.
- **Session-Buddy:** separate `store_reflection` path with its own SQLite.
- **Crackerjack:** filesystem-based, no persistence layer.

This per-component choice produced three concrete problems:

1. **Cross-component imports** (Mahavishnu → Akosha) break when either
   repo upgrades independently. The wire-up gap pattern documented in
   the serverless-readiness plan Rev-9.
2. **Serverless deployment** requires each component to choose a
   serverless-safe backend; without a shared abstraction, this is
   repeated work and divergent decisions.
3. **State sync across cloud and local-first deployments** is per-
   component (Litestream for SQLite here, pg_dump there, manual
   rsync for blobs) instead of a one-line config change.

## Decision

**Oneiric is the single persistence substrate for all Bodai
components.** Every state read/write path in Mahavishnu, Akosha,
Dhara, Session-Buddy, and Crackerjack goes through a Oneiric adapter:

- `oneiric.adapters.storage` for blobs (S3-compatible, local-disk,
  mirror, snapshot)
- `oneiric.adapters.database` for SQL (sqlite, postgres with Neon
  read-replica, libsql/Turso embedded replica)
- `oneiric.adapters.cache` for KV (memory, redis, multitier L1+L2,
  snapshot)
- `oneiric.adapters.queue` for message queues (redis_streams,
  cloudtasks, kafka, nats, pubsub, rabbitmq, lavinmq)
- `oneiric.adapters.vector` for embeddings (pgvector, qdrant)

**Direct Python imports from one Bodai component into another's
storage layer are forbidden.** Cross-component state access goes
through MCP/HTTP or through a shared Oneiric adapter registered
with both components.

## Why Oneiric specifically

- **Already shipped.** 54 built-in adapters across 14 categories, all
  in production at https://github.com/lesleslie/oneiric.
- **Layered config.** `oneiric.core.config` means env-var → YAML →
  settings override works for every Bodai component using the same
  format (`{PROJECT_PREFIX}_{SECTION}__{FIELD}`).
- **Adapter registry is uniform.** Same model for every category; no
  per-category API to learn.
- **Local-first reads, cloud-durable writes.** Memory and sqlite
  adapters for hot reads; postgres, redis_streams, S3 for durable
  writes. Configuration choice, not code path.

## Consequences

### Positive

- **Serverless-deployable by configuration.** A Bodai component
  deployed to a serverless platform changes settings, not code.
  The serverless-readiness plan's Phase 8 (EventBridge Redis Streams
  WAL), Phase 4 (Dhara cloud storage), Phase 5 (Mahavishnu storage
  layer) all depend on this substrate.
- **No more cross-component imports.** Phase 5 of the serverless-
  readiness plan replaces the 8 direct dhara imports + 1 direct
  akosha.storage import with Oneiric adapter access.
- **State sync is a CLI command.** Phase 3 documents the vendor-CLI
  sync pattern (`gcloud storage rsync`, `mc mirror`, `aws s3 sync`,
  `rclone sync`, `turso db sync`) in `docs/ops/state-sync.md`.

### Negative

- **Oneiric becomes load-bearing.** If Oneiric breaks, every Bodai
  component's persistence breaks. Mitigation: Oneiric's adapter
  pattern means most failures are isolated to one adapter; the rest
  of the system continues to function. Plus the adapter pattern
  means a missing adapter returns a clear `LifecycleError` rather
  than silent corruption.
- **Refactoring cost.** Components with bespoke storage need
  rewrites. Phase 4 (Dhara), Phase 5 (Mahavishnu), Phase 6 (Akosha
  strip + schema consolidation) of the serverless-readiness plan
  all depend on this ADR.
- **Oneiric's release cadence is a Bodai release cadence.** Bug
  fixes and adapter additions in Oneiric directly affect Bodai.
  Mitigated by Oneiric's existing test coverage (the Oneiric repo
  has integration tests for every adapter).

## Rejected alternatives

- **Keep per-component persistence, add a thin shared facade.**
  Rejected — adds a layer without removing the underlying
  duplication. Two problems instead of one.
- **Mandate Postgres for everything.** Rejected — locks out
  SQLite-shaped local-first deployments and the Turso-style
  embedded replica pattern. The user has explicitly chosen
  SQLite-shaped local-first as the default for Bodai components
  (per the brainstorm session 2026-09-14).
- **Mandate SQLite/libsql for everything.** Rejected — write-heavy
  workloads (KV layer, fitness signals, idempotency keys per
  REQ-MAHAVISHNU-KV) need Postgres semantics. Oneiric's adapter
  layer lets each workload pick the right backend.

## Implementation evidence

This decision is not speculative; the supporting pieces are landing
in Phases 4-6 of the serverless-readiness plan:

- **Phase 3** — Oneiric adapter additions (`storage.mirror`,
  `database.libsql`, `database.postgres` Neon extension, `cache.snapshot`).
- **Phase 4** — Dhara re-architecture: replace fcntl locks
  (REQ-DHARA-LOCKS), replace hardcoded FileStorage with Oneiric
  adapter selection (REQ-DHARA-STORAGE), cloud primary storage
  (REQ-DHARA-CLOUD), async path via cloud-safe storage
  (REQ-DHARA-ASYNC).
- **Phase 5** — Mahavishnu's OtelIngester uses Oneiric storage
  (REQ-MAHAVISHNU-STORAGE); all 8 direct dhara imports + 1 direct
  akosha.storage import replaced (REQ-MAHAVISHNU-IMPORTS).
- **Phase 6** — Akosha schema move to mcp-common (REQ-AKOSHA-SCHEMAS);
  22 of 32 tools replaced by off-the-shelf or deleted
  (REQ-AKOSHA-STRIP).
- **Phase 8** — EventBridge Redis Streams WAL uses
  `oneiric.adapters.queue.redis_streams` directly (REQ-EVENTBRIDGE-WAL).

Together these phases implement this ADR; this decision document
is the contract they implement.

## References

- `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`
  (status: active) — implements this ADR through Phases 3-6 and 8.
- `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` — amended
  2026-09-14 to note the Oneiric layer between Mahavishnu and Dhara.
- `oneiric/adapters/` — adapter inventory (54 built-ins).
- `.claude/decisions/wire-up-contract.md` — integration contract
  rules this ADR enforces.
- `docs/ops/state-sync.md` — vendor-CLI sync pattern.
- `docs/ops/eventbridge-wal.md` — Redis Streams WAL operator doc.
