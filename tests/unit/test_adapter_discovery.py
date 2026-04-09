"""Targeted coverage tests for adapter discovery engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine, AdapterMetadata


class _FakeEP:
    def __init__(self, name: str, payload):
        self.name = name
        self._payload = payload

    def load(self):
        return self._payload


def _meta(adapter_id: str = "mahavishnu.adapters.x") -> dict:
    return {
        "adapter_id": adapter_id,
        "domain": "orchestration",
        "category": "workflow",
        "provider": "prefect",
        "capabilities": ["workflow"],
        "factory_path": "x:y",
        "priority": 1,
        "metadata": {"k": "v"},
    }


def test_adapter_metadata_from_entry_point_success_and_error() -> None:
    ep_ok = _FakeEP("ok", lambda: _meta())
    got = AdapterMetadata.from_entry_point(ep_ok)
    assert got.source == "entry_point"
    assert got.adapter_id == "mahavishnu.adapters.x"
    payload = got.to_dict()
    assert payload["source"] == "entry_point"
    assert payload["adapter_id"] == "mahavishnu.adapters.x"

    ep_bad = _FakeEP("bad", lambda: {"adapter_id": "missing_fields"})
    with pytest.raises(ValueError):
        AdapterMetadata.from_entry_point(ep_bad)


def test_allowlist_and_cache_validity_paths() -> None:
    engine = AdapterDiscoveryEngine({"allowlist_patterns": [], "cache_ttl_seconds": 1})
    assert engine._is_adapter_allowed("anything")
    assert engine._is_cache_valid("missing") is False
    engine._cache["k"] = ([], datetime.now(UTC))
    assert engine._is_cache_valid("k") is True
    engine._cache["k"] = ([], datetime.now(UTC) - timedelta(seconds=5))
    assert engine._is_cache_valid("k") is False


@pytest.mark.asyncio
async def test_discover_from_entry_points_and_cache() -> None:
    engine = AdapterDiscoveryEngine({"allowlist_patterns": ["mahavishnu.adapters.*"]})
    fake_eps = [_FakeEP("a", lambda: _meta("mahavishnu.adapters.a"))]
    with patch("importlib.metadata.entry_points", return_value=fake_eps):
        first = await engine.discover_from_entry_points()
        second = await engine.discover_from_entry_points()
    assert len(first) == 1
    assert first[0].adapter_id == "mahavishnu.adapters.a"
    assert second[0].adapter_id == "mahavishnu.adapters.a"
    assert engine.get_cache_stats()["hits"] >= 1


@pytest.mark.asyncio
async def test_discover_from_entry_points_py39_style_and_invalid_entries() -> None:
    class _Selectable:
        def select(self, **kwargs):
            assert kwargs["group"] == "mahavishnu.adapters"
            return [
                _FakeEP("ok", lambda: _meta("mahavishnu.adapters.ok")),
                _FakeEP("blocked", lambda: _meta("evil.adapters.blocked")),
                _FakeEP("invalid", lambda: {"adapter_id": "broken"}),
            ]

    engine = AdapterDiscoveryEngine({"allowlist_patterns": ["mahavishnu.adapters.*"]})
    with patch("importlib.metadata.entry_points", side_effect=[TypeError("legacy"), _Selectable()]):
        result = await engine.discover_from_entry_points()
    assert [x.adapter_id for x in result] == ["mahavishnu.adapters.ok"]


@pytest.mark.asyncio
async def test_discover_from_entry_points_skips_generic_exception_from_entry() -> None:
    engine = AdapterDiscoveryEngine({"allowlist_patterns": ["mahavishnu.adapters.*"]})
    eps = [_FakeEP("boom", lambda: 1 / 0)]
    with patch("importlib.metadata.entry_points", return_value=eps):
        result = await engine.discover_from_entry_points()
    assert result == []


@pytest.mark.asyncio
async def test_discover_from_oneiric_mcp_paths() -> None:
    engine = AdapterDiscoveryEngine(
        {"allowlist_patterns": ["mahavishnu.adapters.*"], "enable_oneiric_mcp": True}
    )
    fake_entry = SimpleNamespace(
        adapter_id="mahavishnu.adapters.remote",
        domain="orchestration",
        category="workflow",
        provider="agno",
        capabilities=["workflow"],
        factory_path="m:n",
        metadata={"priority": 3},
        health_check_url=None,
    )
    client = MagicMock()
    client.list_adapters = AsyncMock(return_value=[fake_entry])
    with patch.object(engine, "_get_oneiric_client", return_value=client):
        result = await engine.discover_from_oneiric_mcp()
    assert len(result) == 1
    assert result[0].source == "oneiric_mcp"

    engine.invalidate_cache_for_source("oneiric_mcp")
    client.list_adapters = AsyncMock(side_effect=ConnectionError("down"))
    with patch.object(engine, "_get_oneiric_client", return_value=client):
        result = await engine.discover_from_oneiric_mcp()
    assert result == []


@pytest.mark.asyncio
async def test_discover_all_merges_sources_and_handles_failures() -> None:
    engine = AdapterDiscoveryEngine()
    ep_meta = AdapterMetadata(
        adapter_id="mahavishnu.adapters.same",
        domain="d",
        category="c",
        provider="p",
        capabilities=["x"],
        factory_path="a:b",
        source="entry_point",
    )
    remote_meta = AdapterMetadata(
        adapter_id="mahavishnu.adapters.same",
        domain="d",
        category="c",
        provider="p2",
        capabilities=["x"],
        factory_path="a:b",
        source="oneiric_mcp",
    )
    remote_other = AdapterMetadata(
        adapter_id="mahavishnu.adapters.other",
        domain="d",
        category="c",
        provider="p3",
        capabilities=["z"],
        factory_path="a:b",
        source="oneiric_mcp",
    )
    with (
        patch.object(engine, "discover_from_entry_points", AsyncMock(return_value=[ep_meta])),
        patch.object(
            engine, "discover_from_oneiric_mcp", AsyncMock(return_value=[remote_meta, remote_other])
        ),
    ):
        result = await engine.discover_all()
    assert len(result) == 2
    by_id = {x.adapter_id: x for x in result}
    assert by_id["mahavishnu.adapters.same"].source == "entry_point"
    assert by_id["mahavishnu.adapters.other"].source == "oneiric_mcp"

    cached = await engine.discover_all()
    assert len(cached) == 2

    engine.invalidate_cache_for_source("discover_all")
    with (
        patch.object(engine, "discover_from_entry_points", AsyncMock(side_effect=RuntimeError("x"))),
        patch.object(engine, "discover_from_oneiric_mcp", AsyncMock(side_effect=RuntimeError("y"))),
    ):
        result = await engine.discover_all()
    assert result == []


@pytest.mark.asyncio
async def test_get_oneiric_client_disabled_unavailable_and_failure() -> None:
    engine = AdapterDiscoveryEngine({"enable_oneiric_mcp": False})
    assert engine._get_oneiric_client() is None

    engine = AdapterDiscoveryEngine({"enable_oneiric_mcp": True})
    with patch("mahavishnu.core.adapter_discovery.ONEIRIC_MCP_AVAILABLE", False):
        assert engine._get_oneiric_client() is None

    with (
        patch("mahavishnu.core.adapter_discovery.ONEIRIC_MCP_AVAILABLE", True),
        patch("mahavishnu.core.adapter_discovery.OneiricMCPClient", side_effect=RuntimeError("nope")),
    ):
        assert engine._get_oneiric_client() is None

    fake_client = object()
    with (
        patch("mahavishnu.core.adapter_discovery.ONEIRIC_MCP_AVAILABLE", True),
        patch("mahavishnu.core.adapter_discovery.OneiricMCPClient", return_value=fake_client),
    ):
        assert engine._get_oneiric_client() is fake_client
        assert engine._get_oneiric_client() is fake_client


def test_init_accepts_oneiric_config_variants() -> None:
    import mahavishnu.core.adapter_discovery as module

    cfg_obj = module.OneiricMCPConfig()
    engine_obj = AdapterDiscoveryEngine({"oneiric_mcp_config": cfg_obj})
    assert engine_obj._oneiric_mcp_config is cfg_obj

    engine_dict = AdapterDiscoveryEngine({"oneiric_mcp_config": {"enabled": False}})
    assert isinstance(engine_dict._oneiric_mcp_config, module.OneiricMCPConfig)


@pytest.mark.asyncio
async def test_cache_invalidation_close_and_stats() -> None:
    engine = AdapterDiscoveryEngine()
    engine._cache["entry_points"] = ([], datetime.now(UTC))
    engine._cache_hits = 2
    engine._cache_misses = 1

    stats = engine.get_cache_stats()
    assert stats["entries"] == 1
    assert stats["hit_rate"] > 0
    assert "entry_points" in stats["entries_detail"]

    engine.invalidate_cache_for_source("entry_points")
    assert "entry_points" not in engine._cache
    engine.invalidate_cache()
    assert engine._cache == {}

    client = MagicMock()
    client.close = AsyncMock()
    engine._oneiric_client = client
    await engine.close()
    client.close.assert_awaited_once()
    assert engine._oneiric_client is None


@pytest.mark.asyncio
async def test_discover_from_oneiric_none_blocked_and_exception_paths() -> None:
    engine = AdapterDiscoveryEngine({"allowlist_patterns": ["mahavishnu.adapters.allowed"]})

    with patch.object(engine, "_get_oneiric_client", return_value=None):
        assert await engine.discover_from_oneiric_mcp() == []

    engine.invalidate_cache_for_source("oneiric_mcp")
    blocked_entry = SimpleNamespace(
        adapter_id="evil.adapters.blocked",
        domain="orchestration",
        category="workflow",
        provider="x",
        capabilities=["y"],
        factory_path="a:b",
        metadata={},
        health_check_url=None,
    )
    client = MagicMock()
    client.list_adapters = AsyncMock(return_value=[blocked_entry])
    with patch.object(engine, "_get_oneiric_client", return_value=client):
        assert await engine.discover_from_oneiric_mcp() == []

    with patch.object(engine, "_get_oneiric_client", return_value=client):
        cached = await engine.discover_from_oneiric_mcp()
    assert cached == []

    engine.invalidate_cache_for_source("oneiric_mcp")
    client.list_adapters = AsyncMock(side_effect=RuntimeError("generic"))
    with patch.object(engine, "_get_oneiric_client", return_value=client):
        assert await engine.discover_from_oneiric_mcp() == []


@pytest.mark.asyncio
async def test_close_handles_client_close_error() -> None:
    engine = AdapterDiscoveryEngine()
    client = MagicMock()
    client.close = AsyncMock(side_effect=RuntimeError("close failed"))
    engine._oneiric_client = client
    await engine.close()
    assert engine._oneiric_client is None


@pytest.mark.asyncio
async def test_discover_from_entry_points_outer_exception_re_raises() -> None:
    engine = AdapterDiscoveryEngine()
    with patch("importlib.metadata.entry_points", side_effect=RuntimeError("metadata failed")):
        with pytest.raises(RuntimeError, match="metadata failed"):
            await engine.discover_from_entry_points()


@pytest.mark.asyncio
async def test_discover_from_entry_points_inner_generic_exception_branch() -> None:
    engine = AdapterDiscoveryEngine({"allowlist_patterns": ["mahavishnu.adapters.*"]})
    eps = [_FakeEP("ok", lambda: _meta("mahavishnu.adapters.ok"))]
    with (
        patch("importlib.metadata.entry_points", return_value=eps),
        patch.object(engine, "_is_adapter_allowed", side_effect=RuntimeError("allowlist error")),
    ):
        result = await engine.discover_from_entry_points()
    assert result == []
