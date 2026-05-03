# Initiative 12: Golden Paths for Top Workflows

## Metadata

- Status: `complete`
- Owner Role: `Platform + DX`
- Target Window: `2026-06-01` to `2026-06-26`

## Outcome

Define and enforce canonical high-value orchestration workflows.

## Work Package Checklist

- [x] `I12-1` Select top 10 workflows + baseline metrics
- [x] `I12-2` Implement canonical CLI/MCP pathways
- [x] `I12-3` Add non-canonical warnings and docs

## Dependencies

- `I5-3`, `I9-3`

## Exit Criteria

- Ad hoc workflow variance reduced by `>=30%`

## Risks

- Over-constraining valid advanced use cases
- Incomplete coverage of high-frequency workflows

## Progress Log

- 2026-04-04: Plan file created.
- 2026-04-05: I12-1 complete — top 10 workflows cataloged with baseline metrics. Report: `docs/reports/top-10-workflows-baseline.md`. Key gap: no end-to-end latency or success rate tracking for most workflows.
- 2026-04-05: I12-2 complete — added canonical CLI pathways for all 10 top workflows:
  - `mahavishnu workflow` sub-app: sweep, quality-check, heal, fix, review (5 commands)
  - `mahavishnu adapter` sub-app: list, resolve, health (3 commands)
  - Legacy `sweep` command preserved with deprecation hint pointing to `workflow sweep`
  - All commands use correct internal APIs (DeadLetterQueue.retry_task, FixOrchestrator, HybridAdapterRegistry, SelfImprovementTools, TaskRouter with TaskType enum)
  - 7 async helper functions with lazy imports to match existing patterns
  - Tests: `tests/unit/test_workflow_cli.py` (26 AST-based checks, standalone runner due to I9 import timeout)
  - Coverage: 8 new CLI commands covering workflows 3-6 and 10 (workflows 1,2,7,8,9 already had CLI)
- 2026-04-05: I12-3 complete — golden-path docstring notices added to 9 internal API methods across 6 modules (app.py, fix_orchestrator.py, dead_letter_queue.py, adapter_registry.py, backup_recovery.py, self_improvement_tools.py). Golden paths guide written at docs/reports/golden-paths-guide.md with per-workflow CLI/MCP pathways, quick reference, non-canonical usage warnings table, and guide for adding new golden paths.
