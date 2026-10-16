"""Unit tests for mahavishnu.mcp.tools.learning_pipeline_tools.

The module exposes ``register_learning_tools`` which attaches five read-only
FastMCP tool functions. The tests capture those functions (via a stub
``mcp.tool()`` decorator) and exercise them with mocked pipeline_service,
evidence_store, and skill_registry dependencies.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.learning_pipeline_tools import register_learning_tools


class _StubMCP:
    """Minimal FastMCP stand-in that returns decorated functions unchanged."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _model(**fields) -> MagicMock:
    """Build a MagicMock whose ``model_dump(mode=...)`` returns ``fields``."""
    m = MagicMock()
    m.model_dump = MagicMock(return_value=fields)
    for k, v in fields.items():
        setattr(m, k, v)
    return m


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def pipeline_service() -> MagicMock:
    service = MagicMock()
    service.is_running = True
    service.cycle_count = 7
    service.total_drafts = 3
    service.last_result = _model(cycle=7, drafts_added=2, status="ok")
    service.run_once = AsyncMock(return_value=_model(cycle=8, drafts_added=1, status="ok"))
    return service


@pytest.fixture
def evidence_store() -> MagicMock:
    store = MagicMock()
    store.query_evidence = AsyncMock(
        return_value=[
            _model(id="e1", kind="pattern", text="hello"),
            _model(id="e2", kind="metric", text="world"),
        ]
    )
    return store


@pytest.fixture
def skill_registry() -> MagicMock:
    reg = MagicMock()
    reg.list_active = MagicMock(
        return_value=[
            SimpleNamespace(skill_id="skill-1", version="1.0.0", state="draft", body="body one"),
            SimpleNamespace(skill_id="skill-2", version="0.9.0", state="review", body=None),
        ]
    )
    reg.list_history = MagicMock(
        return_value=[
            SimpleNamespace(version="1.0.0", state="active", body="new body", rollback=None),
            SimpleNamespace(version="0.9.0", state="draft", body="older", rollback="old-snapshot"),
        ]
    )
    return reg


def test_register_attaches_all_five_tools(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    expected = {
        "get_pipeline_status",
        "list_evidence",
        "trigger_synthesis",
        "list_pending_drafts",
        "get_promotion_history",
    }
    assert set(stub_mcp.tools) == expected


def test_get_pipeline_status_without_service(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn())
    assert result == {
        "available": False,
        "error": "Learning pipeline service not initialized",
    }


def test_get_pipeline_status_with_service(stub_mcp: _StubMCP, pipeline_service: MagicMock) -> None:
    register_learning_tools(stub_mcp, pipeline_service=pipeline_service)
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn())
    assert result["available"] is True
    assert result["is_running"] is True
    assert result["cycle_count"] == 7
    assert result["total_drafts"] == 3
    # NOTE: source key is "last_cycle" (not "last_result"); pinned here.
    assert result["last_cycle"] == {
        "cycle": 7,
        "drafts_added": 2,
        "status": "ok",
    }


def test_get_pipeline_status_with_no_last_result(stub_mcp: _StubMCP) -> None:
    service = MagicMock()
    service.is_running = False
    service.cycle_count = 0
    service.total_drafts = 0
    service.last_result = None
    register_learning_tools(stub_mcp, pipeline_service=service)
    fn = stub_mcp.tools["get_pipeline_status"]
    import asyncio

    result = asyncio.run(fn())
    assert result["is_running"] is False
    assert result["last_cycle"] is None


def test_list_evidence_without_store(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(query="x"))
    assert result == {
        "available": False,
        "error": "Evidence store not initialized",
    }


def test_list_evidence_passes_query_and_limit(
    stub_mcp: _StubMCP, evidence_store: MagicMock
) -> None:
    register_learning_tools(stub_mcp, evidence_store=evidence_store)
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(query="hello", limit=5))
    evidence_store.query_evidence.assert_awaited_once_with("hello", 5)
    assert result["available"] is True
    assert result["count"] == 2
    assert result["evidence"] == [
        {"id": "e1", "kind": "pattern", "text": "hello"},
        {"id": "e2", "kind": "metric", "text": "world"},
    ]


def test_list_evidence_handles_query_error(stub_mcp: _StubMCP, evidence_store: MagicMock) -> None:
    evidence_store.query_evidence = AsyncMock(side_effect=RuntimeError("index down"))
    register_learning_tools(stub_mcp, evidence_store=evidence_store)
    fn = stub_mcp.tools["list_evidence"]
    import asyncio

    result = asyncio.run(fn(query="q"))
    assert result["available"] is True
    assert result["count"] == 0
    assert result["evidence"] == []
    assert result["error"] == "index down"


def test_trigger_synthesis_without_service(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn())
    assert result == {
        "available": False,
        "error": "Learning pipeline service not initialized",
    }


def test_trigger_synthesis_returns_cycle_result(
    stub_mcp: _StubMCP, pipeline_service: MagicMock
) -> None:
    register_learning_tools(stub_mcp, pipeline_service=pipeline_service)
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn())
    pipeline_service.run_once.assert_awaited_once()
    assert result["available"] is True
    assert result["cycle_result"] == {
        "cycle": 8,
        "drafts_added": 1,
        "status": "ok",
    }


def test_trigger_synthesis_handles_error(stub_mcp: _StubMCP, pipeline_service: MagicMock) -> None:
    pipeline_service.run_once = AsyncMock(side_effect=RuntimeError("boom"))
    register_learning_tools(stub_mcp, pipeline_service=pipeline_service)
    fn = stub_mcp.tools["trigger_synthesis"]
    import asyncio

    result = asyncio.run(fn())
    assert result["available"] is True
    assert result["error"] == "boom"


def test_list_pending_drafts_without_registry(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn())
    assert result == {
        "available": False,
        "error": "Skill registry not initialized",
    }


def test_list_pending_drafts_truncates_long_bodies(
    stub_mcp: _StubMCP, skill_registry: MagicMock
) -> None:
    long_body = "x" * 1000
    skill_registry.list_active = MagicMock(
        return_value=[
            SimpleNamespace(skill_id="s-long", version="1.0", state="draft", body=long_body),
        ]
    )
    register_learning_tools(stub_mcp, skill_registry=skill_registry)
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn())
    assert result["count"] == 1
    assert result["drafts"][0]["skill_id"] == "s-long"
    assert len(result["drafts"][0]["body"]) == 500


def test_list_pending_drafts_handles_none_body(
    stub_mcp: _StubMCP, skill_registry: MagicMock
) -> None:
    register_learning_tools(stub_mcp, skill_registry=skill_registry)
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn())
    assert result["count"] == 2
    assert result["drafts"][1]["body"] is None


def test_list_pending_drafts_handles_error(stub_mcp: _StubMCP, skill_registry: MagicMock) -> None:
    skill_registry.list_active = MagicMock(side_effect=RuntimeError("registry down"))
    register_learning_tools(stub_mcp, skill_registry=skill_registry)
    fn = stub_mcp.tools["list_pending_drafts"]
    import asyncio

    result = asyncio.run(fn())
    assert result["available"] is True
    assert result["error"] == "registry down"
    assert result["drafts"] == []


def test_get_promotion_history_without_registry(stub_mcp: _StubMCP) -> None:
    register_learning_tools(stub_mcp)
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(skill_id="x"))
    assert result == {
        "available": False,
        "error": "Skill registry not initialized",
    }


def test_get_promotion_history_returns_versions(
    stub_mcp: _StubMCP, skill_registry: MagicMock
) -> None:
    register_learning_tools(stub_mcp, skill_registry=skill_registry)
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(skill_id="skill-1"))
    skill_registry.list_history.assert_called_once_with("skill-1")
    assert result["available"] is True
    assert result["skill_id"] == "skill-1"
    assert result["count"] == 2
    assert result["history"][0]["version"] == "1.0.0"
    assert result["history"][0]["has_rollback"] is False
    assert result["history"][1]["has_rollback"] is True


def test_get_promotion_history_handles_error(stub_mcp: _StubMCP, skill_registry: MagicMock) -> None:
    skill_registry.list_history = MagicMock(side_effect=RuntimeError("db error"))
    register_learning_tools(stub_mcp, skill_registry=skill_registry)
    fn = stub_mcp.tools["get_promotion_history"]
    import asyncio

    result = asyncio.run(fn(skill_id="x"))
    assert result["available"] is True
    assert result["error"] == "db error"
    assert result["count"] == 0
    assert result["history"] == []
