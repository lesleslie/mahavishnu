"""Coverage-focused tests for the Dhara-backed adapter registry client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import mahavishnu.core.oneiric_client as oc


class _FakeDharaClient:
    def __init__(self, base_url: str = "http://dhara:8683/mcp") -> None:
        self.base_url = base_url
        self.calls: list[tuple[str, dict]] = []
        self.fail_next = False
        self.adapters = [
            {
                "adapter_id": "adapter:workflow:prefect",
                "domain": "adapter",
                "key": "workflow",
                "provider": "prefect",
                "version": "1.0.0",
                "factory_path": "mahavishnu.engines.prefect_adapter:PrefectAdapter",
                "capabilities": ["workflow"],
                "metadata": {"category": "workflow", "project": "mahavishnu", "priority": 5},
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_health_check": "2026-01-02T00:00:00+00:00",
                "health_status": "healthy",
            }
        ]

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        self.calls.append((name, arguments))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("down")
        if name == "list_adapters":
            return {"success": True, "count": len(self.adapters), "adapters": self.adapters}
        if name == "get_adapter":
            return {"success": True, "adapter": self.adapters[0]}
        if name == "get_adapter_health":
            return {"success": True, "health": {"healthy": True}}
        if name == "get_contract_info":
            return {"ok": True, "tool_groups": {"adapter_registry": ["list_adapters"]}}
        raise AssertionError(name)


def test_get_and_set_dhara_client_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class _DharaClient:
        def __init__(self, base_url: str, token: str | None = None) -> None:
            created.append(base_url)
            self.base_url = base_url

    monkeypatch.setattr("mahavishnu.core.dhara_adapter.DharaClient", _DharaClient, raising=False)
    oc._dhara_clients.clear()

    oc.set_dhara_client_base_url("http://example:9999/mcp/")
    c1 = oc.get_dhara_client()
    c2 = oc.get_dhara_client("http://example:9999/mcp")
    c3 = oc.get_dhara_client("http://other:8683/mcp")

    assert c1 is c2
    assert c1 is not c3
    assert created == ["http://example:9999/mcp", "http://other:8683/mcp"]


def test_adapter_entry_from_dhara_and_pb2_compat() -> None:
    entry = oc.AdapterEntry.from_dhara(
        {
            "domain": "adapter",
            "key": "storage",
            "provider": "local",
            "factory_path": "x.y.Z",
            "capabilities": ["read"],
            "metadata": {"category": "storage"},
            "created_at": "2026-01-01T00:00:00Z",
            "health_status": "healthy",
        }
    )
    assert entry.adapter_id == "adapter:storage:local"
    assert entry.category == "storage"
    assert entry.registered_at is not None

    pb = SimpleNamespace(
        adapter_id="a",
        project="p",
        domain="d",
        category="c",
        provider="prov",
        capabilities=("x", "y"),
        factory_path="f",
        health_check_url="",
        metadata={"k": "v"},
        registered_at=10,
        last_heartbeat=20,
        health_status="healthy",
    )
    assert oc.AdapterEntry.from_pb2(pb).to_dict()["adapter_id"] == "a"


@pytest.mark.asyncio
async def test_circuit_breaker_block_and_reset() -> None:
    breaker = oc.AdapterCircuitBreaker(failure_threshold=2, block_duration_sec=1)
    assert await breaker.is_available("a")
    await breaker.record_failure("a")
    assert await breaker.is_available("a")
    await breaker.record_failure("a")
    assert not await breaker.is_available("a")
    await breaker.record_success("a")
    assert await breaker.is_available("a")

    breaker.blocked_until["b"] = datetime.now(UTC) - timedelta(seconds=1)
    breaker.failures["b"] = 9
    assert await breaker.is_available("b")
    assert "b" not in breaker.failures


@pytest.mark.asyncio
async def test_dhara_registry_client_happy_path_and_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDharaClient()
    monkeypatch.setattr(oc, "get_dhara_client", lambda _base_url=None, _token=None: fake)

    client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True, cache_ttl_sec=120))
    assert client._make_cache_key("p", "d", "c", True) == "p:d:c:healthy"

    adapters_1 = await client.list_adapters(
        project="mahavishnu", domain="adapter", category="workflow"
    )
    adapters_2 = await client.list_adapters(
        project="mahavishnu", domain="adapter", category="workflow"
    )
    assert len(adapters_1) == 1
    assert adapters_1 == adapters_2
    assert fake.calls.count(("list_adapters", {"domain": "adapter", "category": "workflow"})) == 1

    adapter = await client.get_adapter("adapter:workflow:prefect")
    assert adapter is not None
    assert await client.check_adapter_health("adapter:workflow:prefect") is True
    assert await client.resolve_adapter("adapter", "workflow", "prefect", "mahavishnu") is not None
    assert await client.resolve_adapter("adapter", "workflow", "missing", "mahavishnu") is None
    assert await client.send_heartbeat("adapter:workflow:prefect") is True

    health = await client.health_check()
    assert health["status"] == "healthy"
    assert health["connected"] is True

    await client.invalidate_cache()
    assert client._cache == {}
    await client.close()
    assert client._connected is False

    disabled = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=False))
    assert await disabled.list_adapters() == []
    assert await disabled.get_adapter("x") is None
    assert await disabled.check_adapter_health("x") is False
    assert await disabled.send_heartbeat("x") is False
    assert await disabled.health_check() == {"status": "disabled", "connected": False}


@pytest.mark.asyncio
async def test_dhara_registry_client_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDharaClient()
    monkeypatch.setattr(oc, "get_dhara_client", lambda _base_url=None, _token=None: fake)
    client = oc.OneiricMCPClient(oc.OneiricMCPConfig(enabled=True, cache_ttl_sec=0))

    fake.fail_next = True
    with pytest.raises(ConnectionError):
        await client.list_adapters(use_cache=False)

    assert await client.get_adapter("not-a-dhara-id") is None

    fake.adapters[0]["health_status"] = "unhealthy"
    assert await client.list_adapters(healthy_only=True, use_cache=False) == []

    fake.fail_next = True
    health = await client.health_check()
    assert health["status"] == "unhealthy"
