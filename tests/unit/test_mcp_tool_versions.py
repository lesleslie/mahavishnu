"""Unit tests for mahavishnu.mcp.tool_versions.

The module exposes:
- ``TOOL_VERSIONS`` — dict mapping tool name -> semver string
- ``DEPRECATED_TOOLS`` — dict mapping deprecated tool name -> replacement
- ``get_tool_version(name)``
- ``get_all_tool_versions()``
- ``get_tool_deprecation(name)``
- ``is_tool_deprecated(name)``
"""

from __future__ import annotations

import pytest

from mahavishnu.mcp.tool_versions import (
    DEPRECATED_TOOLS,
    TOOL_VERSIONS,
    get_all_tool_versions,
    get_tool_deprecation,
    get_tool_version,
    is_tool_deprecated,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Constants / Registry shape
# =============================================================================


class TestToolVersionsRegistry:
    """The TOOL_VERSIONS / DEPRECATED_TOOLS registries should be coherent."""

    def test_registry_is_non_empty_mapping(self):
        """The version registry should have many tools mapped."""
        assert isinstance(TOOL_VERSIONS, dict)
        assert len(TOOL_VERSIONS) > 50

    def test_all_values_are_semver_strings(self):
        """Every version value should look like a 3-part semver string."""
        for name, version in TOOL_VERSIONS.items():
            parts = version.split(".")
            assert len(parts) == 3, f"{name} has invalid version {version!r}"
            for p in parts:
                assert p.isdigit(), f"{name} version part {p!r} is not numeric"

    def test_known_tools_are_registered(self):
        """Several well-known tools should be present in the registry."""
        expected = {
            "list_repos",
            "trigger_workflow",
            "pool_spawn",
            "terminal_launch",
            "coord_create_issue",
            "treesitter_parse",
            "adapter_list",
        }
        missing = expected - set(TOOL_VERSIONS)
        assert not missing, f"Missing tools in registry: {missing}"

    def test_deprecated_registry_is_mapping(self):
        """DEPRECATED_TOOLS is a dict of name -> optional replacement string."""
        assert isinstance(DEPRECATED_TOOLS, dict)
        # Each value should be either a string (replacement) or None
        for _name, replacement in DEPRECATED_TOOLS.items():
            assert replacement is None or isinstance(replacement, str)


# =============================================================================
# get_tool_version
# =============================================================================


class TestGetToolVersion:
    """get_tool_version returns the semver string for a named tool."""

    def test_returns_version_for_known_tool(self):
        """A registered tool should return its semver string."""
        assert get_tool_version("list_repos") == "1.0.0"

    def test_returns_monitoring_dashboard_v2(self):
        """get_monitoring_dashboard was bumped to v2.0.0."""
        assert get_tool_version("get_monitoring_dashboard") == "2.0.0"

    def test_returns_none_for_unknown_tool(self):
        """An unknown tool name should return None, not raise."""
        assert get_tool_version("totally_made_up_tool") is None
        assert get_tool_version("") is None


# =============================================================================
# get_all_tool_versions
# =============================================================================


class TestGetAllToolVersions:
    """get_all_tool_versions returns a copy of the full registry."""

    def test_returns_a_copy(self):
        """Mutating the returned dict should not affect the module constant."""
        snapshot = get_all_tool_versions()
        assert isinstance(snapshot, dict)
        snapshot["__mutated__"] = "1.0.0"
        assert "__mutated__" not in TOOL_VERSIONS

    def test_contents_match_module_constant(self):
        """Returned dict should match the module-level constant."""
        assert get_all_tool_versions() == TOOL_VERSIONS


# =============================================================================
# Deprecation helpers
# =============================================================================


class TestToolDeprecation:
    """get_tool_deprecation / is_tool_deprecated work as expected."""

    def test_known_deprecated_tool_has_replacement(self):
        """health_check_service has health_check_all as a replacement."""
        assert get_tool_deprecation("health_check_service") == "health_check_all"

    def test_deprecated_code_intel_tools_listed(self):
        """Session-Buddy code-intel tools have replacement guidance."""
        for name in (
            "index_code_graph",
            "find_related_code",
            "index_documentation",
            "search_documentation",
        ):
            assert is_tool_deprecated(name), f"{name} should be marked deprecated"
            assert get_tool_deprecation(name) is not None

    def test_non_deprecated_tool_returns_none(self):
        """A tool that is not deprecated should return None from get_tool_deprecation."""
        assert get_tool_deprecation("list_repos") is None
        assert is_tool_deprecated("list_repos") is False

    def test_unknown_tool_is_not_deprecated(self):
        """Unknown tools should not be flagged as deprecated."""
        assert is_tool_deprecated("not_a_real_tool") is False
        assert get_tool_deprecation("not_a_real_tool") is None
