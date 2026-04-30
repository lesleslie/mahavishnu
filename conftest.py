"""Test-wide compatibility fixtures."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def ensure_default_event_loop() -> None:
    """Provide a default loop for sync tests that still call get_event_loop()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield
