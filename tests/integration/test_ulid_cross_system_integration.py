"""End-to-end ULID integration tests across ecosystem systems.

Tests complete cross-system traceability from Mahavishnu workflows
through Akosha entities, Crackerjack tests, and Session-Buddy sessions.

Note: Oneiric path is configured in tests/conftest.py
"""

import pytest
from datetime import datetime


@pytest.fixture
def clear_ulid_registry():
    """Clear ULID registry before tests that need clean state."""
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()
    yield
    # Cleanup after test
    _ulid_registry.clear()


@pytest.mark.integration
async def test_workflow_creates_ulid_with_cross_system_trace():
    """Mahavishnu workflow should generate traceable ULID and correlate across systems."""
    # Import here to avoid module-level import issues
    from mahavishnu.core.workflow_models import WorkflowExecution
    from oneiric.core.ulid_resolution import (
        register_reference,
        resolve_ulid,
        get_cross_system_trace,
    )

    # Create workflow execution with ULID
    execution = WorkflowExecution(
        workflow_name="test_workflow",
        status="running",
    )

    # Verify ULID format (26 chars, alphanumeric)
    assert len(execution.execution_id) == 26
    assert execution.execution_id.isalnum()

    # Register in resolution service
    register_reference(
        execution.execution_id,
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow"},
    )

    # Verify cross-system resolution
    ref = resolve_ulid(execution.execution_id)
    assert ref is not None
    assert ref.system == "mahavishnu"
    assert ref.reference_type == "workflow"

    # Get complete trace
    trace = get_cross_system_trace(execution.execution_id)
    assert trace["ulid"] == execution.execution_id
    assert trace["source_system"] == "mahavishnu"
    assert "timestamp_ms" in trace
    assert "registered_at" in trace


@pytest.mark.integration
async def test_akosha_entity_ulid_resolution():
    """Akosha entities should use ULID and be resolvable across systems."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        resolve_ulid,
        find_references_by_system,
    )
    from dhruva import generate

    # Generate ULID for Akosha entity
    entity_ulid = generate()
    entity_type = "test_entity"

    # Register entity
    register_reference(
        entity_ulid,
        system="akosha",
        reference_type="entity",
        metadata={"entity_type": entity_type, "name": "test_entity"},
    )

    # Verify resolution
    ref = resolve_ulid(entity_ulid)
    assert ref is not None
    assert ref.system == "akosha"
    assert ref.reference_type == "entity"
    assert ref.metadata.get("entity_type") == entity_type

    # Verify find by system
    akosha_refs = find_references_by_system("akosha")
    assert len(akosha_refs) >= 1
    assert all(ref.system == "akosha" for ref in akosha_refs)


@pytest.mark.integration
async def test_crackerjack_test_ulid_tracking():
    """Crackerjack tests should have ULID-based tracking and cross-system resolution."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        resolve_ulid,
        get_cross_system_trace,
    )
    from dhruva import generate

    # Generate ULID for Crackerjack test
    test_ulid = generate()

    # Register test execution
    register_reference(
        test_ulid,
        system="crackerjack",
        reference_type="test",
        metadata={"test_file": "test_api.py", "status": "passed"},
    )

    # Verify resolution
    ref = resolve_ulid(test_ulid)
    assert ref is not None
    assert ref.system == "crackerjack"
    assert ref.reference_type == "test"
    assert ref.metadata.get("test_file") == "test_api.py"
    assert ref.metadata.get("status") == "passed"

    # Get cross-system trace
    trace = get_cross_system_trace(test_ulid)
    assert trace["ulid"] == test_ulid
    assert trace["source_system"] == "crackerjack"
    assert trace["reference_type"] == "test"
    assert "metadata" in trace


@pytest.mark.integration
async def test_session_buddy_ulid_integration():
    """Session-Buddy sessions should use ULID for correlation."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        resolve_ulid,
        find_references_by_system,
    )
    from dhruva import generate

    # Generate ULID for Session-Buddy session
    session_ulid = generate()

    # Register session
    register_reference(
        session_ulid,
        system="session-buddy",
        reference_type="session",
        metadata={"project": "test_project", "duration_minutes": 45},
    )

    # Verify session resolution
    ref = resolve_ulid(session_ulid)
    assert ref is not None
    assert ref.system == "session-buddy"
    assert ref.reference_type == "session"
    assert ref.metadata.get("project") == "test_project"

    # Verify find by system
    session_refs = find_references_by_system("session-buddy")
    assert len(session_refs) >= 1


@pytest.mark.integration
async def test_cross_system_time_correlation():
    """Should find ULIDs correlated by time proximity across systems."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        find_related_ulids,
        get_cross_system_trace,
    )
    from dhruva import generate

    # Generate ULIDs at approximately same time
    ulid1 = generate()
    ulid2 = generate()  # Will be within same millisecond

    # Register both
    register_reference(ulid1, "mahavishnu", "workflow", {"index": 1})
    register_reference(ulid2, "crackerjack", "test", {"index": 2})

    # Find related (1 minute window)
    related = find_related_ulids(ulid1, time_window_ms=60000)

    # Should find both ULIDs
    assert len(related) == 2
    assert ulid1 in related
    assert ulid2 in related


@pytest.mark.integration
async def test_cross_system_complete_trace(clear_ulid_registry):
    """Should provide complete trace across all systems."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        find_references_by_system,
        export_registry,
        get_registry_stats,
    )
    from dhruva import generate

    # Register references from all systems
    mahavishnu_ulid = generate()
    akosha_ulid = generate()
    crackerjack_ulid = generate()
    session_ulid = generate()

    register_reference(mahavishnu_ulid, "mahavishnu", "workflow", {"name": "test_workflow"})
    register_reference(akosha_ulid, "akosha", "entity", {"type": "test_entity"})
    register_reference(crackerjack_ulid, "crackerjack", "test", {"file": "test.py"})
    register_reference(session_ulid, "session-buddy", "session", {"project": "test_project"})

    # Export registry
    exported = export_registry()

    assert len(exported) == 4
    assert mahavishnu_ulid in exported
    assert akosha_ulid in exported
    assert crackerjack_ulid in exported
    assert session_ulid in exported

    # Get stats
    stats = get_registry_stats()

    assert stats["total_registrations"] == 4
    assert stats["by_system"]["mahavishnu"] == 1
    assert stats["by_system"]["akosha"] == 1
    assert stats["by_system"]["crackerjack"] == 1
    assert stats["by_system"]["session-buddy"] == 1

    # Verify find by system works
    mahavishnu_refs = find_references_by_system("mahavishnu")
    assert len(mahavishnu_refs) == 1
    assert mahavishnu_refs[0].system == "mahavishnu"


@pytest.mark.integration
async def test_ulid_time_based_sorting():
    """ULIDs should be time-ordered for chronological queries."""
    from dhruva import generate
    from oneiric.core.ulid import extract_timestamp

    # Generate 3 ULIDs in sequence
    ulids = [generate() for _ in range(3)]

    # Extract timestamps
    timestamps = [extract_timestamp(u) for u in ulids]

    # Verify chronological ordering
    assert timestamps[0] <= timestamps[1]
    assert timestamps[1] <= timestamps[2]

    # ULIDs should also be lexicographically sortable
    assert ulids[0] <= ulids[1]
    assert ulids[1] <= ulids[2]


@pytest.mark.integration
async def test_ulid_uniqueness_across_systems():
    """ULIDs should be unique across all systems in registry."""
    from oneiric.core.ulid_resolution import (
        register_reference,
        export_registry,
    )
    from dhruva import generate

    # Generate 1000 ULIDs and register
    ulids = [generate() for _ in range(1000)]
    for ulid in ulids:
        register_reference(
            ulid,
            system=f"test_system_{hash(ulid) % 10}",
            reference_type="test_ref",
        )

    # Export and check uniqueness
    exported = export_registry()

    assert len(exported) == 1000
    assert len(set(exported.keys())) == 1000  # All unique
