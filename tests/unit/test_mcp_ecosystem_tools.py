"""Unit tests for mahavishnu.mcp.tools.ecosystem_tools.

The module exposes ``register_ecosystem_tools`` which attaches three
canonical-status FastMCP tools. All three tools lazily import
``get_app_from_context`` and ``EcosystemStatusService`` at call time, so
the tests monkeypatch those source modules with fakes that return
hand-crafted ``EcosystemStatusReport``-shaped data.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import mahavishnu.mcp.tools.ecosystem_tools as et_module
from mahavishnu.mcp.tools.ecosystem_tools import register_ecosystem_tools


class _StubMCP:
    """Minimal FastMCP stand-in that returns decorated functions unchanged."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _adapter(name: str, status_value: str, *, has_trend: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        status=SimpleNamespace(value=status_value),
        capabilities={"code_generation": "ok"},
        degradation_trend=SimpleNamespace(value="stable") if has_trend else None,
        preference_score=0.5,
        name=name,
    )


def _capability(name: str, status_value: str) -> SimpleNamespace:
    cap = SimpleNamespace(status=SimpleNamespace(value=status_value))
    cap.model_dump = MagicMock(return_value={"name": name, "status": status_value})
    return cap


def _make_report(
    *,
    overall: str = "ok",
    adapters: dict[str, SimpleNamespace] | None = None,
    capabilities: dict[str, SimpleNamespace] | None = None,
) -> MagicMock:
    """Build a mock EcosystemStatusReport with the shape the tools read."""
    report = MagicMock()
    report.status = SimpleNamespace(value=overall)
    report.capabilities = capabilities or {}
    report.adapters = adapters or {}
    report.model_dump = MagicMock(
        return_value={
            "schema_version": "1.0",
            "status": overall,
            "generated_at": "2026-01-01T00:00:00Z",
            "duration_ms": 12.0,
            "services": {"session_buddy": {"status": "ok"}},
            "adapters": {n: {"status": a.status.value} for n, a in (adapters or {}).items()},
            "capabilities": {
                n: {"name": n, "status": c.status.value} for n, c in (capabilities or {}).items()
            },
            "workflows": {"active": 0},
            "alerts": {"total": 0},
            "recommendations": [],
            "errors": [],
        }
    )
    return report


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def fake_report() -> MagicMock:
    return _make_report(
        overall="ok",
        adapters={
            "prefect": _adapter("prefect", "ok"),
            "llamaindex": _adapter("llamaindex", "degraded"),
            "agno": _adapter("agno", "ok"),
        },
        capabilities={
            "code_generation": _capability("code_generation", "ok"),
            "code_review": _capability("code_review", "ok"),
            "vector_search": _capability("vector_search", "degraded"),
        },
    )


def _patch_service(
    monkeypatch: pytest.MonkeyPatch, report: MagicMock, app: object | None = None
) -> MagicMock:
    """Patch the lazy imports used inside the tool functions."""
    service_instance = MagicMock()
    service_instance.generate_report = AsyncMock(return_value=report)
    service_cls = MagicMock(return_value=service_instance)
    monkeypatch.setattr("mahavishnu.core.context.get_app_from_context", lambda: app)
    monkeypatch.setattr("mahavishnu.core.ecosystem_status.EcosystemStatusService", service_cls)
    return service_cls


def test_register_attaches_three_tools(stub_mcp: _StubMCP) -> None:
    register_ecosystem_tools(stub_mcp)
    assert set(stub_mcp.tools) == {
        "ecosystem_status",
        "ecosystem_capabilities",
        "ecosystem_routing_readiness",
    }
    # Module export
    assert "register_ecosystem_tools" in et_module.__all__


def test_ecosystem_status_returns_full_report(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    result = asyncio.run(fn())
    assert result["schema_version"] == "1.0"
    assert result["status"] == "ok"
    assert "services" in result
    assert "adapters" in result
    assert "capabilities" in result


def test_ecosystem_status_filters_sections(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    result = asyncio.run(fn(sections=["adapters", "alerts"]))
    # Filtered response keeps envelope keys + only requested sections
    assert result["schema_version"] == "1.0"
    assert result["status"] == "ok"
    assert "adapters" in result
    assert "alerts" in result
    # Not requested sections should be absent
    assert "services" not in result
    assert "capabilities" not in result


def test_ecosystem_status_filters_unknown_sections_silently(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    result = asyncio.run(fn(sections=["nope", "missing"]))
    # None of the unknown keys land in the result, but envelope is preserved
    assert "nope" not in result
    assert "missing" not in result
    assert result["status"] == "ok"


def test_ecosystem_status_passes_timeout_to_service(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    service_cls = _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    asyncio.run(fn(timeout_per_section_ms=2500))
    kwargs = service_cls.call_args.kwargs
    assert kwargs["section_timeout_ms"] == 2500


def test_ecosystem_status_uses_app_as_recovery_provider(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    app = SimpleNamespace(get_recovery_summary=lambda: {"x": 1})
    service_cls = _patch_service(monkeypatch, fake_report, app=app)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    asyncio.run(fn())
    assert service_cls.call_args.kwargs["recovery_provider"] is app


def test_ecosystem_status_recovery_provider_none_when_no_app(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    service_cls = _patch_service(monkeypatch, fake_report, app=None)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_status"]
    import asyncio

    asyncio.run(fn())
    assert service_cls.call_args.kwargs["recovery_provider"] is None


def test_ecosystem_capabilities_returns_all(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_capabilities"]
    import asyncio

    result = asyncio.run(fn())
    assert set(result) == {"code_generation", "code_review", "vector_search"}
    assert result["code_generation"] == {"name": "code_generation", "status": "ok"}


def test_ecosystem_capabilities_filters_case_insensitively(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_capabilities"]
    import asyncio

    result = asyncio.run(fn(capability="CODE"))
    # Both "code_generation" and "code_review" contain "code" (case-insensitive)
    assert set(result) == {"code_generation", "code_review"}
    assert "vector_search" not in result


def test_ecosystem_capabilities_filter_no_match(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_capabilities"]
    import asyncio

    result = asyncio.run(fn(capability="zzz"))
    assert result == {}


def test_ecosystem_routing_readiness_classifies_adapters(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_routing_readiness"]
    import asyncio

    result = asyncio.run(fn(task_class="CODE_GENERATION"))
    assert result["task_class"] == "CODE_GENERATION"
    assert result["overall_status"] == "ok"
    assert result["healthy_count"] == 2  # prefect, agno
    assert result["degraded_count"] == 1  # llamaindex
    # Recommendation picks the first healthy adapter
    assert result["recommendation"] == "Use prefect"
    # Adapter detail fields are present
    assert result["available_adapters"]["prefect"]["status"] == "ok"
    assert result["available_adapters"]["llamaindex"]["degradation_trend"] == "stable"
    assert result["available_adapters"]["agno"]["preference_score"] == 0.5


def test_ecosystem_routing_readiness_handles_null_degradation_trend(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
    fake_report: MagicMock,
) -> None:
    fake_report.adapters = {
        "p": _adapter("p", "ok", has_trend=False),
        "a": _adapter("a", "ok", has_trend=False),
    }
    _patch_service(monkeypatch, fake_report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_routing_readiness"]
    import asyncio

    result = asyncio.run(fn(task_class="X"))
    assert result["available_adapters"]["p"]["degradation_trend"] is None


def test_ecosystem_routing_readiness_no_healthy_adapters(
    stub_mcp: _StubMCP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _make_report(
        overall="unhealthy",
        adapters={
            "p": _adapter("p", "unhealthy"),
            "a": _adapter("a", "degraded"),
        },
        capabilities={},
    )
    _patch_service(monkeypatch, report)
    register_ecosystem_tools(stub_mcp)
    fn = stub_mcp.tools["ecosystem_routing_readiness"]
    import asyncio

    result = asyncio.run(fn(task_class="X"))
    assert result["healthy_count"] == 0
    assert result["degraded_count"] == 1
    assert "No healthy adapters" in result["recommendation"]
    assert "X" in result["recommendation"]
