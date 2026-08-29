"""Tests for Oneiric-driven capability loader."""
from __future__ import annotations

from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.capabilities import CapabilityKind, CapabilityState
from mahavishnu.core.config import MahavishnuSettings


def test_load_capabilities_groups_by_id() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "a", "command_argv": ["x"], "provides": ["worker:ai-context"], "name": "A"},
            {"worker_type": "b", "command_argv": ["y"], "provides": ["worker:ai-context"], "name": "B"},
        ]},
    })
    caps = load_capabilities_from_settings(s)
    # Both A and B provide worker:ai-context — caller must get a list of 2.
    assert "worker:ai-context" in caps
    assert len(caps["worker:ai-context"]) == 2
    assert {c.description for c in caps["worker:ai-context"]} == {"A", "B"}


def test_load_capabilities_includes_kind_and_state() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "a", "command_argv": ["x"], "provides": ["worker:bash"], "name": "Bash"},
        ]},
    })
    caps = load_capabilities_from_settings(s)
    cap = caps["worker:bash"][0]
    assert cap.kind == CapabilityKind.WORKER
    assert cap.state == CapabilityState.EPHEMERAL
