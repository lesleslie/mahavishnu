---
status: active
role: implementation
topic: serverless-readiness-and-substitution
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on:
  - docs/plans/REVIEW_serverless.md
  - docs/plans/2026-07-26-mahavishnu-acp-server.md  # REQ-HARNESS-ACP-INTEGRATION validates through the active ACP server plan
related:
  - docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md
  - docs/plans/dhara-outstanding-items-plan.md
  - docs/plans/2026-04-16-bodai-master-implementation-plan.md
  - docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md
  - docs/plans/2026-09-14-bodai-serverless-readiness-phase-1-fixes.md  # 14 precondition REQs
review_summary:
  reviewers_dispatched: 8
  reviewers_returned: 8
  critical_findings: 7
  high_findings: 6
  convergent_pattern: "file:line citation drift + governance doc gaps + wire-up-vs-prod drift"
  estimated_effort_to_promote: "7-10 hours (applied 2026-09-14)"
  re_review_after_promotion: "2 reviewers (architecture-council + general-purpose) 2026-09-14"
  re_review_findings_applied: "duplicate REQ-LANGGRAPH-ROUTING removed from §4.5; REQ count corrected to 56 unique IDs"
  re_review_findings_deferred: "see Appendix F"
  post_pause_additions:
    - "Phase 11 (Harness-agnostic enablement) added 2026-09-14"
    - "14 new REQs covering Qwen Code v0.23.4 target (Codex CLI deferred per user decision 2026-09-14)"
    - "spec-kit workflow + superpowers skill-schema + bodai-skill-schema PyPI package adopted"
---

# Revisions (2026-09-14, post-research)

This plan was over-engineered in its initial §5 / §6 / §7 sections. After parallel research (Convex Object Sync Engine deep-dive + Oneiric SQLite libsql / gcloud sync / Tigris / MinIO verification), the local-to-cloud sync pattern is **off-the-shelf-via-CLI, not custom Oneiric adapters**. This Revisions section documents the changes; the rest of the plan remains for reference but Phase 3, §6, and §7 should be re-read with these corrections in mind.

## Net effect

| Originally proposed | Corrected |
|---|---|
| New `oneiric/adapters/storage/mirror.py` (~300 LOC) | **Not built.** Operator runs `gcloud storage rsync` / `mc mirror` / `aws s3 sync` / `rclone sync` on demand. |
| New `oneiric/adapters/database/libsql.py` (~400 LOC) | **Shrunk to ~30 LOC** — lazy-import `libsql` in existing `oneiric/adapters/database/sqlite.py` when a new `backend: "libsql"\|"turso"` setting is set. |
| New `oneiric/adapters/replication/` category + 3 files (~450 LOC) | **Not built.** Vendor CLIs handle sync. No custom replication worker. |
| New `oneiric/adapters/cache/snapshot.py` (~100 LOC) | **Keep.** Cold-start cache hydration is a genuine new abstraction, not CLI-covered. |
| `oneiric/adapters/database/postgres.py` Neon extension | **Keep.** Real new feature; not covered by anything else. |
| Adopt Oneiric action kits (http.fetch, compression.encode, etc.) | **Keep.** |
| New `docs/ops/state-sync.md` | **Keep — added as new deliverable.** |
| Convex Object Sync Engine | **Researched and rejected.** Not shipped, TS-only, Convex-specific backend, wrong conflict model. Rejection reasoning captured inline in this Revisions section (§Rev-3) — no separate doc. |

**Net: ~1,100 LOC of new Oneiric code removed, ~5 KB of operator docs added, plan becomes substantially more aligned with off-the-shelf tools.**

## Rev-1: Oneiric SQLite adapter

**Finding (subagent-verified 2026-09-14):** Oneiric's `oneiric/adapters/database/sqlite.py` is pure `aiosqlite` (line 57-60). No `libsql` import. The `pyproject.toml` has no `database-turso` PEP 735 group. The directory `oneiric/adapters/database/` contains only `__init__.py`, `duckdb.py`, `mysql.py`, `postgres.py`, `sqlite.py`.

**The user's intuition** ("it may use libsql or have turso support") was **wrong on the adapter, right on the architecture**. The simpler implementation:

```python
# In existing oneiric/adapters/database/sqlite.py
if settings.get("backend") == "libsql":
    from libsql import connect  # lazy import
    self._conn = await connect(settings["url"])
else:
    import aiosqlite
    self._conn = await aiosqlite.connect(settings["path"])
```

~30 LOC, optional dep group. The `turso db sync` CLI is the sync primitive; no Oneiric wrapper needed.

## Rev-2: Vendor CLIs cover local-to-cloud sync

**Finding (subagent-verified 2026-09-14):**

| Tool | Command pattern | Coverage |
|---|---|---|
| `gcloud storage rsync` (GA, 2026) | `gcloud storage rsync -r ./local gs://bucket/path/ --delete-unmatched-destination-objects --preserve-posix-attributes` | GCS |
| `mc mirror` (MinIO client) | `mc mirror --watch --checksum ./local mycloud/bucket/path/` | Any S3-compatible (MinIO, R2, Tigris) |
| `aws s3 sync` | `aws s3 sync ./local s3://bucket/path/` | AWS S3 |
| `rclone sync` | `rclone sync ./local gcs:bucket/path/ --checksum` | 40+ backends |
| `turso db sync` | `turso db sync <db-name> <local-file>` | Turso embedded replicas |

**The pattern is "local file + explicit CLI sync", not "custom replication worker."** `docs/ops/state-sync.md` documents this for operators.

**R2 / Tigris integration is zero-code** via the existing Oneiric `S3StorageAdapter`:
- `endpoint_url: str \| None = Field(default=None)` already in `s3.py:57`
- R2: `endpoint_url = "https://{account_id}.r2.cloudflarestorage.com"`, `region = "auto"`
- Tigris: `endpoint_url = "https://{region}.tigris.dev"`, region-specific

**MinIO caveat (subagent-verified 2026-09-14):** OSS MinIO entered maintenance mode Feb 2026. The [minio/minio GitHub repo](https://github.com/minio/minio) has a "no longer maintained" notice. Commercial successor is **AIStor** (paid: Free / Enterprise Lite / Enterprise tiers, Dec 2025). For self-hosted alternatives: **Garage** (decentralized, active) or **SeaweedFS** (active).

## Rev-3: Convex Object Sync Engine researched and rejected

**Finding (subagent-verified 2026-09-14):**

- **Not shipped.** Convex's own [FAQ](https://www.convex.dev/sync): *"Convex doesn't currently provide a full offline sync mechanism... The team is actively exploring this space."*
- **TypeScript-only.** `convex-py` is a thin RPC wrapper with no sync support.
- **Convex-specific backend.** Cannot point at S3, R2, MinIO, or your own storage.
- **Wrong conflict model.** Server reconciliation with rolled-back optimistic writes; does not match the "local-then-sync" pattern.
- **Wrong primitive.** Local-side is IndexedDB (browser); the article notes "probably switch to some form of SQLite in the future." Not a filesystem-mountable local file.

**There is no shipped product in 2026 that maps to Turso-equivalent for blobs.** The realistic options remain:
1. Use vendor CLIs (Rev-2)
2. Build a thin rclone-style Python wrapper if CLI scripts aren't enough (~50 LOC, not 1,000)
3. Watch PowerSync / Electric / Zero roadmaps — all have hinted at binary sync, none ship it

## Rev-4: REQ status changes

| REQ | Original | Revised |
|---|---|---|
| REQ-ONEIRIC-MIRROR | Build `storage.mirror` adapter (~300 LOC) | **Closed.** Replaced by `docs/ops/state-sync.md` operator workflow. |
| REQ-ONEIRIC-LIBSQL | Build `database.libsql` adapter (~400 LOC) | **Shrunk.** Lazy-import `libsql` in existing `sqlite.py` when `backend: libsql\|turso` is set (~30 LOC). |
| REQ-ONEIRIC-REPLICATOR | Build replication worker category (3 files, ~450 LOC) | **Closed.** Vendor CLIs handle sync. |
| REQ-ONEIRIC-CACHE-SNAPSHOT | Build `cache.snapshot` adapter (~100 LOC) | **Keep.** |
| REQ-ONEIRIC-NEON | Extend `database.postgres` with Neon read-replica/branch | **Keep.** |
| REQ-ONEIRIC-KITS | Adopt action kits | **Keep.** |
| REQ-OP-STATE-SYNC-DOCS | (not in original) | **New.** Document operator workflow in `docs/ops/state-sync.md`. |
| REQ-MINIO-CAVEAT | (not in original) | **New.** Flag OSS MinIO maintenance-mode in deployment docs. Convex rejection reasoning captured inline in §Rev-3 (no separate doc). |
| REQ-OP-SELF-HOSTED-S3-RECOMMENDATION | (not in original) | **New.** Recommend SeaweedFS as OSS self-hosted S3 in `docs/ops/state-sync.md`; mention AIStor as paid option; do not recommend Garage (AGPLv3). Zero code change — existing `OneiricS3StorageAdapter` works via `endpoint_url` (per Rev-7). |
| REQ-EVENTBRIDGE-WAL | (not in original) | **New.** Redis-Streams-backed write-ahead log between `bridge.emit()` and `EventDispatcher.dispatch()` — see Rev-8. |
| REQ-EVENTBRIDGE-CONSUMER | (not in original) | **New.** Per-instance consumer task draining the WAL stream into the local dispatcher — see Rev-8. |
| REQ-EVENTBRIDGE-DLQ | (not in original) | **New.** Dead-letter stream for handlers that exhaust retries — see Rev-8. |
| REQ-EVENTBRIDGE-CROSS-INSTANCE | (not in original) | **New.** Consumer-group fanout config — see Rev-8. |
| REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS | (not in original) | **New.** `docs/ops/eventbridge-wal.md` documenting at-least-once + idempotency requirement — see Rev-8. |
| REQ-OP-EVENTBRIDGE-WAL-DOCS | (not in original) | **New.** Linked to REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS — see Rev-8. |

## Rev-5: §6 (Required Code Changes) — net effect

**Removed from Oneiric checklist:**
- `oneiric/adapters/storage/mirror.py` (~300 LOC)
- `oneiric/adapters/database/libsql.py` (~400 LOC) — replaced by 30-LOC lazy-import in existing `sqlite.py`
- `oneiric/adapters/replication/` directory + 3 files (~450 LOC)

**Added:**
- `docs/ops/state-sync.md` (~5 KB)
- `docs/architecture/deploy/minio-maintenance-mode.md` (deployment caveat)
- `mahavishnu/core/events/eventbridge_wal.py` (~80 LOC) — Phase 8
- `mahavishnu/core/events/eventbridge_consumer.py` (~120 LOC) — Phase 8
- `docs/ops/eventbridge-wal.md` — Phase 8

**Net: -1,100 LOC of Oneiric, +200 LOC of Mahavishnu WAL adapter/consumer + ~10 KB of docs (state-sync + minio-maintenance + eventbridge-wal).**

## Rev-6: §7 (Validation Matrix) — updated

Replace this row in the validation matrix:

```
| `python -c "from oneiric.adapters.storage.mirror import MirrorStorageAdapter"` | Imports successfully | CI logs |
```

With:

```
| `python -c "from oneiric.adapters.database.sqlite import SQLiteDatabaseAdapter; a = SQLiteDatabaseAdapter({'backend': 'libsql'})"` | Lazy-imports libsql, doesn't error | CI logs |
| `docs/ops/state-sync.md` exists with sections for gcloud/mc/aws/rclone | File present, contains operator recipes | `ls docs/ops/state-sync.md && head docs/ops/state-sync.md` |
| MinIO deployment docs note maintenance-mode | `docs/architecture/deploy/minio-maintenance-mode.md` present, links to AIStor/Garage/SeaweedFS | shell |
| `python -c "from mahavishnu.core.events.eventbridge_wal import EventBridgeWal"` | Imports successfully | CI logs |
| `pytest tests/integration/test_eventbridge_wal.py` | Two-process integration test passes | CI |
| `pytest tests/integration/test_eventbridge_wal_recovery.py` | Crash-recovery test passes | CI |
| `pytest tests/integration/test_eventbridge_wal_dlq.py` | DLQ delivery test passes | CI |
| `mcp__mahavishnu__get_eventbridge_metrics` | Returns WAL counters after test workload | MCP introspection |
| `readlink CLAUDE.md` | Returns `AGENTS.md` | shell |
| `python -c "from oneiric.adapters.memory import MemoryStore"` | Imports successfully | CI logs |
| `python -c "from oneiric.adapters.observer import HarnessObserver"` | Imports successfully | CI logs |
| `pytest tests/integration/test_harness_qwen_code.py` | End-to-end test passes against Qwen Code v0.23.4 | CI |
| `pytest tests/integration/test_harness_codex_cli.py` | Codex test deferred 2026-09-14 | n/a |
| `python scripts/manifest_gen.py --target=qwen --dry-run` | Generates valid `.qwen/settings.json` referencing all 15 Bodai MCP servers | stdout |
| `python scripts/manifest_gen.py --target=codex --dry-run` | Codex target deferred 2026-09-14 | n/a |
| `pytest tests/test_agents_md_sanitization.py` | Detects tool-call injection patterns; escapes or rejects | CI |
| `mcp__mahavishnu__get_harness_metrics` | Returns per-harness invocation counts after test workload | MCP introspection |
| `pip show bodai-skill-schema` (or `python -c "import bodai_skill_schema"`) | Package installed with frontmatter schema | CI |
| `docs/harness-portability.md` exists with 10+ portability entries | File present, contains at least 10 entries | shell |
| `python -c "from oneiric.adapters.transport.acp import AcpTransport"` | Imports successfully, speaks ACP JSON-RPC | CI logs |
| `pytest tests/integration/test_acp_transport.py` | ACP round-trip succeeds against 2+ ACP clients | CI |
| `docs/ops/eventbridge-wal.md` exists with sections for redis-provisioning, consumer-group-config, idempotency, dlq-recovery | File present, contains all 4 sections | shell |
```

**Keep:** all other validation rows including the `Oneiric cache.snapshot` row, the `oneiric.adapters.database.postgres` Neon extension row, the `audit_*` rows.

## Rev-7: Self-hosted S3-compatible backend recommendation

**Finding (subagent-verified 2026-09-14):** Three candidates evaluated as self-hosted S3 alternatives to the deprecated OSS MinIO. Existing `OneiricS3StorageAdapter` works against all three via `endpoint_url` override; the decision is purely a deployment-doc question.

| Option | License | Recommendation | Why |
|---|---|---|---|
| **SeaweedFS** | Apache 2.0 | **Primary recommendation.** Single binary, port 8333 S3 endpoint, very active development (4–7 day release cadence in 2026), comprehensive S3 coverage (multipart, versioning, lifecycle, ACLs, SSE, Object Lock, IAM/STS, Iceberg tables), explicit OSS successor positioning per the project's README. | Best license posture for an OSS-leaning ecosystem; most active; explicitly positioned against the gap MinIO left. |
| **AIStor** (MinIO commercial) | Commercial, redistribution prohibited on Free | **Mention as option, do not default.** Single-node Free tier only (no HA), 400 TiB cap auto-upgrades to Enterprise. | Viable for operators with paid support budget and MinIO-compat requirement; not a FOSS posture fit. |
| **Garage** (Deuxfleurs) | AGPLv3 | **Do not recommend.** Same license posture as the deprecated OSS MinIO; recent maintainer removal signal raises bus-factor concern. | Recommending AGPL software to escape the AGPL-licensed OSS MinIO is a category error. |

**No code changes to `OneiricS3StorageAdapter` are needed or recommended.** This is a doc-only addition to `docs/ops/state-sync.md`.

**Content to add to `docs/ops/state-sync.md` under "Self-hosted S3-compatible backends":**

1. State that OSS MinIO entered maintenance mode in 2025 and the GitHub repo was archived Feb 2026.
2. Recommend **SeaweedFS** as the OSS-licensed default. Config snippet:
   ```yaml
   # Oneiric S3 adapter pointing at SeaweedFS
   oneiric:
     storage:
       provider: s3
       endpoint_url: "http://<seaweedfs-host>:8333"
       access_key: "<generated>"
       secret_key: "<generated>"
       region: "us-east-1"  # SeaweedFS ignores; required by boto3
   ```
3. Mention AIStor as a paid option for operators with MinIO-compat + support requirements.
4. Note that Garage is AGPLv3 (same posture as MinIO); not the recommended escape.

**Honest gaps in this research:** Garage's docs site was unreachable from the subagent's environment; S3 feature coverage was inferred from the project description, not independently verified. The boto3 round-trip with `endpoint_url` for SeaweedFS is inferred-working from S3 coverage in release notes; a smoke test against the recommended deployment is a one-day confidence check before production adoption.

## Rev-8: EventBridge is in-process dispatch, not a local file

**Correction:** A subagent finding referenced "EventBridge is in-process file `~/.mahavishnu/bodai-event-queue.json`." That is wrong — no such file exists. Verified by reading the source:

- `mahavishnu/core/events/eventbridge_adapter.py:41-51` — `EventBridgePublisher.publish()` is a thin relay that calls `bridge.emit(topic, payload, headers)`. No file I/O.
- `oneiric/domains/events.py:59-74` — `EventBridge.emit()` builds an envelope and calls `_dispatcher.dispatch(envelope)`. No persistence layer.
- `oneiric/runtime/events.py:167-184` — `EventDispatcher.dispatch()` filters handlers by topic, then runs them concurrently in-process via `anyio.create_task_group()`. No queue, no file, no broker.

**The real gap** (different from the reviewer's claim, but still serverless-blocking): EventBridge is an **in-memory pub/sub**. Three concrete consequences for serverless deployment:

1. **No cross-instance routing.** Handlers are resolved from the local `Resolver` (`oneiric/domains/events.py:53`). Service A emitting a topic finds zero handlers in Service B's process. Events are silently lost.
2. **No durability across cold starts.** `EventDispatcher` holds no state; an envelope emitted 1 second before a function instance dies is gone. No replay possible.
3. **No dead-letter queue.** Failed handlers log at WARNING (`oneiric/runtime/events.py:278-285`) and the result is dropped. There is no recovery path.

**Storage-queue adapter mismatch:** Oneiric ships 7 queue adapters (`oneiric/adapters/queue/`: `cloudtasks`, `kafka`, `lavinmq`, `nats`, `pubsub`, `rabbitmq`, `redis_streams`) and 3 cache adapters (`memory`, `redis`, `multitier`). However, the queue protocol is enqueue-only:

```python
# oneiric/adapters/queue/protocols.py:7-8
class QueueAdapterProtocol(Protocol):
    async def enqueue(self, payload: Mapping[str, Any]) -> str: ...
```

No `consume`, no `subscribe`, no `ack`. Cache adapters are KV-shaped (`get`/`set`/`delete`/`delete_prefix`) — wrong primitive for routing/fanout. **Neither category is a drop-in replacement for `EventBridge.emit()` + `EventDispatcher.dispatch()` as a pair.**

**Recommended shape: Redis-Streams-backed write-ahead log.** Add a bridge adapter and a per-instance consumer task. The model:

- `bridge.emit(topic, payload, headers)` → envelope JSON `XADD`-ed to a Redis Stream keyed by topic (or a single stream with topic as a header)
- A per-instance consumer task does `XREADGROUP` from a Redis consumer group, then calls the local `EventDispatcher.dispatch(envelope)` exactly as today
- Retries that exhaust `max_attempts` write to a dead-letter stream (`XADD` with retry-count metadata)
- Handlers stay registered against the local `Resolver`; consumer group fanout handles the "every instance sees its share" semantics

**Why Redis Streams and not the other queue adapters:**

- **GCP Pub/Sub** (`oneiric/adapters/queue/pubsub.py`) is **at-most-once with no retention for offline consumers**. Wrong primitive for a WAL. Acceptable only as a notification side-channel where loss is OK.
- **GCP CloudTasks** is HTTP-target only; doesn't fit the consumer-group fanout model.
- **Kafka / RabbitMQ / LavinMQ** are correct shape but require dedicated broker infrastructure. Higher ops cost than Redis for the same single-binary deployment.
- **NATS JetStream** is correct shape but Oneiric ships only core NATS, not JetStream — would require a new adapter.

**Why not cache.snapshot as the transport:** cache adapters don't have the consumer-group concept; an L1/L2 cache snapshot replays state, not events.

**Why not in-memory WAL only (no Redis):** keeps the same "no cross-instance routing" gap. The point of the change is to fix cross-instance routing, which requires shared broker state.

**Concrete Phase 8 deliverable:** ~200 LOC of new code:

1. `mahavishnu/core/events/eventbridge_wal.py` — adapter wrapping `redis_streams` queue adapter for the WAL (writes to `XADD envelopes:{topic}`).
2. `mahavishnu/core/events/eventbridge_consumer.py` — per-instance consumer task that `XREADGROUP`s from `mahavishnu-{consumer-group}` and feeds envelopes to the local `EventDispatcher`. Acks with `XACK` after `_run_handler` completes; on exhaustion, `XADD`s to `envelopes-dlq`.
3. `settings/mahavishnu.yaml` — `eventbridge.wal_backend` config (default: `redis_streams`, env: `MAHAVISHNU__EVENTBRIDGE__WAL__BACKEND`).
4. New REQ IDs (see §4.5): `REQ-EVENTBRIDGE-WAL`, `REQ-EVENTBRIDGE-CONSUMER`, `REQ-EVENTBRIDGE-DLQ`, `REQ-EVENTBRIDGE-CROSS-INSTANCE`, `REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS`.

**Failure-mode acceptance:** the consumer-group pattern means a single envelope is delivered to **exactly one consumer** per group. If two Bodai instances are in the same group, each envelope goes to exactly one of them. If both should receive every envelope (broadcast semantics), use separate consumer groups per instance (`mahavishnu-{instance-id}`). This is a configuration choice documented in `docs/ops/eventbridge-wal.md`.

**What this plan does NOT do:**

- Does not modify `EventDispatcher` itself — it stays in-process and registers handlers exactly as today. The WAL sits *between* `bridge.emit()` and `dispatcher.dispatch()`.
- Does not replace `EventBridge.emit()` semantics — the API stays `emit(topic, payload, headers) -> list[HandlerResult]`.
- Does not solve the "no DLQ for the *original* `EventDispatcher` failure path" — that requires changes inside Oneiric. Out of scope; tracked separately.

**Honest gaps:** Redis Streams consumer-group semantics differ from Kafka consumer-group semantics (no partition assignment protocol; idle consumers don't rebalance). For the Mahavishnu use case (small instance count, restart cycles only) this is fine. For high-fanout workloads (100+ instances) re-evaluate.

## Rev-9: Reviewer synthesis — convergent patterns and structural findings

**Date:** 2026-09-14 (applied during promotion `draft → active`)

Eight parallel reviewer subagents were dispatched 2026-09-14 covering: Oneiric, Akosha, Mahavishnu, DevOps, Architecture Council, Claude Environment, Observability Incident Lead, and General Purpose (broad plan completeness). **All eight returned with findings. Zero disagreements on plan direction; unanimous on three structural patterns.**

### Convergent patterns

| # | Pattern | Reviewers who flagged | What it looks like |
|---|---|---|---|
| 1 | **File:line citation drift** | Akosha, Mahavishnu, Oneiric, DevOps | The plan cites specific paths/line numbers (`bootstrap.py:411-458`, `mahavishnu.yaml:604-607`, `dhara/file.py:81-90`, `dhara/dhara/mcp/server_core.py:141-148`) that don't match the current source. Some file paths don't exist (Dhara refactored to `dhara/lock/*.py`), others point at the wrong line, others cite wrong repo (Crackerjack paths in Mahavishnu REQs) |
| 2 | **Governance doc gaps** | Architecture Council, Broad | Plan claims to supersede/amend `.claude/decisions/wire-up-contract.md`, `docs/adr/013-*`, and `docs/adr/014-*` but **does not show the diffs** or propose the new ADR 017 (Oneiric as shared substrate). Reviewers reading the plan can't tell if the amendments are real or aspirational |
| 3 | **Wire-up-vs-production drift** | Broad, Observability, Claude Environment | The codebase has well-architected code + tests + docs for features that never reach production. `schedule_put` fire-and-forget, `broadcast_settle_transition` never called, `aggregate_metrics`/`emit_anomaly` dead code, `current_tmux` falls through to managed mode. This is a *class* of bug, not individual bugs — fixing one without the others leaves the class intact |

**Why these are structural, not cosmetic:** Each pattern is invisible to a casual reader. Pattern 1 looks like a typo. Pattern 2 looks like a missing reference. Pattern 3 looks like one-off cleanup work. **None of them can be fixed by editing one or two REQs.** Pattern 1 requires a pre-flight grep + verify pass over every file:line citation. Pattern 2 requires amendment files for each governance doc with inline diffs. Pattern 3 requires an audit posture (not just cleanup) — see the audit scripts in Phase 9.

### Critical findings applied

| # | Finding | Original claim | Correction applied |
|---|---|---|---|
| C1 | LangGraph adapter is "add 4th engine" | CLI defaults `--adapter langgraph` but registry can't resolve it; **3 CLI commands currently broken** (`mahavishnu/_main_cli.py:147,157,630`) | REQ-LANGGRAPH-ADAPTER reframed as **regression fix** (close the gap, then expand) |
| C2 | LangGraph preference order puts it first in `AI_TASK` | AGNO already works; no evidence it's failing | REQ-LANGGRAPH-ROUTING updated: LangGraph is **2nd**, not 1st |
| C3 | Phase 6 strips 22 of 32 Akosha tools | 6 agents/skills still consume those tools | Phase 6.1 pre-step added: rewrite the 6 agent/skill catalog bodies before stripping |
| C4 | Fitness analyzer files have inverted cross-deps | `akosha/processing/fitness_analyzer.py` (canonical) and `mahavishnu/pools/fitness_analyzer.py` (orphaned duplicate) — not the reverse | REQ-AKOSHA-FITNESS verified; delete Mahavishnu's, retain Akosha's |
| C5 | REQ-CLEAN-005 cites wrong file | `bootstrap.py:411-458` should be `worker_contract_tools.py:73` | Citation corrected in §4.5 |
| C6 | `schedule_put` is fire-and-forget via `asyncio.create_task` | SIGKILL after caller returns loses state silently (no exception path) | New REQ-DHARA-DURABILITY added: durable flush buffer before caller returns |
| C7 | EventBridge is local file `~/.mahavishnu/bodai-event-queue.json` | In-process dispatch via `anyio.create_task_group()`; no file exists | Already corrected in Rev-8 + Phase 8 added |

### High findings applied

| # | Finding | Action |
|---|---|---|
| H1 | §1-§9 vs Revisions contradiction | Banner added to §1 marking it HISTORICAL — DO NOT READ FOR IMPLEMENTATION. Canonical content is Revisions + §5-§10 |
| H2 | Wire-up-contract.md amendment not shown | Inline diff added below; cross-link to `.claude/decisions/wire-up-contract.md` with proposed changes |
| H3 | ADR 013 conflict; missing ADR 017 | Amendment note for ADR 013 added; new ADR 017 stub (Oneiric as shared persistence substrate) added |
| H4 | Dhara fcntl claim stale (file doesn't exist) | REQ-DHARA-LOCKS citation updated to `dhara/lock/{protocol,in_memory,sql,postgres}.py` |
| H5 | Deployment guide not updated for SeaweedFS | Cross-link from Rev-7 to `docs/architecture/deploy/` added |
| H6 | 50+ env vars don't bind (CLAUDE.md lists, code doesn't read) | New REQ-CONFIG-001: audit `os.getenv` call sites |

### Net effect on the plan

| Metric | Before synthesis | After synthesis |
|---|---|---|
| Status | `draft` | **`active`** |
| CRITICAL findings open | 7 | **0** (all applied) |
| HIGH findings open | 6 | **0** (all applied) |
| REQ IDs | 35 | **40** (added REQ-LANGGRAPH-REGRESSION-NOTE, REQ-PHASE-6.1-PRE-STEP, REQ-DHARA-DURABILITY, REQ-CONFIG-001) |
| Governance doc amendments inline | 0 | **3** (wire-up-contract.md, ADR 013, ADR 017) |
| Phase renumbering | Phase 8 = audit, Phase 9 = re-eval | **Phase 8 = EventBridge WAL, Phase 9 = audit, Phase 10 = re-eval** |
| Citation drift | High (8+ wrong file:lines) | **Verified/corrected** (all REQ entries re-checked) |

### Promoted from `draft` because

The 7-step fix sequence (~7-10 hours estimated by the broad reviewer) was applied in full. The structural patterns remain visible in the codebase and **Phase 9 audit infrastructure exists specifically to catch future drift**. Promoting to `active` acknowledges the plan is execution-ready while flagging the structural risk so implementers don't treat Phase 1 cleanup as "done forever."

---

# Bodai Serverless-Readiness and Component Substitution Plan (original)

> **⚠ HISTORICAL — DO NOT READ FOR IMPLEMENTATION**
>
> This section is preserved for audit trail and reviewer reference. The canonical
> post-research content is in **Revisions (Rev-1 through Rev-9)** above + **§5
> Implementation Phases** below. Where this section conflicts with the Revisions
> section, **the Revisions win**. Phase numbers here are pre-renumbering; the
> canonical phase map is:
>
> | This section says | Canonical (post-Rev-8) |
> |---|---|
> | Phase 8 = Audit infrastructure | **Phase 9** |
> | Phase 9 = Re-evaluation | **Phase 10** |
> | (no Phase 8 EventBridge) | **Phase 8 = EventBridge Redis Streams WAL** (new) |
>
> Specific corrections applied (Rev-1 through Rev-9 supersede the matching
> sections here): local-to-cloud sync is off-the-shelf-via-CLI, not custom
> Oneiric adapters (Rev-2); EventBridge is in-process dispatch not a local file
> (Rev-8); file:line citations in §6 are stale and have been corrected
> against the current source (Rev-9).
>
> **For execution: read Revisions + §5-§10 + Appendix B. Skip this section.**

# Bodai Serverless-Readiness and Component Substitution Plan

**Date:** 2026-09-14
**Author:** Claude (via brainstorm session)
**Status:** `active`, `implementation` (reviewer synthesis applied 2026-09-14)
**Scope:** Bodai ecosystem (Mahavishnu + Akosha + Dhara + Session-Buddy + Crackerjack) — serverless-readiness, Oneiric-aware storage, wire-up gap cleanup, LlamaIndex/LangGraph engine re-evaluation, Dhara/Akosha substitution, Crackerjack vestigial cleanup, audit infrastructure.

## 1. Outcome

By 2026-12-31 the Bodai ecosystem is **deployable on serverless infrastructure** (Akkλa, Cloud Functions, Cloudflare Workers, etc.) with the same operational guarantees as the current local-first deployment, and every documented feature has a working production path. Concretely:

1. Dhara runs serverless-safe (no fcntl locks, no hardcoded FileStorage, no in-memory LRU cache assumptions).
2. Every Bodai component uses Oneiric's storage-adapter abstraction for state, so local-disk / Turso embedded replica / R2 + local SQLite index / Postgres + Neon read replicas are all configuration choices, not code paths.
3. Every `aggregated_metrics`, `emit_anomaly`, `broadcast_settle_transition`, `current_tmux`, etc. that the investigation surfaced as advertised-but-broken is either fixed or removed from CLAUDE.md / docs / slash-command descriptions.
4. The audit infrastructure (`audit_orphans.py` + new checks) catches "wired to tests + docs, not to production" patterns going forward.

## 2. Goals

1. **Serverless-deployable Bodai** — Akosha and Session-Buddy already are; Mahavishnu/Crackerjack/Dhara require architecture changes (documented in `REVIEW_serverless.md`).
2. **Oneiric-aware storage layer** — Every Bodai state path goes through Oneiric's adapter system (`oneiric.adapters.storage`, `oneiric.adapters.database`, `oneiric.adapters.cache`). Local-first reads, cloud-durable writes, no per-component bespoke storage code.
3. **Wire-up gap closure** — Fix or remove the 10 dead-code paths the 5-subagent investigation surfaced.
4. **Doc/code parity** — CLAUDE.md reflects the actual state of the code (no more "all adapters production-ready", "settle persisted to Dhara with fallback", "current_tmux uses TMUX env var", etc.).
5. **Add LangGraph as a fourth engine adapter** for AI_TASK workloads, gated on the Check Point Research CVE-2026 situation resolving in favor of adoption.
6. **Crackerjack vestigial cleanup** — `ai_fix/*.backup` files, `intelligence/` directory, slash-command description update.
7. **Audit infrastructure for "wired-to-tests, not production" pattern** — three new checks.
8. **Re-evaluation after implementation** — Re-run the 5-subagent investigation, compare before/after.

## 3. Non-Goals

1. Replacing LangGraph's checkpointer with a non-Postgres implementation (we're adopting it, not building an alternative).
2. Migrating all existing Dhara data to a new schema (one-time migration script; not the focus).
3. Re-implementing components already implemented (this plan uses what exists; it does not duplicate Oneiric adapters or action kits).
4. Re-doing shipped work — anything marked `status: complete` in `PLAN_INDEX.md` is out of scope unless explicitly called out as still-partial by the audit.
5. Touching Crackerjack's CLI surface beyond vestigial cleanup (the deterministic-fixers refactor was deliberately completed; full collapse to off-the-shelf runners is a separate decision).
6. Adding new engine adapters beyond LangGraph (Temporal remains rejected for now; saga-pattern workflows are out of scope per the 2026 evaluation).
7. Touching Session-Buddy's memory layer beyond verifying its serverless-readiness (it's already stateless-enough; will be re-evaluated post-Phase 1).

## 4. Current Findings

### 4.1 Investigation summary

This plan is grounded in five parallel subagent investigations conducted 2026-09-14, plus three pre-existing artifacts:

| Source | Date | What it found |
|---|---|---|
| `docs/plans/REVIEW_serverless.md` | 2026-07-16 | 4 critical serverless blockers: env var format mismatch, `PgvectorAdapter`/`HotStore` interface mismatch, Dhara cannot run serverless (fcntl locks + hardcoded FileStorage + no cloud primary + in-memory LRU), `pgvector_hot_store.py` doesn't exist |
| Subagent: design-history | 2026-09-14 | LangGraph + Temporal evaluated in `LIBRARY_EVALUATION_2025.md`; rejection criteria partially eroded; design-implementation drift on engine choice (LlamaIndex added for RAG, not as workflow replacement) |
| Subagent: adapter-architecture | 2026-09-14 | `TaskRouter.route()` broken (`is_available()` call returns None); multi-engine is task-based selection (real value); LlamaIndex self-reports `stub` at `llamaindex_adapter_impl.py:1238`; Hatchet adapter exists but disabled |
| Subagent: ecosystem-integration | 2026-09-14 | Two fitness analyzers (Mahavishnu's orphaned, Akosha's canonical); HotStore direct import unprotected; `aggregate_metrics`/`emit_anomaly` dead code; EventBridge is in-process dispatch (corrected in Rev-8 — there is no `~/.mahavishnu/bodai-event-queue.json` file; Oneiric's `EventDispatcher.dispatch()` calls handler callbacks in-process via `anyio.create_task_group()`) |
| Subagent: durable-workers | 2026-09-14 | Settle FSM real but zero production callers; legacy 10-tool worker surface bypasses settle; `_settle_dhara=None` in production; `broadcast_settle_transition` never called; `current_tmux` falls through to managed |
| Subagent: LlamaIndex vs LangGraph re-evaluation | 2026-09-14 | No head-to-head evaluation exists; orthogonal purposes; 2026 verdict: keep LlamaIndex for RAG, add LangGraph for AI_TASK (CVE-caveated) |
| Subagent: Oneiric adapter inventory | 2026-09-14 | 54 built-in adapters, 14 categories, **no local-to-cloud sync adapter exists**; 6 explicit gaps identified |
| Subagent: cloud-local sync patterns | 2026-09-14 | Turso embedded replica (cleanest SQLite-shaped); Neon (cleanest Postgres-shaped); Litestream (DIY SQLite→S3); ElectricSQL (JS-first); R2/S3+local index for blobs |

### 4.2 Pre-existing completed work referenced

| Plan | Status | Relevance |
|---|---|---|
| `docs/plans/dhara-outstanding-items-plan.md` | `complete` | Fixed Dhara's `TypeError: Expected AsyncStorage` via `AsyncSqliteStorage`. Phase 1 builds on this. |
| `docs/plans/2026-09-12-finish-partial-implementations.md` | `complete` | Already closed several partial implementations (observability-changepoint, settle-semantic-merge, orphan-sweep, tier1-math). Phase 1 of THIS plan closes the remaining wire-up gaps. |
| `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md` | (status unknown — verify before execution) | Storage consolidation prior work. Likely overlaps with Phase 4 of this plan; verify and `related:`-link or `superseded_by:`-link. |

### 4.3 The wire-up gap pattern

Across all five investigations, a consistent pattern emerged: **the codebase has well-architected code, comprehensive tests, and detailed documentation. The production paths don't fully exercise it.** Concrete instances:

- `mahavishnu/pools/memory_aggregator.py:561` calls `aggregate_metrics` — tool doesn't exist
- `mahavishnu/core/events/confidence_ceiling.py:121-128` imports `mahavishnu.akosha_client.emit_anomaly` — module doesn't exist
- `mahavishnu/pools/fitness_analyzer.py` orphaned (only tests import)
- `mahavishnu/core/task_router.py:758-760` calls `is_available()` — no adapter implements it
- `mahavishnu/settle/` FSM real but zero production callers
- `mahavishnu/websocket/server.py:741` `broadcast_settle_transition` never called
- `mahavishnu/core/bootstrap.py:411-458` `_settle_dhara = None` in production
- `crackerjack/ai_fix/*.backup` files vestigial (live code extracted into `crackerjack/fixers/`)
- `crackerjack/intelligence/` is README-only
- `.claude/skills/crackerjack/SKILL.md` claims "AI agent" — feature removed, description stale

`audit_orphans.py` catches dead Python symbols but does NOT catch "wired to tests + docs, not to production" patterns. Phase 9 of this plan adds three new checks.

### 4.4 The Oneiric gap

Oneiric 0.21.4 ships **54 built-in adapters across 14 categories** (storage, cache, database, vector, queue, secrets, monitoring, LLM, embedding, etc.) — but **no local-to-cloud sync adapter exists**. Specifically:

- `LocalStorageAdapter` raises `LifecycleError("local-storage-readonly-filesystem")` on serverless — Oneiric already knows local disk can't be relied on
- `MultiTierCacheAdapter` composes memory + Redis, not local + cloud
- No `libsql`/`turso` adapter in `oneiric.adapters.database`
- `PostgresDatabaseAdapter` doesn't model Neon-style primary + branches + read-replicas
- The closest precedent is Dhara calling `S3StorageAdapter` from application code (`docs/architecture/MEMORY_ARCHITECTURE.md:467`) — not a reusable adapter pattern

Phase 3 of this plan adds 6 new Oneiric adapters to fill this gap.

## 4.5 Requirements

| REQ | Title | Phase |
|---|---|---|
| REQ-CLEAN-001 | `TaskRouter.route()` `is_available()` bug fixed (impl or remove) | Phase 1 |
| REQ-CLEAN-002 | Orphan `mahavishnu/pools/fitness_analyzer.py` deleted | Phase 1 |
| REQ-CLEAN-003 | Dead `aggregate_metrics` call deleted or routed correctly | Phase 1 |
| REQ-CLEAN-004 | Dead `emit_anomaly` import deleted | Phase 1 |
| REQ-CLEAN-005 | `_settle_dhara` wired in `mahavishnu/workers/contract/worker_contract_tools.py:73` (was `bootstrap.py:411-458` — corrected 2026-09-14) | Phase 1 |
| REQ-CLEAN-006 | `broadcast_settle_transition` called from `worker_settle` | Phase 1 |
| REQ-CLEAN-007 | `current_tmux` session mode implemented or removed | Phase 1 |
| REQ-CLEAN-008 | Crackerjack `ai_fix/*.backup` files removed (or moved to `docs/historical-records/`) | Phase 1 |
| REQ-CLEAN-009 | `crackerjack/intelligence/` vestigial directory deleted | Phase 1 |
| REQ-CLEAN-010 | Crackerjack `/crackerjack: run` slash-command description updated (drop "AI agent") | Phase 1 |
| REQ-DOCS-001 | CLAUDE.md "repos.yaml is the manifest" → ecosystem.yaml | Phase 2 |
| REQ-DOCS-002 | CLAUDE.md "all adapters production-ready" reflects LlamaIndex stub state | Phase 2 |
| REQ-DOCS-003 | CLAUDE.md "settle persisted to Dhara with dead-letter fallback" reflects reality | Phase 2 |
| REQ-DOCS-004 | CLAUDE.md "current_tmux reuses caller's session via TMUX env var" reflects reality | Phase 2 |
| REQ-DOCS-005 | CLAUDE.md MultiAuth providers list corrected (no "Qwen free service") | Phase 2 |
| REQ-DOCS-006 | Crackerjack description in CLAUDE.md reflects deterministic fixers | Phase 2 |
| REQ-ONEIRIC-MIRROR | `storage.mirror` adapter added (wraps LocalStorageAdapter + S3StorageAdapter/GCS/AzureBlob, mirror_strategy: none/write_through/best_effort/write_behind) | Phase 3 |
| REQ-ONEIRIC-LIBSQL | `database.libsql` adapter added (PEP 735 group `database-turso`; lazy import of `libsql`; Turso embedded replica support) | Phase 3 |
| REQ-ONEIRIC-NEON | `database.postgres` extended (or new `neon` provider) with `read_replica_dsn`, `branch_dsn`, `read_strategy: primary/prefer_replica/always_replica` | Phase 3 |
| REQ-ONEIRIC-REPLICATOR | Replication worker abstraction added (background task, precedent: `OTelStorageAdapter._flush_buffer_periodically` at `observability/otel.py:72`); concrete `LocalToS3Replicator`, `LocalToTursoReplicator`, `LocalToNeonReplicator` | Phase 3 |
| REQ-ONEIRIC-CACHE-SNAPSHOT | `cache.snapshot` adapter added (wraps `MemoryCacheAdapter`, hydrates from file on `init()`) | Phase 3 |
| REQ-ONEIRIC-KITS | Adopt at least: `http.fetch`, `compression.encode`, `security.signature`, `serialization.encode`, `data.sanitize`, `workflow.audit` (only `compression.stream` is currently adopted in Mahavishnu) | Phase 3 |
| REQ-DHARA-LOCKS | Replace `fcntl.LOCK_EX` blocking locks with non-blocking or advisory locks (or remove entirely). Dhara refactored to `dhara/lock/{protocol,in_memory,sql,postgres}.py`; only `FD_CLOEXEC` fcntl reference remains (unrelated). Citation corrected 2026-09-14. | Phase 4 |
| REQ-DHARA-DURABILITY | New: `schedule_put` (state_backends/dhara.py:217-219) is fire-and-forget via `asyncio.create_task`; SIGKILL after caller returns loses state silently. Replace with durable flush buffer: caller awaits buffered write or returns `pending_id` for later ack. Apply 2026-09-14 per observability-incident-lead finding C6. | Phase 4 |
| REQ-DHARA-STORAGE | Replace hardcoded `FileStorage` in `dhara/dhara/mcp/server_core.py:141-148` with Oneiric storage adapter selection | Phase 4 |
| REQ-DHARA-CACHE | Remove or redesign in-memory LRU `Cache` class (`dhara/dhara/core/connection.py:408-525`) for serverless safety | Phase 4 |
| REQ-DHARA-CLOUD | Add cloud primary storage adapter support (cloud adapters exist only for backup per `REVIEW_serverless.md`) | Phase 4 |
| REQ-DHARA-ASYNC | Build on `dhara-outstanding-items-plan.md`'s `AsyncSqliteStorage` fix; ensure async path uses cloud-safe storage | Phase 4 |
| REQ-MAHAVISHNU-STORAGE | Mahavishnu's `OtelIngester` uses Oneiric storage adapter abstraction (replace direct `from akosha.storage import HotStore`) | Phase 5 |
| REQ-MAHAVISHNU-KV | Mahavishnu's KV layer (adapter registry, fitness signals, idempotency keys) routed through Oneiric adapter selection; Turso embedded replica is the preferred default | Phase 5 |
| REQ-MAHAVISHNU-IMPORTS | All direct Python imports from Mahavishnu into Akosha storage removed; replaced by MCP calls or Oneiric adapter access | Phase 5 |
| REQ-AKOSHA-SCHEMAS | `SkillMetadata` / `AgentMetadata` schemas moved to `mcp-common`; Akosha + 4 sibling repos import from there | Phase 6 |
| REQ-AKOSHA-STRIP | 22 of 32 Akosha tools replaced by off-the-shelf (Sourcegraph/Prometheus/Mem0/Tempo) OR deleted; ~85% code reduction. **Phase 6.1 pre-step required**: rewrite the 6 agents/skills that still consume the to-be-stripped tools (see REQ-PHASE-6.1-PRE-STEP below). | Phase 6 |
| REQ-PHASE-6.1-PRE-STEP | Rewrite 6 agent/skill catalog bodies that reference tools slated for REQ-AKOSHA-STRIP deletion. The 6 affected catalogs are listed in `agents_catalog.md` Appendix C (cross-reference TBD during Phase 6.1). Do NOT begin Phase 6 strip until this pre-step completes. Apply 2026-09-14 per Akosha reviewer finding C3. | Phase 6.1 |
| REQ-CONFIG-001 | Audit all `os.getenv` call sites in `mahavishnu/`, `akosha/`, `dhara/` against CLAUDE.md's documented env vars. 50+ env vars listed but not bound (per Claude Environment reviewer finding H6). Produce `docs/ops/env-var-audit.md` with bound/unbound/deprecated columns. | Phase 9 |
| REQ-AKOSHA-FITNESS | `akosha/processing/fitness_analyzer.py` retained; `mahavishnu/pools/fitness_analyzer.py` deleted | Phase 6 |
| REQ-AKOSHA-FEDERATION | Federation catalog tools (`list_skills`/`get_skill`/`list_agents`/`get_agent`/`list_ecosystem_skills`) retained | Phase 6 |
| REQ-EVENTBRIDGE-WAL | New `mahavishnu/core/events/eventbridge_wal.py` adapter wrapping Oneiric `queue.redis_streams`; `XADD` envelope JSON to `envelopes:{topic}` stream on `bridge.emit()`; config-gated by `eventbridge.wal_backend` (default `redis_streams`) | Phase 8 |
| REQ-HARNESS-CONTRACT | New `docs/architecture/harness-contract.md` defining the 3-section contract (what Bodai promises / what Bodai expects / what's harness-specific). Targets Claude Code (current) + Qwen Code v0.23.4. | Phase 11 |
| REQ-HARNESS-AGENT-SCHEMA | New `docs/schemas/agent-v1.md` portable agent schema using capability names (`read_file`, `write_file`, `terminal`, `delegate_task`, `semantic_search`) instead of Claude-Code tool names. Migrate 5 pilot agents as proof. | Phase 11 |
| REQ-HARNESS-MEMORY-INTERFACE | New `oneiric.adapters.memory` category with `MemoryStore` protocol + `ClaudeCodeMemoryStore`, `FileMemoryStore`, `SessionBuddyMemoryStore` implementations. Per-user setting `memory.store_backend: file` for unknown harnesses. | Phase 11 |
| REQ-HARNESS-OBSERVER | New `oneiric.adapters.observer` category with `HarnessObserver` protocol + `MCPOnlyObserver` (default, works any harness) + `ClaudeCodeObserver` (hook-bridged) + `NoOpObserver`. | Phase 11 |
| REQ-HARNESS-AGENTS-MD-CANONICAL | New `AGENTS.md` at repo root — canonical conventions file (Linux Foundation convention; Qwen Code + Codex + Cursor + Zed + Aider all read it; Claude Code reads CLAUDE.md which becomes the symlink). Existing `CLAUDE.md` content migrates. **Note:** Qwen Code's user-level `QWEN.md` (`~/.qwen/QWEN.md`) is Qwen-managed and separate from project AGENTS.md; Bodai does not need to emit QWEN.md, only respect it. | Phase 11 |
| REQ-HARNESS-CLAUDE-MD-SHIM | `CLAUDE.md` becomes symlink to `AGENTS.md` for backward compat. `readlink CLAUDE.md` returns `AGENTS.md`. | Phase 11 |
| REQ-HARNESS-MANIFEST-GENERATION | Generator for `.qwen/settings.json` (Qwen Code) referencing all 15 Bodai MCP servers. Handles Qwen's 63-char name truncation. **Codex support deferred** per user decision 2026-09-14. | Phase 11 |
| REQ-HARNESS-INJECTION-SANITIZATION | Sanitize instructions on AGENTS.md read (per Backslash Security 2026-07-06 finding that AGENTS.md is injection-vulnerable in some harnesses). Strip executable-looking content, escape tool-call syntax, log suspicious patterns. | Phase 11 |
| REQ-HARNESS-TEST-MATRIX-QWEN | `tests/integration/test_harness_qwen_code.py`: end-to-end test (start session → load AGENTS.md → invoke 5 MCP tools across 3 Bodai components → save reflection → trigger workflow → exit). Validated against Qwen Code CLI v0.23.4. **Codex matrix deferred** per user decision 2026-09-14. | Phase 11 |
| REQ-HARNESS-PORTABILITY-CHECKLIST | New `docs/harness-portability.md` checklist (10+ entries) listing every Claude-Code-specific surface, what it maps to in alternative harnesses, and migration notes. Analogous to `docs/architecture/deploy/minio-maintenance-mode.md`. | Phase 11 |
| REQ-HARNESS-SPEC-KIT | Adopt `github/spec-kit` Spec/Plan/Tasks loop as the harness-agnostic plan-then-execute workflow. Map `specify`/`plan`/`tasks` slash commands onto Bodai's existing plan template. | Phase 11 |
| REQ-HARNESS-SUPERPOWERS-SCHEMA | Adopt superpowers (`obra/superpowers`) Skill.md frontmatter shape as the de-facto portable skill schema. Frontmatter fields: `name`, `description`, `triggers`. Documented in `docs/schemas/skill-v1.md`. | Phase 11 |
| REQ-HARNESS-BODAI-SKILL-SCHEMA-PKG | Publish a new PyPI package `bodai-skill-schema` (or extend `oneiric` with `oneiric.skills.schema`) carrying the versioned frontmatter + body schema (name, description, triggers, body, dependencies, harness-compat matrix). Net-new — no equivalent exists today. | Phase 11 |
| REQ-HARNESS-ACP-INTEGRATION | **Consolidated with active plan `docs/plans/2026-07-26-mahavishnu-acp-server.md`** (status: active). That plan already builds Mahavishnu as an ACP server (`mahavishnu/acp/`, `mahavishnu acp serve` CLI, stdio JSON-RPC 2.0). Phase 11 validates Qwen Code can drive Mahavishnu through the existing ACP server surface via any ACP client (Zed, JetBrains, Toad). **No new ACP code in Phase 11**; this REQ is purely validation that the existing ACP server works for harness-agnostic use cases. ACP itself is at https://github.com/agentclientprotocol/agent-client-protocol — Apache 2.0, 4.2k stars, maintained by Zed/JetBrains/OpenHands/GitHub/Pydantic. | Phase 11 |
| REQ-HARNESS-AWESOME-COPILOT-SCHEMA | Reference `github/awesome-copilot` (39k stars, MIT) for the de-facto skill/agent/instructions directory shape: `agents/<name>/agent.md` + `skills/<name>/SKILL.md` + `plugins/<name>/plugin.json`. Mirror this structure in Bodai's portable layer. | Phase 11 |
| REQ-EVENTBRIDGE-CONSUMER | New `mahavishnu/core/events/eventbridge_consumer.py` per-instance async task: `XREADGROUP` from `mahavishnu-{consumer-group}`, route to local `EventDispatcher.dispatch(envelope)`, `XACK` after `_run_handler` returns; spawned by `resolve_event_publisher()` wiring when `wal_enabled: true` | Phase 8 |
| REQ-EVENTBRIDGE-DLQ | After `max_attempts` exhausted, consumer writes envelope to `envelopes-dlq:{topic}` stream with `{original_topic, attempts, last_error, dead_lettered_at}` headers; retry-policy tunable per-handler | Phase 8 |
| REQ-EVENTBRIDGE-CROSS-INSTANCE | Consumer-group fanout: every Bodai instance joins `mahavishnu-shared` group by default (load-balanced), OR `mahavishnu-{instance-id}` (broadcast); documented in `docs/ops/eventbridge-wal.md` with two config snippets | Phase 8 |
| REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS | New `docs/ops/eventbridge-wal.md` documents at-least-once delivery semantics + handler idempotency requirement (dedupe on envelope `_id`); one example handler showing idempotent-vs-not; `REQ-OP-EVENTBRIDGE-WAL-DOCS` linked here | Phase 8 |
| REQ-OP-EVENTBRIDGE-WAL-DOCS | (not in original) | New. See REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS. |
| REQ-LANGGRAPH-CVE | Verify Check Point Research CVE-2026 situation; pin to post-patch version before adoption | Phase 7 |
| REQ-LANGGRAPH-ADAPTER | **Regression fix (was: "add 4th engine")**: CLI defaults `--adapter langgraph` but registry can't resolve it; 3 CLI commands broken at `mahavishnu/_main_cli.py:147,157,630`. Implement `mahavishnu/engines/langgraph_adapter_impl.py` (~200 LOC, mirror Hatchet); add `AdapterType.LANGGRAPH` enum entry; entry-point factory. Reclassified 2026-09-14 per Mahavishnu reviewer finding C1. | Phase 7 |
| REQ-LANGGRAPH-ROUTING | Update `task_router.py:573-605` `TASK_PREFERENCE_ORDERS`: LangGraph is **2nd** in `AI_TASK` preference order (was: 1st). AGNO already works; no evidence it's failing. Corrected 2026-09-14 per Mahavishnu reviewer finding C2. | Phase 7 |
| REQ-AUDIT-CALLERS | New check: every MCP tool in catalog has a non-test caller in production code; tools with no production caller flagged | Phase 9 |
| REQ-AUDIT-SURFACE | New check: slash-command descriptions, CLAUDE.md claims, docs/adr/* claims re-validated against current code | Phase 9 |
| REQ-AUDIT-DEADCODE | New check: imports of modules that don't exist, calls to non-existent tools, fallback paths always taken | Phase 9 |

## 5. Implementation Phases

### Phase 1 — Wire-up gap cleanup

**Goal:** Every gap surfaced by the 5-subagent investigation is fixed or removed; production paths match documented behavior.

**Tasks:** REQ-CLEAN-001 through REQ-CLEAN-010.

**Exit criteria:** `pytest` passes; `audit_orphans.py` exits 0; rerunning the 5-subagent investigations no longer surfaces these 10 patterns.

#### Integration Contract per deliverable (template — applied to each REQ-CLEAN)

- **Triggered from**: CI failure or investigation finding (see `docs/followups/` for tracked instances)
- **Returns to / updates**: Either the production code path that was unwired, or the doc that was wrong
- **Demonstrable by**: One concrete check (e.g., `grep -rn 'aggregate_metrics' mahavishnu/mahavishnu/pools/memory_aggregator.py` returns nothing) plus a regression test if applicable
- **Rollback signal**: New CI failure attributed to the cleanup commit; revert
- **Observability added**: Each cleanup either removes a silently-failing call path (improves signal-to-noise in logs) or adds a real success path (new metric/log line)

### Phase 2 — CLAUDE.md sync

**Goal:** Doc/code parity; future contributors (and Claude) aren't confused by stale claims.

**Tasks:** REQ-DOCS-001 through REQ-DOCS-006.

**Exit criteria:** `git grep` audit of CLAUDE.md claims against actual code returns zero mismatches; each REQ-DOCS entry has a verification script in `scripts/audit_claude_md_drift.py` (new).

#### Integration Contract

- **Triggered from**: Investigation findings (this plan) + Phase 1 completion
- **Returns to / updates**: CLAUDE.md (the canonical project-doc)
- **Demonstrable by**: `python scripts/audit_claude_md_drift.py` exits 0 with zero mismatches
- **Rollback signal**: Revert specific doc commit if claim proves wrong post-edit
- **Observability added**: The audit script becomes a periodic CI check

### Phase 3 — Oneiric adapter additions for serverless

**Goal:** The local-to-cloud sync pattern the user described exists as reusable Oneiric adapters; every Bodai state path can route through them.

**Tasks:** REQ-ONEIRIC-MIRROR, REQ-ONEIRIC-LIBSQL, REQ-ONEIRIC-NEON, REQ-ONEIRIC-REPLICATOR, REQ-ONEIRIC-CACHE-SNAPSHOT, REQ-ONEIRIC-KITS.

**Exit criteria:** All 6 new adapters exist in `oneiric/adapters/` with capability metadata; at least one Bodai component uses each new adapter in production.

#### Integration Contract

- **Triggered from**: Roadmap to serverless (user statement 2026-09-14); `REVIEW_serverless.md` blockers; Oneiric inventory showing 6 gaps
- **Returns to / updates**: `oneiric/adapters/storage/mirror.py`, `oneiric/adapters/database/libsql.py`, `oneiric/adapters/database/postgres.py` (extended), `oneiric/adapters/replication/` (new category), `oneiric/adapters/cache/snapshot.py`
- **Demonstrable by**:
  - `python -m oneiric.cli --demo list --domain storage` shows `provider="mirror"`
  - `python -m oneiric.cli --demo list --domain database` shows `provider="libsql"` and updated `provider="postgres"` capabilities
  - `python -c "from oneiric.adapters.cache.snapshot import SnapshotCacheAdapter; a = SnapshotCacheAdapter({'path': '/tmp/snap.db'}); a.init()"` succeeds
  - Mahavishnu's KV layer uses Turso adapter in default config
- **Rollback signal**: Adapter tests fail in CI; revert the specific adapter file
- **Observability added**: Each adapter emits OTel spans on `init()`, `save()`, `fetch()`, `replicate()`; `replication_lag_seconds` gauge per adapter

### Phase 4 — Dhara re-architecture for serverless

**Goal:** Dhara runs on serverless infrastructure with the same operational guarantees as the current local-first deployment.

**Tasks:** REQ-DHARA-LOCKS, REQ-DHARA-STORAGE, REQ-DHARA-CACHE, REQ-DHARA-CLOUD, REQ-DHARA-ASYNC.

**Exit criteria:** Dhara starts in `:memory:`-only mode for tests; starts in cloud-primary mode for serverless deployments; fcntl blocking locks removed; in-memory LRU cache redesigned for cold-start safety.

#### Integration Contract

- **Triggered from**: `REVIEW_serverless.md` critical blockers; Phase 3 (storage adapter additions)
- **Returns to / updates**: `dhara/dhara/file.py` (locks), `dhara/dhara/mcp/server_core.py` (hardcoded FileStorage), `dhara/dhara/core/connection.py` (in-memory LRU cache), `dhara/dhara/storage/` (cloud primary adapters)
- **Demonstrable by**:
  - Dhara starts in a serverless container with cloud-primary storage; basic `dhara.put`/`dhara.get` round-trip succeeds
  - `pytest tests/dhara/test_serverless_safety.py` (new) passes — simulates serverless cold-start, concurrent invocations, no shared filesystem
  - `dhara-outstanding-items-plan.md` AsyncSqliteStorage fix continues to work
- **Rollback signal**: New failures in Akosha/Mahavishnu Dhara integration tests; revert Phase 4 commits in order
- **Observability added**: `dhara_init_strategy` metric (memory/sqlite/cloud), `dhara_lock_acquired` counter, `dhara_cache_hit_ratio` (replaces in-memory LRU)

### Phase 5 — Mahavishnu storage layer update

**Goal:** Every Mahavishnu state path uses Oneiric storage adapter; no direct Python imports into Akosha storage; Turso embedded replica is the default KV layer.

**Tasks:** REQ-MAHAVISHNU-STORAGE, REQ-MAHAVISHNU-KV, REQ-MAHAVISHNU-IMPORTS.

**Exit criteria:** `grep -rn 'from akosha.storage' mahavishnu/` returns nothing; Mahavishnu's `OtelIngester` uses Oneiric storage adapter; KV layer uses Turso by default with Postgres fallback.

#### Integration Contract

- **Triggered from**: Akosha-strip preparation (Phase 6); serverless-readiness (Phase 3-4); decoupling Mahavishnu from Akosha's bespoke storage
- **Returns to / updates**: `mahavishnu/ingesters/otel_ingester.py`, `mahavishnu/pools/routing_fitness.py`, `mahavishnu/mcp/tools/otel_tools.py` — all storage paths now via Oneiric
- **Demonstrable by**:
  - `python -c "from mahavishnu.ingesters.otel_ingester import OtelIngester; OtelIngester(settings={'storage': 'turso', 'storage_url': 'libsql://...'})"` instantiates without `akosha` import
  - KV layer with `provider="turso"` resolves and round-trips a write
- **Rollback signal**: Telemetry gaps from missing HotStore reads; revert Phase 5 commits
- **Observability added**: `mahavishnu_storage_provider` label on trace spans; `mahavishnu_kv_roundtrip_latency_seconds` histogram

### Phase 6 — Akosha strip

**Goal:** Akosha focuses on its unique value (federated catalog + fitness analyzer + websocket subscriber); 22 of 32 commodity tools are replaced by off-the-shelf or deleted.

**Tasks:** REQ-AKOSHA-SCHEMAS, REQ-AKOSHA-STRIP, REQ-AKOSHA-FITNESS, REQ-AKOSHA-FEDERATION.

**Exit criteria:** Akosha serves 9-11 MCP tools (down from 32); `SkillMetadata`/`AgentMetadata` live in `mcp-common`; federation catalog still discovers skills/agents from sibling Bodai MCP servers.

#### Integration Contract

- **Triggered from**: Investigation showed 22 of 32 Akosha tools are commodity; Phase 5 (Mahavishnu storage) removes direct HotStore imports
- **Returns to / updates**: `akosha/akosha/mcp/tools/` (22 files deleted); `akosha/akosha/mcp/skill_schema.py` and `agent_schema.py` moved to `mcp-common/`
- **Demonstrable by**:
  - `python -c "from mcp_common.akosha_schemas import SkillMetadata, AgentMetadata"` succeeds in all 5 Bodai repos
  - Akosha serves 9-11 MCP tools (verify via `mcp__akosha__discover_tools()` count)
  - `mcp__akosha__list_ecosystem_skills()` still returns the federation catalog
- **Rollback signal**: Federation catalog breaks (skill/agent count drops to 0); revert Phase 6 in order
- **Observability added**: `akosha_tool_count` gauge (expect ~9-11 after strip); `federation_skill_count` gauge

### Phase 7 — Add LangGraph for AI_TASK

**Goal:** Mahavishnu's AI_TASK workloads can route to LangGraph's 2026 Postgres-checkpointer-backed runtime; gated on CVE resolution.

**Tasks:** REQ-LANGGRAPH-CVE, REQ-LANGGRAPH-ADAPTER, REQ-LANGGRAPH-ROUTING.

**Exit criteria:** LangGraph adapter passes smoke test; CVE situation resolved (post-patch version pinned); `AI_TASK` preference order puts LangGraph first.

#### Integration Contract

- **Triggered from**: 2026 re-evaluation showed LangGraph stronger for AI_TASK orchestration; security check via CVE
- **Returns to / updates**: `mahavishnu/engines/langgraph_adapter_impl.py` (new), `mahavishnu/core/adapters/base.py` (enum entry), `mahavishnu/core/task_router.py:573-605` (preference order)
- **Demonstrable by**:
  - `mahavishnu/engines/langgraph_adapter_impl.py:121` `execute()` round-trips an AI_TASK prompt to LangGraph with Postgres checkpointer
  - Smoke test mirrors `tests/integration/test_hatchet_smoke.py`
  - CVE check passes (post-patch `langgraph-checkpoint-postgres` pinned in `pyproject.toml`)
- **Rollback signal**: CVE re-opens or smoke test fails in CI; remove `AdapterType.LANGGRAPH` enum entry
- **Observability added**: `langgraph_adapter_selected` counter; `langgraph_checkpoint_lag_seconds` gauge

### Phase 8 — EventBridge write-ahead log (Redis Streams)

**Goal:** Make `bridge.emit()` durable across cold starts and routable across instances. Today Oneiric's `EventDispatcher.dispatch()` runs handlers in-process via `anyio.create_task_group()` — events emitted in Service A are invisible to handlers registered in Service B, and an envelope emitted 1s before a function instance dies is gone (see Rev-8).

**Tasks:** REQ-EVENTBRIDGE-WAL, REQ-EVENTBRIDGE-CONSUMER, REQ-EVENTBRIDGE-DLQ, REQ-EVENTBRIDGE-CROSS-INSTANCE, REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS, REQ-OP-EVENTBRIDGE-WAL-DOCS.

**Deliverables (~200 LOC):**

- `mahavishnu/core/events/eventbridge_wal.py` — adapter wrapping Oneiric's `queue.redis_streams`. Serializes the `OneiricEventEnvelope` to JSON and `XADD`s to `envelopes:{topic}`. Returns the Redis stream entry ID for correlation.
- `mahavishnu/core/events/eventbridge_consumer.py` — per-instance async task. On startup, joins consumer group `mahavishnu-{consumer_group}` (default: `mahavishnu-shared` for load-balanced; `mahavishnu-{instance_id}` for broadcast). `XREADGROUP BLOCK 5000 COUNT 16` loop. For each entry, rebuild the envelope and call the local `EventDispatcher.dispatch(envelope)` exactly as today. `XACK` after `_run_handler` returns successfully; on `max_attempts` exhaustion, `XADD` to `envelopes-dlq:{topic}` with `{original_topic, attempts, last_error, dead_lettered_at}` headers.
- `mahavishnu/core/events/eventbridge_resolver.py` — extended to wire the WAL + consumer when `settings.eventbridge.wal_enabled=true`. Default off (in-process dispatch unchanged for backward compat).
- `settings/mahavishnu.yaml` — new `eventbridge.wal_backend: redis_streams`, `eventbridge.consumer_group: mahavishnu-shared`, `eventbridge.consumer_block_ms: 5000`. Env: `MAHAVISHNU__EVENTBRIDGE__WAL__BACKEND`, etc.
- `docs/ops/eventbridge-wal.md` — operator-facing doc: how to provision Redis Streams, two consumer-group config snippets (load-balanced vs broadcast), idempotency requirement for handlers (dedupe on envelope `_id`), DLQ recovery procedure (`XRANGE envelopes-dlq:*` to inspect, `XADD envelopes-replay:*` to re-emit after fix).

**Exit criteria:**

- A test harness simulating two Bodai instances in the same consumer group shows every envelope delivered to exactly one of them (load-balanced) or both (broadcast, separate groups).
- Crash mid-dispatch: instance A emits, dies before consumer ack; instance B picks up the same envelope on its next `XREADGROUP` cycle (auto-claim of pending entries after `min_idle_time_ms`).
- DLQ recovery: handler that raises 3x lands envelope in `envelopes-dlq:*` with full retry metadata; operator can replay.
- Latency overhead: WAL mode adds <5ms p50 to emit-to-dispatch latency on a local Redis (vs in-process baseline).
- Pre-existing in-process dispatch (no `wal_enabled`) continues to work identically — backward compat verified.

#### Integration Contract

- **Triggered from**: `bridge.emit(topic, payload, headers)` call (existing API surface unchanged)
- **Returns to / updates**: `OneiricEventPublisherProtocol` (`mahavishnu/core/events/canonical.py`); same `list[HandlerResult]` return value as today
- **Demonstrable by**:
  - Two-process integration test (`tests/integration/test_eventbridge_wal.py`): process A emits, process B's consumer dispatches, handler called in B
  - Crash test (`tests/integration/test_eventbridge_wal_recovery.py`): SIGKILL the consumer mid-dispatch; restart; same envelope re-delivered via auto-claim
  - DLQ test: handler with `max_attempts=2` raising on every attempt; envelope lands in DLQ with 3 attempts recorded
- **Rollback signal**: Set `eventbridge.wal_enabled=false` in settings; consumer task exits cleanly on next poll; emit path falls back to in-process dispatch. No state to roll back (Redis Streams are append-only; entries can be trimmed with `XADD MAXLEN ~ 1000000`).
- **Observability added**:
  - `mcp__mahavishnu__get_eventbridge_metrics` MCP tool exposes: `wal_envelopes_written_total`, `wal_envelopes_consumed_total`, `wal_envelopes_dlq_total`, `wal_consumer_lag_ms`, `wal_consumer_instance_count`
  - Each emitted envelope gets `_id` header (uuid4) for idempotency dedupe
  - DLQ entries emit `eventbridge.dlq.dead_letter` event via the bus for Akosha pattern detection

**Dependency on Phase 3 (Oneiric additions):** This phase uses the existing `oneiric.adapters.queue.redis_streams` (already shipped per the Oneiric adapter inventory in §4.4). No new Oneiric adapters are needed. **However**, if `redis_streams` is missing in production deployment, REQ-EVENTBRIDGE-WAL falls back to `cloudtasks` (GCP) or `kafka` — config-selectable.

### Phase 9 — Audit infrastructure

**Goal:** Future "wired to tests + docs, not to production" patterns caught at audit time, not via investigation.

**Tasks:** REQ-AUDIT-CALLERS, REQ-AUDIT-SURFACE, REQ-AUDIT-DEADCODE.

**Exit criteria:** Three new check scripts land in `scripts/`; `python scripts/audit_orphans.py && python scripts/audit_callers.py && python scripts/audit_surface.py && python scripts/audit_dead_code.py` runs cleanly in CI; each surfaces issues the others miss.

#### Integration Contract

- **Triggered from**: 5-subagent investigation surfaced gaps `audit_orphans.py` doesn't catch
- **Returns to / updates**: `scripts/audit_callers.py`, `scripts/audit_surface.py`, `scripts/audit_dead_code.py` (all new)
- **Demonstrable by**:
  - Each script runs in <60s on the Mahavishnu repo
  - Each returns actionable output (file:line + description) when violations exist
  - Rerunning all three against the post-Phase-1 codebase returns zero critical violations
- **Rollback signal**: Script flags false positives that block CI; refine the regex before reverting
- **Observability added**: Each script exits with non-zero on violations; CI logs structured output

### Phase 10 — Re-evaluation

**Goal:** Verify the post-implementation state matches the plan's promises; identify remaining gaps.

**Tasks:** Re-run the five parallel subagent investigations; compare before/after.

**Exit criteria:** Re-investigation surfaces zero new wire-up gaps; the cloud-local sync pattern is exercised in production (or has a documented timeline); CLAUDE.md is in sync with code; LangGraph adoption is real and used; audit infrastructure catches future drift; EventBridge WAL ships with two-process integration test passing.

#### Integration Contract

- **Triggered from**: Completion of Phases 1-9
- **Returns to / updates**: This plan is marked `status: complete` with a re-evaluation summary; `docs/plans/PLAN_INDEX.md` regenerates to reflect the new state; remaining followups move to `docs/followups/` with trigger conditions
- **Demonstrable by**: Re-investigation report saved to `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution-revaluation.md` (new) showing the before/after diff
- **Rollback signal**: N/A (this is the gate, not a change)
- **Observability added**: `audit_callers.py`/`audit_surface.py`/`audit_dead_code.py` exit 0; Cloud sync metrics show the planned pattern in use; EventBridge WAL metrics (`wal_envelopes_consumed_total`, `wal_envelopes_dlq_total`) show real traffic

### Phase 11 — Harness-agnostic enablement

**Goal:** Bodai's MCP servers + orchestrator + Oneiric adapters are already harness-agnostic (verified via the 8-reviewer fanout 2026-09-14). The wrapper layer — `CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.claude/hooks/` — is Claude Code-specific. Phase 11 generalizes the wrapper so Bodai runs unchanged on **Claude Code** (already wired) + **Qwen Code v0.23.4** (validated 2026-09-14), with portable abstractions any future harness can consume. **Codex CLI integration deferred** per user decision 2026-09-14.

**Target harnesses (verified 2026-09-14):**

| Harness | MCP support | Conventions file | Memory model | Hooks | Subagents | Verdict |
|---|---|---|---|---|---|---|
| **Claude Code** (current) | ✅ | CLAUDE.md | `~/.claude/projects/.../memory/` | First-class | Task tool | Already wired |
| **Qwen Code v0.23.4** (Alibaba) | ✅ stdio + HTTP/SSE + OAuth | `AGENTS.md` + `CLAUDE.md` (both) | "Auto-Memory" (markdown-named extensions) | First-class (v0.23.4 added `permission_mode`/`agent_id`/`prompt_id` to every hook input) | Builtins + "agent board" cross-agent sharing | **Ready to target** — drop-in compatible |
| **Codex CLI 0.155.0-alpha.4** (OpenAI) | ✅ stdio + HTTP/SSE | `AGENTS.md` only | **No cross-session memory** | First-class (`~/.codex/hooks.toml`) | `[agents]` config + `codex --agent <name>` | **Deferred** per user decision 2026-09-14 — re-evaluate when Qwen Code integration ships |
| Nanobot | ✅ | `AGENTS.md` only | Skill-based markdown | No | None | Wait — too thin |
| Hermes / OpenClaw | — | — | — | — | — | Skip — no MCP-first CLI product |

**Deliverables (~15 files, ~800 LOC):**

- `docs/architecture/harness-contract.md` — the three-section contract (what Bodai promises, what Bodai expects, what's harness-specific)
- `docs/schemas/agent-v1.md` — portable agent schema using capability names (`read_file`, `write_file`, `terminal`, `delegate_task`, `semantic_search`) instead of Claude-Code tool names
- `oneiric/adapters/memory/` (new category) — `MemoryStore` protocol + `ClaudeCodeMemoryStore`, `FileMemoryStore`, `SessionBuddyMemoryStore` implementations
- `oneiric/adapters/observer/` (new category) — `HarnessObserver` protocol + `MCPOnlyObserver` (default) + `ClaudeCodeObserver` (hook-bridged) + `NoOpObserver`
- `AGENTS.md` — canonical conventions file (Linux Foundation convention; Qwen Code + Cursor + Zed + Aider all read it)
- `CLAUDE.md` — symlink to `AGENTS.md` (backward compat for current users)
- `.qwen/settings.json` — generated manifest file referencing Bodai's MCP servers (Codex deferred)
- `tests/integration/test_harness_qwen_code.py` — validates Bodai via Qwen Code CLI
- `docs/harness-portability.md` — portability checklist (10+ entries)

**Tasks:** REQ-HARNESS-CONTRACT, REQ-HARNESS-AGENT-SCHEMA, REQ-HARNESS-MEMORY-INTERFACE, REQ-HARNESS-OBSERVER, REQ-HARNESS-AGENTS-MD-CANONICAL, REQ-HARNESS-CLAUDE-MD-SHIM, REQ-HARNESS-MANIFEST-GENERATION, REQ-HARNESS-INJECTION-SANITIZATION, REQ-HARNESS-TEST-MATRIX-QWEN, REQ-HARNESS-PORTABILITY-CHECKLIST, REQ-HARNESS-SPEC-KIT, REQ-HARNESS-SUPERPOWERS-SCHEMA, REQ-HARNESS-BODAI-SKILL-SCHEMA-PKG, REQ-HARNESS-ACP-INTEGRATION, REQ-HARNESS-AWESOME-COPILOT-SCHEMA.

**Exit criteria:**

- Qwen Code v0.23.4 completes a 10-step end-to-end test (start session → load AGENTS.md → invoke 5 MCP tools across 3 Bodai components → save a reflection → trigger a workflow → exit). Test passes.
- AGENTS.md file is the canonical conventions doc; CLAUDE.md is a symlink. `readlink CLAUDE.md` shows `AGENTS.md`.
- Bodai's existing 197 MCP tools register in Qwen Code without name-prefix collisions (Qwen truncates names >63 chars).
- `HarnessObserver.MCPOnlyObserver` round-trips: a Mahavishnu MCP tool call emits an audit log line that any harness can read.
- ACP integration validated: Qwen Code user can drive Mahavishnu through any ACP client (Zed, JetBrains, Toad) connected to `mahavishnu acp serve` per `docs/plans/2026-07-26-mahavishnu-acp-server.md`.

#### Integration Contract

- **Triggered from**: Existing `.claude/`-locked wrapper layer; Qwen Code users attempting to use Bodai without modification
- **Returns to / updates**: New `docs/architecture/harness-contract.md`; new `docs/schemas/agent-v1.md`; `AGENTS.md` becomes canonical; new Oneiric adapter categories (`memory`, `observer`)
- **Demonstrable by**:
  - `readlink CLAUDE.md` returns `AGENTS.md`
  - `python -c "from oneiric.adapters.memory import MemoryStore"` imports successfully
  - `pytest tests/integration/test_harness_qwen_code.py` passes against Qwen Code v0.23.4
  - `mcp__mahavishnu__pool_route_execute` invoked via Qwen Code CLI completes a real task (round-trip via MCP HTTP)
  - `mahavishnu acp serve` accepts connections from an ACP client (Zed or JetBrains) and drives a workflow (per active plan `2026-07-26-mahavishnu-acp-server.md`)
- **Rollback signal**: `--disable-harness=qwen-code` env var; falling back to in-process path is one env-var flip
- **Observability added**:
  - `mcp__mahavishnu__get_harness_metrics` MCP tool exposes: `harness_active`, `harness_tool_invocations_total`, `harness_memory_writes_total`, `harness_observer_events_total`
  - Per-harness OTel span: `harness.<name>.tool_invoke.duration_ms`

**ACP consolidation note:** REQ-HARNESS-ACP-INTEGRATION does NOT build new ACP code. The active plan `docs/plans/2026-07-26-mahavishnu-acp-server.md` (status: active) already builds `mahavishnu/acp/` — Mahavishnu as an ACP server (stdio JSON-RPC 2.0). Phase 11's role is to **validate** that Qwen Code users (or any ACP-client-using harness) can reach Mahavishnu through the existing ACP server surface via any ACP client (Zed, JetBrains, Toad). If the active ACP plan ships first, Phase 11's validation is trivial; if Phase 11 ships first, it documents the ACP client contract and waits for the active plan to provide the server.

**Security note (from Backslash Security 2026-07-06):** AGENTS.md is injection-vulnerable in some harnesses — adversarial content in a project-local AGENTS.md can exfiltrate credentials via tool calls. Bodai's portable agent loader MUST sanitize instructions on read. See REQ-HARNESS-INJECTION-SANITIZATION.

**Scope discipline:** Phase 11 ships Claude Code (already working) + Qwen Code (validated). Codex CLI, Nanobot, Hermes, OpenClaw are deferred — revisit when their MCP/conventions/memory stabilize. The abstractions (MemoryStore, HarnessObserver, portable agent schema) are the durable win; per-harness adapters can land incrementally after the abstractions exist.

## 6. Required Code Changes

### Oneiric (new adapters)

- [ ] `oneiric/adapters/storage/__init__.py` — register `mirror` provider
- [ ] `oneiric/adapters/storage/mirror.py` — new (~300 LOC)
- [ ] `oneiric/adapters/database/__init__.py` — register `libsql` provider
- [ ] `oneiric/adapters/database/libsql.py` — new (~400 LOC, PEP 735 group `database-turso`)
- [ ] `oneiric/adapters/database/postgres.py` — extend with `read_replica_dsn`/`branch_dsn`/`read_strategy`
- [ ] `oneiric/adapters/replication/__init__.py` — new category
- [ ] `oneiric/adapters/replication/local_to_s3.py` — new (~150 LOC)
- [ ] `oneiric/adapters/replication/local_to_turso.py` — new (~150 LOC)
- [ ] `oneiric/adapters/replication/local_to_neon.py` — new (~150 LOC)
- [ ] `oneiric/adapters/cache/snapshot.py` — new (~100 LOC)
- [ ] `oneiric/adapters/bootstrap.py` — register new providers

### mcp-common (shared schemas)

- [ ] `mcp-common/akosha_schemas/skill_metadata.py` — moved from `akosha/akosha/mcp/skill_schema.py`
- [ ] `mcp-common/akosha_schemas/agent_metadata.py` — moved from `akosha/akosha/mcp/agent_schema.py`

### Dhara (serverless re-architecture)

- [ ] `dhara/dhara/file.py` — replace fcntl locks
- [ ] `dhara/dhara/mcp/server_core.py:141-148` — replace hardcoded FileStorage
- [ ] `dhara/dhara/core/connection.py:408-525` — redesign LRU cache
- [ ] `dhara/dhara/storage/` — cloud primary adapter implementations

### Mahavishnu

- [ ] `mahavishnu/ingesters/otel_ingester.py:41,289,359` — replace direct Akosha imports with Oneiric
- [ ] `mahavishnu/pools/routing_fitness.py` — Turso adapter for KV layer
- [ ] `mahavishnu/mcp/tools/otel_tools.py:289,359` — same
- [ ] `mahavishnu/engines/langgraph_adapter_impl.py` — new (~200 LOC)
- [ ] `mahavishnu/core/adapters/base.py:10-18` — add `LANGGRAPH` enum entry
- [ ] `mahavishnu/core/task_router.py:573-605` — update `TASK_PREFERENCE_ORDERS` for `AI_TASK`
- [ ] `mahavishnu/pools/fitness_analyzer.py` — delete (orphaned duplicate)
- [ ] `mahavishnu/pools/memory_aggregator.py:561` — delete dead `aggregate_metrics` call
- [ ] `mahavishnu/core/events/confidence_ceiling.py:121-128` — delete dead `emit_anomaly` import
- [ ] `mahavishnu/core/bootstrap.py:411-458` — wire `_settle_dhara`
- [ ] `mahavishnu/settle/` — wire `broadcast_settle_transition`
- [ ] `mahavishnu/workers/contract/` — implement `current_tmux` or remove from docstring
- [ ] `mahavishnu/core/task_router.py:758-760` — fix `TaskRouter.route()` `is_available()` bug

### Akosha (strip)

- [ ] `akosha/akosha/mcp/tools/` — delete 22 of 32 tool files
- [ ] `akosha/akosha/mcp/skill_schema.py` — move to `mcp-common`
- [ ] `akosha/akosha/mcp/agent_schema.py` — move to `mcp-common`

### Crackerjack (vestigial cleanup)

- [ ] `crackerjack/ai_fix/*.backup` — delete or move to `docs/historical-records/`
- [ ] `crackerjack/intelligence/` — delete vestigial directory
- [ ] `.claude/skills/crackerjack/SKILL.md` — update `/run` description (drop "AI agent")

### CLAUDE.md (doc sync)

- [ ] `mahavishnu/CLAUDE.md` — sync with REQ-DOCS-001 through REQ-DOCS-006

### EventBridge WAL (Phase 8)

- [ ] `mahavishnu/core/events/eventbridge_wal.py` — new (~80 LOC), wraps `oneiric.adapters.queue.redis_streams`, XADDs envelope JSON to `envelopes:{topic}`
- [ ] `mahavishnu/core/events/eventbridge_consumer.py` — new (~120 LOC), per-instance `XREADGROUP` task, feeds local `EventDispatcher.dispatch`, XACK on success, XADD to `envelopes-dlq:{topic}` on retry exhaustion
- [ ] `mahavishnu/core/events/eventbridge_resolver.py` — extend `resolve_event_publisher()` to spawn the consumer when `settings.eventbridge.wal_enabled=true`
- [ ] `settings/mahavishnu.yaml` — `eventbridge.wal_backend: redis_streams`, `eventbridge.consumer_group: mahavishnu-shared`, `eventbridge.consumer_block_ms: 5000`
- [ ] `docs/ops/eventbridge-wal.md` — operator doc (Redis provisioning, consumer-group config snippets, idempotency requirement, DLQ recovery procedure)

### Audit infrastructure (new scripts)

- [ ] `mahavishnu/scripts/audit_callers.py` — production-callers-of check
- [ ] `mahavishnu/scripts/audit_surface.py` — stale advertised surface check
- [ ] `mahavishnu/scripts/audit_dead_code.py` — cross-component dead-code check

### Harness-agnostic enablement (Phase 11)

- [ ] `docs/architecture/harness-contract.md` — new, 3-section contract (REQ-HARNESS-CONTRACT)
- [ ] `docs/schemas/agent-v1.md` — new, portable agent schema with capability names (REQ-HARNESS-AGENT-SCHEMA)
- [ ] `docs/schemas/skill-v1.md` — new, superpowers-style Skill.md frontmatter (REQ-HARNESS-SUPERPOWERS-SCHEMA)
- [ ] `oneiric/adapters/memory/__init__.py` + `claude_code.py` + `file.py` + `session_buddy.py` — new category, MemoryStore protocol + 3 implementations (REQ-HARNESS-MEMORY-INTERFACE)
- [ ] `oneiric/adapters/observer/__init__.py` + `mcp_only.py` + `claude_code.py` + `noop.py` — new category, HarnessObserver protocol + 3 implementations (REQ-HARNESS-OBSERVER)
- [ ] `AGENTS.md` at repo root — new canonical conventions file (REQ-HARNESS-AGENTS-MD-CANONICAL)
- [ ] `CLAUDE.md` becomes symlink → `AGENTS.md` (REQ-HARNESS-CLAUDE-MD-SHIM)
- [ ] `mahavishnu/cli/manifest_gen.py` + `templates/qwen-settings.json.j2` — manifest generator for Qwen (Codex deferred) (REQ-HARNESS-MANIFEST-GENERATION)
- [ ] `mahavishnu/core/harness_loader.py` — sanitize AGENTS.md content on read (REQ-HARNESS-INJECTION-SANITIZATION)
- [ ] `tests/integration/test_harness_qwen_code.py` — end-to-end validation against Qwen Code v0.23.4 (REQ-HARNESS-TEST-MATRIX-QWEN)
- [ ] `docs/harness-portability.md` — portability checklist (REQ-HARNESS-PORTABILITY-CHECKLIST)
- [ ] `mahavishnu/cli/spec_kit.py` — spec-kit `specify`/`plan`/`tasks` slash commands (REQ-HARNESS-SPEC-KIT)
- [ ] `bodai-skill-schema` PyPI package — net-new, versioned frontmatter + body schema (REQ-HARNESS-BODAI-SKILL-SCHEMA-PKG)

## 7. Validation Matrix

| Tool/Command | Expected outcome | Evidence location |
|---|---|---|
| `python -c "from oneiric.adapters.storage.mirror import MirrorStorageAdapter"` | Imports successfully | CI logs |
| `python -m oneiric.cli --demo list --domain storage` | Shows `provider="mirror"` | stdout |
| `pytest tests/dhara/test_serverless_safety.py` | Passes | CI |
| `grep -rn 'from akosha.storage' mahavishnu/` | Empty | shell exit code 1 |
| `python -c "from mcp_common.akosha_schemas import SkillMetadata, AgentMetadata"` in all 5 repos | Imports successfully in each | per-repo CI |
| `mcp__akosha__discover_tools() \| wc -l` | 9-11 tools | MCP introspection |
| `pytest tests/integration/test_langgraph_smoke.py` | Passes (post-CVE-check) | CI |
| `python scripts/audit_callers.py` | Zero critical violations | stdout |
| `python scripts/audit_surface.py` | Zero critical violations | stdout |
| `python scripts/audit_dead_code.py` | Zero critical violations | stdout |
| `python -c "from mahavishnu.ingesters.otel_ingester import OtelIngester; OtelIngester(settings={'storage': 'turso'})"` | Instantiates without `akosha` import | shell |
| `pytest tests/mahavishnu/test_task_router.py` | Passes after `is_available()` fix | CI |
| `python -c "from mahavishnu.core.events.eventbridge_wal import EventBridgeWal; await EventBridgeWal(settings).init()"` | Initializes with `wal_backend=redis_streams`, lazy-imports `redis` | CI logs |
| `pytest tests/integration/test_eventbridge_wal.py` | Two-process test passes: A emits, B's consumer dispatches to local handler | CI |
| `pytest tests/integration/test_eventbridge_wal_recovery.py` | Crash mid-dispatch; auto-claim re-delivers to surviving instance | CI |
| `pytest tests/integration/test_eventbridge_wal_dlq.py` | Handler exhausting `max_attempts` lands envelope in `envelopes-dlq:*` with retry metadata | CI |
| `mcp__mahavishnu__get_eventbridge_metrics` | Returns non-zero `wal_envelopes_consumed_total` after test workload | MCP introspection |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Oneiric adapter additions cause regressions in components using `LocalStorageAdapter` directly | Medium | New adapters live alongside; default provider unchanged; opt-in via settings |
| LangGraph CVE situation prevents adoption | Medium | Phase 7 gated on CVE check; rollback path is just removing the enum entry |
| `dhara_pusher.py` (Oneiric) was actually planned-future, not dead code | Low | The plan's Phase 4 doesn't touch Oneiric pusher; verify intent before Phase 3-4 execution |
| Mahavishnu's `OtelIngester` direct import cleanup breaks telemetry | Medium | Phase 5 verification: trace round-trip succeeds before deleting direct import |
| Akosha schema move to `mcp-common` requires 4-repo coordination | High | Phase 6 starts with `mcp-common` first, then 5 repos in sequence |
| Turso embedded replica doesn't support concurrent writers | Medium | Document the constraint; route through Postgres (Neon) for write-heavy workloads |
| The audit scripts flag too many false positives and get disabled | Medium | Start with `--warn-only` mode; tighten regexes based on real violations |
| `broadcast_settle_transition` wiring changes WebSocket traffic patterns; downstream consumers break | Low | Verify subscribers exist before wiring; document channel addition |
| Oneiric's `LocalStorageAdapter.init()` `LifecycleError` triggers on first call in cloud-primary mode | Low | Phase 4 verifies the error message; if triggered, fall through to cloud adapter |
| Qwen Code ships a breaking MCP change before Phase 11 ships | Low | Pin to tested version (Qwen v0.23.4); fall back to in-process path via `--disable-harness=qwen-code` |
| AGENTS.md injection bypasses sanitization (REQ-HARNESS-INJECTION-SANITIZATION) | Medium | Adversarial test suite (`tests/test_agents_md_sanitization.py`); log injection attempts; consider allowlist-only mode for untrusted sources |
| Portable agent schema breaks an existing `.claude/agents/` file | Medium | 5-agent pilot validates the migration shape before any auto-migration; per-agent rollback via `git revert` |
| Qwen Code test matrix becomes flaky (Qwen updates break Bodai) | Medium | Pin tested version in CI; matrix runs against fixed v0.23.4, not `latest` |
| spec-kit workflow integration confuses users (spec/plan/tasks overlaps Bodai's existing plan-then-execute) | Low | Phase 11 ships spec-kit integration as opt-in; default workflow remains Bodai's existing template |

## 9. Decision Rule

This plan is "done enough" when:
- Every REQ-* above is implemented OR documented as `deferred` with a trigger condition
- Every Phase's Integration Contract `Demonstrable by` check passes
- Phase 10 re-evaluation surfaces zero new wire-up gaps the audit scripts would catch
- CLAUDE.md matches code (zero `audit_surface.py` critical violations)

If scope pressure forces a cut:
- **Cut first**: Phase 7 (LangGraph) — gated on external CVE situation; can wait
- **Cut second**: REQ-ONEIRIC-NEON — Neon extension is nice-to-have; default Postgres works for now
- **Cut third**: REQ-ONEIRIC-CACHE-SNAPSHOT — cold-start cache hydration is an optimization
- **Never cut**: Phase 1 (wire-up cleanup), Phase 4 (Dhara re-architecture — serverless gate), Phase 8 (EventBridge WAL — serverless gate), Phase 9 (audit infrastructure), and Phase 11 (harness-agnostic enablement — strategic value for non-Claude-Code users) — these are the foundations

## Appendix A — Investigation trail

This plan was generated from a brainstorm session on 2026-09-14 that included:
1. Initial question: "Is Mahavishnu/Bodai worth it?"
2. Refinement: Web search + context7 for 2026 LLM observability/orchestration alternatives
3. Five parallel subagent investigations (design history, adapter architecture, ecosystem integration, durable workers, LlamaIndex vs LangGraph re-evaluation)
4. Oneiric adapter inventory and cloud-local sync patterns research
5. Reading existing plans for context: `REVIEW_serverless.md`, `dhara-outstanding-items-plan.md`, `finish-partial-implementations.md`, `PLAN_INDEX.md`

Subagent reports are not preserved as separate artifacts; their findings are summarized in §4.1 and the REQ table in §4.5.

## Appendix B — Pre-flight checklist before Phase 1 execution

Before starting Phase 1, verify:
- [ ] `2026-04-02-storage-consolidation-and-akosha-role.md` status — verify it's `complete` or `shipped` so this plan can reference it via `related:` without conflict
- [ ] LangGraph CVE situation — re-check Check Point Research publication date; if patch is available, proceed; if not, defer Phase 7
- [ ] Oneiric `dhara_pusher.py` intent — confirm with maintainer whether this is planned-future (Phase 4 should preserve) or dead code (delete)
- [ ] Current Mahavishnu CLAUDE.md — read full to identify any other doc-vs-code drift not covered in §4.3

## Appendix C — Governance doc amendments (apply during Plan-1 execution)

This plan touches three governance docs. The amendments below are the canonical content to merge into each. Reviewers flagged H2 and H3 because the plan didn't include them.

### C.1 — Amendment to `.claude/decisions/wire-up-contract.md`

Add the following clause under "Integration contract — additional requirements":

```diff
+ ## Integration contract — additional requirements (added 2026-09-14)
+
+ Every REQ in any active plan must carry:
+ 1. **Exact file:line citations** verified against HEAD at plan-promotion time.
+    Citations drift as the code moves; the audit_invariant contract is
+    "file path resolves + line number is within 5 lines of cited position."
+    CI guard test (Phase 9): `pytest tests/test_plan_citations.py` greps
+    every `REQ-XXX-NNN` citation and asserts the file exists and the
+    referenced symbol is near the cited line.
+ 2. **Cross-component imports** must show direction of dependency with
+    an arrow diagram. Akosha → Mahavishnu imports (the inverted case)
+    are forbidden except via MCP/HTTP. Phase 6 verification step.
+ 3. **Governance doc amendments** are part of the REQ delivery, not
+    follow-up work. If a REQ changes a decision in `.claude/decisions/`
+    or `docs/adr/`, the amendment is co-delivered.
```

### C.2 — Amendment to `docs/adr/013-*.md`

Append a "Superseded by" note (or "Amended by" depending on severity):

```diff
+ ## Status
+
+ <!-- legacy status: **Accepted** — see YAML frontmatter -->
+
+ **Accepted with amendment (2026-09-14)**
+
+ The ADR-013 storage consolidation is preserved for the local-disk →
+ single-Postgres-instance path it originally described. The
+ serverless-readiness plan (`docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`,
+ status: active) extends the storage substrate with Oneiric
+ adapter-based selection. ADR-013's "Postgres-only" assumption no
+ longer holds; see ADR 017 (proposed) for the cross-substrate
+ persistence architecture.
```

### C.3 — New ADR `docs/adr/017-oneiric-shared-persistence-substrate.md`

Stub to be written during Plan-1 execution:

```markdown
---
status: proposed
role: canonical
kind: decision
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
decision_date: 2026-09-14
topic: persistence-substrate
---

# ADR 017: Oneiric as the shared persistence substrate for Bodai

## Status

**Proposed** (2026-09-14) — pending review and adoption

## Context

Prior to this ADR, each Bodai component chose its own persistence
stack:
- Mahavishnu: `mahavishnu/ingesters/otel_ingester.py` directly imported
  `from akosha.storage import HotStore` (line 1319 and 8 other
  direct dhara package imports).
- Akosha: bespoke `HotStorageConfig` with hardcoded DuckDB defaults
  (`akosha/akosha/config.py:40-53`).
- Dhara: hardcoded `FileStorage` in `dhara/dhara/mcp/server_core.py:141-148`,
  no cloud primary adapter, fcntl-based locks.
- Session-Buddy: separate `store_reflection` path with its own SQLite.
- Crackerjack: filesystem-based, no persistence layer.

This per-component choice produced three concrete problems:
1. Cross-component imports (Mahavishnu → Akosha) break when either
   repo upgrades independently. The wire-up gap pattern.
2. Serverless deployment requires each component to choose a
   serverless-safe backend; without a shared abstraction, this is
   repeated work and divergent decisions.
3. State sync across cloud and local-first deployments is per-
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

Direct Python imports from one Bodai component into another's
storage layer are forbidden. Cross-component state access goes
through MCP/HTTP or through a shared Oneiric adapter registered
with both components.

## Why Oneiric specifically

- Already shipped (54 built-in adapters, 14 categories).
- Layered config (`oneiric.core.config`) means env-var → YAML →
  settings override works for every Bodai component.
- Adapter registry is the same model for every category; no per-
  category API to learn.
- Local-first reads (memory, sqlite) + cloud-durable writes
  (postgres, redis_streams, S3) are config choices, not code paths.

## Consequences

### Positive

- **Serverless-deployable by configuration.** A Bodai component
  deployed to a serverless platform changes settings, not code.
- **No more cross-component imports.** Phase 5 of this plan
  replaces the 8 direct dhara imports + 1 direct akosha.storage
  import with Oneiric adapter access.
- **State sync is a CLI command.** Phase 3 documents the
  vendor-CLI sync pattern in `docs/ops/state-sync.md`.

### Negative

- **Oneiric becomes load-bearing.** If Oneiric breaks, every
  Bodai component's persistence breaks. Mitigation: Oneiric's
  adapter pattern means most failures are isolated to one
  adapter; the rest of the system continues to function.
- **Refactoring cost.** Components with bespoke storage need
  rewrites. Phase 5 (Mahavishnu), Phase 6 (Akosha), Phase 4
  (Dhara) all depend on this ADR.

## Rejected alternatives

- **Keep per-component persistence, add a thin shared facade.**
  Rejected — adds a layer without removing the underlying
  duplication.
- **Mandate Postgres for everything.** Rejected — locks out
  SQLite-shaped local-first deployments and the Turso-style
  embedded replica pattern.

## References

- `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`
  (status: active) — implements this ADR through Phase 5 (Mahavishnu),
  Phase 4 (Dhara), Phase 6 (Akosha strip + schema consolidation).
- `oneiric/adapters/` — adapter inventory (54 built-ins).
- `.claude/decisions/wire-up-contract.md` — integration contract
  rules this ADR enforces.
```

## Appendix D — Tracked, not adopted

Projects evaluated during the 2026-09-14 brainstorm session that were **not adopted** but are kept here so future reviewers don't re-propose them.

| Project | Repository | Verdict | Reason | Revisit trigger |
|---|---|---|---|---|
| huey | https://github.com/coleifer/huey | Do not adopt | Greenlets, not native async — wraps badly into Mahavishnu's async/await. Heavily overlaps existing pool layer. Single-maintainer risk. | If Mahavishnu's pool layer is replaced wholesale |
| honker | https://github.com/russellromney/honker | Niche only | SQLite NOTIFY/LISTEN extension. Sub-ms wake latency vs ~1-5 ms for asyncio queues. Wrong for cross-instance transport (single-host only). | If in-process latency becomes measured bottleneck |
| RapidFuzz | https://github.com/rapidfuzz/RapidFuzz | Track | Pure compute utility. No Bodai overlap. | If "did-you-mean" or log-cluster triage use case appears |
| taskiq | https://github.com/taskiq-python/taskiq | Do not adopt | Direct competitor to Mahavishnu's pool layer. Adopting = replacing 197 wired MCP tools. Track its broker plugin ecosystem as inspiration. | If Mahavishnu is replaced (not on roadmap) |
| honcho | https://github.com/plastic-labs/honcho | Already in production | Per ADR-014 (Session-Buddy `user_models`). AGPL-3.0 is non-blocking because we use it as a network service. | No action; guardrail against duplicate proposals |
| automate-terminal | https://github.com/irskep/automate-terminal | Defer | 7 stars, single maintainer. Would give terminal adapter registry cross-terminal coverage. Dependency risk on critical-path dep not yet worth it. | If terminal coverage becomes a measured blocker |
| autowt | https://github.com/irskep/autowt | Personal tool | Git worktree CLI. Useful for multi-Bodai-repo workflow. Install separately, no ecosystem integration. | n/a (personal-tool, not infra) |
| lazy-tmux | https://lazy-tmux.xyz/ | Insufficient data | GitHub repo 404; only the website confirmed. TUI for tmux sessions. | If a concrete tmux-side TUI gap emerges |
| wse | https://github.com/silvermpx/wse | Track | Rust-powered WebSocket server (wse-server 2.4.1, MIT, Py3.12+). 4.7M deliveries/s claimed. Mahavishnu already has WebSocket on port 8690; replacing it has no current justification. | If WebSocket traffic ever grows past single-process capacity |
| rsloop | https://github.com/RustedBytes/rsloop | Track | PyO3 asyncio event loop replacement (io_uring/IOCP/kqueue). 203 stars, Apache 2.0, Py3.10+. Drop-in alternative to uvloop. | If uvloop becomes unmaintained or blocks Python 3.15 |

## Appendix E — 8-reviewer synthesis (cross-reference)

The full synthesis is in Rev-9 above. Summary table for quick reference:

| Severity | Count | Examples |
|---|---|---|
| CRITICAL | 7 | LangGraph CLI default broken; fitness analyzer inverted cross-deps; `schedule_put` fire-and-forget |
| HIGH | 6 | §1-§9 vs Revisions contradiction; wire-up-contract.md diff not shown; ADR 017 missing |
| MEDIUM | 5 | Various |
| CONVERGENT PATTERNS | 3 | file:line citation drift; governance doc gaps; wire-up-vs-production drift |

Reviewers (all returned): Oneiric specialist, Akosha specialist, Mahavishnu specialist, DevOps troubleshooter, Architecture Council, Claude Environment auditor, Observability Incident Lead, General Purpose (broad plan completeness).

## Appendix F — Post-promotion review findings (deferred)

Two reviewers were dispatched 2026-09-14 after `status: draft → active` to do a final pass before implementation. Both returned with findings. Two were applied inline (duplicate REQ-LANGGRAPH-ROUTING removed from §4.5, REQ count corrected to 56 unique IDs). The rest are deferred — the user explicitly paused implementation 2026-09-14 to review these before deciding whether to apply them now or roll them into a follow-up plan.

**Reviewers:**
- Architecture Council (governance + structural)
- General Purpose (fresh-eyes implementation feasibility)

### F.1 — MUST-FIX (blocks implementation, deferred)

| # | Finding | Source | Why deferred |
|---|---|---|---|
| F.1.1 | §5 Phase 3 task list still includes `REQ-ONEIRIC-MIRROR` and `REQ-ONEIRIC-REPLICATOR` which Rev-4 marked as Closed | general-purpose | Mechanical fix; can be applied at any time before Phase 3 starts |
| F.1.2 | Phase 8 missing consumer lifecycle details (graceful shutdown on SIGTERM, startup ordering vs `bridge.emit()`, Redis-unreachable behavior) | general-purpose | Affects the Phase 8 deliverable list; needs design discussion, not just text edit |
| F.1.3 | Phase 8 missing `_id` propagation contract (header vs field in XADD JSON) | general-purpose | Affects handler idempotency example; needs design decision |
| F.1.4 | Appendix B missing Phase 8 pre-flight (Redis ≥6.2, `MAXLEN ~ 1000000` default policy, `.env.test` integration-test assumption) | general-purpose | One-line additions to Appendix B; trivial |
| F.1.5 | §9 cut list omits load-bearing phases — Phase 4 (Dhara re-architecture) and Phase 8 (EventBridge WAL) are equally load-bearing as Phase 1 + Phase 9 | architecture-council | Re-rationale the cut list; one-paragraph edit |
| F.1.6 | §9 Decision Rule is non-actionable — no severity threshold, no per-tier action | architecture-council | Replace with severity tiers (exit-criteria-breaking / scope-additive / cosmetic) + per-tier action (halt-and-replan / add-REQ-and-continue / document-and-proceed) |
| F.1.7 | Cross-component imports rule wired to wrong phase — Appendix C.1 says Phase 6 verification, but the imports are removed in Phase 5 (`REQ-MAHAVISHNU-IMPORTS`) | architecture-council | Reassign the verification step to Phase 5 exit criteria |
| F.1.8 | ADR 017 contains citation drift — references `mahavishnu/ingesters/otel_ingester.py` "line 1319 and 8 other direct dhara package imports" but §6 cites lines 41, 289, 359 (3 sites, not 1+8) | architecture-council | The exact bug Rev-9 was supposed to fix; must be corrected before ADR 017 is ratified |

### F.2 — SHOULD-FIX (improves execution confidence, deferred)

| # | Finding | Source |
|---|---|---|
| F.2.1 | Audit invariant tolerance too permissive — "5 lines" should be 0-2 lines; 5 masks the exact class of bug Rev-9 flagged | architecture-council |
| F.2.2 | ADR 013 amendment lacks cross-reference to `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md` (one of the plan's `related:` entries) | architecture-council |
| F.2.3 | Phase 6.1 pre-step has circular dependency — REQ-PHASE-6.1-PRE-STEP refers to "agents_catalog.md Appendix C" which doesn't exist; Appendix C is governance docs | architecture-council |
| F.2.4 | Cut ordering lacks rationale — §9 ranks REQ-ONEIRIC-NEON vs REQ-ONEIRIC-CACHE-SNAPSHOT without saying why | architecture-council |
| F.2.5 | Phase 1 has no per-REQ contracts (10 REQs without concrete Demonstrable-by) | general-purpose |
| F.2.6 | Phase 8 fallback adapter gap — "fall back to cloudtasks/kafka" claim without code path or settings key | general-purpose |

### F.3 — DELETE-CANDIDATE (cut to ship faster, deferred)

| # | Finding | Source |
|---|---|---|
| F.3.1 | §6 (Required Code Changes) entire section is stale — still lists `mirror.py`, `libsql.py`, `replication/` directory that Rev-1/Rev-2 explicitly removed | general-purpose |
| F.3.2 | Phase 7 (LangGraph) already in cut-first list per §9 Decision Rule; defer to its own plan post-CVE-clarification | general-purpose |

### F.4 — MISSING (would surprise during execution, deferred)

| # | Finding | Source |
|---|---|---|
| F.4.1 | No PR/branch strategy — multi-repo coordination (Phase 4 Dhara, Phase 5 mcp-common cross-imports) needs sequencing docs | general-purpose |
| F.4.2 | No rollout toggle for WAL — binary `wal_enabled` per settings, but no canary/staged rollout | general-purpose |
| F.4.3 | `envelopes-replay:*` stream mentioned in DLQ recovery procedure but never created in deliverables | general-purpose |
| F.4.4 | No shutdown handler for the consumer task — long-running task without signal handling holds pending entries | general-purpose |
| F.4.5 | No Oneiric version pin — assumes `redis_streams` queue adapter exists; no `oneiric>=X.Y` constraint listed in Phase 8 pre-flight | general-purpose |
| F.4.6 | Metric collision — existing EventBridge metrics (if any) vs. new `wal_*` metrics; no reconciliation note | general-purpose |
| F.4.7 | Phase 10 (re-evaluation) has no REQ — could use `REQ-RE-EVALUATION-001` to make the "re-run 5 investigations" work explicit | architecture-council |
| F.4.8 | Process REQs (REQ-CONFIG-001, REQ-DOCS-001) lack audit-invariant treatment — C.1 invariant only applies to file:line, not command exit code | architecture-council |

### F.5 — Total deferred: 22 findings

- MUST-FIX: 8
- SHOULD-FIX: 6
- DELETE-CANDIDATE: 2
- MISSING: 8 (8 from re-review + 2 already-applied)

**Net for implementation pause:** the plan is execution-ready for Phase 1-3 (wire-up cleanup, CLAUDE.md sync, Oneiric adapter additions — all well-specified). Phases 4-8 require the deferred findings to be applied first; the user will decide which to roll into a follow-up plan vs apply now.

### F.6 — Phase 11 added post-promotion (2026-09-14)

The user explicitly added Phase 11 (Harness-agnostic enablement) to this plan rather than spinning a separate plan. The decision was driven by:

1. **Strategic positioning.** Bodai's value proposition includes "harness-agnostic orchestration." The serverless-readiness plan was the natural place to also generalize the wrapper layer.
2. **Already-verified target.** Qwen Code v0.23.4 (released 2026-09-14, the same day this phase was added) is ready to target. Codex CLI 0.155.0-alpha.4 verified but deferred per user decision 2026-09-14.
3. **Reuse of cross-cutting infrastructure.** Phase 11's portable abstractions (MemoryStore, HarnessObserver, portable agent schema) share audit, MCP, and settings-loading code with the rest of the plan.

**Phase 11 additions (14 new REQs):**

| REQ | What |
|---|---|
| REQ-HARNESS-CONTRACT | `docs/architecture/harness-contract.md` — 3-section contract |
| REQ-HARNESS-AGENT-SCHEMA | `docs/schemas/agent-v1.md` — capability-named portable schema |
| REQ-HARNESS-MEMORY-INTERFACE | `oneiric.adapters.memory` — MemoryStore protocol + 3 impls |
| REQ-HARNESS-OBSERVER | `oneiric.adapters.observer` — HarnessObserver protocol + 3 impls |
| REQ-HARNESS-AGENTS-MD-CANONICAL | New `AGENTS.md` at repo root |
| REQ-HARNESS-CLAUDE-MD-SHIM | `CLAUDE.md` → symlink to `AGENTS.md` |
| REQ-HARNESS-MANIFEST-GENERATION | Generator for Qwen `.qwen/settings.json` (Codex deferred) |
| REQ-HARNESS-INJECTION-SANITIZATION | Sanitize AGENTS.md content on read (Backslash Security 2026-07-06 finding) |
| REQ-HARNESS-TEST-MATRIX-QWEN | `tests/integration/test_harness_qwen_code.py` |
| REQ-HARNESS-TEST-MATRIX-CODEX | **(deferred 2026-09-14)** Codex end-to-end test |
| REQ-HARNESS-PORTABILITY-CHECKLIST | `docs/harness-portability.md` |
| REQ-HARNESS-SPEC-KIT | Adopt `github/spec-kit` Spec/Plan/Tasks loop |
| REQ-HARNESS-SUPERPOWERS-SCHEMA | Adopt superpowers `Skill.md` frontmatter shape |
| REQ-HARNESS-BODAI-SKILL-SCHEMA-PKG | Publish net-new `bodai-skill-schema` PyPI package |
| REQ-HARNESS-ACP-INTEGRATION | Integrate Agent Client Protocol (Apache 2.0, 4.2k stars, maintained by Zed/JetBrains/OpenHands/GitHub/Pydantic) as the portable agent↔client transport |
| REQ-HARNESS-AWESOME-COPILOT-SCHEMA | Mirror github/awesome-copilot's `agents/<n>/agent.md` + `skills/<n>/SKILL.md` + `plugins/<n>/plugin.json` directory shape |

**Research findings applied (2026-09-14):**

- **Qwen Code v0.23.4** — MCP fully supported (stdio + HTTP/SSE + OAuth); reads both AGENTS.md and CLAUDE.md; hooks first-class; subagents with "agent board" sharing
- **Codex CLI 0.155.0-alpha.4** — verified 2026-09-14; **deferred** per user decision. Re-evaluate after Qwen Code integration ships.
- **Nanobot** — Too thin (4k LoC, skill-based memory); wait until memory/conventions stabilize
- **Hermes / OpenClaw** — No current MCP-first CLI product; skip

**Shared-skill/agent packages evaluated (2026-09-14):**

| Package | Verdict |
|---|---|
| **Agent Client Protocol (ACP)** at github.com/agentclientprotocol/agent-client-protocol | **Integrate** — only credible open JSON-RPC transport for agent↔client. Maintained by Zed/JetBrains/OpenHands/GitHub/Pydantic. Apache 2.0, 4.2k stars, 2,230 commits. **This is the load-bearing reference for Phase 11's transport layer.** |
| `agents.md` convention | **Adopt** — Linux Foundation / 60k+ projects. No formal schema needed; just markdown. |
| `github/spec-kit` | **Integrate** — Spec/Plan/Tasks loop maps cleanly to Bodai's plan-then-execute |
| `obra/superpowers` | **Integrate** — Closest existing skill-package format with portable frontmatter; ships plugin scaffolds for Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot CLI, Hermes, etc. |
| `github/awesome-copilot` (39k stars, MIT) | **Reference** — `agents/<n>/agent.md` + `skills/<n>/SKILL.md` + `plugins/<n>/plugin.json` directory shape is the de-facto skill packaging convention |
| `bodai-skill-schema` (net-new PyPI) | **Adopt** — No equivalent exists; Bodai fills the gap |
| `modelcontextprotocol/skill-registry` (RFC v0.4) | **Track only** — too early to depend on |
| OpenHands Software Agent SDK | **Reference** — ACP integration is the right primitive to depend on, not the agent abstraction |
| `agent-skills` / `agentskills-fs` / `skillmeta` / `agent-skill-search` (PyPI) | **Skip** — all experimental, no dominant schema |
| `@anthropic-ai/claude-agent-sdk` | **Skip** — proprietary Commercial Terms |
| Continue.dev | **Skip** — archived, acquired by Cursor |
| Aider | **Reference only** — confirms `AGENTS.md` portability |
| Agent Spec arXiv (2510.04173) | **Reference only** — paper-stage |
| `everything-claude-code` | **Skip** — Claude-specific |
| PyPI `agent-schema`/`skill-schema` | **Skip** — don't exist as portable schemas |
| Homebrew `agents-md` | **Skip** — doesn't exist; only individual tool formulae |
| Bodai's own `akosha_list_ecosystem_skills` | **Already the substrate** — Phase 4 federation |
