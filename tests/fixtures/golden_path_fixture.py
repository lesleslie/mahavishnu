"""Deterministic fixture packet for the C5 golden-path prep harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MockServiceContract:
    """Canonical mock contract for a cross-repo service."""

    repo: str
    owner_role: str
    entrypoints: tuple[str, ...]
    preserved_surfaces: tuple[str, ...]
    mock_strategy: str


@dataclass(frozen=True)
class GoldenPathIncidentFixture:
    """Deterministic incident fixture used for C5-prep and C5 transcripts."""

    incident_id: str
    correlation_id: str
    workflow_id: str
    issue_id: str
    repo: str
    summary: str
    detection_source: str
    recovery_goal: str
    trace_assertions: tuple[str, ...]
    operator_transcript: tuple[str, ...]
    service_contracts: tuple[MockServiceContract, ...]


def golden_path_incident_fixture() -> GoldenPathIncidentFixture:
    """Return the named golden-path fixture used by the contract packet."""
    correlation_id = "corr-20260511-golden-path-001"
    workflow_id = "wf-20260511-golden-path-001"
    return GoldenPathIncidentFixture(
        incident_id="INC-20260511-001",
        correlation_id=correlation_id,
        workflow_id=workflow_id,
        issue_id="ISSUE-2048",
        repo="mahavishnu",
        summary="Quality gate failure on a repo-local fix path with operator approval required.",
        detection_source="Mahavishnu quality gate + event spine",
        recovery_goal="Validate fix, persist checkpoints, and preserve cross-system traceability.",
        trace_assertions=(
            f"The same correlation_id {correlation_id} is present from detection through validation.",
            "Session-Buddy stores the workflow checkpoint for the incident flow.",
            "Crackerjack quality validation is recorded before approval is granted.",
            "Dhara persists workflow, pool, routing, and approval checkpoints.",
            "Akosha receives derived incident/fix memory after validation.",
        ),
        operator_transcript=(
            f"Incident detected for ISSUE-2048 with correlation {correlation_id}.",
            "Quality gate run delegated to Crackerjack and returned a blocking failure.",
            f"Session-Buddy checkpoint created for workflow {workflow_id}.",
            "Operator approval requested before fix execution is resumed.",
            f"Dhara recovery state shows the same correlation and workflow identifiers ({correlation_id}, {workflow_id}).",
            "Akosha indexed the validated fix for semantic retrieval.",
            "Operator cockpit reports the incident resolved and searchable.",
        ),
        service_contracts=(
            MockServiceContract(
                repo="crackerjack",
                owner_role="inspector",
                entrypoints=(
                    "QualityGateManager.run_all_checks",
                    "QualityGateManager.validate_for_completion",
                ),
                preserved_surfaces=("run_qc", "get_qc_thresholds", "set_qc_thresholds"),
                mock_strategy="Return a deterministic pass/fail score and issue list.",
            ),
            MockServiceContract(
                repo="session-buddy",
                owner_role="manager",
                entrypoints=("SessionBuddy.create_checkpoint", "SessionBuddy.update_checkpoint"),
                preserved_surfaces=("get_checkpoint", "restore_from_checkpoint"),
                mock_strategy="Persist a stable workflow checkpoint and replay it on restart.",
            ),
            MockServiceContract(
                repo="akosha",
                owner_role="seer",
                entrypoints=(
                    "CoordinationMemory.store_issue_event",
                    "CoordinationMemory.store_plan_event",
                    "CoordinationMemory.search_coordination_history",
                ),
                preserved_surfaces=("semantic search", "derived-memory indexing"),
                mock_strategy="Index derived incident/fix memory with the shared correlation_id.",
            ),
            MockServiceContract(
                repo="dhara",
                owner_role="curator",
                entrypoints=(
                    "DharaStateBackend.persist_workflow",
                    "DharaStateBackend.persist_pool",
                    "DharaStateBackend.persist_routing_decision",
                    "DharaStateBackend.persist_approval",
                ),
                preserved_surfaces=(
                    "recover_workflows",
                    "recover_pools",
                    "recover_routing_decisions",
                    "recover_approvals",
                ),
                mock_strategy="Persist durable state checkpoints and replay them after restart.",
            ),
        ),
    )


def golden_path_contract_packet() -> dict[str, object]:
    """Return a JSON-serializable contract packet for the golden-path prep artifact."""
    fixture = golden_path_incident_fixture()
    return {
        "fixture": {
            "incident_id": fixture.incident_id,
            "correlation_id": fixture.correlation_id,
            "workflow_id": fixture.workflow_id,
            "issue_id": fixture.issue_id,
            "repo": fixture.repo,
            "summary": fixture.summary,
            "detection_source": fixture.detection_source,
            "recovery_goal": fixture.recovery_goal,
        },
        "trace_assertions": list(fixture.trace_assertions),
        "operator_transcript": list(fixture.operator_transcript),
        "service_contracts": [
            {
                "repo": contract.repo,
                "owner_role": contract.owner_role,
                "entrypoints": list(contract.entrypoints),
                "preserved_surfaces": list(contract.preserved_surfaces),
                "mock_strategy": contract.mock_strategy,
            }
            for contract in fixture.service_contracts
        ],
    }
