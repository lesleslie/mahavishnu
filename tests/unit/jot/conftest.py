"""Shared pytest fixtures for jot inbox tests.

This conftest.py is auto-loaded by pytest for every test in tests/unit/jot/
and tests/integration/jot/ (and property tests via parent conftest.py
inheritance). It ensures module-level caches and lazy-init globals in
mahavishnu.jot.* don't leak between tests.
"""
from __future__ import annotations

import pytest

from mahavishnu.jot import hlc as hlc_module
from mahavishnu.jot import paths as paths_module


@pytest.fixture(autouse=True)
def _reset_module_caches() -> None:
    """Reset module-level caches before each test.

    Without this, _jot_dir_cache (paths.py) and _node (hlc.py) leak between
    tests, causing monkeypatch.setattr(Path, "home", ...) to be silently
    ignored after the first call to jot_dir() / get_node().
    """
    paths_module._jot_dir_cache = None
    hlc_module._node = None
