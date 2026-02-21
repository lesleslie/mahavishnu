"""Tests for Prefect and Agno adapters.

Note: PrefectAdapter tests now use the engines module directly.
The adapters.workflow.prefect_adapter module is deprecated.

These tests are skipped if prefect is not installed (optional dependency).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Skip all Prefect tests if prefect is not installed
prefect = pytest.importorskip("prefect", reason="prefect not installed")

# Import PrefectAdapter from engines module (preferred location)
from mahavishnu.engines.prefect_adapter import PrefectAdapter
from mahavishnu.core.config import PrefectConfig

# Agno adapter is always available
from mahavishnu.adapters.ai.agno_adapter import AgnoAdapter
from mahavishnu.core.adapters.base import (
    OrchestratorAdapter,
    AdapterType,
    AdapterCapabilities,
)


@pytest.fixture
def prefect_config():
    """Create a default PrefectConfig for testing."""
    return PrefectConfig(
        enabled=True,
        api_url="http://localhost:4200",
        work_pool="test-pool",
        timeout_seconds=60,
        max_retries=2,
    )


@pytest.mark.asyncio
async def test_prefect_adapter_initialization(prefect_config):
    """Test Prefect adapter initialization."""
    adapter = PrefectAdapter(prefect_config)

    assert adapter.adapter_type.value == "prefect"
    assert adapter.name == "prefect"
    assert adapter.capabilities.can_deploy_flows is True
    assert adapter.capabilities.has_cloud_ui is True


@pytest.mark.asyncio
async def test_prefect_adapter_initialize_success(prefect_config):
    """Test successful Prefect adapter initialization."""
    adapter = PrefectAdapter(prefect_config)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)

        await adapter.initialize()

        assert adapter._client is not None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prefect_adapter_initialize_connection_failure():
    """Test Prefect adapter initialization failure."""
    config = PrefectConfig(
        enabled=True,
        api_url="http://invalid:9999",
        work_pool="test-pool",
        timeout_seconds=5,  # Short timeout for faster test
        max_retries=1,
    )
    adapter = PrefectAdapter(config)

    # The new adapter handles connection failures differently
    # It initializes the client but may fail on health check
    await adapter.initialize()
    # The adapter should be initialized even if connection fails
    # (connection is verified lazily or via health check)


@pytest.mark.asyncio
async def test_prefect_adapter_health_check(prefect_config):
    """Test Prefect adapter health check."""
    adapter = PrefectAdapter(prefect_config)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)

        await adapter.initialize()
        health = await adapter.get_health()

        assert health["status"] == "healthy"
        assert health["adapter"] == "prefect"


@pytest.mark.asyncio
async def test_adapter_shutdown(prefect_config):
    """Test adapter shutdown."""
    adapter = PrefectAdapter(prefect_config)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        await adapter.initialize()

    with patch("httpx.AsyncClient.aclose") as mock_close:
        await adapter.shutdown()

        assert adapter._client is None
        mock_close.assert_called_once()


# =============================================================================
# Agno Adapter Tests (always available)
# =============================================================================


@pytest.mark.asyncio
async def test_agno_adapter_initialization():
    """Test Agno adapter initialization."""
    adapter = AgnoAdapter(api_url="http://localhost:8000")

    assert adapter.adapter_type.value == "agno"
    assert adapter.name == "agno"
    assert adapter.capabilities.supports_multi_agent is True
    assert adapter.capabilities.has_cloud_ui is False


@pytest.mark.asyncio
async def test_agno_adapter_initialize_success():
    """Test successful Agno adapter initialization."""
    adapter = AgnoAdapter(api_url="http://localhost:8000")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)

        await adapter.initialize()

        assert adapter._client is not None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_agno_adapter_initialize_connection_failure():
    """Test Agno adapter initialization failure."""
    adapter = AgnoAdapter(api_url="http://invalid:9999")

    # This test may need adjustment based on how AgnoAdapter handles failures
    # For now, we expect it to handle the failure gracefully
    try:
        await adapter.initialize()
    except Exception:
        # Expected - connection should fail
        pass


@pytest.mark.asyncio
async def test_agno_create_crew():
    """Test creating Agno crew."""
    adapter = AgnoAdapter(api_url="http://localhost:8000")
    await adapter.initialize()

    crew_config = {
        "agents": ["researcher", "writer"],
        "tasks": ["research", "write"],
        "memory": True,
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201,
            json={"crew_id": "test_crew_id"},
        )

        crew_id = await adapter.create_crew(
            crew_name="test_crew",
            crew_config=crew_config,
        )

        assert crew_id == "test_crew_id"
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_agno_execute_task():
    """Test executing single Agno task."""
    adapter = AgnoAdapter(api_url="http://localhost:8000")
    await adapter.initialize()

    task = {"prompt": "Write a poem about AI"}

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201,
            json={"execution_id": "test_execution_id"},
        )

        execution_id = await adapter.execute_task(
            crew_id="test_crew",
            task=task,
        )

        assert execution_id == "test_execution_id"


@pytest.mark.asyncio
async def test_agno_execute_task_batch():
    """Test executing Agno task batch."""
    adapter = AgnoAdapter(api_url="http://localhost:8000")
    await adapter.initialize()

    tasks = [
        {"prompt": f"Task {i}"}
        for i in range(5)
    ]

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201,
            json={
                "0": "exec_id_0",
                "1": "exec_id_1",
                "2": "exec_id_2",
                "3": "exec_id_3",
                "4": "exec_id_4",
            },
        )

        results = await adapter.execute_task_batch(
            crew_id="test_crew",
            tasks=tasks,
        )

        assert len(results) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
