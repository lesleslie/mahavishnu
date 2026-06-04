______________________________________________________________________

title: Quality Validation Toolkit
owner: Quality Engineering Guild
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts:
- scripts/test_matrix.py
  risk: medium
  id: 01K6EEQ3JBXJN4P7QMKN6SR58W
  status: active
  category: development/testing

______________________________________________________________________

## Quality Validation Toolkit

## Context

Product teams need a single orchestrator for functional, chaos, and multi-agent testing rather than juggling multiple oversized playbooks.

## Requirements

- Provide layered guidance for unit, integration, end-to-end, and exploratory testing.
- Support scenario toggles (functional, chaos, AI/multi-agent) with shared setup.
- Deliver reproducible fixtures, telemetry hooks, and release-readiness signals.

## Inputs

- `$PROJECT_PATH` — repository under test.
- `$STACK` — `python`, `node`, `go`, or `mixed` (required by `scripts/test_matrix.py --stack`).
- `$TEST_TYPES` — comma-separated list matching `scripts/test_matrix.py --types` (e.g. `unit,integration`, or `unit,integration,e2e,property,chaos`).
- `$COVERAGE_TARGET` — target line coverage percentage (default 80; passed to `--coverage-target`).
- `$TARGET_ENV` — environment or cluster name for validation (optional).

## Outputs

- Test execution plan aligned with selected scenarios.
- Observability checklist and gating criteria for release readiness.
- Follow-up actions for defects, flaky tests, or resilience gaps.
- **Coverage matrix** (`test-matrix.json` + `test-matrix.md`): the artifacts produced by `scripts/test_matrix.py`. Read `summary.below_target` for components missing at least one requested test type, and `cells[component][type].gaps` for human-readable gap descriptions. The Markdown companion gives a tabular view of the same data.

## Instructions

1. Generate the on-disk coverage matrix (required by `required_scripts: scripts/test_matrix.py`):
   `python scripts/test_matrix.py --project "$PROJECT_PATH" --stack "$STACK" --types "$TEST_TYPES" --coverage-target "$COVERAGE_TARGET" --out test-matrix.json --out-md test-matrix.md`
1. Assemble baseline coverage, CI jobs, critical paths, and release constraints.
1. Select scenarios and tailor the plan:
   - `functional`: unit, service, UI, contract, and coverage checks.
   - `chaos`: failure injection, steady-state metrics, rollback proof.
   - `multi-agent`: handoffs, prompt datasets, and guardrails.
1. Run the highest-value suites first and capture logs, traces, metrics, and flaky failures.
1. Summarize release posture with pass/fail status, risks, gates, and follow-up work.

## Dependencies

- Access to CI pipelines or local runners with necessary credentials.
- Observability stack configured for log/trace collection during tests.
- Test data management policies for synthetic or production-derived datasets.

______________________________________________________________________
