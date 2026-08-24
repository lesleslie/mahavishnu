---
status: proposed
role: placeholder
date: 2026-08-23
last_reviewed: 2026-08-23
supersedes: []
blocks_on:
  - "015-worktree-and-cache-storage-v4"
related:
  - "015-worktree-and-cache-storage-v4"
  - "015-multi-agent-review"
---

# ADR 016: Phase 4 Streaming tar.zst Evolution

## Status

**Proposed — placeholder filed 2026-08-23.** Skeleton under Phase 3
rollout. Decision, scope, and acceptance criteria for Phase 4 will be
filled in after the Phase 3 7-day monitoring window closes and the
streaming op histograms surface enough telemetry to make a data-driven
call.

## Context

Phase 3 (ADR 015 v4) shipped the streaming `tar.zst` pipeline
end-to-end:

- `serialize_worktree_tar` is now a `@contextmanager` yielding
  `(temp_path, byte_count, sha256)` so the storage adapter can
  atomic-promote after a successful multipart upload.
- `deserialize_worktree_tar` consumes a `chunk_reader` and
  atomic-renames a staging directory onto the target.
- Remote + Local providers both route through a bounded
  `queue.Queue(maxsize=4)` producer/consumer handoff.
- `LocalStorageAdapter` / `S3StorageAdapter` / `GCSStorageAdapter` /
  `AzureBlobStorageAdapter` expose `save_stream` / `load_stream`.
- `streaming_op_total{op,backend,success}` and
  `streaming_op_duration_seconds{op,backend}` give operations a
  per-op view of the new pipeline.

What is not in Phase 3 but is plausibly Phase 4 work, pending
monitoring data:

- **Streaming chunk-size auto-tuning.** Today the chunk size is a
  constant. Phase 4 may switch to an adaptive policy that watches
  `streaming_op_duration_seconds{op="compress"}` and rebalances for
  the 95th-percentile bundle size.
- **Bundle deduplication.** Phase 3 emits one bundle per worktree
  handle. Identical contents across multiple handles produce
  redundant storage; a content-addressed layer may reduce pressure
  on the S3 tier.
- **Cross-region re-streaming.** Operators in multi-region
  deployments may want bundles to stream region-to-region without
  re-encoding. Phase 4 can add a passthrough op kind to
  `StreamingOp`.
- **Compression-codec portability.** Today `zstandard` is the only
  codec. If `lz4` ever becomes operationally desirable, the codec
  selection could move into the `compression-*` PEP 735 group
  family.
- **Streaming-tail validation.** Today integrity is verified after
  the streaming decompress completes. Tail-validated streaming
  would emit `MHV-208` mid-stream and abort the multipart upload
  sooner, reducing S3 abort-rate cost.
- **Multipart abort observability.** Phase 3 records aborts in the
  audit log. Phase 4 may wire them into a dedicated
  `streaming_multipart_abort_total{backend,reason}` counter.

## Decision

**TBD.** To be filled when Phase 4 scope is defined.

## Consequences

### Positive (already realized from Phase 3)

- The Bodai 3.14 ecosystem migration is complete; oneiric,
  mcp-common, dhara, session-buddy, akosha, crackerjack, and
  mahavishnu all pin `requires-python = ">=3.14"`.
- Streaming bundles are observable end-to-end via the new OTel
  histograms and counters.
- The bounded-queue handoff has decoupled slow disk from fast
  network, removing the serverless `/tmp` OOM class of incidents.
- Error codes 209–223 give operators a precise per-failure-mode
  routing signal.

### Pending Phase 4 decisions

- **Bundle deduplication** trades storage for compute (hash +
  dedup table). Operators must decide if the storage savings are
  worth the per-fetch dedup-table lookup.
- **Adaptive chunk sizing** trades CPU (re-tuning) for predictable
  P99 latency. Without monitoring data the policy cannot be set
  defensibly.
- **Tail validation** trades S3 abort-rate cost for slightly higher
  client CPU (incremental SHA-256). The Phase 4 decision hinges on
  observed abort-rate in the 7-day window.
- **Cross-region re-streaming** trades complexity (passthrough op
  kind, region-aware streaming) for reduced egress cost in
  multi-region deployments.

## Open Questions

1. **What is the 95th-percentile bundle size after Phase 3
   rollout?** Drives the chunk-size auto-tuning policy.
2. **What is the S3 multipart abort rate after Phase 3 rollout?**
   Drives the tail-validation decision.
3. **Is there a measurable dedup opportunity?** Phase 4
   deduplication is gated on a content-addressed duplicate-rate
   measurement.
4. **Which regions need re-streaming passthrough?** Cross-region
   re-streaming is only valuable if any two regions see enough
   peer fetches to justify the passthrough op.
5. **Is `zstandard` the long-term codec choice?** If a future
   PEP 735 group (e.g. `compression-lz4`) becomes operationally
   attractive, the codec selection logic may need to grow.
