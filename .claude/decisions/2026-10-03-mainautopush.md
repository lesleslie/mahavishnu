---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: mainautopush
---

# Main auto-push — narrow exception to user-controlled push

## Context

The repo-wide rule `feedback-bodai-push-is-user-controlled` (CC memory) holds
that `git push` is a **user-controlled step** for every Bodai ecosystem repo:
agents merge locally and the user owns publishing. The rule was written after
a 2026-08-26 incident in oneiric where a dispatched merge agent's default
template included `git push origin main` and the push landed before a STOP
message arrived.

The 2026-10-03 spec `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
introduces a single-purpose, mechanically-gated branch-to-`main` workflow in
this repo. The workflow's stage 5 is `git push origin main`, executed only by
the Python module invoked from the SessionEnd hook or the `/merge-to-main`
slash command, only on `main`, only after stages 1–4 (worktree → branch →
ensemble review → `crackerjack run -v` → squash-merge) complete successfully.

This decision doc is the source of truth for that exception. It amends (does
not delete) `feedback-bodai-push-is-user-controlled` via **cross-link**, not
inline amendment — the memory stays the canonical default; this doc is the
canonical exception. Spec §4.6 is a summary of this doc.

## Decision rule

1. **Permitted push, in scope:** `git push origin main`, only on the local
   `main` branch, only after stages 1–4 of the workflow defined in
   `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
   complete successfully, only by the Python module invoked from one of:
   - `.claude/hooks/agent-merge-on-end.py` (SessionEnd hook)
   - `.claude/commands/merge-to-main.md` (slash command body)
   - `mahavishnu/core/merge_to_main.py::run_pipeline()` when called directly
     from the test harness or operator tooling (rare; documented for
     completeness).
2. **What is NOT auto-pushed:**
   - Ephemeral branches (e.g. `fix-ty-errors`, `agent-<short>`, worktree
     branches created by `git worktree add`).
   - Tags (e.g. `v0.32.0`).
   - Any branch other than `main`.
   - Any remote other than `origin`.
   - Force-pushes of any kind, including `--force-with-lease`.
3. **Divergence handling:** if `git push origin main` returns a non-fast-forward
   error, the Python module captures the error verbatim, writes a failure
   entry to the audit log (with `push.result: "diverged"`), surfaces the
   failure via stderr (e.g.
   `Hook output: origin/main has diverged; local=<sha> remote=<sha>. Pull + resolve + retry, or rebase your worktree on origin/main and re-merge.`),
   and does **not** retry, force-push, rebase, or merge. Manual resolution
   only.
4. **Recovery options** (documented for the user; not automated):
   - `git fetch && git rebase origin/main && git push origin main` — rewrites
     local commits as fast-forward onto origin.
   - `git fetch && git reset --hard origin/main` — **discards** the squash
     work; user must re-run stages 1–4.
5. **No-remote case:** if `git remote` returns empty, the push is a no-op;
   the module logs `push.result: "no_remote"` and exits 0. This is the only
   silent-success path.
6. **Opt-out:** `MAHAVISHNU_AUTO_MERGE=0` in the shell disables the SessionEnd
   auto-invocation. The `/merge-to-main` slash command still works (explicit
   user invocation) but bypasses the env-var gate.
7. **All other push types** (tags, force-push, non-origin remotes,
   non-`main` branches) remain user-controlled per
   `feedback-bodai-push-is-user-controlled` and are NOT covered by this
   decision.

## Threat model

| Threat | Mitigation |
|---|---|
| **Remote `main` has diverged** between stages 4 and 5 (operator or another session pushed in the interim) | Push returns non-FF; captured verbatim; surfaced via stderr; no retry, no force-push, no rebase. User resolves manually. |
| **Accidental force-push** (e.g. template drift introduces `--force`) | The module's push command is a hard-coded string `git push origin main` with no flags. Crackerjack and review both gate on the squash step completing first; any flag in the push string would fail review. Belt-and-braces: spec §4.6 forbids force-pushes of any kind. |
| **Replay / reuse of a successful audit-log entry** to justify a later push | Audit-log entries are appended-only per `mahavishnu/core/dev_log.py::write_entry()`. The push command's scope (only on `main`, only after stage 4 succeeded) is enforced at execution time, not derived from the audit log. |
| **Push auth/network failure** (non-FF error aside) | Module exits non-zero; audit log records `push.result: "error:<message>"`. User retries after resolving auth/network. |
| **GitHub branch protection rejects direct push to `main`** | Module surfaces the message verbatim (HTTP 403 with protection error). User disables protection or configures a bypass. |
| **Concurrent merges** (two sessions both squash into local `main`, both push) | Git's ref lock on merge serializes the squash. Second push hits the FF check and fails; user resolves. No data loss. |
| **Push invocation outside the workflow** (e.g. an agent copies the command into its checklist) | The push command is only invoked by `mahavishnu/core/merge_to_main.py::run_pipeline()` at stage 5. Direct CLI invocation by a subagent is out of scope; if it occurs, it falls under `feedback-bodai-push-is-user-controlled` (i.e. the default rule applies and the push should not happen). |
| **Spec drift** (a future spec loosens this rule without updating this doc) | `superseded_by` field; `last_reviewed` date; the spec's REQ-007 cross-link check. A spec change that expands auto-push beyond this scope requires a new decision and a `superseded_by` reference here. |

## Cross-references

- **Amends (by cross-link, NOT inline amendment):**
  `feedback-bodai-push-is-user-controlled` — the default rule this exception
  narrows.
- **Spec source:** `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
  §4.6 (push rule summary) and §REQ-007 (deliverable verification).
- **Implementation:**
  - `mahavishnu/core/merge_to_main.py::run_pipeline()` — stage 5 push.
  - `.claude/hooks/agent-merge-on-end.py` — SessionEnd hook entry point.
  - `.claude/commands/merge-to-main.md` — slash command body.
- **Audit trail:**
  `mahavishnu/core/dev_log.py::write_entry()` writes each push outcome with
  `push.result: ok | diverged | error:<message> | no_remote`. Akosha picks
  up via the existing `dev_log.entry_written` event.
- **Sibling decision (workflow doc):**
  `.claude/decisions/2026-10-03-trunk-based-agent-review.md` (REQ-008) —
  the workflow that owns this push rule.
- **Related memory (future, Task 4.4):**
  `feedback-bodai-merge-workflow.md` — the workflow contract this decision
  is one part of.

## Notes

- The spec uses `2026-10-03-main-autopush.md` in §4.6 and §REQ-007 (with a
  hyphen between `main` and `autopush`); the file written to disk uses
  `2026-10-03-mainautopush.md` (no hyphen) per the implementer brief's
  filename convention. Both refer to the same governance amendment; the
  on-disk name is canonical for the `cat`-based demonstrable check in REQ-007.
- This decision is co-delivered with REQ-007 and ships in the same atomic
  commit as the worktree → branch → review → gate → squash workflow
  implementation. A future commit that loosens or removes the rule must
  set `superseded_by:` to the new decision file.
