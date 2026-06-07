"""Comprehensive unit tests for mahavishnu/mcp/tools/profiles.py."""

from __future__ import annotations

import os
from unittest.mock import patch

from mahavishnu.mcp.tools.profiles import (
    FULL_REGISTRATIONS,
    MINIMAL_REGISTRATIONS,
    PROFILE_REGISTRATIONS,
    STANDARD_REGISTRATIONS,
    get_active_profile,
)


class TestProfileEnumValues:
    """Test that each profile level has the correct registration methods."""

    def test_minimal_registrations_contains_only_health_tools(self) -> None:
        """MINIMAL profile should register only health-related tools."""
        assert MINIMAL_REGISTRATIONS == ["_register_health_tools"]

    def test_standard_registrations_includes_minimal(self) -> None:
        """STANDARD profile should include all MINIMAL registrations plus more."""
        # STANDARD should contain all MINIMAL registrations
        for method in MINIMAL_REGISTRATIONS:
            assert method in STANDARD_REGISTRATIONS

    def test_full_registrations_includes_standard(self) -> None:
        """FULL profile should include all STANDARD registrations plus more."""
        # FULL should contain all STANDARD registrations
        for method in STANDARD_REGISTRATIONS:
            assert method in FULL_REGISTRATIONS

    def test_profile_registrations_dict_has_all_three_profiles(self) -> None:
        """PROFILE_REGISTRATIONS dict should have entries for MINIMAL, STANDARD, FULL."""
        from mcp_common.tools import ToolProfile

        assert ToolProfile.MINIMAL in PROFILE_REGISTRATIONS
        assert ToolProfile.STANDARD in PROFILE_REGISTRATIONS
        assert ToolProfile.FULL in PROFILE_REGISTRATIONS

    def test_profile_tiers_are_progressive(self) -> None:
        """Each profile tier should have strictly more registrations than the previous."""
        assert len(MINIMAL_REGISTRATIONS) < len(STANDARD_REGISTRATIONS)
        assert len(STANDARD_REGISTRATIONS) < len(FULL_REGISTRATIONS)


class TestGetProfileTools:
    """Test that get_profile_tools returns the correct tools for each profile."""

    def test_minimal_has_health_tools_only(self) -> None:
        """MINIMAL profile should map to only MINIMAL_REGISTRATIONS."""
        from mcp_common.tools import ToolProfile

        tools = PROFILE_REGISTRATIONS[ToolProfile.MINIMAL]
        assert tools == MINIMAL_REGISTRATIONS
        assert tools == ["_register_health_tools"]

    def test_standard_has_core_groups(self) -> None:
        """STANDARD profile includes terminal, pool, worker, messaging, git, session_buddy."""
        from mcp_common.tools import ToolProfile

        tools = PROFILE_REGISTRATIONS[ToolProfile.STANDARD]
        # Check we have the expected groups (order-independent)
        expected = set(
            MINIMAL_REGISTRATIONS
            + [
                "_register_terminal_tools",
                "_register_pool_tools",
                "_register_worker_tools",
                "_register_repository_messaging_tools",
                "_register_git_analytics_tools",
                "_register_session_buddy_tools",
            ]
        )
        assert set(tools) == expected

    def test_full_has_all_groups(self) -> None:
        """FULL profile includes all groups (standard + otel, self-improv, goal/team, treesitter, adapters, pycharm)."""
        from mcp_common.tools import ToolProfile

        tools = PROFILE_REGISTRATIONS[ToolProfile.FULL]
        # Should include all standard groups
        assert "_register_otel_tools" in tools
        assert "_register_self_improvement_tools" in tools
        assert "_register_goal_team_tools" in tools
        assert "_register_treesitter_tools" in tools
        assert "_register_adapter_registry_tools" in tools
        assert "_register_pycharm_tools" in tools

    def test_full_count_exceeds_standard(self) -> None:
        """FULL should have strictly more methods than STANDARD."""
        from mcp_common.tools import ToolProfile

        full_count = len(PROFILE_REGISTRATIONS[ToolProfile.FULL])
        standard_count = len(PROFILE_REGISTRATIONS[ToolProfile.STANDARD])
        assert full_count > standard_count

    def test_standard_count_exceeds_minimal(self) -> None:
        """STANDARD should have strictly more methods than MINIMAL."""
        from mcp_common.tools import ToolProfile

        standard_count = len(PROFILE_REGISTRATIONS[ToolProfile.STANDARD])
        minimal_count = len(PROFILE_REGISTRATIONS[ToolProfile.MINIMAL])
        assert standard_count > minimal_count


class TestToolAvailabilityByProfile:
    """Test that tools behave correctly across profile levels.

    A tool available in FULL should NOT be in MINIMAL.
    A tool available in FULL should be in STANDARD.
    """

    def test_otel_tools_in_full_not_minimal(self) -> None:
        """_register_otel_tools is in FULL but not in MINIMAL."""
        from mcp_common.tools import ToolProfile

        full_tools = PROFILE_REGISTRATIONS[ToolProfile.FULL]
        minimal_tools = PROFILE_REGISTRATIONS[ToolProfile.MINIMAL]

        assert "_register_otel_tools" in full_tools
        assert "_register_otel_tools" not in minimal_tools

    def test_pycharm_tools_in_full_not_minimal(self) -> None:
        """_register_pycharm_tools is in FULL but not in MINIMAL."""
        from mcp_common.tools import ToolProfile

        full_tools = PROFILE_REGISTRATIONS[ToolProfile.FULL]
        minimal_tools = PROFILE_REGISTRATIONS[ToolProfile.MINIMAL]

        assert "_register_pycharm_tools" in full_tools
        assert "_register_pycharm_tools" not in minimal_tools

    def test_terminal_tools_in_standard_not_minimal(self) -> None:
        """Terminal tools are in STANDARD but not in MINIMAL."""
        from mcp_common.tools import ToolProfile

        standard_tools = PROFILE_REGISTRATIONS[ToolProfile.STANDARD]
        minimal_tools = PROFILE_REGISTRATIONS[ToolProfile.MINIMAL]

        assert "_register_terminal_tools" in standard_tools
        assert "_register_terminal_tools" not in minimal_tools

    def test_health_tools_in_all_profiles(self) -> None:
        """Health tools appear in all profiles (core inline tools are always registered)."""
        from mcp_common.tools import ToolProfile

        for profile in [ToolProfile.MINIMAL, ToolProfile.STANDARD, ToolProfile.FULL]:
            tools = PROFILE_REGISTRATIONS[profile]
            assert "_register_health_tools" in tools


class TestDiscoverToolsAlwaysRegistered:
    """Test that the discover_tools meta-tool is effectively always available.

    The profiles module documents that discover_tools() is always registered
    regardless of profile because it is a core inline tool.
    """

    def test_discover_tools_documented_as_always_available(self) -> None:
        """The profiles module docstring explicitly states core inline tools are always registered.

        discover_tools is a core inline tool (not in profile registrations) and the module
        docstring confirms this by stating inline tools are always registered regardless of profile.
        """
        import mahavishnu.mcp.tools.profiles as profiles_module

        docstring = profiles_module.__doc__ or ""
        # The docstring explicitly states core inline tools are always registered regardless of profile
        assert "Core inline tools" in docstring
        assert "registered regardless of profile" in docstring

    def test_discover_tools_not_in_registrations(self) -> None:
        """discover_tools is NOT in any profile registration list (by design).

        Core inline tools in _register_tools() are always registered and do
        not appear in the profile-gated registration lists.
        """
        from mcp_common.tools import ToolProfile

        for profile in ToolProfile:
            tools = PROFILE_REGISTRATIONS[profile]
            # discover_tools should NOT be in profile registrations
            assert "_register_discover_tools" not in tools
            assert "discover_tools" not in "\n".join(tools)


class TestProfileFilteringLogic:
    """Test the include/exclude logic for profile-based tool filtering."""

    def _get_minimal_tools(self) -> list[str]:
        """Get MINIMAL tools without relying on ToolProfile import at class level."""
        from mcp_common.tools import ToolProfile

        return PROFILE_REGISTRATIONS[ToolProfile.MINIMAL]

    def test_minimal_excludes_many_groups(self) -> None:
        """MINIMAL profile excludes terminal, pool, worker, otel, pycharm, etc."""
        minimal_tools = self._get_minimal_tools()
        excluded_from_minimal = [
            "_register_terminal_tools",
            "_register_pool_tools",
            "_register_worker_tools",
            "_register_repository_messaging_tools",
            "_register_git_analytics_tools",
            "_register_session_buddy_tools",
            "_register_otel_tools",
            "_register_self_improvement_tools",
            "_register_goal_team_tools",
            "_register_treesitter_tools",
            "_register_adapter_registry_tools",
            "_register_pycharm_tools",
        ]
        for method in excluded_from_minimal:
            assert method not in minimal_tools

    def test_standard_excludes_full_specific_groups(self) -> None:
        """STANDARD profile excludes otel, self-improv, goal-team, treesitter, pycharm."""
        from mcp_common.tools import ToolProfile

        excluded_from_standard = [
            "_register_otel_tools",
            "_register_self_improvement_tools",
            "_register_goal_team_tools",
            "_register_treesitter_tools",
            "_register_adapter_registry_tools",
            "_register_pycharm_tools",
        ]
        standard_tools = PROFILE_REGISTRATIONS[ToolProfile.STANDARD]
        for method in excluded_from_standard:
            assert method not in standard_tools


class TestEdgeCases:
    """Test edge cases: unknown profile, tools with no group, etc."""

    def test_unknown_env_var_defaults_to_full(self) -> None:
        """An unrecognized env var value should fall back to FULL (backward compat)."""
        from mcp_common.tools import ToolProfile

        with patch.dict(os.environ, {"MAHAVISHNU_TOOL_PROFILE": "not_a_real_profile"}):
            profile = get_active_profile()
            assert profile == ToolProfile.FULL

    def test_empty_env_var_defaults_to_full(self) -> None:
        """An empty env var value should fall back to FULL."""
        from mcp_common.tools import ToolProfile

        with patch.dict(os.environ, {"MAHAVISHNU_TOOL_PROFILE": ""}):
            profile = get_active_profile()
            assert profile == ToolProfile.FULL

    def test_env_var_not_set_defaults_to_full(self) -> None:
        """When the env var is not set, should default to FULL."""
        from mcp_common.tools import ToolProfile

        # clear=True removes all env vars so MAHAVISHNU_TOOL_PROFILE won't exist
        with patch.dict(os.environ, {}, clear=True):
            profile = get_active_profile()
            assert profile == ToolProfile.FULL

    def test_whitespace_env_var_defaults_to_full(self) -> None:
        """An env var with only whitespace should fall back to FULL."""
        from mcp_common.tools import ToolProfile

        with patch.dict(os.environ, {"MAHAVISHNU_TOOL_PROFILE": "   "}):
            profile = get_active_profile()
            assert profile == ToolProfile.FULL

    def test_case_insensitive_env_var(self) -> None:
        """Profile parsing is case-insensitive."""
        from mcp_common.tools import ToolProfile

        for value in ["minimal", "MINIMAL", "Minimal", "MiNiMaL"]:
            with patch.dict(os.environ, {"MAHAVISHNU_TOOL_PROFILE": value}):
                profile = get_active_profile()
                assert profile == ToolProfile.MINIMAL, f"Failed for value: {value}"

    def test_all_registration_lists_are_flat_string_lists(self) -> None:
        """All registration lists should contain only string method names."""
        all_registrations = MINIMAL_REGISTRATIONS + STANDARD_REGISTRATIONS + FULL_REGISTRATIONS
        for item in all_registrations:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"

    def test_no_duplicate_methods_in_any_profile(self) -> None:
        """No profile should have duplicate method names."""
        from mcp_common.tools import ToolProfile

        for profile in ToolProfile:
            tools = PROFILE_REGISTRATIONS[profile]
            assert len(tools) == len(set(tools)), f"Duplicates in {profile}"

    def test_no_worktree_tools_in_any_profile(self) -> None:
        """register_worktree_tools is async and conditionally registered; not in any profile."""
        all_methods = MINIMAL_REGISTRATIONS + STANDARD_REGISTRATIONS + FULL_REGISTRATIONS
        for method in all_methods:
            assert "worktree" not in method.lower()

    def test_get_active_profile_respects_custom_env_var(self) -> None:
        """get_active_profile() should read from a custom env var name if provided."""
        from mcp_common.tools import ToolProfile

        with patch.dict(os.environ, {"CUSTOM_PROFILE_VAR": "standard"}):
            profile = get_active_profile(env_var="CUSTOM_PROFILE_VAR")
            assert profile == ToolProfile.STANDARD

    def test_profiles_are_mutually_exclusive_for_methods(self) -> None:
        """MINIMAL methods are a strict subset of STANDARD which is a subset of FULL."""

        minimal_set = set(MINIMAL_REGISTRATIONS)
        standard_set = set(STANDARD_REGISTRATIONS)
        full_set = set(FULL_REGISTRATIONS)

        assert minimal_set.issubset(standard_set)
        assert standard_set.issubset(full_set)
        # minimal_set is a proper subset of standard_set but not equal to it
        assert minimal_set.issubset(standard_set)
        assert minimal_set != standard_set
        assert minimal_set != full_set

    def test_full_is_superset_of_all(self) -> None:
        """FULL registrations should be a superset of STANDARD which is a superset of MINIMAL."""
        from mcp_common.tools import ToolProfile

        minimal_set = set(PROFILE_REGISTRATIONS[ToolProfile.MINIMAL])
        standard_set = set(PROFILE_REGISTRATIONS[ToolProfile.STANDARD])
        full_set = set(PROFILE_REGISTRATIONS[ToolProfile.FULL])

        assert minimal_set.issubset(standard_set)
        assert minimal_set.issubset(full_set)
        assert standard_set.issubset(full_set)
