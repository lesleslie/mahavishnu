# Golden Path Contract Packet

Generated for the C5-prep harness.

## Named Fixture

- Incident ID: `INC-20260511-001`
- Correlation ID: `corr-20260511-golden-path-001`
- Workflow ID: `wf-20260511-golden-path-001`
- Issue ID: `ISSUE-2048`
- Repo: `mahavishnu`
- Recovery goal: validate a fix, persist checkpoints, and preserve cross-system traceability.

## Trace Assertions

1. The same `correlation_id` is present from detection through validation.
1. Session-Buddy stores the workflow checkpoint for the incident flow.
1. Crackerjack quality validation is recorded before approval is granted.
1. Dhara persists workflow, pool, routing, and approval checkpoints.
1. Akosha receives derived incident/fix memory after validation.

## Mock Service Contracts

### Crackerjack

- Owner role: `inspector`
- Entry points: `QualityGateManager.run_all_checks`, `QualityGateManager.validate_for_completion`
- Preserved surfaces: `run_qc`, `get_qc_thresholds`, `set_qc_thresholds`
- Mock strategy: return a deterministic pass/fail score and issue list.

### Session-Buddy

- Owner role: `manager`
- Entry points: `SessionBuddy.create_checkpoint`, `SessionBuddy.update_checkpoint`
- Preserved surfaces: `get_checkpoint`, `restore_from_checkpoint`
- Mock strategy: persist a stable workflow checkpoint and replay it on restart.

### Akosha

- Owner role: `seer`
- Entry points: `CoordinationMemory.store_issue_event`, `CoordinationMemory.store_plan_event`, `CoordinationMemory.search_coordination_history`
- Preserved surfaces: semantic search, derived-memory indexing
- Mock strategy: index derived incident/fix memory with the shared correlation ID.

### Dhara

- Owner role: `curator`
- Entry points: `DharaStateBackend.persist_workflow`, `DharaStateBackend.persist_pool`, `DharaStateBackend.persist_routing_decision`, `DharaStateBackend.persist_approval`
- Preserved surfaces: `recover_workflows`, `recover_pools`, `recover_routing_decisions`, `recover_approvals`
- Mock strategy: persist durable checkpoints and replay them after restart.

## Operator Transcript Shape

- Incident detected for `ISSUE-2048`.
- Quality gate run delegated to Crackerjack and returned a blocking failure.
- Session-Buddy checkpoint created.
- Operator approval requested before fix execution resumes.
- Dhara recovery state shows the same correlation and workflow identifiers.
- Akosha indexed the validated fix.
- Operator cockpit reports the incident resolved and searchable.
