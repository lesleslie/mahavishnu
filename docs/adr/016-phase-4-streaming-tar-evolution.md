---
status: draft
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
topic: streaming-tar-evolution
supersedes: []
blocks_on:
  - "015-worktree-and-cache-storage-v4"
related:
  - "015-worktree-and-cache-storage-v4"
  - "015-multi-agent-review"
---

# ADR 016: Phase 4 — Python 3.15 ecosystem migration + streaming tar evolution

## Status

**Proposed.** Filed 2026-08-23 alongside the Phase 3 rollout closure.

Phase 4 has two parallel tracks:

- **Primary track: Python 3.15 ecosystem migration.** Tracked via `BODAI_UPGRADE_WATCH.md`. Triggers when 3.15.0 final releases AND all critical Bodai dependencies have published 3.15 wheels. Sequence: mcp-common → oneiric → dhara → session-buddy → akosha → crackerjack → mahavishnu. 2-week soak between each merge; total window ~3 months from 3.15.0 GA to mahavishnu on 3.15.

- **Secondary track: streaming tar evolution.** The Phase 3 placeholder captured six plausible follow-on work items (chunk-size auto-tuning, bundle dedup, cross-region re-streaming, codec portability, tail validation, multipart-abort observability). All six are **gated on Phase 3 monitoring telemetry** and not in the initial Phase 4 scope.

This ADR accepts the primary track. The secondary track items remain "proposed extensions" pending telemetry.

## Context

### What Phase 3 delivered

Phase 3 (ADR 015 v4) shipped the streaming `tar.zst` pipeline end-to-end across oneiric + mahavishnu:

- `serialize_worktree_tar` is a `@contextmanager` yielding `(temp_path, byte_count, sha256)` so the storage adapter can atomic-promote after a successful multipart upload.
- `deserialize_worktree_tar` consumes a `chunk_reader` and atomic-renames a staging directory onto the target.
- Remote + Local providers route through a bounded `queue.Queue(maxsize=4)` producer/consumer handoff.
- `LocalStorageAdapter` / `S3StorageAdapter` / `GCSStorageAdapter` / `AzureBlobStorageAdapter` all expose `save_stream` / `load_stream`.
- OTel surface: `streaming_op_total{op,backend,success}`, `streaming_op_duration_seconds{op,backend}`, `bundle_bytes`, `bundle_integrity_failure_total`, `s3_multipart_abort_total{backend,principal_short}`.
- MHV error codes 209–223 give operators precise per-failure-mode routing.
- 22 sibling repos + mahavishnu all pin `requires-python = ">=3.14"`.

### What 3.14 didn't fix (deferred Phase 4 candidates)

- **Fastblocks `snob-lib` maturin Rust build fails under 3.14** — upstream pyo3 / maturin / snob-lib update still pending. Blocks fastblocks from running on 3.14 even with network access. Will re-block Phase 4 unless upstream ships a 3.15-ready release in parallel.
- **Tool-config pins still 3.13 in 21 of 22 sibling repos** — Ruff `target-version = "py313"`, Pyright `pythonVersion = "3.13"`, mypy `python_version = "3.13"`, Refurb `python_version = "3.13"`. Phase 3 bumped `requires-python` but did not propagate to tool-config (only mahavishnu addressed these in commit `c1f3c18`). Phase 4 must update all tool-config pins atomically with the runtime bump.

### What 3.15 is expected to bring

Per CPython 3.15 release notes (pre-release, monitoring required):

- **PEP 709 (inlined comprehensions)** — material perf wins; risk to introspection-heavy code.
- **PEP 750 (t-strings)** — new string-prefix family. Likely affects template engines (fastblocks, jinja2-async-environment).
- **Removal of deprecated stdlib members** — `imp`, `binhex`, `macpath`, `formatter`, etc. Mostly already removed by Bodai deps; sweep during Phase 4 for direct callers.
- **Free-threaded (no-GIL) builds becoming default** — affects adapter code that holds C extensions. Not yet adopted by Bodai; tracked but out of scope for Phase 4.
- **Improved error messages** — minor; no action required.

### Streaming tar evolution candidates (secondary track, gated)

From the Phase 3 placeholder, six follow-on items. None accepted into initial Phase 4 — all require Phase 3 telemetry to make data-driven decisions:

1. **Streaming chunk-size auto-tuning** — today chunk size is constant. Adaptive policy requires `streaming_op_duration_seconds{op="compress"}` data per bundle size.
2. **Bundle deduplication** — content-addressed layer. Gates on measured duplicate rate across the cache.
3. **Cross-region re-streaming** — passthrough op kind. Gates on observed multi-region peer-fetch volume.
4. **Compression-codec portability** — `lz4` alternative to `zstandard`. Gates on operational demand; not a 3.15 driver.
5. **Streaming-tail validation** — emit `MHV-208` mid-stream. Gates on S3 multipart abort rate in Phase 3 monitoring.
6. **Multipart abort observability** — wire `streaming_multipart_abort_total{backend,reason}` counter. Implementation effort low; can land in Phase 4 cleanup wave if telemetry confirms.

## Decision

### Primary track (accepted)

**Bodai ecosystem migrates from Python 3.14 to Python 3.15 in the same dependency-aware 7-PR sequence as Phase 3.** Specifically:

1. **mcp-common** (leaf; no Bodai deps) — bump `requires-python = ">=3.15"`, propagate tool-config pins (Ruff `py315`, Pyright `3.15`, mypy `3.15`, Refurb `3.15`), run `crackerjack run` to surface dependency incompatibilities. No streaming-tar coupling. 2-week soak.

2. **oneiric** (adapter framework) — depends on mcp-common. Bump `requires-python` + tool-config + `StreamingCompressionAction` smoke test under 3.15 (zstandard 0.25+ already 3.15-ready). 2-week soak.

3. **dhara** (curator) — depends on mcp-common, oneiric. Bump + smoke test. 2-week soak.

4. **session-buddy** (builder) — depends on mcp-common, oneiric. Bump + smoke test. 2-week soak.

5. **akosha** (seer) — depends on mcp-common, oneiric. Bump + smoke test. 2-week soak.

6. **crackerjack** (inspector) — depends on all of the above. Bump + smoke test (crackerjack uses itself for quality gates). 2-week soak.

7. **mahavishnu** (orchestrator; last; consumes everything) — bump + tool-config + integration smoke test of the Phase 3 streaming tar path under 3.15. **2-week soak + 7-day monitoring window** before declaring Phase 4 complete (mirrors Phase 3's monitoring contract).

**Tool-config pin sweep.** Every PR must atomically update:
- Ruff `target-version = "py315"`
- Pyright `pythonVersion = "3.15"`
- mypy `python_version = "3.15"`
- Refurb `python_version = "3.15"`
- `Programming Language :: Python :: 3.15` classifier

Tool-config drift between repos was the single largest Phase 3 hygiene issue (only mahavishnu addressed it in commit `c1f3c18`; the other 21 repos have stale `py313` pins). Phase 4 sweep is non-negotiable; tracked as an ADR-level invariant.

**Per-Bodai-pre-1.0 merge policy:** direct to `main`, no PRs. Branch + squash/ff-merge into main is the expected flow. Cross-repo consistency via this ADR, not via gatekeeping.

### Secondary track (deferred)

All six streaming-tar evolution candidates remain **proposed extensions**, not accepted scope. Each one requires Phase 3 monitoring telemetry (bundle size distribution, abort rate, dedup rate) to make a defensible decision. The BODAI_UPGRADE_WATCH weekly checklist does NOT track these — they are tracked via a separate telemetry dashboard (TBD: see Open Question 4).

If Phase 3 7-day monitoring surfaces any of:
- `streaming_op_duration_seconds` P99 > 5s for bundles under the 256 MiB stopgap → consider chunk-size auto-tuning.
- `s3_multipart_abort_total` > 0.1% of fetches → consider streaming-tail validation.
- Storage tier showing > 30% identical-content rate → consider content-addressed dedup.

…then a Phase 4.x sub-ADR opens for that specific item.

### Out of scope (deferred to Phase 5 or later)

- Free-threaded (no-GIL) build adoption — separate ADR needed; risks are too high for Phase 4.
- PEP 750 (t-strings) adoption — depends on jinja2/fastblocks readiness, not on Phase 4 driver.
- Phase 2 streaming-tar → Phase 4 streaming-tar evolution items above — gated on telemetry.

## Consequences

### Positive

- **Single coordinated migration** (not 22 ad-hoc bumps). Phase 3's serialized 7-PR sequence with 2-week soaks produced no cascading failures; reusing it for Phase 4 minimizes risk.
- **Tool-config pin sweep** closes the Phase 3 hygiene gap (only 1 of 22 repos updated tool-config in Phase 3).
- **Two-track separation** (primary 3.15 + secondary streaming-tar evolution) prevents scope creep and makes the Phase 4 deliverables tractable.
- **Telemetry-gated secondary** items ensure the Phase 4 streaming-tar decisions are data-driven, not speculative.

### Negative / risks

- **Fastblocks `snob-lib` 3.14 blocker already pending.** If upstream snob-lib / maturin / pyo3 hasn't shipped a 3.15-compatible release by Phase 4 start, fastblocks will block Phase 4 just as it blocks Phase 3.15. Mitigation: open an upstream issue + ask user to investigate before Phase 4 PR #6.
- **Tool-config pin sweep touches every repo's pyproject.toml.** Risk of formatter drift across 22 repos. Mitigation: scripted edit + crackerjack dry-run per repo before commit.
- **Streaming-tar evolution items may never trigger.** If Phase 3 monitoring shows the current fixed-config performs well, all six deferred items may stay deferred indefinitely. That's a feature, not a bug — the ADR explicitly gates them on telemetry.
- **Phase 4 has its own 7-day monitoring window per Phase 3's contract.** Total elapsed: 3.15.0 GA + 7-PR × 2 weeks soak + 7-day monitoring = ~3.5 months from GA to Phase 4 verified.
- **No automatic rollback path** if 3.15 surfaces a critical incompatibility mid-rollout. Mitigation: per Bodai pre-1.0 policy, any repo can be reverted on main; Phase 4 can pause + reassess between PRs.

## Open Questions

1. **When is 3.15.0 GA expected?** Drives the Phase 4 start date. CPython release schedule (typically October) suggests 2027-Q4, but 3.15's release manager may shift. Track via BODAI_UPGRADE_WATCH weekly.
2. **Will upstream snob-lib / maturin / pyo3 ship 3.15-compatible wheels in time?** If not, fastblocks PR #6 in Phase 4 will block. Owner action: file upstream issue + follow up monthly.
3. **Is the streaming-tail-validation MHV-208 actually worth shipping?** Gated on Phase 3 abort-rate telemetry. Need a decision criterion (e.g. "abort rate > 0.1% of fetches → ship").
4. **Where does the streaming-tar telemetry dashboard live?** Currently metrics are emitted to OTel but not visualized. Need a Grafana dashboard spec (or skip — the OTel exporter in Dhara already collects them).
5. **PEP 750 (t-strings) readiness in fastblocks + jinja2?** Out of scope for the 3.15 bump itself, but if 3.15 GA lands before jinja2 ships t-string support, our template engine migration is delayed.
6. **Free-threaded (no-GIL) build?** CPython 3.15 may make this default. Currently out of scope, but a Phase 5 ADR should track the readiness of `zstandard`, `pydantic-core`, and `httpx` for free-threaded builds.

## Status (update weekly)

- **2026-08-23**: Phase 3 streaming tar.zst merged. 3.14 is baseline. 3.15 still beta. Phase 4 ADR proposed.
- **2026-08-24** (this session): Tool-config pin sweep closed the Phase 3 hygiene gap
  across 26 sibling repos (Ruff target-version, Pyright pythonVersion, mypy
  python_version, Programming Language :: Python classifier). Akosha and
  peanutbutterpub already had 3.14 pins and were skipped. Phase 4 trigger
  unchanged: see BODAI_UPGRADE_WATCH.md.
- Phase 4 trigger: see BODAI_UPGRADE_WATCH.md.

## References

- `BODAI_UPGRADE_WATCH.md` (this repo, root) — 3.15 readiness tracker
- `docs/runbooks/streaming-tar-rollout.md` — Phase 3 operator runbook (template for Phase 4)
- `docs/runbooks/coordinator-error-severity.md` — MHV-200..223 severity table
- `docs/adr/015-worktree-and-cache-storage-v4.md` — Phase 3 design
- `docs/superpowers/plans/2026-08-23-phase3-streaming-tar-plan.md` — Phase 3 plan (template for Phase 4 plan when 3.15.0 GA approaches)
