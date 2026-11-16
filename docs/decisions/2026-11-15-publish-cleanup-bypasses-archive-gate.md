---
status: active
role: canonical
kind: decision
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by: null
topic: archive-completed-plans
title: "Publish-time documentation cleanup bypasses the archive gate"
---

# Publish-time documentation cleanup bypasses the archive gate

## Context

`docs/decisions/2026-10-18-archive-completed-plans.md` sets a gate for
archiving a plan: **rule 2** — "Plans being archived must have `status:
shipped` first. Mechanical 'complete → archive' is not allowed; the gate
forces per-plan verification."

Nothing enforces that gate in the tool that actually moves files.

`crackerjack`'s `documentation_cleanup` phase decides what to archive by
**filename regex**, in
`crackerjack/services/doc_categorizer.py:DocumentationCategorizer.get_archivable_files()`
(the gated build renamed it `get_archival_candidates()`, because it now
returns candidates rather than a verdict).
The `implementation_reports` category matches `.*-implementation\.md`, so
any plan whose name ends in `-implementation.md` is swept into
`docs/plans/.archive/implementation-reports/` regardless of its frontmatter.
`SCANNED_ARCHIVE_AREAS` includes `docs/plans`, and the phase
`git rm --cached`s the original — which, because `docs/plans/.archive/` is
matched by the fleet-wide `**/.archive/` gitignore rule, means the plan is
**untracked and gone from the repo**, not moved.

The sweep then collides with the index. `PLAN_INDEX.md` is not regenerated
after the cleanup, because this repo sets
`documentation.auto_plan_index_sync_on_publish: false` (see
`settings/crackerjack.yaml` — cracker's index fork re-renders the index in
a plainer format and drops the `docs/decisions/` and `docs/audits/` rows;
`scripts/regenerate_plan_index.py` is the authoritative renderer here). The
committed index keeps its rows, the files behind them are gone, and the
`check-local-links` fast hook fails on the dangling relative links.

This is the third occurrence of the same loss:

| Date | What happened |
|---|---|
| 2026-10-21 | read-path implementation plan archived |
| 2026-10-27 | v7 implementation plan archived |
| 2026-10-28 | `8f149717` ("chore: bump version to 0.37.0") archived both again and rewrote `PLAN_INDEX.md` without mentioning it |
| 2026-11-07 | `eaf9e162` reviewed both plans, verified their state, and restored them — "removed five plan/design files and rewrote `PLAN_INDEX.md` without mentioning it" |
| 2026-11-08 | read-path plan archived again (this time the index was *not* rewritten) |
| 2026-11-13 | v7 plan archived again |
| 2026-11-15 | `check-local-links` failed on the two dangling links |

Two of the swept plans are still live work, not history. Both are `status:
complete` with `role: implementation`, which is exactly the state rule 2
forbids archiving from. The read-path plan still carries an open item — R-4's
documentation sub-item, adding the `spans_substrate` path to
`docs/ingestion/DATA_INGESTION.md`, never landed — so per rule 1 it stays at
`complete` rather than `shipped`. Two live specs point at both plan paths
(`docs/specs/2026-10-19-bodai-substrate-otel-v7.md`,
`docs/specs/2026-10-20-bodai-otel-substrate-read-path.md`), and the
read-path plan's own `blocked_by:` names the v7 plan.

## Decision rule

**Publish-time documentation cleanup is disabled in this repo**
(`settings/crackerjack.yaml` → `documentation.auto_cleanup_on_publish:
false`) until the tool enforces the gate itself.

- The archiver must gate on frontmatter `status: shipped` before moving a
  file, per rule 2 of the archive policy. A filename regex cannot
  distinguish "a progress report named `*-implementation.md`" from "a
  canonical plan named `*-implementation.md`".
- Until that ships in a crackerjack release this repo installs, do not
  re-enable `auto_cleanup_on_publish` in this repo. The blast radius is
  small — every other document in the tree is already clean of the
  categorizer's patterns, so the sweep has nothing else to take — but what
  it does take is exactly the live plans.
- Disabling the phase does not drop frontmatter validation:
  `scripts/audit_doc_frontmatter.py` gates it repo-side and is wired into
  `mahavishnu/core/code_index/git_hooks.py:51`.
- If a plan really should be archived, do it by hand under the policy:
  flip `status: shipped` first, update the cross-references in the same
  commit (rule 4), then move it with `git rm --cached` + on-disk `mv`
  (rule 3) and regenerate the index with
  `python scripts/regenerate_plan_index.py`.

## Status

Accepted, 2026-11-15. The two plans were restored from HEAD (lossless — the
archived copies were byte-identical), `settings/crackerjack.yaml` gained the
`auto_cleanup_on_publish: false` guard, and `PLAN_INDEX.md` was regenerated
with the repo's own renderer.

**Residue:** the byte-identical archive copies
`docs/plans/.archive/implementation-reports/2026-10-19-bodai-substrate-otel-v7-implementation__001.md`
and `.../2026-10-20-bodai-otel-substrate-read-path-implementation__001.md`
are still on disk. They are gitignored, so they do not affect the repo, but
a manual `crackerjack run -C` would create `__002` copies of them. The
older plain-named copies in the same directory predate this sweep and are
kept.

### The permanent fix has landed — the guard is retired

Crackerjack now gates the cleanup on the document's declared lifecycle, at a
single choke point: a document carrying YAML frontmatter is archived only
when its `status:` is `shipped`. Measured against this repo's tree, through
the real cleanup entry point
(`DocumentationCleanup._detect_archivable_files()`):

| crackerjack | archivable candidates |
|---|---|
| the package this repo used to run (0.94.0, from PyPI) | **2** — both OTel substrate plans |
| 0.95.0, from PyPI, carrying the gate | **2** found, **0** archived — both held |

That is the whole point of the gate: the two files that were lost five times
are exactly the two the filename sweep takes, and the gate takes neither. The
candidate list stays non-empty — the filename patterns still match — so the
gate, not the patterns, is what protects them.

**The guard was never the fix; it was the workaround for the missing one.**
It is retired now that every step below is satisfied:

1. Push crackerjack's `main` — done; the gate shipped in 0.95.0.
2. Publish crackerjack — done; 0.95.0 is on PyPI.
3. Bump this repo's `crackerjack` pin and re-lock — done; the floor is
   `crackerjack>=0.95.0` and the lock resolves 0.95.0.
4. Re-measure — done; `_detect_archivable_files()` returns 0 on 0.95.0.
5. Drop the `auto_cleanup_on_publish: false` guard — done, below.

So `settings/crackerjack.yaml` no longer disables publish-time cleanup, and
with it the frontmatter validation that ran inside that phase comes back.
The guard cost this repo that validation while it stood.

**The floor is now load-bearing.** The guard was version-independent; the
gate is not. A lower `crackerjack` floor re-resolves to a release with no
gate, and the sweep takes the plans again — silently, on the next publish.
That is why the floor moved in the same release as the guard's removal.

The rule this decision records still stands: **a plan may only be archived
once its `status:` is `shipped`.** The enforcement moved from a settings
flag in this repo to the tool that moves the files, which is where it
belongs — a repo cannot enforce its own archive policy against a tool that
ignores lifecycles.
