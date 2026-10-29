"""Tests for Hatchet adapter — P10 implementation."""

from __future__ import annotations

import importlib

import pytest


def test_hatchet_sdk_importable():
    """hatchet-sdk must be listed as an optional dep and installed."""
    pytest.importorskip("hatchet_sdk")
    hatchet = importlib.import_module("hatchet_sdk")
    assert hatchet is not None


from mahavishnu.core.adapters.base import AdapterType


def test_adapter_type_hatchet_exists():
    assert AdapterType.HATCHET == "hatchet"


from mahavishnu.core.config import AdapterConfig, HatchetConfig


def test_adapter_config_has_hatchet_enabled():
    cfg = AdapterConfig()
    assert cfg.hatchet_enabled is False


def test_hatchet_config_defaults():
    cfg = HatchetConfig()
    assert cfg.server_url == "localhost:7077"
    assert cfg.namespace == "mahavishnu"
    assert cfg.max_runs == 10
    assert cfg.poll_interval_seconds == 2.0
    assert cfg.task_timeout_seconds == 300


from mahavishnu.core.model_routing import TaskCategory, classify_task


def test_task_category_agent_loop_exists():
    assert TaskCategory.AGENT_LOOP == "agent_loop"


def test_classify_task_agent_loop():
    prompt = "run an agent loop to autonomously complete this multi-step workflow"
    category = classify_task(prompt)
    assert category == TaskCategory.AGENT_LOOP


from unittest.mock import AsyncMock, MagicMock

from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl


@pytest.fixture()
def mock_hatchet_client():
    client = MagicMock()
    client.run = AsyncMock(
        return_value={"run_id": "run-001", "status": "SUCCEEDED", "output": "done"}
    )
    client.close = AsyncMock()
    client.rest = MagicMock()
    client.rest.workflow_list = AsyncMock(return_value=[])
    client.event = MagicMock()
    client.event.push = AsyncMock()
    return client


@pytest.fixture()
def hatchet_adapter():
    from mahavishnu.core.config import HatchetConfig

    cfg = HatchetConfig()
    inst = HatchetAdapterImpl(config=cfg)
    return inst


@pytest.mark.asyncio
async def test_hatchet_adapter_type(hatchet_adapter):
    assert hatchet_adapter.adapter_type == AdapterType.HATCHET


@pytest.mark.asyncio
async def test_hatchet_adapter_name(hatchet_adapter):
    assert hatchet_adapter.name == "hatchet"


@pytest.mark.asyncio
async def test_hatchet_execute_returns_output(hatchet_adapter, mock_hatchet_client):
    hatchet_adapter._client = mock_hatchet_client
    result = await hatchet_adapter.execute({"prompt": "run agent loop autonomously"}, repos=[])
    assert result["status"] == "completed"
    assert "output" in result


@pytest.mark.asyncio
async def test_hatchet_execute_no_prompt_returns_error(hatchet_adapter, mock_hatchet_client):
    hatchet_adapter._client = mock_hatchet_client
    result = await hatchet_adapter.execute({}, repos=[])
    assert result["status"] == "error"
    assert "prompt" in result["error"]


@pytest.mark.asyncio
async def test_hatchet_get_health_with_client(hatchet_adapter, mock_hatchet_client):
    hatchet_adapter._client = mock_hatchet_client
    health = await hatchet_adapter.get_health()
    assert health["status"] in ("healthy", "degraded", "unhealthy")


@pytest.mark.asyncio
async def test_hatchet_get_health_no_client(hatchet_adapter):
    hatchet_adapter._client = None
    health = await hatchet_adapter.get_health()
    assert health["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_hatchet_cleanup_closes_client(hatchet_adapter, mock_hatchet_client):
    hatchet_adapter._client = mock_hatchet_client
    await hatchet_adapter.cleanup()
    mock_hatchet_client.close.assert_awaited_once()
    assert hatchet_adapter._client is None


@pytest.mark.asyncio
async def test_hatchet_send_approval_event(hatchet_adapter, mock_hatchet_client):
    hatchet_adapter._client = mock_hatchet_client
    await hatchet_adapter.send_approval_event("run-001", approved=True)
    mock_hatchet_client.event.push.assert_awaited_once()


@pytest.mark.asyncio
async def test_hatchet_execute_timeout(hatchet_adapter, mock_hatchet_client):
    import asyncio as _asyncio

    async def slow_run(*args, **kwargs):
        await _asyncio.sleep(999)

    mock_hatchet_client.run = slow_run
    hatchet_adapter._client = mock_hatchet_client
    result = await hatchet_adapter.execute({"prompt": "run agent loop", "timeout": 0.01}, repos=[])
    assert result["status"] == "timeout"


def test_initialize_adapters_skips_hatchet_when_disabled():
    """When hatchet_enabled=False, no HatchetAdapterImpl is instantiated."""
    from unittest.mock import MagicMock

    from mahavishnu.core.app import MahavishnuApp

    app = MahavishnuApp.__new__(MahavishnuApp)
    app.adapters = {}
    app.config = MagicMock()
    app.config.adapters.prefect_enabled = False
    app.config.adapters.llamaindex_enabled = False
    app.config.adapters.agno_enabled = False
    app.config.adapters.hatchet_enabled = False
    app.config.workers.enabled = False

    app._initialize_adapters()

    assert "hatchet" not in app.adapters


# ============================================================================
# The run-result shape, and the embedded engine
# ============================================================================


def test_hatchet_config_use_embedded_defaults_to_false():
    """The embedded engine is opt-in, so a configured server still wins."""
    cfg = HatchetConfig()
    assert cfg.use_embedded is False


def test_hatchet_run_id_reads_the_nested_run_display_name():
    """``V1WorkflowRunDetails`` carries the id on ``.run.display_name``.

    The SDK's pydantic models expose snake_case field names even though
    the wire format is camelCase. Reading only ``run_id``/``id`` at the
    top level reported an empty run id for every dispatch.
    """
    from types import SimpleNamespace

    from mahavishnu.engines.hatchet_adapter_impl import _hatchet_run_id

    details = SimpleNamespace(run=SimpleNamespace(display_name="agent-loop-abc123"))

    assert _hatchet_run_id(details) == "agent-loop-abc123"


def test_hatchet_run_id_still_reads_the_flat_shape():
    from types import SimpleNamespace

    from mahavishnu.engines.hatchet_adapter_impl import _hatchet_run_id

    assert _hatchet_run_id(SimpleNamespace(run_id="flat-1")) == "flat-1"
    assert _hatchet_run_id({"run_id": "dict-1"}) == "dict-1"


def test_hatchet_run_output_reads_the_nested_run_output():
    from types import SimpleNamespace

    from mahavishnu.engines.hatchet_adapter_impl import _hatchet_run_output

    details = SimpleNamespace(run=SimpleNamespace(output={"text": "hi"}))

    assert _hatchet_run_output(details) == "{'text': 'hi'}"


def test_initialize_uses_the_embedded_engine_when_configured(monkeypatch):
    """``use_embedded`` selects the SDK's embedded engine.

    It needs neither Docker nor an API token, and issues its own
    address and token at startup.
    """
    from unittest.mock import MagicMock

    hatchet_sdk = pytest.importorskip("hatchet_sdk")

    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    calls: dict = {}

    def fake_from_embedded(config=None):
        calls["from_embedded"] = True
        return MagicMock()

    monkeypatch.setattr(hatchet_sdk.Hatchet, "from_embedded", staticmethod(fake_from_embedded))
    monkeypatch.delenv("HATCHET_CLIENT_TOKEN", raising=False)

    cfg = HatchetConfig(use_embedded=True)
    adapter = HatchetAdapterImpl(config=cfg)

    import asyncio

    asyncio.run(adapter.initialize())

    assert calls["from_embedded"] is True
    assert adapter.client is not None
