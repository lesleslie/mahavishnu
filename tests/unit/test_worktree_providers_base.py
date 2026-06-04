"""Unit tests for mahavishnu.core.worktree_providers.base.WorktreeProvider.

The base module defines an abstract interface: it has no I/O, no side
effects, and no state. These tests pin down:

- The class is genuinely abstract (cannot be instantiated directly).
- The 5 abstract methods are listed in ``__abstractmethods__``.
- A subclass that implements all 5 methods is concrete and usable.
- A subclass missing any single abstract method stays abstract and cannot
  be instantiated.
- Concrete subclasses can be used polymorphically through the base type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mahavishnu.core.worktree_providers.base import WorktreeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_provider(name: str = "test", healthy: bool = True) -> WorktreeProvider:
    """Build a minimal concrete subclass that implements every abstract method."""

    class _FullProvider(WorktreeProvider):
        async def create_worktree(
            self,
            repository_path: Path,
            branch: str,
            worktree_path: Path,
            create_branch: bool = False,
        ) -> dict[str, Any]:
            return {
                "success": True,
                "worktree_path": str(worktree_path),
                "branch": branch,
            }

        async def remove_worktree(
            self,
            repository_path: Path,
            worktree_path: Path,
            force: bool = False,
        ) -> dict[str, Any]:
            return {"success": True, "removed_path": str(worktree_path)}

        async def list_worktrees(self, repository_path: Path) -> dict[str, Any]:
            return {"success": True, "worktrees": []}

        def health_check(self) -> bool:
            return healthy

        def provider_name(self) -> str:
            return name

    return _FullProvider()


# ---------------------------------------------------------------------------
# Abstract class shape
# ---------------------------------------------------------------------------


def test_worktree_provider_cannot_be_instantiated_directly() -> None:
    """Base class has unimplemented abstract methods -> TypeError on call."""
    with pytest.raises(TypeError) as exc_info:
        WorktreeProvider()  # type: ignore[abstract]

    # The error message should mention the first missing abstract method
    assert "abstract" in str(exc_info.value).lower()


def test_worktree_provider_lists_all_five_abstract_methods() -> None:
    """The 5 abstract methods documented in the source must be marked abstract."""
    expected = {
        "create_worktree",
        "remove_worktree",
        "list_worktrees",
        "health_check",
        "provider_name",
    }
    assert set(WorktreeProvider.__abstractmethods__) == expected


def test_worktree_provider_inherits_from_abc() -> None:
    """WorktreeProvider must use abc.ABC, not just a metaclass=ABCMeta trick."""
    from abc import ABC

    assert issubclass(WorktreeProvider, ABC)


# ---------------------------------------------------------------------------
# Subclass coverage of abstract methods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_method",
    [
        "create_worktree",
        "remove_worktree",
        "list_worktrees",
        "health_check",
        "provider_name",
    ],
)
def test_subclass_missing_one_abstract_method_still_abstract(
    missing_method: str,
) -> None:
    """Omitting any single abstract method must keep the subclass abstract."""
    namespace: dict[str, Any] = {}

    if missing_method != "create_worktree":
        async def create_worktree(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        namespace["create_worktree"] = create_worktree

    if missing_method != "remove_worktree":
        async def remove_worktree(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        namespace["remove_worktree"] = remove_worktree

    if missing_method != "list_worktrees":
        async def list_worktrees(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        namespace["list_worktrees"] = list_worktrees

    if missing_method != "health_check":
        def health_check(self) -> bool:
            return True

        namespace["health_check"] = health_check

    if missing_method != "provider_name":
        def provider_name(self) -> str:
            return "partial"

        namespace["provider_name"] = provider_name

    Incomplete = type("IncompleteProvider", (WorktreeProvider,), namespace)

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Concrete subclass behavior
# ---------------------------------------------------------------------------


def test_concrete_subclass_is_instantiable() -> None:
    provider = _make_full_provider()
    assert isinstance(provider, WorktreeProvider)


async def test_concrete_subclass_create_worktree_returns_expected_shape() -> None:
    provider = _make_full_provider(name="acme")
    result = await provider.create_worktree(
        Path("/repo"),
        "main",
        Path("/wt/main"),
        create_branch=True,
    )

    assert result == {
        "success": True,
        "worktree_path": "/wt/main",
        "branch": "main",
    }


async def test_concrete_subclass_remove_worktree_returns_expected_shape() -> None:
    provider = _make_full_provider()
    result = await provider.remove_worktree(
        Path("/repo"),
        Path("/wt"),
        force=True,
    )
    assert result == {"success": True, "removed_path": "/wt"}


async def test_concrete_subclass_list_worktrees_returns_expected_shape() -> None:
    provider = _make_full_provider()
    result = await provider.list_worktrees(Path("/repo"))
    assert result == {"success": True, "worktrees": []}


def test_concrete_subclass_health_check_returns_configured_value() -> None:
    assert _make_full_provider(healthy=True).health_check() is True
    assert _make_full_provider(healthy=False).health_check() is False


def test_concrete_subclass_provider_name_returns_configured_name() -> None:
    assert _make_full_provider(name="session-buddy").provider_name() == "session-buddy"
    assert _make_full_provider(name="direct-git").provider_name() == "direct-git"
    assert _make_full_provider(name="mock").provider_name() == "mock"


# ---------------------------------------------------------------------------
# Polymorphism / duck-typing through the base type
# ---------------------------------------------------------------------------


async def test_concrete_provider_usable_through_base_type() -> None:
    """A list of WorktreeProvider references must dispatch to subclass impls."""
    providers: list[WorktreeProvider] = [
        _make_full_provider(name="a", healthy=True),
        _make_full_provider(name="b", healthy=False),
    ]

    names = [p.provider_name() for p in providers]
    healths = [p.health_check() for p in providers]

    assert names == ["a", "b"]
    assert healths == [True, False]

    for p in providers:
        result = await p.list_worktrees(Path("/repo"))
        assert result["success"] is True
