"""Pool registry contract tests (D0 refactor).

Validates:
- ``get_pool_factory`` raises ``KeyError`` for unknown pool types (C5 fix).
- ``register_pool_type`` rejects duplicate registration.
- ``canonicalize_pool_type`` translates underscore to hyphen form.
- ``list_pool_types`` returns the expected 4-tuple after D0 refactor.
"""

from __future__ import annotations

import pytest

from mahavishnu.pools._registry import (
    canonicalize_pool_type,
    get_pool_factory,
    list_pool_types,
    register_pool_type,
)


def test_list_pool_types_contains_expected_entries() -> None:
    """All four canonical pool types are registered after D0."""
    types = list_pool_types()
    assert "mahavishnu" in types
    assert "pi" in types
    assert "runpod" in types
    assert "session-buddy" in types
    assert len(types) == 4


def test_get_pool_factory_known_returns_callable() -> None:
    """Known pool names return a factory callable."""
    factory = get_pool_factory("mahavishnu")
    assert callable(factory)


def test_get_pool_factory_unknown_raises_key_error() -> None:
    """Unknown pool types raise KeyError, not silent None (C5 fix)."""
    with pytest.raises(KeyError) as excinfo:
        get_pool_factory("nonexistent-pool")
    msg = str(excinfo.value)
    assert "nonexistent-pool" in msg
    assert "Available:" in msg


def test_register_pool_type_rejects_duplicate() -> None:
    """Re-registering a known type raises ValueError."""
    # `mahavishnu` is registered at module load; a duplicate must raise.
    with pytest.raises(ValueError) as excinfo:
        register_pool_type("mahavishnu", lambda *a, **kw: None)
    assert "already registered" in str(excinfo.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("session_buddy", "session-buddy"),
        ("session-buddy", "session-buddy"),
        ("mahavishnu", "mahavishnu"),
        ("runpod", "runpod"),
        ("pi", "pi"),
    ],
)
def test_canonicalize_pool_type_translates_underscore(raw: str, expected: str) -> None:
    """Underscore-form input is normalized to canonical hyphen-form."""
    assert canonicalize_pool_type(raw) == expected
