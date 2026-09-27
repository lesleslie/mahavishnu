# Eval Methodology Fixture List Proposal

**Date:** 2026-09-27
**Status:** Proposed (awaits §8 reviewer sign-off before Plan 2 promotion)
**Author:** Claude (drafted under user direction during the 2026-09-26 conversation)
**Parent plan:** `docs/plans/drafts/2026-09-26-eval-methodology.md`

## What this proposal covers

Plan 2 (Eval Methodology) §8 names four conditions that must ALL hold before
the plan promotes from `draft` to `active`:

1. Plan 1 Phase 1 shipped. ✅ Met (`dbc2c7fa`, 2026-09-27).
2. Plan 1 Phase 2 Task 2.1 shipped. ✅ Met (`3215d824`, 2026-09-27).
   `scripts/audit_top_tool_calls.py` is the §6 step 2 prerequisite.
3. ≥7 days of `mcp_tool_call` traces covering top-20 tools. ❌ Blocked
   on production traffic post-Phase 1 deploy.
4. **This proposal** + §8 reviewer sign-off. ⏳ This document.

This proposal addresses the third missing piece: **what fixtures** and
**what rubric strategy** will define the cross-adapter eval mini-suite.

## Fixture list (12 fixtures, spanning 4 task classes × 3 adapters)

The three production-ready adapters per CLAUDE.md are **Prefect** (workflow
orchestration), **LlamaIndex** (RAG/code tooling), and **Agno** (agent loops).
The fixture set covers the four task classes Plan 2 §5 names as candidates,
with each fixture cross-evaluable across all three adapters so the suite
produces a non-trivial ordering (per §5 exit criteria).

| # | Fixture slug | Task class | Adapter coverage | Tooling touchpoints (anticipated) |
|---|---|---|---|---|
| 1 | `code-review-py-typo` | code_review | all 3 | `mcp__mahavishnu__discover_tools`, `mcp__akosha__search_code_patterns` |
| 2 | `code-review-py-typing` | code_review | all 3 | same as above + `mcp__akosha__search_semantic` |
| 3 | `refactor-py-extract-method` | refactor | all 3 | `mcp__akosha__search_code_patterns`, `mcp__mahavishnu__pool_route_execute` |
| 4 | `refactor-py-rename-symbol` | refactor | all 3 | same as above |
| 5 | `refactor-py-decompose-class` | refactor | all 3 (hardest) | same as above, multi-step |
| 6 | `ingest-webpage-summary` | ingest | all 3 | `mcp__web_reader__*` (port 8699), content_ingester path |
| 7 | `ingest-blog-multiple` | ingest | all 3 | same, multi-source |
| 8 | `ingest-book-chapter` | ingest | all 3 (slowest) | same, large payload |
| 9 | `deploy-prefect-flow` | deploy | Prefect + Agno | `mcp__mahavishnu__trigger_workflow(adapter="prefect")` |
| 10 | `deploy-llamaindex-rag-index` | deploy | LlamaIndex + Agno | adapter-specific; LlamaIndex's ingestion + index build |
| 11 | `deploy-agno-multi-step` | deploy | Agno (canonical) | `mcp__mahavishnu__trigger_workflow(adapter="agno")` |
| 12 | `multi-adapter-fanout` | cross-cutting | all 3 | exercises the pool_route_execute selector |

**Why 12, not 10:** the original sketch said "10–20." 12 keeps the suite
small enough for nightly CI (<10 min total) while spanning all four
task classes with cross-adapter coverage. Fixtures 9/10/11 exercise
adapter-specific deploy paths, which is where the cross-adapter ranking
is most likely to discriminate (Prefect vs LlamaIndex vs Agno handle
their native task differently). Fixture 12 is the integration test.

**Why these specific fixtures:** each is intentionally small (under
200 lines of test fixture code) and exercises a tool chain we already
have data showing gets called. After production data lands,
`scripts/audit_top_tool_calls.py` will pick the actual top-N from real
traffic — this list is the **first pass** that becomes the baseline
once we have before-data to measure against.

## Rubric strategy

Two-track scoring, mirroring OpenHands' eval methodology:

### Track 1: structural pass/fail (≤3 second verdict)

For every fixture, define a structural check that can run in CI without
an LLM:

- **Output shape:** does the result match the expected schema (dict with
  required keys, list with expected length, file path that exists, etc.)?
- **Tool-call budget:** did the adapter finish within N tool calls
  (e.g. 8 for `code-review-py-typo`)?
- **No-regression sentinel:** did the adapter avoid forbidden tools
  (e.g. fixture 3 must NOT call `mcp__mahavishnu__deploy_*`)?

Structural pass/fail is the gate; if a fixture fails structurally, the
LLM-judge track is skipped.

### Track 2: LLM-as-judge (only when Track 1 is ambiguous)

For fixtures where structural pass/fail is too coarse (e.g.
`refactor-py-decompose-class` — the result might be syntactically
correct but semantically wrong), an LLM-as-judge with a **pinned rubric
prompt** evaluates quality on a 0–4 scale:

- **0 = wrong.** Result does not solve the task or introduces regressions.
- **1 = partial.** Some elements of the task done; others missing or broken.
- **2 = adequate.** Result solves the task with no regressions but
  misses the rubric's "good practice" criteria.
- **3 = good.** Result solves the task cleanly with appropriate style.
- **4 = excellent.** Result solves the task cleanly AND exceeds the
  expected approach (e.g. refactor also documents why the new structure
  is cleaner).

Score ≥ 2 = pass. Both `MiniMax-M3` and local `qwen3.5` are pinned as
judge candidates; the activation step picks one and freezes the choice
in the test config (per `feedback-bodai-push-is-user-controlled` style
version pinning — no silent model swaps).

### Rubric prompt structure (template)

```
You are scoring an AI adapter's output on the fixture:

  FIXTURE: {slug}
  TASK: {task_description}
  EXPECTED_OUTCOME: {expected_outcome_shape}
  ADAPTER: {adapter_name}

The adapter produced this output:

  {output}

Score the output on this rubric:
  - correctness: did it solve the task? (0/1/2)
  - completeness: did it cover all required elements? (0/1/2)
  - style: did it match the codebase's existing patterns? (0/1/2)
  - regressions: did it introduce any test failures or new warnings? (0/1/2)

Overall score: 0 (wrong) - 4 (excellent).
Reply with a single integer on its own line.
```

The rubric prompt is **frozen in the test fixture** so future contributors
can't quietly change the scoring criteria. Any change requires a
Plan-1-style multi-agent review pass.

### Why two tracks, not one

OpenHands' eval methodology evolved from LLM-only judging to structural +
LLM hybrid because LLM-as-judge is non-deterministic — a single
fixture can flip between scores on identical inputs. The structural
track gives a stable floor (we know exactly when an adapter passes
or fails a coarse check); the LLM track gives nuanced ranking when
structural checks tie. This matches the
`feedback-random-order-pollution-bisect` memory: deterministic
gating first, probabilistic refinement second.

## Why this proposal can be drafted BEFORE production data lands

The Plan 2 §6 rationale for deferral was "writing fixture designs based
on guesses about tool usage" would rot. Two reasons that concern
doesn't apply here:

1. **The fixture list is a candidate set, not a commitment.** When
   `audit_top_tool_calls.py` returns real top-N data, the activation
   step reconciles this list against the data — replaces any fixture
   whose touched tools aren't actually in the top-20, adds any missing
   task classes. The list is a starting point, not a contract.
2. **The rubric strategy is fixture-agnostic.** Two-track scoring
   (structural + LLM) is methodology that doesn't depend on which
   specific tools get called. It's decided once and reused across
   fixtures.

## Activation path (after this proposal + reviewer sign-off)

1. Wait for ≥7 days of production `mcp_tool_call` traces (Plan 2 §8 #3).
2. Run `scripts/audit_top_tool_calls.py` — output replaces or refines
   the "Tooling touchpoints" column in the table above.
3. Reconcile fixture list: any task class with low real-world traffic
   gets removed; any task class with high real-world traffic but no
   fixture gets added.
4. Promote Plan 2 from `draft` to `active`. Add finalized REQ-IDs and
   task list per §4.5.
5. Run Phase 0 multi-agent review on the promoted plan.
6. Implement Phase 1 (cross-adapter eval mini-suite).

## Sign-off

This proposal needs Phase 0 reviewer sign-off per Plan 2 §8 #4. The
reviewer's job: confirm that the fixture list is realistic (not
based on guesses) and the rubric strategy is sound (not over-reliant
on LLM-as-judge).

**Proposed reviewers (suggested):**
- `mcp-integration-expert` — covers the tooling touchpoints column.
- `feature-dev:code-architect` — covers the fixture-level testability.
- `akosha-specialist` — covers the metric storage + anomaly detection
  integration (Plan 2 §3 goal #3).

Reviewers should reply with **APPROVED**, **APPROVED WITH REVISIONS**,
or **REQUIRED HARDENING** per the established Phase-1 multi-agent-review
convention.
