"""Test-wide compatibility fixtures."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

# Make ``scripts/`` importable as a top-level package so tests can do
# ``import test_matrix`` (and similar) without the per-test
# ``sys.path.insert`` hack. This pins the location once at the repo
# root instead of duplicating the path-mutation in every test file.
_REPO_ROOT = Path(__file__).resolve().parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if _SCRIPTS_DIR.is_dir() and str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def ensure_default_event_loop() -> None:
    """Provide a default loop for sync tests that still call get_event_loop()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield
