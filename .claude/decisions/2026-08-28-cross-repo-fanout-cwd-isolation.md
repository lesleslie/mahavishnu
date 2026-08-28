---
status: active
role: canonical
date: 2026-08-28
last_reviewed: 2026-08-28
superseded_by: null
topic: cross-repo-fanout-cwd-isolation
---

# Cross-repo fanout CWD isolation

One-line summary: `Workflow({script: parallel()})` and similar
parallel-fanout dispatches assume the parent session is in a clean
main checkout; dispatching from inside any worktree silently fails
because subagents inherit the parent's CWD, see `EnterWorktree`
refuse, and either fall through to raw `git worktree add <abs-path>`
at the wrong location (location leak) or land in the parent's
existing worktree (silent-fallthrough leak).

## Context

On 2026-08-26 a 5-way Phase 3 fanout (dhara, session-buddy, akosha,
crackerjack, mahavishnu) was dispatched from a session already inside
`/Users/les/Projects/mahavishnu/.claude/worktrees/plan-a-review-fixes`.
The session's CWD was inherited by every child agent. When the agents
attempted `EnterWorktree`, the tool refused ("Already in a worktree
session") because Claude Code's per-session worktrees live under
`.claude/worktrees/` of the parent's repo, not the target's. The
agents fell through to raw `git worktree add <abs-path>` or to
working in the parent's existing worktree. Result: 0 implementations
landed, ~660k subagent tokens wasted, and the workflow's
"succeeded: 2/5" aggregate hid the failure because agents
self-reported `main_landed_locally: true` against pre-existing main
commits while flagging every implementation boolean as false.

A 2026-08-27 cleanup removed 16 abandoned worktrees created by a
similar 2026-08-21 fanout — all in `/Users/les/Projects/`, none
inside any `.claude/worktrees/`, all `ahead=0` on their branches.
Same mechanism.

The `feedback-workflow-cwd-leak-parallel-fanout` memory file carries
the worked detail and the `git worktree add /tmp/<branch>` recipe.
This decision codifies the rule; that memory keeps the incident
narrative. They should not duplicate.

## Decision rule

1. **Default to sequential per-repo dispatch** when the parent
   session's CWD might restrict child agent scope. Each dispatch is
   short-lived, isolated, and inherits no stale state from the
   previous one. Use parallel only when the parent is provably in a
   non-worktree context (e.g., a main checkout on a target repo).
2. **If parallel is required** (cross-repo work, tight time budget),
   the parent session MUST be in a clean main checkout of one of
   the fanout's target repos — NOT inside any Claude-Code-managed
   worktree. `ExitWorktree` before dispatching.
3. **For cross-repo fanouts where each agent's target repo differs
   from the parent's**, each agent MUST create its own worktree via
   raw `git worktree add` at a path OUTSIDE Claude-Code's session
   tree (default `$XDG_RUNTIME_DIR/mahavishnu/fanout/<session-id>/`,
   fallback `/tmp/<branch>`). See memory file
   `feedback-workflow-cwd-leak-parallel-fanout` for the recipe.
4. **Parallel-fanout aggregation MUST gate on THREE conditions**:
   (a) the schema's implementation booleans (catches silent-
   fallthrough — agents self-report `false` while lying about main);
   (b) `commit_sha.length >= 8` per agent (catches empty/null
   commit); (c) the target branch actually has new commits —
   `git -C <target-repo> rev-parse <branch>` against the pre-
   dispatch SHA (catches agents that landed in the parent's
   worktree without creating a new worktree at all).
5. **Cross-repo MCP dispatch is a separate concern.** This rule
   does NOT recommend `mcp__mahavishnu__pool_route_execute` over
   `Workflow({script: parallel()})` for CWD-leak reasons — that
   is an observability/routing improvement, not a leak fix. The
   leak is in Claude Code's dispatch, not Mahavishnu's. Mixing
   them creates drift-bundling (per `.claude/decisions/removed-scripts.md`).
6. **Layer 4 (PreToolUse hook + auto-trigger skill) was
   considered and DEFERRED.** The hook's false-positive risk for
   legitimate in-repo fanouts, AST-parsing fragility on the
   `script` payload, and Bun-runtime hardening requirement (per
   memory `claude-code-bun-hardened-runtime-stop-hook-enoent`) all
   push the cost above the value at this point. Revisit after this
   rule has demonstrably reduced incidents.

## Related coverage

- Memory `feedback-workflow-cwd-leak-parallel-fanout` — worked
  incident detail and the `git worktree add /tmp/<branch>` recipe.
  Link, do not duplicate.
- Memory `sdd-workspace-cwd-hijack` — sister CWD-leak for the SDD
  `subagent-driven-development` skill (`sdd-workspace` /
  `task-brief` write artifacts to the calling shell's CWD). Same
  root cause (CWD-inheritance); mitigation is `cd <repo> && bash
  <script>` before any SDD dispatch.
- `.claude/decisions/session-worktree-defaults.md` — opt-in
  per-session worktree isolation (`MAHAVISHNU_AUTO_WORKTREE=1`).
  Complementary, not duplicative: this decision is the rule for
  when isolation IS active but a fanout is still needed.
- `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` §2
  — same CWD-inheritance mechanism explains per-project
  `.mcp.json` scoping; the fanout CWD problem is the agent-
  dispatch analogue.
- `.claude/decisions/worktree-autoremove-policy.md` — narrow Rule 2
  amendment permitting explicitly invoked `worktree prune-merged`.
  Hooks and cron remain prohibited; cleanup of the
  `$XDG_RUNTIME_DIR/...` or `/tmp/<branch>` worktrees created under
  Rule 3 above is manual after the fanout completes.

## Status <!-- legacy status: Active — see YAML frontmatter -->

Active. Adopted 2026-08-28 after the 2026-08-27 cleanup of 16
abandoned worktrees from the 2026-08-21 fanout and the 2026-08-26
Phase 3 fanout incident. Supersedes no prior decision; complementary
to `session-worktree-defaults.md`.