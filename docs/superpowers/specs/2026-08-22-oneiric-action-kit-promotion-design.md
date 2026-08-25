---
status: active
role: implementation
topic: oneiric-action-kit-adoption
date: 2026-08-22
last_reviewed: 2026-08-22
superseded_by: null
blocks_on: []
---

# Oneiric Action-Kit Adoption: Promotion Infrastructure

**Status:** Approved
**Date:** 2026-08-22
**Author:** Claude Code + les
**Unblocks:** W4+ kit-adoption waves across the rest of the bodai ecosystem

## 1. Problem

Wave 3 (W3) adopted five oneiric action kits across five bodai core repos
(mailgun-mcp, akosha, session-buddy, dhara, mahavishnu). 207 tests pass;
redaction, signing, retry, probing, sanitize, secure-token, and
serialization now share one canonical envelope across components.

But W3 reached only 5 repos out of ~15 in the bodai ecosystem. The
remaining repos — `crackerjack`, `css-mcp`, `splashstand`,
`porkbun-domain-mcp`, `langsmith-mcp`, `opera-cloud-mcp`, `raindropio-mcp`,
`fastblocks`, `mdinject`, plus any future bodai repos — have no
promotion surface that says "use the kits first". A contributor
working in any of those repos who needs an HMAC signer or a retry loop
will reach for `cryptography` or hand-rolled backoff, not for
`oneiric.actions.security.SecuritySignatureAction` or
`oneiric.actions.workflow.WorkflowRetryAction`, because nothing in their
context tells them the kit exists.

There is no enforcement today. There is no discoverability either.

## 2. Goals

1. **Discoverability-first.** A contributor about to write kit-shaped
   code surfaces the matching kit before reaching for stdlib or
   reinventing.
2. **Single source of truth for kit semantics.** Per-kit documentation
   lives in exactly one place (the oneiric repo). Every other surface
   links to it instead of duplicating.
3. **Whole-ecosystem reach.** The promotion infrastructure reaches every
   bodai repo (~15 today) without per-repo maintenance burden.
4. **Cheap to roll back.** Each piece is independently removable; no
   piece is load-bearing for the others.
5. **No enforcement (yet).** Discovery surfaces only; lint/CI rules and
   reviewer agents are explicitly out of scope.

## 3. Non-Goals

- Lint or CI rules that block reinvention (Approach C; deferred)
- A reviewer agent that flags kit-shaped reinvention in PRs (deferred)
- A repo-wide audit script that scans for kit-shaped patterns
  (Approach B; deferred — can be a follow-up wave)
- Migrating existing reinventions inside the non-W3 repos (deferred —
  promotion first, migration as a follow-up wave)
- Updating oneiric's own action kit code (out of scope; this design is
  only about *promoting* existing kits)
- Per-repo adoption tests (already exists in the 5 W3 adopters; new
  tests only when new kits are adopted)

## 4. Architecture

Three-layer split, mirroring the existing
`mahavishnu/.claude/decisions/bodai-observability-pattern.md` pattern:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Source of truth: ONEIRIC                                            │
│    oneiric/docs/action-kits.md         (catalog; per-kit entries)    │
└───────────────┬─────────────────────────────────────────────────────┘
                │  linked from
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Decision + runtime: MAHAVISHNU                                      │
│    mahavishnu/.claude/decisions/promote-oneiric-action-kits.md       │
│      → the WHY (use kits first; what "kit-shaped code" looks like)   │
│    mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md   │
│      → the WHEN (auto-trigger skill; runtime discovery)              │
└───────────────┬─────────────────────────────────────────────────────┘
                │  cited by
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Breadcrumbs: every other bodai repo                                 │
│    <repo>/CLAUDE.md  or  AGENTS.md  ← one-line addition              │
│    (akosha, dhara, session-buddy, crackerjack, mailgun-mcp,          │
│     css-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp,         │
│     opera-cloud-mcp, raindropio-mcp, fastblocks, mdinject, …)        │
└─────────────────────────────────────────────────────────────────────┘
```

Three jobs, three owners:

- **oneiric** owns *what* the kits are (single source of truth; can
  evolve as kits ship)
- **mahavishnu** owns *why* and *when* (decision doc = durable rule;
  skill = runtime surface)
- **per-repo CLAUDE.md/AGENTS.md** is *who reads it* (cheap reach into
  the contributor's working context)

## 5. Components

### 5.1 Decision doc — `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`

Matches the existing pattern in `mahavishnu/.claude/decisions/`
(see `bodai-observability-pattern.md` for the closest analog).
**Use this exact frontmatter** (matches every other file in
`mahavishnu/.claude/decisions/`):

```markdown
---
status: active
role: canonical
date: 2026-08-22
last_reviewed: 2026-08-22
topic: oneiric-action-kit-promotion
---

# Promote Oneiric Action Kits Across Bodai

## Context
[Why kit adoption matters — the W3 results, the 207 tests passing,
the unification argument across 5 bodai repos.]

## Discovery hint
When about to write [list of kit-shaped primitives: HMAC signing, token
generation, schema validation, retries, redaction, HTTP probing,
serialization, compression, hashing, data transforms, automation
triggers, workflow orchestration], **discover** whether a matching
`oneiric.actions.<kit>` exists before reaching for stdlib. The catalog
is the canonical reference at `oneiric/docs/action-kits.md` in the
oneiric project on this filesystem. If the kit fits, use it (or wrap it).
If it doesn't fit (latency, API mismatch), document why in a code
comment linking back to the catalog.

This is a discovery surface, not an enforcement gate. The skill
(`oneiric-action-kit-awareness` in `mahavishnu/.claude/skills/`)
auto-fires when the user's task smells like kit-shaped work and prompts
the user to reach for the kit.

## Status
Active. Adopted 2026-08-22 after W3 across 5 repos.

## Inventory of kits (deferred to oneiric/docs/action-kits.md)
[Link, not duplication. The catalog is the source of truth; this
decision doc links to it.]

## Exceptions
[List of legitimate non-kit cases: e.g., when latency budget is < 1ms
and the kit adds an lru_cache lookup; when the kit's API doesn't fit
and a wrapper would be dishonest. Discovery, not enforcement — bypass
freely with a one-line note.]
```

### 5.2 Skill — `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`

Auto-trigger skill. **Use header-style frontmatter** to match the
active convention in `mahavishnu/.claude/skills/` (see
`mahavishnu/SKILL.md:1-3`, `bodai-status/SKILL.md:1-3`):

```markdown
______________________________________________________________________

## name: oneiric-action-kit-awareness description: "Auto-trigger skill that surfaces the matching oneiric.actions.X kit when the user is about to write HMAC signing, token generation, schema validation, retries with backoff, span/log redaction, config serialization, HTTP fetch/probe, compression, hashing, data transforms, debug consoles, automation triggers, or workflow orchestration. Prompts 'Use the kit?' before implementation. Catalog at oneiric/docs/action-kits.md in the oneiric project."

# Oneiric Action-Kit Awareness (auto-trigger)

When user is about to write code that maps to a known kit, surface the
kit before they reinvent.

## When this fires
- HMAC, signing, signature verification → SecuritySignatureAction (`security.signature`)
- Token / secret / random string generation → SecuritySecureAction (`security.secure`)
- JSON Schema validation → ValidationSchemaAction (`validation.schema`)
- Retry with backoff, jitter → WorkflowRetryAction (`workflow.retry`)
- PII / secret redaction in logs, spans, traces → DataSanitizeAction (`data.sanitize`)
- JSON / YAML serialize / deserialize → SerializationAction (`serialization.encode`)
- HTTP fetch / probe with retries → HttpFetchAction (`http.fetch`)
- Audit log / event emission → WorkflowAuditAction (`workflow.audit`)
- Cron / interval / scheduled task → TaskScheduleAction (`task.schedule`)
- Webhook / workflow notification → WorkflowNotifyAction (`workflow.notify`)
- Event dispatch / pub-sub → EventDispatchAction (`event.dispatch`)
- Compression / encoding (gzip, base64, etc.) → CompressionAction (`compression.encode`)
- Hashing (md5, sha*, blake2b) → HashAction (`compression.hash`)
- Generic data transforms (rename keys, coerce types) → DataTransformAction (`data.transform`)
- Debug / console output (formatted traces) → DebugConsoleAction (`debug.console`)
- Trigger automation (cron-to-event glue) → AutomationTriggerAction (`automation.trigger`)
- Multi-step workflow orchestration → WorkflowOrchestratorAction (`workflow.orchestrate`)

## What to do
1. Locate the catalog at `oneiric/docs/action-kits.md` in the oneiric
   project on the developer's filesystem (path varies by setup; if not
   findable, surface "couldn't find the oneiric catalog; please paste
   the kit name from §When this fires above" and continue).
2. Surface to the user: "This looks like `<kit>` (`<metadata.key>`);
   canonical pattern is in the oneiric catalog. Use it?"
3. If yes, write the wrapper. If no (latency, fit), document why in a
   code comment linking back to the catalog entry.

Note: kit invocations go through `oneiric.actions.ActionBridge` (in
`bridge.py`); not all kits require it directly, but the bridge is the
canonical runtime surface for cross-process kit calls.
```

### 5.3 Catalog — `oneiric/docs/action-kits.md`

**17 kit entries** (one per `*Action` class) covering every kit in
`oneiric/actions/`. The kit classes live across 10 modules
(`automation`, `compression`, `data`, `debug`, `event`, `http`,
`security`, `serialization`, `task`, `workflow`); the other 5 files in
`oneiric/actions/` (`__init__.py`, `bootstrap.py`, `bridge.py`,
`metadata.py`, `payloads.py`) are infrastructure (re-exports, resolver
glue, metadata model, payload normalization) and not kit-shaped. Note
that this file does not yet exist at the time of writing; it is created
in Wave 1 step 1.

**Catalog ordering**: alphabetical by `metadata.key` (e.g.,
`automation.trigger` before `compression.encode` before
`compression.hash` …). This makes the catalog predictable and lets the
skill grep it deterministically. New kits added to oneiric must be
appended to maintain alphabetical order.

Each entry follows the same template (see Section 6).

### 5.4 Per-repo breadcrumb

One line each, ~15 repos. Placed in `CLAUDE.md` for repos that have
one, otherwise `AGENTS.md` (per a W3 spot check, every bodai repo has
at least one). The breadcrumb text is **identical** across repos (no
per-repo path substitution) so Wave 3 step 8's parallel dispatch works.

```markdown
## Oneiric action kits

Before writing common primitives (HMAC, token gen, schema validation,
retries, redaction, HTTP probing, serialization, compression, hashing,
data transforms), check `oneiric.actions` — catalog lives at
`oneiric/docs/action-kits.md` in the oneiric project. Discovery hint:
`mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`.
```

## 6. Catalog Entry Template

Every kit entry in `oneiric/docs/action-kits.md` follows the same
template, so the catalog is scannable and the skill can grep it:

```markdown
### `<key>`  (e.g. `security.signature`)

**Module**: `oneiric.actions.security`
**Use when**: writing HMAC signing/verification, webhooks, message
authentication, JWT-style MAC operations.
**Don't use when**: you need an asymmetric signature (RSA / Ed25519)
— use `cryptography` directly; the kit only handles HMAC.

**Settings** (dataclass):
- `secret: str` — shared secret
- `algorithm: str = "sha256"` — hashlib name
- `encoding: str = "utf-8"`

**Payload shape**:
\`\`\`python
{
    "mode": "sign" | "verify",
    "secret": "...", "message": "...", "signature": "...",
    "algorithm": "sha256",        # optional
    "constant_time": True,        # verify-mode only; default True
}
\`\`\`

**Result shape**:
\`\`\`python
{"status": "ok", "signature": "abc..."}       # sign
{"status": "ok", "valid": True}              # verify
{"status": "error", "valid": False, "error": "..."}  # verify failure
\`\`\`

**Minimal example**:
\`\`\`python
from oneiric.actions.security import SecuritySignatureAction

action = SecuritySignatureAction(settings=SecuritySignatureSettings(secret="..."))
sig = (await action.execute({"mode": "sign", "secret": "...", "message": msg}))["signature"]
\`\`\`

**Adopted by** (real-world usage; proves it works):
- mailgun-mcp `verify_webhook_signature` (replay-protected)
- session-buddy `CrossProjectAuth.sign_message`
```

The **Adopted by** line is social proof — every kit that has at least
one production caller lists it. As more repos adopt, this becomes a
self-reinforcing network effect (visible evidence the kit works).

## 7. Rollout Sequence

Four waves; each wave is one or more PRs per repo. The catalog file
**does not yet exist**; Wave 1 step 1 creates it.

### Wave 1 — Authoring (~half a day)

1. Write `oneiric/docs/action-kits.md` — 17 kit entries, alphabetical
   by `metadata.key`. **Commit and push this to the oneiric repo** as a
   docs-only PR (separate from mahavishnu's PRs).
2. Write `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`
   using the frontmatter and template in §5.1.
3. Write `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`
   using the header-style frontmatter and template in §5.2.
4. **Verify locally** — open a Claude session in a bodai repo (e.g.
   dhara) with the new skill loaded, ask "write me an HMAC signer",
   confirm the skill fires and surfaces the kit. If the skill does
   not fire: tighten the trigger phrases in the `description:` field
   (e.g., add synonyms for the kit action), re-test, and iterate. Do
   not commit until the smoke test passes.

### Wave 2 — Self-bootstrap (~15 min)

5. Add the breadcrumb to mahavishnu's own `CLAUDE.md` (PR to mahavishnu).
6. Add the breadcrumb to oneiric's `CLAUDE.md` (PR to oneiric; same
   oneiric PR as step 1's commit is fine if preferred).
7. Merge both PRs to origin/main.

### Wave 3 — Ecosystem rollout (~1 hr)

8. For each remaining bodai repo, add the breadcrumb (single PR per
   repo, no other changes). Use parallel agent dispatch (one agent
   per repo) since the breadcrumb text is identical. PR label:
   `oneiric-action-kit-promotion` (consistent across repos).
9. Verify with `git grep -l "oneiric action kits"` across the bodai
   project tree — should hit ≥10 repos.

### Wave 4 — Follow-up (separate planning wave; out of scope for this design)

Promised in §10 risk mitigations; tracked separately:

- **CI guard for catalog drift**: when oneiric adds a new kit, fail
  the PR if `oneiric/docs/action-kits.md` is not updated.
- **Skill firing observability**: lightweight counter that records
  when the skill fires, so the day-7/day-14 success-criteria checks
  don't require manual testing.
- **Migrate existing reinventions** in non-W3 repos — separate
  audit-and-migrate wave.

## 8. Success Criteria

Measurable; checked at day 7, day 14, and day 30 post-rollout.

| Metric | Target | Day-7 / Day-14 check | How to measure |
|---|---|---|---|
| Catalog completeness | 17/17 kits documented | Day 7 only | `grep -c "^### \`" <oneiric-path>/docs/action-kits.md` == 17 |
| Breadcrumb reach | ≥10 bodai repos have the breadcrumb | Day 7 | `git grep -l "oneiric action kits"` across bodai tree ≥ 10 |
| Skill fires correctly | Skill triggers on the kit-shaped prompts in a Claude session with the skill loaded | Day 7, 14 | Manual smoke test: run 5 prompts (HMAC, token gen, retry, sanitize, fetch) in a session with the new skill loaded |
| Decision doc discoverable | `git grep "promote-oneiric-action-kits"` from any bodai repo lands on the right file | Day 7 | Manual verification (filename is literal — do not rename the file without updating this needle) |
| Adoption (lagging) | ≥2 new kit adoptions in the next 30 days (excluding W3) | Day 30 | PR scan |

**Skill smoke-test definition** (was ambiguous in earlier draft): "A
Claude session with the new skill loaded" = a session in
`mahavishnu/.claude/worktrees/<branch>/` (so mahavishnu's
`.claude/skills/oneiric-action-kit-awareness/` is on the active skill
path) with no other bodai-specific skills pre-loaded. Run prompts like
"write me an HMAC signer" / "generate a secure token" / "add retry
with backoff" / "redact PII from this dict" / "fetch this URL with
retries". Pass = skill surfaces the matching kit + asks "Use it?"
for ≥3 of the 5 prompts. (Note: no automated instrumentation in Wave
1; this is a manual test. Wave 4 follow-up adds observability.)

## 9. Rollback Plan

Each piece is independently removable.

- Decision doc: revert the file; nothing downstream depends on it
- Skill: rename folder to `oneiric-action-kit-awareness.disabled/`;
  auto-trigger stops
- Catalog: just delete the file
- Breadcrumbs: trivial per-repo revert

Nothing breaks if any one is removed; readers opt in independently.

## 10. Risks & Open Items

- **Catalog drift**: If oneiric ships a new kit without updating the
  catalog, the skill will silently miss it. Mitigation: when Wave 3 is
  complete, add a CI guard that fails if `oneiric/actions/*.py` adds a
  new module without a matching catalog entry. (Out of scope for this
  design; noted for follow-up.)
- **Path hardcoding**: The breadcrumb text uses a *symbolic* reference
  (`oneiric/docs/action-kits.md` in the oneiric project) rather than
  an absolute filesystem path. This avoids stale breadcrumbs when the
  oneiric project moves on disk — the breadcrumb is identical across
  repos, and only the skill body needs to know the developer's actual
  filesystem layout (it gracefully degrades when the catalog can't be
  located). Mitigation: keep the breadcrumb identical across repos; if
  the catalog moves, only the skill body and any direct linkers need
  updates.
- **Skill over-trigger**: The skill's `description:` is broad. If it
  fires on every minor edit, contributors will tune it out. Mitigation:
  scope the trigger phrases narrowly (the 11 list items in §5.2).
  Iterate after first month of usage data.
- **Agent prompts never reach the skill**: If a contributor works in a
  Claude session with skill discovery off, the skill is invisible.
  Mitigation: documented as a limitation; discovery-first only works if
  discovery is on (default in mahavishnu).
- **No CLAUDE.md in some repos**: If a future bodai repo has neither
  `CLAUDE.md` nor `AGENTS.md`, the breadcrumb has nowhere to go.
  Mitigation: documented as a hard prerequisite for adoption waves;
  the spot check confirms every current bodai repo has at least one.

## 11. References

- W3 deliverables across 5 repos (mailgun-mcp, akosha, session-buddy,
  dhara, mahavishnu) — already merged to origin/main
- `mahavishnu/.claude/decisions/bodai-observability-pattern.md` —
  template analog
- `mahavishnu/docs/adr/001-use-oneiric.md` — pre-existing oneiric
  promotion for config + logging (this design extends it to action
  kits)
- `mahavishnu/.claude/skills/.archive/oneiric-integration/` —
  previous, archived skill attempt; signals one prior promotion
  experiment that did not stick (this design supersedes it)
