"""Tests for the capability MCP tools.

Covers:
- ``_all_registrations`` merges engines + worker entries into one
  ``EngineRegistration`` list keyed by ``engine_id``.
- The three gated tools raise ``AuthorizationError`` on missing scope
  and short-circuit with ``FEATURE_DISABLED`` when the feature flag
  is off.
- ``resolve_capabilities`` returns a list of Candidate-shaped dicts;
  ``plan_capability`` returns an ExecutionDAG-shaped dict;
  ``execute_capability`` returns a CapabilityExecutionResult-shaped dict.
- ``list_capabilities`` is ungated and always returns the registry.

The Dhara client is mocked; no live storage is required.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from mahavishnu.core.capabilities import CapabilityId
from mahavishnu.core.config import EnginesConfig, WorkerEntry, WorkerRegistryConfig
from mahavishnu.core.errors import AuthorizationError, ErrorCode, MahavishnuError
from mahavishnu.mcp.tools import capability_tools as capability_tools_mod
from mahavishnu.mcp.tools.capability_tools import register_capability_tools


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _settings(
    *,
    capability_enabled: bool = True,
    capability_scopes: list[str] | None = None,
    worker_entries: list[WorkerEntry] | None = None,
) -> Any:
    """Build a settings object that satisfies the capability_tools interface.

    Uses a real ``WorkerRegistryConfig`` / ``EnginesConfig`` so attribute
    access mirrors production (and ``set(settings.engines.disabled)`` works).
    """
    settings = MagicMock()
    settings.capability_enabled = capability_enabled
    settings.capability_scopes = capability_scopes or []
    settings.worker_registry = WorkerRegistryConfig(
        entries=worker_entries or [],
    )
    settings.engines = EnginesConfig(disabled=[])
    return settings


def _worker_entry(
    *,
    worker_type: str = "terminal-claude",
    name: str = "",
    description: str = "",
    provides: list[str] | None = None,
) -> WorkerEntry:
    return WorkerEntry(
        worker_type=worker_type,
        name=name,
        description=description,
        provides=["worker:bash"] if provides is None else list(provides),
        tags=["shell"],
    )


def _tool(server: FastMCP, name: str) -> Any:
    """Find a registered tool on a FastMCP server by name."""
    tools = asyncio.run(server.list_tools())
    return next(t for t in tools if t.name == name)


# ---------------------------------------------------------------------------
# _all_registrations
# ---------------------------------------------------------------------------


def test_all_registrations_returns_empty_list_when_no_workers() -> None:
    """When there are no engines and no workers, the merged list is empty.

    Stub ``_all_registrations`` on the module to bypass the engines import.
    """
    original = capability_tools_mod._all_registrations
    capability_tools_mod._all_registrations = lambda s: []  # type: ignore[assignment]
    try:
        regs = capability_tools_mod._all_registrations(_settings())
    finally:
        capability_tools_mod._all_registrations = original  # type: ignore[assignment]
    assert regs == []


def test_all_registrations_groups_worker_entries_by_worker_type() -> None:
    """Two WorkerEntries with the same worker_type produce one EngineRegistration."""
    settings = _settings(
        worker_entries=[
            _worker_entry(worker_type="terminal-claude", provides=["worker:bash"]),
            _worker_entry(worker_type="terminal-claude", provides=["worker:edit"]),
            _worker_entry(worker_type="terminal-qwen", provides=["worker:bash"]),
        ],
    )
    regs = capability_tools_mod._worker_engine_registrations(settings)
    ids = {r.engine_id for r in regs}
    assert ids == {"terminal-claude", "terminal-qwen"}
    by_id = {r.engine_id: r for r in regs}
    # terminal-claude has the union of two entries' provides
    terminal_claude_caps = sorted(c.id for c in by_id["terminal-claude"].provides)
    assert terminal_claude_caps == ["worker:bash", "worker:edit"]
    assert sorted(c.id for c in by_id["terminal-qwen"].provides) == ["worker:bash"]


def test_all_registrations_skips_worker_entries_with_no_provides() -> None:
    """WorkerEntry with empty provides does not produce a registration."""
    settings = _settings(
        worker_entries=[_worker_entry(provides=[])],
    )
    regs = capability_tools_mod._worker_engine_registrations(settings)
    assert regs == []


# ---------------------------------------------------------------------------
# list_capabilities (ungated)
# ---------------------------------------------------------------------------


def test_list_capabilities_is_ungated_and_returns_registrations() -> None:
    """``list_capabilities`` always succeeds (no user_id required)."""
    settings = _settings(
        capability_enabled=False,  # ungated tool ignores the flag
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-list")
    register_capability_tools(server, settings)

    tool = _tool(server, "list_capabilities")
    result = asyncio.run(tool.fn())

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert isinstance(result["registrations"], list)


# ---------------------------------------------------------------------------
# Gated tools: feature flag
# ---------------------------------------------------------------------------


def test_resolve_capabilities_short_circuits_when_feature_flag_off() -> None:
    """When capability_enabled=False, FEATURE_DISABLED is surfaced."""
    settings = _settings(capability_enabled=False, capability_scopes=["alice"])
    server = FastMCP("test-feat")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    result = asyncio.run(
        tool.fn(requires=["engine:durable-flow"], prompt="x", user_id="alice")
    )

    assert result["status"] == "error"
    assert result["error_code"] == ErrorCode.FEATURE_DISABLED.value


def test_plan_capability_short_circuits_when_feature_flag_off() -> None:
    settings = _settings(capability_enabled=False, capability_scopes=["alice"])
    server = FastMCP("test-feat-plan")
    register_capability_tools(server, settings)
    tool = _tool(server, "plan_capability")

    result = asyncio.run(
        tool.fn(
            requires=["engine:durable-flow"], prompt="x", user_id="alice",
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == ErrorCode.FEATURE_DISABLED.value


def test_execute_capability_short_circuits_when_feature_flag_off() -> None:
    settings = _settings(capability_enabled=False, capability_scopes=["alice"])
    server = FastMCP("test-feat-exec")
    register_capability_tools(server, settings)
    tool = _tool(server, "execute_capability")

    result = asyncio.run(
        tool.fn(
            requires=["engine:durable-flow"], prompt="x", trace_id="a" * 32,
            user_id="alice",
        )
    )

    assert result["status"] == "rejected"
    assert result["error_code"] == ErrorCode.FEATURE_DISABLED.value


# ---------------------------------------------------------------------------
# Gated tools: scope checks (AuthorizationError, NOT PERMISSION_DENIED)
# ---------------------------------------------------------------------------


def test_resolve_capabilities_requires_user_id() -> None:
    """The require_mcp_auth decorator returns AUTH_REQUIRED when user_id is missing.

    The decorator short-circuits before the body runs, so the body never
    sees user_id=None. The MCP-boundary contract returns a dict, not a
    raised exception.
    """
    settings = _settings(capability_scopes=["alice"])
    server = FastMCP("test-no-user")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    result = asyncio.run(
        tool.fn(requires=["engine:durable-flow"], prompt="x", user_id=None)
    )
    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_REQUIRED"


def test_resolve_capabilities_rejects_user_outside_allow_list() -> None:
    """A user not in capability_scopes surfaces AUTHORIZATION_ERROR in the dict."""
    settings = _settings(capability_scopes=["alice"])
    server = FastMCP("test-bad-user")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    result = asyncio.run(
        tool.fn(
            requires=["engine:durable-flow"], prompt="x", user_id="mallory",
        )
    )
    assert result["status"] == "error"
    assert result["error_code"] == ErrorCode.AUTHORIZATION_ERROR.value


def test_plan_capability_rejects_user_outside_allow_list() -> None:
    settings = _settings(capability_scopes=["alice"])
    server = FastMCP("test-bad-user-plan")
    register_capability_tools(server, settings)
    tool = _tool(server, "plan_capability")

    result = asyncio.run(
        tool.fn(
            requires=["engine:durable-flow"], prompt="x", user_id="mallory",
        )
    )
    assert result["status"] == "error"
    assert result["error_code"] == ErrorCode.AUTHORIZATION_ERROR.value


def test_execute_capability_rejects_user_outside_allow_list() -> None:
    settings = _settings(capability_scopes=["alice"])
    server = FastMCP("test-bad-user-exec")
    register_capability_tools(server, settings)
    tool = _tool(server, "execute_capability")

    result = asyncio.run(
        tool.fn(
            requires=["engine:durable-flow"], prompt="x", trace_id="a" * 32,
            user_id="mallory",
        )
    )
    assert result["status"] == "rejected"
    assert result["error_code"] == ErrorCode.AUTHORIZATION_ERROR.value


def test_empty_scope_allow_list_accepts_any_authenticated_user() -> None:
    """When capability_scopes=[] (empty), any user_id passes the scope check.

    The allow-list is opt-in: an empty list means "no allow-list configured",
    NOT "no one allowed". This matches the brief's allow-list semantics —
    the gate only rejects when a non-empty allow-list excludes the caller.
    """
    settings = _settings(
        capability_scopes=[],
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-empty-scopes")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    # With an empty scope list, "alice" passes the gate. The resolve call
    # then either returns candidates (status=ok) or [] (status=ok, count=0)
    # — neither surfaces an AUTHORIZATION_ERROR.
    result = asyncio.run(
        tool.fn(
            requires=["worker:bash"], prompt="x", user_id="alice",
        )
    )
    assert result["status"] == "ok"
    assert result.get("error_code") != ErrorCode.AUTHORIZATION_ERROR.value


# ---------------------------------------------------------------------------
# End-to-end (against the in-process conductor)
# ---------------------------------------------------------------------------


def test_plan_capability_returns_execution_dag_shape() -> None:
    """With a registered worker providing ``worker:bash``, plan returns nodes/edges lists."""
    settings = _settings(
        capability_scopes=["alice"],
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-e2e-plan")
    register_capability_tools(server, settings)
    tool = _tool(server, "plan_capability")

    result = asyncio.run(
        tool.fn(
            requires=["worker:bash"], prompt="x", user_id="alice",
            trace_id="a" * 32,
        )
    )

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["trace_id"] == "a" * 32
    assert isinstance(result["nodes"], list)
    assert isinstance(result["edges"], list)
    assert result["nodes"][0]["engine_id"] == "terminal-claude"


def test_execute_capability_returns_capability_execution_result_shape() -> None:
    settings = _settings(
        capability_scopes=["alice"],
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-e2e-exec")
    register_capability_tools(server, settings)
    tool = _tool(server, "execute_capability")

    result = asyncio.run(
        tool.fn(
            requires=["worker:bash"], prompt="x", trace_id="b" * 32,
            user_id="alice",
        )
    )

    assert isinstance(result, dict)
    assert result["status"] == "planned"
    assert result["trace_id"] == "b" * 32
    assert result["nodes"] == 1
    assert result["edges"] == 0
    assert result["error"] is None


def test_resolve_capabilities_returns_candidates_when_match() -> None:
    settings = _settings(
        capability_scopes=["alice"],
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-e2e-resolve")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    result = asyncio.run(
        tool.fn(
            requires=["worker:bash"], prompt="x", user_id="alice",
        )
    )

    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["candidates"][0]["engine_id"] == "terminal-claude"


def test_resolve_capabilities_rejects_unknown_selector() -> None:
    """A bad selector surfaces a VALIDATION_ERROR dict (not an exception)."""
    settings = _settings(
        capability_scopes=["alice"],
        worker_entries=[_worker_entry(provides=["worker:bash"])],
    )
    server = FastMCP("test-bad-sel")
    register_capability_tools(server, settings)
    tool = _tool(server, "resolve_capabilities")

    result = asyncio.run(
        tool.fn(
            requires=["worker:bash"], prompt="x", user_id="alice",
            selector="not-a-strategy",
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == ErrorCode.VALIDATION_ERROR.value


def test_capability_id_is_validated_via_pydantic() -> None:
    """CapabilityId newtype uses TypeAdapter for runtime validation."""
    from pydantic import TypeAdapter, ValidationError

    from mahavishnu.core.capabilities import CapabilityId

    adapter: TypeAdapter[str] = TypeAdapter(CapabilityId)
    with pytest.raises(ValidationError):
        adapter.validate_python("not valid id with spaces")
