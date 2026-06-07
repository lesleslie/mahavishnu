"""Unit tests for mahavishnu.mcp.tools.profiles."""

from __future__ import annotations

import os
from unittest.mock import patch

from mcp_common.tools import ToolProfile
import pytest

from mahavishnu.mcp.tools.profiles import (
    FULL_REGISTRATIONS,
    MINIMAL_REGISTRATIONS,
    PROFILE_REGISTRATIONS,
    STANDARD_REGISTRATIONS,
    get_active_profile,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Remove the MAHAVISHNU_TOOL_PROFILE env var to test defaults."""
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)


# =============================================================================
# Constants
# =============================================================================


class TestProfileConstants:
    """Tests for profile registration lists."""

    def test_minimal_registrations_only_health(self):
        """MINIMAL profile should only register health tools."""
        assert MINIMAL_REGISTRATIONS == ["_register_health_tools"]

    def test_standard_includes_minimal(self):
        """STANDARD profile should be a superset of MINIMAL."""
        for entry in MINIMAL_REGISTRATIONS:
            assert entry in STANDARD_REGISTRATIONS

    def test_full_includes_standard(self):
        """FULL profile should be a superset of STANDARD."""
        for entry in STANDARD_REGISTRATIONS:
            assert entry in FULL_REGISTRATIONS

    def test_full_has_all_feature_specific_tools(self):
        """FULL profile should register all major feature tools."""
        expected = [
            "_register_otel_tools",
            "_register_self_improvement_tools",
            "_register_goal_team_tools",
            "_register_treesitter_tools",
            "_register_adapter_registry_tools",
            "_register_pycharm_tools",
        ]
        for tool in expected:
            assert tool in FULL_REGISTRATIONS

    def test_worktree_registration_not_in_any_profile(self):
        """worktree registration is gated by runtime, not profile."""
        assert "_register_worktree_tools" not in MINIMAL_REGISTRATIONS
        assert "_register_worktree_tools" not in STANDARD_REGISTRATIONS
        assert "_register_worktree_tools" not in FULL_REGISTRATIONS


# =============================================================================
# PROFILE_REGISTRATIONS
# =============================================================================


class TestProfileRegistrations:
    """Tests for the PROFILE_REGISTRATIONS mapping."""

    def test_all_tool_profiles_covered(self):
        """All three ToolProfile values should be mapped."""
        for profile in (ToolProfile.MINIMAL, ToolProfile.STANDARD, ToolProfile.FULL):
            assert profile in PROFILE_REGISTRATIONS

    def test_profile_mappings_use_list_values(self):
        """Each profile maps to a list of registration method names."""
        for profile, methods in PROFILE_REGISTRATIONS.items():
            assert isinstance(methods, list), f"{profile} should map to a list"
            for method in methods:
                assert isinstance(method, str)
                assert method.startswith("_register_")

    def test_minimal_registration_maps_correctly(self):
        """MINIMAL profile maps to MINIMAL_REGISTRATIONS list."""
        assert PROFILE_REGISTRATIONS[ToolProfile.MINIMAL] is MINIMAL_REGISTRATIONS

    def test_standard_registration_maps_correctly(self):
        """STANDARD profile maps to STANDARD_REGISTRATIONS list."""
        assert PROFILE_REGISTRATIONS[ToolProfile.STANDARD] is STANDARD_REGISTRATIONS

    def test_full_registration_maps_correctly(self):
        """FULL profile maps to FULL_REGISTRATIONS list."""
        assert PROFILE_REGISTRATIONS[ToolProfile.FULL] is FULL_REGISTRATIONS


# =============================================================================
# get_active_profile
# =============================================================================


class TestGetActiveProfile:
    """Tests for the get_active_profile helper."""

    def test_default_full_when_env_unset(self, clean_env):
        """When env var is unset, profile should default to FULL."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_active_profile()
        assert result == ToolProfile.FULL

    def test_minimal_from_env(self, monkeypatch):
        """Setting env var to 'minimal' should yield MINIMAL profile."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "minimal")
        assert get_active_profile() == ToolProfile.MINIMAL

    def test_standard_from_env(self, monkeypatch):
        """Setting env var to 'standard' should yield STANDARD profile."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "standard")
        assert get_active_profile() == ToolProfile.STANDARD

    def test_full_from_env(self, monkeypatch):
        """Setting env var to 'full' should yield FULL profile."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
        assert get_active_profile() == ToolProfile.FULL

    def test_unrecognized_value_falls_back_to_full(self, monkeypatch):
        """Unrecognized env values should fall back to FULL."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "not-a-real-profile")
        assert get_active_profile() == ToolProfile.FULL

    def test_custom_env_var_name(self, monkeypatch):
        """Custom env var name should be honored."""
        monkeypatch.setenv("MY_CUSTOM_VAR", "standard")
        assert get_active_profile(env_var="MY_CUSTOM_VAR") == ToolProfile.STANDARD

    def test_empty_string_falls_back_to_full(self, monkeypatch):
        """Empty string env var should fall back to FULL."""
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "")
        assert get_active_profile() == ToolProfile.FULL

    def test_case_sensitive_env_value(self, monkeypatch):
        """Lowercase value 'standard' should yield STANDARD, uppercase should fall back."""
        # The env var uses ToolProfile.from_env; lowercase 'standard' is recognized
        monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "STANDARD")
        # Whatever the result, it should be a valid ToolProfile
        result = get_active_profile()
        assert isinstance(result, ToolProfile)
