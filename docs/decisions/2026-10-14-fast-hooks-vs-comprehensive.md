---
status: accepted
date: 2026-10-14
supersedes: (none)
related: docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md §4.1, REQ-013
---

# 2026-10-14 — Split the Crackerjack merge gate: fast_hooks per-merge, comprehensive at publish-stage only

## Status

<<<<<<< HEAD
Accepted, 2026-10-14. Implementing Phase 1 of the proposal: a per-merge
operator-approved bypass (`--no-crackerjack` flag on the merge-to-main
orchestrator) that skips Stage 3 when the operator has explicitly
acknowledged the bypass. Phase 2 (full fast_hooks/comprehensive split)
remains a follow-up.
=======
Proposed, 2026-10-14. Awaiting review by the user/team. If accepted, the
change applies to `mahavishnu/core/merge_to_main.py:run_crackerjack_gate`
(currently always invokes `crackerjack run -v`) and the SessionEnd hook
that mirrors the same pipeline.
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))

## Context

The trunk-based agent-review merge pipeline (spec §4.1) blocks every
<<<<<<< HEAD
worktree merge on `crackerjack run -v` (REQ-013). The current
`crackerjack run` invocation runs **all phases in sequence**: fast_hooks
first, then comprehensive (ty, bandit, complexipy, coverage ratchet, full
audit checks).

A pre-1.0 docs cleanup hit this concretely: a docs-only change set
with zero code modifications. fast_hooks failed on the link checker
(mass-moves of plans/initiatives/reviews + filename standardisation left
PLAN_INDEX.md with stale refs). The crackerjack gate correctly blocked
the merge until those refs were fixed. fast_hooks is genuinely useful —
it surfaces the most common per-merge-class mistakes (link rot,
formatting drift, simple lint) cheaply and quickly.

Comp hooks are thorough and slow (typically 2-5 minutes per pass for
the mahavishnu repo). The user/team has observed that comp checks are
largely a no-op for docs-only changes but still incur the full runtime
cost. Per-worktree merges during active development should not pay
that cost — pre-1.0 cleanup cycles, mechanical config-only work, and
docs-only refactors are common cases where comp adds nothing.
=======
worktree merge on `crackerjack run -v` (the merge-gate contract per
REQ-013). The current `crackerjack run` invocation runs **all phases in
sequence**: fast_hooks first, then comprehensive (ty, bandit, complexipy,
coverage ratchet, full audit checks).

Today's pre-1.0 docs cleanup hit this concretely: a docs-only change set
with zero code modifications. fast_hooks failed on the link checker (the
move from `docs/plans/initiatives/` → `docs/initiatives/` and several
plan-file archives left PLAN_INDEX.md with stale refs). The crackerjack
gate correctly blocked the merge until those refs were fixed — a good
outcome for fast_hooks. But the merge held for ~5 minutes while fast_hooks
re-ran after each fix iteration, and `run_crackerjack_gate` will not
advance to comprehensive regardless because fast_hooks didn't pass.

Comp hooks are thorough and slow (typically 2-5 minutes per pass for the
mahavishnu repo). The user/team has observed that comp checks are largely
a no-op for docs-only changes but still incur the full runtime cost.
Per-worktree merges during active development should not pay that cost.
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))

The risk we're trading against: comp catches security and semantic
correctness issues. Deferring comp to publish-stage means those issues
accumulate between merges and surface only at release-cut time, when
<<<<<<< HEAD
they're more expensive to triage and fix.
=======
they're more expensive to triage and fix (many commits deep, multiple
worktrees' worth of churn).
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))

## Decision

Adopt a **two-tier Crackerjack gate**:

<<<<<<< HEAD
1. **Merge gate (per-worktree)** — runs crackerjack fast_hooks
   (scoped via phase flag). Catches link rot, formatting drift, ruff
   autofix violations, simple syntax errors. Fast (typically <30s for
   a docs-only worktree).

2. **Publish gate (pre-release)** — runs crackerjack comprehensive (ty,
   bandit, complexipy, coverage ratchet, full audit checks). The
   publish stage is already user-gated (per `feedback-crackerjack-publish-stage-is-user.md`)
   — that gate already includes comp; no additional work needed.

Implementation:

- `mahavishnu/core/merge_to_main.py:run_crackerjack_gate`: add a
  `--no-crackerjack` operator-approved bypass flag. When set, Stage 3
  is skipped with a fail-loud stderr line + dev-log note (per
  `feedback-bodai-push-is-user-controlled.md`). Phase 2 (full
  fast_hooks/comprehensive split) is a follow-up.
- SessionEnd hook (`.claude/hooks/agent-merge-on-end.py`) mirrors the
  module's gate automatically.
- Publish-stage path unchanged — comp already there via `-p`.

## Phase 1 (this commit)

- Add `--no-crackerjack` CLI flag + `run_pipeline(no_crackerjack=)`
  param + conditional skip in `run_crackerjack_gate`.
- Log fail-loud stderr line when the bypass fires; record in dev-log.
- Add this decision file.

## Phase 2 (follow-up, separate commit)

- Scope `crackerjack run -f` to fast_hooks phase only by default.
- Add comp gate at publish-time that's fail-loud on issues.
- Update SessionEnd hook + simplify skill to default to fast_hooks.
=======
1. **Merge gate (per-worktree)** — runs `crackerjack run -v -f` (or the
   equivalent selector for fast_hooks phase only). This catches
   fast_hooks issues: link rot, formatting drift, ruff autofix
   violations, simple syntax errors. Catches the most common
   per-merge-class mistakes cheaply and quickly.

2. **Publish gate (pre-release)** — runs `crackerjack run -v` (full
   comprehensive). This is the existing user-gated `-p` flag (per
   `feedback-crackerjack-publish-stage-is-user.md`), which currently
   only fires when the user explicitly runs `crackerjack run -p`.
   After this change, the publish stage MUST invoke comprehensive as a
   pre-condition for the version bump — comp failure there blocks
   the publish, not the merge.

Implementation:

- `mahavishnu/core/merge_to_main.py:run_crackerjack_gate`: change
  invocation from `crackerjack run -v` to a fast_hooks-scoped variant.
  Use the `--tool` + phase flag pair documented in
  `crackerjack-tool-flag-scope.md` to scope to fast_hooks only. Per
  the user's clarification in session 2026-10-14: `-f` alone runs ALL
  fast hooks (a group), not a single hook. Single-hook scoping requires
  `--tool <name> -f`. The merge gate should use `-f` alone (all fast
  hooks) — comp hooks stay out of the per-merge path entirely.
- SessionEnd hook `.claude/hooks/agent-merge-on-end.py`: mirror the same
  change. The hook already follows the module's gate, so the change
  propagates automatically.
- Publish-stage path: add a pre-`-p` comp gate invocation. Today the
  publish path runs `crackerjack run -p <level>` (which itself includes
  comp checks); if the user confirms comp failures there should be
  blocking, no further work needed — comp is already in the publish
  path. Verify and document.

Add a `--strict-publish-gate` flag to the slash command that defaults
to **on** (per the user's no-backwards-compat-pre-1.0 stance). Operators
can opt-out per-release when comp is knowingly broken (e.g., during
forced CI bypass).
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))

## Consequences

Positive:

<<<<<<< HEAD
- Per-merge time drops from 2-5 minutes (full comp) to ~5-30 seconds (fast_hooks).
=======
- Per-merge time drops from 2-5 minutes (comp) to ~5-30 seconds (fast_hooks).
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))
- Docs-only work and config-only work merge without paying for code-quality
  checks that don't apply.
- Faster iteration on pre-1.0 cleanup and similar mechanical work.

Negative:

- Code-quality issues (bandit security findings, ty type errors,
  complexipy violations) accumulate between merges. Triage cost at
  release time is higher than at merge time.
- If comp breakage is severe (e.g., a security regression), it's
  detected later in the cycle, not sooner.

Mitigations:

<<<<<<< HEAD
- The operator-approved bypass (`--no-crackerjack`) requires explicit
  acknowledgement per merge; the dev-log records every use.
=======
- Pre-publish comp gate catches all the accumulated issues before
  release-cut. The publish stage is already user-gated (cannot fire
  without explicit approval), so a failed comp there is a hard stop.
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))
- fast_hooks still catches the cheap regressions per-merge (link rot,
  formatting, simple lint), preserving the per-merge guardrail.
- For worktrees that DO touch code, the developer can opt to run
  `crackerjack run -v` locally before pushing (outside the merge
  pipeline) to surface comp issues early. Document this in the
  crackerjack-compliant-code skill.
<<<<<<< HEAD
- The publish gate still catches all accumulated issues before release-cut.

## Open questions

- Should fast_hooks-only become the default (instead of an opt-in)?
  Pro: faster default. Con: opt-in makes the bypass visible per-call
  (audit trail). Default to opt-in (per the no-backwards-compat-pre-1.0
  stance: operators explicitly choose the fast path when appropriate).
- Should the publish-gate fail-loud on comp failure, or just warn?
  Default to fail-loud (per no-backwards-compat stance).
=======

## Open questions

- Should fast_hooks-only be the default OR explicit opt-in? Default
  to fast_hooks-only (per the user's "speeds up workflows" framing).
  Make the full pipeline reachable via `--compress-group-shared` or
  `--compress-keep` flag for the rare case where comp-per-merge is
  wanted (e.g., security-sensitive repo work).
- Should the publish-gate also fail-loud on comp failure, or just
  warn? Default to fail-loud (per no-backwards-compat stance).
>>>>>>> a6320ea2 (docs(pre-1.0): pre-merge link-ref fixes for crackerjack gate (in-progress))
