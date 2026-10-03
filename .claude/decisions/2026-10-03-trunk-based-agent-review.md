---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: trunk-based-agent-review
---

# Trunk-Based Agent-Reviewed Dev Workflow

## Context

Replaces GitHub-PR-shaped review for AI-driven solo dev. Ephemeral
branches + AI ensemble review + `crackerjack run -v` gate + squash-merge
+ auto-push `main` + governed cleanup. See spec §"The Workflow".

The 2026-10-03 spec `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
ships a single-purpose, mechanically-gated branch-to-`main` workflow for
this repo. Stages 1–6 are owned by the AI worker (slash command or
SessionEnd hook); stage 7 (publish — `crackerjack run -p <level>` + version
bump + tag + tag-push) is owned by the human. Branches are ephemeral
(deleted with their worktree) and never pushed to a remote; only the
squashed result lands on `main`, and only `main` is pushed to `origin`.

This doc is the canonical reference for the workflow itself. The
auto-push rule (stage 5) is the exception it shares with
`2026-10-03-mainautopush.md`; that sibling decision is the source of
truth for the push exception and is cross-linked from this doc.

## Decision rule

The 7-stage workflow in spec §Workflow is the canonical dev flow for
Bodai ecosystem repos when an AI worker is driving. Branches are
ephemeral (deleted with their worktree); auto-push is governed by
`2026-10-03-mainautopush.md`; cleanup routes through `mahavishnu worktree
prune-merged`.

`MAHAVISHNU_AUTO_MERGE=1` is the default (per user choice; explicitly
exported in `~/.zshenv`). To disable auto-merge at SessionEnd, set
`MAHAVISHNU_AUTO_MERGE=0`. The `/merge-to-main` slash command and
`Skill(skill="merge-to-main", ...)` invocation still work after opt-out
(explicit user invocation), bypassing the env-var gate.

Stage summary (per spec §Workflow):

| Stage | Owner | Action | Gate |
|---|---|---|---|
| 1. Worktree | AI worker | Ephemeral branch inside session worktree (or `git worktree add` if auto-worktree off) | Path outside repo, unique branch |
| 2. Review | AI ensemble | 2 specialists + 1 random generalist; iterate on `needs_adjustment` | `block` from any agent blocks; else 2/3 `pass` proceeds |
| 3. Quality gate | AI worker | `crackerjack run -v` | non-zero exit blocks merge |
| 4. Squash-merge | AI worker | `git rebase <base>` → re-verify base SHA → `git merge --squash <branch>` → semantic `git commit` | Rebase clean; pre-merge `git status` clean |
| 5. Auto-push | AI worker | `git push origin main` | Non-fast-forward fails loudly; never force-pushes |
| 6. Cleanup | AI worker | `mahavishnu worktree prune-merged --one-off <path>` + `git branch -d <ephemeral>` | Classifier returns `merged` |
| 7. Publish | Human | `crackerjack run -p <level>` + version bump + tag + `git push origin --tags` | `feedback-bodai-push-is-user-controlled` still applies for tag + version bump |

## Cross-references

- **Spec (source of truth for the workflow):**
  `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
  — §"The Workflow" (7 stages), §4.1–4.6 (component contracts),
  §"Failure Modes", §REQ-008 (deliverable verification).
- **Spec plan (implementation plan):**
  `docs/superpowers/plans/2026-10-03-trunk-based-agent-review.md`
  — the 4-plan decomposition that shipped this workflow.
- **Sibling decision (auto-push governance):**
  `.claude/decisions/2026-10-03-mainautopush.md` (REQ-007) — the
  exception that allows stage 5 to push `origin/main` after a
  successful squash-merge; cross-linked (not amended inline) from
  `feedback-bodai-push-is-user-controlled`.
- **Memory (forward ref, ships with Task 4.4):**
  `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-merge-workflow.md`
  — the workflow contract surfaced for CLAUDE.md readers and
  dual-stored via `mcp__session-buddy__store_reflection` with tags
  `["feedback", "merge-workflow", "trunk-based-agent-review"]`.
- **Implementation:**
  - `mahavishnu/core/merge_to_main.py::run_pipeline()` — orchestration
    module invoked by both surfaces.
  - `mahavishnu/core/dev_log.py::write_entry()` — audit-log writer
    (`<get_dev_log_path()>/<YYYY-MM-DD>-<branch-slug>.md`) with
    session-buddy dual-store.
  - `mahavishnu/core/paths.py::get_dev_log_path()` — dev-log path
    resolver honoring `XDG_STATE_HOME`.
  - `.claude/hooks/agent-merge-on-end.py` — SessionEnd hook entry
    point (primary surface for in-session merges).
  - `.claude/commands/merge-to-main.md` — slash command body (manual
    surface; `Skill(skill="merge-to-main", ...)` is the
    MiniMax-compatible equivalent).
- **Local config (REQ-010):**
  `~/.zshenv` exports `MAHAVISHNU_AUTO_MERGE=1` (default-on per user
  choice; `MAHAVISHNU_AUTO_MERGE=0` opt-out).
- **Related worktree convention:**
  `~/.claude/CLAUDE.md` §"Worktree location preference" — the XDG
  path the workflow's stage-1 worktrees resolve to.
