from __future__ import annotations

from mahavishnu.core.config import MahavishnuSettings


def test_capability_flag_defaults_to_false() -> None:
    s = MahavishnuSettings()
    assert s.capability_enabled is False
    assert s.legacy_tools is False


def test_capability_scopes_default_empty() -> None:
    s = MahavishnuSettings()
    assert s.capability_scopes == []


def test_capability_scopes_validate_strings() -> None:
    s = MahavishnuSettings.model_validate({
        "capability_scopes": ["execute_capability", "list_capabilities"],
    })
    assert "execute_capability" in s.capability_scopes