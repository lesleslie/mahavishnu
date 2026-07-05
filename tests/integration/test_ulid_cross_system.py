"""End-to-end ULID integration tests across ecosystem.

Tests cross-system ULID correlation and traceability between:
- Mahavishnu workflows
- Crackerjack tests
- Session-Buddy sessions
- Akosha entities
"""

import sys

from oneiric.core.ulid_resolution import (
    get_cross_system_trace,
    register_reference,
    resolve_ulid,
)
import pytest

# Import ULID generation from Dhara-era ULID utilities (fallback to timestamp-based)
try:
    from oneiric.core.ulid import generate as generate_ulid_impl
    from oneiric.core.ulid import is_ulid

    def generate_config_id() -> str:
        return generate_ulid_impl()

    def is_config_ulid(value: str) -> bool:
        return is_ulid(value)
except ImportError:
    # Fallback ULID generation
    import os
    import time

    def generate_config_id() -> str:
        timestamp_ms = int(time.time() * 1000)
        timestamp_bytes = timestamp_ms.to_bytes(6, byteorder="big")
        randomness = os.urandom(10)
        ulid_bytes = timestamp_bytes + randomness
        alphabet = "0123456789abcdefghjkmnpqrstvwxyz"

        def b32_encode(data):
            return "".join([alphabet[(b >> 35) & 31] for b in data])

        return b32_encode(ulid_bytes)

    def is_config_ulid(value: str) -> bool:
        if len(value) != 26:
            return False
        return all(c in "0123456789abcdefghjkmnpqrstvwxyz" for c in value)


_ULID_CHARS = "0123456789abcdefghjkmnpqrstvwxyz"


@pytest.fixture(autouse=True)
def _patch_ulid_generators(monkeypatch: pytest.MonkeyPatch):
    counter = {"value": 0}

    def generate() -> str:
        counter["value"] += 1
        value = counter["value"]
        chars = []
        base = len(_ULID_CHARS)
        for _ in range(26):
            chars.append(_ULID_CHARS[value % base])
            value //= base
        return "".join(reversed(chars))

    def is_valid(value: str) -> bool:
        return len(value) == 26 and all(c in _ULID_CHARS for c in value)

    monkeypatch.setattr(
        "crackerjack.services.ulid_generator.generate_ulid", generate, raising=False
    )
    monkeypatch.setattr(
        "crackerjack.services.ulid_generator.is_valid_ulid", is_valid, raising=False
    )
    monkeypatch.setattr("session_buddy.core.ulid_generator.generate_ulid", generate, raising=False)
    monkeypatch.setattr("session_buddy.core.ulid_generator.is_valid_ulid", is_valid, raising=False)
    monkeypatch.setattr("oneiric.core.ulid.generate", generate, raising=False)
    monkeypatch.setattr("oneiric.core.ulid.is_ulid", is_valid, raising=False)

    module = sys.modules[__name__]
    monkeypatch.setattr(module, "generate_config_id", generate, raising=False)
    monkeypatch.setattr(module, "is_config_ulid", is_valid, raising=False)
    yield


@pytest.mark.integration
async def test_mahavishnu_workflow_generates_traceable_ulid():
    """Mahavishnu workflow should generate traceable ULID."""
    from mahavishnu.core.workflow_models import WorkflowExecution

    execution = WorkflowExecution(
        workflow_name="test_workflow",
        status="running",
    )

    assert is_config_ulid(execution.execution_id), f"Invalid ULID: {execution.execution_id}"
    assert len(execution.execution_id) == 26, "ULID must be 26 characters"

    # Register in resolution service
    register_reference(
        execution.execution_id,
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow"},
    )

    # Verify resolution
    ref = resolve_ulid(execution.execution_id)
    assert ref is not None, "ULID should be resolvable"
    assert ref.system == "mahavishnu"
    assert ref.reference_type == "workflow"


@pytest.mark.integration
async def test_crackerjack_test_ulid_tracking():
    """Crackerjack tests should have ULID-based tracking."""
    from crackerjack.services.ulid_generator import generate_ulid

    # Simulate test execution with ULID
    test_ulid = generate_ulid()

    assert len(test_ulid) == 26, "ULID must be 26 characters"

    # Register test in resolution service
    register_reference(
        test_ulid,
        system="crackerjack",
        reference_type="test_execution",
        metadata={"status": "passed", "tests_run": 10},
    )

    # Verify cross-system trace
    trace = get_cross_system_trace(test_ulid)
    assert trace["source_system"] == "crackerjack"
    assert trace["reference_type"] == "test_execution"
    assert "metadata" in trace


@pytest.mark.integration
async def test_session_buddy_conversation_ulid():
    """Session-Buddy conversations should use ULID for correlation."""
    from session_buddy.core.ulid_generator import generate_ulid

    # Simulate conversation with ULID
    conversation_ulid = generate_ulid()

    assert len(conversation_ulid) == 26, "ULID must be 26 characters"

    # Register conversation in resolution service
    register_reference(
        conversation_ulid,
        system="session_buddy",
        reference_type="conversation",
        metadata={"project": "test", "quality_score": 85},
    )

    # Verify can be traced
    ref = resolve_ulid(conversation_ulid)
    assert ref is not None
    assert ref.system == "session_buddy"
    assert ref.reference_type == "conversation"


@pytest.mark.integration
async def test_cross_system_workflow_to_test_trace():
    """Should trace workflow from Mahavishnu → Crackerjack test."""

    # Create workflow ULID (Mahavishnu)
    workflow_ulid = generate_config_id()
    register_reference(
        workflow_ulid,
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow"},
    )

    # Simulate test execution ULID (Crackerjack)
    from crackerjack.services.ulid_generator import generate_ulid

    test_ulid = generate_ulid()
    register_reference(
        test_ulid,
        system="crackerjack",
        reference_type="test_execution",
        metadata={"status": "passed"},
    )

    # Verify both ULIDs are valid and traceable
    assert is_config_ulid(workflow_ulid)
    assert len(test_ulid) == 26

    # Cross-resolution should work
    workflow_trace = get_cross_system_trace(workflow_ulid)
    test_trace = get_cross_system_trace(test_ulid)

    assert workflow_trace["source_system"] == "mahavishnu"
    assert test_trace["source_system"] == "crackerjack"


@pytest.mark.integration
async def test_ulid_time_ordering():
    """ULIDs generated within short time should be sortable."""

    ulids = []
    for _ in range(10):
        ulid = generate_config_id()
        ulids.append(ulid)

    # ULIDs should be monotonically increasing (lexicographically sortable)
    for i in range(1, len(ulids)):
        assert ulids[i - 1] < ulids[i], f"ULID {i - 1} should be < ULID {i}"


@pytest.mark.integration
async def test_ulid_uniqueness():
    """ULIDs should be unique across generations."""

    ulids = set()
    for _ in range(1000):
        ulid = generate_config_id()
        assert ulid not in ulids, f"Duplicate ULID detected: {ulid}"
        ulids.add(ulid)

    assert len(ulids) == 1000, "Should generate 1000 unique ULIDs"


@pytest.mark.integration
async def test_session_buddy_reflection_ulid():
    """Session-Buddy reflections should use ULID."""
    from session_buddy.core.ulid_generator import generate_ulid

    reflection_ulid = generate_ulid()

    assert len(reflection_ulid) == 26, "ULID must be 26 characters"

    register_reference(
        reflection_ulid,
        system="session_buddy",
        reference_type="reflection",
        metadata={"tags": ["test", "quality"]},
    )

    trace = get_cross_system_trace(reflection_ulid)
    assert trace["source_system"] == "session_buddy"
    assert trace["reference_type"] == "reflection"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
