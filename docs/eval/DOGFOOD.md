# Dogfooding the model-evaluation framework

The dogfood set is Mahavishnu's own questions, asked of a model, scored
against phrases we believe are correct. It exists for one reason: to
catch a change that makes Mahavishnu's behaviour wrong *before* a user
does.

## What is in Phase 1

Phase 1 ships the framework, the golden set, and the plumbing:

- the four extension points (dataset loader, scorer, storage, model
  backend), discovered through entry points;
- `EvalEngine`, which composes them into a scored, persisted run;
- an `EvalPool`, three MCP tools (`eval_register_dataset`,
  `eval_run_suite`, `eval_get_run`), and an `/health` feed;
- a Markdown report writer and the `mahavishnu eval` CLI;
- 29 golden cases in [`dogfood-v0.jsonl`](dogfood-v0.jsonl).

**Phase 1 runs the set against the mock backend.** `mahavishnu.mock`
echoes the prompt back, so a Phase 1 run proves the *plumbing* — the
dataset loads, every case runs, every case is scored, the run is
persisted, the report is written, the health feed advances — and proves
nothing about a model's answers. The mean it reports is **0.000**,
deterministically: no case's expected phrase is in its own question
(a test enforces that, because an expectation inside its own question
is satisfied by the echo), so the echo never contains it. Read the
Phase 1 mean as "the harness works", not "the model is right" — and do
not go looking for a regression in it. The scorer the set is graded
with is `mahavishnu.contains`, which is what a phrase answer needs;
against the mock it simply has nothing to match.

**The set is re-reviewed in one pass.** All 29 cases carry the same
`last_reviewed` date, so the freshness gate
(`tests/integration/test_dogfood_freshness.py`) falls from 100% fresh to
0% fresh on a single day, roughly 90 days after the review. That is
deliberate: the gate is a forcing function for a *human* re-read, and
a cliff is louder than a slope. Expect to re-review the whole set in
one sitting.

**Phase 2 adds a real backend.** A model backend is one entry point
away:

```toml
[project.entry-points."mahavishnu.eval.model_backends"]
"mahavishnu.minimax" = "your.package.model_backends.minimax:MiniMaxBackend"
```

Once it is registered, the same golden set runs against a real model
with no change to the data:

```bash
mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl \
    --model mahavishnu.minimax --scorers mahavishnu.contains
```

The Phase 1 CLI already takes `--model` as a *backend name* for exactly
this reason. `MiniMax-M3` is a model name — it is what a backend is
asked to call, not a backend.

## The operating procedure

**1. Run it.**

```bash
mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl \
    --scorers mahavishnu.contains
```

The command prints the run id, status, case counts, mean score, cost,
and the path of the Markdown report.

**2. Read the report.**

The report is at `<run store>/reports/{run_id}.md` — by default
`~/.local/state/mahavishnu/eval/reports/`. It has the run header, the
summary, and one section per case with the model's output and every
scorer's verdict and reasoning. A failing case's reasoning says what
was missing.

**3. Compare against the last run.**

```bash
mahavishnu eval list-runs --limit 10
```

The mean score is the number to watch. Compare it with the previous
run's mean by eye: Phase 1 computes no regression threshold, because
regression detection is Phase 2 work and a setting that computes
nothing is a setting that lies.

**4. Triage the failures.**

A failing case is one of two things:

- **The model got it wrong.** The golden set is wrong, or the model is.
  Decide which, and record the decision in the case's
  `metadata.failure_mode`.
- **The golden set is stale.** The codebase moved and the expected
  phrase no longer describes Mahavishnu. Fix the case, bump
  `metadata.last_reviewed`, and move on.

Do not "fix" a failing case by loosening its expected phrase until it
passes. That is how a golden set stops being a golden set.

## Freshness

`tests/integration/test_dogfood_freshness.py` runs on every PR and
fails when fewer than 80% of the cases have been reviewed within the
last 90 days. A golden set nobody re-reads is a golden set that
certifies the wrong thing.

Reviewing a case means opening the code or the doc it asks about and
confirming the expected phrase is still what Mahavishnu does. Bump
`metadata.last_reviewed` when you do.

## Cost and budget

Every run is capped by `EvalSettings.cost_budget_per_run` (5.00 USD by
default). The engine tracks the actual cost of each completed case and
stops before starting another once the spend reaches the cap; a run
that ends strictly above the cap is reported as `budget_exceeded`
rather than `completed`. Override the cap per run with `--budget`.

The mock backend is free. A real backend costs what the provider
charges, so the budget cap is the thing that keeps a loop of
"re-run the golden set" from becoming an invoice.

## Where the pieces live

| Piece | Location |
|-------|----------|
| Golden set | [`docs/eval/dogfood-v0.jsonl`](dogfood-v0.jsonl) |
| Format and how to add cases | [`docs/eval/dogfood-v0.README.md`](dogfood-v0.README.md) |
| Scorers | `mahavishnu/core/eval/scorers/` |
| Model backends | `mahavishnu/core/eval/model_backends/` |
| Engine | `mahavishnu/core/eval/engine.py` |
| Report writer | `mahavishnu/core/eval/report.py` |
| CLI | `mahavishnu/cli/eval_cli.py` |
| MCP tools | `mahavishnu/mcp/tools/eval_tools.py` |
| Plan | `docs/plans/2026-10-03-eval-adapter-phase1.md` |
