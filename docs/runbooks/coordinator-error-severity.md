# Coordinator Error Severity Table

Severity, retry policy, and alerting routing for every Mahavishnu
error code in the MHV-200..223 range. This is the canonical
on-call reference for triage: pair the table with
`mahavishnu.mcp.health` output and the
`bundle_integrity_failure_total` / `streaming_op_total` OTel
counters.

## Table of Contents

1. [How to Use This Table](#how-to-use-this-table)
1. [Severity Definitions](#severity-definitions)
1. [Retry Behavior](#retry-behavior)
1. [Alert Channels](#alert-channels)
1. [Error Code Table](#error-code-table)
1. [PHASE 3 Streaming-tar Decisions](#phase-3-streaming-tar-decisions)

______________________________________________________________________

## How to Use This Table

1. Find the MHV code from the log line or the `error_code` field on
   the exception.
1. Read the **Severity** column to know how urgent the response is.
1. Read **Retry?** to know whether the coordinator will re-attempt.
1. Read **Alert Channel** to know where to expect a page or message.

When a single incident produces multiple MHV codes, take the
**highest** severity across the observed set. Example: a fetch that
returns MHV-208 (data integrity) plus MHV-222 (handle not found) is
`error`-severity because MHV-208 dominates.

## Severity Definitions

| Severity | Definition | Response Time SLA |
|---|---|---|
| `critical` | Data loss, integrity breach, sustained outage | 15 minutes |
| `error` | Functional failure with workaround; integrity failure spike | 1 hour |
| `warn` | Operational anomaly; transient failure with self-heal | 4 hours |
| `info` | Lifecycle event; expected under normal operation | Next business day |

## Retry Behavior

| Retry? | Meaning |
|---|---|
| `yes` | Coordinator re-attempts with exponential backoff (3 attempts, jittered) |
| `no` | Coordinator surfaces the error to the caller; no retry |
| `yes-once` | Coordinator re-attempts once before surfacing (transient I/O class) |

## Alert Channels

| Channel | Meaning |
|---|---|
| `pagerduty` | Page on-call via `mahavishnu-worktree-streaming` PagerDuty service |
| `slack` | Post to `#mahavishnu-ops` Slack channel |
| `none` | Log only; no external notification |
| `audit` | Forwarded to the Dhara audit pipeline for forensic chain-of-custody (no realtime alert) |

## Error Code Table

| MHV Code | Name | Severity | Retry? | Alert Channel |
|---|---|---|---|---|
| MHV-200 | `REPOSITORY_NOT_FOUND` | warn | no | slack |
| MHV-201 | `REPOSITORY_NOT_CONFIGURED` | warn | no | slack |
| MHV-202 | `WORKTREE_CREATION_FAILED` | error | yes-once | slack |
| MHV-203 | `WORKTREE_NOT_FOUND` | warn | no | slack |
| MHV-204 | `WORKTREE_CLEANUP_FAILED` | warn | yes-once | none |
| MHV-205 | `REPOSITORY_CLONE_FAILED` | error | yes | slack |
| MHV-206 | `REPOSITORY_ACCESS_DENIED` | error | no | audit |
| MHV-207 | `WORKTREE_LOCKED` | info | yes | none |
| MHV-208 | `WORKTREE_INTEGRITY_FAILED` | error | no | slack + audit |
| MHV-209 | `WORKTREE_BUNDLE_TEMP_CREATE_FAILED` | error | no | slack |
| MHV-210 | `WORKTREE_BUNDLE_TEMP_WRITE_FAILED` | warn | yes-once | none |
| MHV-211 | `WORKTREE_BUNDLE_PATH_TRAVERSAL` | critical | no | pagerduty + audit |
| MHV-212 | `WORKTREE_BUNDLE_MALFORMED` | warn | no | audit |
| MHV-213 | `WORKTREE_BUNDLE_LEGACY_PHASE2` | warn | no | slack |
| MHV-220 | `WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG` | error | no | slack |
| MHV-221 | `WORKTREE_BUNDLE_STOPGAP_TOO_LARGE` | error | no | slack |
| MHV-222 | `WORKTREE_BUNDLE_NOT_FOUND` | info | no | none |
| MHV-223 | `WORKTREE_BUNDLE_CODEC_UNAVAILABLE` | critical | no | pagerduty |

## PHASE 3 Streaming-tar Decisions

The following per-code routing decisions were made during the Phase 3
streaming tar rollout. They are the on-call single source of truth;
any change to severity or retry must update this table and propagate
to `mahavishnu.core.worktree_coordination`.

```python
# Phase 3 error severity decisions:
#   MHV-209 TEMP_CREATE_FAILED   → propagate (programmer error, retry won't help)
#   MHV-210 TEMP_WRITE_FAILED    → swallow-and-log (could be transient ENOSPC)
#   MHV-211 PATH_TRAVERSAL       → propagate (security event, audit)
#   MHV-212 MALFORMED            → swallow-and-log + invalidate handle (corrupt bundle)
#   MHV-213 LEGACY_PHASE2        → propagate (operator-facing migration warning)
#   MHV-220 STORAGE_KEY_TOO_LONG → propagate (programmer error)
#   MHV-221 STOPGAP_TOO_LARGE    → propagate (deployment misconfig)
#   MHV-222 NOT_FOUND            → swallow-and-log (handle gone, not an error)
#   MHV-223 CODEC_UNAVAILABLE    → propagate (deployment misconfig; missing dep)
```

### Rationale (per code)

- **MHV-209 (`TEMP_CREATE_FAILED`)** — `tempfile.mkstemp` raising
  `OSError` is almost always a disk-full or per-process fd-exhaustion
  condition. Retrying makes the exhaustion worse. Surface to the
  caller and let the operator investigate filesystem health.
- **MHV-210 (`TEMP_WRITE_FAILED`)** — Write errors may be transient
  (ENOSPC, EDQUOT). Retry once; on second failure, surface.
- **MHV-211 (`PATH_TRAVERSAL`)** — `tarfile.data_filter` rejecting
  a member is a security event, not a transient I/O failure. Propagate
  and write an audit row in Dhara so the bundle can be quarantined.
- **MHV-212 (`MALFORMED`)** — A malformed bundle is a corruption
  signal. The handle is unsafe to retry against; invalidate it and
  log. Higher-level code should re-create from source.
- **MHV-213 (`LEGACY_PHASE2`)** — A `.tar.gz` key in the storage
  bucket is an operator-facing migration signal. Propagate so the
  operator runs the migration sweep
  (`scripts/migrate_to_streaming_tar.py`).
- **MHV-220 (`STORAGE_KEY_TOO_LONG`)** — Hitting the 1024-byte S3
  key limit is a programmer error. Propagate; do not retry.
- **MHV-221 (`STOPGAP_TOO_LARGE`)** — Bundle exceeded the 256 MiB
  in-memory stopgap. This is a deployment misconfiguration: the
  streaming path was not taken. Surface immediately.
- **MHV-222 (`NOT_FOUND`)** — Storage adapter returned None for an
  expected key. The handle was already gone (TTL expired or manual
  deletion). Swallow and log; the caller treats the handle as
  gone.
- **MHV-223 (`CODEC_UNAVAILABLE`)** — `zstandard` not installed.
  Deployment misconfiguration. Page on-call so the operator installs
  the `compression-zstd` PEP 735 group.
