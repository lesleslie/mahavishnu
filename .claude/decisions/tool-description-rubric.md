---
status: active
role: canonical
kind: decision
date: 2026-09-27
last_reviewed: 2026-09-27
superseded_by: null
blocks_on:
  - docs/plans/2026-09-26-tool-surface-quality.md
topic: mcp-tool-design
shipped_with: REQ-TSQ-010 (Plan Phase 2 Task 2.2)
---

# MCP Tool Description Rubric

## Context

`docs/plans/2026-09-26-tool-surface-quality.md` Phase 2 established that
single-sentence tool descriptions like `"List all active pools."` do not
give language models enough information to choose the right tool
reliably — they omit failure modes, side effects, when NOT to use the
tool, and return-shape contracts. Akosha's per-tool fitness signals
(success_rate, error_rate) are observable but not actionable: a low
success_rate on `pool_route_execute` could mean the description doesn't
tell the model to pass `selector="least_loaded"`.

This decision establishes the **6-criterion rubric** every Mahavishnu
tool description must satisfy. Phase 2 Task 2.3 rewrites the top-10
most-called tools' `description=` strings against this rubric.

## Decision rule

Every `@mcp.tool()` decorator in `mahavishnu/mcp/tools/*.py` MUST have a
`description=` (or docstring-equivalent) that satisfies all six criteria
below. Each criterion has one **pass** example and one **fail** example.
The structural validator (`tests/unit/test_tool_description_rubric.py`)
asserts that this file exists, contains the six named sections, and each
section has both a pass and fail example.

### 1. When *not* to use the tool (negative cases)

The description must say which tool should be used INSTEAD for common
adjacent intents. Models pick tools by elimination; without explicit
"don't use X for Y" guidance they reach for the broadest match.

| | |
|---|---|
| ✅ **PASS** | "List active pools. **Do NOT use to execute work — use `pool_route_execute` for that.** Returns the pool registry only." |
| ❌ **FAIL** | "List pools." (no negative case; model cannot distinguish from `pool_route_execute`) |

### 2. Common failure modes

The description must list the realistic failure modes so the model can
anticipate them and surface them to the user instead of looping.

| | |
|---|---|
| ✅ **PASS** | "List pools. **Fails if no pools are spawned yet (returns empty list, not an error). Times out after 30s if a pool is unhealthy.**" |
| ❌ **FAIL** | "List pools." (no failure-mode guidance) |

### 3. Return shape hint

The description must say what the tool returns — string, structured
object, empty-when-no-data, etc. — so the model can render or chain
correctly.

| | |
|---|---|
| ✅ **PASS** | "List pools. Returns `list[dict]` where each dict has keys `pool_id`, `pool_type`, `workers`, `status`. **Empty list means no pools are spawned yet.**" |
| ❌ **FAIL** | "List pools." (return type ambiguous; model cannot distinguish "no pools" from "error") |

### 4. Model-side language (active voice, second-person imperatives, no marketing prose)

The description is read by a model, not a human. Active voice + second-person
imperatives compress intent. Marketing prose ("powerful", "comprehensive",
"intelligent") wastes tokens and signals nothing.

| | |
|---|---|
| ✅ **PASS** | "List pools. Returns the pool registry." |
| ❌ **FAIL** | "Leverage our powerful, comprehensive pool intelligence to gain deep insights into your infrastructure." (marketing prose, no actionable signal) |

### 5. Side-effect caveat (filesystem / network / external state)

Tools that mutate state must say so explicitly. Models need to know
whether a call is observational or mutating to decide when to ask the
user for confirmation.

| | |
|---|---|
| ✅ **PASS** | "Spawn a pool. **Side effect: starts a subprocess; persists the pool record in the local registry. NOT reversible by the tool itself — use `pool_close` to stop.**" |
| ❌ **FAIL** | "Spawn a pool." (model cannot tell observational vs mutating) |

### 6. No internal disclosure

The description must NOT contain:
- Absolute file paths (e.g. `/Users/les/Projects/mahavishnu/...`).
- Internal-only tool names not exposed via the public MCP surface.
- Auth-mechanism hints (token types, JWT claims, header names).

Operators see the description via `tools/list`. Internal scaffolding
that leaks into the description surfaces implementation details to
end-users and creates a churn burden when internals change.

| | |
|---|---|
| ✅ **PASS** | "Read a file. Returns UTF-8 text or empty string for missing files. Side effect: none." |
| ❌ **FAIL** | "Reads from /Users/les/Projects/mahavishnu/mahavishnu/settings/local.yaml using os.getenv('MAHAVISHNU_AUTH_SECRET') for JWT validation against the HS256 algorithm with a 1440-minute expiry." |

## Why these six criteria

1. **Negative cases** — eliminates ambiguity between adjacent tools.
2. **Failure modes** — prevents the model from looping on predictable
   errors it could surface to the user.
3. **Return shape** — enables correct rendering and chaining.
4. **Model-side language** — maximizes information density per token.
5. **Side-effect caveat** — distinguishes observational from mutating.
6. **No internal disclosure** — keeps the description stable across
   refactors and prevents accidental implementation leakage.

Criteria 1, 2, 3, 5 came from SWE-Agent's Agent-Computer Interface
discipline (SWE-Agent paper §4.2 — tool schema design). Criteria 4 and
6 are local additions: 4 reflects that the description's audience is a
model not a human, 6 reflects the Bodai pre-1.0 disclosure posture
(`no-bodai-mentions-in-mcp-repos` memory).

## Scope

Applies to every `@mcp.tool()` decorator under `mahavishnu/mcp/tools/`
and any inline `add_tool` / `add_tool_fn` call in `mahavishnu/mcp/`.
Excludes the 27 inline core tools that are registered unconditionally
(those have stable descriptions written when the tool was added).

## Activation

Phase 2 Task 2.3 rewrites the top-10 most-called tools' descriptions
against this rubric. The top-10 list is produced by
`scripts/audit_top_tool_calls.py` (Phase 2 Task 2.1) once production
`mcp_tool_call` traces accumulate. Until then, this rubric is enforced
on:
- Any new tool added to `mahavishnu/mcp/tools/`.
- Any rewrite of an existing tool's description string.

The enforcement path is `tests/unit/test_tool_description_rubric.py`
which validates the file's structural contract (six sections, pass/fail
examples per section). Per-tool compliance is reviewed in code review,
not as an automated test — see "Why no automated per-tool enforcement"
below.

## Why no automated per-tool enforcement

An automated test that asserts every `@mcp.tool()` description meets all
six criteria is tempting but brittle:

- The criteria are qualitative (e.g. "no marketing prose"). Encoding them
  as heuristics produces false positives/negatives that erode trust in
  the test suite.
- The rubric is a moving target — when a criterion evolves, every
  matching test must be re-baselined.
- Per-tool enforcement belongs in code review, where a reviewer can
  apply judgement. Code-review automation (`pr-review-toolkit:code-reviewer`)
  can be configured to flag descriptions that miss obvious criteria
  (e.g. "this description is under 30 characters — probably missing
  context") but the qualitative criteria 1, 2, 5 require human reading.

The structural validator test is intentionally narrow: it pins THIS
file's structure (six named sections, pass + fail examples per section),
not per-tool compliance. Per-tool compliance is a code-review concern.

## Related

- `docs/plans/2026-09-26-tool-surface-quality.md` — Phase 2 source plan.
- `docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md` —
  follow-on plan that depends on Task 2.3 actually landing.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — sibling
  decision covering the wire-up side of the same surface.
- `tests/unit/test_tool_description_rubric.py` — structural validator.
