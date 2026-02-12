"""Basic ULID generation tests for all systems.

Tests ULID generation functionality without cross-system dependencies.
"""

import sys
from pathlib import Path

# Add project paths to Python path
sys.path.insert(0, str(Path("/Users/les/Projects/crackerjack")))
sys.path.insert(0, str(Path("/Users/les/Projects/session-buddy")))

import pytest


def test_mahavishnu_workflow_ulid_generation():
    """Mahavishnu workflows should generate valid ULIDs."""
    from mahavishnu.core.workflow_models import WorkflowExecution

    execution = WorkflowExecution(
        workflow_name="test_workflow",
        status="running",
    )

    assert execution.execution_id is not None
    assert len(execution.execution_id) == 26
    assert all(c in "0123456789abcdefghjkmnpqrstvwxyz" for c in execution.execution_id)


def test_crackerjack_ulid_generation():
    """Crackerjack should generate valid ULIDs."""
    from crackerjack.services.ulid_generator import generate_ulid, is_valid_ulid

    ulid = generate_ulid()
    assert is_valid_ulid(ulid)
    assert len(ulid) == 26


def test_session_buddy_ulid_generation():
    """Session-Buddy should generate valid ULIDs."""
    from session_buddy.core.ulid_generator import generate_ulid, is_valid_ulid

    ulid = generate_ulid()
    assert is_valid_ulid(ulid)
    assert len(ulid) == 26


def test_ulid_uniqueness():
    """ULIDs should be unique across 100 generations."""
    from crackerjack.services.ulid_generator import generate_ulid

    ulids = set()
    for _ in range(100):
        ulid = generate_ulid()
        assert ulid not in ulids, f"Duplicate ULID: {ulid}"
        ulids.add(ulid)

    assert len(ulids) == 100


def test_ulid_time_ordering():
    """ULIDs should be time-ordered (lexicographically sortable)."""

    from crackerjack.services.ulid_generator import generate_ulid
    import time

    ulids = []
    for _ in range(10):
        ulids.append(generate_ulid())
        time.sleep(0.001)  # 1ms delay to ensure different timestamps

    # Check monotonic ordering
    for i in range(1, len(ulids)):
        assert ulids[i-1] < ulids[i], f"ULID {i-1} should be < ULID {i}"


def test_ulid_format_consistency():
    """All ULID generators should produce same format."""

    from crackerjack.services.ulid_generator import generate_ulid as cj_generate
    from session_buddy.core.ulid_generator import generate_ulid as sb_generate
    from mahavishnu.core.workflow_models import WorkflowExecution

    # Generate ULIDs from all systems
    cj_ulid = cj_generate()
    sb_ulid = sb_generate()
    mahavishnu_execution = WorkflowExecution(**{"workflow_name": "test_workflow"})
    mv_ulid = mahavishnu_execution.execution_id

    # All should be 26 characters
    assert len(cj_ulid) == 26
    assert len(sb_ulid) == 26
    assert len(mv_ulid) == 26

    # All should use Crockford Base32 alphabet
    for ulid in [cj_ulid, sb_ulid, mv_ulid]:
        assert all(c in "0123456789abcdefghjkmnpqrstvwxyz" for c in ulid)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
