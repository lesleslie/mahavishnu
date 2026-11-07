"""Contract tests for the eval extension-point registry (REQ-EVAL-001).

Validates:

- each ``discover_*`` call returns a ``name -> callable`` mapping;
- the built-in table and the ``pyproject.toml`` entry-point groups declare
  the same extension points (drift guard);
- the discovery cache serves a hit inside the TTL and re-discovers after it;
- an installed entry point overrides a built-in of the same name.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from freezegun import freeze_time
import pytest

from mahavishnu.core.eval import _registry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> Iterator[None]:
    """Keep the discovery cache from leaking between tests."""
    _registry._cache.clear()
    yield
    _registry._cache.clear()


@pytest.mark.req(["REQ-EVAL-001"])
@pytest.mark.parametrize(
    "discover",
    [
        _registry.discover_scorers,
        _registry.discover_dataset_loaders,
        _registry.discover_storage,
        _registry.discover_model_backends,
    ],
)
def test_discover_returns_name_to_callable_mapping(
    discover: Callable[[], dict[str, Callable[..., Any]]],
) -> None:
    """Each discover_* call returns a mapping whose values are callable."""
    found = discover()
    assert isinstance(found, dict)
    assert all(callable(target) for target in found.values())


@pytest.mark.req(["REQ-EVAL-001"])
def test_builtin_table_matches_pyproject_entry_points() -> None:
    """The built-in table and the pyproject groups declare the same entries.

    The two are separate sources by design — the built-in table is the
    install-independent runtime source, the pyproject groups are what an
    installed distribution advertises — so this test is the drift guard
    that keeps them in agreement.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    declared = {
        group: dict(entries)
        for group, entries in pyproject["project"]["entry-points"].items()
        if group.startswith("mahavishnu.eval.")
    }
    builtins = {group: dict(targets) for group, targets in _registry._BUILTINS.items()}
    assert declared == builtins


@pytest.mark.req(["REQ-EVAL-001"])
def test_resolve_imports_the_named_attribute() -> None:
    """A ``"module:attr"`` target resolves to the attribute it names."""
    resolved = _registry._resolve("mahavishnu.core.eval._registry:SCORERS_GROUP")
    assert resolved == "mahavishnu.eval.scorers"


@pytest.mark.req(["REQ-EVAL-001"])
def test_cache_hit_serves_the_same_mapping() -> None:
    """A second call inside the TTL returns the cached mapping."""
    first = _registry.discover_scorers()
    second = _registry.discover_scorers()
    assert first is second


@pytest.mark.req(["REQ-EVAL-001"])
def test_cache_expires_after_the_ttl() -> None:
    """A call after the TTL re-discovers instead of serving the cache."""
    with freeze_time("2026-11-06 00:00:00"):
        first = _registry.discover_scorers()
    with freeze_time("2026-11-06 00:10:00"):
        second = _registry.discover_scorers()
    assert first is not second


@pytest.mark.req(["REQ-EVAL-001"])
def test_entry_point_overrides_a_builtin_of_the_same_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An installed entry point replaces a built-in sharing its name."""

    class _FakeEntryPoint:
        name = "mahavishnu.fake"

        @staticmethod
        def load() -> Callable[[], str]:
            return lambda: "from-entry-point"

    monkeypatch.setattr(
        _registry, "iter_entry_points", lambda group: [_FakeEntryPoint()]
    )
    monkeypatch.setitem(
        _registry._BUILTINS[_registry.SCORERS_GROUP], "mahavishnu.fake", "json:loads"
    )

    found = _registry.discover_scorers()
    assert found["mahavishnu.fake"]() == "from-entry-point"


@pytest.mark.req(["REQ-EVAL-001"])
def test_package_reexports_resolve_lazily() -> None:
    """``mahavishnu.core.eval`` exposes the discover_* names via lazy import."""
    from mahavishnu.core import eval as eval_package

    assert callable(eval_package.discover_scorers)
    with pytest.raises(AttributeError):
        _ = eval_package.no_such_attribute
