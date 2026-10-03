---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: main-branch-protection
---

# GitHub branch protection on `main` across the Bodai core-6

## Context

The Bodai core-6 repos (mahavishnu, akosha, session-buddy, crackerjack, oneiric,
mcp-common) had no remote-side branch protection on `main` as of 2026-10-03.
Before this decision, `git push --force origin main` would silently rewrite
the trunk, and `git push origin :main` would delete it.

`feedback-bodai-push-is-user-controlled` (CC memory) and
`2026-10-03-mainautopush.md` (sibling decision) govern **when** pushes
happen, but neither address what GitHub itself will or will not allow.
This decision fills the gap.

The pre-1.0 policy (per `bodai-pre-1.0-merge-policy.md`) is **direct merge to
`main`, no PRs**. Branch protection must therefore:
- Block the two catastrophic accidents (force-push, branch deletion)
- **NOT** require pull-request reviews (would break pre-1.0 direct-merge)
- **NOT** require status checks (no CI runs on any of the 6 yet)
- **NOT** enforce linear history (direct pushes bypass it anyway)
- Leave `enforce_admins: false` so the auto-push path in
  `2026-10-03-mainautopush.md` is not bricked for the owner

This is the **first** such rule. Future changes (e.g. adding required CI
status checks once `crackerjack run -v` gates run on GitHub Actions) are
amendments — they set `superseded_by:` in this doc and live as new decision
files.

## Decision rule

Apply the following JSON rule via `gh api PUT /repos/lesleslie/<repo>/branches/main/protection`
on all 6 Bodai core repos (`mahavishnu`, `akosha`, `session-buddy`,
`crackerjack`, `oneiric`, `mcp-common`):

```json
{
  "allow_force_pushes": false,
  "allow_deletions": false,
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_status_checks": null,
  "required_linear_history": null,
  "block_creations": false
}
```

### Per-setting rationale

| Setting | Value | Why |
|---|---|---|
| `allow_force_pushes` | `false` | **The headline protection.** Blocks `git push --force origin main` and `--force-with-lease`. Without this, an accidental `git push --force` could rewrite the entire trunk history. Cheap insurance; never legitimately needed on `main` post-merge. |
| `allow_deletions` | `false` | Blocks `git push origin :main` and the "Delete branch" UI button. Catastrophic-recovery insurance. The auto-push path never deletes; the merge hook never deletes; this only fires if a human typo-destroys the trunk. |
| `enforce_admins` | `false` | The owner (`lesleslie`) and any future admins must be able to direct-push. Setting `true` would brick `MAHAVISHNU_AUTO_MERGE=1` and `2026-10-03-mainautopush.md` stage 5. |
| `required_pull_request_reviews` | `null` | **Explicitly null**, not `{required_approving_review_count: 0}`. Per `bodai-pre-1.0-merge-policy.md`, the policy is direct merge; no PRs. If a future spec moves us to PR-based merges, this becomes an amendment with `required_approving_review_count: 1` + admin bypass = on. |
| `required_status_checks` | `null` | **Explicitly null.** None of the 6 repos run CI on GitHub Actions yet. When `crackerjack run -v` (or equivalent) starts gating merges via GitHub Actions, this becomes an amendment listing `contexts: ["crackerjack / fast_hooks"]` (or whatever the workflow produces). |
| `required_linear_history` | `null` | Direct pushes bypass this anyway; it only affects merge-button UI. Setting `true` would reject merge commits via the UI but does nothing for our direct-merge workflow. |
| `restrictions` | `null` | No push-restriction list. Anyone with write access can push. (Future amendment could narrow this to a `push` allowlist if write collaborators grow.) |
| `block_creations` | `false` | Allows creating new branches — required for the trunk-based workflow itself (`feat/*` branches must be push-able to exist at all). |

### Scope

- **Repos:** all 6 Bodai core repos owned by `lesleslie`. Non-core repos
  (e.g. `archive-org-mcp`, `www-mcp-servers`) are out of scope; they keep
  default protection (none). Apply per-repo when those repos join the
  core roster.
- **Branch:** `main` only. No protection on `feat/*`, `fix/*`, etc. —
  ephemeral branches need no protection; they're deleted post-merge by the
  trunk-based workflow.
- **Operating mode:** idempotent. Re-running the PUT with the same values
  is a no-op semantic. PUT with different values is the amendment path.

## Threat model

| Threat | Mitigation | Why this rule is sufficient |
|---|---|---|
| Accidental `git push --force origin main` from an agent or human | `allow_force_pushes: false` | GitHub's pre-receive hook rejects with HTTP 403 + clear error message; agent loop surfaces it. No history loss. |
| Accidental `git push origin :main` (branch deletion) | `allow_deletions: false` | Same — rejected by GitHub. Branch is the trunk; never legitimately deleted. |
| A future agent spec loosens `feedback-bodai-push-is-user-controlled` to allow force-pushes | The GitHub-side rule is independent of the agent-side rule. Even if a future spec allows it locally, GitHub still blocks it. Belt-and-braces. | Two independent layers of defense. |
| An admin (the owner) decides they need to force-push for a recovery | `enforce_admins: false` | Admins can temporarily relax via GitHub UI for a single recovery, then restore. Documented in the recovery section. |
| A future spec moves to PR-based merges | `required_pull_request_reviews` is `null`, not absent; amendment requires explicit decision + supersedes this doc | The null is a choice, not an oversight. The next person who changes it knows they're changing governance. |
| CI lands on these repos but the protection doesn't pick it up | `required_status_checks` is `null`, not absent; amendment requires explicit decision | Same — the null documents "no CI today"; amendment documents "CI added today". |

### Recovery from a legitimate force-push need

If the owner genuinely needs to force-push to `main` (e.g. rewrite a
botched merge that landed in the last few minutes):

1. **Locally:** GitHub UI → repo Settings → Branches → Branch protection
   rules → `main` → Edit → temporarily set `Allow force pushes` = true.
2. **Push:** `git push --force-with-lease origin main`.
3. **Restore:** Edit again → `Allow force pushes` = false. **Same
   commit, immediately.** Don't leave the relaxation in effect.

This is the only legitimate force-push path. Audit-log it (manual
entry to `mahavishnu/core/dev_log.py`) if your change is not reversible
from `git reflog` in <5 minutes.

## Cross-references

- **Amends (by cross-link, NOT inline amendment):** the **absence** of
  branch protection was the previous implicit default. This doc fills
  the gap; nothing is being deleted.
- **Co-delivered governance:**
  - `feedback-bodai-push-is-user-controlled` (CC memory) — the
    agent-side rule about when pushes happen.
  - `2026-10-03-mainautopush.md` (sibling decision) — the narrow
    exception that auto-pushes `main` after stages 1–4.
  - `bodai-pre-1.0-merge-policy.md` (CC memory) — direct-merge-to-`main`,
    no-PR policy that constrains this rule (no required reviews, no
    required status checks yet).
- **Trunk-based workflow spec:**
  `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
  — the workflow whose auto-merge path relies on this protection being
  just-strict-enough.
- **Implementation:** applied via `gh api -X PUT
  /repos/lesleslie/<repo>/branches/main/protection`. Live state on 6
  repos verified 2026-10-03.
- **Future amendments:** any change to the JSON rule (e.g. adding
  `required_status_checks`, switching `required_pull_request_reviews`
  from `null` to a count) is a new file under `2026-10-03-mainplus-*` or
  a similar topic-name, with `superseded_by:` set in this doc.

## Notes

- The rule was applied 2026-10-03 across all 6 core repos in one batch;
  this doc records the intent for future maintainers who will see the
  GitHub-side settings without context.
- `gh api` normalizes `required_linear_history` to `{enabled: false}` on
  GET regardless of what was PUT. Functionally equivalent to `null`.
  Don't be surprised by the verify-output asymmetry.
- Re-running the PUT is idempotent; no migration concerns if applied
  to additional repos later (e.g. as a core roster expands).
- The `/tmp/main_protection.json` working file used to apply the rule
  was a one-shot artifact; do not check it in. Repeated.
