"""Verify the 5 ecosystem-state MCP tools (Phase 3 of Dhara retirement).

Mirrors the test shape of ``test_workflow_tools.py`` / ``test_webhook_tools.py``:

* Patch ``mahavishnu.core.ecosystem_state.dhara_calltime`` so a host-supplied
  fake ``put`` / ``get`` swap routes into the leaf store without booting a real
  Dhara server.
* Verify each tool: registers on the FastMCP server, delegates to the leaf
  ``AsyncEcosystemStateStore`` correctly, and enforces the ``@require_mcp_auth``
  contract via the ``rbac_manager`` argument.
* The substrate is exercised through the index + record keys so we catch
  regressions in either the writer (upsert / record) or the reader
  (get / list) paths.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP
import msgspec
import pytest

from mahavishnu.core.models.persistence import EcosystemEvent, EcosystemService
from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.tools import ecosystem_state_tools
from mahavishnu.mcp.tools.ecosystem_state_tools import register_ecosystem_state_tools

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSubstrate:
    """In-memory substrate: ``put`` is sync, ``get`` is awaitable.

    Mirrors the production contract used by ``outcome_writer.py`` /
    ``webhook_receiver.py`` (sync ``put``) and ``webhook_replay.py`` /
    ``workflow_tools.py`` (async ``get``).

    The substrate stores records in a plain dict; ``get`` round-trips a
    copy so the test assertions see the durable form. ``list_prefix``
    is NOT part of the substrate-compat surface, so listing is driven
    off the index keys (``ecosystem-services-index/``,
    ``ecosystem-events-index/``) which the writer updates atomically.
    """

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        # msgspec.to_builtins already returned plain dicts at the writer
        # boundary, so this is a direct assignment.
        self.records[key] = value

    async def get(self, key: str) -> Any:
        value = self.records.get(key)
        if value is None:
            return None
        # Return a shallow copy so the writer can mutate its own views.
        if isinstance(value, list):
            return [dict(item) for item in value]
        return dict(value)

    def clear(self) -> None:
        self.records.clear()


def _patch_substrate(monkeypatch: pytest.MonkeyPatch, substrate: _FakeSubstrate) -> None:
    """Swap the lazy ``dhara_calltime`` resolver on the ecosystem_state module.

    The substrate-compat shim is imported by name in
    :mod:`mahavishnu.core.ecosystem_state`; monkeypatch the symbol
    there so the writer resolves ``put`` / ``get`` to our fake without
    spinning up a host dhara install.
    """

    def fake_calltime(name: str) -> Any:
        if name == "put":
            return substrate.put
        if name == "get":
            return substrate.get
        return None

    monkeypatch.setattr(
        "mahavishnu.core.ecosystem_state.dhara_calltime", fake_calltime,
    )


def _fake_rbac_manager(*, allow: bool = True) -> Any:
    """Return a fake RBAC manager that allows (or denies) all checks."""
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=allow)
    return rbac


# ---------------------------------------------------------------------------
# Leaf-store tests (no FastMCP layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_service_persists_and_returns_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf: ``upsert_service`` writes the record + updates the index."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    record = await store.upsert_service_async(
        service_id="svc-1",
        service_type="mcp",
        capabilities=["a", "b"],
        metadata={"k": "v"},
        status="ok",
    )
    assert isinstance(record, dict)
    assert record["service_id"] == "svc-1"
    assert record["service_type"] == "mcp"
    assert record["capabilities"] == ["a", "b"]
    assert record["metadata"] == {"k": "v"}
    assert record["status"] == "ok"
    assert record["schema_version"] == 1
    assert record["created_at"] is not None
    assert record["updated_at"] is not None

    # Both the service record AND the index entry are persisted.
    assert substrate.records["ecosystem-services/svc-1/"]["service_id"] == "svc-1"
    index = substrate.records["ecosystem-services-index/"]
    assert any(entry["service_id"] == "svc-1" for entry in index)


@pytest.mark.asyncio
async def test_upsert_service_preserves_created_at_on_re_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf: re-upserting a service preserves the original ``created_at``."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    first = await store.upsert_service_async(
        service_id="svc-2", service_type="mcp", status="ok"
    )
    original_created = first["created_at"]
    second = await store.upsert_service_async(
        service_id="svc-2", service_type="mcp", status="degraded"
    )
    assert second["created_at"] == original_created
    assert second["status"] == "degraded"
    assert second["updated_at"] >= original_created


@pytest.mark.asyncio
async def test_get_service_returns_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf: ``get_service`` reads back the durable record."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    await store.upsert_service_async(
        service_id="svc-3", service_type="worker_pool", status="ok"
    )

    fetched = await store.get_service_async("svc-3")
    assert isinstance(fetched, dict)
    assert fetched["service_id"] == "svc-3"
    assert fetched["service_type"] == "worker_pool"

    missing = await store.get_service_async("nope")
    assert missing is None


@pytest.mark.asyncio
async def test_list_services_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf: ``list_services`` respects service_type / status / capability filters."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    await store.upsert_service_async(
        service_id="a", service_type="mcp", capabilities=["deploy"], status="ok"
    )
    await store.upsert_service_async(
        service_id="b", service_type="worker_pool", capabilities=["run"], status="ok"
    )
    await store.upsert_service_async(
        service_id="c", service_type="mcp", capabilities=["run"], status="degraded"
    )

    all_services = await store.list_services_async()
    assert {s["service_id"] for s in all_services} == {"a", "b", "c"}

    only_mcp = await store.list_services_async(service_type="mcp")
    assert {s["service_id"] for s in only_mcp} == {"a", "c"}

    only_degraded = await store.list_services_async(status="degraded")
    assert {s["service_id"] for s in only_degraded} == {"c"}

    only_run_capability = await store.list_services_async(capability="run")
    assert {s["service_id"] for s in only_run_capability} == {"b", "c"}


@pytest.mark.asyncio
async def test_record_and_list_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaf: events round-trip through substrate with retention pruning."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    first = await store.record_event_async(
        event_type="service_started",
        source_service="svc-a",
        payload={"k": 1},
    )
    assert isinstance(first, dict)
    assert first["event_type"] == "service_started"
    assert first["source_service"] == "svc-a"
    assert first["related_service"] is None
    assert first["payload"] == {"k": 1}
    assert first["event_id"]  # derived from timestamp + source_service + uuid

    second = await store.record_event_async(
        event_type="service_started",
        source_service="svc-b",
        related_service="svc-a",
        # Recent timestamp so the 30-day retention window does not prune it.
        timestamp="2099-01-01T00:00:00+00:00",
    )
    assert second["related_service"] == "svc-a"
    assert second["timestamp"] == "2099-01-01T00:00:00+00:00"

    # List with no filter → both events (sliced to the most recent `limit`).
    events = await store.list_events_async()
    assert len(events) == 2

    # Filter by event_type → only the second event (added last).
    by_type = await store.list_events_async(event_type="service_started")
    assert len(by_type) == 2

    # Filter by source_service → only svc-b events.
    by_source = await store.list_events_async(source_service="svc-b")
    assert len(by_source) == 1
    assert by_source[0]["source_service"] == "svc-b"

    # Filter by related_service → only svc-a-related events.
    by_related = await store.list_events_async(related_service="svc-a")
    assert len(by_related) == 1

    # Limit trims the result.
    limited = await store.list_events_async(limit=1)
    assert len(limited) == 1


# ---------------------------------------------------------------------------
# FastMCP-registered tool tests
# ---------------------------------------------------------------------------


_EXPECTED_TOOLS = {
    "mahavishnu_upsert_service",
    "mahavishnu_get_service",
    "mahavishnu_list_services",
    "mahavishnu_record_event",
    "mahavishnu_list_events",
}


@pytest.mark.asyncio
async def test_register_ecosystem_state_tools_registers_all_five() -> None:
    """register_ecosystem_state_tools registers the 5 canonical tool names."""
    mcp = FastMCP(name="test-ecosystem-state-tools")
    register_ecosystem_state_tools(mcp)
    tool_names = {t.name for t in await mcp.list_tools()}
    missing = _EXPECTED_TOOLS - tool_names
    assert not missing, f"missing tools: {missing}"

    # Each registered tool is async, matching the FastMCP contract.
    for name in _EXPECTED_TOOLS:
        tool = next(t for t in await mcp.list_tools() if t.name == name)
        assert asyncio.iscoroutinefunction(tool.fn), f"{name} must be async"


@pytest.mark.asyncio
async def test_registered_upsert_tool_delegates_to_leaf_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the registered ``mahavishnu_upsert_service`` writes via the leaf store."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    mcp = FastMCP(name="test-ecosystem-state-tools-upsert")
    register_ecosystem_state_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_upsert_service")

    result = await tool.fn(
        service_id="e2e-svc",
        service_type="mcp",
        capabilities=["x"],
        user_id="alice",
    )

    assert result["service_id"] == "e2e-svc"
    assert substrate.records["ecosystem-services/e2e-svc/"]["service_type"] == "mcp"


@pytest.mark.asyncio
async def test_registered_get_tool_returns_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ``mahavishnu_get_service`` returns ``{"ok": True, "service": ...}``."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    await store.upsert_service_async(service_id="g-1", service_type="mcp", status="ok")

    mcp = FastMCP(name="test-ecosystem-state-tools-get")
    register_ecosystem_state_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_get_service")

    result = await tool.fn(service_id="g-1", user_id="alice")
    assert result["ok"] is True
    assert result["service"]["service_id"] == "g-1"

    missing = await tool.fn(service_id="missing", user_id="alice")
    assert missing == {"ok": True, "service": None}


@pytest.mark.asyncio
async def test_registered_list_tools_return_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: list tools return ``{"ok": True, "count": N, ...}``."""
    substrate = _FakeSubstrate()
    _patch_substrate(monkeypatch, substrate)

    from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore

    store = AsyncEcosystemStateStore()
    await store.upsert_service_async(service_id="ls-1", service_type="mcp")
    await store.upsert_service_async(service_id="ls-2", service_type="worker_pool")
    await store.record_event_async(event_type="x", source_service="ls-1")

    mcp = FastMCP(name="test-ecosystem-state-tools-list")
    register_ecosystem_state_tools(mcp, rbac_manager=_fake_rbac_manager())
    services_tool = next(
        t for t in await mcp.list_tools() if t.name == "mahavishnu_list_services"
    )
    events_tool = next(
        t for t in await mcp.list_tools() if t.name == "mahavishnu_list_events"
    )

    services = await services_tool.fn(user_id="alice")
    assert services["ok"] is True
    assert services["count"] == 2
    assert {s["service_id"] for s in services["services"]} == {"ls-1", "ls-2"}

    events = await events_tool.fn(user_id="alice")
    assert events["ok"] is True
    assert events["count"] == 1


# ---------------------------------------------------------------------------
# Auth contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_rejects_without_user_id() -> None:
    """@require_mcp_auth wrapper rejects calls missing ``user_id``.

    Without ``user_id`` the wrapper returns the AUTH_REQUIRED error envelope
    BEFORE the leaf store runs. The substrate-compat gate is not touched.
    """
    mcp = FastMCP(name="test-ecosystem-state-tools-auth-write")
    register_ecosystem_state_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_upsert_service")

    result = await tool.fn(service_id="auth-svc", service_type="mcp")

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_read_tool_rejects_without_user_id() -> None:
    """Same AUTH_REQUIRED envelope for the READ tools."""
    mcp = FastMCP(name="test-ecosystem-state-tools-auth-read")
    register_ecosystem_state_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_get_service")

    result = await tool.fn(service_id="x")

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_write_tool_intruder_returns_permission_denied() -> None:
    """RBAC denies → ``PERMISSION_DENIED`` envelope for WRITE tools."""
    rbac = _fake_rbac_manager(allow=False)
    mcp = FastMCP(name="test-ecosystem-state-tools-intruder-write")
    register_ecosystem_state_tools(mcp, rbac_manager=rbac)
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_upsert_service")

    result = await tool.fn(service_id="x", service_type="mcp", user_id="intruder")

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_code"] == "PERMISSION_DENIED"
    # WRITE gate forwarded the correct permission enum.
    call_args = rbac.check_permission.await_args_list
    assert any(
        call.kwargs.get("permission") == Permission.WRITE_ECOSYSTEM_STATE
        or (call.args and call.args[2] == Permission.WRITE_ECOSYSTEM_STATE)
        for call in call_args
    )


@pytest.mark.asyncio
async def test_read_tool_intruder_returns_permission_denied() -> None:
    """RBAC denies → ``PERMISSION_DENIED`` envelope for READ tools."""
    rbac = _fake_rbac_manager(allow=False)
    mcp = FastMCP(name="test-ecosystem-state-tools-intruder-read")
    register_ecosystem_state_tools(mcp, rbac_manager=rbac)
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_get_service")

    result = await tool.fn(service_id="x", user_id="intruder")

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_code"] == "PERMISSION_DENIED"
    call_args = rbac.check_permission.await_args_list
    assert any(
        call.kwargs.get("permission") == Permission.READ_ECOSYSTEM_STATE
        or (call.args and call.args[2] == Permission.READ_ECOSYSTEM_STATE)
        for call in call_args
    )


@pytest.mark.asyncio
async def test_no_rbac_returns_auth_not_configured() -> None:
    """``rbac_manager=None`` → ``AUTH_NOT_CONFIGURED`` envelope (fail-closed)."""
    mcp = FastMCP(name="test-ecosystem-state-tools-no-rbac")
    register_ecosystem_state_tools(mcp, rbac_manager=None)
    tool = next(t for t in await mcp.list_tools() if t.name == "mahavishnu_list_services")

    result = await tool.fn(user_id="alice")

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Substrate-unbound behavior (smoke check that the leaf never crashes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaf_store_handles_unbound_substrate() -> None:
    """Substrate-unbound reads return ``None`` / ``[]``, writes warn + return the record."""

    def calltime_returns_none(name: str) -> Any:
        return None

    from mahavishnu.core import ecosystem_state

    prev = ecosystem_state.dhara_calltime
    ecosystem_state.dhara_calltime = calltime_returns_none  # type: ignore[assignment]
    try:
        store = ecosystem_state.AsyncEcosystemStateStore()
        # Reads → None / []
        assert await store.get_service_async("x") is None
        assert await store.list_services_async() == []
        assert await store.list_events_async() == []
        # Writes → record still constructed, persisted skipped with a warning log.
        upserted = await store.upsert_service_async(
            service_id="unbound-svc", service_type="mcp", status="ok"
        )
        assert upserted["service_id"] == "unbound-svc"
        recorded = await store.record_event_async(
            event_type="e", source_service="unbound-svc"
        )
        assert recorded["event_type"] == "e"
    finally:
        ecosystem_state.dhara_calltime = prev  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Sanity: the EcosystemService / EcosystemEvent structs validate
# ---------------------------------------------------------------------------


def test_ecosystem_models_validate() -> None:
    """Local msgspec Structs round-trip through ``msgspec.to_builtins``."""
    svc = EcosystemService(
        service_id="model-svc",
        service_type="mcp",
        capabilities=["a"],
        metadata={"k": "v"},
        status="ok",
    )
    svc_dict = msgspec.to_builtins(svc)
    assert svc_dict["service_id"] == "model-svc"
    # Round-trip through convert to confirm the schema matches.
    reloaded = msgspec.convert(svc_dict, EcosystemService)
    assert reloaded == svc

    evt = EcosystemEvent(
        event_id="eid-1",
        event_type="t",
        source_service="s",
        payload={"x": 1},
        timestamp="2026-09-16T00:00:00+00:00",
    )
    evt_dict = msgspec.to_builtins(evt)
    reloaded_evt = msgspec.convert(evt_dict, EcosystemEvent)
    assert reloaded_evt == evt


def test_ecosystem_state_tools_module_exports_register() -> None:
    """The module exposes the registration helper as a top-level symbol."""
    assert hasattr(ecosystem_state_tools, "register_ecosystem_state_tools")
    assert callable(ecosystem_state_tools.register_ecosystem_state_tools)
