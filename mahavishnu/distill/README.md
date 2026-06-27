# mahavishnu.distill

Distilled Workflows substrate (Plan 5). This module owns the storage
schema, the heuristic + LLM synthesizers, and the trust gates that
decide which workflow run records are eligible to feed the
distiller.

## Layout

| File | Role |
|------|------|
| `decorator.py` | `@mahavishnu_workflow(...)` decorator + `WorkflowSpec`. |
| `discovery.py` | File-system workflow discovery with quarantine invariant. |
| `schema.py` | DuckDB DDL for `distilled_workflows` + `mahavishnu_workflow_runs`. |
| `distiller.py` | `distill_workflows()` — runs the synthesis pass with the H4 + H6 pre-filter pipeline. |
| `reporter.py` | Telemetry writer (`report_run`, `safe_report_run`). |
| `synthesizer.py` | Phase A.1 LLM stub + cost ceiling (`MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP`). |
| `health.py` | 4-bucket classifier (stale / under_utilized / cold / fresh). |
| `reviewer.py` | **H6** — reviewer identity trust root (`MAHAVISHNU_USER_ID` + `MAHAVISHNU_PUBLISHER_ALLOWLIST`). |
| `provenance.py` | **H4** — source provenance gate (`check_source_purity`). |

## Trust gates (Plan 5 audit fixes)

The distiller runs two layered gates BEFORE any synthesis:

1. **H6 — Reviewer identity** (`mahavishnu.distill.reviewer`). When a
   `ReviewerIdentity` is passed to `distill_workflows(reviewer=...)`
   it is `enforce()`'d at function entry. Only an allowlisted
   reviewer (or bootstrap mode) can publish.

2. **H4 — Source provenance** (`mahavishnu.distill.provenance`). For
   each candidate session the distiller looks up the originating run
   record (`mahavishnu_workflow_runs`) and feeds it through
   `check_source_purity(run_record, allowlist=...)`. Records with an
   external source type, a missing reviewer identity, or an unlisted
   reviewer are rejected and logged.

Both gates are wired into `distill_workflows()` and log rejections
at WARNING level with `extra={"audit": True}` for forensic
visibility.

## Configuration

```yaml
# settings/mahavishnu.yaml
distill:
  publisher_allowlist: settings/distill_publishers.txt
  evidence_threshold: 3
  require_reviewer: true
```

Or via env vars (`MAHAVISHNU_DISTILL__*`).

The `MAHAVISHNU_PUBLISHER_ALLOWLIST` env var is also accepted
directly by `ReviewerIdentity.from_env()` — env wins.

## Tests

| Test file | What it covers |
|-----------|----------------|
| `tests/unit/test_distill_provenance.py` | H4 gate contract. |
| `tests/unit/test_distill_provenance_wired.py` | H4 wired into distiller pre-filter. |
| `tests/unit/test_reviewer_identity.py` | H6 reviewer gate contract + env interaction. |
| `tests/unit/test_distill_workflows.py` | Distiller pass + per-candidate isolation. |
| `tests/unit/test_distill_schema.py` | DDL invariants + idempotent apply. |
| `tests/unit/test_distill_reporter.py` | Telemetry writer + idempotency. |
| `tests/unit/test_distill_health.py` | 4-bucket classifier. |
| `tests/unit/test_distill_cost_ceiling.py` | LLM weekly cap + env var. |
| `tests/unit/test_distill_quarantine_regression.py` | Runtime + CI guard. |

## Runbooks

- `docs/runbooks/distill-reviewer-identity.md` (H6)
- `docs/runbooks/distill-source-provenance.md` (H4)
