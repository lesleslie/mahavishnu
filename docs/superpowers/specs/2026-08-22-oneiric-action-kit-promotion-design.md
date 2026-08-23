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
(see `bodai-observability-pattern.md` for the closest analog):

```markdown
## Context
[Why kit adoption matters — the W3 results, the 207 tests passing,
the unification argument across 5 bodai repos.]

## Decision rule
[Imperative: "When about to write [list of kit-shaped primitives],
reach for `oneiric.actions.<kit>` first. Catalog at <path>. If the kit
doesn't fit, write a wrapper that defers to the kit — do NOT
reimplement."]

## Status
Active. Adopted 2026-08-22 after W3 across 5 repos.

## Inventory of kits (deferred to oneiric/docs/action-kits.md)
[Link, not duplication.]

## Exceptions
[List of legitimate non-kit cases: e.g., when latency budget is < 1ms
and the kit adds an lru_cache lookup; when the kit's API doesn't fit
and a wrapper would be dishonest.]
```

### 5.2 Skill — `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`

Auto-trigger skill. The frontmatter `description:` lists the trigger
phrases; the body is short — when fired, it surfaces the catalog and
proposes the kit call.

```markdown
---
name: oneiric-action-kit-awareness
description: Use when about to write HMAC signing, token generation,
schema validation, retries with backoff, span/log redaction, config
serialization, HTTP fetch/probe, compression, hashing, data transforms,
debug consoles, automation triggers, or workflow orchestration.
Surfaces the matching oneiric.actions.X kit and prompts "Use the kit?"
before implementation.
---

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
1. Read the catalog at the absolute path baked into this skill body
   (e.g., `/Users/les/Projects/oneiric/docs/action-kits.md`) for the
   matching kit
2. Surface to the user: "This looks like `<kit>`; canonical pattern is:
   [snippet from catalog]. Use it?"
3. If yes, write the wrapper. If no (latency, fit), document why in a
   code comment linking back to the catalog.
```

### 5.3 Catalog — `oneiric/docs/action-kits.md`

**17 kit entries** (one per `*Action` class) covering every kit in
`oneiric/actions/`. The kit classes live across 10 modules
(`automation`, `compression`, `data`, `debug`, `event`, `http`,
`security`, `serialization`, `task`, `workflow`); the other 5 files in
`oneiric/actions/` (`__init__.py`, `bootstrap.py`, `bridge.py`,
`metadata.py`, `payloads.py`) are infrastructure (re-exports, resolver
glue, metadata model, payload normalization) and not kit-shaped.

Each entry follows the same template (see Section 6).

### 5.4 Per-repo breadcrumb

One line each, ~15 repos. Placed in `CLAUDE.md` for repos that have
one, otherwise `AGENTS.md` (per a W3 spot check, every bodai repo has
at least one).

```markdown
## Oneiric action kits

Before writing common primitives (HMAC, token gen, schema validation,
retries, redaction, HTTP probing, serialization), check
`oneiric.actions` — catalog at
`<absolute-path>/oneiric/docs/action-kits.md`. The rule of thumb lives
in `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`.
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

Three waves; each wave is a PR per repo.

### Wave 1 — Authoring (~half a day)

1. Write `oneiric/docs/action-kits.md` — 17 kit entries (one per
   `*Action` class in `oneiric/actions/`)
2. Write `mahavishnu/.claude/decisions/promote-oneiric-action-kits.md`
3. Write `mahavishnu/.claude/skills/oneiric-action-kit-awareness/SKILL.md`
4. **Verify locally** — open a Claude session in a bodai repo
   (e.g. dhara), ask "write me an HMAC signer", confirm the skill fires
   and surfaces the kit. No commits yet.

### Wave 2 — Self-bootstrap (~15 min)

5. Add the breadcrumb to mahavishnu's own `CLAUDE.md`
6. Add the breadcrumb to oneiric's `CLAUDE.md` (where the catalog
   lives — contributors of new kits should know)
7. Commit + push both to origin/main

### Wave 3 — Ecosystem rollout (~1 hr)

8. For each remaining bodai repo, add the breadcrumb (single PR per
   repo, no other changes). Use a parallel dispatch (one agent per
   repo) since the breadcrumb is identical.
9. Verify with `git grep -l "oneiric action kits"` across
   `/Users/les/Projects/` — should hit ≥10 repos.

## 8. Success Criteria

Measurable; checked 30 days post-rollout.

| Metric | Target | How to measure |
|---|---|---|
| Catalog completeness | 17/17 kits documented | `grep "^### \`" oneiric/docs/action-kits.md \| wc -l` == 17 |
| Breadcrumb reach | ≥10 bodai repos have the breadcrumb | `git grep -l "oneiric actions" /Users/les/Projects/*/CLAUDE.md /Users/les/Projects/*/AGENTS.md` ≥ 10 |
| Skill fires correctly | Skill triggers on ≥3 of the kit-shaped prompts in a clean Claude session | Manual smoke test (the W3 kit list above) |
| Decision doc discoverable | A `git grep "promote-oneiric-action-kits"` from any bodai repo lands on the right file | Manual verification |
| Adoption (lagging) | ≥2 new kit adoptions in the next 30 days (excluding W3) | PR scan |

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
- **Path hardcoding**: The breadcrumb references the catalog by
  absolute path. If the path changes (e.g., monorepo move), every
  breadcrumb goes stale. Mitigation: link to `oneiric/docs/action-kits.md`
  via repo-relative path in the breadcrumb text; agents can resolve to
  the actual working tree.
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