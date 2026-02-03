"""Pytest configuration for unit tests.

This file automatically marks all tests in tests/unit/ as unit tests,
allowing the production readiness checker to run only unit tests with the
`-m unit` flag.
"""

import pytest


def pytest_collection_modifyitems(items, config):
    """Automatically mark all tests in tests/unit/ as unit tests."""
    for item in items:
        # Mark tests in tests/unit/ directory as unit tests
        if "/tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        # Mark tests in tests/integration/ directory as integration tests
        elif "/tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        # Mark tests in tests/property/ directory as property tests
        elif "/tests/property/" in str(item.fspath):
            item.add_marker(pytest.mark.property)
