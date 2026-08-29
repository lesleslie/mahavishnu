from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.core.config import MahavishnuSettings


def test_settings_accepts_worker_registry_block() -> None:
    s = MahavishnuSettings.model_validate({"worker_registry": {"entries": []}})
    assert hasattr(s, "worker_registry")


def test_settings_rejects_unknown_worker_block_keys() -> None:
    with pytest.raises(ValidationError):
        MahavishnuSettings.model_validate({"worker_registry": {"unknown_field": "x"}})


def test_worker_entry_rejects_invalid_capability_id() -> None:
    """provides list values must match CapabilityId pattern ^[a-z]+:[a-z0-9._-]+$."""
    with pytest.raises(ValidationError):
        MahavishnuSettings.model_validate({
            "worker_registry": {"entries": [
                {"worker_type": "x", "command_argv": ["bash"], "provides": ["BAD-ID"]},
            ]},
        })


def test_worker_entry_accepts_valid_capability_id() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "x", "command_argv": ["bash"], "provides": ["worker:bash"]},
        ]},
    })
    assert s.worker_registry.entries[0].provides == ["worker:bash"]


def test_worker_entry_name_is_optional() -> None:
    """name is optional — the Pydantic default is empty string."""
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "x", "command_argv": ["bash"], "provides": ["worker:bash"]},
        ]},
    })
    assert s.worker_registry.entries[0].name == ""
