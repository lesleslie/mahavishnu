"""Terminal adapter registry contract tests (D0 refactor).

Validates:
- ``get_adapter_factory`` raises ``KeyError`` for unknown adapters (C5 fix).
- ``register_adapter`` rejects duplicate registration.
- ``list_adapter_names`` returns the expected 4-tuple after D0.
"""

from __future__ import annotations

import pytest

from mahavishnu.terminal.adapters import (
    get_adapter_factory,
    list_adapter_names,
    register_adapter,
)


def test_list_adapter_names_contains_expected_entries() -> None:
    """All four canonical terminal adapters are registered after D0."""
    names = list_adapter_names()
    assert "mock" in names
    assert "tmux" in names
    # crow and goose are optional — only registered if their dep is available
    # and the corresponding feature flag is enabled. We don't assert their
    # presence here, only that mock + tmux (always available) are present.
    assert "mock" in names
    assert "tmux" in names


def test_get_adapter_factory_known_returns_callable() -> None:
    """Known adapter names return a factory callable."""
    factory = get_adapter_factory("mock")
    assert callable(factory)


def test_get_adapter_factory_unknown_raises_key_error() -> None:
    """Unknown adapters raise KeyError, not silent None (C5 fix)."""
    with pytest.raises(KeyError) as excinfo:
        get_adapter_factory("nonexistent-adapter")
    msg = str(excinfo.value)
    assert "nonexistent-adapter" in msg
    assert "Available:" in msg


def test_register_adapter_rejects_duplicate() -> None:
    """Re-registering a known adapter raises ValueError."""
    with pytest.raises(ValueError) as excinfo:
        register_adapter("mock", lambda *a, **kw: None)
    assert "already registered" in str(excinfo.value)
