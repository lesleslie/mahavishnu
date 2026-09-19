---
status: active
role: canonical
topic: sb-subagent-lockfile-producer
date: 2026-09-19
last_reviewed: 2026-09-19
superseded_by: null
blocks_on: []
title: 'Session-Buddy Subagent Lockfile Producer — Cross-Repo Followup'
---

# Session-Buddy Subagent Lockfile Producer — Cross-Repo Followup

## Summary

The detect-and-defer mechanism for subagent checkpoint interference is
*structurally* in place but *functionally dormant* in session-buddy
because the **producer half** of the lockfile contract is missing.

The consumer (`SubagentDetector.is_active()`) reads
`<working_dir>/.session-buddy/subagent.lock` and is wired into
`policy.py` + `orchestrator.py`. But nothing in this codebase (or any
tracked Bodai codebase per `BODAI_REPO_REGISTRY.md` 2026-09-19) writes
the lockfile when a subagent starts. Per the docstring at
`session_buddy/checkpoint/subagent_detector.py:33-41`:

> "The `.write()` method has no in-codebase caller at present; the
> producer (creating `<working_dir>/.session-buddy/subagent.lock`
> when a subagent starts) is owned by the subagent-runtime team and
> tracked externally."

## Scope

Create the producer half inside the **session-buddy** repo:

1. **Write path**: `SubagentDetector.write(working_dir)` that creates
   `<working_dir>/.session-buddy/subagent.lock` on subagent start and
   removes it on subagent end. Atomic write (write-temp + rename)
   to avoid partial-read races. Lockfile payload should include at
   minimum: `pid`, `started_at_ms`, `node_id`, `parent_agent_id`.

2. **Lifecycle hook surface**: a `SubagentLifecycleHook` (or similar
   protocol) that gets called by whichever subagent runtime is in
   use. For Claude Code subagents dispatched via the Task tool, this
   is the Claude Code session-buddy integration point; for Mahavishnu
   pools, it's the worker-spawn callback in `PoolManager`.

3. **Test coverage**: existing `tests/unit/core/checkpoint/test_subagent_detector.py::test_subagent_detector_fails_open_when_lockfile_unreadable`
   already tests the consumer side. Add a parallel test for the
   producer side: `test_subagent_detector_write_creates_lockfile`,
   `test_subagent_detector_write_atomic`, `test_subagent_detector_write_removes_lockfile_on_end`.

4. **Documentation**: update `docs/checkpoint/STASH_CLOBBER.md`
   (or analogous) to reflect that the producer now exists, and
   remove the "functionally dormant" caveat from
   `session_buddy/checkpoint/subagent_detector.py:33-41`.

## Repository

This work lives in `/Users/les/Projects/session-buddy/` (Phase 0.4
per `BODAI_REPO_REGISTRY.md`), not in mahavishnu. The followup file
itself lives here in mahavishnu because (a) mahavishnu is where the
affected plans live, and (b) the followups lifecycle policy
(`.claude/decisions/followups-lifecycle.md`) treats mahavishnu's
`docs/followups/` as the cross-Bodai canonical index.

## Blocks

- `docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md`
  (consumer-half plan, partial — closes to complete when this
  followup ships)
- `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`
  (parent observation, partial — closes when consumer plan closes)

## Closure criteria

This followup closes to `complete` when:

1. `SubagentDetector.write()` is implemented in session-buddy and
   covered by tests (≥ 90% coverage on the new code, matching the
   project's `--cov-fail-under=89.01682905225863` gate).
1. The lockfile is created/removed by at least one runtime path
   (Claude Code Task tool OR Mahavishnu PoolManager worker spawn).
1. The "functionally dormant" caveat is removed from
   `subagent_detector.py:33-41`.
1. The two blocking plans above update their `blocks_on:` and
   promote from `partial` to `complete` via PLAN_INDEX regeneration.

## Tracking

- Originating session: 2026-07-15 comprehensive-hooks-cleanup wave
  (`docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`)
- Parent memory:
  `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/session-buddy-checkpoint-hooks-fire-during-subagent-sessions.md`
- Resolution target: when both blocking plans close to `complete`,
  move this followup to `docs/followups/.archive/` per the
  followups lifecycle policy at `.claude/decisions/followups-lifecycle.md`.
