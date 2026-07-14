"""Unit tests for mahavishnu.terminal.backends."""
from __future__ import annotations

import dataclasses

import pytest

from mahavishnu.terminal.backends import (
    BUILTIN_BACKENDS,
    PtyBackend,
    check_prerequisites,
)


@pytest.mark.unit
class TestPtyBackend:
    def test_frozen_dataclass(self) -> None:
        # Frozen dataclasses raise FrozenInstanceError on attribute assignment.
        backend = PtyBackend(name="x", command="y", args=("z",))

        assert dataclasses.is_dataclass(backend)
        # Verify frozen by attempting mutation.
        with pytest.raises(dataclasses.FrozenInstanceError):
            backend.name = "mutated"  # type: ignore[misc]

    def test_default_tool_map_is_empty_dict(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        assert backend.tool_map == {}

    def test_default_requires_is_empty_tuple(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        assert backend.requires == ()

    def test_equality_supports_dict_keys(self) -> None:
        a = PtyBackend(name="x", command="y", args=("z",))
        b = PtyBackend(name="x", command="y", args=("z",))
        # Equal PtyBackends should hash identically (frozen dataclass + eq=True).
        assert hash(a) == hash(b)
        assert a == b


@pytest.mark.unit
class TestBuiltinBackends:
    def test_has_mcpretentious(self) -> None:
        assert "mcpretentious" in BUILTIN_BACKENDS

    def test_mcpretentious_uses_npx(self) -> None:
        # Regression: the original bug was using "uvx" for an npm package.
        # The fix is "npx" + the npm package name.
        backend = BUILTIN_BACKENDS["mcpretentious"]
        assert backend.command == "npx"
        assert backend.args == ("mcpretentious",)

    def test_mcpretentious_requires_node(self) -> None:
        # MCPretentious is an npm package, so it needs Node.js on PATH.
        assert "node" in BUILTIN_BACKENDS["mcpretentious"].requires

    def test_has_pty_mcp_python(self) -> None:
        # The second built-in backend, using uvx.
        assert "pty_mcp_python" in BUILTIN_BACKENDS

    def test_pty_mcp_python_uses_uvx(self) -> None:
        backend = BUILTIN_BACKENDS["pty_mcp_python"]
        assert backend.command == "uvx"
        # Verify it has the --from flag pointing at the package.
        assert "--from" in backend.args
        assert "luqm4nx-pty-mcp-server-python" in backend.args

    def test_all_backends_have_command_args_name(self) -> None:
        # Defensive: every registered backend must be launchable.
        for name, backend in BUILTIN_BACKENDS.items():
            assert backend.name == name
            assert backend.command, f"backend {name!r} has empty command"
            assert backend.args, f"backend {name!r} has empty args"


@pytest.mark.unit
class TestCheckPrerequisites:
    def test_empty_requires_returns_empty_list(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        assert check_prerequisites(backend) == []

    def test_missing_prereq_is_reported(self) -> None:
        # "definitely-not-a-real-binary-xyz" should never exist on PATH.
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("definitely-not-a-real-binary-xyz",),
        )
        result = check_prerequisites(backend)
        assert result == ["definitely-not-a-real-binary-xyz"]

    def test_present_prereq_is_not_reported(self) -> None:
        # "sh" is universally available on POSIX. On Windows this test would
        # need adjustment, but the spec is macOS/Linux only.
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("sh",),
        )
        assert check_prerequisites(backend) == []

    def test_partial_missing_reports_only_missing(self) -> None:
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("sh", "definitely-not-a-real-binary-xyz"),
        )
        result = check_prerequisites(backend)
        assert result == ["definitely-not-a-real-binary-xyz"]