"""Tests for the shared httpx2 client lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.mcp.crow import client as crow_client
from mahavishnu.mcp.crow.settings import CrowSettings


@pytest.fixture
def reset_http_client():
    """Ensure module-level singleton is clean before/after each test."""
    saved = crow_client._http_client
    crow_client._http_client = None
    try:
        yield
    finally:
        crow_client._http_client = saved


async def test_get_http_client_raises_before_init(reset_http_client):
    with pytest.raises(RuntimeError, match="not initialized"):
        crow_client.get_http_client()


async def test_init_creates_client_and_close_clears(reset_http_client, tmp_path):
    settings = CrowSettings(workspace_root=tmp_path)
    await crow_client.init_http_client(settings)
    assert crow_client._http_client is not None
    # follow_redirects must be False so manual redirect validation runs
    assert crow_client._http_client.follow_redirects is False
    await crow_client.close_http_client()
    assert crow_client._http_client is None


async def test_close_is_idempotent(reset_http_client, tmp_path):
    settings = CrowSettings(workspace_root=tmp_path)
    await crow_client.init_http_client(settings)
    await crow_client.close_http_client()
    # Second close must not raise
    await crow_client.close_http_client()
    assert crow_client._http_client is None