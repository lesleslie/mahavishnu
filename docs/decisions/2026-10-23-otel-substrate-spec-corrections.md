# Spec corrections found while building the OTLP receiver

**Date:** 2026-10-23
**Context:** PR-A3 of `docs/specs/2026-10-19-bodai-substrate-otel-v7.md`
**Status:** Applied in code. The spec text is not yet amended — see "Still to do".

Six places where the spec's sketch did not survive contact with the
fleet. Five of them share a failure mode: the code as written runs happily
and stores nothing, or raises on a path nobody tests. The sixth is a
blocking startup defect that predates this work.

This follows `2026-10-21-otel-substrate-port-ownership.md`, which
established that the substrate owns `:4317`/`:4318`.

---

## 1. `mcp_common.errors` does not exist

§6 (line 295) and §12 say `LifecycleError` is imported from
`mcp_common.errors`. There is no such module — `mcp_common`'s submodules
are `auth`, `config`, `health`, `profiles`, `traces`, … and none is
`errors`.

`LifecycleError` is in **`oneiric.core.lifecycle`**, and subclasses
`RuntimeError`.

## 2. §5.1's composite UNIQUE constraint is unreachable

The DDL declares both:

```sql
span_id TEXT PRIMARY KEY,
CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
```

A PK on `span_id` alone is strictly **narrower** than a unique on the
pair. Every row that collides on `(trace_id, span_id)` has therefore
already collided on `span_id`, so the PK fires first and
`uq_span_identity` can never be the constraint that rejects anything.

The spec's prescribed `ON CONFLICT (trace_id, span_id) DO NOTHING` names
only the constraint it targets, so a `span_id` collision falls through to
the PK and raises `ConstraintException` — an unhandled exception on the
hot ingest path, in exactly the case the composite key exists to handle.

**Applied:** untargeted `ON CONFLICT DO NOTHING`. Verified against the
pinned DuckDB 2.0.0.dev build that it honours both constraints, and that
`NOT NULL` violations still raise (the table constraint remains a
backstop for rows validation misses).

The DDL itself is left alone: dropping the PK would weaken `span_id`
lookups for the read path, and the untargeted clause already achieves the
spec's stated intent.

## 3. `opentelemetry.exporter.otlp.proto.http` has no servicer

§6's sketch imports `TraceServiceResource` from it. That package is a
**client-side exporter**; it ships no servicer and no ASGI app. The
receiver is the server.

**Applied:** a Starlette app built in the receiver, parsing
`ExportTraceServiceRequest` off the raw protobuf body at `/v1/traces`.

## 4. Service identity is on `ResourceSpans`, not `Span`

A protobuf `Span` message has no `resource` field. Service identity lives
one level up, on the `ResourceSpans`. A mapping that reaches for
`span.resource` finds nothing and falls through to a default — silently
attributing every span in the system to a service named `"unknown"`,
which no read-path filter would match.

**Applied:** `ResourceSpans` attributes are extracted once per resource
and threaded into the per-span mapping.

## 5. A sentinel default makes `REQUIRED_FIELDS` unreachable

`REQUIRED_FIELDS` requires `service_name`, `service_namespace`, and
`span_name`. Filling them with `"unknown"` at the mapping layer satisfies
every required field on every row, so `pre_validate` can never reject
anything, `_dlq_rows` stays permanently empty, and misconfigured producers
write rows nothing can query.

**Applied:** no sentinel. Absence survives into validation and reaches
the DLQ, where an operator sees it.

Separately, `received_at_unix_nano` is stamped from the **receiver's**
clock, never the producer's. §15 calls this the cardinal rule: retention
sweeps on that column, so a producer clock offset either deletes spans
before anything reads them or keeps them past retention. A batch replayed
from a queue hours late is the same failure with no skew at all.

## 6. Alloy's config could not load — pre-existing, now blocking

`otelcol.exporter.debug` sits at "experimental" stability, below Alloy's
minimum "generally-available" level:

```
Error: otelcol.exporter.debug is at stability level "experimental",
       below the minimum allowed stability level "generally-available"
Error: could not perform the initial load successfully
```

This predates PR-A3 and was masked because Alloy had been running under
the old config since April. Moving the ports forced a config reload and
surfaced it.

**Applied:** the trace pipeline is removed from `config.alloy`. It was
dead by construction anyway — `otelcol.exporter.debug` discards traces by
design, which is the entire reason the substrate exists. Alloy is
metrics-only now. Backup at
`/usr/local/etc/grafana-alloy/config.alloy.bak-pre-akosha-cutover`.

---

## Producer repointing is a no-op

§13.1's table says to "repoint the 3 `~/.zshrc` OTLP endpoint exports"
(lines 188, 191, 193), then says "`:4318` stays canonical". Those exports
**already target `:4318`**, which is now the substrate receiver.

Repointing them to `:14318` would send traces to Alloy's discarding
pipeline — strictly worse than leaving them. They were never wrong; they
were pointed at a port a debug exporter happened to occupy.

Only the occupier moved. That is the payoff of resolving port
*ownership* rather than port *numbers*: no coordinated producer rollout,
and no window in which spans are lost.

## Still to do

- Amend the spec (§5.1 DDL note, §6 imports and HTTP sketch, §12, §13.1
  producer table) so the next PR does not re-derive these.
- Observe `bifrost-http` across a flush interval. The spec correctly
  flags its endpoint as uninspectable and warns that a point-in-time
  `lsof` sweep is not a valid producer census. `bifrost-h` is listening
  on `:8471`; whether its spans land is unconfirmed.
- R-6 wiring (construct `FitnessAnalyzer` with `SpanQuery` + declared
  pairs in the lifespan) was blocked on PR-A3 and is now unblocked.