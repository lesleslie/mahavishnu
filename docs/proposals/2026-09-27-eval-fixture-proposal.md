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

| # | Fixture slug | Task class | Adapter coverage | Output type | Tooling touchpoints (anticipated) |
|---|---|---|---|---|---|
| 1 | `code-review-py-typo` | code_review | Prefect, LlamaIndex, Agno | list | `mcp__mahavishnu__discover_tools`, `mcp__akosha__search_code_patterns` |
| 2 | `code-review-py-typing` | code_review | Prefect, LlamaIndex, Agno | list | same as #1 + `mcp__crackerjack__search_semantic` (Akkosha has no semantic search tool) |
| 3 | `refactor-py-extract-method` | refactor | Prefect, LlamaIndex, Agno | file_path | `mcp__akosha__search_code_patterns`, `mcp__mahavishnu__trigger_workflow(adapter="...")` |
| 4 | `refactor-py-rename-symbol` | refactor | Prefect, LlamaIndex, Agno | file_path | same as #3 |
| 5 | `refactor-py-decompose-class` | refactor | Prefect, LlamaIndex, Agno (hardest) | file_path + list | same as #3, multi-step; budget ≥ 15 tool calls |
| 6 | `ingest-webpage-summary` | ingest | Prefect, LlamaIndex, Agno | dict | `mcp__mahavishnu__pool_route_execute(prompt="ingest <url>")` — pool worker calls `ContentIngester.ingest_url()` which POSTs to `http://localhost:8699/mcp` (HTTP-delegated, not a direct MCP tool). Requires web_reader deployed on port 8699. |
| 7 | `ingest-blog-multiple` | ingest | Prefect, LlamaIndex, Agno | dict | same as #6, multi-source |
| 8 | `ingest-book-chapter` | ingest | Prefect, LlamaIndex, Agno (slowest) | dict | same as #6, large payload (PDF) |
| 9 | `deploy-prefect-flow` | deploy | Prefect (canonical) + Agno | dict | `mcp__mahavishnu__trigger_workflow(adapter="prefect")`, `mcp__mahavishnu__get_workflow_status` |
| 10 | `deploy-llamaindex-rag-index` | deploy | LlamaIndex (canonical) + Agno | dict | `mcp__mahavishnu__trigger_workflow(adapter="llamaindex")` |
| 11 | `deploy-agno-multi-step` | deploy | Agno (canonical) | dict | `mcp__mahavishnu__trigger_workflow(adapter="agno")` |
| 12 | `multi-adapter-fanout` | cross-cutting | Prefect + LlamaIndex + Agno | dict (3x) | three `mcp__mahavishnu__trigger_workflow(adapter=...)` calls in parallel, polled via `get_workflow_status`. Cross-adapter comparison fixture — runs each adapter on the same task and compares results. |

**Output type taxonomy** (committed per fixture): `list` = ordered collection
of issue dicts; `file_path` = the result is a file written to disk; `dict` =
single structured response. Phase 1 must add a schema test asserting each
fixture's `task.json` declares one of these three types and the actual
output conforms.

**Why the cross-product is uneven:** fixtures 9-11 deliberately cover
adapter-canonical paths (each adapter's strongest deploy capability) so
the cross-adapter comparison surfaces where each adapter genuinely
differs. Fixtures 1-8 cover all three adapters because the underlying
capability (code-review, refactor, ingest) is the same shape across
adapters — only the implementation differs. Plan 2 §5's "non-trivial
cross-adapter ordering" exit criterion is satisfied by fixtures 1-5 +
9-11, not by uniform 4×3 coverage.

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

- **Output shape:** does the result match the expected schema (dict /
  list / file_path per the output-type taxonomy committed in the
  fixture table)?
- **Tool-call budget:** did the adapter finish within N tool calls?
  Budgets are **derived from production telemetry**, not pre-set (see
  "Budget derivation" below).
- **No-regression sentinel:** did the adapter avoid forbidden tools?
  See "No-regression sentinel mechanism" below for how tool calls are
  recorded in isolated CI runs.

Structural pass/fail is the gate; if a fixture fails structurally, the
LLM-judge track is skipped.

### Track 2: LLM-as-judge

Track 2 runs when **either** of these conditions hold:
1. `task.json.judge_required: true` (fixture-class signal — the fixture
   declares semantic evaluation is needed, e.g. `refactor-py-decompose-class`).
2. Two or more adapters tie at Track 1 on a given fixture run (runtime
   tie-breaking signal).

For Track 2, an LLM-as-judge with a **pinned rubric prompt** evaluates
quality on a 0–4 scale per criterion:

- **0 = wrong.** Result does not solve the task or introduces regressions.
- **1 = partial.** Some elements of the task done; others missing or broken.
- **2 = adequate.** Result solves the task with no regressions but
  misses the rubric's "good practice" criteria.
- **3 = good.** Result solves the task cleanly with appropriate style.
- **4 = excellent.** Result solves the task cleanly AND exceeds the
  expected approach.

Score ≥ 2 = pass. The judge call uses **frozen parameters** —
`temperature=0`, `seed=42`, model = one of two pinned candidates:
`MiniMax-M3[1m]` (cloud) or local `qwen3.5`. Activation selects one
and freezes the choice in the eval config. Model version is **version-stamped**
in the test logs to prevent silent model upgrades from breaking
reproducibility (analogous to `TestYAMLRoutingSync` at
`tests/unit/test_task_router.py:279-343`).

### Rubric prompt structure (template, frozen)

```
You are scoring an AI adapter's output on the fixture:

  FIXTURE: {slug}
  TASK: {task_description}
  EXPECTED_OUTCOME: {expected_outcome_shape}
  ADAPTER: {adapter_name}

The adapter produced this output:

  {output}

Reply with EXACTLY five lines, no other text:
  correctness: <0|1|2>     # did it solve the task?
  completeness: <0|1|2>   # did it cover all required elements?
  style: <0|1|2>          # did it match the codebase's existing patterns?
  regressions: <0|1|2>    # did it introduce any test failures or new warnings?
  overall: <0|1|2|3|4>    # 0=wrong, 4=excellent
```

The rubric prompt is **frozen in the test fixture** so future contributors
can't quietly change the scoring criteria. Any change requires a
Plan-1-style multi-agent review pass. The "Reply with EXACTLY five lines"
instruction is enforced by a parser test (each response is split on `\n`
and asserted to have exactly 6 lines: 4 criterion + 1 overall + 1 trailing
blank; a malformed response fails Track 2 → fixture is scored as Track 1
result only).

### Budget derivation (deferred to activation)

Tool-call budgets cannot be derived without production telemetry. At
activation, run `scripts/audit_top_tool_calls.py` against ≥7 days of
`mcp_tool_call` traces. For each canonical fixture, compute the
**25th-percentile of total tool-call count across successful runs**
as the initial budget. Then add a 20% margin and round up to the nearest
integer. This gives a budget that's tight enough to fail when an adapter
loops but loose enough to absorb legitimate variation.

Budgets are **not** pre-set in this proposal because doing so would
commit to numbers that may not match observed reality (e.g. fixture 5
may legitimately need 12-18 calls on the harder decompose-class task;
no amount of proposal-time guessing pins that).

### Mocking strategy

Fixtures 6-12 depend on live external backends (web_reader port 8699,
Prefect, LlamaIndex, Agno). The Phase 1 mocking framework follows the
existing pattern at `tests/fixtures/adapter_mocks.py`:

- **Per-adapter canned responses** loaded from
  `tests/fixtures/eval/<slug>/mocks/<adapter>.json` (one JSON file per
  adapter per fixture).
- **No live backends in CI** — the suite runs offline against mocks.
- **Smoke tests against live backends** (separately, in
  `tests/integration/test_eval_smoke.py`) — run weekly, not nightly.

Line-count reality: simple fixtures (1, 4) are <100 lines. Complex
fixtures with mocking (5, 8, 9-12) are 300-500 lines including the
canned-response JSON. The "under 200 lines per fixture" line in the
parent plan §5 is wrong; this proposal supersedes it.

### No-regression sentinel mechanism

Forbidding certain tool calls requires recording them. Phase 1
implements a **fixture-local tool-call recorder** wrapping the adapter's
MCP client. Each tool call goes through the recorder, which:

1. Appends to an in-memory list (`calls: list[ToolCall]`).
2. Forwards to the real MCP client.
3. Returns the result.

After fixture execution, the recorder is asserted to NOT contain any
tool in `task.json.forbidden_tools`. The recorder is **NOT** the
production ToolCallEnrichmentMiddleware (which only fires on production
HTTP traffic); it's a test-local Python wrapper. This separation matters
because production telemetry is fire-and-forget while eval fixtures need
synchronous, in-process introspection.

### Held-out set

Plan 2 §5 names "rubric disagreements > 30% on a held-out set" as a
rollback signal. The held-out set is **5 fixtures distinct from the
canonical 12**, run **weekly** (not nightly) by a separate CI job:

- 3 of the 5 are hand-written by humans (gold labels); 2 are drawn
  randomly from the canonical 12 and re-labelled blind.
- Rubric disagreements measured as: (Track 2 LLM judge score on held-out
  fixture vs. human gold label) — fraction of fixtures where the
  judge deviates by ≥1 point on the 0-4 scale. Threshold: >30% means
  the judge is unreliable; revert to Track 1 only.

The held-out set lives at `tests/fixtures/eval_held_out/<slug>/` —
distinct from the canonical `tests/fixtures/eval/<slug>/` so nightly
runs don't see held-out labels.

### Why two tracks, not one

OpenHands' eval methodology evolved from LLM-only judging to structural +
LLM hybrid because LLM-as-judge is non-deterministic — a single
fixture can flip between scores on identical inputs. The structural
track gives a stable floor (we know exactly when an adapter passes
or fails a coarse check); the LLM track gives nuanced ranking when
structural checks tie. This is the deterministic-then-probabilistic
principle: any LLM-judged output must be gated by a deterministic
structural check first.

## Why this proposal can be drafted BEFORE production data lands

The Plan 2 §6 rationale for deferral was "writing fixture designs based
on guesses about tool usage" would rot. Two reasons that concern
doesn't apply here:

1. **The fixture list is a candidate set, not a commitment.** When
   `audit_top_tool_calls.py` returns real top-N data, the activation
   step reconciles this list against the data using the explicit
   thresholds below. The list is a starting point, not a contract.
2. **The rubric strategy is fixture-agnostic.** Two-track scoring
   (structural + LLM) is methodology that doesn't depend on which
   specific tools get called. It's decided once and reused across
   fixtures.

## task.json schema (frozen)

Every fixture ships a `task.json` validated against this JSON Schema
(lives at `tests/fixtures/eval/_schema/task.schema.json`, frozen at
Phase 1 commit time):

```json
{
  "type": "object",
  "required": ["slug", "description", "expected_outcome_shape", "output_type", "rubric"],
  "properties": {
    "slug": {"type": "string", "pattern": "^[a-z0-9-]+$"},
    "description": {"type": "string", "minLength": 20},
    "expected_outcome_shape": {"type": "string"},
    "output_type": {"enum": ["dict", "list", "file_path"]},
    "tool_call_budget": {"type": "integer", "minimum": 1, "maximum": 100},
    "forbidden_tools": {"type": "array", "items": {"type": "string"}},
    "judge_required": {"type": "boolean"},
    "rubric": {
      "type": "object",
      "required": ["pass_threshold"],
      "properties": {
        "pass_threshold": {"type": "integer", "minimum": 0, "maximum": 4}
      }
    }
  }
}
```

A schema-conformance test asserts every fixture in `tests/fixtures/eval/`
parses against this schema. Adding a fixture without conforming fails CI.

## CLI surface sketch

`mahavishnu eval run --suite mini-v1 [--adapter <name>] [--output <path>]`

- `--suite` (required): suite identifier; currently only `mini-v1` (the
  canonical 12). Reserved for `held-out` (the 5-fixture weekly run).
- `--adapter` (optional): if supplied, runs only that adapter's slice.
  Default: all three (Prefect, LlamaIndex, Agno).
- `--output` (optional): write JSON results to `<path>`. Default: stdout.

Settings keys (new file `settings/eval.yaml`, gitignored):

- `eval_judge_model`: pinned model identifier (e.g. `MiniMax-M3[1m]`).
- `eval_judge_temperature`: pinned to `0`.
- `eval_judge_seed`: pinned to `42`.
- `eval_held_out_cron`: weekly cron for the held-out-set run.

Consumer sites (per `feedback-cli-flag-consumer-wiring` memory):

- `mahavishnu/eval/runner.py` — the CLI entry point.
- `mahavishnu/eval/sink.py` — posts to Akosha (requires the
  write-side MCP tool from the follow-on Akosha plan).
- `mahavishnu/eval/reporter.py` — emits the JSON results + Slack/email
  notification on regression.

## Activation path (after this proposal + reviewer sign-off)

**Pre-conditions (all must be true):**

1. Plan 1 Phase 1 + Phase 2 Tasks 2.1 + 2.2 shipped. ✅ All met.
2. ≥7 days of production `mcp_tool_call` traces. ❌ Blocked on traffic.
3. Phase 0 reviewer sign-off on this proposal. ❌ Pending — this review.
4. **Deployment confirmation:** `web_reader` MCP server running on
   port 8699 in the eval CI environment (fixtures 6-8 require it).
   Add to activation checklist.
5. **Akkosha follow-on plan shipped:** the metric-sink MCP write tool
   + persistence layer are required for the eval results to actually
   sink. See `docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md`
   (deferred; not yet drafted as of this proposal's revision).

**Activation steps:**

1. Run `scripts/audit_top_tool_calls.py` against the ≥7-day corpus.
2. Reconcile the fixture list using **explicit thresholds**:
   - **Drop a task class** if total call count across all its tools
     is `<5` in the 7-day window.
   - **Drop a fixture** if any of its tooling touchpoints has `<1`
     call in the 7-day window (the fixture would test a dead path).
   - **Add a task class** if a tool with `>50` calls/day exists that
     no current fixture covers.
   - **Cross-adapter coverage** required: minimum 2 adapters per task
     class (3 if the canonical adapter set is fully available).
3. Derive budgets per "Budget derivation" subsection.
4. Promote Plan 2 from `draft` to `active`. Add finalized REQ-IDs and
   task list per §4.5.
5. Run Phase 0 multi-agent review on the promoted plan.
6. Implement Phase 1 (cross-adapter eval mini-suite + task.json schema
   + CLI surface + tool-call recorder + mocks).

## Cross-repo dependencies (corrected after Phase 0 review)

The Phase 0 review surfaced two critical Akosha-side gaps that block
the eval metric sink:

1. `add_metric()` is in-process only; no MCP write path exists.
2. `TimeSeriesAnalytics._metrics_cache` is in-memory only; no
   persistence layer (Dhara was decommissioned).

Both are captured in the follow-on plan
`docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md` (drafted as
part of the Phase 0 review resolution). Plan 2 cannot activate until
that Akosha work ships. Until then, eval results can be JSON-dumped
to stdout and archived locally — sufficient for nightly CI smoke,
insufficient for the >10% week-over-week anomaly detector.

## Sign-off

This proposal needs Phase 0 reviewer sign-off per Plan 2 §8 #4. The
reviewer's job: confirm that the fixture list is realistic (not
based on guesses), the rubric strategy is sound (not over-reliant
on LLM-as-judge), and the cross-repo Akosha dependencies are
correctly enumerated.

**Proposed reviewers (suggested):**
- `mcp-integration-expert` — covers the tooling touchpoints column.
- `feature-dev:code-architect` — covers the fixture-level testability.
- `akosha-specialist` — covers the metric storage + anomaly detection
  integration (Plan 2 §3 goal #3).

Reviewers should reply with **APPROVED**, **APPROVED WITH REVISIONS**,
or **REQUIRED HARDENING** per the established Phase-1 multi-agent-review
convention.
