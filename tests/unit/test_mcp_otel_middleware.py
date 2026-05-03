"""Tests for FastMCP OpenTelemetry middleware wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp.otel_middleware import FastMCPOpenTelemetryMiddleware
from mahavishnu.mcp.server_core import FastMCPServer


class _Span:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []
        self.status = None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)

    def set_status(self, status: object) -> None:
        self.status = status


class _SpanContextManager:
    def __init__(self, span: _Span) -> None:
        self._span = span

    def __enter__(self) -> _Span:
        return self._span

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001,ANN201,ANN202
        return False


class _Tracer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.span = _Span()

    def start_as_current_span(
        self, name: str, attributes: dict[str, object] | None = None
    ) -> _SpanContextManager:
        self.calls.append((name, attributes or {}))
        self.span.attributes.update(attributes or {})
        return _SpanContextManager(self.span)


@pytest.mark.asyncio
async def test_otel_middleware_wraps_mcp_request(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _Tracer()
    monkeypatch.setattr(
        "mcp_common.server.telemetry.trace.get_tracer",
        lambda _name: tracer,
    )

    middleware = FastMCPOpenTelemetryMiddleware(
        service_name="mahavishnu",
        environment="production",
    )
    context = SimpleNamespace(
        method="tools/call",
        type="request",
        message=SimpleNamespace(name="list_repos"),
    )

    result = await middleware.on_message(context, lambda _ctx: _success_result())

    assert result == {"status": "ok", "count": 2}
    assert tracer.calls[0][0] == "mcp.tools.call.list_repos"
    assert tracer.calls[0][1]["rpc.system"] == "mcp"
    assert tracer.calls[0][1]["mcp.tool.name"] == "list_repos"
    assert tracer.span.attributes["mcp.result.status"] == "ok"
    assert tracer.span.attributes["service.name"] == "mahavishnu"
    assert tracer.span.attributes["service.environment"] == "production"


@pytest.mark.asyncio
async def test_otel_middleware_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _Tracer()
    monkeypatch.setattr(
        "mcp_common.server.telemetry.trace.get_tracer",
        lambda _name: tracer,
    )

    middleware = FastMCPOpenTelemetryMiddleware(service_name="mahavishnu")
    context = SimpleNamespace(
        method="tools/call",
        type="request",
        message=SimpleNamespace(name="broken_tool"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.on_message(context, _raise_runtime_error)

    assert tracer.calls[0][0] == "mcp.tools.call.broken_tool"
    assert tracer.span.exceptions


def test_fastmcp_server_registers_otel_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mahavishnu.mcp.server_core.get_auth_from_config", lambda config: None)

    config = SimpleNamespace(
        server_name="Test Server",
        observability=SimpleNamespace(tracing_enabled=True),
        terminal=SimpleNamespace(
            enabled=False, adapter_preference="auto", max_concurrent_sessions=1
        ),
    )
    app = SimpleNamespace(
        config=config,
        get_repos=lambda **kwargs: [],
        execute_workflow_parallel=None,
        workflow_state_manager=MagicMock(),
        rbac_manager=MagicMock(),
        observability=MagicMock(),
        opensearch_integration=MagicMock(),
        error_recovery_manager=MagicMock(),
        monitoring_service=MagicMock(),
        worktree_coordinator=None,
    )

    server = FastMCPServer(app=app)

    assert any(
        isinstance(middleware, FastMCPOpenTelemetryMiddleware)
        for middleware in server.server.middleware
    )


def test_fastmcp_server_skips_otel_middleware_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mahavishnu.mcp.server_core.get_auth_from_config", lambda config: None)

    config = SimpleNamespace(
        server_name="Test Server",
        observability=SimpleNamespace(tracing_enabled=False),
        terminal=SimpleNamespace(
            enabled=False, adapter_preference="auto", max_concurrent_sessions=1
        ),
    )
    app = SimpleNamespace(
        config=config,
        get_repos=lambda **kwargs: [],
        execute_workflow_parallel=None,
        workflow_state_manager=MagicMock(),
        rbac_manager=MagicMock(),
        observability=MagicMock(),
        opensearch_integration=MagicMock(),
        error_recovery_manager=MagicMock(),
        monitoring_service=MagicMock(),
        worktree_coordinator=None,
    )

    server = FastMCPServer(app=app)

    assert not any(
        isinstance(middleware, FastMCPOpenTelemetryMiddleware)
        for middleware in server.server.middleware
    )


async def _success_result() -> dict[str, object]:
    return {"status": "ok", "count": 2}


async def _raise_runtime_error(_context) -> None:
    raise RuntimeError("boom")
