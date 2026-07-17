---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: routing-composition
---

# Plan Template — Integration-Contract Required

> **Why this template exists**: features are being built but not wired into
> apps and workflows. This template makes wiring a first-class plan section.
> A plan is not "done" until every deliverable has an Integration Contract
> block, even if that block says "no wiring required (rationale: …)".

_See `docs/schemas/document-frontmatter-v1.md` for the schema definition._

## 1. Outcome

\<prompt: what user-observable change will exist when this plan ships?>

\<prompt: how will we know it succeeded — concrete metric, signal, or artifact?>

## 2. Goals

<numbered list of outcome-bearing goals>

## 3. Non-Goals

\<numbered list of explicitly-out-of-scope items — preempts feature creep>

## 4. Current Findings

\<prompt: what did we discover? citations to files, issues, metrics>

## 5. Implementation Phases

### Phase N: <name>

**Goal:**
**Tasks:**
**Exit criteria:**

#### Integration Contract ← REQUIRED for every deliverable in this phase

- **Triggered from**: \<prompt: what user action, schedule, or upstream
  event calls this? include exact entry-point symbol/path>
- **Returns to / updates**: \<prompt: what state, store, or downstream
  artifact does this mutate? include destination path>
- **Demonstrable by**: \<prompt: one concrete check (CLI command, HTTP
  request, log line, screenshot, test name) that proves the wiring
  works end-to-end>
- **Rollback signal**: \<prompt: what log line, metric, or alert tells
  us to revert? include threshold if applicable>
- **Observability added**: \<prompt: which OTel/metric/log signal was
  added so this wiring is visible in production>

## 6. Required Code Changes

<checkbox list of file paths grouped by package>

## 7. Validation Matrix

\<table: tool/command | expected outcome | evidence location>

## 8. Risks

\<table: risk | likelihood | mitigation>

## 9. Decision Rule

\<prompt: the rule that decides when this plan is "done enough" — used
when scope pressure forces a cut>

______________________________________________________________________

## Section-by-section guidance

The prompts above are placeholders. The notes below explain why each
section is non-negotiable and what a strong answer looks like.

### Integration Contract — Triggered from

*Forces a concrete entry point; without it, "wired" becomes ambiguous.*

A strong answer names the exact symbol, command path, MCP tool name, HTTP
route, or scheduler invocation that reaches the new code. Vague answers
("the user can call this") are treated as unwired.

### Integration Contract — Returns to / updates

*Prevents dead-write paths where code computes but never persists.*

A strong answer names the destination state, file, store, database row,
WebSocket channel, or downstream artifact. If the answer is "logs only"
or "no persistent effect," the deliverable is suspect — either it is a
diagnostic (label it as such) or it is missing a state destination.

### Integration Contract — Demonstrable by

*One checkable proof; if you cannot name it, the wiring does not exist.*

A strong answer is a single CLI command, HTTP request, log line, or
test name. Anything longer than one line is a sign that the deliverable
needs to be split.

### Integration Contract — Rollback signal

*Every integration must have a kill-switch or regression detector.*

A strong answer is a log line, metric threshold, or alert that an
on-call engineer can act on. "We can revert via git" is acceptable only
for trivial scope; anything user-facing needs an automated signal.

### Integration Contract — Observability added

*Ties wiring into the existing OTel/Metrics surface from
`mahavishnu/ingesters/otel_ingester.py` and `mahavishnu/metrics_cli.py`.*

A strong answer names the specific OTel span, metric name, or structured
log line, and the destination (e.g. `mahavishnu.workflow.duration`, span
`adapter.execute`, log key `workflow.completed`). Observability added
during design is cheaper than observability bolted on after the fact.

______________________________________________________________________

## Conventions

- Mirror the dated-plan header (`Date / Status / Owner / Scope / Purpose`)
  used by `2026-05-10-minimax27-provider-migration.md` and
  `2026-04-25-type-adapter-migration-plan.md` so plan metadata parses
  consistently across files.
- Phases are numbered `Phase 1`, `Phase 2`, … and must each carry their
  own Integration Contract for every deliverable. If a phase has no
  deliverable that needs wiring, state that explicitly with a rationale
  (for example, "documentation-only phase").
- Status labels align with the taxonomy in `PLAN_INDEX.md`: lifecycle is
  one of `draft`, `active`, `partial`, `shipped`, `complete`; role is
  one of `canonical`, `implementation`, `umbrella`, `historical`,
  `superseded`. A new plan starts as `draft, planning` until accepted.
- Add the new plan to `docs/plans/PLAN_INDEX.md` once promoted out of
  `draft`.

## References

- `.claude/decisions/wire-up-contract.md` — the policy this template
  implements.
- `docs/feature-tracking/TEMPLATE.md` — feature-state template that
  tracks each wiring's lifecycle (`built` → `wired` → `adopted`).
- `scripts/audit_orphans.py` — orphan-detection gate that runs before a
  feature is declared complete.
- `.claude/commands/workflows/feature/feature-delivery-lifecycle.md` —
  workflow with the Wiring phase between Design and Validate.
- `CLAUDE.md` § Process Discipline — user-facing summary of the policy.
