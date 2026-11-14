---
status: active
role: canonical
kind: decision
date: 2026-11-10
last_reviewed: 2026-11-10
superseded_by: null
blocks_on: []
related:
  - "docs/adr/005-memory-architecture.md"
  - "docs/adr/017-oneiric-shared-persistence-substrate.md"
  - "docs/adr/019-legacy-mcp-server-decommissioning.md"
  - "docs/architecture/MEMORY_ARCHITECTURE.md"
  - "docs/decisions/2026-10-15-unified-event-bus-wrapper.md"
  - "docs/decisions/2026-10-21-otel-substrate-port-ownership.md"
  - "docs/decisions/2026-10-23-otel-substrate-spec-corrections.md"
decision_date: 2026-11-10
topic: memory-architecture
---

# ADR 020: Bodai ecosystem memory ownership and interoperability

## Status

**Active** on 2026-11-10. This ADR is the target architecture and
coordination contract. Its normative rules describe the target; the current
state and migration exceptions are called out separately below.

ADR 005 is historical. It proposed a universal Mahavishnu memory façade that
was never implemented. The Bodai ecosystem instead has several useful memory
and persistence capabilities, each optimised for a different kind of truth.

## Context

The Bodai ecosystem has two related but different needs:

1. **Operator continuity** — remembering what Les decided, prefers, values,
   and where work was left across tools and conversations.
2. **Ecosystem intelligence** — retaining session evidence, workflow results,
   traces, code context, quality findings, routing outcomes, and durable
   component state so the system can search, learn, and improve.

Treating these as one database creates the wrong ownership model. Treating
each component as an isolated memory creates duplication, drift, and lost
provenance. The goal is therefore a symbiotic memory system: distinct owners,
shared identifiers and contracts, asynchronous projections, and federated
retrieval with evidence attached.

The six core repositories are Mahavishnu, Akosha, Session-Buddy, Crackerjack,
Oneiric, and mcp-common. The legacy standalone MCP server is not part of the
core fleet, per ADR 019.

Bodai Kit is the operator-facing continuity layer alongside the six-repository
core fleet. It is not a seventh fleet repository and does not own the
ecosystem's raw transport or operational stores.

This ADR complements, rather than replaces, ADR 017. Oneiric is the shared
persistence and transport substrate, but it does not make every physical
table or semantic record globally owned by Oneiric. A component may own a
domain schema while using Oneiric's adapter boundary for persistence. The
owner in this ADR means semantic and lifecycle ownership: meaning, allowed
mutations, retention, deletion, and external contract. Oneiric may physically
persist or deliver records owned by another component.

### Current state and migration boundary

The target rules below are not a claim that every path has already migrated.
At the time of this ADR:

- Mahavishnu still has local workflow/event and observability paths, including
  transitional stores documented in `MEMORY_ARCHITECTURE.md`.
- Oneiric EventBridge is the authoritative transport/envelope path adopted by
  Mahavishnu's wrapper layer, while legacy publisher interfaces remain during
  staged migration ([unified EventBus decision](../decisions/2026-10-15-unified-event-bus-wrapper.md)).
- Akosha's `spans_substrate` is the canonical OTel span store. Any remaining
  Mahavishnu OTel conversation/local records are transitional or derived and
  are not authoritative semantic memory.
- ADR 017's adapter migration remains a target for paths still using bespoke
  persistence. Those exceptions must carry an owner, current backend, target
  adapter, and migration plan in the owning implementation plan.

Normative `must` statements in this ADR apply to new cross-component paths and
to migrated paths; transitional paths must expose their exception and
authoritative/derived status rather than silently presenting target state as
current state.

| Current path | Semantic owner | Current backend | Target adapter | State | Migration authority |
|---|---|---|---|---|---|
| Mahavishnu workflow results | Mahavishnu | local KV plus mirror | Oneiric KV/database | authoritative for workflow state, transitional backend | `docs/plans/2026-11-01-control-plane-consolidation.md`, Gate B |
| Mahavishnu async dead-letter files | Mahavishnu | local files | Oneiric queue/DLQ | authoritative recovery record, transitional backend | `docs/decisions/2026-10-15-unified-event-bus-wrapper.md`, legacy cleanup path |
| Mahavishnu OTel conversation records | Akosha owns OTel data contract, query surface, and projections; Oneiric owns physical substrate | Mahavishnu DuckDB/pgvector path | Akosha `spans_substrate` via Oneiric boundary | transitional/derived, not canonical | `docs/decisions/2026-10-21-otel-substrate-port-ownership.md`, OTel implementation plans |
| Bodai EventBridge queue and offsets | transport/projection owner | local queue/state files | Oneiric EventBridge queue and consumer offsets | transitional delivery buffer | `docs/decisions/2026-10-15-unified-event-bus-wrapper.md`, wrapper migration |

Physical persistence and semantic ownership are separate. The semantic owner
controls meaning, external reads, correction, deletion, and retention policy;
the substrate owner controls adapter lifecycle, durability, and delivery.
During migration, the table's stated authoritative/derived status wins over a
legacy document's generic storage description.

## Decision

### 1. Assign one canonical owner to each kind of information

| Component | Canonical responsibility | Must not become |
|---|---|---|
| **Bodai Kit** | Operator-centric continuity: durable decisions, preferences, relationships, handoffs, reviewed lessons, and behavioural context across tools | A raw telemetry archive, project database, or automatic dump of every session |
| **Mahavishnu** | Control-plane state: workflow identity, results, pool/worker state, routing decisions, audit/dead-letter state, and coordination of memory reads and writes | The long-term semantic memory for the whole ecosystem |
| **Session-Buddy** | Session evidence: raw conversation turns, distilled reflections, project-scoped history, provenance, and code/session context | The authoritative store for task execution state or personal continuity |
| **Akosha** | Analytical and semantic intelligence: searchable embeddings, entities, patterns, traces, cross-project relationships, and derived analytics | The source of truth for operational workflow state |
| **Oneiric** | Shared persistence substrate: adapter selection, durable objects, databases, caches, queues, vector backends, configuration, and lifecycle primitives | The place where every semantic memory decision is made, or a substitute for domain ownership |
| **Crackerjack** | Quality and engineering learning: validation evidence, findings, skill knowledge, and quality outcomes | A second workflow orchestrator or a general-purpose conversation store |
| **mcp-common** | Shared schemas, authentication, transport, telemetry, and protocol contracts used by the other components | An independent memory database |

This extends the ownership model already documented in
`docs/architecture/MEMORY_ARCHITECTURE.md`: Mahavishnu routes memory work and
persists operational state, while long-term ecosystem memory is distributed
across Session-Buddy, Akosha, Oneiric, and Crackerjack.

### 2. Make overlap intentional and typed

The same event or lesson may be represented in multiple stores, but each copy
must have a different purpose and an explicit relationship to the source:

- Session-Buddy may retain the raw conversation and a reflection.
- Akosha may index the reflection and derive entities or patterns.
- Mahavishnu may retain the workflow result and execution evidence.
- Crackerjack may retain the validation outcome or reusable skill lesson.
- Bodai Kit may promote a reviewed, stable decision into operator continuity.
- Oneiric may persist the durable records and delivery machinery behind those
  components, without becoming their semantic owner.

These are projections, not unconstrained bidirectional replication. A
projection must identify its source, schema version, content hash, and
supersession relationship so that duplicates can be joined, updated, or
forgotten without guessing.

### 3. Establish a shared memory and provenance envelope

Every cross-component memory-bearing event or projection should carry, where
applicable:

```text
event_id          globally unique idempotency key
source_component component that first observed or authored the record
owner_component   canonical semantic owner of the record
project           repository or project scope
workflow_id       Mahavishnu workflow identity, when applicable
session_id        harness/session identity, when applicable
memory_id        source memory/reflection identity, when applicable
event_time        when the source event occurred
observed_at       when the receiving component observed it
schema_version   version of the payload contract
content_hash      stable duplicate and integrity key
sensitivity       scope and privacy classification
supersedes        prior record or projection, when applicable
```

This is a memory-projection profile of the existing `EventEnvelope`, not a
second top-level wire envelope. `EventEnvelope` remains the transport
envelope: `event_id`, `event_type`, `version`, `timestamp`, `source`,
`correlation_id`, `causation_id`, `payload`, and `metadata`. The fields above
map as follows:

| Memory-projection field | EventEnvelope mapping |
|---|---|
| `event_id` | `EventEnvelope.event_id` |
| `source_component` | `EventEnvelope.source` |
| `schema_version` | `EventEnvelope.version` |
| `event_time` | `EventEnvelope.timestamp` |
| `workflow_id`, `session_id`, `memory_id`, `owner_component`, `project`, `content_hash`, `sensitivity`, `supersedes` | typed fields in `payload` or `metadata`, defined by the mcp-common memory-projection contract |
| `observed_at` | receiver/projection metadata, set by the consumer and never substituted for `event_time` |

mcp-common owns the versioned memory-projection payload schema, field types,
requiredness, sensitivity values, tombstone shape, and compatibility rules.
Oneiric owns transport and delivery metadata for EventBridge. Mahavishnu's
existing envelope wrappers remain compatibility adapters, not a competing
canonical schema. On the wire, Oneiric EventBridge carries the
`EventEnvelope`; Mahavishnu `canonical.py` and `envelope.py` convert at the
Mahavishnu boundary; the memory-projection profile is the typed payload or
metadata contract consumed by mcp-common-aware producers and consumers. The
migration sequence is: publish the mcp-common contract,
add producer/consumer mapping tests, install it at the workflow/session
boundary, then remove any local projection-envelope definitions once all
consumers accept the shared major version.

The initial contract artifact is `mcp_common/contracts.py` in mcp-common,
version `memory-projection/1.0.0`, with mapping tests in
`mcp-common/tests/test_contracts.py`. Until that artifact is published, new
cross-component paths must use the existing EventEnvelope fields and carry
the proposed profile fields in `payload`/`metadata` exactly as mapped above;
they must not claim profile compatibility.

Components may add domain fields, but they must not silently rename or
reinterpret the shared fields.

The envelope is not required on every local implementation detail or every
telemetry attribute. It is required at a cross-component boundary where a
record, outcome, projection, or promotion is transferred or referenced.

### 4. Prefer append-and-project over distributed transactions

Critical writes remain local to their canonical owner. Cross-component
delivery is asynchronous, idempotent, observable, and replayable:

- A Mahavishnu workflow must succeed or fail based on its own authoritative
  state, not on Session-Buddy or Akosha availability.
- Outboxes, bounded local buffers, or Oneiric-backed queues may bridge
  outages, but delivery loss must be visible through metrics and health
  surfaces.
- Consumers deduplicate by `event_id` or `(source_component, content_hash)`.
- Every projection reports its source and delivery status.
- Destructive or privacy-sensitive changes use explicit ownership-aware
  commands, not blind replication.

The projection ledger is owned by the component that owns the projection
boundary. For the first workflow/session slice, Mahavishnu owns the ledger
record and reconciliation command; mcp-common owns its schema; Oneiric/Event-
Bridge carries delivery; each consumer owns applying or rejecting its local
projection. A ledger row contains `event_id`, source, target, owner,
`content_hash`, schema version, status, attempt count, first/last attempt,
last error, target identifier, and supersession/deletion state.

Delivery semantics are explicit: producer outbox/buffer ownership belongs to
the producer; consumer acknowledgement/offset belongs to the consumer;
transport retry and dead-letter handling belongs to Oneiric/EventBridge;
replay selection and reconciliation belongs to the projection-ledger owner.
At-least-once delivery is expected, ordering is guaranteed only within a
declared stream key, duplicates are harmless, and a failed derived projection
does not change authoritative source success. An authoritative write failure
is reported as failed or uncertain and cannot be reported as successful merely
because a projection was delivered.

Transport failures belong in the Oneiric/EventBridge transport DLQ. A
projection-application failure belongs in the Mahavishnu projection ledger
and its projection DLQ. A handler failure after transport delivery is a
projection failure for ownership purposes, even where the current wrapper
records it in Mahavishnu's `dead_letter_queue.py`; that file is the
transitional projection-DLQ implementation, not a third authority. The
existing Mahavishnu async dead-letter file remains a transitional local
recovery record until that migration completes. Replay
of a transport failure republishes the original event with the same
`event_id`; replay of a projection rebuilds the target from the original event
and records a new attempt, not a new source event. Mahavishnu authorises
replay, consumers advance offsets only after applying or recording a terminal
rejection, and replay must converge the ledger to `projected`, `rejected`, or
`superseded`. DLQ retention follows the owning source's deletion policy and
must be visible before cleanup.

### 5. Define a promotion path from evidence to continuity

The default direction for learning is:

```text
session / workflow evidence
        ↓
Session-Buddy capture and reflection
        ↓
Akosha indexing and relationship discovery
        ↓
Mahavishnu / Crackerjack outcome validation
        ↓
reviewed promotion
        ↓
Bodai Kit durable continuity
```

The lifecycle is `captured → derived → candidate → reviewed → promoted`,
with terminal `rejected` and `superseded` states. Capture is written by the
source owner; derivation is written by an approved indexer; only an explicit
promotion candidate may enter review; Bodai Kit owns the review decision for
operator continuity. `revise` creates a new candidate linked by `supersedes`,
`forget` emits a tombstone, and a rejected candidate may be reconsidered only
as a new candidate with a new review decision. Each decision preserves source,
reviewer, reason, scope, and supersession links. Indexing, validation, or
successful replay does not by itself authorise promotion.

Promotion into Bodai Kit must be selective and reviewable. Raw turns,
telemetry, speculative associations, and transient failures must not become
operator memory automatically merely because they were indexed elsewhere.
Conversely, a stable Bodai decision may be exported as an operator-neutral
constraint or project fact when another component needs it, with privacy and
scope preserved.

### 6. Provide federated retrieval, not a universal memory façade

There should be one discoverable retrieval experience, but not one store or
one semantic owner. A future Mahavishnu or shared retrieval tool may fan out
to the owning components and merge results only when it preserves:

- source and owner attribution;
- record type and freshness;
- project/session/privacy scope;
- confidence and whether the result is observed or derived;
- links back to the underlying record;
- partial-failure and stale-result indicators.

Queries should route by intent: operator continuity to Bodai Kit, session
evidence to Session-Buddy, semantic relationships and traces to Akosha,
workflow state to Mahavishnu, quality findings to Crackerjack, and durable
object/configuration lookup to Oneiric.

### 7. Make the system observable as a system

The ecosystem must measure more than individual service health. The shared
memory contract should expose:

- capture, projection, deduplication, promotion, and replay counts;
- queue age, delivery lag, retry count, and dead-letter count;
- projection freshness and source-to-owner lineage;
- search fan-out latency, partial failures, and result provenance;
- duplicate and conflict rates;
- privacy/scope violations and rejected writes;
- whether a component is serving authoritative, derived, stale, or degraded
  data.

The existing Oneiric/EventBridge/OTel substrate is the preferred path for
these signals. Observability records must describe memory operations without
becoming another semantic memory store.

For OTel specifically, Akosha owns the OTel data contract, canonical query
surface, and projections over the append-only `spans_substrate`; Oneiric owns
the physical persistence substrate and transport. This is the receiver and
storage arrangement established by the OTel substrate decisions, not a claim
that Akosha owns all ecosystem memory or that every Bodai memory must become
an OTel span. OTel spans are observability evidence unless explicitly promoted
through the memory lifecycle.

### 8. Make correction and deletion first-class

The semantic owner authorises correction, forget, and deletion for its record.
The owner emits an authenticated tombstone carrying the source identity,
content hash, reason/scope, and supersession or deletion relation. Projection
owners acknowledge `applied`, `already_absent`, `deferred`, or `rejected`; a
deferred or rejected acknowledgement remains visible in the ledger and health
surface. Consumers remove or invalidate local records, embeddings, caches,
search indexes, dead letters, and derived projections within their declared
retention boundary. Backups and legal-retention exceptions must be reported
explicitly rather than presented as deleted. A correction never silently
creates a competing owner: the source owner's supersession chain wins.

The owner authenticates the request through the component's existing write
permission and records actor, request id, reason, and requested scope. The
projection ledger assigns each target a deadline and retry policy; an
unavailable consumer remains `deferred` and blocks final completion until it
acknowledges or the owner records an approved retention exception. Backup
copies receive the same tombstone and report `pending`, `applied`, or
`retained-by-policy`; no component may report global deletion while a required
target is still pending.

### 9. Terms used by this ADR

- **Memory-bearing event:** an event that transfers or references a record,
  outcome, reflection, decision, or projection that another component may
  retain or retrieve; ordinary telemetry attributes are excluded.
- **Projection boundary:** the producer/consumer hand-off where one component
  creates or updates a representation owned by another component.
- **Semantic owner:** the component that controls meaning, lifecycle,
  correction, deletion, retention, and external read semantics.
- **Derived:** computed from another record and reproducible from its source;
  it is not authoritative when the source is available.
- **Sensitivity:** the approved privacy/scope classification carried by the
  mcp-common profile and enforced by every consumer.
- **Target identifier:** the consumer's stable identifier for the projected
  record, used by the ledger for idempotent reconciliation.
- **Operator-neutral constraint:** a scoped fact exported without personal
  identity or private context, only when the owner authorises that export.

## Improvements and implementation order

The following are the highest-leverage improvements toward this architecture:

1. **Publish the ownership matrix.** Keep the table above synchronised with
   the living memory architecture and each component's tool catalog.
2. **Publish the envelope profile.** Add the versioned mcp-common
   memory-projection model and its mapping/compatibility tests to
   `EventEnvelope`.
3. **Build an idempotent projection ledger.** Mahavishnu owns the first
   workflow/session ledger and replay command; record source event, target,
   status, attempt count, last error, target identifier, and deletion state so
   replay and reconciliation are safe.
4. **Separate raw, derived, and promoted records.** Make the state transition
   explicit in Session-Buddy, Akosha, and Bodai Kit integrations.
5. **Add federated retrieval with evidence.** Start with a narrow query broker
   for workflow/session/quality questions; do not hide partial failures or
   flatten all results into an untyped list.
6. **Close the feedback loop.** Link Crackerjack validation and Mahavishnu
   workflow outcomes back to the originating session/reflection and the
   Akosha-derived pattern.
7. **Test failure and replay paths.** Exercise duplicate delivery, delayed
   delivery, unavailable consumers, schema evolution, redaction, deletion,
   and recovery from local outboxes.
8. **Use operator review for promotion.** Add explicit keep, revise, forget,
   and supersede semantics wherever ecosystem evidence becomes Bodai
   continuity.

The implementation sequence is: (1) publish/install the Session-Buddy
workflow-link contract, (2) publish the mcp-common memory-projection profile
and EventEnvelope mapping, (3) implement Mahavishnu's projection ledger at the
workflow/session boundary, (4) prove duplicate delivery, replay, partial
failure, correction, and deletion, and only then (5) expand federated search
and Bodai promotion. The first slice exits only when a duplicate converges,
replay converges, source/owner lineage survives, pending/failed/replayed
statuses are visible, and a test tombstone reaches every declared projection.

## Consequences

### Positive

- Each system can be optimised for its real workload without pretending to be
  the whole memory system.
- Redundancy becomes useful evidence and projection rather than accidental
  duplication.
- Failures in a secondary memory or analytics service do not block core
  orchestration.
- Search results can be joined across the ecosystem without erasing source,
  freshness, or uncertainty.
- Operator memory stays smaller, more trustworthy, and more private than a
  dump of all project telemetry.

### Negative

- The ecosystem must maintain contracts, projections, and reconciliation
  tooling across several repositories.
- Some queries will be eventually consistent or partially degraded.
- Promotion and privacy review add deliberate friction before evidence becomes
  durable operator continuity.
- Oneiric and the event/provenance substrate become important shared
  dependencies, so their compatibility and health require fleet-level tests.

## Rejected alternatives

### One universal memory database

Rejected. It would combine personal continuity, raw session evidence,
operational state, semantic analytics, and quality knowledge under incompatible
retention and authority rules.

### Full bidirectional replication

Rejected. It creates conflict resolution and deletion problems without making
any component the clear owner of a fact.

### Automatic promotion of all indexed content into Bodai Kit

Rejected. Indexing is not evidence of stability, truth, permission, or
operator intent.

### Direct cross-repository database access

Rejected. Components must use MCP/HTTP, shared contracts, the event spine, or
Oneiric adapters rather than importing another component's storage internals.

## References

- `docs/adr/005-memory-architecture.md` — historical universal-façade proposal.
- `docs/adr/017-oneiric-shared-persistence-substrate.md` — shared persistence
  adapter boundary.
- `docs/adr/019-legacy-mcp-server-decommissioning.md` — current six-repository
  core fleet.
- `docs/architecture/MEMORY_ARCHITECTURE.md` — Mahavishnu's living storage
  inventory and cross-component visibility contract.
- `docs/specs/event-envelope-spec.md` — canonical EventEnvelope contract and
  compatibility rules extended by the memory-projection profile.
- `docs/decisions/2026-10-15-unified-event-bus-wrapper.md` — EventBridge
  transport and Mahavishnu compatibility-wrapper decision.
- `docs/decisions/2026-10-21-otel-substrate-port-ownership.md` and
  `docs/decisions/2026-10-23-otel-substrate-spec-corrections.md` — canonical
  OTel ingress/storage and implementation corrections.
- `mahavishnu/pools/memory_aggregator.py` — current best-effort Session-Buddy
  synchronization and local fallback behaviour.
