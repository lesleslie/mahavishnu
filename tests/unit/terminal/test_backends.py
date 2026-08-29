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
    def test_has_tmux(self) -> None:
        assert "tmux" in BUILTIN_BACKENDS

    def test_tmux_backend_shape(self) -> None:
        backend = BUILTIN_BACKENDS["tmux"]
        assert backend.command == "tmux"
        assert backend.args == ()
        assert "tmux" in backend.requires

    def test_only_tmux_backend_registered(self) -> None:
        # Only the tmux PTY backend is registered. If you add a new entry
        # here, also update docs/terminal/backends.md and add a
        # backends-specific test for it.
        assert list(BUILTIN_BACKENDS) == ["tmux"]

    def test_all_backends_have_command_args_name(self) -> None:
        # Defensive: every registered backend must be launchable. The
        # `command` field is the spawn target and must be non-empty; the
        # `args` field may be empty when `command` alone is the full
        # invocation (e.g., `tmux` with no subcommand opens the default
        # session). The `PtyBackend` dataclass already enforces `args` to
        # be a tuple, so a tuple of any length (including 0) is valid.
        for name, backend in BUILTIN_BACKENDS.items():
            assert backend.name == name
            assert backend.command, f"backend {name!r} has empty command"
            assert isinstance(backend.args, tuple), (
                f"backend {name!r} has non-tuple args: {backend.args!r}"
            )


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
