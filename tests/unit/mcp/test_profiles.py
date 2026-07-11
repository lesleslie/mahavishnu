"""Unit tests for mahavishnu.mcp.tools.profiles.

Covers the public surface of the tool-profile registry:
    - MINIMAL_REGISTRATIONS / STANDARD_REGISTRATIONS / FULL_REGISTRATIONS constants
    - PROFILE_REGISTRATIONS dispatch table
    - get_active_profile() helper (env var resolution)

Style mirrors tests/unit/mcp/test_openhands_tools.py -- function-based
tests with the ``@pytest.mark.unit`` decorator. Uses ``monkeypatch``
for env-var mutation; no async surface in the SUT.
"""

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
# Constants: MINIMAL_REGISTRATIONS
# =============================================================================


def test_minimal_registrations_only_health() -> None:
    """MINIMAL profile should only register the health-tool group."""
    assert MINIMAL_REGISTRATIONS == ["_register_health_tools"]


def test_minimal_registrations_contains_strings_with_register_prefix() -> None:
    """Every entry must be a ``_register_*`` method name (string)."""
    for entry in MINIMAL_REGISTRATIONS:
        assert isinstance(entry, str)
        assert entry.startswith("_register_")


# =============================================================================
# Constants: STANDARD_REGISTRATIONS
# =============================================================================


def test_standard_is_superset_of_minimal() -> None:
    """STANDARD must contain every entry that MINIMAL registers."""
    for entry in MINIMAL_REGISTRATIONS:
        assert entry in STANDARD_REGISTRATIONS


def test_standard_includes_core_tool_groups() -> None:
    """STANDARD must register the core operational tool groups."""
    expected_groups = {
        "_register_terminal_tools",
        "_register_pool_tools",
        "_register_worker_tools",
        "_register_repository_messaging_tools",
        "_register_git_analytics_tools",
        "_register_session_buddy_tools",
        "_register_openhands_tools",
        "_register_primitive_tools",
    }
    assert expected_groups.issubset(set(STANDARD_REGISTRATIONS))


def test_standard_registrations_no_otel_or_self_improvement() -> None:
    """STANDARD must NOT register OTel or self-improvement groups."""
    assert "_register_otel_tools" not in STANDARD_REGISTRATIONS
    assert "_register_self_improvement_tools" not in STANDARD_REGISTRATIONS


# =============================================================================
# Constants: FULL_REGISTRATIONS
# =============================================================================


def test_full_is_superset_of_standard() -> None:
    """FULL must contain every entry that STANDARD registers."""
    for entry in STANDARD_REGISTRATIONS:
        assert entry in FULL_REGISTRATIONS


def test_full_includes_feature_specific_tool_groups() -> None:
    """FULL must register all feature-specific tool groups."""
    expected_groups = {
        "_register_otel_tools",
        "_register_self_improvement_tools",
        "_register_clone_tools",
        "_register_goal_team_tools",
        "_register_treesitter_tools",
        "_register_adapter_registry_tools",
        "_register_pycharm_tools",
    }
    assert expected_groups.issubset(set(FULL_REGISTRATIONS))


# =============================================================================
# Cross-cutting constant invariants
# =============================================================================


def test_worktree_tools_not_in_any_profile() -> None:
    """``_register_worktree_tools`` is gated by runtime state, not by profile."""
    assert "_register_worktree_tools" not in MINIMAL_REGISTRATIONS
    assert "_register_worktree_tools" not in STANDARD_REGISTRATIONS
    assert "_register_worktree_tools" not in FULL_REGISTRATIONS


def test_profile_sizes_strictly_increase() -> None:
    """MINIMAL < STANDARD < FULL (strict ordering)."""
    assert len(MINIMAL_REGISTRATIONS) < len(STANDARD_REGISTRATIONS)
    assert len(STANDARD_REGISTRATIONS) < len(FULL_REGISTRATIONS)


def test_profile_lists_are_unique() -> None:
    """No registration method appears twice within a single profile list."""
    for name, lst in (
        ("MINIMAL", MINIMAL_REGISTRATIONS),
        ("STANDARD", STANDARD_REGISTRATIONS),
        ("FULL", FULL_REGISTRATIONS),
    ):
        assert len(lst) == len(set(lst)), f"{name} has duplicate entries"


# =============================================================================
# PROFILE_REGISTRATIONS dispatch table
# =============================================================================


def test_profile_registrations_covers_all_profiles() -> None:
    """PROFILE_REGISTRATIONS must map every ToolProfile enum value."""
    for profile in ToolProfile:
        assert profile in PROFILE_REGISTRATIONS


def test_profile_registrations_values_are_lists() -> None:
    """Each mapped value must be a non-empty list of method names."""
    for profile, methods in PROFILE_REGISTRATIONS.items():
        assert isinstance(methods, list), f"{profile} should map to a list"
        assert methods, f"{profile} must register at least one method"
        for method in methods:
            assert isinstance(method, str)
            assert method.startswith("_register_")


def test_profile_registrations_keys_are_toolprofile_enum() -> None:
    """All keys of the dispatch table must be ToolProfile enum members."""
    for key in PROFILE_REGISTRATIONS:
        assert isinstance(key, ToolProfile)


def test_profile_registrations_minimal_identity() -> None:
    """MINIMAL mapping must reference the MINIMAL_REGISTRATIONS constant."""
    assert PROFILE_REGISTRATIONS[ToolProfile.MINIMAL] is MINIMAL_REGISTRATIONS


def test_profile_registrations_standard_identity() -> None:
    """STANDARD mapping must reference the STANDARD_REGISTRATIONS constant."""
    assert PROFILE_REGISTRATIONS[ToolProfile.STANDARD] is STANDARD_REGISTRATIONS


def test_profile_registrations_full_identity() -> None:
    """FULL mapping must reference the FULL_REGISTRATIONS constant."""
    assert PROFILE_REGISTRATIONS[ToolProfile.FULL] is FULL_REGISTRATIONS


# =============================================================================
# get_active_profile: env-var resolution
# =============================================================================


def test_default_full_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env var must fall back to FULL (backward compatibility)."""
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)
    assert get_active_profile() == ToolProfile.FULL


def test_default_full_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty-string env var must fall back to FULL."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "")
    assert get_active_profile() == ToolProfile.FULL


def test_minimal_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MAHAVISHNU_TOOL_PROFILE=minimal`` must resolve to MINIMAL."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "minimal")
    assert get_active_profile() == ToolProfile.MINIMAL


def test_standard_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MAHAVISHNU_TOOL_PROFILE=standard`` must resolve to STANDARD."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "standard")
    assert get_active_profile() == ToolProfile.STANDARD


def test_full_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MAHAVISHNU_TOOL_PROFILE=full`` must resolve to FULL."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
    assert get_active_profile() == ToolProfile.FULL


def test_unrecognized_value_falls_back_to_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrecognized env values must fall back to FULL."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "not-a-real-profile")
    assert get_active_profile() == ToolProfile.FULL


def test_custom_env_var_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env-var name parameter must be honored."""
    monkeypatch.setenv("MY_CUSTOM_PROFILE_VAR", "standard")
    # Ensure the default env var is not interfering.
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)
    assert (
        get_active_profile(env_var="MY_CUSTOM_PROFILE_VAR")
        == ToolProfile.STANDARD
    )


def test_custom_env_var_unset_falls_back_to_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset custom env var must fall back to FULL."""
    monkeypatch.delenv("MY_CUSTOM_PROFILE_VAR", raising=False)
    assert get_active_profile(env_var="MY_CUSTOM_PROFILE_VAR") == ToolProfile.FULL


def test_default_env_var_is_mahavishnu_tool_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default env-var name must be ``MAHAVISHNU_TOOL_PROFILE``."""
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)
    # Inspect the signature default rather than calling.
    import inspect

    sig = inspect.signature(get_active_profile)
    assert sig.parameters["env_var"].default == "MAHAVISHNU_TOOL_PROFILE"


def test_returns_toolprofile_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_active_profile`` must always return a ToolProfile enum member."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "standard")
    result = get_active_profile()
    assert isinstance(result, ToolProfile)


def test_env_isolation_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the env between calls must change the resolved profile."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "minimal")
    first = get_active_profile()
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
    second = get_active_profile()
    assert first == ToolProfile.MINIMAL
    assert second == ToolProfile.FULL


def test_get_active_profile_uses_clear_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """With os.environ cleared and the default env var unset, FULL is returned."""
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)
    with patch.dict(os.environ, {}, clear=True):
        assert get_active_profile() == ToolProfile.FULL
