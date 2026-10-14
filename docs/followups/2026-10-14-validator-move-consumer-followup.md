---
status: active
role: implementation
kind: followup
date: 2026-10-14
last_reviewed: 2026-10-14
superseded_by: null
blocks_on: []
topic: shared-frontmatter-validator-move-consumer-followup
---

# Followup — Consumer-repo followup for the frontmatter-validator move

**Date:** 2026-10-14
**Status:** PENDING USER ACTION
**Originating plan:** `docs/plans/2026-10-14-shared-frontmatter-validator-move.md`
**Originating spec:** `docs/specs/2026-10-14-shared-frontmatter-validator-move-amendment.md`

## Why

The shared frontmatter validator moved from mcp-common into
crackerjack (Tasks 1-4 of the originating plan). All 5 consumer
repos have already deleted their seed-copied
`scripts/validate_document_frontmatter.py`. The remaining
work is to bump the crackerjack version, re-sync the
consumers, and verify the CLI works end-to-end on each.

## Steps (for each of 4 consumer repos: session-buddy, akosha, oneiric, mahavishnu)

1. **Pick the crackerjack version to bump to.** The plan's
   Tasks 1+2 produce commits on the crackerjack side. The
   version bump (crackerjack's `pyproject.toml`) is the
   user's call per `feedback-mcp-common-version-bump-is-user.md`.
   Recommend a minor bump (e.g. 0.70.x → 0.71.0) because the
   `--vocab-path` CLI flag and the `VocabFileNotFoundError`
   exception class are new public API surface.

2. **In each consumer repo, bump the crackerjack pin.**
   Update `crackerjack>=0.70.0` to `crackerjack>=0.71.0` (or
   whatever version was chosen) in `pyproject.toml`. This is
   the user-controlled per-repo version bump.

3. **Run `uv sync` to update the lock file.**

4. **Smoke-test the CLI** in the consumer's working tree:
   ```bash
   .venv/bin/python -m crackerjack docs validate --repo-root . --vocab-path docs/schemas/topic-vocabulary-v1.md 2>&1 | tail -20
   ```
   The mahavishnu tree's PLAN_INDEX is post-fix (it has the
   topic vocabulary symlink at `docs/archive/topic-vocabulary-v1.md`
   pointing at `docs/schemas/topic-vocabulary-v1.md`).
   Other consumers may not have this symlink yet — that's
   expected; the smoke test will either succeed (if the
   default path is right) or surface the new
   `VocabFileNotFoundError` (if not; the operator adds the
   symlink or passes `--vocab-path`).

5. **Update `scripts/regenerate_plan_index.py` help text** in
   each consumer to point at `crackerjack docs validate`
   instead of the deleted mcp-common script. This is the
   rule from the original 2026-07-26 plan: "All consumer
   repos must update their `scripts/regenerate_plan_index.py`
   help text to point at `crackerjack docs validate` (not the
   script)."

6. **Commit and push.** Per
   `feedback-bodai-push-is-user-controlled.md`, push requires
   explicit user approval per repo.

## What to do if a consumer's smoke test fails

- **`crackerjack: command not found`** — the bump didn't take
  effect. Re-run `uv sync` and check `pyproject.toml`'s pin.
- **`VocabFileNotFoundError` exit 2** — the consumer's tree
  doesn't have the canonical vocab file at the default path.
  Either (a) add the symlink `docs/archive/topic-vocabulary-v1.md`
  → `../schemas/topic-vocabulary-v1.md` (mahavishnu's pattern
  from the earlier session), or (b) pass `--vocab-path=PATH`
  on the CLI invocation.
- **Old `scripts/validate_document_frontmatter.py` references
  in tests or docs** — the consumer may have lingering
  references. Grep for the script name in the consumer repo
  and update each one.
