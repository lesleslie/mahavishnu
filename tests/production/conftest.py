"""Configuration for production WebSocket tests."""

from __future__ import annotations

import asyncio
import pytest


# pytest markers
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "production: marks tests as production tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (performance/load tests)"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Skip slow tests by default
def pytest_collection_modifyitems(config, items):
    """Modify test collection to skip slow tests by default."""
    if not config.getoption("--runslow", default=False):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests (performance/load tests)"
    )
