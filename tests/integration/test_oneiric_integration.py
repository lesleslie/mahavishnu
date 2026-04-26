"""Integration tests for the Dhara-backed adapter registry client.

The filename is retained for compatibility with existing test selectors. The
former ``oneiric_mcp`` package has been absorbed into Dhara's adapter registry
MCP surface.

Run live-service tests:
    MAHAVISHNU_DHARA_INTEGRATION=1 \
    MAHAVISHNU_DHARA_REGISTRY_URL=http://localhost:8683/mcp \
    uv run pytest tests/integration/test_oneiric_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from mahavishnu.core.oneiric_client import (
    AdapterEntry,
    DharaAdapterRegistryClient,
    DharaAdapterRegistryConfig,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("MAHAVISHNU_DHARA_INTEGRATION") != "1",
        reason="set MAHAVISHNU_DHARA_INTEGRATION=1 to run live Dhara registry tests",
    ),
]


def _config(timeout_sec: int = 5, cache_ttl_sec: int = 300) -> DharaAdapterRegistryConfig:
    return DharaAdapterRegistryConfig(
        enabled=True,
        base_url=os.getenv("MAHAVISHNU_DHARA_REGISTRY_URL", "http://localhost:8683/mcp"),
        timeout_sec=timeout_sec,
        cache_ttl_sec=cache_ttl_sec,
        token=os.getenv("MAHAVISHNU_DHARA_TOKEN"),
    )


class TestDharaAdapterRegistryIntegration:
    """Integration tests with a real Dhara MCP adapter registry."""

    async def test_health_check(self) -> None:
        client = DharaAdapterRegistryClient(_config())

        try:
            health = await client.health_check()

            assert "status" in health
            assert "connected" in health
            assert "adapter_count" in health
        finally:
            await client.close()

    async def test_list_all_adapters(self) -> None:
        client = DharaAdapterRegistryClient(_config())

        try:
            adapters = await client.list_adapters()

            assert isinstance(adapters, list)
            for adapter in adapters:
                assert isinstance(adapter, AdapterEntry)
                assert adapter.adapter_id
                assert adapter.domain
                assert adapter.category
                assert adapter.provider
        finally:
            await client.close()

    async def test_list_adapters_with_filters(self) -> None:
        client = DharaAdapterRegistryClient(_config())

        try:
            storage_adapters = await client.list_adapters(category="storage")

            for adapter in storage_adapters:
                assert adapter.category == "storage"
        finally:
            await client.close()

    async def test_list_adapters_caching(self) -> None:
        client = DharaAdapterRegistryClient(_config(cache_ttl_sec=60))

        try:
            adapters1 = await client.list_adapters(use_cache=True)
            cache_entries_after_first = len(client._cache)

            adapters2 = await client.list_adapters(use_cache=True)
            cache_entries_after_second = len(client._cache)

            assert adapters1 == adapters2
            assert cache_entries_after_first == cache_entries_after_second

            await client.invalidate_cache()
            assert len(client._cache) == 0
        finally:
            await client.close()

    async def test_resolve_adapter(self) -> None:
        client = DharaAdapterRegistryClient(_config())

        try:
            adapter = await client.resolve_adapter(
                domain="adapter",
                category="storage",
                provider="s3",
                healthy_only=False,
            )

            if adapter:
                assert adapter.domain == "adapter"
                assert adapter.category == "storage"
                assert adapter.provider == "s3"
                assert adapter.adapter_id is not None
        finally:
            await client.close()

    async def test_adapter_entry_serialization(self) -> None:
        client = DharaAdapterRegistryClient(_config())

        try:
            adapters = await client.list_adapters()

            if adapters:
                adapter_dict = adapters[0].to_dict()

                assert "adapter_id" in adapter_dict
                assert "project" in adapter_dict
                assert "domain" in adapter_dict
                assert "category" in adapter_dict
                assert "provider" in adapter_dict
                assert "capabilities" in adapter_dict
                assert "factory_path" in adapter_dict
                assert "health_status" in adapter_dict
        finally:
            await client.close()

    async def test_connection_failure(self) -> None:
        client = DharaAdapterRegistryClient(
            DharaAdapterRegistryConfig(
                enabled=True,
                base_url="http://localhost:9/mcp",
                timeout_sec=1,
            )
        )

        try:
            with pytest.raises(ConnectionError):
                await client.list_adapters(use_cache=False)
        finally:
            await client.close()
