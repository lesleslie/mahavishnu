"""Unit tests for the Dhara-backed adapter registry compatibility client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mahavishnu.core.oneiric_client import (
    AdapterEntry,
    OneiricMCPClient,
    OneiricMCPConfig,
)


class _Client:
    base_url = "http://localhost:8683/mcp"

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        if name == "list_adapters":
            return {
                "success": True,
                "adapters": [
                    {
                        "adapter_id": "adapter:storage:local",
                        "domain": "adapter",
                        "key": "storage",
                        "provider": "local",
                        "factory_path": "x.y:factory",
                        "capabilities": ["read", "write"],
                        "metadata": {"category": "storage", "project": "mahavishnu"},
                        "health_status": "healthy",
                    }
                ],
            }
        if name == "get_adapter":
            return {
                "success": True,
                "adapter": {
                    "adapter_id": "adapter:storage:local",
                    "domain": "adapter",
                    "key": "storage",
                    "provider": "local",
                    "factory_path": "x.y:factory",
                    "capabilities": ["read"],
                    "metadata": {"category": "storage"},
                },
            }
        if name == "get_adapter_health":
            return {"success": True, "health": {"healthy": True}}
        if name == "get_contract_info":
            return {"ok": True}
        raise AssertionError(name)


def test_adapter_entry_from_pb2_compatibility() -> None:
    pb2_entry = SimpleNamespace(
        adapter_id="test.adapter.storage.s3",
        project="test",
        domain="adapter",
        category="storage",
        provider="s3",
        capabilities=["read", "write"],
        factory_path="test.adapters.S3Adapter",
        health_check_url="http://example.com/health",
        metadata={"region": "us-east-1"},
        registered_at=1234567890,
        last_heartbeat=1234567890,
        health_status="healthy",
    )

    entry = AdapterEntry.from_pb2(pb2_entry)
    assert entry.adapter_id == "test.adapter.storage.s3"
    assert entry.category == "storage"
    assert entry.to_dict()["metadata"] == {"region": "us-east-1"}


@pytest.mark.asyncio
async def test_client_dhara_tool_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    import mahavishnu.core.oneiric_client as module

    monkeypatch.setattr(module, "get_dhara_client", lambda _base_url=None, _token=None: _Client())
    client = OneiricMCPClient(OneiricMCPConfig(enabled=True))

    adapters = await client.list_adapters(category="storage")
    assert len(adapters) == 1
    assert adapters[0].adapter_id == "adapter:storage:local"

    adapter = await client.get_adapter("adapter:storage:local")
    assert adapter is not None
    assert await client.check_adapter_health("adapter:storage:local") is True
    assert await client.resolve_adapter("adapter", "storage", "local") is not None
    assert (await client.health_check())["status"] == "healthy"


def test_config_defaults() -> None:
    config = OneiricMCPConfig()
    assert config.enabled is True
    assert config.base_url is None
    assert config.cache_ttl_sec == 300


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_none_returns_none(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        assert _parse_datetime(None) is None

    def test_datetime_passthrough(self) -> None:
        from datetime import UTC, datetime

        from mahavishnu.core.oneiric_client import _parse_datetime

        dt = datetime(2026, 1, 1, tzinfo=UTC)
        assert _parse_datetime(dt) is dt

    def test_int_timestamp(self) -> None:
        from datetime import UTC

        from mahavishnu.core.oneiric_client import _parse_datetime

        result = _parse_datetime(1700000000)
        assert result is not None
        assert result.tzinfo is UTC
        assert result.year == 2023

    def test_float_timestamp(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        result = _parse_datetime(1700000000.5)
        assert result is not None

    def test_iso_string_with_z(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        result = _parse_datetime("2026-04-24T12:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_iso_string_with_offset(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        result = _parse_datetime("2026-04-24T12:00:00+00:00")
        assert result is not None

    def test_iso_string_no_tz_gets_utc(self) -> None:
        from datetime import UTC

        from mahavishnu.core.oneiric_client import _parse_datetime

        result = _parse_datetime("2026-04-24T12:00:00")
        assert result is not None
        assert result.tzinfo is UTC

    def test_invalid_string_returns_none(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        assert _parse_datetime("not-a-date") is None

    def test_unsupported_type_returns_none(self) -> None:
        from mahavishnu.core.oneiric_client import _parse_datetime

        assert _parse_datetime([1, 2, 3]) is None


# ---------------------------------------------------------------------------
# get_dhara_client / set_dhara_client_base_url
# ---------------------------------------------------------------------------


class TestDharaClientHelpers:
    def test_get_dhara_client_caches(self) -> None:
        from types import ModuleType, SimpleNamespace
        from unittest.mock import MagicMock, patch

        import mahavishnu.core.oneiric_client as mod

        fake_client = SimpleNamespace(base_url="http://example.com/mcp")
        mock_dhara = MagicMock(return_value=fake_client)
        mock_module = ModuleType("mahavishnu.core.dhara_adapter")
        mock_module.DharaClient = mock_dhara

        with (
            patch.object(mod, "_dhara_clients", {}),
            patch.dict("sys.modules", {"mahavishnu.core.dhara_adapter": mock_module}),
        ):
            c1 = mod.get_dhara_client("http://example.com/mcp")
            c2 = mod.get_dhara_client("http://example.com/mcp")
            assert c1 is c2
            mock_dhara.assert_called_once_with(base_url="http://example.com/mcp", token=None)

    def test_get_dhara_client_default_url(self) -> None:
        from types import ModuleType, SimpleNamespace
        from unittest.mock import MagicMock, patch

        import mahavishnu.core.oneiric_client as mod

        fake_client = SimpleNamespace(base_url="http://default:8683/mcp")
        mock_dhara = MagicMock(return_value=fake_client)
        mock_module = ModuleType("mahavishnu.core.dhara_adapter")
        mock_module.DharaClient = mock_dhara

        with (
            patch.object(mod, "_dhara_clients", {}),
            patch.object(mod, "_default_dhara_base_url", "http://default:8683/mcp"),
            patch.dict("sys.modules", {"mahavishnu.core.dhara_adapter": mock_module}),
        ):
            c = mod.get_dhara_client()
            assert c.base_url == "http://default:8683/mcp"

    def test_get_dhara_client_with_token(self) -> None:
        from types import ModuleType, SimpleNamespace
        from unittest.mock import MagicMock, patch

        import mahavishnu.core.oneiric_client as mod

        fake_client = SimpleNamespace(base_url="http://example.com/mcp")
        mock_dhara = MagicMock(return_value=fake_client)
        mock_module = ModuleType("mahavishnu.core.dhara_adapter")
        mock_module.DharaClient = mock_dhara

        with (
            patch.object(mod, "_dhara_clients", {}),
            patch.dict("sys.modules", {"mahavishnu.core.dhara_adapter": mock_module}),
        ):
            mod.get_dhara_client("http://example.com/mcp", token="secret")
            mock_dhara.assert_called_once_with(base_url="http://example.com/mcp", token="secret")

    def test_set_dhara_client_base_url(self) -> None:
        import mahavishnu.core.oneiric_client as mod

        original = mod._default_dhara_base_url
        try:
            mod.set_dhara_client_base_url("http://new:8683/mcp")
            assert mod._default_dhara_base_url == "http://new:8683/mcp"
        finally:
            mod._default_dhara_base_url = original


# ---------------------------------------------------------------------------
# _split_adapter_id
# ---------------------------------------------------------------------------


class TestSplitAdapterId:
    def test_valid_three_part(self) -> None:
        from mahavishnu.core.oneiric_client import _split_adapter_id

        d, k, p = _split_adapter_id("adapter:storage:local")
        assert d == "adapter"
        assert k == "storage"
        assert p == "local"

    def test_invalid_two_part_raises(self) -> None:
        from mahavishnu.core.oneiric_client import _split_adapter_id

        with pytest.raises(ValueError, match="Invalid Dhara adapter_id"):
            _split_adapter_id("adapter:storage")

    def test_invalid_empty_part_raises(self) -> None:
        from mahavishnu.core.oneiric_client import _split_adapter_id

        with pytest.raises(ValueError, match="Invalid Dhara adapter_id"):
            _split_adapter_id("adapter::local")


# ---------------------------------------------------------------------------
# AdapterEntry.from_dhara
# ---------------------------------------------------------------------------


class TestAdapterEntryFromDhara:
    def test_minimal_dict(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterEntry

        entry = AdapterEntry.from_dhara({"domain": "adapter", "key": "storage"})
        assert entry.domain == "adapter"
        assert entry.category == "storage"
        assert entry.provider == ""
        assert entry.project == "mahavishnu"

    def test_full_dict(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterEntry

        entry = AdapterEntry.from_dhara(
            {
                "adapter_id": "a:b:c",
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "capabilities": ["read", "write"],
                "factory_path": "mymod.RedisFactory",
                "health_check_url": "http://localhost/health",
                "metadata": {"category": "cache", "project": "myproj"},
                "created_at": "2026-04-24T12:00:00Z",
                "last_heartbeat": 1700000000,
                "health_status": "healthy",
            }
        )
        assert entry.adapter_id == "a:b:c"
        assert entry.category == "cache"
        assert entry.project == "myproj"
        assert entry.registered_at is not None
        assert entry.last_heartbeat is not None
        assert entry.health_status == "healthy"

    def test_metadata_category_fallback(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterEntry

        entry = AdapterEntry.from_dhara(
            {
                "metadata": {"category": "storage"},
            }
        )
        assert entry.category == "storage"

    def test_adapter_id_generated_from_parts(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterEntry

        entry = AdapterEntry.from_dhara(
            {
                "domain": "service",
                "key": "email",
                "provider": "smtp",
            }
        )
        assert entry.adapter_id == "service:email:smtp"


# ---------------------------------------------------------------------------
# AdapterCircuitBreaker
# ---------------------------------------------------------------------------


class TestAdapterCircuitBreaker:
    async def test_initially_available(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterCircuitBreaker

        cb = AdapterCircuitBreaker()
        assert await cb.is_available("test") is True

    async def test_record_success_clears_failures(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterCircuitBreaker

        cb = AdapterCircuitBreaker()
        await cb.record_failure("test")
        await cb.record_failure("test")
        await cb.record_success("test")
        assert "test" not in cb.failures
        assert await cb.is_available("test") is True

    async def test_blocks_after_threshold(self) -> None:
        from mahavishnu.core.oneiric_client import AdapterCircuitBreaker

        cb = AdapterCircuitBreaker(failure_threshold=2, block_duration_sec=300)
        await cb.record_failure("test")
        await cb.record_failure("test")
        assert await cb.is_available("test") is False

    async def test_unblocks_after_block_duration(self) -> None:
        from datetime import UTC, datetime, timedelta

        from mahavishnu.core.oneiric_client import AdapterCircuitBreaker

        cb = AdapterCircuitBreaker(failure_threshold=1, block_duration_sec=1)
        await cb.record_failure("test")
        assert await cb.is_available("test") is False
        cb.blocked_until["test"] = datetime.now(UTC) - timedelta(seconds=2)
        assert await cb.is_available("test") is True
        assert "test" not in cb.failures


# ---------------------------------------------------------------------------
# DharaAdapterRegistryClient — disabled & error paths
# ---------------------------------------------------------------------------


class _FailingClient:
    base_url = "http://localhost:8683/mcp"

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        raise ConnectionError("Dhara unavailable")


class _EmptyClient:
    base_url = "http://localhost:8683/mcp"

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        return {"success": True, "adapters": [], "adapter": None}


class _ErrorPayloadClient:
    base_url = "http://localhost:8683/mcp"

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        if name == "list_adapters":
            return {"success": False, "error": "registry error"}
        if name == "get_adapter":
            return {"success": False, "error": "adapter lookup failed"}
        return {"success": True, "health": {"healthy": False}}


class _FallbackLookupClient:
    base_url = "http://localhost:8683/mcp"

    async def call_tool(self, name: str, arguments: dict):  # noqa: ANN001
        if name == "list_adapters":
            return {
                "success": True,
                "adapters": [
                    {
                        "adapter_id": "invalid-id",
                        "domain": "adapter",
                        "key": "storage",
                        "provider": "local",
                        "factory_path": "x.y:factory",
                        "capabilities": ["read"],
                        "metadata": {"category": "storage"},
                        "health_status": "healthy",
                    }
                ],
            }
        if name == "get_adapter":
            return {"success": True, "adapter": None}
        if name == "get_adapter_health":
            return {"success": True, "health": {"healthy": True}}
        if name == "get_contract_info":
            return {"ok": True}
        raise AssertionError(name)


class TestClientDisabledPaths:
    async def test_list_adapters_disabled(self) -> None:
        from mahavishnu.core.oneiric_client import (
            DharaAdapterRegistryClient,
            DharaAdapterRegistryConfig,
        )

        client = DharaAdapterRegistryClient(DharaAdapterRegistryConfig(enabled=False))
        result = await client.list_adapters()
        assert result == []

    async def test_get_adapter_disabled(self) -> None:
        from mahavishnu.core.oneiric_client import (
            DharaAdapterRegistryClient,
            DharaAdapterRegistryConfig,
        )

        client = DharaAdapterRegistryClient(DharaAdapterRegistryConfig(enabled=False))
        assert await client.get_adapter("a:b:c") is None

    async def test_check_health_disabled(self) -> None:
        from mahavishnu.core.oneiric_client import (
            DharaAdapterRegistryClient,
            DharaAdapterRegistryConfig,
        )

        client = DharaAdapterRegistryClient(DharaAdapterRegistryConfig(enabled=False))
        assert await client.check_adapter_health("a:b:c") is False

    async def test_health_check_disabled(self) -> None:
        from mahavishnu.core.oneiric_client import (
            DharaAdapterRegistryClient,
            DharaAdapterRegistryConfig,
        )

        client = DharaAdapterRegistryClient(DharaAdapterRegistryConfig(enabled=False))
        result = await client.health_check()
        assert result["status"] == "disabled"
        assert result["connected"] is False

    async def test_call_tool_disabled_raises(self) -> None:
        from mahavishnu.core.oneiric_client import (
            DharaAdapterRegistryClient,
            DharaAdapterRegistryConfig,
        )

        client = DharaAdapterRegistryClient(DharaAdapterRegistryConfig(enabled=False))
        with pytest.raises(ConnectionError, match="disabled"):
            await client._call_tool("list_adapters", {})


def _mock_get_dhara(client_cls):
    """Return a get_dhara_client that always returns an instance of client_cls."""
    return lambda base_url=None, token=None: client_cls()


class TestClientErrorPaths:
    async def test_call_tool_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_FailingClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        with pytest.raises(ConnectionError, match="unavailable"):
            await client._call_tool("list_adapters", {})
        assert client._connected is False

    async def test_list_adapters_error_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_ErrorPayloadClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        with pytest.raises(ConnectionError, match="registry error"):
            await client.list_adapters()

    async def test_get_adapter_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_FailingClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        with pytest.raises(ConnectionError):
            await client.get_adapter("adapter:storage:local")

    async def test_get_adapter_success_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_EmptyClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.get_adapter("adapter:storage:local")
        assert result is None

    async def test_get_adapter_payload_failure_records_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_ErrorPayloadClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.get_adapter("adapter:storage:local")
        assert result is None
        assert client._circuit_breaker.failures["adapter:storage:local"] == 1

    async def test_get_adapter_invalid_id_falls_back_to_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_FallbackLookupClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.get_adapter("invalid-id")
        assert result is not None
        assert result.adapter_id == "invalid-id"

    async def test_get_adapter_invalid_id_not_found_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_EmptyClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        assert await client.get_adapter("invalid-id") is None

    async def test_check_health_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_ErrorPayloadClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.check_adapter_health("adapter:storage:local")
        assert result is False

    async def test_check_health_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_FailingClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.check_adapter_health("adapter:storage:local")
        assert result is False

    async def test_get_adapter_blocked_by_circuit_breaker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))
        client._circuit_breaker.blocked_until["adapter:storage:local"] = datetime.now(
            UTC
        ) + timedelta(minutes=5)

        assert await client.get_adapter("adapter:storage:local") is None

    async def test_check_health_blocked_by_circuit_breaker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))
        client._circuit_breaker.blocked_until["adapter:storage:local"] = datetime.now(
            UTC
        ) + timedelta(minutes=5)

        assert await client.check_adapter_health("adapter:storage:local") is False

    async def test_send_heartbeat_delegates_to_get_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        assert await client.send_heartbeat("adapter:storage:local") is True

    async def test_send_heartbeat_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_EmptyClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        assert await client.send_heartbeat("adapter:storage:local") is False

    async def test_invalidate_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        await client.list_adapters()
        assert len(client._cache) > 0
        await client.invalidate_cache()
        assert len(client._cache) == 0

    async def test_health_check_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_FailingClient))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.health_check()
        assert result["status"] == "unhealthy"
        assert result["connected"] is False
        assert "error" in result

    async def test_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        await client.list_adapters()
        assert client._connected is True
        await client.close()
        assert client._connected is False

    async def test_list_adapters_with_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        config = mod.DharaAdapterRegistryConfig(enabled=True, cache_ttl_sec=300)
        client = mod.DharaAdapterRegistryClient(config)

        r1 = await client.list_adapters(use_cache=True)
        r2 = await client.list_adapters(use_cache=True)
        assert len(r1) == len(r2) == 1
        # Second call should come from cache (only 1 actual call_tool invocation)

    async def test_list_adapters_cache_expired_refreshes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        first = await client.list_adapters(use_cache=True)
        cache_key = client._make_cache_key(None, None, None, False)
        cached_adapters, _ = client._cache[cache_key]
        client._cache[cache_key] = (
            cached_adapters,
            datetime.now(UTC) - timedelta(seconds=client.config.cache_ttl_sec + 1),
        )

        second = await client.list_adapters(use_cache=True)
        assert len(first) == len(second) == 1

    async def test_list_adapters_project_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        results = await client.list_adapters(project="nonexistent")
        assert results == []

    async def test_list_adapters_healthy_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        results = await client.list_adapters(healthy_only=True)
        assert len(results) == 1

    async def test_resolve_adapter_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mahavishnu.core.oneiric_client as mod

        monkeypatch.setattr(mod, "get_dhara_client", _mock_get_dhara(_Client))
        client = mod.DharaAdapterRegistryClient(mod.DharaAdapterRegistryConfig(enabled=True))

        result = await client.resolve_adapter("adapter", "storage", "nonexistent")
        assert result is None
