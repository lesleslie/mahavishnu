---
status: active
role: canonical
kind: decision
date: 2026-10-29
last_reviewed: 2026-10-29
topic: learning-pipeline-tools-authz-block
---

# Learning-pipeline MCP tools — blocked on an authentication-identity gap

One-line summary: the `feat/wire-learning-pipeline` branch is **not
merged**; the ensemble review found that the `require_mcp_auth` gate
authenticates nothing, because the identity it binds on is a
caller-supplied tool argument.

## Context

`feat/wire-learning-pipeline` (commit `c664598d`, 2026-10-14) wires the
five learning-pipeline MCP tools that Phase 1B of ADR 012 built but never
registered. It is the only genuinely-unmerged branch in the fleet: every
other named branch was verified to be already on `main` (ancestor of
main, squash-merged with an identical commit subject, or merging to
main's exact tree).

The branch's own hardening is sound in the parts it controls. All five
tools apply `@require_mcp_auth` to the outer function, the availability
fallbacks sit *behind* the gate, `trigger_synthesis` is gated at
`Permission.WRITE`, and the error messages are sanitised to the
exception class name.

Two blocking findings remain.

### B1 — the gate authenticates nothing

`require_mcp_auth` resolves the caller's identity from
`kwargs.get("user_id")` and prefers a trusted channel only when the tool
declares a `ctx: Context` parameter
(`mahavishnu/mcp/auth.py:114-125`). The branch's five tools declare
`user_id: str | None = None` as an ordinary tool parameter and declare no
`ctx`, so:

- the trusted branch never executes — FastMCP never injects a Context
  into a function that does not ask for one;
- `user_id` appears in the tool's input schema, so the **caller asserts
  who they are** and RBAC only checks that the asserted name holds a
  role;
- the "trusted" fallback is not trusted either:
  `AuthContextMiddleware` reads `context.message.arguments`
  (`mahavishnu/mcp/middleware/auth_context.py:69-82`) — the same
  tool-call argument dict — and `extract_auth_from_request` prefers
  `request["user_id"]` over the `Authorization` header
  (`mahavishnu/mcp/auth.py:236-237`). The transport's HTTP request is
  never consulted, so the `Bearer` path the middleware docstring
  describes is unreachable.

The review confirmed this empirically against the real FastMCP schema
generator: the registered schema exposes `user_id` as a settable
property, and `check_permission` is invoked with the caller's own
string.

This is a **pre-existing house pattern** — `workflow_tools.py:90`,
`webhook_tools.py:58` and `ecosystem_state_tools.py:82` all take
`user_id` the same way — so the branch is consistent with the codebase.
What the branch changes is the blast radius: it is the first to put a
content-bearing surface (session goals and observations harvested from
other sessions' Session-Buddy memories, plus skill draft bodies) behind
that pattern.

`create_user` compounds it: its permission check is guarded by
`if user_id_caller:` (`mahavishnu/mcp/server_core.py:763`), so omitting
the argument skips the check, and `RBACManager.create_user` copies the
role's `allowed_repos is None` — every repo.

### B2 — the tools register at every tool profile

`mahavishnu/mcp/tools/profiles.py:133` puts
`_register_learning_pipeline_tools` in `FULL_REGISTRATIONS` only, with
the rationale that the tools query live backends that STANDARD and
MINIMAL environments do not have. But `mahavishnu/mcp/bootstrap.py:966`
calls it **unconditionally** inside `register_profile_tools`, ignoring
the `methods_set` the function receives.

So `MAHAVISHNU_TOOL_PROFILE=minimal` — documented in CLAUDE.md as
"health probes only" — exposes `list_evidence`, `list_pending_drafts`,
`get_promotion_history` and the WRITE-gated `trigger_synthesis`. This
one is a defect the branch introduces, and it is fixed inside the
branch's own diff.

### The correctness review found four more blockers

Three are mechanical; the fourth is a decision.

**It breaks 19 pre-existing tests it never touched.**
`tests/unit/test_learning_pipeline_tools.py:133` calls
`register_learning_tools(fake_mcp, pipeline, evidence, registry)` with
four positional arguments and no `rbac_manager`. The branch's
`@require_mcp_auth` fails closed on a `None` manager
(`mahavishnu/mcp/auth.py:94-99`), so every tool returns
`{"status": "error", "error_code": "AUTH_NOT_CONFIGURED"}` — a dict with
no `"available"` key — and the assertions fail with `KeyError`. Verified:
19 pass on `main`, 19 fail on the branch. The branch's own test file
passes, which is why it was missed.

**The merge gate is red on formatting.** `ruff format --check` reports
two files the branch itself added lines to. The gate fails; a merge does
not fix it.

**Two of the five tools have no data producer.**
`LearningPipelineService._run_cycle` synthesizes drafts and runs the
review gate but never writes to `SkillRegistry`, and
`SkillRegistry.register()` — the only writer — has zero production
callers. So `list_pending_drafts` and `get_promotion_history` can only
ever return `{"count": 0, ...}`, however many cycles have run. That is
the failure mode CLAUDE.md's "MCP backend wiring discipline" calls out:
*"every registered tool must have a working data feed."* Two of the five
newly-live tools are permanently empty, and the commit message's
"the tools observe the same live state the pipeline mutates" is false.

**The branch is 357 commits behind `main`.** The merge itself is
conflict-free, but the branch's `bootstrap.py` and `profiles.py`
predate main's current `# noqa: BLE001, RUF100` additions.

### The generalist review added three more

**`SkillRegistry` cannot represent a "pending draft" at all.** Its only
mutator, `register()`, calls `promote_draft()` and stores
`state=ACTIVE`; `list_active()` returns only ACTIVE records. The
`DRAFT` and `REVIEW` states exist in `skill_governance.py` but the
registry has no API to insert them. So `list_pending_drafts` — whose
docstring says "list all *active skill drafts*" — would return `[]`
even after drafts are written, and would list an already-approved skill
as a "pending draft" if one were. The registry needs a draft-state API
before that tool can mean anything.

**The pipeline creates a shadow registry.** `core/bootstrap.py:524`
already builds `app.skill_registry`, which the TUI reads
(`mahavishnu/tui/app.py:221-224`). The branch creates a *second*
instance at `learning_pipeline.py:87`; the MCP tools read the
pipeline's, the TUI reads the app's. The branch's own new test warns
about exactly this hazard — "a copy / shadow registry would silently
diverge from activation events" — while the branch introduces the
shadow.

**`trigger_synthesis`'s effect is invisible to `get_pipeline_status`.**
`run_once()` does not set `_last_result` or bump `_cycle_count`; only
the `_run_loop` path does. After a manual cycle the status tool still
reports `cycle_count: 0, last_result: None`.

Two facts that make the surface smaller than it looks: `LearningConfig.enabled`
defaults to `False`, and `start_learning_pipeline` — which starts the
periodic loop ADR 012 ties to app startup — has no production caller.
So on a default install every one of the five tools returns
`{"available": False, ...}`.

## Decision rule

**The branch does not merge as it stands.** The ensemble returned BLOCK,
and under the agent-review workflow a BLOCK means the change does not
land until the finding is fixed.

The complete fix for B1 is a cross-cutting change to authentication in a
live control plane, not a patch to this branch:

1. `mahavishnu/mcp/middleware/auth_context.py` — source the identity
   from the transport's `Authorization` header
   (`ctx.request_context.request.headers`; FastMCP 4.1.4 has no
   `Context.get_http_headers`) and drop the caller-supplied `user_id`
   from the request dict when a header is present. Header-derived
   identity is strictly better than an asserted one, and the change is
   additive for clients that send no header.
2. The five learning tools — declare `ctx: Context` and remove
   `user_id` from the signatures, so the schema no longer offers the
   caller a way to assert an identity.
3. `mahavishnu/mcp/server_core.py:763` — make `create_user`'s
   permission check unconditional: a missing `user_id_caller` denies
   rather than skipping the check.

Steps 1 and 3 change authentication behaviour for **every** tool in the
fleet. That is its own piece of work: its own branch, its own ensemble
review, its own sign-off. Bundling it into a fifteen-day-old feature
merge, at the end of a long session, with no second pair of eyes on the
auth change specifically, is how an authz regression reaches production.

All three reviewers returned **BLOCK**, and they converged: two of them
found the permanently-empty registry independently, and all three found
the profile-gating defect. The mechanical items — the 19 broken tests,
the format gate, the profile gate, the docs and fixtures — are each
small. The two that need a decision rather than an edit are the
registry's draft representation and the per-caller cache bucket, and
both are product questions rather than implementation ones.

## Status

**Open.** The branch is intact at `feat/wire-learning-pipeline` and is
deliberately *not* deleted — it is the only unmerged work in the fleet
and the fixes belong on top of it.

Owner and date for the auth work are **not** assigned. The review was
explicit that it would not accept "fix it later" without both. Assigning
them is an operator decision, not one this change can make on its own.

Two smaller items the review raised are recorded here for whoever picks
the work up, and are *not* blockers:

- `available: True` is returned on failure paths, so a failure reads as
  "available"; and `available` carries two contradictory meanings
  ("dependency not wired" vs "dependency present, call failed").
- `EvidenceStore.query_evidence` swallows `MCPServerError` and returns
  `[]`, so a Session-Buddy outage is indistinguishable from "no
  matches".
- `PipelineCycleResult.errors` carries raw `str(exception)` text one
  layer below the branch's own sanitisation, so `cycle_result` and
  `last_cycle` can leak internal detail the branch intended to withhold.
