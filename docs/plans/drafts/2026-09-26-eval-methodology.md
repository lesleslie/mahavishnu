---
status: draft
role: implementation
kind: plan
date: 2026-09-26
last_reviewed: 2026-09-27
superseded_by: null
blocks_on:
  - docs/plans/2026-09-26-tool-surface-quality.md
activation_readiness:
  - met: Plan 1 Phase 1 shipped (commit dbc2c7fa, mahavishnu)
  - met: Plan 1 Phase 2 Task 2.1 shipped (commit 3215d824 — scripts/audit_top_tool_calls.py ranks tools by call count, exactly the §6 step 2 prerequisite)
  - met: Plan 1 Phase 2 Task 2.2 shipped (commit f5903d6c — tool-description-rubric.md, useful for the rubric strategy section of the fixture proposal)
  - blocked: ≥7 days of mcp_tool_call traces covering top-20 tools (depends on production traffic post-Phase 1 deploy)
  - blocked: short proposal document naming fixture list + rubric strategy
  - blocked: Phase 0 reviewer sign-off on fixture list
topic: adapter-architecture
---

# Evaluation Methodology — Implementation Plan (DEFERRED)

> **Status:** `draft` — **explicitly deferred** until Phase 1 of `docs/plans/2026-09-26-tool-surface-quality.md` lands and surfaces the tool-call telemetry needed to design eval fixtures against real observed tool-usage patterns.
>
> **Why deferred, not written in full now:** the eval suite's design depends on which tools the agents actually use (and in what combinations) for each task class. Until Phase 1 of the companion plan produces that data, any fixture design written today would be speculative and would rot within weeks. This document captures the *shape and direction*; the full task list, fixtures, and rubric prompts get written when the data is in hand.
>
> **Origin:** 2026-09-26 conversation — same as the companion plan. Specifically, OpenHands' [evaluation methodology](https://github.com/All-Hands-AI/OpenHands/tree/main/evaluation) discipline (standardized rubric suites, before/after measurement, regression detection against orchestrator behavior changes) adapted to Mahavishnu's adapter architecture.

## 1. Outcome (target)

- **User-observable change:** `mahavishnu eval run --suite mini-v1` runs a fixed set of representative tasks across one or more of the three production-ready adapters (`prefect`, `llamaindex`, `agno`) and reports a per-adapter pass rate. `mcp__akosha__analyze_trends(metric_name="eval_pass_rate")` returns a time series; nightly CI posts to Akosha; an anomaly alert fires if any adapter's score drops > 10% week-over-week. Eventually: full OpenHands-style regression detection against orchestrator behavior changes (not just adapter comparison).
- **Success metric:** After activation, the "which adapter do I pick for task class X" question has a data-backed answer. After full-harness activation, every Mahavishnu release ships with a non-decreasing pass rate on the canonical suite.

## 2. Goals (when activated)

1. Standardized eval suite that can run any subset of adapters and report comparable pass rates.
2. Per-task outcome scoring (pass/fail shape OR LLM-as-judge with a fixed rubric prompt) that survives eval-drift over time.
3. Trend storage in Akosha so existing anomaly detection (`mcp__akosha__detect_anomalies`) catches regressions automatically.
4. The full eval harness (Phase 2) extends the mini-suite to broader task coverage + regression detection against orchestrator behavior changes (not just adapter comparison).

## 3. Non-Goals (initial sketch)

1. Real-time eval (point-in-time is enough; nightly is the cadence).
2. LLM-as-judge for *every* task (only for tasks where a structural pass/fail check isn't possible).
3. Cross-component eval (Akosha, Crackerjack, Session-Buddy each have their own eval surfaces — out of scope here).
4. Public eval dashboard (the trend storage in Akosha is enough for now; a Grafana panel is a follow-up).
5. Replacing the fitness analyzer (the analyzer is a different granularity — operational latency/failure vs. outcome correctness; both coexist).

## 4. Current Findings (initial sketch — to be expanded when activated)

- **Three production-ready adapters** (`prefect`, `llamaindex`, `agno`) per `mahavishnu/core/adapters/` and CLAUDE.md "Adapters" section. Each is a candidate for cross-adapter eval.
- **No existing eval suite.** Grep for `eval_pass_rate`, `eval_runner`, `EvalSuite`, `LLMJudge` returns nothing under `mahavishnu/`. This plan is greenfield.
- **Akosha already supports trend storage + anomaly detection.** `mcp__akosha__analyze_trends(metric_name=...)` and `mcp__akosha__detect_anomalies(...)` are the consumption surface. No new storage layer needed; eval pass rates live as `eval_pass_rate` + per-task-class metrics.
- **Crackerjack for code-quality gating** is the right place to add `crackerjack eval run` (or whatever CLI surface) — but only after the suite shape is decided. Do not pre-commit to the CLI surface in this deferred plan.
- **The fixture repos themselves are a real cost.** Each fixture needs: a small repo (in `tests/fixtures/eval/`), a task description, an expected outcome, a rubric. 10–20 of these is a week of work. Defer until activation.

## 4.5 Requirements (sketch — finalized when activated)

```yaml
requirements:
  - id: REQ-EVAL-001
    title: "mahavishnu eval CLI: run --suite <name> --adapter <name> (placeholder; finalized at activation)"
  - id: REQ-EVAL-002
    title: "10-20 fixture tasks spanning code-review, refactor, ingest, deploy across adapters"
  - id: REQ-EVAL-003
    title: "Per-task outcome scoring (structural check OR LLM-as-judge with fixed rubric)"
  - id: REQ-EVAL-004
    title: "Pass-rate results sink to Akosha as eval_pass_rate metric per adapter per task-class"
  - id: REQ-EVAL-005
    title: "Nightly CI integration: posts to Akosha; alert on >10% week-over-week drop"
  - id: REQ-EVAL-006
    title: "Full-harness Phase 2: regression detection against orchestrator behavior changes (deferred to follow-on plan)"
```

## 5. Implementation Phases (sketch)

### Phase 1: Cross-adapter eval mini-suite

**Goal:** A small but real suite that proves the methodology works and produces a first cross-adapter ranking.

**Sketch tasks (finalize when activating):**

- Finalize fixture list. Likely candidates from existing Mahavishnu functionality: `code_review` (one of the agent adapters), `refactor` (LlamaIndex has RAG/code tooling), `ingest` (content ingestion path), `deploy` (workflow trigger).
- Each fixture: small repo in `tests/fixtures/eval/<slug>/`, a `task.json` with `{description, expected_outcome_shape, rubric}`, a runner script.
- LLM-as-judge prompt: pinned, version-stamped in the test logs. Use a small cheap model (local `qwen3.5` or cloud `MiniMax-M3`) at temperature=0 with seed.
- Sink pass rates to Akosha as `eval_pass_rate` + per-`(adapter, task_class)` breakdown.

**Exit criteria (target):**

- `mahavishnu eval run --suite mini-v1 --adapter prefect` returns non-empty pass rate.
- `mcp__akosha__analyze_trends(metric_name="eval_pass_rate")` shows non-zero data.
- Nightly CI posts to Akosha.
- Cross-adapter ranking produces a non-trivial ordering (Prefect vs LlamaIndex vs Agno on the same fixture set).

#### Integration Contract (sketch — finalized at activation)

- **Triggered from:** Manual `mahavishnu eval run` invocation OR nightly CI cron.
- **Returns to / updates:** Akosha trend storage under `eval_pass_rate` metric; alert rules under existing anomaly detection.
- **Demonstrable by:** (finalize at activation — likely `uv run mahavishnu eval run --suite mini-v1 --adapter prefect` + `mcp__akosha__analyze_trends(metric_name="eval_pass_rate")`)
- **Rollback signal:** Rubric disagreements > 30% on a held-out set OR nightly CI post fails 3 nights in a row.
- **Observability added:** `eval_pass_rate` metric; per-`(adapter, task_class)` breakdown.

---

### Phase 2: Full OpenHands-style harness (separate plan when activated)

**Goal:** Broader task coverage, regression detection against orchestrator behavior changes, not just adapter comparison.

**Sketch tasks (NOT in scope of this draft):**

- Larger suite (50–200 tasks).
- Cross-component regression: does a change to the orchestrator break tasks that previously passed?
- Held-out test set to validate LLM-as-judge stability.
- Eval suite maintenance: who owns the rubric prompts? How does the suite evolve?
- Grafana dashboard.

This Phase 2 is a separate plan file written when Phase 1 has shipped and the methodology has proven out. **Do not bundle** — the decision to commit to ongoing eval maintenance is a separate one from "can we build a useful mini-suite."

---

## 6. Why this is deferred, summarized

The eval suite's task design depends on:
- Which tools agents actually use (and in what combinations) — **only known after Plan 1 Phase 1 lands**.
- Which adapter combinations are common in production — **only knowable from operational telemetry**.
- Which failure modes are the worst — **only diagnosable after we have a baseline to compare against**.

Writing the full plan now means committing to fixture designs based on guesses about tool usage. The deferred sketch captures:
- The decision that we *want* this work.
- The shape it will take.
- The blocking dependency (Plan 1 Phase 1).

When Plan 1 Phase 1 surfaces the telemetry, the activation step is:
1. Read `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call")` output.
2. Identify top-N tool combinations per task class.
3. Pick fixtures that exercise those combinations.
4. Promote this plan from `draft` to `active` with finalized REQ-IDs, tasks, and exit criteria.
5. Open a multi-agent review (Phase 0) before code begins.

---

## 7. Review Notes

No review yet — this plan is `draft` and explicitly blocked. Review happens at activation time, after Plan 1 Phase 1 data is in hand.

## 8. Decision Rule (for activation)

Activate this plan when ALL of the following are true:
- Plan 1 (`docs/plans/2026-09-26-tool-surface-quality.md`) Phase 1 is `shipped` or `complete`.
- Akosha has ≥7 days of `mcp_tool_call` traces covering at least the top-20 tools.
- A short proposal document exists that names the fixture list and rubric strategy.
- A reviewer (per Phase 0 convention) has signed off on the fixture list.
