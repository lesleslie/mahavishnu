"""Focused unit tests for core.adapter_registry."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import mahavishnu.core.adapter_registry as ar


@dataclass
class _Meta:
    adapter_id: str
    domain: str
    category: str
    provider: str
    capabilities: list[str]
    factory_path: str
    priority: int = 50
    source: str = "entry_point"


class _FakeDiscovery:
    def __init__(self, config) -> None:  # noqa: ANN001
        self.config = config
        self.closed = False
        self.invalidated = False
        self.items: list[_Meta] = []

    async def discover_all(self):
        return list(self.items)

    def invalidate_cache(self) -> None:
        self.invalidated = True

    async def close(self) -> None:
        self.closed = True


class _FakePersistence:
    def __init__(self) -> None:
        self.states: dict[str, object] = {}
        self.inited = False
        self.closed = False
        self.health: list[object] = []

    async def initialize(self) -> None:
        self.inited = True

    async def load_state(self, adapter_id: str):
        return self.states.get(adapter_id)

    async def save_state(self, state) -> None:  # noqa: ANN001
        self.states[state.adapter_id] = state

    async def record_health(self, record) -> None:  # noqa: ANN001
        self.health.append(record)

    async def close(self) -> None:
        self.closed = True


class _WS:
    def __init__(self) -> None:
        self.registered: list[dict] = []
        self.health_changed: list[dict] = []
        self.enabled_calls: list[dict] = []

    async def broadcast_adapter_registered(self, **kwargs):  # noqa: ANN003
        self.registered.append(kwargs)

    async def broadcast_adapter_health_changed(self, **kwargs):  # noqa: ANN003
        self.health_changed.append(kwargs)

    async def broadcast_adapter_enabled(self, **kwargs):  # noqa: ANN003
        self.enabled_calls.append(kwargs)


def _patch_registry_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar, "AdapterDiscoveryEngine", _FakeDiscovery)
    monkeypatch.setattr(ar, "AdapterPersistenceLayer", _FakePersistence)


class _Adapter:
    def __init__(self, config=None, health=None, fail=False):  # noqa: ANN001
        self.config = config
        self._health = health or {"status": "healthy", "latency_ms": 5}
        self._fail = fail

    async def get_health(self):
        if self._fail:
            raise RuntimeError("health failed")
        return self._health


@pytest.mark.asyncio
async def test_discover_register_resolve_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    ws = _WS()
    registry = ar.HybridAdapterRegistry(SimpleNamespace(), websocket_server=ws)

    module = SimpleNamespace(Prefect=_Adapter)
    monkeypatch.setattr(ar.importlib, "import_module", lambda _p: module)

    md = _Meta(
        adapter_id="mahavishnu.prefect",
        domain="orchestration",
        category="workflow",
        provider="prefect",
        capabilities=["deploy_flows", "monitor_execution"],
        factory_path="x.y:Prefect",
        priority=90,
    )
    registry.discovery.items = [md]
    await registry.initialize()
    report = await registry.discover_and_register()
    assert report.discovered == 1
    assert report.registered == 1
    assert ws.registered

    decision = await registry.resolve(
        domain="orchestration", key="workflow", capabilities=["deploy_flows"]
    )
    assert decision is not None
    assert decision.adapter_name == "prefect"

    # Cached resolution path
    decision2 = await registry.resolve(
        domain="orchestration", key="workflow", capabilities=["deploy_flows"]
    )
    assert decision2 is decision

    matches = await registry.find_by_capabilities(["deploy_flows"])
    assert len(matches) == 1
    assert matches[0].provider == "prefect"

    listed = registry.list_adapters(domain="orchestration", capabilities=["deploy_flows"])
    assert len(listed) == 1
    assert listed[0]["name"] == "prefect"
    assert registry.get_adapter("prefect") is not None
    assert registry.get_metadata("prefect") is not None


@pytest.mark.asyncio
async def test_register_failure_and_resolve_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    registry = ar.HybridAdapterRegistry(SimpleNamespace())
    await registry.initialize()

    # No factory path branch
    bad = _Meta(
        adapter_id="bad",
        domain="orchestration",
        category="workflow",
        provider="bad",
        capabilities=[],
        factory_path="",
    )
    ok = await registry._register_adapter_from_metadata(bad)  # noqa: SLF001
    assert ok is False

    # Import failure branch
    monkeypatch.setattr(ar.importlib, "import_module", lambda _p: (_ for _ in ()).throw(RuntimeError("x")))
    bad2 = _Meta(
        adapter_id="bad2",
        domain="orchestration",
        category="workflow",
        provider="bad2",
        capabilities=[],
        factory_path="a.b:C",
    )
    ok2 = await registry._register_adapter_from_metadata(bad2)  # noqa: SLF001
    assert ok2 is False

    # Module-only path branch: factory_path without ":" returns the imported module object.
    module_only = _Meta(
        adapter_id="module-only",
        domain="orchestration",
        category="workflow",
        provider="module-only",
        capabilities=[],
        factory_path="module.path",
    )
    monkeypatch.setattr(ar.importlib, "import_module", lambda _p: SimpleNamespace(marker=True))
    ok3 = await registry._register_adapter_from_metadata(module_only)  # noqa: SLF001
    assert ok3 is True
    assert registry.get_adapter("module-only") is not None

    assert await registry.resolve(domain="orchestration", key="workflow", capabilities=["none"]) is None


@pytest.mark.asyncio
async def test_health_checks_enable_disable_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    ws = _WS()
    registry = ar.HybridAdapterRegistry(SimpleNamespace(), websocket_server=ws)
    await registry.initialize()

    m1 = _Meta("id.prefect", "orchestration", "workflow", "prefect", ["a"], "x")
    m2 = _Meta("id.agno", "orchestration", "agent", "agno", ["b"], "y")
    registry._metadata = {"prefect": m1, "agno": m2}  # noqa: SLF001
    registry._adapters = {  # noqa: SLF001
        "prefect": _Adapter(health={"healthy": True, "latency_ms": 3}),
        "agno": _Adapter(fail=True),
    }

    health = await registry.check_all_health()
    assert health["prefect"]["status"] == "healthy"
    assert health["agno"]["status"] == "unhealthy"
    assert len(registry.persistence.health) == 2
    assert ws.health_changed

    # enable/disable with and without known adapter
    assert await registry.set_adapter_enabled("missing", True) is False
    assert await registry.set_adapter_enabled("prefect", False, reason="test") is True
    assert ws.enabled_calls

    # healthy_only filter path
    only_healthy = registry.list_adapters(healthy_only=True)
    assert [x["name"] for x in only_healthy] == ["prefect"]

    registry.invalidate_cache()
    assert registry.discovery.invalidated is True
    await registry.close()
    assert registry.discovery.closed is True
    assert registry.persistence.closed is True
    assert isinstance(registry.adapters, dict)


@pytest.mark.asyncio
async def test_discover_register_handles_registration_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    registry = ar.HybridAdapterRegistry(SimpleNamespace())
    await registry.initialize()

    registry.discovery.items = [
        _Meta(
            adapter_id="boom",
            domain="orchestration",
            category="workflow",
            provider="boom",
            capabilities=["deploy_flows"],
            factory_path="a.b:C",
        )
    ]

    async def _boom(_metadata):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "_register_adapter_from_metadata", _boom)

    report = await registry.discover_and_register()
    assert report.discovered == 1
    assert report.registered == 0
    assert report.failed == [("boom", "boom")]
    assert report.to_dict()["failed"] == [("boom", "boom")]


@pytest.mark.asyncio
async def test_discover_register_records_false_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    registry = ar.HybridAdapterRegistry(SimpleNamespace())
    await registry.initialize()

    registry.discovery.items = [
        _Meta(
            adapter_id="skip",
            domain="orchestration",
            category="workflow",
            provider="skip",
            capabilities=[],
            factory_path="",
        )
    ]

    report = await registry.discover_and_register()
    assert report.discovered == 1
    assert report.registered == 0
    assert report.failed == [("skip", "Registration failed")]


@pytest.mark.asyncio
async def test_resolve_and_list_filters_and_enable_state_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    registry = ar.HybridAdapterRegistry(SimpleNamespace())
    await registry.initialize()

    good = _Meta(
        adapter_id="good-id",
        domain="orchestration",
        category="workflow",
        provider="good",
        capabilities=["deploy_flows", "monitor_execution"],
        factory_path="x.y:Good",
        priority=80,
    )
    wrong_domain = _Meta(
        adapter_id="wrong-domain-id",
        domain="security",
        category="workflow",
        provider="wrong-domain",
        capabilities=["deploy_flows"],
        factory_path="x.y:Bad",
        priority=90,
    )
    wrong_caps = _Meta(
        adapter_id="wrong-caps-id",
        domain="orchestration",
        category="workflow",
        provider="wrong-caps",
        capabilities=["monitor_execution"],
        factory_path="x.y:Bad",
        priority=70,
    )

    registry._metadata = {  # noqa: SLF001
        "good": good,
        "wrong-domain": wrong_domain,
        "wrong-caps": wrong_caps,
    }
    registry._adapters = {  # noqa: SLF001
        "good": _Adapter(),
        "wrong-domain": _Adapter(),
        "wrong-caps": _Adapter(),
    }
    registry.persistence.states = {
        "good-id": SimpleNamespace(adapter_id="good-id", enabled=True, updated_at=None)
    }

    decision = await registry.resolve(
        domain="orchestration",
        key="workflow",
        capabilities=["deploy_flows"],
    )
    assert decision is not None
    assert decision.adapter_name == "good"

    listed = registry.list_adapters(domain="orchestration", capabilities=["deploy_flows"])
    assert [entry["name"] for entry in listed] == ["good"]

    assert await registry.set_adapter_enabled("missing", False) is False
    assert await registry.set_adapter_enabled("good", False, reason="maintenance") is True
    assert registry.persistence.states["good-id"].enabled is False
    assert registry.persistence.states["good-id"].updated_at is not None


@pytest.mark.asyncio
async def test_registry_singleton_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_registry_deps(monkeypatch)
    ar._registry = None

    with pytest.raises(RuntimeError):
        ar.get_registry()

    r1 = await ar.initialize_registry(SimpleNamespace())
    r2 = await ar.initialize_registry(SimpleNamespace())
    assert r1 is r2
    assert ar.get_registry() is r1
