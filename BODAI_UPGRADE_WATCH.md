# Bodai Python Upgrade Watch

Tracks Python 3.15 readiness across the Bodai ecosystem. Filed 2026-08-23
during Phase 3 rollout (3.14 migration).

## Weekly checklist

- [ ] 3.15 beta releases (cpython devguide.python.org)
- [ ] llama-index-core 3.15 wheel status
- [ ] pydantic-ai-slim 3.15 wheel status
- [ ] selectolax 3.15 wheel status
- [ ] Other deps with no 3.15 wheel yet
- [ ] Bodai CI matrix (each repo) currently on 3.14, ready to bump to 3.15

## Phase 4 trigger

When 3.15.0 final releases AND all tracked deps have 3.15 wheels:
- Open Phase 4 ADR update (move from Proposed to Accepted) — see `docs/adr/016-phase-4-streaming-tar-evolution.md`
- Begin the 7-PR sequence: mcp-common → oneiric → dhara → session-buddy → akosha → crackerjack → mahavishnu
- 2-week soak between each merge
- Total window: ~3 months from 3.15.0 GA to mahavishnu on 3.15

## Rollout order (dependency-aware)

Same as Phase 0 (3.14 migration):

1. **mcp-common** — leaf dependency
2. **oneiric** — adapter framework
3. **dhara** — curator
4. **session-buddy** — builder
5. **akosha** — seer
6. **crackerjack** — inspector
7. **mahavishnu** — orchestrator (last; consumes all of the above)

Per Bodai pre-1.0 policy: merge directly to `main`, no PRs. Branch + squash/ff-merge into main is the expected flow.

## Rollback signals (per Phase E contract)

- integrity failure rate > 0.01% sustained
- stopgap path OOM (MAX_BUNDLE_BYTES_STOPGAP exceeded in prod)
- migration sweep finds > 100 legacy `.tar.gz` keys still in storage after 7 days

## Status (update weekly)

- **2026-08-23**: Phase 3 merged. 3.14 is baseline. 3.15 still beta.
  - Phase A (oneiric streaming tar core): DONE
  - Phase B (GCS/Azure streaming): DONE
  - Phase C (mahavishnu integration): DONE
  - Phase D (runbook + docs): DONE
  - Phase E (monitoring + Phase 4 ADR): IN PROGRESS
  - Fastblocks `snob-lib` maturin Rust build fails under 3.14 — real blocker for that repo's 3.14 adoption; needs upstream snob-lib or maturin/pyo3 update.
  - 22 sibling repos have `.python-version = 3.14` on disk; user must run `uv sync` from network-enabled shell to populate venvs (sandbox DNS unreachable).