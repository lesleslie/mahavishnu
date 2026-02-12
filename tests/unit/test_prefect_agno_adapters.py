"""Tests for Prefect and Agno adapters."""

import pytest
from unittest.mock import AsyncMock, patch

from mahavishnu.adapters.workflow.prefect_adapter import PrefectAdapter
from mahavishnu.adapters.ai.agno_adapter import AgnoAdapter
from mahavishnu.core.adapters.base import (
    OrchestratorAdapter,
    AdapterType,
    AdapterCapabilities,
)


@pytest.mark.asyncio
async def test_prefect_adapter_initialization():
    """Test Prefect adapter initialization."""
    adapter = PrefectAdapter(api_url="http://localhost:4200")

    assert adapter.adapter_type.value == "prefect"
    assert adapter.name == "prefect"
    assert adapter.capabilities.can_deploy_flows is True
    assert adapter.capabilities.has_cloud_ui is True


@pytest.mark.asyncio
async def test_prefect_adapter_initialize_success():
    """Test successful Prefect adapter initialization."""
    adapter = PrefectAdapter(api_url="http://localhost:4200")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = Mock(status_code=200)

        await adapter.initialize()

        assert adapter._client is not None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prefect_adapter_initialize_connection_failure():
    """Test Prefect adapter initialization failure."""
    adapter = PrefectAdapter(api_url="http://invalid:9999")

    with pytest.raises(AdapterInitializationError):
        await adapter.initialize()


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
        mock_get.return_value = Mock(status_code=200)

        await adapter.initialize()

        assert adapter._client is not None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_agno_adapter_initialize_connection_failure():
    """Test Agno adapter initialization failure."""
    adapter = AgnoAdapter(api_url="http://invalid:9999")

    with pytest.raises(AdapterInitializationError):
        await adapter.initialize()


@pytest.mark.asyncio
async def test_prefect_deploy_workflow_from_file():
    """Test deploying Prefect workflow from Python file."""
    adapter = PrefectAdapter(api_url="http://localhost:4200")
    await adapter.initialize()

    flow_code = """
from prefect import flow, task

@flow
def hello_flow():
    @task
    def say_hello():
        return "Hello from Prefect!"

    return hello_flow()
"""

    with patch("builtins.open", mock_open=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = flow_code

        execution_id = await adapter.deploy_workflow_from_file(
            file_path="workflow.py",
            workflow_name="test_workflow",
        )

        assert execution_id is not None
        assert len(execution_id) == 26  # ULID format


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
        mock_post.return_value = Mock(
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
        mock_post.return_value = Mock(
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
        mock_post.return_value = Mock(
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
        assert all(eid.startswith("01") for eid in results.values())  # ULID format


@pytest.mark.asyncio
async def test_adapter_shutdown():
    """Test adapter shutdown."""
    adapter = PrefectAdapter(api_url="http://localhost:4200")
    await adapter.initialize()

    with patch("httpx.AsyncClient.aclose") as mock_close:
        await adapter.shutdown()

        assert adapter._client is None
        mock_close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
