"""Tests for LlamaIndex adapter stub."""

import pytest
from unittest.mock import AsyncMock, patch

from mahavishnu.adapters.rag.llamaindex_adapter import LlamaIndexAdapter
from mahavishnu.core.adapters.base import (
    OrchestratorAdapter,
    AdapterType,
    AdapterCapabilities,
)
from mahavishnu.core.errors import WorkflowError


@pytest.mark.asyncio
async def test_llamaindex_adapter_initialization():
    """Test LlamaIndex adapter initialization."""
    adapter = LlamaIndexAdapter(api_url="http://localhost:11434")

    assert adapter.adapter_type.value == "llamaindex"
    assert adapter.name == "llamaindex"
    assert adapter.api_url == "http://localhost:11434"


@pytest.mark.asyncio
async def test_llamaindex_adapter_capabilities():
    """Test LlamaIndex adapter capabilities."""
    adapter = LlamaIndexAdapter()

    caps = adapter.capabilities
    assert caps.can_deploy_flows is True          # RAG pipelines
    assert caps.can_monitor_execution is True        # Query tracking
    assert caps.can_cancel_workflows is True         # Can cancel queries
    assert caps.supports_batch_execution is True   # Multiple queries
    assert caps.supports_multi_agent is False        # Single query engine
    assert caps.has_cloud_ui is False             # Local engine


@pytest.mark.asyncio
async def test_llamaindex_adapter_initialize_stub():
    """Test LlamaIndex adapter stub initialization (no-op)."""
    adapter = LlamaIndexAdapter()

    # Should not raise any errors in stub mode
    await adapter.initialize()

    # Stub doesn't create a client
    assert adapter._client is None  # type: ignore


@pytest.mark.asyncio
async def test_llamaindex_adapter_execute_query_stub():
    """Test LlamaIndex execute() stub behavior."""
    adapter = LlamaIndexAdapter()
    await adapter.initialize()

    task = {
        "type": "query",
        "params": {"query": "test query"},
    }
    repos = ["/path/to/repo"]

    result = await adapter.execute(task, repos)

    assert result["status"] == "completed"
    assert "execution_id" in result["result"]
    assert len(result["result"]["execution_id"]) == 26  # ULID format
    assert result["result"]["task"] == task
    assert result["result"]["repos_processed"] == len(repos)


@pytest.mark.asyncio
async def test_llamaindex_adapter_execute_ingest_stub():
    """Test LlamaIndex execute() with ingest task."""
    adapter = LlamaIndexAdapter()
    await adapter.initialize()

    task = {
        "type": "ingest",
        "params": {"repo_path": "/test/repo"},
    }
    repos = ["/path/to/repo"]

    result = await adapter.execute(task, repos)

    assert result["status"] == "completed"
    assert "execution_id" in result["result"]
    assert "message" in result["result"]


@pytest.mark.asyncio
async def test_llamaindex_get_health_stub():
    """Test LlamaIndex get_health() stub behavior."""
    adapter = LlamaIndexAdapter(api_url="http://test:11434")
    await adapter.initialize()

    health = await adapter.get_health()

    assert health["status"] == "healthy"
    assert "details" in health
    assert health["details"]["implementation"] == "stub"
    assert health["details"]["api_url"] == "http://test:11434"
    assert "note" in health["details"]


@pytest.mark.asyncio
async def test_llamaindex_adapter_shutdown_stub():
    """Test LlamaIndex shutdown (no-op)."""
    adapter = LlamaIndexAdapter()

    # Should not raise any errors in stub mode
    await adapter.shutdown()

    # Stub is a no-op


@pytest.mark.asyncio
async def test_llamaindex_adapter_implements_interface():
    """Test that LlamaIndex adapter implements OrchestratorAdapter."""
    adapter = LlamaIndexAdapter()

    assert isinstance(adapter, OrchestratorAdapter)
    assert hasattr(adapter, "adapter_type")
    assert hasattr(adapter, "name")
    assert hasattr(adapter, "capabilities")
    assert hasattr(adapter, "execute")
    assert hasattr(adapter, "get_health")
    assert hasattr(adapter, "shutdown")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
