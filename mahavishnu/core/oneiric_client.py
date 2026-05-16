"""Dhara-backed adapter registry client.

The former ``oneiric_mcp`` gRPC package has been folded into Dhara's canonical
FastMCP surface. This module keeps the historic class names as compatibility
aliases while routing adapter discovery through Dhara MCP tools.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .dhara_adapter import DharaClient

logger = logging.getLogger(__name__)
_dhara_clients: dict[tuple[str, str | None], DharaClient] = {}
_default_dhara_base_url = "http://localhost:8683/mcp"


def get_dhara_client(base_url: str | None = None, token: str | None = None) -> DharaClient:
    """Return a cached Dhara MCP client."""
    from .dhara_adapter import DharaClient

    resolved_base_url = (base_url or _default_dhara_base_url).rstrip("/")
    cache_key = (resolved_base_url, token)
    client = _dhara_clients.get(cache_key)
    if client is None:
        client = DharaClient(base_url=resolved_base_url, token=token)
        _dhara_clients[cache_key] = client
    return client


def set_dhara_client_base_url(base_url: str) -> None:
    """Set the default Dhara MCP URL used by get_dhara_client()."""
    global _default_dhara_base_url
    _default_dhara_base_url = base_url.rstrip("/")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


@dataclass
class AdapterEntry:
    """Normalized adapter entry returned from Dhara's adapter registry."""

    adapter_id: str
    project: str
    domain: str
    category: str
    provider: str
    capabilities: list[str]
    factory_path: str
    health_check_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: datetime | None = None
    last_heartbeat: datetime | None = None
    health_status: str = "unknown"

    @classmethod
    def from_dhara(cls, adapter: dict[str, Any]) -> AdapterEntry:
        """Create an entry from Dhara's adapter registry schema."""
        metadata = dict(adapter.get("metadata") or {})
        domain = str(adapter.get("domain") or "")
        key = str(adapter.get("key") or metadata.get("key") or metadata.get("category") or "")
        provider = str(adapter.get("provider") or "")
        adapter_id = str(adapter.get("adapter_id") or f"{domain}:{key}:{provider}")
        category = str(metadata.get("category") or key)

        return cls(
            adapter_id=adapter_id,
            project=str(metadata.get("project") or "mahavishnu"),
            domain=domain,
            category=category,
            provider=provider,
            capabilities=list(adapter.get("capabilities") or []),
            factory_path=str(adapter.get("factory_path") or ""),
            health_check_url=adapter.get("health_check_url"),
            metadata=metadata,
            registered_at=_parse_datetime(
                adapter.get("created_at") or adapter.get("registered_at")
            ),
            last_heartbeat=_parse_datetime(
                adapter.get("last_health_check") or adapter.get("last_heartbeat")
            ),
            health_status=str(adapter.get("health_status") or "unknown"),
        )

    @classmethod
    def from_pb2(cls, pb2_entry: Any) -> AdapterEntry:
        """Compatibility converter for old tests and fixtures."""
        return cls(
            adapter_id=pb2_entry.adapter_id,
            project=pb2_entry.project,
            domain=pb2_entry.domain,
            category=pb2_entry.category,
            provider=pb2_entry.provider,
            capabilities=list(pb2_entry.capabilities),
            factory_path=pb2_entry.factory_path,
            health_check_url=pb2_entry.health_check_url or None,
            metadata=dict(pb2_entry.metadata),
            registered_at=_parse_datetime(pb2_entry.registered_at),
            last_heartbeat=_parse_datetime(pb2_entry.last_heartbeat),
            health_status=pb2_entry.health_status,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "adapter_id": self.adapter_id,
            "project": self.project,
            "domain": self.domain,
            "category": self.category,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "factory_path": self.factory_path,
            "health_check_url": self.health_check_url,
            "metadata": self.metadata,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "health_status": self.health_status,
        }


@dataclass
class DharaAdapterRegistryConfig:
    """Configuration for Dhara adapter registry discovery."""

    enabled: bool = True
    base_url: str | None = None
    timeout_sec: int = 30
    cache_ttl_sec: int = 300
    token: str | None = None


OneiricMCPConfig = DharaAdapterRegistryConfig


class AdapterCircuitBreaker:
    """Circuit breaker for failing adapters."""

    def __init__(self, failure_threshold: int = 3, block_duration_sec: int = 300):
        self.failure_threshold = failure_threshold
        self.block_duration_sec = block_duration_sec
        self.failures: dict[str, int] = {}
        self.blocked_until: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def is_available(self, adapter_id: str) -> bool:
        """Check if adapter is available."""
        async with self._lock:
            if adapter_id in self.blocked_until:
                if datetime.now(UTC) < self.blocked_until[adapter_id]:
                    return False
                del self.blocked_until[adapter_id]
                self.failures.pop(adapter_id, None)
        return True

    async def record_success(self, adapter_id: str) -> None:
        """Record successful adapter call."""
        async with self._lock:
            self.failures.pop(adapter_id, None)
            self.blocked_until.pop(adapter_id, None)

    async def record_failure(self, adapter_id: str) -> None:
        """Record adapter failure and potentially block it."""
        async with self._lock:
            self.failures[adapter_id] = self.failures.get(adapter_id, 0) + 1
            if self.failures[adapter_id] >= self.failure_threshold:
                self.blocked_until[adapter_id] = datetime.now(UTC) + timedelta(
                    seconds=self.block_duration_sec
                )


class DharaAdapterRegistryClient:
    """Async client for Dhara's adapter registry MCP tools."""

    def __init__(self, config: DharaAdapterRegistryConfig | None = None):
        self.config = config or DharaAdapterRegistryConfig()
        self._client = get_dhara_client(self.config.base_url, self.config.token)
        self._circuit_breaker = AdapterCircuitBreaker()
        self._cache: dict[str, tuple[list[AdapterEntry], datetime]] = {}
        self._connected = False
        logger.info(
            "Dhara adapter registry client initialized (base_url=%s)", self._client.base_url
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self.config.enabled:
            raise ConnectionError("Dhara adapter registry client disabled")
        try:
            result = await self._client.call_tool(name, arguments)
            self._connected = True
            return result
        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"Dhara adapter registry unavailable: {exc}") from exc

    def _make_cache_key(
        self,
        project: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = False,
    ) -> str:
        parts = [
            project or "*",
            domain or "*",
            category or "*",
            "healthy" if healthy_only else "all",
        ]
        return ":".join(parts)

    async def list_adapters(
        self,
        project: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = False,
        use_cache: bool = True,
    ) -> list[AdapterEntry]:
        """List adapters from Dhara with optional local filtering."""
        if not self.config.enabled:
            return []

        cache_key = self._make_cache_key(project, domain, category, healthy_only)
        if use_cache and cache_key in self._cache:
            adapters, cached_at = self._cache[cache_key]
            if (datetime.now(UTC) - cached_at).total_seconds() < self.config.cache_ttl_sec:
                return adapters
            del self._cache[cache_key]

        payload = await self._call_tool(
            "list_adapters",
            {"domain": domain, "category": category},
        )
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ConnectionError(payload.get("error") or "Dhara list_adapters failed")

        raw_adapters = payload.get("adapters", []) if isinstance(payload, dict) else []  # type: ignore[var-annotated]
        adapters = [AdapterEntry.from_dhara(a) for a in raw_adapters if isinstance(a, dict)]

        if project:
            adapters = [a for a in adapters if a.project == project]
        if healthy_only:
            adapters = [a for a in adapters if a.health_status == "healthy"]

        self._cache[cache_key] = (adapters, datetime.now(UTC))
        return adapters

    async def get_adapter(self, adapter_id: str) -> AdapterEntry | None:
        """Get a specific adapter by Dhara adapter ID."""
        if not self.config.enabled:
            return None
        if not await self._circuit_breaker.is_available(adapter_id):
            return None

        try:
            domain, key, provider = _split_adapter_id(adapter_id)
            payload = await self._call_tool(
                "get_adapter",
                {"domain": domain, "key": key, "provider": provider},
            )
            if not isinstance(payload, dict) or not payload.get("success"):
                await self._circuit_breaker.record_failure(adapter_id)
                return None
            await self._circuit_breaker.record_success(adapter_id)
            return AdapterEntry.from_dhara(payload["adapter"])
        except ValueError:
            for adapter in await self.list_adapters(use_cache=False):
                if adapter.adapter_id == adapter_id:
                    return adapter
            return None
        except ConnectionError:
            await self._circuit_breaker.record_failure(adapter_id)
            raise
        except Exception:
            await self._circuit_breaker.record_failure(adapter_id)
            return None

    async def check_adapter_health(self, adapter_id: str) -> bool:
        """Check adapter health through Dhara."""
        if not self.config.enabled:
            return False
        if not await self._circuit_breaker.is_available(adapter_id):
            return False

        try:
            domain, key, provider = _split_adapter_id(adapter_id)
            payload = await self._call_tool(
                "get_adapter_health",
                {"domain": domain, "key": key, "provider": provider},
            )
            healthy = bool(
                isinstance(payload, dict)
                and payload.get("success")
                and payload.get("health", {}).get("healthy")
            )
            if healthy:
                await self._circuit_breaker.record_success(adapter_id)
            else:
                await self._circuit_breaker.record_failure(adapter_id)
            return healthy
        except Exception:
            await self._circuit_breaker.record_failure(adapter_id)
            return False

    async def resolve_adapter(
        self,
        domain: str,
        category: str,
        provider: str,
        project: str | None = None,
        healthy_only: bool = True,
    ) -> AdapterEntry | None:
        """Resolve best matching adapter."""
        adapters = await self.list_adapters(
            domain=domain,
            category=category,
            project=project,
            healthy_only=healthy_only,
        )
        for adapter in adapters:
            if adapter.provider == provider:
                return adapter
        return None

    async def send_heartbeat(self, adapter_id: str) -> bool:
        """Compatibility method; Dhara has no adapter heartbeat tool."""
        return await self.get_adapter(adapter_id) is not None

    async def invalidate_cache(self) -> None:
        """Invalidate all cached adapter lists."""
        self._cache.clear()

    async def health_check(self) -> dict[str, Any]:
        """Check Dhara registry health and contract availability."""
        if not self.config.enabled:
            return {"status": "disabled", "connected": False}
        try:
            contract = await self._call_tool("get_contract_info", {})
            adapters = await self.list_adapters(use_cache=False)
            return {
                "status": "healthy",
                "connected": True,
                "adapter_count": len(adapters),
                "cache_entries": len(self._cache),
                "contract": contract,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(exc),
            }

    async def close(self) -> None:
        """Mark the shared Dhara client as disconnected."""
        self._connected = False


def _split_adapter_id(adapter_id: str) -> tuple[str, str, str]:
    parts = adapter_id.split(":")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"Invalid Dhara adapter_id: {adapter_id}")
    return parts[0], parts[1], parts[2]


OneiricMCPClient = DharaAdapterRegistryClient
