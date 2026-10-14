---
status: active
role: canonical
kind: decision
date: 2026-10-13
last_reviewed: 2026-10-13
superseded_by: null
topic: prepush-consolidation-gate
---

# Pre-push Consolidation Gate — further narrowing of the auto-push exception

## Context

`feedback-bodai-push-is-user-controlled` (CC memory) holds that `git push` is
user-controlled for every Bodai ecosystem repo. The exception for
`git push origin main` after a successful squash-merge lives in
`docs/decisions/2026-10-03-mainautopush.md`. This decision adds a
**further** narrowing: in addition to stages 1–4 succeeding, the auto-push
is held back until co-located worktrees are consolidated (merged, pruned,
mid-review, or explicitly abandoned). This prevents a class of failure the
current contract does not address: a push that ships one worktree's
squash-commit while a sibling worktree's WIP gets stranded on local `main`.

This decision amends (does not delete) the auto-push exception in
`2026-10-03-mainautopush.md` via **cross-link**, not inline amendment —
the same pattern as the push memory's relationship to the autopush
decision.

## Decision rule

In addition to the existing stage 1–4 conditions in
`2026-10-03-mainautopush.md`, `git push origin main` is further authorized
only after the pre-push consolidation gate is satisfied. The gate runs in
`mahavishnu/core/merge_to_main.py::run_pipeline()` between stage 4
(squash-merge) and stage 5 (auto-push).

### Gate predicate

For the current repo, the gate performs two checks:

#### 1. Co-located-worktree check

The gate enumerates **co-located worktrees** of the current repo: any
worktree directory under `<worktree-base>/<basename-of-cwd>/`. The
worktree base is resolved per `~/.claude/CLAUDE.md` §"Worktree location
preference" — precedence: `MAHAVISHNU_WORKTREE_BASE_PATH` env var, then
`~/.local/state/mahavishnu/worktrees`, then per-repo `.worktrees/`. (The
gate MUST call `mahavishnu/core/paths.py::get_worktree_base_path()`;
the CI guard at `tests/unit/test_worktree_base_path_resolution.py`
enforces this.) For each co-located worktree, the gate accepts one of
four states:

- **(a) Branch merged or fast-forwarded.** The worktree's branch HEAD
  is an ancestor of local `main` HEAD (per
  `git merge-base --is-ancestor <wt-head> main`).
- **(b) Worktree pruned.** No entry in `git worktree list --porcelain`
  for the worktree's path.
- **(c) Mid-review in progress.** A `.review-state.json` exists with
  `stages_completed` non-empty and `stage_failed: null` (an active
  session is in stage 2 or 3 of the pipeline).
- **(d) Explicitly abandoned.** A `.review-state.json` exists with
  `stage_failed` non-null.

Any co-located worktree whose branch is **not** in one of the four
states holds back the push. The held-back list is surfaced in stderr
and recorded in the dev-log entry.

#### 2. Pending-commit eligibility check

For every commit in `git log origin/main..main`, the gate verifies
the commit shape:

- **(α) Squash-merge commit (binding).** The commit subject matches
  the squash-merge template `merge: <branch> -> <base>` (per
  `run_squash_merge`).
- **(β) Fast-forward replay (binding).** The commit is a fast-forward replay of a worktree branch that was fully merged into
  local `main` prior to the replay (parent SHA on local `main`).
- **(γ) Authorized release-cycle version bump (binding).** The commit
  touches only `pyproject.toml` `[project].version` (or analogous
  release files) and is the only commit in the local-but-not-remote
  range. This is the canonical authorized non-squash direct-to-`main`
  operation per `feedback-mcp-common-version-bump-is-user` (CC
  memory). Expanding this list requires a new memory entry and a
  `superseded_by` reference on this decision; it is not a
  per-implementer decision.

A commit that does not match (α), (β), or (γ) holds back the push.

### Held-back behavior

When the gate holds back:

- **Stage 6 (cleanup) is skipped.** The branch and worktree must
  remain until the push lands; otherwise the squash-commit gets
  orphaned. This deviates from the current "always-cleanup"
  semantics in `run_pipeline()`.
- **Sticky-failure marker is written.** `.review-state.json` for the
  current worktree gets
  `stage_failed: "stage_5_push_held_back_by_consolidation_gate"` and
  `stages_completed` is appended with
  `stage_5_consolidation_gate_held_back`. This makes subsequent
  `agent-merge-on-end.py` invocations see
  `is_sticky_failed() == True` and skip the pipeline until the user
  resolves. Without this marker, the gate's `EXIT_OK` return would
  be a silent-deferred-push failure mode — this deviates from the
  `MAHAVISHNU_AUTO_MERGE=1` loud-failure contract that the user
  explicitly chose per the workflow's spec §4.2.
- **The dev-log entry is written with
  `push.result: "error:consolidation_gate_held_back"`** (reusing the
  existing `error:<message>` enum value from
  `2026-10-03-mainautopush.md` line 100 — no new value added to the
  parent's enum). The entry also includes
  `held_back_sibling_worktrees: [<list>]` or
  `held_back_pending_commits: [<list>]` as applicable.
- **stderr surfaces the hold-back** with the held-back worktree
  paths or ineligible commit SHAs.
- **The pipeline returns `EXIT_OK = 0`.** The squash-merge
  succeeded locally; only the push is deferred. The hook contract at
  `.claude/hooks/agent-merge-on-end.py:197–207` already collapses
  "skip" and "full success" to 0; the held-back path is morally a
  "skip the push."

### Re-evaluation strategy

The gate is re-checked on the **next SessionEnd in any co-located
worktree of the same repo**. As sibling worktrees advance
(squash-merge to local `main`) or get pruned, local `main` advances
and the gate re-evaluates against the new state. If the held-back
worktree's branch becomes an ancestor of local `main` (via another
worktree's merge), the next SessionEnd clears the gate and the push
fires, consolidating all held-back work.

If the user wants to retry the push without re-running review / gate
/ squash, they invoke `Skill(skill="merge-to-main", args={"--no-consolidation-gate", "--branch": "<held-back-branch>"})`
from any worktree. The `--no-consolidation-gate` slash-command flag
bypasses the gate (operator escape hatch for emergency pushes).

### Override semantics

- `MAHAVISHNU_AUTO_MERGE=0` continues to skip the **entire pipeline**
  (no merge, no gate check, no push). The gate runs inside the
  pipeline; it is **not** bypassed by the env-var opt-out.
- `/merge-to-main --no-push` continues to allow explicit
  user-controlled pushes (bypassing the gate by not invoking the
  push stage).
- `/merge-to-main --no-consolidation-gate` (new flag) bypasses the
  gate while still running the push stage. Operator escape hatch.

### What is NOT gated

- The gate does **not** apply to manual `git push origin main`
  invocations by the operator. Such pushes fall under
  `feedback-bodai-push-is-user-controlled` (the default rule; the
  push should not happen unless the operator explicitly initiated it).
- The gate does **not** apply to non-`origin` remotes, non-`main`
  branches, tags, or force-pushes. These are explicitly out of scope
  per `2026-10-03-mainautopush.md` rule 2.
- The gate does **not** apply to direct `git push` outside the
  trunk-based workflow (e.g. a subagent copies
  `git push origin main` into its checklist). Such invocations fall
  under `feedback-bodai-push-is-user-controlled`.

## Threat model

| Threat | Mitigation |
|---|---|
| **Sibling worktree abandoned with unmerged WIP** → push silently deferred → squash-commits stranded on local `main` | Co-located-worktree check (state d); sticky-failure marker prevents re-attempt without user acknowledgement. Held-back state surfaces in stderr and the dev log. |
| **Two sessions race on the same repo's `main`** (concurrent merges) | Co-located-worktree check (state a): the second session's gate sees the first session's squash-merge as an ancestor of local `main` and passes. Re-mitigates `2026-10-03-mainautopush.md` row 6. |
| **Spec drift loosens the squash-merge requirement** (a future spec drops stage 4 verification) | Eligibility check (α) is binding: a non-squash commit cannot pass the gate unless (γ) authorizes it. The squash-merge requirement is enforced at the gate, not at the spec. |
| **Tampered `.review-state.json`** (an agent in a sibling worktree writes `stage_failed: "user_abandoned"` to make the gate treat its WIP as abandoned) | For v1, the gate accepts any non-null `stage_failed` value. Documented as a known gap; the upgrade path is a signed dev-log cross-reference (analogous to the eligibility check). Filed as Tier 2 follow-up in `feedback-bodai-merge-workflow-followups`. |
| **Pre-push logic invoked outside the workflow** (a subagent copies the gate into its checklist) | The gate is only invoked by `mahavishnu/core/merge_to_main.py::run_pipeline()` between squash-merge and push. Direct CLI invocation by a subagent is out of scope; if it occurs, it falls under `feedback-bodai-push-is-user-controlled`. Mirrors `2026-10-03-mainautopush.md` row 7. |
| **Audit-log replay** to justify a later push | The gate writes its own `dev_log.py` entry on every evaluation. A forged prior entry cannot make a new push "appear authorized" because the gate re-reads sibling-worktree state at execution time, not from the audit log. Mirrors `2026-10-03-mainautopush.md` row 3. |
| **No-remote case** (no `origin` configured) | Push is a silent no-op success per `2026-10-03-mainautopush.md` rule 5. The gate is bypassed (no remote → no push needed). |

## Recovery options for held-back pushes

The user can resolve a held-back push by any of:

1. **Merge the held-back sibling worktree** via its own
   `/merge-to-main` invocation. The sibling's squash-merge advances
   local `main`; the held-back gate clears on the next SessionEnd in
   any co-located worktree.
2. **Prune the held-back sibling worktree** via
   `mahavishnu worktree prune-merged` (existing tier rubric). The
   worktree's branch is deleted; the gate's state (b) — no entry in
   `git worktree list --porcelain` — clears.
3. **Mark the sibling's `.review-state.json` with
   `stage_failed: "user_abandoned"`** to acknowledge the WIP is
   intentionally abandoned. The gate's state (d) clears.
4. **Bypass the gate** via `/merge-to-main --no-consolidation-gate`
   for emergency pushes. The push executes immediately; the gate
   does not re-evaluate.

## Cross-references

- **Amends (by cross-link, NOT inline amendment):**
  - `feedback-bodai-push-is-user-controlled` (CC memory) — the
    default rule; this decision is a further narrowing on the
    auto-push conditions.
  - `feedback-mcp-common-version-bump-is-user` (CC memory) — the
    canonical authorized non-squash direct-to-`main` operation
    (eligibility check γ).
  - `feedback-bodai-merge-workflow-followups` (CC memory) — the
    workflow contract this decision is one part of.
- **Sibling decision (push governance):**
  `docs/decisions/2026-10-03-mainautopush.md` (REQ-007) — the
  exception that allows stage 5 to push `origin/main`; this
  decision adds a pre-push *condition* to that exception. The threat
  model re-mitigates `2026-10-03-mainautopush.md` rows 3, 4, 5, 6,
  and 7.
- **Sibling decision (workflow doc):**
  `docs/decisions/2026-10-03-trunk-based-agent-review.md` — the
  7-stage workflow this gate slots into; the gate is a new sub-step
  between stage 4 (squash-merge) and stage 5 (auto-push). Stage 6
  (cleanup) is conditionally skipped when the gate holds back.
- **Sibling decision (branch protection):**
  `docs/decisions/2026-10-03-main-branch-protection.md` — the
  GitHub-side hardening; the gate complements it with a local-side
  pre-push check.
- **Spec source:**
  `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
  §4.6 (push rule summary), §REQ-007 (governance-amendment cross-link
  requirement), §"Failure Modes" (a new row for "Sibling worktree has
  unmerged WIP; consolidation gate holds back").
- **Implementation:**
  - `mahavishnu/core/merge_to_main.py::run_pipeline()` — gate
    invocation point (between squash-merge and push); new
    `_run_consolidation_gate()` and `_write_held_back_log()`
    helpers; `make_review_state()` extended with the sticky-failure
    marker; arg-parser gains `--no-consolidation-gate`; stage 6 is
    conditionally skipped on hold-back.
  - `mahavishnu/core/dev_log.py::write_entry()` — audit-log writer;
    `push.result: "error:consolidation_gate_held_back"` round-trips
    via the existing `_format_frontmatter`.
  - `mahavishnu/core/paths.py::get_worktree_base_path()` —
    worktree-base resolution; the gate MUST call this helper (per
    existing CI guard test).
  - `.claude/hooks/agent-merge-on-end.py` — no code changes; the
    gate is internal to `run_pipeline()`. The sticky-failure marker
    written by the gate is read by the hook's existing
    `is_sticky_failed()` check.
  - `.claude/commands/merge-to-main.md` — adds
    `--no-consolidation-gate` flag.
- **Test plan:** `tests/unit/core/test_merge_to_main.py` — new tests
  for gate pass, hold-back, lineage, co-located worktree,
  sticky-failure, and `--no-consolidation-gate` bypass.
- **Related worktree convention:** `~/.claude/CLAUDE.md` §"Worktree
  location preference" — the XDG path the gate's co-located-worktree
  enumeration walks.

## Notes

- The on-disk filename is
  `2026-10-13-prepushconsolidationgate.md` (no hyphens between
  `prepush` / `consolidation` / `gate`) per the existing convention
  in `2026-10-03-mainautopush.md` (canonical filename omits the
  hyphen in `main-autopush`).
- The held-back path intentionally returns `EXIT_OK = 0` per the
  user's explicit choice (multi-subagent review, 2026-10-13). The
  sticky-failure marker is the mechanism that converts what would
  otherwise be a silent-deferred-push into an explicit
  user-acknowledgement-required state.
- The eligibility check (γ) reuses
  `feedback-mcp-common-version-bump-is-user` as the canonical
  authorized-operation anchor; expanding the authorized list requires
  a new memory entry (per Bodai pre-1.0 governance: replace, don't
  extend).
- A follow-up plan will harden the `.review-state.json` accept list
  (currently accepts any non-null `stage_failed`) by requiring a
  signed dev-log cross-reference. Filed as a Tier 2 follow-up in
  `feedback-bodai-merge-workflow-followups`.