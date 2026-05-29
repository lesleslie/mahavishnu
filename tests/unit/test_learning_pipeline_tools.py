# tests/unit/test_learning_pipeline_tools.py
"""Unit tests for learning_pipeline_tools MCP module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from mahavishnu.mcp.tools import learning_pipeline_tools as lpt_module

# ---------------------------------------------------------------------------
# Fake pipeline / evidence / skill-registry components
# ---------------------------------------------------------------------------


# _FakePipelineService must be defined before _register references it.
@dataclass
class _FakePipelineResult:
    """Minimal fake for pipeline_service.last_result."""

    cycle_id: str = "cycle-42"
    drafts_evaluated: int = 3
    skills_promoted: int = 1
    model_dump_mode: str = "json"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "drafts_evaluated": self.drafts_evaluated,
            "skills_promoted": self.skills_promoted,
        }


class _FakePipelineService:
    is_running: bool = True
    cycle_count: int = 5
    total_drafts: int = 12
    last_result: _FakePipelineResult | None = _FakePipelineResult()

    async def run_once(self) -> _FakePipelineResult:
        return _FakePipelineResult(cycle_id="manual-trigger", drafts_evaluated=7, skills_promoted=2)


@dataclass
class _FakeEvidence:
    evidence_id: str = "ev-1"
    content: str = "evidence content"
    source: str = "test"
    model_dump_mode: str = "json"

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "content": self.content,
            "source": self.source,
        }


class _FakeEvidenceStore:
    def __init__(self, evidence: list[_FakeEvidence] | None = None) -> None:
        self._evidence = evidence or [_FakeEvidence(evidence_id="ev-1")]

    async def query_evidence(self, query: str, limit: int) -> list[_FakeEvidence]:
        return self._evidence[:limit]


@dataclass
class _FakeSkillRecord:
    skill_id: str
    version: str
    state: str
    body: str | None = "skill body content"
    rollback: Any = None


class _FakeSkillRegistry:
    def __init__(self, active: list[_FakeSkillRecord] | None = None) -> None:
        self._active = active or [
            _FakeSkillRecord(skill_id="skill-a", version="1.0", state="active"),
            _FakeSkillRecord(skill_id="skill-b", version="2.1", state="draft"),
        ]
        self._history: dict[str, list[_FakeSkillRecord]] = {
            "skill-a": [
                _FakeSkillRecord(skill_id="skill-a", version="1.0", state="active"),
                _FakeSkillRecord(
                    skill_id="skill-a", version="0.9", state="archived", rollback=True
                ),
            ],
        }

    def list_active(self) -> list[_FakeSkillRecord]:
        return self._active

    def list_history(self, skill_id: str) -> list[_FakeSkillRecord]:
        return self._history.get(skill_id, [])


# ---------------------------------------------------------------------------
# Fake FastMCP
# ---------------------------------------------------------------------------


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


async def _call_tool(tools: dict[str, Any], name: str, *args, **kwargs) -> Any:
    """Call a tool by name, awaiting the result if it is a coroutine."""
    result = tools[name](*args, **kwargs)
    if hasattr(result, "__await__"):
        return await result
    return result


# ---------------------------------------------------------------------------
# Helper: build a fake MCP + register with given services
# ---------------------------------------------------------------------------


def _register(pipeline=None, evidence=None, registry=None) -> dict[str, Any]:
    fake_mcp = _FakeMCP()
    lpt_module.register_learning_tools(fake_mcp, pipeline, evidence, registry)
    return fake_mcp.tools


# ---------------------------------------------------------------------------
# get_pipeline_status (sync wrapper around _pipeline_status)
# ---------------------------------------------------------------------------


def test_get_pipeline_status_available() -> None:
    """When pipeline_service is provided, status should show available=True."""
    tools = _register(pipeline=_FakePipelineService())
    result = asyncio.run(_call_tool(tools, "get_pipeline_status"))
    assert result["available"] is True
    assert result["is_running"] is True
    assert result["cycle_count"] == 5
    assert result["total_drafts"] == 12
    assert result["last_cycle"] is not None


def test_get_pipeline_status_not_available() -> None:
    """When pipeline_service is None, available should be False."""
    tools = _register(pipeline=None)
    result = asyncio.run(_call_tool(tools, "get_pipeline_status"))
    assert result["available"] is False
    assert "error" in result


def test_get_pipeline_status_not_running() -> None:
    """is_running=False should be reflected in status."""
    svc = _FakePipelineService()
    svc.is_running = False
    tools = _register(pipeline=svc)
    result = asyncio.run(_call_tool(tools, "get_pipeline_status"))
    assert result["available"] is True
    assert result["is_running"] is False


# ---------------------------------------------------------------------------
# list_evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_evidence_available() -> None:
    evidence_store = _FakeEvidenceStore(
        [
            _FakeEvidence(evidence_id="ev-1"),
            _FakeEvidence(evidence_id="ev-2"),
        ]
    )
    tools = _register(evidence=evidence_store)
    result = await tools["list_evidence"]("test query", limit=10)
    assert result["available"] is True
    assert result["count"] == 2
    assert len(result["evidence"]) == 2


@pytest.mark.asyncio
async def test_list_evidence_not_available() -> None:
    tools = _register(evidence=None)
    result = await tools["list_evidence"]("", limit=20)
    assert result["available"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_list_evidence_respects_limit() -> None:
    evidence_store = _FakeEvidenceStore([_FakeEvidence(evidence_id=f"ev-{i}") for i in range(5)])
    tools = _register(evidence=evidence_store)
    result = await tools["list_evidence"]("", limit=2)
    assert result["count"] == 2
    assert len(result["evidence"]) == 2


@pytest.mark.asyncio
async def test_list_evidence_handles_exception() -> None:
    class _BrokenStore:
        async def query_evidence(self, *args, **kwargs):
            raise RuntimeError("query failed")

    tools = _register(evidence=_BrokenStore())
    result = await tools["list_evidence"]("", limit=20)
    assert result["available"] is True  # still True (graceful handling)
    assert "error" in result
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# trigger_synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_synthesis_available() -> None:
    tools = _register(pipeline=_FakePipelineService())
    result = await tools["trigger_synthesis"]()
    assert result["available"] is True
    assert result["cycle_result"]["cycle_id"] == "manual-trigger"


@pytest.mark.asyncio
async def test_trigger_synthesis_not_available() -> None:
    tools = _register(pipeline=None)
    result = await tools["trigger_synthesis"]()
    assert result["available"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_trigger_synthesis_handles_exception() -> None:
    class _BrokenPipeline:
        async def run_once(self):
            raise RuntimeError("pipeline error")

    tools = _register(pipeline=_BrokenPipeline())
    result = await tools["trigger_synthesis"]()
    assert result["available"] is True
    assert "error" in result


# ---------------------------------------------------------------------------
# list_pending_drafts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_drafts_available() -> None:
    registry = _FakeSkillRegistry()
    tools = _register(registry=registry)
    result = await tools["list_pending_drafts"]()
    assert result["available"] is True
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_list_pending_drafts_not_available() -> None:
    tools = _register(registry=None)
    result = await tools["list_pending_drafts"]()
    assert result["available"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_list_pending_drafts_handles_exception() -> None:
    class _BrokenRegistry:
        def list_active(self):
            raise RuntimeError("registry error")

    tools = _register(registry=_BrokenRegistry())
    result = await tools["list_pending_drafts"]()
    assert result["available"] is True
    assert "error" in result
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_pending_drafts_body_truncated() -> None:
    """Body should be truncated to 500 chars."""
    long_body = "x" * 1000
    registry = _FakeSkillRegistry(
        active=[
            _FakeSkillRecord(skill_id="long-skill", version="1.0", state="draft", body=long_body)
        ]
    )
    tools = _register(registry=registry)
    result = await tools["list_pending_drafts"]()
    assert result["drafts"][0]["body"] is not None
    assert len(result["drafts"][0]["body"]) == 500


# ---------------------------------------------------------------------------
# get_promotion_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_promotion_history_available() -> None:
    registry = _FakeSkillRegistry()
    tools = _register(registry=registry)
    result = await tools["get_promotion_history"]("skill-a")
    assert result["available"] is True
    assert result["skill_id"] == "skill-a"
    assert result["count"] == 2
    assert len(result["history"]) == 2
    # Second entry had a rollback
    assert result["history"][1]["has_rollback"] is True


@pytest.mark.asyncio
async def test_get_promotion_history_not_available() -> None:
    tools = _register(registry=None)
    result = await tools["get_promotion_history"]("any-skill")
    assert result["available"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_get_promotion_history_unknown_skill() -> None:
    """Unknown skill should return empty history, not an error."""
    registry = _FakeSkillRegistry()
    tools = _register(registry=registry)
    result = await tools["get_promotion_history"]("unknown-skill")
    assert result["available"] is True
    assert result["count"] == 0
    assert result["history"] == []


@pytest.mark.asyncio
async def test_get_promotion_history_handles_exception() -> None:
    class _BrokenRegistry:
        def list_history(self, skill_id):
            raise RuntimeError("history error")

    tools = _register(registry=_BrokenRegistry())
    result = await tools["get_promotion_history"]("skill-a")
    assert result["available"] is True
    assert "error" in result
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# Graceful error handling across all tools
# ---------------------------------------------------------------------------


def test_all_tools_handle_missing_services() -> None:
    """All 5 tools should return graceful 'not available' when services are None."""
    tools = _register(pipeline=None, evidence=None, registry=None)

    # get_pipeline_status is async (sync wrapper returns coroutine)
    status_result = asyncio.run(_call_tool(tools, "get_pipeline_status"))
    assert status_result["available"] is False

    async def run_all():
        results = []
        results.append(await _call_tool(tools, "list_evidence", "", 20))
        results.append(await _call_tool(tools, "trigger_synthesis"))
        results.append(await _call_tool(tools, "list_pending_drafts"))
        results.append(await _call_tool(tools, "get_promotion_history", "any-skill"))
        return results

    for r in asyncio.run(run_all()):
        assert r["available"] is False
