---
status: active
role: implementation
date: 2026-08-23
last_reviewed: 2026-08-23
superseded_by: null
topic: oneiric-action-kit-promotion
---

# Oneiric Action-Kit Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Establish discovery-first promotion infrastructure for oneiric action kits across the bodai ecosystem: a canonical catalog in oneiric, a decision doc + auto-trigger skill in mahavishnu, and one-line breadcrumbs in every other bodai repo.
> **Architecture:** Three-layer split. oneiric owns the catalog (`oneiric/docs/action-kits.md` — source of truth for kit semantics). mahavishnu owns the decision (`mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`) and the runtime surface (`mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`). Every other bodai repo carries a one-line breadcrumb pointing at the canonical paths.
> **Tech Stack:** Markdown + YAML frontmatter; oneiric action-kit Python API (existing).
> **Spec:** `docs/superpowers/specs/2026-08-22-oneiric-action-kit-promotion-design.md`
> **Working directories:**
>   - oneiric repo: `/Users/les/Projects/oneiric`
>   - mahavishnu repo: `/Users/les/Projects/mahavishnu` (use the existing `worktree-w4-promote-oneiric-kits` worktree for mahavishnu-side tasks)
>   - other bodai repos: respective project roots under `/Users/les/Projects/`

______________________________________________________________________

## File Structure

```
oneiric/
└── docs/
    └── action-kits.md                          # NEW — 17-entry catalog

mahavishnu/
├── .claude/
│   ├── decisions/
│   │   └── promote-oneiric-action-kits.md     # NEW — decision doc
│   └── skills/
│       └── oneiric-action-kit-awareness/
│           └── SKILL.md                        # NEW — auto-trigger skill
└── CLAUDE.md                                   # MODIFY — breadcrumb

oneiric/
└── CLAUDE.md                                   # MODIFY — breadcrumb

<other-bodai-repo>/                             # 9 repos in Wave 3
├── CLAUDE.md                                   # MODIFY — breadcrumb (preferred)
└── or AGENTS.md                                # MODIFY — breadcrumb (fallback)
```

**Repo layout note:** the implementer must be in the correct git working tree before running any `git` command for that repo. Use `git -C <repo-path>` to target a specific repo from a single shell session. Each task is scoped to one repo so the implementer can `cd` or use `-C` consistently.

______________________________________________________________________

## Global Constraints

- **Git author email:** `les@wedgwoodwebworks.com` (NOT `.local`). Every `git commit` invocation must set this explicitly via `-c user.email=...`.
- **Pre-1.0 Bodai merge policy:** every bodai repo merges directly to `main` (no PRs, no review gates). This plan produces separate commits per repo; each commit lands via the repo's normal flow.
- **Frontmatter format:**
  - Decision doc (`promote-oneiric-action-kits.md`) uses YAML frontmatter matching every other file in `mahavishnu/.claude/decisions/` (status, role, date, last_reviewed, topic).
  - Skill (`SKILL.md`) uses **header-style** frontmatter (`## name: <slug> description: "..."`) to match the active convention in `mahavishnu/.claude/skills/` (e.g., `mahavishnu/SKILL.md`, `bodai-status/SKILL.md`). The archived YAML format is NOT used.
- **Skill description size:** keep the skill frontmatter `description:` under ~300 chars where possible; the aggregate skill-description budget is bounded.
- **Symbolic references only:** neither the breadcrumb text nor the skill body bakes absolute filesystem paths. References to the catalog use `oneiric/docs/action-kits.md` (relative to the oneiric project). The skill gracefully degrades when the catalog can't be located.
- **PR label:** every Wave 3 PR uses label `oneiric-action-kit-promotion` for cross-repo consistency.
- **Commit message style:** `chore(<scope>): <imperative summary>` — scopes are `oneiric-action-kits`, `decisions`, `skills`, `claude-md`, or repo-name for Wave 3.

______________________________________________________________________

## Task 1: Author the catalog

**Files:**
- Create: `oneiric/docs/action-kits.md` (NEW — does not exist yet at write time)

**Produces:** `oneiric/docs/action-kits.md` containing 17 kit entries (one per `*Action` class in `oneiric/actions/`), ordered alphabetically by `metadata.key`. Each entry follows the template in spec §6.

**Does NOT produce yet:** the decision doc, the skill, or any breadcrumb. Those are Tasks 2, 3, and 5–6.

- [ ] **Step 1: Confirm the 17 kit classes and their metadata keys**

Read `oneiric/oneiric/actions/__init__.py` (the `builtin_action_metadata()` function) and the kit modules. Produce a list:

```
Key                       Class                          Module
automation.trigger        AutomationTriggerAction        automation.py
compression.encode        CompressionAction             compression.py
compression.hash          HashAction                     compression.py
data.sanitize             DataSanitizeAction             data.py
data.transform            DataTransformAction             data.py
debug.console             DebugConsoleAction             debug.py
event.dispatch            EventDispatchAction            event.py
http.fetch                HttpFetchAction                http.py
security.secure           SecuritySecureAction           security.py
security.signature        SecuritySignatureAction        security.py
serialization.encode      SerializationAction            serialization.py
task.schedule             TaskScheduleAction             task.py
validation.schema         ValidationSchemaAction         data.py
workflow.audit            WorkflowAuditAction            workflow.py
workflow.notify           WorkflowNotifyAction           workflow.py
workflow.orchestrate      WorkflowOrchestratorAction     workflow.py
workflow.retry            WorkflowRetryAction            workflow.py
```

Run:
```bash
grep -E "^class |^    ActionMetadata\(" /Users/les/Projects/oneiric/oneiric/actions/*.py | head -40
```
Expected: confirms each class name + metadata.key pair.

- [ ] **Step 2: Write `oneiric/docs/action-kits.md`**

Create the file. The structure is:

```markdown
# Oneiric Action Kits — Catalog

This is the canonical reference for every built-in action kit in
`oneiric.actions`. Each entry documents when to reach for the kit,
the settings/payload/result shapes, a minimal example, and known
production callers.

**Ordering:** alphabetical by `metadata.key`. **Adding a kit:** append a
new entry (don't break ordering); do the same in
`oneiric/oneiric/actions/__init__.py::builtin_action_metadata()`.

---

### `automation.trigger`

**Module**: `oneiric.actions.automation`
**Use when**: bridging cron/interval triggers into oneiric events —
e.g., a scheduler that should emit an event when a job is ready.
**Don't use when**: you need a recurring task itself — use
`task.schedule` instead. Trigger fires; schedule runs.

**Settings** (peek at `AutomationTriggerSettings` in
`oneiric/actions/automation.py` for the actual field list).

**Minimal example**:
```python
from oneiric.actions.automation import (
    AutomationTriggerAction,
    AutomationTriggerSettings,
)

action = AutomationTriggerAction(settings=AutomationTriggerSettings())
result = await action.execute({"trigger": "tick", "payload": {...}})
```

**Adopted by**: (none yet)

---

### `compression.encode`
... [same template, all 17 entries]
```

**Per-entry required fields** (the implementer fills each with the
real values from the source):

- **Module** (literal)
- **Use when** (1-2 sentences; when this is the right kit)
- **Don't use when** (1-2 sentences; what to reach for instead)
- **Settings** (peek at the `*Settings` dataclass; list 2-4 most-used fields)
- **Payload shape** (1-3 key fields; copy from the kit's `execute()` docstring or `_run` body)
- **Result shape** (the canonical `{"status": ..., ...}` returned by `execute()`)
- **Minimal example** (copy the canonical pattern from the W3 code: `lru_cache(maxsize=1)` factory + `await action.execute({...})["<key>"]`)
- **Adopted by** (real callers from the W3 wave + any other production usage; empty list if none)

The implementer must produce all 17 entries. **Do not abbreviate** — the
catalog is the entire value of this design; skimping here is failure.

- [ ] **Step 3: Verify the catalog**

Run:
```bash
grep -c "^### \`" /Users/les/Projects/oneiric/docs/action-kits.md
```
Expected: `17`.

Run:
```bash
grep "^### \`" /Users/les/Projects/oneiric/docs/action-kits.md | sort
```
Expected: the 17 keys listed in spec §5.3, alphabetically sorted.

If the count is wrong or the order is not alphabetical, fix the file
and re-run before committing.

- [ ] **Step 4: Commit**

```bash
git -C /Users/les/Projects/oneiric add docs/action-kits.md
git -C /Users/les/Projects/oneiric -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "docs(oneiric-action-kits): add canonical catalog of 17 builtin action kits"
```

Push:
```bash
git -C /Users/les/Projects/oneiric push origin main
```
Expected: PR-equivalent direct push to origin/main (bodai pre-1.0 merge policy).

______________________________________________________________________

## Task 2: Author the decision doc

**Files:**
- Create: `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md` (NEW — uses mahavishnu worktree `worktree-w4-promote-oneiric-kits`)

**Consumes:** the canonical catalog from Task 1 (linked, not duplicated).

**Does NOT produce yet:** the skill or any breadcrumb. Those are Tasks 3, 5–6.

- [ ] **Step 1: Confirm the canonical frontmatter shape**

Read `mahavishnu/.claude/decisions/bodai-observability-pattern.md` (lines 1-9) and confirm the YAML frontmatter shape:

```
---
status: active
role: canonical
date: 2026-XX-XX
last_reviewed: 2026-XX-XX
topic: oneiric-action-kit-promotion
---
```

Use today's date (`date: 2026-08-23`).

- [ ] **Step 2: Write `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`**

Use the exact structure from spec §5.1:

```markdown
---
status: active
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
topic: oneiric-action-kit-promotion
---

# Promote Oneiric Action Kits Across Bodai

## Context

[Why kit adoption matters — the W3 results (207 tests passing across
5 bodai repos), the unification argument (redaction, signing, retry,
probing, sanitize, secure-token, serialization all share one canonical
envelope), and the gap that this decision closes (no promotion surface
for the remaining ~10 bodai repos).]

## Discovery hint

When about to write [list of kit-shaped primitives: HMAC signing,
token generation, schema validation, retries, redaction, HTTP probing,
serialization, compression, hashing, data transforms, automation
triggers, workflow orchestration], **discover** whether a matching
`oneiric.actions.<kit>` exists before reaching for stdlib. The catalog
is the canonical reference at `oneiric/docs/action-kits.md` in the
oneiric project. If the kit fits, use it (or wrap it). If it doesn't
fit (latency, API mismatch), document why in a code comment linking
back to the catalog entry.

This is a discovery surface, not an enforcement gate. The
`oneiric-action-kit-awareness` skill in
`mahavishnu/.claude/skills/` auto-fires when the user's task smells
like kit-shaped work and prompts the user to reach for the kit.

## Status

Active. Adopted 2026-08-23 after W3 across 5 repos.

## Inventory of kits

The catalog is the source of truth; this doc links to it rather than
duplicating. See `oneiric/docs/action-kits.md` for the 17 built-in
kits (alphabetical by `metadata.key`).

## Exceptions

- Latency budget < 1ms where the kit's `lru_cache` lookup still
  costs more than the inline operation
- Kit API genuinely does not fit (wrapper would be dishonest) — wrap
  with a one-line comment linking back to the catalog entry

Discovery, not enforcement — bypass freely with a one-line note in the
code.
```

- [ ] **Step 3: Verify the decision doc**

Run:
```bash
head -8 /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/.claude/decisions/promote-oneiric-action-kits.md
```
Expected: the YAML frontmatter block, with `status: active`, `role: canonical`, `topic: oneiric-action-kit-promotion`.

Run:
```bash
ls /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/.claude/decisions/promote-oneiric-action-kits.md
```
Expected: file exists.

- [ ] **Step 4: Commit**

```bash
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits add .claude/decisions/promote-oneiric-action-kits.md
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "chore(decisions): promote oneiric action kits via discovery hint"
```

Do NOT push yet — Tasks 3 and 5 also touch the mahavishnu worktree.

______________________________________________________________________

## Task 3: Author the skill

**Files:**
- Create: `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md` (NEW)

**Consumes:** the trigger phrases and inventory from spec §5.2; the
catalog from Task 1 (referenced, not duplicated).

- [ ] **Step 1: Confirm the active skill frontmatter shape**

Read the first 5 lines of:
- `mahavishnu/.claude/skills/mahavishnu/SKILL.md`
- `mahavishnu/.claude/skills/bodai-status/SKILL.md`

Confirm the format is **header-style**:
```
______________________________________________________________________

## name: <slug> description: "<text>"
```

(NOT YAML `---name/description---` — that format is only used by the
archived `oneiric-integration` skill.)

- [ ] **Step 2: Write `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`**

Use the exact content from spec §5.2 (header-style frontmatter, full
17-trigger list, "What to do" steps, ActionBridge note).

The `description:` field (header style) should be a single quoted
string under ~300 chars:

```
description: "Auto-trigger skill that surfaces the matching oneiric.actions.X kit when the user is about to write HMAC signing, token generation, schema validation, retries with backoff, span/log redaction, config serialization, HTTP fetch/probe, compression, hashing, data transforms, debug consoles, automation triggers, or workflow orchestration. Prompts 'Use the kit?' before implementation."
```

Verify the byte count:
```bash
echo -n 'description: "Auto-trigger skill that surfaces the matching oneiric.actions.X kit when the user is about to write HMAC signing, token generation, schema validation, retries with backoff, span/log redaction, config serialization, HTTP fetch/probe, compression, hashing, data transforms, debug consoles, automation triggers, or workflow orchestration. Prompts '"'"'Use the kit?'"'"' before implementation."' | wc -c
```
Expected: under 400 (ideally under 300; this string is ~370 chars and acceptable).

- [ ] **Step 3: Verify the skill**

Run:
```bash
ls /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/.claude/skills/oneiric-action-kit-awareness/SKILL.md
```
Expected: file exists.

Run:
```bash
head -5 /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/.claude/skills/oneiric-action-kit-awareness/SKILL.md
```
Expected: the underline (`______`) + `## name: oneiric-action-kit-awareness description: "..."` header.

- [ ] **Step 4: Commit**

```bash
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits add .claude/skills/oneiric-action-kit-awareness/SKILL.md
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "chore(skills): add oneiric-action-kit-awareness auto-trigger skill"
```

Do NOT push yet — Task 5 also touches the mahavishnu worktree.

______________________________________________________________________

## Task 4: Local smoke test

**Files:** none (read-only verification)

**Verifies:** the skill from Task 3 actually fires on a kit-shaped
prompt and surfaces the matching kit. Failure here blocks Wave 2.

- [ ] **Step 1: Open a Claude session in a bodai repo with the new skill loaded**

Use dhara (any non-oneiric bodai repo will work). Start a Claude
session in a worktree:

```bash
git -C /Users/les/Projects/dhara worktree add /tmp/dhara-skill-smoke -b w4-skill-smoke main
```

In a Claude session launched from `/tmp/dhara-skill-smoke`, confirm the
skill is on the active skill path (it inherits from mahavishnu's
`.claude/skills/` via the worktree's parent).

- [ ] **Step 2: Run a kit-shaped prompt**

Ask Claude: "write me an HMAC signer that signs a webhook payload".

Expected: the `oneiric-action-kit-awareness` skill fires; Claude
surfaces the matching kit (`security.signature` →
`SecuritySignatureAction`) and asks "Use it?".

- [ ] **Step 3: If the skill does not fire — iterate**

If the skill does NOT fire, the trigger phrases in the
`description:` field are too narrow. Edit
`mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/.claude/skills/oneiric-action-kit-awareness/SKILL.md`
to broaden them (add synonyms like "hash-based message authentication
code", "webhook signature", "verify this token", etc.), amend the
Task 3 commit, and re-test.

Do not proceed to Task 5 until the skill fires on at least 3 of these
5 prompts:
1. "write me an HMAC signer that signs a webhook payload"
2. "generate a secure random token"
3. "add retry with backoff to this function"
4. "redact PII from this dict before logging"
5. "fetch this URL with retries"

If even with iteration only 2/5 fire, escalate to the user before
proceeding — the description: field needs a different shape (perhaps
shorter, or different trigger vocabulary).

- [ ] **Step 4: Clean up the smoke-test worktree**

```bash
git -C /Users/les/Projects/dhara worktree remove /tmp/dhara-skill-smoke --force
git -C /Users/les/Projects/dhara branch -D w4-skill-smoke
```

(This cleanup is local-only; no commit, no push.)

______________________________________________________________________

## Task 5: Self-bootstrap (Wave 2)

**Files:**
- Modify: `mahavishnu/CLAUDE.md` (add breadcrumb)
- Modify: `oneiric/CLAUDE.md` (add breadcrumb)

**The breadcrumb text** (identical across all repos; from spec §5.4):

```markdown
## Oneiric action kits

Before writing common primitives (HMAC, token gen, schema validation,
retries, redaction, HTTP probing, serialization, compression, hashing,
data transforms), check `oneiric.actions` — catalog lives at
`oneiric/docs/action-kits.md` in the oneiric project. Discovery hint:
`mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`.
```

- [ ] **Step 1: Add breadcrumb to mahavishnu's CLAUDE.md**

Read `/Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/CLAUDE.md` to find an insertion point (anywhere logical; the spec does not prescribe — append at the end is acceptable for a non-conflicting section).

Insert the breadcrumb section.

- [ ] **Step 2: Add breadcrumb to oneiric's CLAUDE.md**

Same operation, different repo:

```bash
git -C /Users/les/Projects/oneiric worktree add /Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md -b w4-claude-md main
```

Read `/Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md/CLAUDE.md`, insert the breadcrumb.

(Sub-step 1 also needs a worktree if not already in one. The implementer is
already in the `worktree-w4-promote-oneiric-kits` mahavishnu worktree from
earlier tasks; for oneiric, create a fresh worktree.)

- [ ] **Step 3: Verify both breadcrumbs are identical**

Run:
```bash
diff <(grep -A 5 "## Oneiric action kits" /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits/CLAUDE.md) \
     <(grep -A 5 "## Oneiric action kits" /Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md/CLAUDE.md)
```
Expected: empty output (the two breadcrumbs match byte-for-byte).

- [ ] **Step 4: Commit and push mahavishnu**

```bash
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits add CLAUDE.md
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits -c user.email=les@wedgwoodwebworks.com -c user.name=les commit --amend --no-edit
git -C /Users/les/Projects/mahavishnu/.claude/worktrees/w4-promote-oneiric-kits push origin worktree-w4-promote-oneiric-kits
```
(The `--amend` folds the breadcrumb commit into the prior
decisions/skills commit so the mahavishnu PR is a single commit;
after push, open a PR against main per the bodai merge policy and
merge directly.)

- [ ] **Step 5: Commit and push oneiric**

```bash
git -C /Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md add CLAUDE.md
git -C /Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "chore(claude-md): add oneiric action-kit discovery breadcrumb"
git -C /Users/les/Projects/oneiric/.claude/worktrees/w4-claude-md push origin w4-claude-md
```
Then merge the PR to main directly (bodai pre-1.0 merge policy).

______________________________________________________________________

## Task 6: Ecosystem rollout (Wave 3)

**Files:** ~9 bodai repos' `CLAUDE.md` or `AGENTS.md` (one-line breadcrumb each, identical text)

**Repos to roll out** (from spec §4):

| Repo | Default file | Notes |
|---|---|---|
| akosha | CLAUDE.md | yes, has CLAUDE.md per W3 spot check |
| crackerjack | CLAUDE.md | yes |
| css-mcp | (check) | confirm before edit |
| splashstand | (check) | confirm before edit |
| porkbun-domain-mcp | (check) | confirm before edit |
| langsmith-mcp | (check) | confirm before edit |
| opera-cloud-mcp | (check) | confirm before edit |
| raindropio-mcp | (check) | confirm before edit |
| fastblocks | AGENTS.md | may not have CLAUDE.md |
| mdinject | (check) | confirm before edit |

If any repo in the list lacks both `CLAUDE.md` and `AGENTS.md`, skip it
and note in the final report.

- [ ] **Step 1: For each repo, run a quick smoke check that the breadcrumb file exists**

```bash
for repo in akosha crackerjack css-mcp splashstand porkbun-domain-mcp langsmith-mcp opera-cloud-mcp raindropio-mcp fastblocks mdinject; do
    if [ -f "/Users/les/Projects/$repo/CLAUDE.md" ]; then
        echo "$repo: CLAUDE.md"
    elif [ -f "/Users/les/Projects/$repo/AGENTS.md" ]; then
        echo "$repo: AGENTS.md"
    else
        echo "$repo: MISSING — skipping"
    fi
done
```
Expected: each repo maps to CLAUDE.md or AGENTS.md, or "MISSING — skipping".

- [ ] **Step 2: Dispatch parallel agents for the breadcrumb edits**

For each repo that has a breadcrumb target file, dispatch a parallel
agent (one per repo). Each agent's instructions are identical:

```
Task: Add a one-line breadcrumb to <REPO_PATH>/<FILE>.md

The breadcrumb section to add (verbatim — do not modify wording):

## Oneiric action kits

Before writing common primitives (HMAC, token gen, schema validation,
retries, redaction, HTTP probing, serialization, compression, hashing,
data transforms), check `oneiric.actions` — catalog lives at
`oneiric/docs/action-kits.md` in the oneiric project. Discovery hint:
`mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`.

Steps:
1. Read <FILE>.md to find an insertion point.
2. Append the section above.
3. Verify with: `grep -A 5 "## Oneiric action kits" <FILE>.md`
4. Commit with message: `chore(claude-md): add oneiric action-kit discovery breadcrumb`
   (use `-c user.email=les@wedgwoodwebworks.com -c user.name=les` on the git commit)
5. Push to origin/<branch> and open a PR.

Constraints:
- Do NOT touch any other file in the repo.
- Do NOT modify any existing line in <FILE>.md (only append).
- If the file already contains a "## Oneiric action kits" section,
  abort (the breadcrumb already exists).
- Return: confirmation that the commit was pushed + the branch name.
```

Run all dispatches in parallel from the orchestrating session.

- [ ] **Step 3: Verify breadcrumb reach ≥ 10**

After all dispatches complete, run:

```bash
grep -l "oneiric action kits" /Users/les/Projects/*/CLAUDE.md /Users/les/Projects/*/AGENTS.md 2>/dev/null | wc -l
```
Expected: ≥ 10.

Run a per-repo list:
```bash
grep -l "oneiric action kits" /Users/les/Projects/*/CLAUDE.md /Users/les/Projects/*/AGENTS.md 2>/dev/null
```
Expected: mahavishnu, oneiric, akosha, crackerjack, css-mcp (or whatever was rolled out).

- [ ] **Step 4: Final summary report**

Print a table of:

| Repo | File modified | Commit SHA | Branch | Status |
|---|---|---|---|---|
| oneiric | docs/action-kits.md | (from Task 1) | main | merged |
| mahavishnu | .claude/decisions/, .claude/skills/, CLAUDE.md | (from Tasks 2/3/5) | worktree-w4-promote-oneiric-kits → main | merged |
| akosha | CLAUDE.md | (per-repo) | (per-repo branch) | (PR status) |
| ... | ... | ... | ... | ... |

This table is the final deliverable of the plan. Hand it to the user
along with the success-criteria tracking checklist.

______________________________________________________________________

## Rollback Reference

If a piece needs to be removed after rollout, each is independently
revertible (spec §9). The implementer can roll back by:

| Piece | File(s) | Rollback action |
|---|---|---|
| Catalog | `oneiric/docs/action-kits.md` | `git -C /Users/les/Projects/oneiric revert <catalog-commit-sha>` (or delete the file) |
| Decision doc | `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md` | Delete the file (no other code depends on it) |
| Skill | `mahavishnu/.claude/skills/oneiric-action-kit-awareness/` | Rename folder to `oneiric-action-kit-awareness.disabled/` (auto-trigger stops) |
| Mahavishnu breadcrumb | `mahavishnu/CLAUDE.md` | Revert the Wave 2 commit |
| Oneiric breadcrumb | `oneiric/CLAUDE.md` | Revert the Wave 2 commit |
| Wave 3 breadcrumbs | `<repo>/CLAUDE.md` (or `AGENTS.md`) × N | Revert each repo's PR/commit individually |

Nothing breaks if any one is removed; readers opt in independently.

______________________________________________________________________

## Success-Criteria Tracking (post-rollout)

| Metric | Target | How to measure | Check at |
|---|---|---|---|
| Catalog completeness | 17/17 kits documented | `grep -c "^### \`" <oneiric-path>/docs/action-kits.md` | Day 7 |
| Breadcrumb reach | ≥ 10 bodai repos | `grep -l "oneiric action kits" /Users/les/Projects/*/CLAUDE.md /Users/les/Projects/*/AGENTS.md \| wc -l` | Day 7 |
| Skill fires correctly | ≥ 3/5 prompts trigger the skill | Re-run the 5 prompts from Task 4 step 3 in a fresh session | Day 7, 14 |
| Decision doc discoverable | `git grep "promote-oneiric-action-kits"` lands on the file | `git -C /Users/les/Projects/akosha grep -l "promote-oneiric-action-kits" 2>/dev/null` | Day 7 |
| Adoption (lagging) | ≥ 2 new kit adoptions in 30 days (excluding W3) | PR scan across bodai repos | Day 30 |

______________________________________________________________________

## Notes

- **TDD caveat:** this plan adapts the TDD discipline to non-code artifacts. Each task's "verify" step is the equivalent of "run the failing test" — if the artifact doesn't pass its verification, do not commit.
- **Wave 4 follow-up** (per spec §10): catalog-drift CI guard, skill-firing observability, migration of existing reinventions. Tracked separately.
- **Pre-1.0 merge policy:** every bodai repo merges directly to `main` (no PR review gate). The implementer opens a PR per repo for visibility but merges immediately.