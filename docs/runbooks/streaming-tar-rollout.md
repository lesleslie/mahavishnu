# Streaming tar.zst Rollout Runbook (Phase 3)

This runbook covers operational concerns for the Phase 3 streaming
`tar.zst` worktree bundle rollout shipped under ADR 015 v4. Operators
should reach for this document whenever a streaming-tar symptom shows
up in production, when planning a release of the worktree stack, or
when onboarding a new region.

## Table of Contents

1. [Overview](#overview)
1. [Prerequisites](#prerequisites)
1. [Verification Steps](#verification-steps)
1. [Rollback Procedure](#rollback-procedure)
1. [Known Limitations](#known-limitations)
1. [Escalation Path](#escalation-path)

______________________________________________________________________

## Overview

Phase 3 replaces the Phase 2 in-memory `tar.gz` bundle pipeline with a
streaming `tar.zst` pipeline that handles >100 MB worktrees without
buffering the full blob. The change touches three layers:

- **Oneiric** — `compression-zstd` PEP 735 group plus
  `LocalStorageAdapter`/`S3StorageAdapter`/`GCSStorageAdapter`/
  `AzureBlobStorageAdapter` now expose `save_stream`/`load_stream`.
- **Mahavishnu** — `mahavishnu/core/worktree_providers/storage_io.py`
  has been rewritten around streaming serialize/deserialize
  (`serialize_worktree_tar` context manager,
  `deserialize_worktree_tar` chunk reader). Storage key suffix moved
  from `.tar.gz` to `.tar.zst`.
- **Observability** — new `streaming_op_duration_seconds` histogram
  and `streaming_op_total{op,backend,success}` counter wired to every
  streaming op (`SERIALIZE`, `DESERIALIZE`, `COMPRESS`, `DECOMPRESS`,
  `HASH`, `UPLOAD`, `DOWNLOAD`). `bundle_bytes` histogram extended to
  1 GB buckets.

The bounded queue producer/consumer handoff (Python `queue.Queue`
with `maxsize=4`) in `RemoteWorktreeProvider.fetch` decouples slow
disk from fast network so memory stays at `chunk_size × 4` regardless
of bundle size.

Why it matters: prior to Phase 3, worktrees >100 MB had to be encoded
in memory before upload, which OOMed on serverless workers with the
1 GB ephemeral `/tmp` cap. Phase 3 streams the entire encode + upload
pipeline so the only memory ceiling is the bounded queue.

## Prerequisites

The rollout assumes the following are already in place:

- **Oneiric >= 0.16** with Phase A streaming work merged (commits
  for `compression-zstd` PEP 735 group + `save_stream`/`load_stream`
  on all four storage adapters).
- **Mahavishnu Phase C commits** — `storage_io.py` rewrite, provider
  updates (Local + Remote streaming), observability helpers, and
  integration test green on `requires-python = ">=3.14"`.
- **`zstandard >= 0.23.0`** installed via the `compression-zstd` PEP
  735 group. Earlier releases lack the `chunker()` API used by
  `serialize_worktree_tar`.
- **`mahavishnu.observability.metrics`** export configured to point
  at the operational OTel collector. The streaming counters will be
  silent otherwise.

## Verification Steps

### 1. Confirm streaming is active (MCP health)

```bash
mahavishnu mcp health | jq '.worktree.streaming_enabled'
```

Expected: `true`. If `false` or missing the operator is still on the
Phase 2 path and Phase 3 commits have not landed in the running
container.

### 2. Confirm OTel streaming metrics are emitting

```bash
# From any host that can reach the OTel collector:
curl -s "$OTEL_COLLECTOR/v1/metrics" \
  | jq '.resourceMetrics[].scopeMetrics[].metrics[]
        | select(.name | startswith("streaming_op_"))'
```

Expected: at least one `streaming_op_total` series with `op="compress"`
after a create, and `op="decompress"` after a fetch. If absent after
10 minutes of steady traffic, the streaming helpers are not wired to
the meter (likely a missing `record_streaming_op` call).

### 3. Confirm storage keys have the new suffix

```bash
# S3:
aws s3api list-objects-v2 \
  --bucket "$MAHAVISHNU_BUNDLE_BUCKET" \
  --prefix "worktrees/" \
  --query "Contents[?contains(Key, '.tar.gz')].Key" \
  --output text
```

Expected: empty. Any `.tar.gz` keys are Phase 2 orphans — run the
migration sweep script (`scripts/migrate_to_streaming_tar.py`) or the
detection sweep (`scripts/sweep_legacy_targz.py`).

### 4. Confirm bundle integrity failure rate is bounded

```promql
sum(rate(bundle_integrity_failure_total[5m]))
  /
sum(rate(worktree_fetch_duration_seconds_count[5m]))
```

Expected: < 0.0001 (0.01%) per ADR 015 v4 SLO. If higher, escalate per
the matrix below.

## Rollback Procedure

Rolling back from Phase 3 to Phase 2 does not require a schema
migration — bundle suffix change is the only persistent delta, and
Phase 2 readers tolerate `.tar.zst` only if Phase 2 writers also
produced `.tar.zst`. The safe rollback path is therefore to drain
Phase 3 writers before allowing Phase 2 readers back in.

1. **Pause writers.**
   Set `MAHAVISHNU_WORKTREE_STORAGE__BACKEND_PREFERENCE=local` and
   disable the streaming feature flag:

   ```bash
   export MAHAVISHNU_WORKTREE_STORAGE__STREAMING_ENABLED=false
   ```

2. **Drain in-flight creates.** Wait for
   `worktree_create_duration_seconds_count` rate to fall to zero
   over a 5-minute window. This bounds how many Phase 3 `.tar.zst`
   bundles are in flight.

3. **Revert Phase C commits.** Cherry-revert the commits that
   introduced the streaming `storage_io.py`, the provider updates,
   and the observability helpers. No schema migration; the registry
   continues to point at the same handles.

4. **Restart with Phase 2 code path.**

   ```bash
   mahavishnu mcp stop && mahavishnu mcp start
   ```

5. **Verify.** Re-run the Verification Steps above. The
   `streaming_op_total` counter will fall to zero; legacy
   `bundle_bytes` histogram will continue to populate from Phase 2
   reads.

Rollback signal (per Phase D Integration Contract): spike in
`MHV-208` > 0.01% of fetches within 7 days of rollout.

## Known Limitations

- **256 MB stopgap cap.** `MAX_BUNDLE_BYTES_STOPGAP = 256 MiB`
  defines the in-memory / temp-file path boundary. Bundles larger
  than 256 MB must route through streaming-aware adapters and the
  bounded queue. Operators sizing new fleets should treat this as a
  memory ceiling per active fetch.
- **`zstandard >= 0.23.0` required.** Earlier versions do not
  expose the `ZstdCompressor.chunker()` streaming entry point used
  by `serialize_worktree_tar`. Pinning is enforced by the
  `compression-zstd` PEP 735 group pin in `pyproject.toml`.
- **LocalStorageAdapter pre-Phase-A incompatible.** Phase 3 callers
  require the `save_stream`/`load_stream` surface added by oneiric
  Phase A.6. Rolling back the oneiric side without rolling back the
  mahavishnu side produces `AttributeError` at fetch time.
- **`data_filter` strips setuid/setgid bits.** Worktrees with
  intentional setuid binaries will lose them on Phase 3
  serialize/deserialize. Phase 2 had no such filter. Document this
  in tenant onboarding if any setuid binaries are expected.
- **`uuid4().hex` handle_id cardinality.** Phase 3 dropped the
  deterministic `(repo, branch, base_ref)` handle_id derivation in
  favor of `uuid4().hex` to eliminate concurrent-create races. Each
  new worktree allocates a fresh handle; old Phase 2 handle_ids
  continue to work but should be migrated during the rollout window.

## Escalation Path

File issues against the worktree-streaming component in the project
tracker. Severity routing:

| Severity | Where to file | PagerDuty service |
|---|---|---|
| S1 (data loss, integrity failure spike) | `mahavishnu-worktree-streaming` PagerDuty | `mahavishnu-worktree-streaming` |
| S2 (performance regression, sustained MHV-208 > 0.01%) | Same | Same |
| S3 (single-region fetch failure) | Slack `#mahavishnu-ops` | n/a |
| S4 (cosmetic, docs) | GitHub issue | n/a |

When filing, include:

- OTel snapshot of `streaming_op_total` and `bundle_integrity_failure_total`
  over the affected window.
- Output of `mahavishnu mcp health | jq '.worktree'` at the time of
  the incident.
- The `handle_id` and `principal_short` from the failing fetch log
  line.
- S3/GCS request ID for the storage-side leg (if applicable).

For the on-call rotation, see `docs/runbooks/on_call_handbook.md`.
For cross-component ripple (Dhara / Session-Buddy / Akosha), see
`docs/runbooks/error_budget_enforcement.md`.
