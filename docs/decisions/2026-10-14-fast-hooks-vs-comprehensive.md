---
status: accepted
date: 2026-10-14
supersedes: (none)
related: docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md §4.1, REQ-013
---

# 2026-10-14 — Split the Crackerjack merge gate: fast_hooks per-merge, comprehensive at publish-stage only

## Status

Accepted, 2026-10-14. Implementing Phase 1 of the proposal: a per-merge
operator-approved bypass (`--no-crackerjack` flag on the merge-to-main
orchestrator) that skips Stage 3 when the operator has explicitly
acknowledged the bypass. Phase 2 (full fast_hooks/comprehensive split)
remains a follow-up.

## Context

The trunk-based agent-review merge pipeline (spec §4.1) blocks every
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

The risk we're trading against: comp catches security and semantic
correctness issues. Deferring comp to publish-stage means those issues
accumulate between merges and surface only at release-cut time, when
they're more expensive to triage and fix.

## Decision

Adopt a **two-tier Crackerjack gate**:

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

## Consequences

Positive:

- Per-merge time drops from 2-5 minutes (full comp) to ~5-30 seconds (fast_hooks).
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

- The operator-approved bypass (`--no-crackerjack`) requires explicit
  acknowledgement per merge; the dev-log records every use.
- fast_hooks still catches the cheap regressions per-merge (link rot,
  formatting, simple lint), preserving the per-merge guardrail.
- For worktrees that DO touch code, the developer can opt to run
  `crackerjack run -v` locally before pushing (outside the merge
  pipeline) to surface comp issues early. Document this in the
  crackerjack-compliant-code skill.
- The publish gate still catches all accumulated issues before release-cut.

## Open questions

- Should fast_hooks-only become the default (instead of an opt-in)?
  Pro: faster default. Con: opt-in makes the bypass visible per-call
  (audit trail). Default to opt-in (per the no-backwards-compat-pre-1.0
  stance: operators explicitly choose the fast path when appropriate).
- Should the publish-gate fail-loud on comp failure, or just warn?
  Default to fail-loud (per no-backwards-compat stance).