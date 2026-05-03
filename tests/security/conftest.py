"""Pytest configuration and fixtures for security tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db() -> MagicMock:
    """Create a mock database connection."""
    db = MagicMock()
    db.fetch_one = AsyncMock(return_value=None)
    db.fetch_all = AsyncMock(return_value=[])
    db.execute = AsyncMock(return_value="INSERT 0 1")
    return db


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {}
    return request
